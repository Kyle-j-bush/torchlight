# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import Mock

from torchlight.analysis import SparkAnalyzer, _TrackedValue, parse_source
from torchlight.diagnostics import Location, Rule
from torchlight.plugins import CallFacts, Plugin, Value


class TrackedStateTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = SparkAnalyzer("job.py", ("spark",))
        self.frame = _TrackedValue(Value("frame", "source"), "frame-trace")
        self.analyzer.state["df"] = self.frame

    def analyze(self, source):
        return self.analyzer.analyze(parse_source(source, "job.py"), source)

    def test_wrapper_is_immutable_and_does_not_change_public_value(self):
        self.assertIs(type(self.frame.value), Value)
        self.assertFalse(hasattr(self.frame.value, "trace"))
        for name, value in (("trace", "other"), ("value", Value("session", "other"))):
            with self.assertRaises(FrozenInstanceError):
                setattr(self.frame, name, value)

    def test_bindings_and_attributes_preserve_trace(self):
        self.analyze(
            "alias = df\n"
            "assigned = (named := alias)\n"
            "annotated: UnknownType = alias\n"
            "with alias as managed:\n    inside = managed\n"
            "writer = alias.write\nna = alias.na\n"
        )
        for name in (
            "df",
            "alias",
            "assigned",
            "named",
            "annotated",
            "managed",
            "inside",
        ):
            self.assertIs(self.analyzer.state[name], self.frame)
        for name, kind in (("writer", "writer"), ("na", "frame_na")):
            self.assertEqual(
                self.analyzer.state[name],
                _TrackedValue(replace(self.frame.value, kind=kind), self.frame.trace),
            )

    def test_fact_transitions_preserve_trace_without_mutating_aliases(self):
        value = Value("frame", "source", row_limit=5, single_partition=Location(1))
        self.frame = _TrackedValue(value, "frame-trace")
        self.analyzer.state["df"] = self.frame
        for expression, expected in (
            ("df.select('x')", value),
            ("df.limit(2)", replace(value, row_limit=2)),
            ("df.join(other)", replace(value, row_limit=None, single_partition=None)),
            ("df.repartition(4)", replace(value, single_partition=None)),
            ("df.na.fill(0)", value),
            (
                "df.groupBy('x').pivot('y').count()",
                replace(value, row_limit=None, single_partition=None),
            ),
            ("df.agg(expr)", replace(value, row_limit=1, single_partition=None)),
            ("df.write.mode('overwrite')", replace(value, kind="writer")),
            ("df.writeTo('out').using('delta')", replace(value, kind="writer_v2")),
        ):
            with self.subTest(expression=expression):
                self.analyze("result = " + expression)
                self.assertEqual(
                    self.analyzer.state["result"],
                    _TrackedValue(expected, self.frame.trace),
                )
                self.assertIs(self.analyzer.state["df"], self.frame)

    def test_reader_builder_and_session_options_preserve_trace(self):
        for kind, expression, result_kind in (
            ("session", "source.newSession()", "session"),
            ("session", "source.read.option('x', 'y')", "reader"),
            ("session_type", "source.builder.appName('job')", "builder"),
        ):
            with self.subTest(expression=expression):
                self.analyzer.state["source"] = _TrackedValue(
                    Value(kind, "source"), "trace"
                )
                self.analyze("result = " + expression)
                self.assertEqual(
                    self.analyzer.state["result"],
                    _TrackedValue(Value(result_kind, "source"), "trace"),
                )

    def test_fresh_sources_and_annotations_start_without_trace_or_loop_tokens(self):
        self.analyzer.state["spark"] = _TrackedValue(Value("session", "session"), "old")
        self.analyze(
            "from pyspark.sql import DataFrame, SparkSession\n"
            "read = spark.read.parquet('events')\n"
            "table = spark.table('events')\n"
            "session = SparkSession.builder.getOrCreate()\n"
            "constructed = SparkSession(context)\n"
            "looked_up = SparkSession.getActiveSession()\n"
            "annotated: 'DataFrame'\n"
            "session_annotation: SparkSession\n"
        )
        for name in (
            "read",
            "table",
            "session",
            "constructed",
            "looked_up",
            "annotated",
            "session_annotation",
        ):
            with self.subTest(name=name):
                self.assertIsNone(self.analyzer.state[name].trace)
                self.assertEqual(
                    self.analyzer.state[name].value.loop_origins, frozenset()
                )

    def test_unknown_results_close_only_the_result_not_the_receiver(self):
        for expression in ("custom(df)", "df.unknown()", "df.rdd", "df.collect()"):
            with self.subTest(expression=expression):
                self.analyze("result = df\nresult = " + expression)
                self.assertNotIn("result", self.analyzer.state)
                self.assertIs(self.analyzer.state["df"], self.frame)

    def test_merging_equal_facts_ignores_different_trace_endpoints(self):
        for kind in (
            "frame",
            "grouped",
            "writer",
            "writer_v2",
            "frame_na",
            "local_iterator",
            "session",
            "session_type",
            "frame_type",
            "module",
            "builder",
            "reader",
            "generator",
            "materializer",
        ):
            with self.subTest(kind=kind):
                value = Value(kind, "source")
                for trace in (None, "left", "right"):
                    merged = self.analyzer._merge_value(
                        _TrackedValue(value, "left"),
                        _TrackedValue(replace(value), trace),
                    )
                    self.assertEqual(merged.value, value)
                    self.assertEqual(merged.trace, "left" if trace == "left" else None)

    def test_merge_keeps_existing_bounds_partition_and_loop_rules(self):
        for kind in ("frame", "grouped", "writer", "writer_v2", "frame_na"):
            with self.subTest(kind=kind):
                left = Value(
                    kind,
                    "left",
                    row_limit=5,
                    single_partition=Location(2),
                    loop_origins=frozenset({(0, "df"), (1, "df")}),
                )
                right = replace(
                    left,
                    origin="right",
                    row_limit=10,
                    loop_origins=frozenset({(0, "df")}),
                )
                expected = replace(
                    right, origin="Spark DataFrame on all analyzed paths"
                )
                for alternative, result in (
                    (right, expected),
                    (replace(right, row_limit=None), replace(expected, row_limit=None)),
                    (
                        replace(right, single_partition=Location(3)),
                        replace(expected, single_partition=None),
                    ),
                    (
                        replace(right, single_partition_method="repartition"),
                        replace(expected, single_partition=None),
                    ),
                ):
                    self.assertEqual(
                        self.analyzer._merge_value(
                            _TrackedValue(left, "left"),
                            _TrackedValue(alternative, "right"),
                        ),
                        _TrackedValue(result),
                    )

    def test_merge_drops_unknown_and_incompatible_facts_without_changing_inputs(self):
        for left, right in (
            (None, self.frame),
            (self.frame, None),
            (self.frame, _TrackedValue(Value("session", "source"), self.frame.trace)),
            (
                _TrackedValue(Value("session", "a")),
                _TrackedValue(Value("session", "b")),
            ),
            (
                _TrackedValue(Value("local_iterator", "a")),
                _TrackedValue(Value("local_iterator", "b")),
            ),
        ):
            with self.subTest(left=left, right=right):
                self.assertIsNone(self.analyzer._merge_value(left, right))
        left = {"df": self.frame, "left_only": self.frame}
        right = {"df": replace(self.frame, trace="right"), "right_only": self.frame}
        self.assertEqual(
            self.analyzer._merge(left, right), {"df": replace(self.frame, trace=None)}
        )
        self.assertIs(left["df"], self.frame)
        self.assertEqual(set(left), {"df", "left_only"})
        self.assertEqual(right["df"].trace, "right")

    def test_scopes_restore_the_original_tracked_binding(self):
        for source in (
            "def run():\n    df = unknown\n",
            "class Job:\n    df = unknown\n",
            "function = lambda: (df := unknown)\n",
            "[df for df in items]\n",
            "{df for df in items}\n",
            "{df: df for df in items}\n",
            "(df for df in items)\n",
        ):
            with self.subTest(source=source):
                self.analyze(source)
                self.assertIs(self.analyzer.state["df"], self.frame)

    def test_control_flow_merges_semantics_not_wrapper_equality(self):
        self.analyzer.state.update(a=self.frame, b=replace(self.frame, trace="right"))
        for source in (
            "result = a if condition else b\n",
            "result = a\ncondition and (result := b)\n",
            "if condition:\n    result = a\nelse:\n    result = b\n",
            "try:\n    result = a\nexcept Exception:\n    result = b\n",
            "match item:\n    case 1:\n        result = a\n    case _:\n        result = b\n",
        ):
            with self.subTest(source=source):
                self.analyzer.state.pop("result", None)
                self.analyze(source)
                self.assertEqual(
                    self.analyzer.state["result"], replace(self.frame, trace=None)
                )
                self.assertEqual(self.analyzer.state["a"], self.frame)

    def test_loop_tagging_and_materialization_keep_traces_private(self):
        detector = Mock(rule_id="LOCAL001")
        detector.check.return_value = ()
        plugin = Plugin(
            Rule("LOCAL001", "Record facts", "Test only.", "No action."), detector
        )
        self.analyzer = SparkAnalyzer("job.py", plugins=(plugin,))
        self.frame = replace(
            self.frame,
            value=replace(
                self.frame.value,
                single_partition=Location(1),
                loop_origins=frozenset({(99, "external")}),
            ),
        )
        self.analyzer.state["df"] = self.frame
        findings = self.analyze(
            "for outer in names:\n"
            "    df = df.withColumn(outer, expr)\n"
            "    for inner in names:\n"
            "        df = df.withColumn(inner, expr)\n"
            "    df = df.withColumn(outer, expr)\n"
            "df.collect()\nstream = df.toLocalIterator()\ntuple(stream)\n"
            "df.write.parquet(path)\n"
        )
        self.assertEqual(
            [f.rule_id for f in findings],
            ["TL003", "TL003", "TL003", "TL001", "TL005", "TL002"],
        )
        facts = [call.args[0] for call in detector.check.call_args_list]
        for fact in facts:
            self.assertIs(type(fact), CallFacts)
            self.assertIs(type(fact.receiver), Value)
            self.assertFalse(hasattr(fact.receiver, "trace"))
        self.assertEqual([f.carries_loop_frame for f in facts[:3]], [True, True, True])
        self.assertEqual(
            [f.receiver.loop_origins for f in facts[:3]],
            [
                frozenset({(99, "external"), (0, "df")}),
                frozenset({(99, "external"), (0, "df"), (1, "df")}),
                frozenset({(99, "external"), (0, "df")}),
            ],
        )
        self.assertEqual(self.analyzer.state["df"], self.frame)
        stream = self.analyzer.state["stream"]
        self.assertEqual(stream.trace, self.frame.trace)
        self.assertEqual(stream.value.kind, "local_iterator")
        self.assertIs(facts[-2].receiver, stream.value)
        self.assertEqual(facts[-2].method, "tuple")
        self.assertTrue(facts[-1].terminal_write)

    def test_forget_clears_semantics_and_trace_between_cells(self):
        self.analyze("alias = df\n")
        self.analyzer.forget()
        self.assertEqual(self.analyzer.state, {})
        self.assertEqual(self.analyze("df.collect()\nalias.collect()\n"), [])
