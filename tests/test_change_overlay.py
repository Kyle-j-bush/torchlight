# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Conservative Git-base change overlays for opt-in report graphs."""

import json
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from test_git import GitRepository

from torchlight import Config, Scanner
from torchlight.git import GitError
from torchlight.graph import (
    AnalysisGraph,
    BaseCapture,
    GraphArtifact,
    GraphComparison,
    GraphNode,
    NodeChange,
    _GraphCollector,
)

SETUP = (
    "from pyspark.sql import SparkSession\n"
    "spark = SparkSession.builder.getOrCreate()\n"
    "df = spark.read.parquet('events')\n"
)
SOURCE = (
    "from pyspark.sql import DataFrame\ndef export(df: DataFrame):\n    df.collect()\n"
)
BASE_FACTS = (
    "from pyspark.sql import SparkSession\n"
    "spark = SparkSession.builder.getOrCreate()\n"
    "df = spark.table('events').limit(1000)\n"
    "df.collect()\n"
)
CURRENT_FACTS = (
    "from pyspark.sql import SparkSession\n"
    "spark = SparkSession.builder.getOrCreate()\n"
    "df = spark.table('events')\n"
    "df.collect()\n"
)


def notebook(cells):
    return json.dumps(
        {
            "cells": [
                {"cell_type": "markdown", "source": "Not code."},
                *(
                    {
                        "cell_type": "code",
                        "source": cell.splitlines(keepends=True),
                    }
                    for cell in cells
                ),
            ]
        }
    )


