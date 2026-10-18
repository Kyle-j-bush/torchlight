# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import hashlib
import json
import unittest

from torchlight.analysis import SparkAnalyzer, parse_source
from torchlight.detectors import DETECTORS
from torchlight.diagnostics import RULES, Location
from torchlight.facts import CallFacts, Value


class DetectorTests(unittest.TestCase):
    def test_every_rule_has_exactly_one_detector(self):
        codes = [detector.rule_id for detector in DETECTORS]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(set(codes), set(RULES))

    def test_detectors_consume_facts_without_ast_or_analyzer(self):
        facts = CallFacts(Value("frame", "Known Spark source"), "collect")
        results = [d for detector in DETECTORS for d in detector.check(facts)]
        self.assertEqual([d.rule_id for d in results], ["TL001"])
        write = CallFacts(
            Value("writer", "Known Spark source", single_partition=Location(3)),
            "parquet",
            terminal_write=True,
        )
        results = [d for detector in DETECTORS for d in detector.check(write)]
        self.assertEqual([d.rule_id for d in results], ["TL002"])

    def test_v030_original_rule_outputs_are_unchanged(self):
        # Captured before detector extraction. Includes full JSON fields,
        # structural fingerprints, messages, evidence, and human-readable text.
        source = (
            "from pyspark.sql import SparkSession\n"
            "spark = SparkSession.builder.getOrCreate()\n"
            "df = spark.table('events')\n"
            "df.collect()\n"
            "df.coalesce(1).write.parquet('out')\n"
            "for column in columns:\n"
            "    df = df.withColumn(column, expression)\n"
        )
        for cell, expected in (
            (None, "655f5bf53e3eb03be8bb933ba0a6e271931049835138237ed198375d5931f543"),
            (2, "454d4c1060a0628615c287b22193a34663a1a9e302664ffe2872c3add4a12ce9"),
        ):
            with self.subTest(cell=cell):
                findings = SparkAnalyzer("pipeline.py").analyze(
                    parse_source(source, "pipeline.py"), source, cell
                )
                output = json.dumps(
                    [{"json": f.to_dict(), "text": str(f)} for f in findings],
                    sort_keys=True,
                )
                self.assertEqual(hashlib.sha256(output.encode()).hexdigest(), expected)
