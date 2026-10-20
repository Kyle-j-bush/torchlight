# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "from pyspark.sql import SparkSession\ndf = SparkSession.builder.getOrCreate().table('private-table')\ndf.collect()\n"


class ValidationHarnessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.corpus = self.work / "corpus"
        self.corpus.mkdir()
        self.source = self.corpus / "private-job.py"
        self.source.write_text(SOURCE, encoding="utf-8")
        self.snapshot = self.work / "snapshot"
        result = self.run_tool(
            "snapshot",
            self.corpus,
            "--permission",
            "fixture data only",
            "--output",
            self.snapshot,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.labels = self.snapshot / "labels.json"

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "scripts.validate_corpus", *map(str, args)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    def write_labels(self, sites=None, reviewers=1, labeler="agent"):
        labels = json.loads(self.labels.read_text())
        labels.update(
            blind_review=True,
            reviewer_count=reviewers,
            labeler=labeler,
            reviewed_files=["private-job.py"],
            sites=sites if sites is not None else [self.site()],
        )
        self.labels.write_text(json.dumps(labels), encoding="utf-8")

    def site(self, **values):
        return {
            "path": "private-job.py",
            "rule_id": "TL001",
            "line": 3,
            "column": 1,
            "cell": None,
            "a": "surface",
            "b": None,
            "decision": "surface",
            "rationale": "Full result needs review.",
            "adjudication": "",
            **values,
        }

    def evaluate(self, output="result"):
        target = self.work / output
        result = self.run_tool(
            "evaluate",
            self.corpus,
            "--manifest",
            self.snapshot / "manifest.json",
            "--labels",
            self.labels,
            "--output",
            target,
        )
        summary = (
            json.loads((target / "summary.json").read_text())
            if (target / "summary.json").exists()
            else None
        )
        return result, summary

    def test_snapshot_is_blind_and_evaluation_is_source_inert_private_and_aggregate_only(
        self,
    ):
        template = json.loads(self.labels.read_text())
        self.assertEqual(template["sites"], [])
        self.assertFalse(template["blind_review"])
        self.assertIsNone(template["labeler"])
        self.write_labels()
        before = self.source.read_bytes()
        result, summary = self.evaluate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list(self.corpus.iterdir()), [self.source])
        rule = summary["rules"]["TL001"]
        self.assertEqual((rule["tp"], rule["fp"], rule["fn"]), (1, 0, 0))
        self.assertEqual((rule["precision"], rule["recall"]), (1, 1))
        self.assertIsNone(rule["initial_agreement"])
        self.assertEqual(summary["labeler"], "agent")
        self.assertIsNone(summary["rules"]["TL005"]["recall"])
        serialized = json.dumps(summary)
        for private in (
            "private-job",
            "private-table",
            str(self.corpus),
            "fixture data only",
        ):
            self.assertNotIn(private, serialized)
        self.assertIn(
            "private-job", (self.work / "result/raw-findings.json").read_text()
        )

    def test_unreviewed_emissions_and_uncertainty_withhold_metrics(self):
        self.write_labels([])
        result, summary = self.evaluate("missing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(summary["rules"]["TL001"]["unreviewed_emissions"], 1)
        self.assertIsNone(summary["rules"]["TL001"]["precision"])
        self.write_labels([self.site(a="uncertain", decision="uncertain")])
        result, summary = self.evaluate("uncertain")
        self.assertEqual(summary["rules"]["TL001"]["uncertain_sites"], 1)
        self.assertIsNone(summary["rules"]["TL001"]["recall"])

    def test_false_positives_missed_sites_and_two_reviewer_agreement(self):
        self.write_labels(
            [
                self.site(
                    a="do-not-surface",
                    b="surface",
                    decision="do-not-surface",
                    adjudication="Third reviewer resolved intent.",
                ),
                self.site(rule_id="TL005", b="surface"),
            ],
            reviewers=2,
            labeler="human",
        )
        result, summary = self.evaluate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(summary["rules"]["TL001"]["fp"], 1)
        self.assertEqual(
            summary["rules"]["TL001"]["initial_agreement"],
            {"agreed": 0, "total": 1, "fraction": 0},
        )
        self.assertEqual(summary["rules"]["TL005"]["fn"], 1)
        self.assertEqual(summary["rules"]["TL005"]["initial_agreement"]["fraction"], 1)

    def test_agent_agreement_is_withheld_even_with_two_matching_reviewers(self):
        self.write_labels([self.site(b="surface")], reviewers=2, labeler="agent")
        result, summary = self.evaluate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(summary["labeler"], "agent")
        self.assertEqual(summary["reviewer_count"], 2)
        self.assertEqual(summary["rules"]["TL001"]["tp"], 1)
        self.assertTrue(
            all(rule["initial_agreement"] is None for rule in summary["rules"].values())
        )
        self.assertTrue(
            any(
                "not independent human validation" in limit
                for limit in summary["limits"]
            )
        )

    def test_missing_or_invalid_labeler_is_not_silently_assumed_human(self):
        self.write_labels()
        labels = json.loads(self.labels.read_text())
        for value in (None, True, [], "unknown", "human,agent"):
            with self.subTest(value=value):
                self.labels.write_text(
                    json.dumps({**labels, "labeler": value}), encoding="utf-8"
                )
                result, summary = self.evaluate()
                self.assertEqual(result.returncode, 2)
                self.assertIn("explicit provenance", result.stderr)
                self.assertIsNone(summary)
        labels.pop("labeler")
        self.labels.write_text(json.dumps(labels), encoding="utf-8")
        self.assertEqual(self.evaluate()[0].returncode, 2)

    def test_unreviewed_files_wrong_manifest_duplicates_and_malformed_labels_fail(self):
        for sites, reviewers in (
            ([self.site(), self.site()], 1),
            ([self.site(line=True)], 1),
            ([self.site(path="../outside.py")], 1),
            ([self.site(rule_id="UNKNOWN")], 1),
            ([self.site(b="do-not-surface")], 2),
        ):
            with self.subTest(sites=sites):
                self.write_labels(sites, reviewers)
                result, summary = self.evaluate()
                self.assertEqual(result.returncode, 2)
                self.assertIsNone(summary)
        self.write_labels()
        labels = json.loads(self.labels.read_text())
        for key, value in (
            ("reviewed_files", []),
            ("manifest_sha256", "wrong"),
            ("blind_review", False),
        ):
            modified = {**labels, key: value}
            self.labels.write_text(json.dumps(modified), encoding="utf-8")
            self.assertEqual(self.evaluate()[0].returncode, 2)

    def test_source_changes_and_new_files_invalidate_the_snapshot(self):
        self.write_labels()
        self.source.write_text(SOURCE + "# changed\n", encoding="utf-8")
        self.assertEqual(self.evaluate()[0].returncode, 2)
        self.source.write_text(SOURCE, encoding="utf-8")
        (self.corpus / "new.py").write_text("pass", encoding="utf-8")
        self.assertEqual(self.evaluate()[0].returncode, 2)

    def test_source_symlinks_are_rejected_without_creating_outputs(self):
        try:
            (self.corpus / "alias.py").symlink_to(self.source)
        except OSError:
            self.skipTest("symlinks unavailable")
        result = self.run_tool(
            "snapshot",
            self.corpus,
            "--permission",
            "fixture",
            "--output",
            self.work / "symlink-result",
        )
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.work / "symlink-result").exists())

    def test_jupyter_and_databricks_audited_coordinates_match_real_findings(self):
        (self.corpus / "job.ipynb").write_text(
            json.dumps({"cells": [{"cell_type": "code", "source": SOURCE}]}),
            encoding="utf-8",
        )
        (self.corpus / "export.py").write_text(
            "# Databricks notebook source\n"
            + SOURCE.rsplit("df.collect()", 1)[0]
            + "# COMMAND ----------\n# MAGIC %python\n# MAGIC df.collect()\n",
            encoding="utf-8",
        )
        other = self.work / "all-formats"
        result = self.run_tool(
            "snapshot", self.corpus, "--permission", "fixture", "--output", other
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.snapshot = other
        self.labels = other / "labels.json"
        self.write_labels(
            [
                self.site(),
                self.site(path="job.ipynb", cell=1),
                self.site(path="export.py", line=6, column=9, cell=2),
            ]
        )
        labels = json.loads(self.labels.read_text())
        labels["reviewed_files"].extend(["job.ipynb", "export.py"])
        self.labels.write_text(json.dumps(labels), encoding="utf-8")
        result, summary = self.evaluate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(summary["rules"]["TL001"]["tp"], 3)
        self.assertEqual(summary["rules"]["TL001"]["unreviewed_emissions"], 0)
        self.assertEqual(
            summary["formats"], {"python": 1, "jupyter": 1, "databricks": 1}
        )

    def test_scan_errors_remain_visible_and_do_not_inflate_metrics(self):
        self.source.write_text("? invalid", encoding="utf-8")
        other = self.work / "invalid-snapshot"
        result = self.run_tool(
            "snapshot", self.corpus, "--permission", "fixture", "--output", other
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.snapshot = other
        self.labels = other / "labels.json"
        self.write_labels([])
        result, summary = self.evaluate()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(summary["scan_errors"], 1)
        self.assertTrue(
            all(rule["precision"] is None for rule in summary["rules"].values())
        )

    def test_refuses_repo_outputs_existing_destinations_and_unconfirmed_rights(self):
        for output, permission in (
            (ROOT / "must-not-create-private-artifacts", "fixture"),
            (self.corpus / "output", "fixture"),
            (self.snapshot, "fixture"),
            (self.work / "empty-rights", " "),
        ):
            with self.subTest(output=output):
                result = self.run_tool(
                    "snapshot",
                    self.corpus,
                    "--permission",
                    permission,
                    "--output",
                    output,
                )
                self.assertEqual(result.returncode, 2)
        self.assertFalse((ROOT / "must-not-create-private-artifacts").exists())

    def test_jupyter_source_lines_exclude_outputs_and_source_is_never_executed(self):
        marker = self.work / "executed"
        self.source.write_text(
            f"open({str(marker)!r}, 'w').write('bad')\n" + SOURCE, encoding="utf-8"
        )
        notebook = self.corpus / "job.ipynb"
        notebook.write_text(
            json.dumps(
                {
                    "cells": [
                        {"cell_type": "markdown", "source": "ignore"},
                        {
                            "cell_type": "code",
                            "source": ["unknown.collect()\n", "pass\n"],
                            "outputs": ["private output\n" * 100],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        other = self.work / "notebook-snapshot"
        result = self.run_tool(
            "snapshot", self.corpus, "--permission", "fixture", "--output", other
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((other / "manifest.json").read_text())
        self.assertEqual(manifest["files"][0]["source_lines"], 2)
        self.snapshot = other
        self.labels = other / "labels.json"
        self.write_labels([self.site(line=4)])
        labels = json.loads(self.labels.read_text())
        labels["reviewed_files"].append("job.ipynb")
        self.labels.write_text(json.dumps(labels), encoding="utf-8")
        self.assertEqual(self.evaluate()[0].returncode, 0)
        self.assertFalse(marker.exists())
