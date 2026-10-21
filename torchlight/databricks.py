# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Databricks Python source exports, with physical file coordinates and cell state."""

import ast
import io
import tokenize
from pathlib import Path

from torchlight.analysis import SparkAnalyzer, format_syntax_error
from torchlight.diagnostics import Finding, Location
from torchlight.graph import _GraphCollector
from torchlight.notebooks import PYTHON_CELL_MAGICS, _parse_cell
from torchlight.plugins import Plugin
from torchlight.suppressions import apply_suppressions

HEADER = "# Databricks notebook source"
SEPARATOR = "# COMMAND ----------"


def scan_databricks_source(
    path: Path,
    source: str,
    *,
    assume_sessions: tuple[str, ...] = (),
    plugins: tuple[Plugin, ...] = (),
    _collector: _GraphCollector | None = None,
) -> tuple[list[Finding], list[str]]:
    if _collector is not None:
        _collector.set_source_kind("databricks")
    lines = source.splitlines(keepends=True)
    comments = {}
    strings = 0
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            kind = tokenize.tok_name[token.type]
            if kind in {"FSTRING_START", "TSTRING_START"}:
                strings += 1
            elif kind in {"FSTRING_END", "TSTRING_END"}:
                strings -= 1
            elif not strings and token.type == tokenize.COMMENT and token.start[1] == 0:
                comments[token.start[0]] = token.string.rstrip()
    except (tokenize.TokenError, IndentationError) as exc:
        # Without reliable tokens, markers inside a multiline string are ambiguous.
        return [], [f"{path}: source notebook tokenization error: {exc}"]

    separators = [line for line, comment in comments.items() if comment == SEPARATOR]
    starts, ends = [0, *separators], [*(line - 1 for line in separators), len(lines)]
    analyzer = SparkAnalyzer(
        str(path), assume_sessions, plugins=plugins, _collector=_collector
    )
    findings, errors = [], []
    for cell, (start, end) in enumerate(zip(starts, ends, strict=True), 1):
        decoded = []
        prefixes = {}
        for index in range(start, end):
            comment = comments.get(index + 1, "")
            prefix = (
                8
                if comment.startswith("# MAGIC ")
                else (7 if comment == "# MAGIC" else 0)
            )
            decoded.append(lines[index][prefix:])
            prefixes[index + 1] = prefix
        first = next(
            (
                i
                for i, line in enumerate(decoded)
                if line.strip() and not line.lstrip().startswith("#")
            ),
            None,
        )
        boundary_line = start + (first or 0) + 1
        boundary_location = (
            Location(boundary_line, prefixes.get(boundary_line, 0) + 1, cell)
            if _collector is not None
            else None
        )
        if first is not None and decoded[first].strip() == "%python":
            decoded[first] = "\n"
        elif first is not None and decoded[first].lstrip().startswith("%%"):
            magic = decoded[first].lstrip()[2:].split()
            if not magic or magic[0] not in PYTHON_CELL_MAGICS:
                analyzer.forget(
                    reason=f"Opaque code cell {cell}", location=boundary_location
                )
                continue
        cell_source = "".join(decoded)
        try:
            parsed = _parse_cell(cell_source, f"{path}:cell {cell}")
        except (SyntaxError, ValueError) as exc:
            if isinstance(exc, SyntaxError) and exc.lineno is not None:
                exc.lineno += start
            errors.append(f"{path}:cell {cell}: {format_syntax_error(exc)}")
            analyzer.forget(
                reason=f"Unparseable code cell {cell}", location=boundary_location
            )
            continue
        if parsed is None:
            analyzer.forget(
                reason=f"Opaque code cell {cell}", location=boundary_location
            )
            continue
        tree, cleaned = parsed
        ast.increment_lineno(tree, start)
        # Parse decoded code, but report columns/snippets in the original export.
        for node in ast.walk(tree):
            for line_attribute, column_attribute in (
                ("lineno", "col_offset"),
                ("end_lineno", "end_col_offset"),
            ):
                column = getattr(node, column_attribute, None)
                if column is not None:
                    setattr(
                        node,
                        column_attribute,
                        column + prefixes.get(getattr(node, line_attribute), 0),
                    )
        cell_findings, cell_errors = apply_suppressions(
            cleaned,
            analyzer.analyze(tree, source, cell),
            str(path),
            cell,
            line_offset=start,
            rules=analyzer.rules,
        )
        findings.extend(cell_findings)
        errors.extend(cell_errors)
    return findings, errors
