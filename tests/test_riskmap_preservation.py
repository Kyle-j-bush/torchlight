# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Pre-provenance v0.8.0 contracts; fixtures are parsed, never executed."""

import contextlib
import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from torchlight import Config, Rule, Scanner, ScanReport
from torchlight.files import scan_source
from torchlight.graph import GraphArtifact, _GraphCollector
from torchlight.plugins import API_VERSION, CallFacts, Plugin, Value

CELLS = (
    "from pyspark.sql import SparkSession\n"
    "spark = SparkSession.builder.getOrCreate()\n"
    "df = spark.read.parquet('events')\n",
    "bounded = df.limit(10)\n"
    "bounded.collect()\n"
    "expanded = bounded.selectExpr('explode(items)')\n"
    "expanded.collect()\n"
    "small = df.coalesce(1)\n",
    "small.write.mode('overwrite').parquet('out')\n"
    "df.repartition(1).writeTo('target').using('parquet').create()\n"
    "for name in names:\n"
    "    df = df.withColumn(name, expression)\n",
    "stream = df.toLocalIterator()\n"
    "list(stream)\n"
    "tuple(stream)\n"
    "é = 1; df.collect()\n"
    "df.collect()\n"
    "df.limit(1).toPandas()\n"
    "list(df.limit(1).toLocalIterator())\n"
    "df.coalesce(1).repartition(4).write.csv('out')\n"
    "other.collect()\n",
)
SOURCES = {
    "pipeline.py": "".join(CELLS),
    "pipeline.ipynb": json.dumps(
        {
            "cells": [
                {"cell_type": "markdown", "source": "Not a code cell."},
                *(
                    {"cell_type": "code", "source": cell.splitlines(keepends=True)}
                    for cell in CELLS
                ),
            ]
        }
    ),
    "export.py": "# Databricks notebook source\n"
    + CELLS[0]
    + "".join(
        "# COMMAND ----------\n# MAGIC %python\n"
        + "".join("# MAGIC " + line for line in cell.splitlines(keepends=True))
        for cell in CELLS[1:]
    ),
}
EXPECTED_CODES = [
    "TL001",
    "TL002",
    "TL004",
    "TL003",
    "TL005",
    "TL005",
    "TL001",
    "TL001",
]
# Captured at ee47c973b9ddd2d5565dc6c9afeb093673344875 before analyzer changes.
OUTPUT_DIGESTS = {
    "pipeline.py": "1b185830c67247274600105cba9faaadffea1aa1cb65e3cb7fd0e2193597707c",
    "pipeline.ipynb": "f852b0d3bb5b66c4e61aaf0efb56c10db60eed619da821e7766b74f7d0093e8c",
    "export.py": "5403ff149c749a89148982c5f2cc684450237295bea48cd21dec4f0ea987a594",
}
FACT_DIGESTS = {
    "pipeline.py": "0d3903b99d66890495137c0b0ac30373e1ba5c01be8c989370ed4ee70b0829ad",
    "pipeline.ipynb": "345ae207b0542f6f25d54b33b5f4727e28df52570c890067049ec511fe9bd110",
    "export.py": "9a6dfc8833075644b98f0f21a56c78366c62ca77e829337a64edbbb039c1c4ee",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


class RecordingDetector:
    rule_id = "LOCAL001"

    def __init__(self):
        self.facts = []

    def check(self, facts: CallFacts):
        self.facts.append(facts)
        return ()


class RiskMapPreservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.enterContext(contextlib.chdir(self.root))

    def scan(self, name, source, plugins=()):
        path = Path(name)
        path.write_text(source, encoding="utf-8")
        return Scanner(Config(root=self.root, plugins=plugins)).scan(path)

    def output_snapshot(self, report):
        with patch("torchlight.sarif.version", return_value="0.8.0"):
            outputs = {
                output_format: report.render(output_format).replace(
                    self.root.as_uri() + "/", "file:///torchlight-contract/"
                )
                for output_format in ("text", "json", "github", "sarif")
            }
        return {"report": report.to_dict(), "outputs": outputs}

    def test_v080_all_rule_outputs_across_source_formats(self):
        for name, source in SOURCES.items():
            with self.subTest(source=name):
                report = self.scan(name, source)
                self.assertEqual(report.errors, ())
                self.assertEqual(report.exit_code, 1)
                self.assertEqual([f.rule_id for f in report.findings], EXPECTED_CODES)
                self.assertEqual(
                    report.findings[-2].fingerprint, report.findings[-1].fingerprint
                )
                self.assertEqual(
                    digest(self.output_snapshot(report)), OUTPUT_DIGESTS[name]
                )

    def test_v1_plugin_fact_streams_across_source_formats(self):
        self.assertEqual(API_VERSION, 1)
        for name, source in SOURCES.items():
            with self.subTest(source=name):
                detector = RecordingDetector()
                plugin = Plugin(
                    Rule(detector.rule_id, "Record facts", "Test only.", "No action."),
                    detector,
                )
                report = self.scan(name, source, (plugin,))
                self.assertEqual(report.errors, ())
                self.assertEqual([f.rule_id for f in report.findings], EXPECTED_CODES)
                self.assertEqual(
                    digest(self.output_snapshot(report)), OUTPUT_DIGESTS[name]
                )
                observed = []
                for facts in detector.facts:
                    self.assertIs(type(facts), CallFacts)
                    self.assertIs(type(facts.receiver), Value)
                    record = asdict(facts)
                    record["receiver"]["loop_origins"] = sorted(
                        facts.receiver.loop_origins
                    )
                    observed.append(record)
                self.assertTrue(observed)
                self.assertEqual(digest(observed), FACT_DIGESTS[name])

    def test_private_capture_and_limits_preserve_all_source_outputs_and_plugin_facts(
        self,
    ):
        for name, source in SOURCES.items():
            for budget in (1, 8, 10_000):
                with self.subTest(source=name, budget=budget):
                    self.check_capture(name, source, budget)

    def check_capture(self, name, source, budget):
        detector = RecordingDetector()
        plugin = Plugin(
            Rule(detector.rule_id, "Record facts", "Test only.", "No action."),
            detector,
        )
        collector = _GraphCollector(GraphArtifact(name, "python"), max_records=budget)
        findings, errors = scan_source(
            Path(name),
            source.encode("utf-8"),
            plugins=(plugin,),
            _collector=collector,
        )
        self.assertEqual(errors, [])
        report = ScanReport(findings, root=self.root)
        self.assertEqual(digest(self.output_snapshot(report)), OUTPUT_DIGESTS[name])
        observed = []
        for facts in detector.facts:
            self.assertIs(type(facts.receiver), Value)
            record = asdict(facts)
            record["receiver"]["loop_origins"] = sorted(facts.receiver.loop_origins)
            observed.append(record)
        self.assertEqual(digest(observed), FACT_DIGESTS[name])
        graph = collector.build()
        self.assertEqual(graph.capture_complete, budget == 10_000)
        self.assertLessEqual(
            len(graph.nodes) + len(graph.edges) + len(graph.anchors), budget
        )
        if graph.capture_complete:
            self.assertEqual(len(graph.anchors), len(findings))
