# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from torchlight.cli import main
from torchlight.config import Config, ConfigError, load_config, read_config
from torchlight.diagnostics import RULES
from torchlight.files import iter_source_files

SOURCE = (
    "from pyspark.sql import SparkSession\n"
    "df = SparkSession.builder.getOrCreate().table('events')\n"
    "df.collect()\n"
    "df.coalesce(1).write.parquet(path)\n"
)


class ProjectFiles(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.write("pyproject.toml", "")

    def write(self, name, source):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def configure(self, settings):
        return self.write("pyproject.toml", "[tool.torchlight]\n" + settings)


class ConfigTests(ProjectFiles):
    def test_defaults_are_immutable_and_preserve_existing_policy(self):
        config = load_config(cwd=self.root)
        self.assertEqual(config.enabled_rules, frozenset(RULES))
        self.assertEqual(config.exclude, ())
        self.assertEqual(config.assume_sessions, ())
        self.assertEqual(config.root, self.root)
        with self.assertRaises(FrozenInstanceError):
            config.ignore = frozenset(RULES)

    def test_load_all_supported_settings(self):
        path = self.configure(
            'select = ["TL001", "TL002", "TL001"]\n'
            'ignore = ["TL002"]\n'
            'exclude = ["generated/**", "vendor/"]\n'
            'assume-spark-session = ["spark", "session"]\n'
        )
        config = read_config(path)
        self.assertEqual(config.enabled_rules, {"TL001"})
        self.assertEqual(config.exclude, ("generated/**", "vendor/"))
        self.assertEqual(config.assume_sessions, ("spark", "session"))

    def test_empty_lists_are_valid(self):
        self.configure(
            "select = []\nignore = []\nexclude = []\nassume-spark-session = []"
        )
        self.assertEqual(load_config(cwd=self.root).enabled_rules, frozenset())

    def test_discovery_uses_cwd_not_target_and_stops_at_nearest_pyproject(self):
        self.configure('ignore = ["TL001"]')
        nested = self.write("nested/pyproject.toml", "[project]\nname = 'other'").parent
        child = nested / "src"
        child.mkdir()
        self.assertEqual(load_config(cwd=child), Config(root=nested))
        self.assertEqual(load_config(cwd=self.root).ignore, {"TL001"})

    def test_explicit_file_replaces_discovery_and_sets_its_own_root(self):
        self.configure('ignore = ["TL001"]')
        path = self.write("policy/checks.toml", '[tool.torchlight]\nselect = ["TL002"]')
        config = load_config(cwd=self.root, config_path=Path("policy/checks.toml"))
        self.assertEqual(config.enabled_rules, {"TL002"})
        self.assertEqual(config.ignore, frozenset())
        self.assertEqual(config.root, path.parent)

    def test_no_config_does_not_read_malformed_policy(self):
        self.write("pyproject.toml", "invalid [")
        self.assertEqual(
            load_config(cwd=self.root, no_config=True), Config(root=self.root)
        )

    def test_missing_project_uses_cwd(self):
        (self.root / "pyproject.toml").unlink()
        # Isolate this test from any real pyproject in the temporary directory's ancestors.
        with patch.object(Path, "exists", return_value=False):
            self.assertEqual(load_config(cwd=self.root), Config(root=self.root))

    def test_unknown_and_mistyped_settings_are_errors_with_file_context(self):
        for settings, message in (
            ('selct = ["TL001"]', "unknown setting(s): selct"),
            ('target-spark = "3.5"', "unknown setting(s): target-spark"),
            ('select = "TL001"', "select must be an array of strings"),
            ("ignore = [1]", "ignore must be an array of strings"),
            ("exclude = true", "exclude must be an array of strings"),
            ("assume-spark-session = [false]", "must be an array of strings"),
            ('select = ["TL999"]', "select: unknown rule ID(s): TL999"),
            ('ignore = ["tl001"]', "ignore: unknown rule ID(s): tl001"),
            (
                'assume-spark-session = ["spark.session"]',
                "invalid Python variable name",
            ),
            ('assume-spark-session = ["for"]', "invalid Python variable name"),
            ('assume-spark-session = [""]', "invalid Python variable name"),
            ('baseline = ""', "baseline must be a nonempty path string"),
            ('baseline = ["file.json"]', "baseline must be a nonempty path string"),
            ("baseline = false", "baseline must be a nonempty path string"),
        ):
            with self.subTest(settings=settings):
                path = self.configure(settings)
                with self.assertRaises(ConfigError) as raised:
                    load_config(cwd=self.root)
                self.assertIn(str(path), str(raised.exception))
                self.assertIn(message, str(raised.exception))

    def test_unreadable_invalid_or_non_table_config_is_an_error(self):
        for content in ("[", "tool = []", "[tool]\ntorchlight = []"):
            with self.subTest(content=content):
                path = self.write("pyproject.toml", content)
                with self.assertRaises(ConfigError):
                    read_config(path)
        path.write_bytes(b"\xff")
        with self.assertRaises(ConfigError):
            read_config(path)
        with self.assertRaises(ConfigError):
            read_config(self.root / "missing.toml")
        with patch.object(Path, "open", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(ConfigError, "denied"):
                read_config(path)

    def test_explicit_file_requires_a_torchlight_table(self):
        with self.assertRaisesRegex(
            ConfigError, r"expected a \[tool.torchlight\] table"
        ):
            load_config(cwd=self.root, config_path=Path("pyproject.toml"))

    def test_invalid_exclude_patterns_are_rejected(self):
        for pattern in (
            "",
            "/tmp/**",
            "../jobs",
            "./jobs",
            "a//b",
            "a/**b",
            "C:/jobs",
            "a\\b",
        ):
            with self.subTest(pattern=pattern):
                self.configure("exclude = [" + json.dumps(pattern) + "]")
                with self.assertRaisesRegex(ConfigError, "exclude patterns"):
                    load_config(cwd=self.root)

    def test_globs_have_portable_segment_and_subtree_semantics(self):
        cases = (
            ("generated/**", "generated/file.py", True),
            ("generated/**", "generated", True),
            ("generated/**", "jobs/generated/file.py", False),
            ("vendor/", "jobs/vendor/file.py", True),
            ("*.ipynb", "jobs/nested/analysis.ipynb", True),
            ("*.ipynb", "jobs/notebook.py", False),
            ("**/test_?.py", "test_a.py", True),
            ("**/test_?.py", "nested/test_b.py", True),
            ("**/test_?.py", "nested/test_ab.py", False),
            ("jobs/*.py", "jobs/nested/code.py", False),
            ("jobs/*.py", "jobs/code.py", True),
            ("jobs/[ab].py", "jobs/a.py", True),
            ("jobs/[ab].py", "jobs/c.py", False),
            ("jobs", "jobs/nested/code.py", True),
            ("jobs", "myjobs/code.py", False),
            ("JOBS/**", "jobs/code.py", False),
            ("**", ".", True),
        )
        for pattern, name, expected in cases:
            with self.subTest(pattern=pattern, name=name):
                config = Config(root=self.root, exclude=(pattern,))
                self.assertEqual(config.is_excluded(self.root / name), expected)

    def test_outside_project_and_parent_traversal_do_not_match(self):
        config = Config(root=self.root, exclude=("**",))
        self.assertFalse(config.is_excluded(self.root.parent / "other.py"))
        self.assertFalse(config.is_excluded(self.root / ".." / "other.py"))

    def test_trailing_slash_matches_directories_not_same_named_files(self):
        file = self.write("jobs/vendor", "")
        directory = self.root / "vendor"
        directory.mkdir()
        config = Config(root=self.root, exclude=("vendor/",))
        self.assertFalse(config.is_excluded(file))
        self.assertTrue(config.is_excluded(directory))
        self.assertTrue(config.is_excluded(directory / "code.py"))

    def test_symlink_paths_use_named_paths_not_target_paths(self):
        target = self.write(
            "policy/settings.toml", '[tool.torchlight]\nexclude = ["alias.py"]'
        )
        source = self.write("jobs/code.py", SOURCE)
        linked_policy = self.root / "linked.toml"
        alias = self.root / "alias.py"
        try:
            linked_policy.symlink_to(target)
            alias.symlink_to(source)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        config = load_config(cwd=self.root, config_path=linked_policy)
        self.assertEqual(config.root, self.root)
        self.assertTrue(config.is_excluded(alias))
        self.assertFalse(config.is_excluded(source))

    def test_root_aliases_preserve_project_relative_exclusions(self):
        self.write("generated/code.py", SOURCE)
        with tempfile.TemporaryDirectory() as directory:
            alias = Path(directory).resolve() / "project"
            try:
                alias.symlink_to(self.root, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            config = Config(root=self.root, exclude=("generated/**",))
            self.assertTrue(config.is_excluded(alias / "generated" / "code.py"))
            self.assertFalse(config.is_excluded(alias / "jobs" / "code.py"))
            self.assertTrue(Config(root=self.root, exclude=("**",)).is_excluded(alias))

    def test_excluded_directories_are_pruned_during_discovery(self):
        self.write("generated/bad.py", "?")
        good = self.write("jobs/code.py", SOURCE)
        config = Config(root=self.root, exclude=("generated/**",))
        self.assertEqual(
            list(iter_source_files(self.root, is_excluded=config.is_excluded)), [good]
        )


class ConfigCliTests(ProjectFiles):
    def run_cli(self, *arguments, cwd=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            contextlib.chdir(cwd or self.root),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = main([str(argument) for argument in arguments])
        return status, stdout.getvalue(), stderr.getvalue()

    def rule_ids(self, *arguments, cwd=None):
        status, stdout, stderr = self.run_cli("--format", "json", *arguments, cwd=cwd)
        self.assertEqual(stderr, "")
        return status, [f["rule_id"] for f in json.loads(stdout)["findings"]]

    def test_directory_hook_style_and_ci_scans_share_one_policy(self):
        self.configure(
            'select = ["TL001", "TL002"]\nignore = ["TL002"]\nexclude = ["generated/**"]'
        )
        job = self.write("jobs/code.py", SOURCE)
        excluded = self.write("generated/bad.py", "?")
        self.write("jobs/pyproject.toml", "[tool.torchlight]\nselect = []")
        for paths in ((".",), (job, excluded), ("jobs",)):
            with self.subTest(paths=paths):
                self.assertEqual(self.rule_ids(*paths), (1, ["TL001"]))

    def test_cli_selection_and_ignore_replace_configured_lists(self):
        self.configure('select = ["TL003"]\nignore = ["TL001"]')
        job = self.write("code.py", SOURCE)
        self.assertEqual(self.rule_ids(job), (0, []))
        self.assertEqual(
            self.rule_ids("--select", "TL001,TL002", "--ignore", "TL003", job),
            (1, ["TL001", "TL002"]),
        )
        self.assertEqual(self.rule_ids("--select", "TL001,TL002", job), (1, ["TL002"]))

    def test_repeatable_cli_lists_replace_not_append(self):
        self.configure('exclude = ["code.py"]\nassume-spark-session = ["spark"]')
        job = self.write(
            "code.py", "spark.table('a').collect()\nsession.table('b').collect()"
        )
        self.assertEqual(self.rule_ids(job), (0, []))
        status, stdout, stderr = self.run_cli(
            "--format",
            "json",
            "--exclude",
            "other/**",
            "--exclude",
            "*.ipynb",
            "--assume-spark-session",
            "session",
            "--assume-spark-session",
            "extra",
            job,
        )
        self.assertEqual((status, stderr), (1, ""))
        self.assertEqual([f["line"] for f in json.loads(stdout)["findings"]], [2])

    def test_session_assumptions_flow_across_notebook_cells(self):
        self.configure('assume-spark-session = ["spark"]')
        notebook = self.write(
            "analysis.ipynb",
            json.dumps(
                {
                    "cells": [
                        {"cell_type": "code", "source": "df = spark.table('events')"},
                        {"cell_type": "code", "source": "df.collect()"},
                    ]
                }
            ),
        )
        self.assertEqual(self.rule_ids(notebook), (1, ["TL001"]))

    def test_explicit_excluded_files_and_directories_are_skipped(self):
        self.configure('exclude = ["generated/**", "*.ipynb"]')
        bad = self.write("generated/bad.py", "?")
        notebook = self.write("broken.ipynb", "invalid JSON")
        for path in (bad, bad.parent, notebook):
            self.assertEqual(self.run_cli(path), (0, "", ""))
        # A typo must still be reported rather than hidden by an exclude.
        self.assertEqual(self.run_cli("generated/missing.py")[0], 2)

    def test_explicit_config_paths_and_globs_are_relative_to_the_documented_roots(self):
        job = self.write("jobs/code.py", SOURCE)
        self.write("jobs/policy.toml", '[tool.torchlight]\nexclude = ["code.py"]')
        self.assertEqual(self.rule_ids("--config", "jobs/policy.toml", job), (0, []))
        # Config discovery follows the working directory, not the input paths.
        self.assertEqual(self.rule_ids(job), (1, ["TL001", "TL002"]))
        self.assertEqual(
            self.rule_ids("--config", "policy.toml", job, cwd=job.parent), (0, [])
        )

    def test_no_config_restores_defaults_and_cwd_relative_excludes(self):
        self.configure('select = []\nexclude = ["code.py"]')
        self.write("code.py", SOURCE)
        self.assertEqual(
            self.rule_ids("--no-config", "code.py"), (1, ["TL001", "TL002"])
        )
        self.assertEqual(
            self.rule_ids("--no-config", "--exclude", "code.py", "."), (0, [])
        )

    def test_invalid_config_aborts_before_scanning_in_every_output_format(self):
        self.configure('select = ["TL999"]')
        job = self.write("code.py", SOURCE)
        for output_format in ("text", "json", "github", "sarif"):
            with (
                self.subTest(output_format=output_format),
                patch("torchlight.cli.scan_file") as scan,
            ):
                status, stdout, stderr = self.run_cli("--format", output_format, job)
                self.assertEqual(status, 2)
                self.assertIn("configuration error", stderr)
                scan.assert_not_called()
                if output_format == "json":
                    report = json.loads(stdout)
                    self.assertEqual(report["findings"], [])
                    self.assertEqual(len(report["errors"]), 1)
                elif output_format == "github":
                    self.assertTrue(stdout.startswith("::error "))
                elif output_format == "sarif":
                    invocation = json.loads(stdout)["runs"][0]["invocations"][0]
                    self.assertFalse(invocation["executionSuccessful"])
                else:
                    self.assertEqual(stdout, "")
        self.assertEqual(self.rule_ids("--no-config", job), (1, ["TL001", "TL002"]))

    def test_invalid_cli_config_options_exit_two(self):
        for arguments in (
            ("--config", "policy.toml", "--no-config"),
            ("--exclude", "../outside"),
        ):
            with (
                self.subTest(arguments=arguments),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as raised:
                    main([*arguments, "."])
                self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
