# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import unittest

from torchlight.analysis import SparkAnalyzer, _TrackedValue, parse_source
from torchlight.diagnostics import Location, Rule
from torchlight.graph import GraphArtifact, GraphEdge, GraphFacts, _GraphCollector
from torchlight.plugins import Plugin, PluginError, Value

SETUP = (
    "from pyspark.sql import SparkSession, DataFrame\n"
    "spark = SparkSession.builder.getOrCreate()\n"
    "df = spark.table('events')\n"
)


class Recorder:
    rule_id = "LOCAL001"

    def __init__(self):
        self.facts = []

    def check(self, facts):
        self.facts.append(facts)
        return ()


class ControlTraceTests(unittest.TestCase):
    def analyze(self, source, budget=10_000):
        source = SETUP + source
        observed = []
        for enabled in (False, True):
            recorder = Recorder()
            collector = (
                _GraphCollector(GraphArtifact("job.py", "python"), max_records=budget)
                if enabled
                else None
            )
            plugin = Plugin(
                Rule("LOCAL001", "Record facts", "Test only.", "No action."), recorder
            )
            analyzer = SparkAnalyzer("job.py", plugins=(plugin,), _collector=collector)
            findings = analyzer.analyze(parse_source(source, "job.py"), source)
            observed.append(
                (
                    findings,
                    recorder.facts,
                    {k: v.value for k, v in analyzer.state.items()},
                )
            )
            self.assertEqual(analyzer._controls, [])
            self.assertEqual(analyzer.loop_ids, [])
            self.assertEqual(analyzer.assignment_targets, set())
        self.assertEqual(observed[0], observed[1])
        graph = collector.build()
        indices = {n.id: i for i, n in enumerate(graph.nodes)}
        self.assertTrue(all(indices[e.source] < indices[e.target] for e in graph.edges))
        self.assertLessEqual(
            len(graph.nodes) + len(graph.edges) + len(graph.anchors), budget
        )
        for facts in recorder.facts:
            self.assertIs(type(facts.receiver), Value)
        return findings, graph, analyzer

    def incoming(self, graph, node, relation):
        return {
            e.source
            for e in graph.edges
            if e.target == node.id and e.relation == relation
        }

    def test_equal_semantics_different_paths_have_alternative_not_receiver_edges(self):
        findings, graph, analyzer = self.analyze(
            "if condition:\n    result = df.select('id')\nelse:\n    result = df.filter('active')\n"
            "result.collect()\ndf.collect()\n"
        )
        select, filter_ = [n for n in graph.nodes if n.kind == "transform"]
        merge = next(
            n for n in graph.nodes if n.after is not None and n.kind == "merge"
        )
        source = graph.nodes[1]
        self.assertEqual(select.after, filter_.after)
        self.assertEqual(merge.after, GraphFacts("frame"))
        self.assertEqual(
            self.incoming(graph, merge, "alternative"), {select.id, filter_.id}
        )
        self.assertEqual(self.incoming(graph, merge, "receiver"), set())
        self.assertNotIn(GraphEdge(select.id, filter_.id, "receiver"), graph.edges)
        self.assertEqual(analyzer.state["result"].trace, merge.id)
        self.assertEqual(analyzer.state["df"].trace, source.id)
        self.assertEqual([f.rule_id for f in findings], ["TL001", "TL001"])
        self.assertNotEqual(
            self.incoming(graph, select, "control"),
            self.incoming(graph, filter_, "control"),
        )

    def test_shared_endpoint_needs_no_fabricated_merge(self):
        _, graph, analyzer = self.analyze(
            "result = df\nif condition:\n    result = df\nresult.collect()\n"
        )
        self.assertEqual(analyzer.state["result"].trace, analyzer.state["df"].trace)
        self.assertFalse(
            any(n.kind == "merge" and n.after is not None for n in graph.nodes)
        )

    def test_merging_partition_and_iterator_paths_does_not_add_inference(self):
        findings, graph, _ = self.analyze(
            "if condition:\n    result = df.coalesce(1)\nelse:\n    result = df.repartition(1)\n"
            "result.write.parquet('out')\n"
            "stream = df.toLocalIterator() if condition else df.toLocalIterator()\nlist(stream)\n"
        )
        self.assertEqual([f.rule_id for f in findings], ["TL005"])
        merge = next(
            n for n in graph.nodes if n.kind == "merge" and n.after is not None
        )
        self.assertEqual(merge.after, GraphFacts("frame"))
        iterator_merge = next(
            n
            for n in graph.nodes
            if n.kind == "merge" and n.after == GraphFacts("local_iterator")
        )
        self.assertEqual(len(self.incoming(graph, iterator_merge, "alternative")), 2)
        findings, graph, _ = self.analyze(
            "stream = (df.toLocalIterator()\n    if condition else df.toLocalIterator())\nlist(stream)\n"
        )
        self.assertEqual(findings, [])
        self.assertTrue(
            any(
                n.kind == "opaque" and "identity not established" in n.label
                for n in graph.nodes
            )
        )

    def test_direct_terminators_stop_capture_without_new_reachability_inference(self):
        for terminator in ("return", "raise Error", "break", "continue"):
            with self.subTest(terminator=terminator):
                _, graph, _ = self.analyze(
                    "def run():\n    for column in columns:\n        df.count()\n        "
                    + terminator
                    + "\n        df.collect()\n"
                )
                self.assertFalse(any(n.label == ".collect()" for n in graph.nodes))

    def test_conditional_expression_merges_result_and_walrus_bindings(self):
        findings, graph, analyzer = self.analyze(
            "result = (alias := df.limit(1)) if condition else (alias := df.limit(4))\n"
            "result.collect()\nalias.collect()\n"
        )
        self.assertEqual(findings, [])
        merges = [n for n in graph.nodes if n.kind == "merge" and n.after is not None]
        self.assertEqual(len(merges), 2)
        self.assertTrue(all(n.after.row_limit == 4 for n in merges))
        self.assertTrue(
            all(len(self.incoming(graph, n, "alternative")) == 2 for n in merges)
        )
        self.assertEqual(
            {analyzer.state[k].trace for k in ("result", "alias")},
            {n.id for n in merges},
        )

    def test_boolean_short_circuit_state_is_an_alternative_but_result_stays_unknown(
        self,
    ):
        for operator in ("and", "or"):
            with self.subTest(operator=operator):
                findings, graph, analyzer = self.analyze(
                    f"result = df\ncondition {operator} (result := df.limit(1))\n"
                    f"unknown_result = df {operator} df.limit(2)\nresult.collect()\nunknown_result.collect()\n"
                )
                self.assertEqual([f.rule_id for f in findings], ["TL001"])
                self.assertNotIn("unknown_result", analyzer.state)
                merge = next(
                    n for n in graph.nodes if n.kind == "merge" and n.after is not None
                )
                self.assertEqual(merge.after, GraphFacts("frame"))
                self.assertEqual(len(self.incoming(graph, merge, "alternative")), 2)
                self.assertTrue(
                    any(
                        n.kind == "opaque" and "Boolean result" in n.label
                        for n in graph.nodes
                    )
                )

    def test_try_handlers_and_else_merge_without_sequencing_exceptions(self):
        for except_ in ("except", "except*"):
            with self.subTest(except_=except_):
                findings, graph, _ = self.analyze(
                    "try:\n    result = df.limit(1)\n"
                    f"{except_} ValueError as error:\n    result = df.limit(2)\n"
                    f"{except_} TypeError:\n    result = df.limit(3)\n"
                    "else:\n    result = result.select('id')\n"
                    "finally:\n    df.count()\nresult.collect()\n"
                )
                self.assertEqual(findings, [])
                merge = next(
                    n for n in graph.nodes if n.kind == "merge" and n.after is not None
                )
                self.assertEqual(merge.after.row_limit, 3)
                self.assertEqual(len(self.incoming(graph, merge, "alternative")), 3)
                count = next(n for n in graph.nodes if n.label == ".count()")
                self.assertEqual(self.incoming(graph, count, "control"), set())
                handlers = [
                    n for n in graph.nodes if n.label.startswith("Exception handler")
                ]
                self.assertEqual(len(handlers), 2)

    def test_try_written_names_are_not_reused_in_handler(self):
        findings, graph, analyzer = self.analyze(
            "result = df\ntry:\n    result = df.limit(1)\n"
            "except Exception:\n    result.collect()\nresult.collect()\n"
        )
        self.assertEqual(findings, [])
        self.assertNotIn("result", analyzer.state)
        self.assertTrue(
            any(
                n.kind == "opaque" and "result identity not established" in n.label
                for n in graph.nodes
            )
        )
        self.assertFalse(any(n.label == ".collect()" for n in graph.nodes))

    def test_match_exhaustive_and_unmatched_paths_keep_existing_bound_rules(self):
        for ending, bound in (
            ("case _:\n        result = df.limit(2)\n", 2),
            ("case 2 if guard:\n        result = df.limit(2)\n", None),
        ):
            with self.subTest(bound=bound):
                findings, graph, _ = self.analyze(
                    "result = df\nmatch item:\n    case 1:\n        result = df.limit(1)\n    "
                    + ending
                    + "result.collect()\n"
                )
                merge = next(
                    n for n in graph.nodes if n.kind == "merge" and n.after is not None
                )
                self.assertEqual(merge.after.row_limit, bound)
                self.assertEqual(
                    len(self.incoming(graph, merge, "alternative")), 2 if bound else 3
                )
                self.assertEqual(
                    [f.rule_id for f in findings], [] if bound else ["TL001"]
                )

    def test_missing_or_incompatible_alternative_closes_result_not_independent_input(
        self,
    ):
        for other in ("custom(df)", "spark", "unknown", "df.toLocalIterator()"):
            with self.subTest(other=other):
                findings, graph, analyzer = self.analyze(
                    "if condition:\n    result = df\nelse:\n    result = "
                    + other
                    + "\n"
                    "result.collect()\ndf.collect()\n"
                )
                self.assertNotIn("result", analyzer.state)
                self.assertEqual([f.rule_id for f in findings], ["TL001"])
                boundaries = [
                    n
                    for n in graph.nodes
                    if n.kind == "opaque" and "identity not established" in n.label
                ]
                self.assertEqual(len(boundaries), 1)
                self.assertIsNone(boundaries[0].after)
                self.assertFalse(any(e.source == boundaries[0].id for e in graph.edges))
                self.assertEqual(
                    self.incoming(graph, graph.nodes[-1], "receiver"),
                    {analyzer.state["df"].trace},
                )

    def test_identity_loss_without_any_finding_remains_a_boundary(self):
        findings, graph, analyzer = self.analyze(
            "result = df if condition else unknown\nresult.collect()\n"
        )
        self.assertEqual(findings, [])
        self.assertNotIn("result", analyzer.state)
        self.assertEqual(graph.nodes[-1].kind, "opaque")
        self.assertEqual(len(self.incoming(graph, graph.nodes[-1], "alternative")), 1)
        self.assertIn("some alternatives untracked", graph.nodes[-1].label)

    def test_replacing_input_and_wildcard_invalidation_keep_explicit_boundaries(self):
        findings, graph, analyzer = self.analyze(
            "alias = df\ndf = custom(df)\ndf.collect()\nalias.collect()\n"
        )
        self.assertEqual([f.rule_id for f in findings], ["TL001"])
        self.assertNotIn("df", analyzer.state)
        boundary = next(n for n in graph.nodes if n.kind == "opaque")
        self.assertFalse(any(e.source == boundary.id for e in graph.edges))
        findings, graph, analyzer = self.analyze("from custom import *\ndf.collect()\n")
        self.assertEqual(findings, [])
        self.assertEqual(analyzer.state, {})
        self.assertIn("previous bindings invalidated", graph.nodes[-1].label)

    def test_known_dead_paths_are_not_captured(self):
        findings, graph, _ = self.analyze(
            "if False:\n    df.collect()\n"
            "False and df.collect()\nTrue or df.collect()\n"
            "result = df.limit(1) if True else df.collect()\n"
            "for item in []:\n    df.collect()\n"
            "while False:\n    df.collect()\nresult.collect()\n"
        )
        self.assertEqual(findings, [])
        self.assertEqual(
            [n.kind for n in graph.nodes], ["source", "source", "constraint", "action"]
        )

    def test_nested_loop_summaries_anchor_tl003_to_transforms_not_invented_actions(
        self,
    ):
        findings, graph, analyzer = self.analyze(
            "for outer in columns:\n"
            "    df = df.withColumn(outer, expr)\n"
            "    for inner in columns:\n        df = df.withColumn(inner, expr)\n"
            "    df = df.withColumn(outer, expr)\n"
        )
        self.assertEqual([f.rule_id for f in findings], ["TL003"] * 3)
        loops = [n for n in graph.nodes if n.kind == "loop"]
        self.assertEqual(len(loops), 2)
        self.assertTrue(all("iteration count not observed" in n.label for n in loops))
        self.assertEqual(self.incoming(graph, loops[1], "control"), {loops[0].id})
        transforms = [n for n in graph.nodes if n.kind == "transform"]
        self.assertEqual([a.node_id for a in graph.anchors], [n.id for n in transforms])
        self.assertEqual(
            [self.incoming(graph, n, "control") for n in transforms],
            [{loops[0].id}, {loops[1].id}, {loops[0].id}],
        )
        self.assertFalse(any(n.kind == "action" for n in graph.nodes))
        self.assertEqual(analyzer.state["df"].value.loop_origins, frozenset())

    def test_while_async_for_and_loop_else_do_not_leak_control_to_following_calls(self):
        for header in (
            "while condition:",
            "async for column in columns:",
            "for column in columns:",
        ):
            with self.subTest(header=header):
                findings, graph, _ = self.analyze(
                    header + "\n    df = df.withColumn(column, expr)\n"
                    "else:\n    df.count()\ndf.collect()\n"
                )
                self.assertEqual([f.rule_id for f in findings], ["TL003", "TL001"])
                self.assertEqual(
                    self.incoming(graph, graph.nodes[-1], "control"), set()
                )
                count = next(n for n in graph.nodes if n.label == ".count()")
                parent = next(
                    n
                    for n in graph.nodes
                    if n.id in self.incoming(graph, count, "control")
                )
                self.assertIn("Loop else", parent.label)

    def test_single_iteration_break_and_fresh_frames_do_not_gain_tl003(self):
        for body in (
            "for column in [1]:\n    df = df.withColumn(column, expr)\n",
            "for column in columns:\n    df = df.withColumn(column, expr)\n    break\n",
            "for column in columns:\n    fresh = spark.table('other')\n    fresh = fresh.withColumn(column, expr)\n",
        ):
            with self.subTest(body=body):
                findings, graph, _ = self.analyze(body)
                self.assertEqual(findings, [])
                self.assertEqual(len([n for n in graph.nodes if n.kind == "loop"]), 1)

    def test_scopes_restore_receiver_and_control_but_do_not_inherit_outer_loop(self):
        for scope in (
            "def run(value=df.limit(1)):\n        df.collect()\n",
            "async def run(value=df.limit(1)):\n        df.collect()\n",
            "class Job:\n        df.collect()\n",
            "run = lambda: df.collect()\n",
        ):
            with self.subTest(scope=scope):
                _, graph, analyzer = self.analyze(
                    "for item in items:\n    "
                    + scope
                    + "    df.count()\ndf.collect()\n"
                )
                actions = [n for n in graph.nodes if n.kind == "action"]
                self.assertEqual(
                    [n.label for n in actions], [".collect()", ".count()", ".collect()"]
                )
                self.assertEqual(self.incoming(graph, actions[0], "control"), set())
                self.assertEqual(self.incoming(graph, actions[2], "control"), set())
                loop = next(n for n in graph.nodes if n.kind == "loop")
                self.assertEqual(self.incoming(graph, actions[1], "control"), {loop.id})
                self.assertTrue(
                    all(
                        self.incoming(graph, n, "receiver")
                        == {analyzer.state["df"].trace}
                        for n in actions
                    )
                )
                for default in [n for n in graph.nodes if n.kind == "constraint"]:
                    self.assertEqual(
                        self.incoming(graph, default, "control"), {loop.id}
                    )

    def test_comprehensions_restore_targets_and_record_nested_static_context(self):
        for expression in (
            "[df.count() for df in items]",
            "{df.count() for df in items}",
            "{df: df.count() for df in items}",
            "(df.count() for df in items)",
        ):
            with self.subTest(expression=expression):
                _, graph, _ = self.analyze(expression + "\ndf.collect()\n")
                self.assertEqual(
                    [n.label for n in graph.nodes if n.kind == "action"], [".collect()"]
                )
                self.assertEqual(
                    self.incoming(graph, graph.nodes[-1], "control"), set()
                )
        _, graph, _ = self.analyze(
            "[df.count() for outer in items for inner in items if df.count()]\ndf.collect()\n"
        )
        loops = [n for n in graph.nodes if n.kind == "loop"]
        self.assertEqual(self.incoming(graph, loops[1], "control"), {loops[0].id})
        self.assertTrue(
            all(
                self.incoming(graph, n, "control") == {loops[1].id}
                for n in graph.nodes
                if n.label == ".count()"
            )
        )

    def test_annotations_and_class_method_lookup_keep_scope_boundaries(self):
        findings, graph, analyzer = self.analyze(
            "for item in items:\n"
            "    def run(df: DataFrame):\n        df.collect()\n"
            "    class Job:\n        df = df.limit(1)\n"
            "        def run(self):\n            df.collect()\n"
            "df.collect()\n"
        )
        self.assertEqual([f.rule_id for f in findings], ["TL001"] * 3)
        annotation = next(
            n for n in graph.nodes if n.label.startswith("Annotated DataFrame")
        )
        self.assertEqual(self.incoming(graph, annotation, "control"), set())
        actions = [n for n in graph.nodes if n.kind == "action"]
        self.assertEqual(self.incoming(graph, actions[0], "receiver"), {annotation.id})
        self.assertTrue(
            all(
                self.incoming(graph, n, "receiver") == {analyzer.state["df"].trace}
                for n in actions[1:]
            )
        )

    def test_opaque_arguments_are_context_not_receiver_or_alternative_lineage(self):
        for expression in (
            "custom(df)",
            "custom(data=df)",
            "unknown.custom(df)",
            "sql.custom(df)",
            "custom(df, df.limit(1))",
            "df[columns]",
            "await df",
            "[df]",
        ):
            with self.subTest(expression=expression):
                findings, graph, analyzer = self.analyze(
                    "import pyspark.sql as sql\nresult = "
                    + expression
                    + "\nresult.collect()\ndf.collect()\n"
                )
                boundary = next(n for n in graph.nodes if n.kind == "opaque")
                self.assertEqual([f.rule_id for f in findings], ["TL001"])
                self.assertNotIn("result", analyzer.state)
                self.assertIsNone(boundary.after)
                self.assertTrue(self.incoming(graph, boundary, "control"))
                self.assertEqual(self.incoming(graph, boundary, "receiver"), set())
                self.assertEqual(self.incoming(graph, boundary, "alternative"), set())
                self.assertFalse(any(e.source == boundary.id for e in graph.edges))

    def test_unsupported_receiver_kinds_end_in_boundary_without_granting_identity(self):
        for receiver in (
            "spark",
            "spark.read",
            "df.groupBy('id')",
            "df.na",
            "df.write",
            "df.writeTo('out')",
            "df.toLocalIterator()",
        ):
            with self.subTest(receiver=receiver):
                findings, graph, analyzer = self.analyze(
                    "receiver = "
                    + receiver
                    + "\nresult = receiver.custom()\nresult.collect()\ndf.collect()\n"
                )
                self.assertEqual([f.rule_id for f in findings], ["TL001"])
                self.assertNotIn("result", analyzer.state)
                boundary = next(n for n in graph.nodes if n.kind == "opaque")
                self.assertEqual(
                    self.incoming(graph, boundary, "receiver"),
                    {analyzer.state["receiver"].trace},
                )

    def test_missing_endpoint_is_disclosed_instead_of_guessed(self):
        source = "result = df.limit(1) if condition else df\nresult.collect()\n"
        collector = _GraphCollector(GraphArtifact("job.py", "python"))
        analyzer = SparkAnalyzer("job.py", _collector=collector)
        analyzer.state["df"] = _TrackedValue(Value("frame", "not graph evidence"))
        analyzer.analyze(parse_source(source, "job.py"), source)
        graph = collector.build()
        merge = next(
            n for n in graph.nodes if n.kind == "merge" and n.after is not None
        )
        self.assertIn("some alternatives untracked", merge.label)
        self.assertEqual(len(self.incoming(graph, merge, "alternative")), 1)

    def test_capture_limits_preserve_nested_flow_findings_and_facts(self):
        source = (
            "for column in columns:\n    if condition:\n        df = df.withColumn(column, expr)\n"
            "    else:\n        df = df.select('id')\n"
            "result = df if condition else custom(df)\ndf.collect()\n"
        )
        complete = self.analyze(source)[1]
        required = len(complete.nodes) + len(complete.edges) + len(complete.anchors)
        for budget in range(1, required + 2):
            with self.subTest(budget=budget):
                findings, graph, _ = self.analyze(source, budget)
                self.assertEqual([f.rule_id for f in findings], ["TL003", "TL001"])
                self.assertEqual(graph.capture_complete, budget >= required)
                if graph.capture_complete:
                    self.assertEqual(len(graph.anchors), len(findings))

    def test_nested_control_ids_are_deterministic_and_unicode_locations_are_character_based(
        self,
    ):
        source = "é = 1; result = df.limit(1) if condition else df\nresult.collect()\n"
        _, graph, _ = self.analyze(source)
        self.assertEqual(graph, self.analyze(source)[1])
        merge = next(
            n for n in graph.nodes if n.kind == "merge" and n.after is not None
        )
        self.assertEqual(merge.location, Location(4, 17))
        shifted = self.analyze("\n# shifted\n" + source)[1]
        self.assertEqual([n.id for n in graph.nodes], [n.id for n in shifted.nodes])
        self.assertEqual([n.key for n in graph.nodes], [n.key for n in shifted.nodes])

    def test_plugin_errors_in_isolated_scopes_are_not_masked_by_control_cleanup(self):
        class Broken(Recorder):
            def check(self, facts):
                if facts.method == "collect":
                    raise RuntimeError("private error")
                return ()

        plugin = Plugin(
            Rule("LOCAL001", "Broken", "Test only.", "No action."), Broken()
        )
        for scope in (
            "def run():\n        df.collect()\n",
            "class Job:\n        df.collect()\n",
            "run = lambda: df.collect()\n",
        ):
            for enabled in (False, True):
                with self.subTest(scope=scope, enabled=enabled):
                    collector = (
                        _GraphCollector(GraphArtifact("job.py", "python"))
                        if enabled
                        else None
                    )
                    analyzer = SparkAnalyzer(
                        "job.py", plugins=(plugin,), _collector=collector
                    )
                    source = SETUP + "if condition:\n    " + scope
                    with self.assertRaisesRegex(
                        PluginError, r"plugin LOCAL001 failed \(RuntimeError\)"
                    ):
                        analyzer.analyze(parse_source(source, "job.py"), source)
                    self.assertEqual(analyzer._controls, [])
