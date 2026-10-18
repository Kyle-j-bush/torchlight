# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from torchlight.cli import main
from torchlight.diagnostics import RULES, Finding, Location
from torchlight.reporting import render


class SarifTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.finding = Finding(
            str(self.root / "jobs" / "export.py"),
            "TL001",
            Location(3, 2),
            4,
            "Potential driver-memory risk from .collect()",
            ("Spark reader",),
            "df.collect()",
            structural_key="test-call",
        )

    def report(self, findings=None, errors=None):
        return json.loads(
            render(
                [self.finding] if findings is None else findings,
                errors or [],
                "sarif",
                root=self.root,
            )
        )

    def test_python_result_golden_contract(self):
        finding = self.finding
        result = self.report()["runs"][0]["results"][0]
        self.assertEqual(
            result,
            {
                "ruleId": "TL001",
                "ruleIndex": 0,
                "level": "warning",
                "message": {
                    "text": (
                        f"{finding.message}\nEvidence: Spark reader\n"
                        f"Why: {finding.rule.explanation}\nReview: {finding.rule.recommendation}"
                    )
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": "jobs/export.py",
                                "uriBaseId": "%SRCROOT%",
                            },
                            "region": {"startLine": 3, "startColumn": 2, "endLine": 4},
                        }
                    }
                ],
                "partialFingerprints": {
                    "torchlightStructural/v1": finding.fingerprint,
                    "primaryLocationLineHash": finding.fingerprint.removeprefix("v1:")
                    + ":1",
                },
                "properties": {
                    "evidence": ["Spark reader"],
                    "sourceSnippet": "df.collect()",
                },
            },
        )

    def test_all_rule_metadata_is_present_and_no_unmeasured_precision_claim(self):
        report = self.report()
        self.assertEqual(report["version"], "2.1.0")
        self.assertEqual(
            report["$schema"], "https://json.schemastore.org/sarif-2.1.0.json"
        )
        run = report["runs"][0]
        self.assertEqual(run["columnKind"], "unicodeCodePoints")
        self.assertEqual(run["tool"]["driver"]["name"], "Torchlight")
        self.assertEqual([r["id"] for r in run["tool"]["driver"]["rules"]], list(RULES))
        for rule in run["tool"]["driver"]["rules"]:
            self.assertTrue(rule["help"]["text"])
            self.assertTrue(rule["fullDescription"]["text"])
            self.assertTrue(rule["helpUri"].endswith(f"/{rule['id']}.md"))
            self.assertNotIn("precision", rule["properties"])
            self.assertNotIn("security-severity", rule["properties"])

    def test_notebooks_have_cell_metadata_not_fake_json_regions(self):
        finding = replace(
            self.finding,
            path=str(self.root / "analysis.ipynb"),
            location=Location(3, 2, 5),
        )
        result = self.report([finding])["runs"][0]["results"][0]
        self.assertNotIn("region", result["locations"][0]["physicalLocation"])
        self.assertEqual(
            result["properties"]["notebookLocation"],
            {"cell": 5, "line": 3, "column": 2, "endLine": 4},
        )
        self.assertTrue(result["message"]["text"].startswith("cell 5, line 3:"))

    def test_duplicate_results_get_distinct_github_fingerprints(self):
        second = replace(self.finding, location=Location(9, 2), end_line=9)
        results = self.report([self.finding, second])["runs"][0]["results"]
        self.assertEqual(
            results[0]["partialFingerprints"]["torchlightStructural/v1"],
            results[1]["partialFingerprints"]["torchlightStructural/v1"],
        )
        self.assertTrue(
            results[0]["partialFingerprints"]["primaryLocationLineHash"].endswith(":1")
        )
        self.assertTrue(
            results[1]["partialFingerprints"]["primaryLocationLineHash"].endswith(":2")
        )

    def test_paths_are_uri_encoded_and_outside_root_uses_absolute_file_uri(self):
        special = replace(self.finding, path=str(self.root / "sp ace#%ü.py"))
        outside = replace(self.finding, path=str(self.root.parent / "outside.py"))
        results = self.report([special, outside])["runs"][0]["results"]
        artifacts = [
            r["locations"][0]["physicalLocation"]["artifactLocation"] for r in results
        ]
        self.assertEqual(artifacts[0]["uri"], "sp%20ace%23%25%C3%BC.py")
        self.assertEqual(artifacts[1], {"uri": Path(outside.path).as_uri()})

    def test_sarif_resolves_symlinks_for_github_display(self):
        source = self.root / "source.py"
        source.touch()
        alias = self.root / "alias.py"
        try:
            alias.symlink_to(source)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        result = self.report([replace(self.finding, path=str(alias))])["runs"][0][
            "results"
        ][0]
        self.assertEqual(
            result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
            "source.py",
        )

    def test_errors_make_invocation_unsuccessful_even_with_findings(self):
        run = self.report(errors=["bad.py: parse error"])["runs"][0]
        invocation = run["invocations"][0]
        self.assertFalse(invocation["executionSuccessful"])
        self.assertEqual(
            invocation["toolExecutionNotifications"],
            [{"level": "error", "message": {"text": "bad.py: parse error"}}],
        )
        self.assertEqual(len(run["results"]), 1)

    def test_clean_report_and_uninstalled_checkout(self):
        from importlib.metadata import PackageNotFoundError

        with patch("torchlight.sarif.version", side_effect=PackageNotFoundError):
            run = self.report([])["runs"][0]
        self.assertEqual(run["results"], [])
        self.assertTrue(run["invocations"][0]["executionSuccessful"])
        self.assertNotIn("version", run["tool"]["driver"])

    def test_cli_baseline_errors_are_structured_sarif(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            contextlib.chdir(self.root),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = main(["--format", "sarif", "--baseline", "missing.json", "."])
        self.assertEqual(status, 2)
        run = json.loads(stdout.getvalue())["runs"][0]
        self.assertEqual(run["results"], [])
        self.assertFalse(run["invocations"][0]["executionSuccessful"])
        self.assertIn("baseline error", stderr.getvalue())

    def test_actual_cli_columns_count_unicode_code_points(self):
        path = self.root / "unicode.py"
        path.write_text(
            "from pyspark.sql import SparkSession\n"
            "df = SparkSession.builder.getOrCreate().table('events')\n"
            "label = '😀'; df.collect()\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = main(["--format", "sarif", str(path)])
        self.assertEqual(status, 1)
        run = json.loads(stdout.getvalue())["runs"][0]
        region = run["results"][0]["locations"][0]["physicalLocation"]["region"]
        self.assertEqual(region, {"startLine": 3, "startColumn": 14, "endLine": 3})


if __name__ == "__main__":
    unittest.main()