class ChangeOverlayTests(GitRepository):
    def scan(self, path=None, **kwargs):
        return Scanner(Config(root=self.root)).scan(
            self.root if path is None else path,
            changed_from=self.base,
            include_graph=True,
            **kwargs,
        )

    def change_for(self, report, node):
        return next(
            change for change in report.graph.changes if change.node_id == node.id
        )

    def commit_base(self, source, name="job.py"):
        path = self.write(name, source)
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        return path

    def test_matched_syntax_keeps_safe_base_facts(self):
        self.commit_base(BASE_FACTS)
        self.path.write_text(CURRENT_FACTS, encoding="utf-8")

        report = self.scan()

        self.assertEqual([finding.rule_id for finding in report.findings], ["TL001"])
        self.assertEqual(report.errors, ())
        collect = next(
            node
            for node in report.graph.nodes
            if node.kind == "action" and node.label == ".collect()"
        )
        change = self.change_for(report, collect)
        self.assertEqual(change.label, "matched")
        self.assertEqual(change.base_location.line, 4)
        self.assertEqual(change.base_before.row_limit, 1000)
        self.assertIsNone(collect.before.row_limit)
        self.assertEqual(report.graph.comparison.requested_ref, self.base)
        self.assertEqual(report.graph.comparison.merge_base, self.base)
        self.assertEqual(report.graph.comparison.current_source, "working-tree")
        self.assertTrue(report.graph.comparison.base_capture_complete)
        self.assertEqual(len(report.graph.changes), len(report.graph.nodes))

    def test_new_file_is_new_or_edited(self):
        report = self.scan(self.write("new.py", SOURCE))

        self.assertEqual([finding.rule_id for finding in report.findings], ["TL001"])
        collect = next(
            node
            for node in report.graph.nodes
            if node.kind == "action" and node.label == ".collect()"
        )
        self.assertEqual(self.change_for(report, collect).label, "new-or-edited")
        self.assertTrue(report.graph.comparison.base_capture_complete)

    def test_rename_matches_base_operations(self):
        self.commit_base(BASE_FACTS)
        self.git("mv", "job.py", "renamed.py")
        renamed = self.write("renamed.py", CURRENT_FACTS)

        report = self.scan(renamed)

        self.assertEqual([finding.rule_id for finding in report.findings], ["TL001"])
        self.assertEqual(report.errors, ())
        collect = next(
            node
            for node in report.graph.nodes
            if node.kind == "action" and node.label == ".collect()"
        )
        change = self.change_for(report, collect)
        self.assertEqual(change.label, "matched")
        self.assertEqual(change.base_before.row_limit, 1000)
        self.assertEqual(report.graph.artifacts[0].path, str(renamed))

    def test_cell_shift_matches_operations(self):
        path = self.commit_base(
            notebook((SETUP, "custom(df)\n")),
            name="job.ipynb",
        )
        path.write_text(notebook((SETUP, "pass\n", "custom(df)\n")), encoding="utf-8")

        report = self.scan(path)

        self.assertEqual(report.findings, ())
        self.assertEqual(report.errors, ())
        opaque = next(node for node in report.graph.nodes if node.kind == "opaque")
        change = self.change_for(report, opaque)
        self.assertEqual(change.label, "matched")
        self.assertEqual(change.base_location.cell, 2)
        self.assertEqual(opaque.location.cell, 3)

    def test_duplicate_operations_are_unknown(self):
        self.path.write_text(SOURCE + "    df.collect()\n", encoding="utf-8")

        report = self.scan()

        self.assertEqual([finding.location.line for finding in report.findings], [4])
        self.assertEqual(report.errors, ())
        collect = next(
            node
            for node in report.graph.nodes
            if node.kind == "action" and node.location.line == 4
        )
        self.assertEqual(self.change_for(report, collect).label, "unknown")
        self.assertTrue(report.graph.comparison.base_capture_complete)

    def test_base_syntax_error_is_unknown(self):
        self.commit_base("?")
        self.path.write_text(SOURCE, encoding="utf-8")

        report = self.scan()

        self.assertEqual([finding.rule_id for finding in report.findings], ["TL001"])
        self.assertTrue(any("Git base" in error for error in report.errors))
        self.assertFalse(report.graph.comparison.base_capture_complete)
        self.assertTrue(
            all(change.label == "unknown" for change in report.graph.changes)
        )

    def test_base_blob_error_is_unknown(self):
        self.path.write_text(SOURCE + "# local edit\n", encoding="utf-8")

        with patch(
            "torchlight.git.GitComparison.previous_source",
            side_effect=GitError("missing blob"),
        ):
            report = self.scan()

        self.assertEqual([finding.rule_id for finding in report.findings], ["TL001"])
        self.assertIn("Git comparison error", report.errors[0])
        self.assertFalse(report.graph.comparison.base_capture_complete)
        self.assertTrue(
            all(change.label == "unknown" for change in report.graph.changes)
        )

    def test_base_budget_truncation_is_unknown(self):
        self.path.write_text(SOURCE + "    df.toPandas()\n", encoding="utf-8")
        calls = []

        def collector(artifact):
            calls.append(artifact.path)
            return _GraphCollector(
                artifact, max_records=1 if len(calls) == 2 else 10_000
            )

        with patch("torchlight.scanner._GraphCollector", new=collector):
            report = self.scan()

        self.assertEqual([finding.rule_id for finding in report.findings], ["TL001"])
        self.assertEqual(report.errors, ())
        self.assertEqual(len(calls), 2)
        self.assertEqual(report.graph.limits, ())
        self.assertTrue(report.graph.capture_complete)
        self.assertFalse(report.graph.comparison.base_capture_complete)
        self.assertTrue(
            all(change.label == "unknown" for change in report.graph.changes)
        )

    def test_current_budget_truncation_does_not_hide_duplicate_ambiguity(self):
        other = self.write("other.py", BASE_FACTS)
        self.commit_base(BASE_FACTS)
        self.path.write_text(CURRENT_FACTS + "df.collect()\n", encoding="utf-8")
        other.write_text(CURRENT_FACTS, encoding="utf-8")
        calls = []

        def collector(artifact):
            calls.append(artifact.path)
            return _GraphCollector(
                artifact, max_records=6 if len(calls) == 1 else 10_000
            )

        with patch("torchlight.scanner._GraphCollector", new=collector):
            report = self.scan()

        self.assertEqual(report.errors, ())
        self.assertEqual(len(report.findings), 3)
        self.assertEqual(len(calls), 4)
        self.assertFalse(report.graph.capture_complete)
        self.assertTrue(report.graph.comparison.base_capture_complete)
        self.assertIsNotNone(report.graph.links[0].node_id)
        self.assertIsNone(report.graph.links[1].node_id)
        self.assertIsNotNone(report.graph.links[2].node_id)
        self.assertTrue(report.graph.changes)
        truncated = report.graph.limits[0].artifact_id
        nodes = {node.id: node for node in report.graph.nodes}
        for change in report.graph.changes:
            if nodes[change.node_id].artifact_id == truncated:
                self.assertEqual(change.label, "unknown")
                self.assertIsNone(change.base_before)
            else:
                self.assertEqual(change.label, "matched")

    def test_unavailable_base_source_is_unknown(self):
        self.write("notes.txt", SOURCE)
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("mv", "notes.txt", "new.py")

        report = self.scan(self.root / "new.py")

        self.assertEqual([finding.rule_id for finding in report.findings], ["TL001"])
        self.assertFalse(report.graph.comparison.base_capture_complete)
        self.assertTrue(
            all(change.label == "unknown" for change in report.graph.changes)
        )

    def test_without_comparison_nodes_are_not_compared(self):
        report = Scanner(Config(root=self.root)).scan(self.path, include_graph=True)

        self.assertIsNone(report.graph.comparison)
        self.assertEqual(len(report.graph.changes), len(report.graph.nodes))
        self.assertTrue(
            all(change.label == "not-compared" for change in report.graph.changes)
        )

    def test_comparison_keeps_finding_output_parity(self):
        self.commit_base(BASE_FACTS)
        self.path.write_text(CURRENT_FACTS, encoding="utf-8")

        plain = Scanner(Config(root=self.root)).scan(self.path, changed_from=self.base)
        captured = self.scan()

        self.assertIsNone(plain.graph)
        self.assertIsNotNone(captured.graph)
        self.assertEqual(captured.findings, plain.findings)
        self.assertEqual(captured.errors, plain.errors)
        self.assertEqual(captured.to_dict(), plain.to_dict())


