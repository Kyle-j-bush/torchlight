# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Command-line arguments, findings on stdout, and errors on stderr."""

import argparse
import sys
from pathlib import Path

from torchlight.files import SOURCE_SUFFIXES, iter_source_files, scan_file


def report_error(message: str) -> None:
    """Print a tool warning to stderr, leaving stdout for findings."""
    print(f"torchlight: {message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="torchlight",
        description="Scan Python files and Jupyter notebooks for Spark operations.",
        epilog="Exit codes: 0 = no findings, 1 = findings, 2 = scan errors only.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Files or directories to scan (.py, .ipynb, or directories).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    found = 0
    errors = 0

    for path in args.paths:
        if path.is_dir():
            files = iter_source_files(path)
        elif path.exists() and path.suffix in SOURCE_SUFFIXES:
            files = [path]
        else:
            reason = (
                "unsupported file type (expected .py or .ipynb)"
                if path.exists()
                else "no such file or directory"
            )
            report_error(f"{path}: {reason}")
            errors += 1
            continue

        for file in files:
            findings, file_errors = scan_file(file)
            for finding in findings:
                print(finding)
            for error in file_errors:
                report_error(error)
            found += len(findings)
            errors += len(file_errors)

    if found:
        return 1
    if errors:
        return 2
    return 0
