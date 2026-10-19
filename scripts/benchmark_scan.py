# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Reproducible synthetic scan-only timing, not a production performance claim."""

import argparse
import hashlib
import json
import platform
import statistics
import tempfile
import time
from pathlib import Path

import torchlight
from torchlight import Config, Scanner

SETUP = "from pyspark.sql import SparkSession\ndf = SparkSession.builder.getOrCreate().table('events')\n"
CELL = (
    "df.collect()\nlist(df.toLocalIterator())\ndf.repartition(1).write.parquet('out')\n"
)


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def generate(root: Path, files: int, cells: int) -> str:
    """Return a content digest; generation and hashing are outside the timer."""
    sources = {
        ".py": SETUP + CELL * cells,
        ".ipynb": json.dumps(
            {
                "cells": [
                    {"cell_type": "code", "source": source}
                    for source in (SETUP, *([CELL] * cells))
                ]
            },
            sort_keys=True,
        ),
        ".db.py": "# Databricks notebook source\n"
        + SETUP
        + (
            "# COMMAND ----------\n# MAGIC %python\n"
            + "".join("# MAGIC " + line for line in CELL.splitlines(keepends=True))
        )
        * cells,
    }
    digest = hashlib.sha256()
    for index in range(files):
        for suffix, source in sources.items():
            name = f"job-{index:05}{suffix}"
            data = source.encode("utf-8")
            (root / name).write_bytes(data)
            digest.update(name.encode("utf-8") + b"\0" + data + b"\0")
    return digest.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--files", type=positive, default=100, help="files per format (three formats)"
    )
    parser.add_argument(
        "--cells",
        type=positive,
        default=8,
        help="workload cells per notebook, plus one setup cell",
    )
    parser.add_argument("--samples", type=positive, default=5)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="torchlight-timing-") as directory:
        root = Path(directory)
        digest = generate(root, args.files, args.cells)
        scanner = Scanner(Config(root=root))
        timings = []
        for repetition in range(args.samples + 1):
            start = time.perf_counter()
            report = scanner.scan(root, use_baseline=False)
            elapsed = time.perf_counter() - start
            if report.errors or len(report.findings) != args.files * args.cells * 9:
                raise RuntimeError(
                    "synthetic workload did not produce the expected findings"
                )
            if repetition:
                timings.append(elapsed)
    package = Path(torchlight.__file__).parent
    tool_hash = hashlib.sha256(
        b"".join(
            path.name.encode() + b"\0" + path.read_bytes()
            for path in sorted(package.glob("*.py"))
        )
    ).hexdigest()
    print("# Synthetic scan timing\n")
    print(f"- Python: {platform.python_version()} ({platform.python_implementation()})")
    print(f"- Platform: {platform.platform()}")
    print(f"- Tool source SHA-256: `{tool_hash}`")
    print(f"- Corpus SHA-256: `{digest}`")
    print(f"- Files: {args.files * 3} ({args.files} each Python/Jupyter/Databricks)")
    print(f"- Workload cells per notebook: {args.cells}, plus one setup cell")
    print(f"- Findings per scan: {args.files * args.cells * 9}")
    print(f"- Samples: {args.samples}, after one discarded warm-up scan")
    print(f"- Wall seconds: {', '.join(f'{value:.6f}' for value in timings)}")
    print(f"- Median seconds: {statistics.median(timings):.6f}")
    print(f"- Range seconds: {min(timings):.6f}–{max(timings):.6f}\n")
    print(
        "Scan-only in-process wall time, including discovery and parsing; generation, hashing, and rendering excluded. Warm filesystem/cache policy; no cold-cache or peak-memory measurement. Synthetic workload only, no production accuracy, comparative speed, or runtime-savings claim. Timing thresholds do not gate CI."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
