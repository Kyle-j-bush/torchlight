# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Command-line arguments, findings on stdout, and errors on stderr."""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from torchlight.config import (
    ConfigError,
    load_config,
    valid_session_name,
    validate_pattern,
)
from torchlight.diagnostics import RULES
from torchlight.files import SOURCE_SUFFIXES, iter_source_files, scan_file
from torchlight.reporting import render


def report_error(message: str) -> None:
    """Print a tool warning to stderr, leaving stdout for findings."""
    print(f"torchlight: {message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="torchlight",
        description="Review Spark safety risks in Python files and Jupyter notebooks without execution.",
        epilog="Exit codes: 0 = no findings, 1 = findings, 2 = scan errors only.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Files or directories to scan (.py, .ipynb, or directories).",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json", "github"),
        default="text",
        help="Output format (default: text). GitHub output uses Actions annotations.",
    )
    parser.add_argument(
        "--select",
        type=rule_codes,
        metavar="RULES",
        help="Comma-separated rule IDs to enable; replaces configured selection.",
    )
    parser.add_argument(
        "--ignore",
        type=rule_codes,
        metavar="RULES",
        help="Comma-separated rule IDs to disable; overrides --select.",
    )
    parser.add_argument(
        "--assume-spark-session",
        action="append",
        type=session_name,
        metavar="NAME",
        help="Explicitly treat an existing name as a SparkSession; repeatable.",
    )
    config_group = parser.add_mutually_exclusive_group()
    config_group.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help="Read [tool.torchlight] from this TOML file instead of discovering one.",
    )
    config_group.add_argument(
        "--no-config",
        action="store_true",
        help="Ignore project configuration; exclusions are relative to the working directory.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        type=exclude_pattern,
        metavar="GLOB",
        help="Exclude a project-relative glob; repeatable, replaces configured excludes.",
    )
    return parser


def rule_codes(value: str) -> set[str]:
    codes = {code.strip() for code in value.split(",")}
    if not codes <= RULES.keys():
        raise argparse.ArgumentTypeError(f"expected rule IDs from {','.join(RULES)}")
    return codes


def session_name(value: str) -> str:
    if not valid_session_name(value):
        raise argparse.ArgumentTypeError(
            "expected a Python variable name, such as spark"
        )
    return value


def exclude_pattern(value: str) -> str:
    try:
        return validate_pattern(value)
    except ConfigError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    findings = []
    errors = []
    seen = set()
    try:
        config = load_config(config_path=args.config, no_config=args.no_config)
    except ConfigError as exc:
        message = f"configuration error: {exc}"
        output = render([], [message], args.format)
        if output:
            print(output)
        report_error(message)
        return 2

    overrides = {}
    for argument, field in (
        (args.select, "select"),
        (args.ignore, "ignore"),
        (args.exclude, "exclude"),
        (args.assume_spark_session, "assume_sessions"),
    ):
        if argument is not None:
            overrides[field] = (
                frozenset(argument)
                if field in {"select", "ignore"}
                else tuple(argument)
            )
    config = replace(config, **overrides)

    for path in args.paths:
        if path.exists() and config.is_excluded(path):
            continue
        if path.is_dir():
            files = iter_source_files(path, is_excluded=config.is_excluded)
        elif path.is_file() and path.suffix in SOURCE_SUFFIXES:
            files = [path]
        else:
            reason = (
                "unsupported file type (expected .py or .ipynb)"
                if path.exists()
                else "no such file or directory"
            )
            errors.append(f"{path}: {reason}")
            continue

        for file in files:
            resolved = file.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            file_findings, file_errors = scan_file(
                file, assume_sessions=config.assume_sessions
            )
            findings.extend(
                f for f in file_findings if f.rule_id in config.enabled_rules
            )
            errors.extend(file_errors)

    output = render(findings, errors, args.format)
    if output:
        print(output)
    for error in errors:
        report_error(error)

    if findings:
        return 1
    if errors:
        return 2
    return 0
