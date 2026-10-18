# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from torchlight.cli import main
from torchlight.diagnostics import Finding, Location
from torchlight.reporting import escape_command, github_annotation

SOURCE = (
    "from pyspark.sql import SparkSession\n"
    "df = SparkSession.builder.getOrCreate().table('events')\n"
    "df.collect()\n"
    "df.coalesce(1).write.parquet(path)\n"
    "for name in columns:\n"
    "    df = df.withColumn(name, expr)\n"
)


class CliOutputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "example.py"
        self.path.write_text(SOURCE, encoding="utf-8")

    def run_cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main([str(arg) for arg in arguments])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_json_has_stable_fields_and_all_rules(self):
        status, stdout, stderr = self.run_cli("--format", "json", self.path)
        self.assertEqual(status, 1)
        self.assertEqual(stderr, "")
        report = json.loads(stdout)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["errors"], [])
        self.assertEqual(
            [f["rule_id"] for f in report["findings"]], ["TL001", "TL002", "TL003"]
        )
        finding = report["findings"][0]
        self.assertEqual(finding["path"], str(self.path))
        self.assertEqual(
            (finding["line"], finding["column"], finding["cell"]), (3, 1, None)
        )
        for key in ("evidence", "explanation", "recommendation", "snippet"):
            self.assertTrue(finding[key])

    def test_json_is_valid_even_when_empty_or_errors_only(self):
        clean = self.root / "clean.py"
        clean.write_text("unknown.collect()", encoding="utf-8")
        for path, expected_status in ((clean, 0), (self.root / "missing", 2)):
            with self.subTest(path=path):
                status, stdout, stderr = self.run_cli("--format", "json", path)
                report = json.loads(stdout)
                self.assertEqual(status, expected_status)
                self.assertEqual(report["findings"], [])
                self.assertEqual(bool(report["errors"]), expected_status == 2)
                self.assertEqual(bool(stderr), expected_status == 2)

    def test_json_findings_still_take_precedence_over_errors(self):
        status, stdout, stderr = self.run_cli(
            "--format", "json", self.path, self.root / "missing"
        )
        self.assertEqual(status, 1)
        self.assertEqual(len(json.loads(stdout)["errors"]), 1)
        self.assertIn("no such file", stderr)

    def test_rule_selection_and_ignores(self):
        status, stdout, stderr = self.run_cli(
            "--format",
            "json",
            "--select",
            "TL001,TL002",
            "--ignore",
            "TL001",
            self.path,
        )
        self.assertEqual(status, 1)
        self.assertEqual(
            [f["rule_id"] for f in json.loads(stdout)["findings"]], ["TL002"]
        )
        self.assertEqual(stderr, "")
        self.assertEqual(
            self.run_cli("--ignore", "TL001,TL002,TL003", self.path), (0, "", "")
        )

    def test_invalid_options_fail_before_scanning(self):
        for args in (
            ("--select", "TL999"),
            ("--ignore", ""),
            ("--select", "TL001,"),
            ("--assume-spark-session", "spark.session"),
            ("--assume-spark-session", "for"),
            ("--format", "yaml"),
        ):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main([*args, str(self.path)])
                self.assertEqual(raised.exception.code, 2)

    def test_explicit_existing_sessions_are_repeatable(self):
        self.path.write_text(
            "spark.table('a').collect()\nsession.table('b').toPandas()",
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli(self.path), (0, "", ""))
        status, stdout, stderr = self.run_cli(
            "--assume-spark-session",
            "spark",
            "--assume-spark-session",
            "session",
            "--format",
            "json",
            self.path,
        )
        self.assertEqual(status, 1)
        self.assertEqual(len(json.loads(stdout)["findings"]), 2)
        self.assertEqual(stderr, "")
        self.assertIn("Explicitly assumed", stdout)

    def test_overlapping_paths_are_not_reported_twice(self):
        _, stdout, _ = self.run_cli("--format", "json", self.path, self.root, self.path)
        self.assertEqual(len(json.loads(stdout)["findings"]), 3)

    def test_github_annotations_use_source_coordinates(self):
        status, stdout, stderr = self.run_cli("--format", "github", self.path)
        lines = stdout.splitlines()
        self.assertEqual((status, len(lines), stderr), (1, 3, ""))
        self.assertIn("line=3,col=1,title=TL001", lines[0])
        self.assertIn("%0AEvidence:", lines[0])
        self.assertIn("%0AWhy:", lines[0])

    def test_notebook_annotations_do_not_misuse_json_line_numbers(self):
        path = self.root / "example.ipynb"
        path.write_text(
            json.dumps({"cells": [{"cell_type": "code", "source": SOURCE}]}),
            encoding="utf-8",
        )
        _, stdout, _ = self.run_cli("--format", "github", path)
        annotation = stdout.splitlines()[0]
        self.assertNotIn(",line=", annotation)
        self.assertIn("::cell 1, line 3:", annotation)

    def test_github_control_characters_and_property_delimiters_are_escaped(self):
        finding = Finding(
            "bad%,:\n::error::injected.py",
            "TL001",
            Location(1),
            1,
            "message\r\n::error::injected%",
            ("evidence",),
            "source",
        )
        annotation = github_annotation(finding)
        self.assertEqual(len(annotation.splitlines()), 1)
        self.assertIn("file=bad%25%2C%3A%0A%3A%3Aerror%3A%3Ainjected.py,", annotation)
        self.assertIn("message%0D%0A::error::injected%25", annotation)
        self.assertEqual(escape_command("%\r\n"), "%25%0D%0A")

    def test_github_scan_errors_are_annotations_and_stderr(self):
        status, stdout, stderr = self.run_cli(
            "--format", "github", self.root / "missing"
        )
        self.assertEqual(status, 2)
        self.assertTrue(stdout.startswith("::error title=Torchlight scan error::"))
        self.assertIn("no such file", stderr)


if __name__ == "__main__":
    unittest.main()
