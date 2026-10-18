# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from torchlight.baseline import (
    BaselineError,
    new_findings,
    read_baseline,
    write_baseline,
)
from torchlight.cli import main
from torchlight.files import scan_file

SOURCE = (
    "from pyspark.sql import SparkSession\n"
    "df = SparkSession.builder.getOrCreate().table('events')\n"
    "df.collect()\n"
)


class BaselineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "job.py"
        self.source.write_text(SOURCE, encoding="utf-8")
        self.baseline = self.root / ".torchlight-baseline.json"
        (self.root / "pyproject.toml").write_text("", encoding="utf-8")

    def run_cli(self, *args, cwd=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            contextlib.chdir(cwd or self.root),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = main([str(arg) for arg in args])
        return status, stdout.getvalue(), stderr.getvalue()

    def capture(self):
        status, _, stderr = self.run_cli("--write-baseline", self.baseline, ".")
        self.assertEqual((status, stderr), (0, ""))

    def test_capture_then_report_only_new_findings(self):
        self.capture()
        self.assertEqual(self.run_cli("--baseline", self.baseline, "."), (0, "", ""))
        self.source.write_text(SOURCE + "df.toPandas()\n", encoding="utf-8")
        status, stdout, stderr = self.run_cli("--baseline", self.baseline, ".")
        self.assertEqual((status, stderr), (1, ""))
        self.assertIn("toPandas", stdout)
        self.assertNotIn("from .collect()", stdout)

    def test_duplicate_counts_cannot_hide_additional_identical_calls(self):
        self.capture()
        self.source.write_text(SOURCE + "df.collect()\n", encoding="utf-8")
        status, stdout, stderr = self.run_cli(
            "--format", "json", "--baseline", self.baseline, self.source, "."
        )
        self.assertEqual((status, stderr), (1, ""))
        self.assertEqual(len(json.loads(stdout)["findings"]), 1)
        self.assertEqual(json.loads(stdout)["findings"][0]["line"], 4)

    def test_capture_is_deterministic_counts_duplicates_and_stores_no_source(self):
        self.source.write_text(SOURCE + "df.collect()", encoding="utf-8")
        self.capture()
        before = self.baseline.read_bytes()
        self.capture()
        self.assertEqual(before, self.baseline.read_bytes())
        entry = json.loads(before)["findings"][0]
        self.assertEqual(entry["path"], "job.py")
        self.assertEqual(entry["count"], 2)
        self.assertEqual(set(entry), {"path", "rule_id", "fingerprint", "count"})
        self.assertNotIn(str(self.root), before.decode())
        self.assertNotIn("SparkSession", before.decode())

    def test_formatting_and_blank_line_insertions_preserve_baseline_match(self):
        self.capture()
        self.source.write_text(
            "\n# header\n" + SOURCE.replace("df.collect()", "(df).collect( )"),
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli("--baseline", self.baseline, "."), (0, "", ""))

    def test_checkout_relocation_and_absolute_or_relative_inputs_match(self):
        self.capture()
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory).resolve()
            (other / "pyproject.toml").write_text("", encoding="utf-8")
            (other / "job.py").write_text(SOURCE, encoding="utf-8")
            (other / self.baseline.name).write_bytes(self.baseline.read_bytes())
            for target in ("job.py", other / "job.py", "."):
                self.assertEqual(
                    self.run_cli("--baseline", self.baseline.name, target, cwd=other),
                    (0, "", ""),
                )

    def test_different_files_and_renames_are_new(self):
        self.capture()
        self.source.rename(self.root / "renamed.py")
        self.assertEqual(self.run_cli("--baseline", self.baseline, ".")[0], 1)

    def test_configured_baseline_and_cli_overrides(self):
        self.capture()
        (self.root / "pyproject.toml").write_text(
            '[tool.torchlight]\nbaseline = ".torchlight-baseline.json"\n',
            encoding="utf-8",
        )
        child = self.root / "nested"
        child.mkdir()
        self.assertEqual(self.run_cli(self.source, cwd=child), (0, "", ""))
        self.assertEqual(self.run_cli("--no-baseline", self.source)[0], 1)
        self.assertEqual(self.run_cli("--no-config", self.source)[0], 1)
        empty = self.root / "empty.json"
        write_baseline(empty, [], self.root)
        self.assertEqual(self.run_cli("--baseline", empty, self.source)[0], 1)
        # Writing a replacement snapshot ignores even a missing configured input.
        self.baseline.unlink()
        self.capture()

    def test_invalid_baseline_aborts_before_scanning(self):
        self.baseline.write_text("{}", encoding="utf-8")
        with patch("torchlight.scanner.scan_file") as scan:
            status, stdout, stderr = self.run_cli(
                "--format", "json", "--baseline", self.baseline, "."
            )
        self.assertEqual(status, 2)
        scan.assert_not_called()
        self.assertIn("baseline error", stderr)
        self.assertEqual(json.loads(stdout)["findings"], [])
        self.assertEqual(len(json.loads(stdout)["errors"]), 1)

    def test_scan_errors_are_not_hidden_by_baseline(self):
        self.capture()
        status, stdout, stderr = self.run_cli(
            "--format", "json", "--baseline", self.baseline, ".", "missing.py"
        )
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(stdout)["findings"], [])
        self.assertIn("no such file", stderr)

    def test_failed_scans_never_create_or_update_baselines(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    self.capture()
                before = self.baseline.read_bytes() if existing else None
                status, _, stderr = self.run_cli(
                    "--write-baseline", self.baseline, ".", "missing.py"
                )
                self.assertEqual(status, 2)
                self.assertIn("no such file", stderr)
                self.assertEqual(
                    self.baseline.read_bytes() if self.baseline.exists() else None,
                    before,
                )

    def test_unrelated_files_and_symlinks_are_never_overwritten(self):
        for target in (self.source, self.root / "unrelated.json"):
            target.write_text(SOURCE, encoding="utf-8")
            self.assertEqual(self.run_cli("--write-baseline", target, ".")[0], 2)
            self.assertEqual(target.read_text(encoding="utf-8"), SOURCE)
        self.capture()
        alias = self.root / "alias.json"
        try:
            alias.symlink_to(self.baseline)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        self.assertEqual(self.run_cli("--write-baseline", alias, ".")[0], 2)
        self.assertTrue(alias.is_symlink())

    def test_atomic_write_failure_preserves_previous_file_and_cleans_temporary(self):
        self.capture()
        before = self.baseline.read_bytes()
        with patch(
            "torchlight.baseline.os.replace", side_effect=PermissionError("denied")
        ):
            status, _, stderr = self.run_cli("--write-baseline", self.baseline, ".")
        self.assertEqual(status, 2)
        self.assertIn("denied", stderr)
        self.assertEqual(self.baseline.read_bytes(), before)
        self.assertEqual(list(self.root.glob(".torchlight-*")), [self.baseline])

    def test_write_error_for_missing_parent_is_reported(self):
        self.assertEqual(
            self.run_cli("--write-baseline", "missing/baseline.json", ".")[0], 2
        )

    def test_outside_root_findings_are_always_new_and_cannot_be_captured(self):
        self.capture()
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "job.py"
            outside.write_text(SOURCE, encoding="utf-8")
            found, _ = scan_file(outside)
            self.assertEqual(
                new_findings(found, read_baseline(self.baseline), self.root), found
            )
            with self.assertRaisesRegex(BaselineError, "outside project root"):
                write_baseline(self.baseline, found, self.root)

    def test_notebook_cell_insertions_and_counting(self):
        notebook = self.root / "analysis.ipynb"
        cells = [{"cell_type": "code", "source": SOURCE}]
        notebook.write_text(json.dumps({"cells": cells}), encoding="utf-8")
        self.capture()
        cells.insert(0, {"cell_type": "code", "source": "# inserted"})
        notebook.write_text(json.dumps({"cells": cells}), encoding="utf-8")
        self.assertEqual(self.run_cli("--baseline", self.baseline, "."), (0, "", ""))
        cells.append({"cell_type": "code", "source": "df.collect()"})
        notebook.write_text(json.dumps({"cells": cells}), encoding="utf-8")
        self.assertEqual(self.run_cli("--baseline", self.baseline, ".")[0], 1)

    def test_named_symlinks_and_project_root_aliases_have_portable_paths(self):
        alias = self.root / "alias.py"
        try:
            alias.symlink_to(self.source)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        found, _ = scan_file(alias)
        write_baseline(self.baseline, found, self.root)
        self.assertEqual(
            json.loads(self.baseline.read_text())["findings"][0]["path"], "alias.py"
        )
        original, _ = scan_file(self.source)
        self.assertEqual(
            new_findings(original, read_baseline(self.baseline), self.root), original
        )
        with tempfile.TemporaryDirectory() as directory:
            linked_root = Path(directory) / "project"
            linked_root.symlink_to(self.root, target_is_directory=True)
            linked, _ = scan_file(linked_root / "alias.py")
            self.assertEqual(
                new_findings(linked, read_baseline(self.baseline), self.root), []
            )

    def test_rule_selection_and_inline_suppressions_apply_before_capture(self):
        self.source.write_text(
            SOURCE
            + "df.toPandas()  # torchlight: ignore[TL001] -- small lookup\n"
            + "df.coalesce(1).write.parquet('out')\n",
            encoding="utf-8",
        )
        status, _, _ = self.run_cli(
            "--select", "TL001", "--write-baseline", self.baseline, "."
        )
        self.assertEqual(status, 0)
        entries = json.loads(self.baseline.read_text())["findings"]
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0]["rule_id"], entries[0]["count"]), ("TL001", 1))

    def test_malformed_entries_fail_closed(self):
        self.capture()
        valid = json.loads(self.baseline.read_text())
        for field, value in (
            ("path", "../job.py"),
            ("path", "/job.py"),
            ("path", "a\\job.py"),
            ("path", "./job.py"),
            ("path", "a//job.py"),
            ("path", "C:/job.py"),
            ("path", []),
            ("rule_id", "TL999"),
            ("rule_id", []),
            ("fingerprint", "v2:" + "a" * 64),
            ("fingerprint", False),
            ("count", 0),
            ("count", -1),
            ("count", True),
            ("count", "1"),
        ):
            with self.subTest(field=field, value=value):
                document = json.loads(json.dumps(valid))
                document["findings"][0][field] = value
                self.baseline.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(BaselineError):
                    read_baseline(self.baseline)
        for document in (
            [],
            {},
            {**valid, "schema_version": True},
            {**valid, "fingerprint_version": "v2"},
            {**valid, "findings": {}},
            {**valid, "findings": [None]},
            {**valid, "findings": [{"path": "job.py"}]},
            {**valid, "findings": valid["findings"] * 2},
        ):
            with self.subTest(document=document):
                self.baseline.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(BaselineError):
                    read_baseline(self.baseline)

    def test_invalid_encoding_json_and_missing_file_are_reported(self):
        for data in (b"\xff", b"{"):
            self.baseline.write_bytes(data)
            with self.assertRaises(BaselineError):
                read_baseline(self.baseline)
        self.baseline.unlink()
        with self.assertRaises(BaselineError):
            read_baseline(self.baseline)

    def test_read_filter_does_not_mutate_baseline(self):
        self.capture()
        found, _ = scan_file(self.source)
        baseline = read_baseline(self.baseline)
        self.assertEqual(new_findings(found, baseline, self.root), [])
        self.assertEqual(new_findings(found, baseline, self.root), [])

    def test_baseline_flags_are_mutually_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--baseline", "a.json", "--write-baseline", "b.json", "."])


if __name__ == "__main__":
    unittest.main()
