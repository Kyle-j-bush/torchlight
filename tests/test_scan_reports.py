# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Public opt-in report graphs: filtering, links, pruning, and compatibility."""

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError, asdict
from functools import partial
from pathlib import Path
from unittest.mock import patch

from test_git import GitRepository
from test_riskmap_preservation import CELLS, EXPECTED_CODES, SOURCES

from torchlight import Config, Rule, Scanner, ScanReport
from torchlight.baseline import write_baseline
from torchlight.graph import AnalysisGraph, _GraphCollector
from torchlight.plugins import Diagnostic, Plugin

SETUP = CELLS[0]


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


class ReportGraphTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / "job.py"

    def write(self, name, source):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def scan(self, source=None, *, config=None, paths=None, **kwargs):
        if source is not None:
            self.path.write_text(source, encoding="utf-8")
        report = Scanner(config or Config(root=self.root)).scan(
            self.path if paths is None else paths, **kwargs
        )
        return report

    def assert_links_match_findings(self, report):
        graph = report.graph
        self.assertIsNotNone(graph)
        self.assertEqual(graph.anchors, ())
        self.assertEqual(
            [(link.rule_id, link.location) for link in graph.links],
            [(finding.rule_id, finding.location) for finding in report.findings],
        )
        nodes = {node.id: node for node in graph.nodes}
        for link in graph.links:
            if link.node_id is not None:
                self.assertEqual(nodes[link.node_id].location, link.location)

    def test_opt_in_graph_preserves_default_outputs_and_schema(self):
        self.path.write_text(SETUP + CELLS[3], encoding="utf-8")
        plain = Scanner(Config(root=self.root)).scan(self.path)
        captured = Scanner(Config(root=self.root)).scan(self.path, include_graph=True)
        self.assertIsNone(plain.graph)
        self.assertIsNotNone(captured.graph)
        self.assertEqual(captured.findings, plain.findings)
        self.assertEqual(captured.errors, plain.errors)
        self.assertEqual(captured.to_dict(), plain.to_dict())
        for output_format in ("text", "json", "github", "sarif"):
            self.assertEqual(
                captured.render(output_format), plain.render(output_format)
            )
        self.assert_links_match_findings(captured)
        self.assertTrue(captured.graph.capture_complete)

    def test_include_graph_bool_is_validated_before_source_io(self):
        for value in (1, "false", None):
            with (
                self.subTest(value=value),
                patch("torchlight.scanner.scan_file") as scan_file,
                self.assertRaises(TypeError),
            ):
                Scanner().scan(self.root / "missing.py", include_graph=value)
            scan_file.assert_not_called()

    def test_explicit_opt_out_allocates_no_graph_records(self):
        self.path.write_text(SETUP + "df.collect()\n", encoding="utf-8")
        with patch.object(
            _GraphCollector,
            "__init__",
            side_effect=AssertionError("opt-out allocated a collector"),
        ):
            report = Scanner().scan(self.path, include_graph=False)
        self.assertIsNone(report.graph)
        self.assertEqual([f.rule_id for f in report.findings], ["TL001"])

    def test_report_graph_and_its_records_are_immutable(self):
        report = self.scan(SETUP + "df.collect()\n", include_graph=True)
        for obj, attribute, value in (
            (report, "graph", AnalysisGraph()),
            (report.graph, "nodes", ()),
            (report.graph.nodes[0], "label", "changed"),
            (report.graph.links[0], "node_id", None),
            (report.graph.artifacts[0], "path", "changed.py"),
        ):
            with (
                self.subTest(attribute=attribute),
                self.assertRaises(FrozenInstanceError),
            ):
                setattr(obj, attribute, value)
        self.assertIsInstance(report.graph.nodes, tuple)
        self.assertIsInstance(report.graph.links, tuple)
        detached = asdict(report.graph)
        detached["links"][0]["node_id"] = None
        self.assertIsNotNone(report.graph.links[0].node_id)
        with self.assertRaises(TypeError):
            ScanReport(graph=object())

    def test_duplicate_fingerprints_get_distinct_stable_report_ids(self):
        source = SETUP + "df.collect(); df.collect()\n"
        first = self.scan(source, include_graph=True)
        second = self.scan(source, include_graph=True)
        self.assertEqual(len(first.findings), 2)
        self.assertEqual(first.findings[0].fingerprint, first.findings[1].fingerprint)
        links = first.graph.links
        self.assertEqual(len({link.finding_id for link in links}), 2)
        self.assertEqual(len({link.node_id for link in links}), 2)
        self.assertEqual(
            [link.finding_id for link in links],
            [link.finding_id for link in second.graph.links],
        )

    def test_same_location_in_different_files_gets_different_links(self):
        self.path.write_text(SETUP + "df.collect()\n", encoding="utf-8")
        other = self.write("other.py", SETUP + "df.collect()\n")
        report = Scanner(Config(root=self.root)).scan(
            (self.path, other), include_graph=True
        )
        self.assertEqual(len(report.findings), 2)
        self.assertEqual(len(report.graph.artifacts), 2)
        self.assertEqual(len({link.finding_id for link in report.graph.links}), 2)

    def test_suppressed_and_deselected_findings_never_reappear(self):
        source = (
            SETUP
            + "df.collect() # torchlight: ignore[TL001] -- reviewed small result\n"
            + "small = df.coalesce(1)\n"
            + "small.write.parquet('out')\n"
        )
        report = self.scan(source, include_graph=True)
        self.assertEqual([f.rule_id for f in report.findings], ["TL002"])
        self.assert_links_match_findings(report)
        self.assertFalse(any(node.label == ".collect()" for node in report.graph.nodes))

        report = self.scan(
            source,
            config=Config(root=self.root, select={"TL002"}),
            include_graph=True,
        )
        self.assertEqual([f.rule_id for f in report.findings], ["TL002"])

        report = self.scan(
            SETUP + "df.collect() # torchlight: ignore[TL001] -- reviewed\n",
            include_graph=True,
        )
        self.assertEqual(report.findings, ())
        self.assertEqual(report.graph, AnalysisGraph())

    def test_invalid_suppressions_keep_errors_and_their_finding_links(self):
        report = self.scan(
            SETUP + "df.collect() # torchlight: ignore[TL999] -- unknown rule\n",
            include_graph=True,
        )
        self.assertEqual([f.rule_id for f in report.findings], ["TL001"])
        self.assertEqual(len(report.errors), 1)
        self.assertIn("invalid suppression", report.errors[0])
        self.assert_links_match_findings(report)

    def test_baseline_filtering_removes_links_without_hiding_scan_errors(self):
        baseline = self.root / "debt.json"
        scanner = Scanner(Config(root=self.root, baseline=baseline))
        source = (
            SETUP + "df.collect()\nsmall = df.coalesce(1)\nsmall.write.parquet('out')\n"
        )
        self.path.write_text(source, encoding="utf-8")
        all_findings = scanner.scan(self.path, use_baseline=False, include_graph=True)
        self.assertEqual(len(all_findings.findings), 2)
        write_baseline(baseline, list(all_findings.findings), self.root)
        filtered = scanner.scan(self.path, include_graph=True)
        self.assertEqual(filtered.findings, ())
        self.assertEqual(filtered.graph, AnalysisGraph())
        missing = scanner.scan(
            (self.path, self.root / "missing.py"), include_graph=True
        )
        self.assertEqual(len(missing.errors), 1)
        self.assertEqual(missing.graph, AnalysisGraph())

    def test_budget_truncation_keeps_findings_and_exposes_the_gap(self):
        self.path.write_text(SETUP + "df.collect()\n", encoding="utf-8")
        with patch(
            "torchlight.scanner._GraphCollector",
            new=partial(_GraphCollector, max_records=1),
        ):
            report = Scanner().scan(self.path, include_graph=True)
        self.assertEqual([f.rule_id for f in report.findings], ["TL001"])
        self.assertEqual(report.errors, ())
        self.assertFalse(report.graph.capture_complete)
        self.assertEqual(len(report.graph.limits), 1)
        self.assertEqual(report.graph.limits[0].max_records, 1)
        self.assertEqual(len(report.graph.links), 1)
        self.assertIsNone(report.graph.links[0].node_id)
        self.assertEqual(len(report.graph.artifacts), 1)

    def test_partial_scan_keeps_only_real_artifacts_and_errors(self):
        bad = self.write("bad.py", "?\n")
        good = self.write("good.py", SETUP + "df.collect()\n")
        report = Scanner(Config(root=self.root)).scan(
            (bad, good, self.root / "missing.py"), include_graph=True
        )
        self.assertEqual(len(report.errors), 2)
        self.assertEqual([f.path for f in report.findings], [str(good)])
        self.assertEqual([a.path for a in report.graph.artifacts], [str(good)])
        self.assertEqual(len(report.graph.links), 1)
        self.assert_links_match_findings(report)

    def test_public_capture_parity_across_the_regression_corpus(self):
        cases = json.loads(
            (
                Path(__file__).resolve().parents[1] / "benchmarks" / "cases.json"
            ).read_text(encoding="utf-8")
        )["cases"]
        for index, case in enumerate(cases):
            if "cells" in case:
                source = notebook(["\n".join(cell) + "\n" for cell in case["cells"]])
                suffix = ".ipynb"
            else:
                source = "\n".join(case["source"]) + "\n"
                suffix = ".py"
            path = self.write(f"case-{index}{suffix}", source)
            config = Config(
                root=self.root,
                assume_sessions=tuple(case.get("assume_sessions", ())),
            )
            plain = Scanner(config).scan(path, use_baseline=False)
            captured = Scanner(config).scan(
                path, use_baseline=False, include_graph=True
            )
            with self.subTest(case=case["name"]):
                self.assertEqual(captured.findings, plain.findings)
                self.assertEqual(captured.errors, plain.errors)
                self.assertEqual(captured.to_dict(), plain.to_dict())
                self.assert_links_match_findings(captured)

    def test_empty_inputs_return_an_empty_requested_graph(self):
        report = Scanner().scan([], include_graph=True)
        self.assertEqual(report.errors, ("no input paths supplied",))
        self.assertEqual(report.graph, AnalysisGraph())

    def test_early_baseline_error_returns_an_empty_requested_graph(self):
        baseline = self.write("debt.json", "{}")
        scanner = Scanner(Config(root=self.root, baseline=baseline))
        with patch("torchlight.scanner.scan_file") as scan_file:
            report = scanner.scan(self.path, include_graph=True)
        scan_file.assert_not_called()
        self.assertIn("baseline error", report.errors[0])
        self.assertEqual(report.graph, AnalysisGraph())

    def test_pruning_keeps_finding_paths_and_analysis_boundaries(self):
        source = (
            SETUP
            + "safe = df.limit(5)\n"
            + "safe.collect()\n"
            + "df.collect()\n"
            + "result = custom(df)\n"
        )
        report = self.scan(source, include_graph=True)
        self.assertEqual([f.rule_id for f in report.findings], ["TL001"])
        lines = {(node.kind, node.location.line) for node in report.graph.nodes}
        self.assertNotIn(("constraint", 4), lines)
        self.assertNotIn(("action", 5), lines)
        self.assertIn(("action", 6), lines)
        self.assertIn(("opaque", 7), lines)
        self.assert_links_match_findings(report)

    def test_boundaries_without_findings_are_retained(self):
        report = self.scan(SETUP + "result = custom(df)\n", include_graph=True)
        self.assertEqual(report.findings, ())
        self.assertEqual(report.graph.links, ())
        self.assertEqual(
            [node.kind for node in report.graph.nodes if node.kind == "opaque"],
            ["opaque"],
        )
        opaque = next(node for node in report.graph.nodes if node.kind == "opaque")
        self.assertTrue(
            any(
                edge.target == opaque.id and edge.relation == "control"
                for edge in report.graph.edges
            )
        )

    def test_notebook_and_databricks_graphs_use_existing_coordinates(self):
        for name, kind in (("pipeline.ipynb", "jupyter"), ("export.py", "databricks")):
            with self.subTest(name=name):
                path = self.write(name, SOURCES[name])
                report = Scanner(Config(root=self.root)).scan(path, include_graph=True)
                self.assertEqual([f.rule_id for f in report.findings], EXPECTED_CODES)
                self.assertEqual(report.graph.artifacts[0].source_kind, kind)
                self.assert_links_match_findings(report)
                self.assertTrue(report.graph.capture_complete)

    def test_notebook_invalidation_boundary_survives_without_findings(self):
        path = self.write(
            "boundary.ipynb",
            notebook((SETUP, "%%sql\nselect 1\n", "df.collect()\n")),
        )
        report = Scanner(Config(root=self.root)).scan(path, include_graph=True)
        self.assertEqual(report.findings, ())
        self.assertEqual(report.graph.links, ())
        opaque = next(node for node in report.graph.nodes if node.kind == "opaque")
        self.assertEqual(opaque.location.cell, 2)
        self.assertIn("previous bindings invalidated", opaque.label)

    def test_plugin_findings_link_to_the_analyzed_operation(self):
        class Count:
            rule_id = "TEAM001"

            def check(self, facts):
                if facts.method == "count":
                    yield Diagnostic(self.rule_id, ("verbatim <evidence>",))

        rule = Rule("TEAM001", "Review count", "Test only.", "No action.")
        config = Config(root=self.root, plugins=(Plugin(rule, Count()),))
        report = self.scan(SETUP + "df.count()\n", config=config, include_graph=True)
        self.assertEqual([f.rule_id for f in report.findings], ["TEAM001"])
        self.assertEqual(report.findings[0].evidence, ("verbatim <evidence>",))
        self.assert_links_match_findings(report)
        link = report.graph.links[0]
        node = next(node for node in report.graph.nodes if node.id == link.node_id)
        self.assertEqual(node.label, ".count()")

    def test_plugin_failure_keeps_existing_error_semantics(self):
        class Broken:
            rule_id = "TEAM001"

            def check(self, facts):
                raise RuntimeError("private error")

        rule = Rule("TEAM001", "Review count", "Test only.", "No action.")
        config = Config(root=self.root, plugins=(Plugin(rule, Broken()),))
        report = self.scan(SETUP + "df.count()\n", config=config, include_graph=True)
        self.assertEqual(report.findings, ())
        self.assertIn("plugin TEAM001 failed (RuntimeError)", report.errors[0])
        self.assertNotIn("private error", report.errors[0])
        self.assertEqual(report.graph, AnalysisGraph())