class ChangeRecordTests(unittest.TestCase):
    def setUp(self):
        self.artifact = GraphArtifact("job.py", "python")
        self.node = GraphNode("n-1", self.artifact.id, "source", "source", "g1-source")

    def test_change_records_are_immutable_and_snapshot_sequences(self):
        change = NodeChange(self.node.id, "matched")
        graph = AnalysisGraph(
            artifacts=(self.artifact,),
            nodes=(self.node,),
            changes=[change],
            comparison=GraphComparison("HEAD~1", "a" * 40),
        )
        self.assertIsInstance(graph.changes, tuple)
        with self.assertRaises(FrozenInstanceError):
            change.label = "unknown"
        with self.assertRaises(FrozenInstanceError):
            graph.comparison.merge_base = "b" * 40

    def test_changes_must_be_unique_and_reference_known_nodes(self):
        change = NodeChange(self.node.id, "matched")
        with self.assertRaisesRegex(ValueError, "unique"):
            AnalysisGraph(
                artifacts=(self.artifact,),
                nodes=(self.node,),
                changes=(change, change),
            )
        with self.assertRaisesRegex(ValueError, "unknown node"):
            AnalysisGraph(
                artifacts=(self.artifact,),
                nodes=(self.node,),
                changes=(NodeChange("n-missing", "matched"),),
            )
        with self.assertRaisesRegex(ValueError, "unsupported change label"):
            NodeChange(self.node.id, "changed")

    def test_comparison_metadata_is_validated(self):
        with self.assertRaisesRegex(ValueError, "requested_ref"):
            GraphComparison("", "a" * 40)
        with self.assertRaisesRegex(ValueError, "merge_base"):
            GraphComparison("HEAD~1", "")
        with self.assertRaisesRegex(ValueError, "base_capture_complete"):
            GraphComparison("HEAD~1", "a" * 40, 1)
        with self.assertRaisesRegex(ValueError, "current_source"):
            GraphComparison("HEAD~1", "a" * 40, current_source="HEAD")
        with self.assertRaises(TypeError):
            AnalysisGraph(comparison="HEAD~1")

    def test_base_capture_status_and_graph_must_agree(self):
        self.assertEqual(BaseCapture("job.py", "added").status, "added")
        self.assertEqual(
            BaseCapture("job.py", "analyzed", AnalysisGraph()).status, "analyzed"
        )
        with self.assertRaisesRegex(ValueError, "requires exactly one graph"):
            BaseCapture("job.py", "analyzed")
        with self.assertRaisesRegex(ValueError, "requires exactly one graph"):
            BaseCapture("job.py", "added", AnalysisGraph())
        with self.assertRaisesRegex(ValueError, "unsupported base status"):
            BaseCapture("job.py", "missing")


if __name__ == "__main__":
    unittest.main()
