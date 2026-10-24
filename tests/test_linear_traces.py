# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import json
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

from torchlight.analysis import SparkAnalyzer, parse_source
from torchlight.diagnostics import Location, Rule
from torchlight.graph import GraphArtifact, GraphEdge, GraphFacts, _GraphCollector
from torchlight.identity import call_key
from torchlight.plugins import Diagnostic, Plugin, PluginError, Value

SETUP = (
    "from pyspark.sql import SparkSession, DataFrame\n"
    "spark = SparkSession.builder.getOrCreate()\n"
    "df = spark.read.parquet('events')\n"
)


class LinearTraceTests(unittest.TestCase):
    def capture(self, source, *, max_records=10_000, plugins=(), assume_sessions=()):
        collector = _GraphCollector(
            GraphArtifact("job.py", "python"), max_records=max_records
        )
        analyzer = SparkAnalyzer(
            "job.py", assume_sessions, plugins=plugins, _collector=collector
        )
        findings = analyzer.analyze(parse_source(source, "job.py"), source)
        return findings, collector.build(), analyzer

    def test_sources_aliases_constraints_and_safe_actions_form_receiver_paths(self):
        findings, graph, analyzer = self.capture(
            SETUP + "bounded = df.limit(10)\nalias = bounded\n"
            "filtered = alias.filter('active')\nfiltered.collect()\ndf.collect()\n"
        )
        self.assertEqual(
            [n.kind for n in graph.nodes],
            ["source", "source", "constraint", "transform", "action", "action"],
        )
        session, source, bound, transform, safe, unsafe = graph.nodes
        self.assertEqual(session.after, GraphFacts("session"))
        self.assertEqual(source.before, GraphFacts("reader"))
        self.assertEqual(source.after, GraphFacts("frame"))
        self.assertEqual(bound.before, GraphFacts("frame"))
        self.assertEqual(bound.after, GraphFacts("frame", row_limit=10))
        self.assertEqual(transform.after, bound.after)
        self.assertEqual(safe.before, bound.after)
        self.assertIsNone(safe.after)
        self.assertEqual(unsafe.before, source.after)
        self.assertEqual(
            graph.edges,
            (
                GraphEdge(session.id, source.id, "receiver"),
                GraphEdge(source.id, bound.id, "receiver"),
                GraphEdge(bound.id, transform.id, "receiver"),
                GraphEdge(transform.id, safe.id, "receiver"),
                GraphEdge(source.id, unsafe.id, "receiver"),
            ),
        )
        self.assertEqual([f.rule_id for f in findings], ["TL001"])
        self.assertEqual(graph.anchors[0].node_id, unsafe.id)
        self.assertIs(analyzer.state["alias"], analyzer.state["bounded"])
        self.assertEqual(analyzer.state["df"].trace, source.id)
        self.assertEqual(analyzer.state["filtered"].trace, transform.id)

    def test_row_bound_changes_come_from_existing_inference(self):
        for expression, bound, last_role in (
            ("select('id')", 10, "transform"),
            ("limit(3)", 3, "constraint"),
            ("limit(amount)", 10, "constraint"),
            ("sample(False, 0.5)", 10, "transform"),
            ("sample(True, 2.0)", None, "transform"),
            ("selectExpr('explode(items)')", None, "transform"),
            ("select(expand('items'))", None, "transform"),
            ("groupBy('id').count()", None, "transform"),
            ("agg(expr)", 1, "transform"),
            ("na.drop()", 10, "transform"),
        ):
            with self.subTest(expression=expression):
                findings, graph, analyzer = self.capture(
                    SETUP + "from pyspark.sql.functions import explode as expand\n"
                    "bounded = df.limit(10)\nresult = bounded."
                    + expression
                    + "\nresult.collect()\n"
                )
                operation, action = graph.nodes[-2:]
                self.assertEqual(operation.kind, last_role)
                self.assertEqual(operation.after, GraphFacts("frame", row_limit=bound))
                self.assertEqual(action.before, operation.after)
                self.assertEqual(analyzer.state["result"].trace, operation.id)
                self.assertEqual(
                    [f.rule_id for f in findings], ["TL001"] if bound is None else []
                )

    def test_both_writer_apis_retain_partition_evidence_and_terminal_anchors(self):
        for method, writer, terminal, rule in (
            ("coalesce", "write.mode('overwrite')", "parquet(path)", "TL002"),
            ("repartition", "writeTo('out').using('delta')", "create()", "TL004"),
        ):
            with self.subTest(method=method):
                findings, graph, _ = self.capture(
                    SETUP
                    + f"single = df.{method}(1)\nwriter = single.{writer}\nwriter.{terminal}\n"
                )
                constraint = next(n for n in graph.nodes if n.kind == "constraint")
                sink = graph.nodes[-1]
                self.assertEqual(constraint.after.single_partition, Location(4, 10))
                self.assertEqual(constraint.after.single_partition_method, method)
                self.assertEqual(sink.kind, "sink")
                self.assertEqual(
                    sink.before.kind, "writer" if method == "coalesce" else "writer_v2"
                )
                self.assertEqual(sink.before.single_partition_method, method)
                self.assertIsNone(sink.after)
                self.assertEqual([f.rule_id for f in findings], [rule])
                self.assertEqual(graph.anchors[0].node_id, sink.id)
                self.assertEqual(
                    [n.label for n in graph.nodes if n.kind == "transform"],
                    [".write", ".mode()"]
                    if method == "coalesce"
                    else [".writeTo()", ".using()"],
                )

    def test_clearing_partition_evidence_does_not_claim_multiple_partitions(self):
        for operation in ("repartition(8)", "distinct()", "groupBy('id').count()"):
            with self.subTest(operation=operation):
                findings, graph, _ = self.capture(
                    SETUP
                    + "single = df.coalesce(1)\nresult = single."
                    + operation
                    + "\nresult.write.parquet(path)\n"
                )
                self.assertEqual(findings, [])
                changed = next(
                    n
                    for n in graph.nodes
                    if n.before is not None
                    and n.after is not None
                    and n.before.single_partition is not None
                    and n.after.single_partition is None
                )
                self.assertIsNone(changed.after.single_partition_method)
                self.assertIsNone(graph.nodes[-1].before.single_partition)
                self.assertNotIn(
                    "multiple partitions", " ".join(n.label for n in graph.nodes)
                )

    def test_iterator_and_materializer_aliases_keep_the_original_receiver_path(self):
        findings, graph, analyzer = self.capture(
            SETUP + "stream = df.toLocalIterator()\nalias = stream\n"
            "list(alias)\ntuple(alias)\nconsume = list\nconsume(stream)\n"
            "list(df.limit(2).toLocalIterator())\n"
            "list = custom\nlist(stream)\ntuple(iterable=stream)\n"
        )
        iterator = graph.nodes[2]
        self.assertEqual(iterator.kind, "action")
        self.assertEqual(iterator.after, GraphFacts("local_iterator"))
        self.assertEqual(analyzer.state["stream"].trace, iterator.id)
        eager = [n for n in graph.nodes if "eager iterator materialization" in n.label]
        self.assertEqual(len(eager), 4)
        self.assertEqual([f.rule_id for f in findings], ["TL005"] * 3)
        self.assertEqual([a.node_id for a in graph.anchors], [n.id for n in eager[:3]])
        for operation in eager[:3]:
            self.assertEqual(operation.before, GraphFacts("local_iterator"))
            self.assertIn(GraphEdge(iterator.id, operation.id, "receiver"), graph.edges)
        self.assertEqual(eager[-1].before.row_limit, 2)
        self.assertIsNone(eager[-1].after)

    def test_known_actions_are_not_mistaken_for_frame_return_values(self):
        for method in (
            "collect",
            "count",
            "first",
            "foreach",
            "foreachPartition",
            "head",
            "isEmpty",
            "show",
            "tail",
            "take",
            "toPandas",
        ):
            with self.subTest(method=method):
                findings, graph, analyzer = self.capture(
                    SETUP + f"result = df.{method}()\nresult.collect()\n"
                )
                self.assertEqual(graph.nodes[-1].kind, "action")
                self.assertEqual(graph.nodes[-1].label, f".{method}()")
                self.assertIsNone(graph.nodes[-1].after)
                self.assertNotIn("result", analyzer.state)
                self.assertEqual(
                    [f.rule_id for f in findings],
                    ["TL001"] if method in {"collect", "toPandas"} else [],
                )

    def test_unknown_methods_and_attributes_close_only_the_result_path(self):
        for expression in ("df.custom()", "df.rdd"):
            with self.subTest(expression=expression):
                findings, graph, analyzer = self.capture(
                    SETUP
                    + "result = "
                    + expression
                    + "\nresult.collect()\ndf.collect()\n"
                )
                boundary, action = graph.nodes[-2:]
                self.assertEqual(boundary.kind, "opaque")
                self.assertIsNone(boundary.after)
                self.assertEqual(boundary.before, GraphFacts("frame"))
                self.assertNotIn("result", analyzer.state)
                self.assertEqual(len(findings), 1)
                self.assertEqual(graph.anchors[0].node_id, action.id)
                self.assertEqual(
                    [e.source for e in graph.edges if e.target == action.id],
                    [analyzer.state["df"].trace],
                )
                self.assertFalse(any(e.source == boundary.id for e in graph.edges))
        findings, graph, _ = self.capture("df = custom()\ndf.collect()\n")
        self.assertEqual(findings, [])
        self.assertEqual(graph.nodes, ())

    def test_multi_input_operations_disclose_receiver_only_evidence(self):
        for method in ("join", "union", "unionAll", "unionByName", "subtract"):
            with self.subTest(method=method):
                _, graph, analyzer = self.capture(
                    SETUP
                    + "other = spark.table('other')\nresult = df."
                    + method
                    + "(other)\nresult.collect()\n"
                )
                operation = graph.nodes[-2]
                self.assertIn(
                    "receiver path only; other inputs untracked", operation.label
                )
                self.assertEqual(
                    [e.source for e in graph.edges if e.target == operation.id],
                    [analyzer.state["df"].trace],
                )
                self.assertFalse(
                    any(
                        e.source == analyzer.state["other"].trace
                        and e.target == operation.id
                        for e in graph.edges
                    )
                )

    def test_annotations_and_assumed_sessions_are_not_fabricated_reads(self):
        _, graph, _ = self.capture(
            "from pyspark.sql import DataFrame, SparkSession\n"
            "def run(df: 'DataFrame', session: SparkSession):\n"
            "    df.collect()\n    session.table('events').collect()\n"
            "events: DataFrame = custom()\nevents.collect()\n"
        )
        annotations = [n for n in graph.nodes if n.label.startswith("Annotated")]
        self.assertEqual(
            [n.label for n in annotations],
            [
                "Annotated DataFrame (not a traced read)",
                "Annotated SparkSession",
                "Annotated DataFrame (not a traced read)",
            ],
        )
        self.assertTrue(
            all(n.kind == "source" and n.before is None for n in annotations)
        )
        self.assertFalse(
            any(e.target in {n.id for n in annotations} for e in graph.edges)
        )
        _, assumed, _ = self.capture(
            "spark.table('events').collect()\n", assume_sessions=("spark",)
        )
        self.assertEqual([n.kind for n in assumed.nodes], ["source", "action"])
        self.assertEqual(assumed.nodes[0].before, GraphFacts("session"))

    def test_constructor_and_lookup_sources_use_ast_syntax_not_origin_text(self):
        for expression in (
            "SparkSession(context)",
            "SparkSession.getActiveSession()",
            "SparkSession.getDefaultSession()",
        ):
            with self.subTest(expression=expression):
                _, graph, _ = self.capture(
                    "from pyspark.sql import SparkSession\nsession = "
                    + expression
                    + "\nsession.table('secret-table').collect()\n"
                )
                self.assertEqual(
                    [n.kind for n in graph.nodes], ["source", "source", "action"]
                )
                self.assertEqual(graph.nodes[0].after, GraphFacts("session"))
                self.assertNotIn("secret-table", json.dumps(asdict(graph)))

    def test_duplicate_ids_are_deterministic_and_coordinates_use_characters(self):
        source = SETUP + "é = 1; df.collect()\ndf.collect()\n"
        findings, graph, _ = self.capture(source)
        self.assertEqual(graph, self.capture(source)[1])
        first, second = graph.nodes[-2:]
        self.assertEqual(first.key, second.key)
        self.assertNotEqual(first.id, second.id)
        self.assertTrue(first.id.endswith("-1"))
        self.assertTrue(second.id.endswith("-2"))
        self.assertEqual(first.location, Location(4, 8))
        self.assertEqual(first.location, findings[0].location)
        shifted = self.capture(
            "\n# shifted\n" + source.replace("collect()", "collect( )")
        )[1]
        self.assertEqual([n.id for n in graph.nodes], [n.id for n in shifted.nodes])

    def test_finding_and_trace_reuse_the_same_structural_key(self):
        with patch("torchlight.analysis.call_key", wraps=call_key) as keys:
            findings, graph, _ = self.capture(SETUP + "df.collect()\n")
        self.assertEqual([finding.rule_id for finding in findings], ["TL001"])
        self.assertEqual(keys.call_count, len(graph.nodes))

    def test_matching_roles_and_keys_do_not_depend_on_incoming_bounds(self):
        graphs = [
            self.capture(
                SETUP
                + f"input = {expression}\nresult = input.select('id')\nresult.collect()\n"
            )[1]
            for expression in ("df", "df.limit(1)")
        ]
        unbounded, bounded = graphs
        self.assertEqual(
            [n.key for n in unbounded.nodes[-2:]], [n.key for n in bounded.nodes[-2:]]
        )
        self.assertEqual([n.kind for n in bounded.nodes[-2:]], ["transform", "action"])
        self.assertIsNone(unbounded.nodes[-1].before.row_limit)
        self.assertEqual(bounded.nodes[-1].before.row_limit, 1)

    def test_divergent_trace_uses_alternatives_without_fabricated_sequences(self):
        findings, graph, _ = self.capture(
            SETUP
            + "if condition:\n    result = df.limit(1)\nelse:\n    result = df\nresult.collect()\n"
        )
        self.assertEqual([f.rule_id for f in findings], ["TL001"])
        action = graph.nodes[-1]
        merge = graph.nodes[-2]
        self.assertEqual(merge.kind, "merge")
        self.assertIn("Analyzed alternatives (not a sequence)", merge.label)
        self.assertEqual(
            [e.relation for e in graph.edges if e.target == merge.id],
            ["alternative", "alternative"],
        )
        self.assertIn(GraphEdge(merge.id, action.id, "receiver"), graph.edges)

    def test_plugin_anchors_follow_last_diagnostic_without_inventing_plugin_edges(self):
        detector = Mock(rule_id="LOCAL001")
        detector.check.return_value = (
            Diagnostic("LOCAL001", ("opaque plugin evidence",)),
        )
        plugin = Plugin(
            Rule("LOCAL001", "Record calls", "Test only.", "No action."), detector
        )
        findings, graph, _ = self.capture(
            SETUP + "df.select('id').collect()\n", plugins=(plugin,)
        )
        calls = [call.args[0] for call in detector.check.call_args_list]
        self.assertTrue(all(type(f.receiver) is Value for f in calls))
        self.assertEqual(len(graph.anchors), len(findings))
        for finding in findings:
            anchor = next(
                a
                for a in graph.anchors
                if a.rule_id == finding.rule_id and a.location == finding.location
            )
            operation = next(n for n in graph.nodes if n.id == anchor.node_id)
            self.assertEqual(operation.location, finding.location)
        local = next(
            a for a in graph.anchors if a.rule_id == "LOCAL001" and a.location.line == 4
        )
        self.assertEqual(local.node_id, graph.nodes[-1].id)
        self.assertEqual(findings[-1].rule_id, "TL001")
        self.assertNotIn(
            "opaque plugin evidence", " ".join(n.label for n in graph.nodes)
        )

    def test_plugin_errors_propagate_identically_with_capture_enabled(self):
        detector = Mock(rule_id="LOCAL001")
        detector.check.side_effect = RuntimeError("private error")
        plugin = Plugin(
            Rule("LOCAL001", "Record calls", "Test only.", "No action."), detector
        )
        with self.assertRaisesRegex(
            PluginError, "plugin LOCAL001 failed \\(RuntimeError\\)"
        ):
            self.capture(SETUP, plugins=(plugin,))

    def test_python_corpus_findings_and_semantic_state_are_unchanged(self):
        cases = json.loads(
            (
                Path(__file__).resolve().parents[1] / "benchmarks" / "cases.json"
            ).read_text(encoding="utf-8")
        )["cases"]
        for case in cases:
            if "source" not in case:
                continue
            with self.subTest(case=case["name"]):
                source = "\n".join(case["source"]) + "\n"
                assumptions = tuple(case.get("assume_sessions", ()))
                plain = SparkAnalyzer("job.py", assumptions)
                expected = plain.analyze(parse_source(source, "job.py"), source)
                actual, graph, captured = self.capture(
                    source, assume_sessions=assumptions
                )
                self.assertEqual(actual, expected)
                self.assertEqual(
                    {k: v.value for k, v in captured.state.items()},
                    {k: v.value for k, v in plain.state.items()},
                )
                self.assertTrue(graph.capture_complete)