class GitReportGraphTests(GitRepository):
    def test_subtracted_findings_do_not_keep_links(self):
        self.path.write_text(
            "from pyspark.sql import DataFrame\ndef export(df: DataFrame):\n"
            "    df.collect()\n    df.toPandas()\n",
            encoding="utf-8",
        )
        report = Scanner(Config(root=self.root)).scan(
            self.path, changed_from=self.base, include_graph=True
        )
        self.assertEqual([f.rule_id for f in report.findings], ["TL001"])
        self.assertIn("toPandas", report.findings[0].message)
        self.assertEqual(len(report.graph.links), 1)
        self.assertEqual(report.graph.links[0].location, report.findings[0].location)
        self.assertEqual(len(report.graph.artifacts), 1)

    def test_no_new_findings_leaves_an_empty_requested_graph(self):
        report = Scanner(Config(root=self.root)).scan(
            self.path, changed_from=self.base, include_graph=True
        )
        self.assertEqual(report.findings, ())
        self.assertEqual(report.errors, ())
        self.assertEqual(report.graph, AnalysisGraph())

    def test_invalid_comparison_ref_returns_an_empty_requested_graph(self):
        with patch("torchlight.scanner.scan_file") as scan_file:
            report = Scanner(Config(root=self.root)).scan(
                self.path, changed_from="missing-ref", include_graph=True
            )
        scan_file.assert_not_called()
        self.assertIn("Git comparison error", report.errors[0])
        self.assertEqual(report.graph, AnalysisGraph())
