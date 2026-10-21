# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import ast
import contextlib
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
from unittest.mock import patch

from torchlight import Scanner
from torchlight.diagnostics import Location
from torchlight.graph import (
    AnalysisGraph,
    CaptureLimit,
    FindingAnchor,
    GraphArtifact,
    GraphEdge,
    GraphFacts,
    GraphNode,
    _GraphCollector,
)
from torchlight.identity import call_key


def structural_key(source):
    tree = ast.parse(source)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    return call_key(
        next(node for node in ast.walk(tree) if isinstance(node, ast.Call)), parents
    )


class GraphTests(unittest.TestCase):
    def collector(self, path="job.py", source_kind="python", **kwargs):
        return _GraphCollector(GraphArtifact(path, source_kind), **kwargs)

    def source(self, collector, key="source"):
        return collector.add_node(
            "source", "Spark reader", structural_key=key, after=GraphFacts("frame")
        )

    def pipeline(self):
        collector = self.collector()
        source = self.source(collector)
        single = GraphFacts(
            "frame", single_partition=Location(2), single_partition_method="coalesce"
        )
        constraint = collector.add_node(
            "constraint",
            "coalesce(1)",
            structural_key="coalesce",
            location=Location(2),
            parents=((source, "receiver"),),
            before=GraphFacts("frame"),
            after=single,
        )
        sink = collector.add_node(
            "sink",
            "write.parquet()",
            structural_key="write",
            location=Location(3),
            parents=((constraint, "receiver"),),
            before=replace(single, kind="writer"),
        )
        collector.anchor("TL002", Location(3), sink)
        return collector

    def test_snapshots_are_immutable_detached_and_deterministic(self):
        collector = self.pipeline()
        graph = collector.build()
        self.assertEqual(graph, self.pipeline().build())
        self.assertEqual(
            json.dumps(asdict(graph)), json.dumps(asdict(self.pipeline().build()))
        )
        self.assertEqual(
            [node.kind for node in graph.nodes], ["source", "constraint", "sink"]
        )
        self.assertTrue(graph.capture_complete)
        for record, attribute in (
            (graph, "nodes"),
            (graph.artifacts[0], "path"),
            (graph.nodes[0], "label"),
            (graph.nodes[0].after, "kind"),
            (graph.edges[0], "relation"),
            (graph.anchors[0], "node_id"),
            (CaptureLimit(graph.artifacts[0].id, 1), "max_records"),
        ):
            with (
                self.subTest(record=type(record).__name__),
                self.assertRaises(FrozenInstanceError),
            ):
                setattr(record, attribute, "changed")
        detached = asdict(graph)
        detached["nodes"][0]["label"] = "changed"
        self.source(collector, "another-source")
        self.assertEqual(len(graph.nodes), 3)
        self.assertEqual(graph.nodes[0].label, "Spark reader")

    def test_graph_snapshots_caller_owned_sequences(self):
        original = self.pipeline().build()
        fields = {
            name: list(getattr(original, name))
            for name in ("artifacts", "nodes", "edges", "anchors", "limits")
        }
        graph = AnalysisGraph(**fields)
        for items in fields.values():
            items.clear()
        self.assertEqual(graph, original)

    def test_ids_ignore_coordinates_labels_and_facts_not_occurrences(self):
        first, second = (
            self.collector("job.ipynb", "jupyter"),
            self.collector("job.ipynb", "jupyter"),
        )
        key = structural_key("df.collect()")
        first_id = first.add_node(
            "action", "collect", structural_key=key, location=Location(1, 1, 1)
        )
        self.source(second, "unrelated-call")
        second_id = second.add_node(
            "action",
            "new label",
            structural_key=structural_key("\n# moved\ndf.collect( )"),
            location=Location(9, 3, 4),
            before=GraphFacts("frame", row_limit=10),
        )
        duplicate = second.add_node("action", "collect", structural_key=key)
        self.assertEqual(first_id, second_id)
        self.assertNotEqual(second_id, duplicate)
        self.assertTrue(second_id.endswith("-1"))
        self.assertTrue(duplicate.endswith("-2"))
        self.assertEqual(second.build().nodes[-2].key, second.build().nodes[-1].key)

    def test_matching_keys_distinguish_roles_calls_and_scopes_not_artifact_paths(self):
        collectors = [
            self.collector(),
            self.collector("renamed.py"),
            self.collector("job.py", "databricks"),
        ]
        for collector in collectors:
            collector.add_node(
                "action", "collect", structural_key=structural_key("df.collect()")
            )
        nodes = [collector.build().nodes[0] for collector in collectors]
        self.assertEqual(len({node.id for node in nodes}), 3)
        self.assertEqual(len({node.key for node in nodes}), 1)
        collector = collectors[0]
        for kind, source in (
            ("transform", "df.collect()"),
            ("action", "df.toPandas()"),
            ("action", "def job():\n    df.collect()"),
        ):
            collector.add_node(kind, "call", structural_key=structural_key(source))
        self.assertEqual(len({node.key for node in collector.build().nodes}), 4)
        self.assertRegex(nodes[0].id, r"^n-[0-9a-f]{64}-1$")

    def test_alternatives_and_control_edges_are_explicit_and_deduplicated(self):
        collector = self.collector()
        left, right = self.source(collector, "left"), self.source(collector, "right")
        merged = collector.add_node(
            "merge",
            "Analyzed alternatives",
            structural_key="if",
            parents=(
                (right, "alternative"),
                (left, "alternative"),
                (left, "alternative"),
            ),
        )
        collector.add_node(
            "loop",
            "Potentially repeated",
            structural_key="loop",
            parents=((merged, "control"),),
        )
        graph = collector.build()
        self.assertEqual(len(graph.edges), 3)
        self.assertEqual(
            [edge.relation for edge in graph.edges],
            ["alternative", "alternative", "control"],
        )
        self.assertEqual(
            [edge.source for edge in graph.edges[:2]], sorted((left, right))
        )

    def test_opaque_nodes_can_lack_coordinates_and_anchors_can_lack_traces(self):
        collector = self.collector("job.ipynb", "jupyter")
        collector.add_node("opaque", "Unparseable cell", structural_key="opaque")
        self.assertTrue(collector.anchor("TL001", Location(1, 1, 2), None))
        graph = collector.build()
        self.assertIsNone(graph.nodes[0].location)
        self.assertIsNone(graph.anchors[0].node_id)
        self.assertEqual(graph.artifacts[0].source_kind, "jupyter")

    def test_unknown_parents_and_invalid_relations_are_rejected_atomically(self):
        collector = self.collector()
        with self.assertRaisesRegex(ValueError, "unknown node"):
            collector.add_node(
                "transform",
                "filter",
                structural_key="filter",
                parents=(("missing", "receiver"),),
            )
        source = self.source(collector)
        with self.assertRaisesRegex(ValueError, "edge relation"):
            collector.add_node(
                "transform",
                "filter",
                structural_key="filter",
                parents=((source, "dataflow"),),
            )
        self.assertEqual(len(collector.build().nodes), 1)
        with self.assertRaisesRegex(ValueError, "unknown node"):
            collector.anchor("TL001", Location(2), "missing")
        self.assertEqual(collector.build().anchors, ())

    def test_capture_limit_rejects_whole_operations_and_stops_growth(self):
        collector = self.collector(max_records=2)
        source = self.source(collector)
        self.assertIsNone(
            collector.add_node(
                "action",
                "collect",
                structural_key="collect",
                parents=((source, "receiver"),),
            )
        )
        for number in range(20):
            self.assertIsNone(self.source(collector, str(number)))
            self.assertFalse(collector.anchor("TL001", Location(number + 1), None))
        graph = collector.build()
        self.assertEqual(len(graph.nodes), 1)
        self.assertEqual(graph.edges, ())
        self.assertEqual(graph.anchors, ())
        self.assertEqual(len(collector._occurrences), 1)
        self.assertFalse(graph.capture_complete)
        self.assertEqual(graph.limits, (CaptureLimit(graph.artifacts[0].id, 2),))

    def test_anchor_budget_and_last_diagnostic_wins_without_growing(self):
        collector = self.collector(max_records=2)
        source = self.source(collector)
        self.assertTrue(collector.anchor("TL001", Location(2), source))
        previous = collector.build()
        self.assertTrue(collector.anchor("TL001", Location(2), None))
        self.assertTrue(collector.build().capture_complete)
        self.assertIsNone(collector.build().anchors[0].node_id)
        self.assertEqual(previous.anchors[0].node_id, source)
        self.assertFalse(collector.anchor("TL001", Location(3), None))
        self.assertFalse(collector.build().capture_complete)

    def test_exact_budget_accepts_node_with_all_edges_and_build_is_read_only(self):
        collector = self.collector(max_records=3)
        source = self.source(collector)
        action = collector.add_node(
            "action",
            "collect",
            structural_key="collect",
            parents=((source, "receiver"),),
        )
        self.assertIsNotNone(action)
        graph = collector.build()
        self.assertEqual(graph, collector.build())
        self.assertEqual(len(graph.nodes), 2)
        self.assertEqual(graph.edges, (GraphEdge(source, action, "receiver"),))
        self.assertTrue(graph.capture_complete)
        self.assertFalse(collector.anchor("TL001", Location(3), action))
        self.assertFalse(collector.build().capture_complete)
        self.assertTrue(graph.capture_complete)

    def test_graph_rejects_duplicate_ids_and_dangling_or_foreign_references(self):
        graph = self.pipeline().build()
        foreign = GraphArtifact("other.py", "python")
        foreign_node = replace(
            graph.nodes[0], id="foreign-node", artifact_id=foreign.id
        )
        cases = (
            {"artifacts": (*graph.artifacts, graph.artifacts[0])},
            {"nodes": (*graph.nodes, graph.nodes[0])},
            {"nodes": (*graph.nodes, foreign_node)},
            {"edges": (*graph.edges, graph.edges[0])},
            {"edges": (GraphEdge("missing", graph.nodes[0].id, "receiver"),)},
            {
                "artifacts": (*graph.artifacts, foreign),
                "nodes": (*graph.nodes, foreign_node),
                "edges": (GraphEdge(graph.nodes[0].id, foreign_node.id, "receiver"),),
            },
            {"anchors": (*graph.anchors, graph.anchors[0])},
            {"anchors": (replace(graph.anchors[0], artifact_id="missing"),)},
            {"anchors": (replace(graph.anchors[0], node_id="missing"),)},
            {
                "artifacts": (*graph.artifacts, foreign),
                "anchors": (replace(graph.anchors[0], artifact_id=foreign.id),),
            },
            {"limits": (CaptureLimit("missing", 1),)},
            {
                "limits": (
                    CaptureLimit(graph.artifacts[0].id, 1),
                    CaptureLimit(graph.artifacts[0].id, 2),
                )
            },
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                replace(graph, **overrides)

    def test_invalid_metadata_and_budgets_are_rejected(self):
        for value in (0, -1, True, "10", 1.5):
            with self.subTest(limit=value), self.assertRaises(ValueError):
                self.collector(max_records=value)
        for value in (-1, True, 1.5):
            with self.subTest(bound=value), self.assertRaises(ValueError):
                GraphFacts("frame", row_limit=value)
        for kwargs in (
            {"single_partition": Location(1)},
            {"single_partition_method": "coalesce"},
            {"single_partition": Location(1), "single_partition_method": "shuffle"},
        ):
            with self.subTest(facts=kwargs), self.assertRaises(ValueError):
                GraphFacts("frame", **kwargs)
        with self.assertRaises(ValueError):
            GraphArtifact("", "python")
        with self.assertRaises(ValueError):
            GraphArtifact("job.py", "ipynb")
        with self.assertRaises(ValueError):
            GraphEdge("source", "target", "execution")
        with self.assertRaises(ValueError):
            GraphNode("node", "artifact", "execution", "label", "key")
        collector = self.collector()
        for kind, key in (("execution", "key"), ("source", "")):
            with self.subTest(kind=kind, key=key), self.assertRaises(ValueError):
                collector.add_node(kind, "label", structural_key=key)

    def test_default_scan_never_allocates_graph_records_or_collectors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job.py"
            path.write_text(
                "from pyspark.sql import SparkSession, DataFrame\n"
                "df = SparkSession.builder.getOrCreate().table('events')\n"
                "df.collect()\nlist(df.toLocalIterator())\n"
                "df.coalesce(1).write.mode('overwrite').parquet('out')\n"
                "df.repartition(1).writeTo('target').create()\n"
                "for column in columns:\n    df = df.withColumn(column, expr)\n"
                "def job(events: DataFrame):\n    events.collect()\n"
                "if condition:\n    bounded = df.limit(1)\nelse:\n    bounded = df.limit(2)\n"
                "branch = df if condition else df\ncondition and (alias := df)\n"
                "try:\n    bounded = df.limit(1)\nexcept Exception:\n    bounded = df.limit(2)\n"
                "match item:\n    case _:\n        bounded = df.limit(1)\n"
                "result = custom(df)\n[df.count() for item in items]\n",
                encoding="utf-8",
            )
            with contextlib.ExitStack() as stack:
                for record in (
                    AnalysisGraph,
                    GraphArtifact,
                    GraphNode,
                    GraphEdge,
                    GraphFacts,
                    FindingAnchor,
                    CaptureLimit,
                    _GraphCollector,
                ):
                    stack.enter_context(
                        patch.object(
                            record,
                            "__init__",
                            side_effect=AssertionError(
                                "default scan allocated graph data"
                            ),
                        )
                    )
                report = Scanner().scan(path)
            self.assertEqual(report.errors, ())
            self.assertEqual(
                [f.rule_id for f in report.findings],
                ["TL001", "TL005", "TL002", "TL004", "TL003", "TL001"],
            )
