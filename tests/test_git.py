# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from torchlight import Config, Scanner
from torchlight.cli import main
from torchlight.files import scan_file, scan_source
from torchlight.git import GitComparison, GitError

SOURCE = (
    "from pyspark.sql import DataFrame\ndef export(df: DataFrame):\n    df.collect()\n"
)


@unittest.skipUnless(shutil.which("git"), "Git is required for comparison tests")
class GitRepository(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.git("init", "--template=", "-b", "main")
        self.git("config", "user.name", "Torchlight Tests")
        self.git("config", "user.email", "tests@example.invalid")
        self.path = self.write("job.py", SOURCE)
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def write(self, name, source):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-m", "test snapshot")

    def compare(self, ref=None):
        return GitComparison.from_ref(self.root, ref or self.base)


class GitTests(GitRepository):
    def test_every_git_command_disables_lazy_fetching(self):
        with patch("torchlight.git.subprocess.run", wraps=subprocess.run) as run:
            self.compare()
        self.assertTrue(run.call_args_list)
        for call in run.call_args_list:
            self.assertIn("--no-lazy-fetch", call.args[0])
            self.assertEqual(call.kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")

    def test_comparison_does_not_modify_index_worktree_or_refs(self):
        self.path.write_text(SOURCE + "# changed\n", encoding="utf-8")
        index = (self.root / ".git/index").read_bytes()
        source = self.path.read_bytes()
        self.compare()
        self.assertEqual((self.root / ".git/index").read_bytes(), index)
        self.assertEqual(self.path.read_bytes(), source)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.base)

    def test_unrelated_and_ambiguous_history_are_errors(self):
        tree = self.git("rev-parse", "HEAD^{tree}").strip()
        unrelated = self.git("commit-tree", tree, "-m", "unrelated").strip()
        with self.assertRaises(GitError):
            self.compare(unrelated)
        a = self.git("commit-tree", tree, "-p", self.base, "-m", "a").strip()
        b = self.git("commit-tree", tree, "-p", self.base, "-m", "b").strip()
        one = self.git("commit-tree", tree, "-p", a, "-p", b, "-m", "one").strip()
        two = self.git("commit-tree", tree, "-p", b, "-p", a, "-m", "two").strip()
        self.git("checkout", "--detach", one)
        with self.assertRaisesRegex(GitError, "exactly one merge base"):
            self.compare(two)

    def test_unresolved_conflicts_are_errors(self):
        self.git("checkout", "-b", "feature")
        self.path.write_text("feature = 1\n", encoding="utf-8")
        self.commit()
        self.git("checkout", "main")
        self.path.write_text("main = 1\n", encoding="utf-8")
        self.commit()
        with self.assertRaises(subprocess.CalledProcessError):
            self.git("merge", "feature")
        with self.assertRaisesRegex(GitError, "unresolved merge conflict"):
            self.compare()

    def test_unchanged_checkout_has_no_changes(self):
        comparison = self.compare()
        self.assertEqual(comparison.base, self.base)
        self.assertEqual(comparison.changes, {})
        self.assertEqual(comparison.deleted, frozenset())

    def test_committed_staged_unstaged_and_untracked_changes(self):
        self.write("committed.py", SOURCE)
        self.commit()
        self.write("staged.py", SOURCE)
        self.git("add", "staged.py")
        self.path.write_text(SOURCE + "# local edit\n", encoding="utf-8")
        self.write("untracked.py", SOURCE)
        comparison = self.compare()
        self.assertEqual(
            set(comparison.changes),
            {"job.py", "committed.py", "staged.py", "untracked.py"},
        )
        self.assertEqual(comparison.previous_source("job.py"), SOURCE.encode())
        for name in ("committed.py", "staged.py", "untracked.py"):
            self.assertIsNone(comparison.previous_source(name))

    def test_uses_merge_base_not_target_tip(self):
        self.git("checkout", "-b", "feature")
        self.write("feature.py", SOURCE)
        self.commit()
        self.git("checkout", "main")
        self.write("main-only.py", SOURCE)
        self.commit()
        self.git("checkout", "feature")
        comparison = self.compare("main")
        self.assertEqual(comparison.base, self.base)
        self.assertEqual(set(comparison.changes), {"feature.py"})

    def test_staged_rename_keeps_original_blob_and_deleted_name(self):
        self.git("mv", "job.py", "renamed.py")
        comparison = self.compare()
        self.assertEqual(set(comparison.changes), {"renamed.py"})
        self.assertEqual(comparison.deleted, {"job.py"})
        self.assertEqual(comparison.previous_source("renamed.py"), SOURCE.encode())

    def test_unstaged_move_is_conservatively_new(self):
        self.path.rename(self.root / "renamed.py")
        comparison = self.compare()
        self.assertEqual(comparison.deleted, {"job.py"})
        self.assertIsNone(comparison.previous_source("renamed.py"))

    def test_deleted_and_ignored_files(self):
        self.path.unlink()
        self.write(".gitignore", "ignored.py\n")
        self.write("ignored.py", SOURCE)
        comparison = self.compare()
        self.assertEqual(comparison.deleted, {"job.py"})
        self.assertNotIn("ignored.py", comparison.changes)

    def test_nul_delimited_paths_preserve_spaces_unicode_and_newlines(self):
        names = ["space name.py", "café.py", "-option.py"]
        if os.name != "nt":
            names.append("line\nbreak.py")
        for name in names:
            self.write(name, SOURCE)
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        for name in names:
            self.write(name, SOURCE + "# changed\n")
        comparison = self.compare()
        self.assertEqual(set(comparison.changes), set(names))
        for name in names:
            self.assertEqual(comparison.previous_source(name), SOURCE.encode())

    def test_shallow_clone_is_rejected_with_recovery_advice(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "clone"
            self.git("clone", "--depth=1", self.root.as_uri(), str(clone))
            with self.assertRaisesRegex(GitError, "shallow.*fetch-depth"):
                GitComparison.from_ref(clone, "HEAD")

    def test_invalid_revisions_and_non_repository_are_errors(self):
        for ref in ("missing", "--help", "HEAD:path"):
            with self.subTest(ref=ref), self.assertRaises(GitError):
                self.compare(ref)
        for ref in ("", " ", "bad\x00ref"):
            with self.assertRaises(ValueError):
                GitComparison.from_ref(self.root, ref)
        with self.assertRaises(TypeError):
            GitComparison.from_ref(self.root, 1)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(GitError):
                GitComparison.from_ref(Path(directory), "HEAD")

    def test_missing_git_and_timeout_become_errors(self):
        for error in (
            FileNotFoundError("git unavailable"),
            subprocess.TimeoutExpired("git", 60),
        ):
            with patch("torchlight.git.subprocess.run", side_effect=error):
                with self.assertRaises(GitError):
                    self.compare()

    def test_repository_helpers_and_source_are_never_executed(self):
        marker = self.root / "executed"
        command = "echo executed > executed"
        self.git("config", "filter.test.clean", command)
        self.git("config", "filter.test.process", command)
        self.git("config", "filter.test.required", "true")
        self.git("config", "diff.test.command", command)
        self.git("config", "diff.test.textconv", command)
        self.git("config", "core.fsmonitor", command)
        self.write(".gitattributes", "*.py filter=test diff=test\n")
        self.path.write_text(
            SOURCE + "raise RuntimeError('never execute')\n", encoding="utf-8"
        )
        comparison = self.compare()
        self.assertEqual(comparison.previous_source("job.py"), SOURCE.encode())
        self.assertFalse(marker.exists())

    def test_memory_source_matches_file_scanning_and_errors(self):
        for name, text in (
            ("job.py", SOURCE),
            ("job.py", "?"),
            (
                "job.ipynb",
                json.dumps({"cells": [{"cell_type": "code", "source": SOURCE}]}),
            ),
            ("job.ipynb", "["),
            ("job.ipynb", '{"cells": [null]}'),
        ):
            path = self.root / name
            data = ("\ufeff" + text.replace("\n", "\r\n")).encode("utf-8")
            path.write_bytes(data)
            self.assertEqual(scan_source(path, data), scan_file(path))
        for suffix in ("py", "ipynb"):
            path = self.root / f"bad.{suffix}"
            path.write_bytes(b"\xff")
            self.assertEqual(scan_source(path, b"\xff"), scan_file(path))


class ComparisonTests(GitRepository):
    def test_databricks_source_mapping_and_tl005_comparison(self):
        setup = "# Databricks notebook source\nfrom pyspark.sql import SparkSession\ndf = SparkSession.builder.getOrCreate().table('events')\n"
        cell = "# COMMAND ----------\n# MAGIC %python\n# MAGIC list(df.toLocalIterator())\n"
        self.path.write_text(setup + cell, encoding="utf-8")
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        shifted = setup + "# COMMAND ----------\n# inserted cell\n" + cell
        self.path.write_text(shifted, encoding="utf-8")
        self.assertEqual(self.scan().exit_code, 0)
        self.path.write_text(shifted + cell, encoding="utf-8")
        report = self.scan()
        self.assertEqual(report.errors, ())
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].rule_id, "TL005")
        self.assertEqual(report.findings[0].location.cell, 4)
        self.assertEqual(report.findings[0].location.line, 11)

    def scan(self, paths=None, **policy):
        return Scanner(Config(root=self.root, **policy)).scan(
            self.root if paths is None else paths, changed_from=self.base
        )

    def cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            contextlib.chdir(self.root),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = main([str(arg) for arg in args])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_only_new_findings_and_net_new_duplicates_are_reported(self):
        self.path.write_text(
            "\n# header\n" + SOURCE.replace("df.collect()", "df.collect( )"),
            encoding="utf-8",
        )
        self.assertEqual(self.scan().exit_code, 0)
        self.path.write_text(
            SOURCE + "    df.collect()\n    df.toPandas()\n", encoding="utf-8"
        )
        report = self.scan([self.path, self.root])
        self.assertEqual(report.errors, ())
        self.assertEqual([f.location.line for f in report.findings], [4, 5])
        self.assertEqual(report.exit_code, 1)

    def test_changed_file_is_analyzed_whole_not_only_added_lines(self):
        self.path.write_text(
            SOURCE.replace("df.collect()", "df.limit(1).collect()"), encoding="utf-8"
        )
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        self.path.write_text(SOURCE, encoding="utf-8")
        self.assertEqual(len(self.scan().findings), 1)

    def test_committed_staged_and_untracked_source_is_scanned(self):
        self.write("committed.py", SOURCE)
        self.commit()
        self.write("staged.py", SOURCE)
        self.git("add", "staged.py")
        self.write("untracked.py", SOURCE)
        report = self.scan()
        self.assertEqual(report.errors, ())
        self.assertEqual(
            [Path(f.path).name for f in report.findings],
            ["committed.py", "staged.py", "untracked.py"],
        )

    def test_rename_matches_old_findings_but_not_additions(self):
        self.git("mv", "job.py", "renamed.py")
        self.assertEqual(self.scan().exit_code, 0)
        renamed = self.root / "renamed.py"
        renamed.write_text(SOURCE + "    df.toPandas()\n", encoding="utf-8")
        report = self.scan(renamed)
        self.assertEqual(report.errors, ())
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].path, str(renamed))
        self.assertIn("toPandas", report.findings[0].message)

    def test_moves_from_non_source_or_excluded_paths_are_new(self):
        for name in ("notes.txt", "generated/old.py"):
            self.write(name, SOURCE)
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("mv", "notes.txt", "new.py")
        self.git("mv", "generated/old.py", "moved.py")
        report = self.scan(exclude=("generated/**",))
        self.assertEqual(report.errors, ())
        self.assertEqual(
            {Path(f.path).name for f in report.findings}, {"new.py", "moved.py"}
        )

    def test_deleted_files_are_skipped_but_missing_inputs_are_errors(self):
        self.path.unlink()
        self.assertEqual(self.scan().exit_code, 0)
        self.assertEqual(self.scan(self.path).exit_code, 0)
        report = self.scan(self.root / "missing.py")
        self.assertEqual(report.exit_code, 2)
        self.assertIn("no such file", report.errors[0])

    def test_current_policy_selection_excludes_and_suppressions_apply(self):
        self.write("new.py", SOURCE + "    df.repartition(1).write.csv('out')\n")
        self.write("generated/bad.py", "?")
        self.write(
            "suppressed.py",
            SOURCE.replace(
                "df.collect()",
                "df.collect() # torchlight: ignore[TL001] -- reviewed small export",
            ),
        )
        report = self.scan(select={"TL004"}, exclude=("generated/**",))
        self.assertEqual(report.errors, ())
        self.assertEqual([f.rule_id for f in report.findings], ["TL004"])
        report = self.scan(ignore={"TL004"}, exclude=("generated/**",))
        self.assertEqual([Path(f.path).name for f in report.findings], ["new.py"])

    def test_same_current_session_assumptions_apply_to_both_snapshots(self):
        self.path.write_text("spark.table('events').collect()\n", encoding="utf-8")
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        self.path.write_text(
            "spark.table('events').collect()\n# changed\n", encoding="utf-8"
        )
        self.assertEqual(self.scan(assume_sessions=("spark",)).exit_code, 0)

    def test_configuration_root_can_be_a_subdirectory(self):
        path = self.write("jobs/new.py", SOURCE)
        with contextlib.chdir(path.parent):
            report = Scanner(Config(root=path.parent)).scan(".", changed_from=self.base)
        self.assertEqual(report.errors, ())
        self.assertEqual([f.path for f in report.findings], ["new.py"])

    def test_saved_baseline_is_ignored_and_never_written(self):
        self.write("new.py", SOURCE)
        missing = self.root / "missing-baseline.json"
        self.assertEqual(self.scan(baseline=missing).exit_code, 1)
        self.assertFalse(missing.exists())
        policy = self.write(
            "pyproject.toml", '[tool.torchlight]\nbaseline = "missing-baseline.json"\n'
        )
        status, stdout, stderr = self.cli(
            "--changed-from", self.base, "--config", policy, "."
        )
        self.assertEqual((status, stderr), (1, ""))
        self.assertIn("new.py", stdout)

    def test_cli_rejects_baseline_combinations_before_scanning(self):
        for flag in ("--baseline", "--write-baseline", "--no-baseline"):
            args = [flag] if flag == "--no-baseline" else [flag, "baseline.json"]
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()):
                with (
                    patch("torchlight.cli.Scanner.scan") as scan,
                    self.assertRaises(SystemExit) as error,
                ):
                    main([".", "--changed-from", self.base, *args])
                self.assertEqual(error.exception.code, 2)
                scan.assert_not_called()
        self.assertFalse((self.root / "baseline.json").exists())

    def test_cli_and_api_parity_in_all_formats(self):
        self.write("new.py", SOURCE)
        with contextlib.chdir(self.root):
            report = Scanner(Config(root=self.root)).scan(".", changed_from=self.base)
        for output_format in ("text", "json", "github", "sarif"):
            status, stdout, stderr = self.cli(
                ".",
                "--no-config",
                "--changed-from",
                self.base,
                "--format",
                output_format,
            )
            self.assertEqual((status, stderr), (report.exit_code, ""))
            with contextlib.chdir(self.root):
                self.assertEqual(stdout, report.render(output_format) + "\n")

    def test_base_and_current_errors_are_not_hidden(self):
        for name, old, current in (("job.py", "?", SOURCE), ("job.ipynb", "[", "{}")):
            self.write(name, old)
            self.commit()
            self.base = self.git("rev-parse", "HEAD").strip()
            self.write(name, current)
            report = self.scan(self.root / name)
            self.assertTrue(report.errors)
            self.assertIn("Git base", report.errors[0])
            self.assertEqual(report.exit_code, 1 if report.findings else 2)
        self.path.write_text("?", encoding="utf-8")
        report = self.scan(self.path)
        self.assertEqual(report.exit_code, 2)

    def test_blob_read_failure_is_an_error_and_preserves_current_findings(self):
        self.path.write_text(SOURCE + "# changed\n", encoding="utf-8")
        with patch(
            "torchlight.git.GitComparison.previous_source",
            side_effect=GitError("missing blob"),
        ):
            report = self.scan()
        self.assertEqual(report.exit_code, 1)
        self.assertIn("missing blob", report.errors[0])
        self.assertEqual(len(report.findings), 1)

    def test_unchanged_invalid_file_is_outside_comparison(self):
        self.write("invalid.py", "?")
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        self.assertEqual(self.scan().exit_code, 0)

    def test_notebook_state_cell_insertions_and_new_duplicates(self):
        cells = [
            {
                "cell_type": "code",
                "source": "from pyspark.sql import SparkSession\nspark = SparkSession.builder.getOrCreate()\ndf = spark.table('events')",
            },
            {"cell_type": "code", "source": "df.collect()"},
        ]
        path = self.write("job.ipynb", json.dumps({"cells": cells}))
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        cells.insert(1, {"cell_type": "code", "source": "# inserted cell"})
        path.write_text(
            json.dumps({"cells": cells, "metadata": {"changed": True}}),
            encoding="utf-8",
        )
        self.assertEqual(self.scan().exit_code, 0)
        cells.append({"cell_type": "code", "source": "df.collect()"})
        path.write_text(json.dumps({"cells": cells}), encoding="utf-8")
        report = self.scan()
        self.assertEqual(report.errors, ())
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].location.cell, 4)

    def test_invalid_api_refs_raise_but_git_failures_are_reports(self):
        scanner = Scanner(Config(root=self.root))
        for ref, error in (("", ValueError), ("\x00", ValueError), (True, TypeError)):
            with self.assertRaises(error):
                scanner.scan(self.root, changed_from=ref)
        status, stdout, stderr = self.cli(
            ".", "--changed-from", "missing", "--format", "json"
        )
        self.assertEqual(status, 2)
        self.assertTrue(json.loads(stdout)["errors"])
        self.assertIn("Git comparison error", stderr)
        for ref in ("", " ", "bad\x00ref"):
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                main([".", "--changed-from", ref])
            self.assertEqual(error.exception.code, 2)

    def test_unsupported_index_flags_are_errors(self):
        for flag in ("skip-worktree", "assume-unchanged"):
            self.git("update-index", f"--{flag}", "job.py")
            self.assertEqual(self.scan().exit_code, 2)
            self.git("update-index", f"--no-{flag}", "job.py")

    def test_outside_repository_inputs_are_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outside.py"
            path.write_text(SOURCE, encoding="utf-8")
            report = self.scan(path)
        self.assertEqual(report.exit_code, 2)
        self.assertIn("inside the Git repository", report.errors[0])

    def test_symlink_inputs_are_rejected_and_base_symlinks_are_not_source(self):
        link = self.root / "link.py"
        try:
            link.symlink_to("job.py")
        except OSError:
            self.skipTest("symlinks unavailable")
        self.assertEqual(self.scan(link).exit_code, 2)
        directory_link = self.root / "linked"
        directory_link.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.scan(directory_link / "job.py").exit_code, 2)
        directory_link.unlink()
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        link.unlink()
        link.write_text(SOURCE, encoding="utf-8")
        report = self.scan(link)
        self.assertEqual(report.errors, ())
        self.assertEqual(len(report.findings), 1)

    def test_nested_repository_must_be_scanned_separately(self):
        nested = self.root / "nested"
        nested.mkdir()
        self.git("init", "--template=", str(nested))
        self.write("nested/new.py", SOURCE)
        self.assertEqual(self.scan(nested).exit_code, 2)
        self.assertEqual(self.scan().exit_code, 0)
