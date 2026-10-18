# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import json
import tempfile
import unittest
from pathlib import Path

from torchlight.analysis import SparkAnalyzer, parse_source
from torchlight.files import scan_file

SETUP = "from pyspark.sql import DataFrame\ndef export(df: DataFrame):\n"


class RepartitionWriteTests(unittest.TestCase):
    def analyze(self, body):
        source = SETUP + "\n".join("    " + line for line in body.splitlines()) + "\n"
        return SparkAnalyzer("export.py").analyze(
            parse_source(source, "export.py"), source
        )

    def codes(self, body):
        return [f.rule_id for f in self.analyze(body)]

    def test_literal_single_partition_feeding_terminal_writes(self):
        for expression in (
            "df.repartition(1).write.parquet('out')",
            "df.repartition(numPartitions=1).write.mode('overwrite').csv('out')",
            "df.repartition(1, 'key').write.save('out')",
            "df.repartition(1).writeTo('table').using('parquet').create()",
            "small = df.repartition(1)\nwriter = small.write\nwriter.json('out')",
            "df.repartition(1).filter('active').select('key').write.save('out')",
            "df.limit(10).repartition(1).write.csv('out')",
            "df.repartition(1).coalesce(4).write.csv('out')",
        ):
            with self.subTest(expression=expression):
                findings = self.analyze(expression)
                self.assertEqual([f.rule_id for f in findings], ["TL004"])
                self.assertIn("repartition(1) at line", findings[0].evidence[1])
                self.assertIn(
                    "Annotated as pyspark.sql.DataFrame", findings[0].evidence[0]
                )

    def test_unproven_or_non_terminal_patterns_are_ignored(self):
        for expression in (
            "df.repartition(1)",
            "df.repartition(1).write",
            "df.repartition(1).write.mode('overwrite')",
            "df.repartition(2).write.parquet('out')",
            "df.repartition(partitions).write.parquet('out')",
            "df.repartition('key').write.parquet('out')",
            "df.repartition(True).write.parquet('out')",
            "df.repartition(*args).write.parquet('out')",
            "df.repartitionByRange(1, 'key').write.parquet('out')",
            "unknown.repartition(1).write.parquet('out')",
            "df = other\ndf.repartition(1).write.parquet('out')",
            "df.repartition(1).custom().write.parquet('out')",
        ):
            with self.subTest(expression=expression):
                self.assertEqual(self.codes(expression), [])

    def test_partition_changing_operations_drop_evidence(self):
        for operation in (
            "repartition(8)",
            "repartition(dynamic)",
            "repartition('key')",
            "repartitionByRange(8, 'key')",
            "groupBy('key').count()",
            "agg(expression)",
            "distinct()",
            "join(other, 'key')",
            "orderBy('key')",
        ):
            with self.subTest(operation=operation):
                self.assertEqual(
                    self.codes(f"df.repartition(1).{operation}.write.parquet('out')"),
                    [],
                )

    def test_coalesce_provenance_keeps_tl002_without_duplicate_warnings(self):
        for expression in (
            "df.coalesce(1).repartition(1).write.parquet('out')",
            "df.repartition(1).coalesce(1).write.parquet('out')",
        ):
            self.assertEqual(self.codes(expression), ["TL002"])

    def test_branch_dependent_evidence_is_not_assumed(self):
        self.assertEqual(
            self.codes(
                "if condition:\n    df = df.repartition(1)\ndf.write.csv('out')"
            ),
            [],
        )
        self.assertEqual(
            self.codes(
                "small = df.repartition(1)\nif condition:\n    small = other\nsmall.write.csv('out')"
            ),
            [],
        )
        self.assertEqual(
            self.codes(
                "small = df.repartition(1)\nif condition:\n    small = small.filter('x')\nsmall.write.csv('out')"
            ),
            ["TL004"],
        )

    def test_notebook_cross_cell_provenance_invalidation_and_suppression(self):
        setup = "from pyspark.sql import SparkSession\nsmall = SparkSession.builder.getOrCreate().table('events').repartition(1)"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.ipynb"
            for middle, end, expected in (
                ("", "small.write.csv('out')", ["TL004"]),
                ("%run other.ipynb", "small.write.csv('out')", []),
                ("small = other", "small.write.csv('out')", []),
                (
                    "",
                    "small.write.csv('out') # torchlight: ignore[TL004] -- small export",
                    [],
                ),
            ):
                with self.subTest(middle=middle, end=end):
                    path.write_text(
                        json.dumps(
                            {
                                "cells": [
                                    {"cell_type": "code", "source": s}
                                    for s in (setup, middle, end)
                                ]
                            }
                        ),
                        encoding="utf-8",
                    )
                    findings, errors = scan_file(path)
                    self.assertEqual(errors, [])
                    self.assertEqual([f.rule_id for f in findings], expected)
                    if findings:
                        self.assertEqual(findings[0].location.cell, 3)
                        self.assertIn("cell 1, line 2", findings[0].evidence[1])

    def test_metamorphic_alias_formatting_and_renaming_keep_detection(self):
        for body in (
            "df.repartition(1).write.csv('out')",
            "events = df\nsmall = events.repartition(numPartitions=1)\nsmall.write.csv('out')",
            "(df\n .repartition(1)\n .write.csv('out'))",
        ):
            self.assertEqual(self.codes(body), ["TL004"])
