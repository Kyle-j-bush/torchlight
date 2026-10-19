# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Validate representative output against the SHA-pinned OASIS SARIF schema.

Development only: requires jsonschema. Downloads the public schema, never sends
source or reports. Supply --schema PATH to validate completely offline.
"""

import argparse
import contextlib
import hashlib
import io
import json
import tempfile
from pathlib import Path
from urllib.request import urlopen

from jsonschema import Draft4Validator

from torchlight import Config, Rule, Scanner
from torchlight.cli import main as scan
from torchlight.plugins import Diagnostic, Plugin

SCHEMA_URL = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/"
    "a560296ca8c921f3bdb8d4a8db57ab83dae968a7/"
    "sarif-2.1/schema/sarif-schema-2.1.0.json"
)
SCHEMA_SHA256 = "c3b4bb2d6093897483348925aaa73af03b3e3f4bd4ca38cef26dcb4212a2682e"
SOURCE = (
    "from pyspark.sql import SparkSession\n"
    "df = SparkSession.builder.getOrCreate().table('events')\n"
    "df.collect()\n"
    "df.coalesce(1).write.parquet('out')\n"
    "df.repartition(1).write.parquet('out')\n"
    "list(df.toLocalIterator())\n"
    "for name in names:\n    df = df.withColumn(name, expr)\n"
)


class SchemaDetector:
    rule_id = "SCHEMA001"

    def check(self, facts):
        if facts.receiver.kind == "frame" and facts.method == "collect":
            yield Diagnostic(self.rule_id, (facts.receiver.origin,))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, help="Local copy of the pinned schema.")
    args = parser.parse_args()
    if args.schema:
        data = args.schema.read_bytes()
    else:
        with urlopen(SCHEMA_URL, timeout=30) as response:
            data = response.read()
    if hashlib.sha256(data).hexdigest() != SCHEMA_SHA256:
        raise SystemExit("SARIF schema checksum mismatch")
    schema = json.loads(data)
    Draft4Validator.check_schema(schema)
    validator = Draft4Validator(schema)
    with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
        Path("pyproject.toml").write_text("", encoding="utf-8")
        Path("job.py").write_text(SOURCE, encoding="utf-8")
        Path("clean.py").write_text("unknown.collect()", encoding="utf-8")
        Path("export.py").write_text(
            "# Databricks notebook source\n"
            + SOURCE
            + "# COMMAND ----------\n# MAGIC %python\n# MAGIC list(df.toLocalIterator())\n",
            encoding="utf-8",
        )
        Path("job.ipynb").write_text(
            json.dumps({"cells": [{"cell_type": "code", "source": SOURCE}]}),
            encoding="utf-8",
        )
        Path("invalid.toml").write_text(
            "[tool.torchlight]\ninvalid = true", encoding="utf-8"
        )
        for arguments in (
            ["job.py"],
            ["job.ipynb"],
            ["export.py"],
            ["clean.py"],
            ["missing.py"],
            ["job.py", "missing.py"],
            ["--config", "invalid.toml", "job.py"],
            ["--baseline", "missing.json", "job.py"],
        ):
            stdout = io.StringIO()
            with (
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                scan(["--format", "sarif", *arguments])
            validator.validate(json.loads(stdout.getvalue()))
        plugin = Plugin(
            Rule("SCHEMA001", "Schema test", "Test policy.", "Review."),
            SchemaDetector(),
        )
        validator.validate(
            json.loads(
                Scanner(Config(plugins=(plugin,))).scan("job.py").render("sarif")
            )
        )
    print("9 SARIF report variants validated against the pinned OASIS 2.1.0 schema.")


if __name__ == "__main__":
    main()
