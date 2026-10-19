# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Command-line arguments, findings on stdout, and errors on stderr."""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from torchlight.baseline import (
    BaselineError,
    validate_destination,
    write_baseline,
)
from torchlight.config import (
    ConfigError,
    load_config,
    valid_session_name,
    validate_pattern,
)
from torchlight.diagnostics import RULES
from torchlight.reporting import render
from torchlight.scanner import Scanner


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
        choices=("text", "json", "github", "sarif"),
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
    baseline_group = parser.add_mutually_exclusive_group()
    baseline_group.add_argument(
        "--baseline",
        type=Path,
        metavar="PATH",
        help="Report only findings not recorded in this baseline JSON file.",
    )
    baseline_group.add_argument(
        "--write-baseline",
        type=Path,
        metavar="PATH",
        help="Capture all enabled findings after an error-free scan; success exits 0.",
    )
    baseline_group.add_argument(
        "--no-baseline",
        action="store_true",
        help="Ignore the configured baseline and report all enabled findings.",
    )
    baseline_group.add_argument(
        "--changed-from",
        type=git_revision,
        metavar="REF",
        help="Report findings introduced since the merge base of REF and HEAD; ignores saved baselines.",
    )
    return parser


def rule_codes(value: str) -> set[str]:
    codes = {code.strip() for code in value.split(",")}
    if not codes <= RULES.keys():
        raise argparse.ArgumentTypeError(f"expected rule IDs from {','.join(RULES)}")
    return codes


def git_revision(value: str) -> str:
    if not value.strip() or "\x00" in value:
        raise argparse.ArgumentTypeError("expected a nonempty Git revision")
    return value


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
    try:
        baseline_path = (
            args.baseline.absolute() if args.baseline is not None else config.baseline
        )
        if args.no_baseline or args.write_baseline is not None:
            baseline_path = None
        config = replace(config, baseline=baseline_path)
        if args.write_baseline is not None:
            validate_destination(args.write_baseline)
    except (BaselineError, ConfigError) as exc:
        message = f"baseline error: {exc}"
        output = render([], [message], args.format, root=config.root)
        if output:
            print(output)
        report_error(message)
        return 2

    report = Scanner(config=config).scan(args.paths, changed_from=args.changed_from)
    findings, errors = list(report.findings), list(report.errors)
    if args.write_baseline is not None and not errors:
        try:
            write_baseline(args.write_baseline, findings, config.root)
        except BaselineError as exc:
            errors.append(f"baseline error: {exc}")

    output = render(findings, errors, args.format, root=config.root)
    if output:
        print(output)
    for error in errors:
        report_error(error)

    if args.write_baseline is not None:
        return 2 if errors else 0
    if findings:
        return 1
    if errors:
        return 2
    return 0
