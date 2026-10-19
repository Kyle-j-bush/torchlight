# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import json
import tempfile
import unittest
from pathlib import Path

from torchlight import Config, Scanner
from torchlight.analysis import SparkAnalyzer, parse_source
from torchlight.baseline import write_baseline
from torchlight.detectors import EagerLocalIterator
from torchlight.facts import CallFacts, Value
from torchlight.files import scan_file

SETUP = "from pyspark.sql import DataFrame\ndef export(df: DataFrame):\n"


class LocalIteratorTests(unittest.TestCase):
    def analyze(self, body):
        source = SETUP + "\n".join("    " + line for line in body.splitlines()) + "\n"
        return SparkAnalyzer("export.py").analyze(
            parse_source(source, "export.py"), source
        )

    def test_eager_consumption_and_aliases(self):
        for body in (
            "list(df.toLocalIterator())",
            "tuple(df.toLocalIterator(True))",
            "rows = df.toLocalIterator(prefetchPartitions=True)\nlist(rows)",
            "events = df\nrows = events.filter('active').toLocalIterator()\nconsume = tuple\nconsume(rows)",
            "list((df\n .toLocalIterator()))",
            "list(df.limit(1).join(other).toLocalIterator())",
        ):
            with self.subTest(body=body):
                findings = self.analyze(body)
                self.assertEqual([f.rule_id for f in findings], ["TL005"])
                self.assertIn(
                    "Annotated as pyspark.sql.DataFrame", findings[0].evidence[0]
                )
                self.assertIn("Spark .toLocalIterator() (line", findings[0].evidence[0])

    def test_streaming_bounded_unknown_and_invalid_consumers_are_not_reported(self):
        for body in (
            "df.toLocalIterator()",
            "for row in df.toLocalIterator():\n    consume(row)",
            "list(df.limit(10).toLocalIterator())",
            "tuple(df.agg(expr).toLocalIterator())",
            "list(unknown.toLocalIterator())",
            "list(df.custom().toLocalIterator())",
            "rows = df.toLocalIterator()\nrows = other\nlist(rows)",
            "rows = df.toLocalIterator()\nlist(rows.custom())",
            "list = custom\nlist(df.toLocalIterator())",
            "if condition:\n    tuple = custom\ntuple(df.toLocalIterator())",
            "list(df.toLocalIterator(), other)",
            "list(iterable=df.toLocalIterator())",
            "list(*df.toLocalIterator())",
            "from other import *\nlist(df.toLocalIterator())",
            "[row for row in df.toLocalIterator()]",
        ):
            with self.subTest(body=body):
                self.assertEqual(self.analyze(body), [])

    def test_local_bindings_parameters_imports_and_scopes_shadow_consumers(self):
        sources = (
            "def export(df: DataFrame, list):\n    list(df.toLocalIterator())",
            "def export(df: DataFrame):\n    list(df.toLocalIterator())\n    list = custom",
            "def export(df: DataFrame):\n    import module as tuple\n    tuple(df.toLocalIterator())",
            "def export(df: DataFrame):\n    (lambda list: list(df.toLocalIterator()))(custom)",
        )
        for source in sources:
            source = "from pyspark.sql import DataFrame\n" + source
            self.assertEqual(
                SparkAnalyzer("job.py").analyze(parse_source(source, "job.py"), source),
                [],
            )
        self.assertEqual(
            len(
                self.analyze(
                    "rows = df.toLocalIterator()\nif condition:\n    rows = other\nlist(rows)"
                )
            ),
            0,
        )

    def test_detector_consumes_only_immutable_facts(self):
        facts = CallFacts(Value("local_iterator", "Known Spark source"), "list")
        self.assertEqual(
            [d.rule_id for d in EagerLocalIterator().check(facts)], ["TL005"]
        )
        self.assertEqual(
            list(
                EagerLocalIterator().check(CallFacts(Value("frame", "source"), "list"))
            ),
            [],
        )

    def test_alias_formatting_and_line_shifts_preserve_outer_call_identity(self):
        first = self.analyze("list(df.toLocalIterator())")[0]
        shifted = self.analyze("# header\n(list( df.toLocalIterator( ) ))")[0]
        self.assertEqual(first.fingerprint, shifted.fingerprint)
        self.assertEqual(first.location.line + 1, shifted.location.line)

    def test_notebook_provenance_opaque_boundaries_and_suppression(self):
        setup = "from pyspark.sql import SparkSession\nrows = SparkSession.builder.getOrCreate().table('events').toLocalIterator()"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job.ipynb"
            for middle, consumer, count in (
                ("", "list(rows)", 1),
                ("%run other", "list(rows)", 0),
                ("rows = other", "list(rows)", 0),
                ("", "list(rows) # torchlight: ignore[TL005] -- small export", 0),
            ):
                path.write_text(
                    json.dumps(
                        {
                            "cells": [
                                {"cell_type": "code", "source": s}
                                for s in (setup, middle, consumer)
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                findings, errors = scan_file(path)
                self.assertEqual(errors, [])
                self.assertEqual(len(findings), count)
                if findings:
                    self.assertEqual(findings[0].location.cell, 3)

    def test_selection_baseline_duplicate_count_and_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "job.py"
            source = SETUP + "    list(df.toLocalIterator())\n"
            path.write_text(source, encoding="utf-8")
            baseline = root / "baseline.json"
            scanner = Scanner(Config(root=root, baseline=baseline, select={"TL005"}))
            report = scanner.scan(path, use_baseline=False)
            write_baseline(baseline, list(report.findings), root)
            self.assertEqual(scanner.scan(path).exit_code, 0)
            path.write_text(
                source + "    list(df.toLocalIterator())\n", encoding="utf-8"
            )
            report = scanner.scan(path)
            self.assertEqual(len(report.findings), 1)
            self.assertEqual(Scanner(Config(ignore={"TL005"})).scan(path).exit_code, 0)
            for output_format in ("text", "json", "github", "sarif"):
                self.assertIn("TL005", report.render(output_format))
