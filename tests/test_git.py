# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from torchlight.files import scan_file, scan_source
from torchlight.git import GitComparison, GitError

SOURCE = (
    "from pyspark.sql import DataFrame\ndef export(df: DataFrame):\n    df.collect()\n"
)


@unittest.skipUnless(shutil.which("git"), "Git is required for comparison tests")
class GitTests(unittest.TestCase):
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
