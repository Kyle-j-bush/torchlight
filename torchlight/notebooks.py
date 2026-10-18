# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Scan notebook code cells, allowing IPython magics and shell escapes."""

import ast
import json
from pathlib import Path

from torchlight.analysis import SparkAnalyzer, format_syntax_error, parse_source
from torchlight.diagnostics import Finding

PYTHON_CELL_MAGICS = {"capture", "debug", "prun", "time", "timeit"}


def prepare_cell(source: str) -> str | None:
    """Blank magic/shell lines without shifting line numbers; skip non-Python cells."""
    lines = source.splitlines(keepends=True)
    if lines and lines[0].lstrip().startswith("%%"):
        magic = lines[0].lstrip()[2:].split()
        if not magic or magic[0] not in PYTHON_CELL_MAGICS:
            return None

    return "".join(
        "\n" if line.lstrip().startswith(("%", "!")) else line for line in lines
    )


def _parse_cell(source: str, filename: str) -> ast.Module | None:
    """Try Python first so magic-like text inside strings stays untouched."""
    try:
        return parse_source(source, filename)
    except SyntaxError:
        # These magics can replace bindings or execute Python we cannot inspect.
        # Do not retain type assumptions through them, even within this cell.
        for line in source.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("%") and not stripped.startswith("%%"):
                magic = stripped[1:].split(maxsplit=1)
                if magic and magic[0] != "matplotlib":
                    return None
        cleaned = prepare_cell(source)
        return None if cleaned is None else parse_source(cleaned, filename)


def scan_notebook(
    path: Path, *, assume_sessions: tuple[str, ...] = ()
) -> tuple[list[Finding], list[str]]:
    """Return (findings, errors), numbering code cells and their lines from 1."""
    try:
        notebook = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError) as exc:
        return [], [f"{path}: {exc}"]
    except json.JSONDecodeError as exc:
        return [], [f"{path}: invalid notebook JSON: {exc}"]

    if not isinstance(notebook, dict):
        return [], [f"{path}: not a Jupyter notebook"]
    cells = notebook.get("cells", [])
    if not isinstance(cells, list):
        return [], [f"{path}: notebook cells must be a list"]

    findings = []
    errors = []
    analyzer = SparkAnalyzer(str(path), assume_sessions)
    number = 0
    for index, cell in enumerate(cells, 1):
        if not isinstance(cell, dict):
            errors.append(f"{path}: notebook cell entry {index} must be an object")
            analyzer.forget()
            continue
        if cell.get("cell_type") != "code":
            continue
        number += 1
        source = cell.get("source", "")
        if isinstance(source, list) and all(isinstance(line, str) for line in source):
            source = "".join(source)

        filename = f"{path}:cell {number}"
        if not isinstance(source, str):
            errors.append(f"{filename}: source must be a string or a list of strings")
            analyzer.forget()
            continue
        try:
            tree = _parse_cell(source, filename)
        except (SyntaxError, ValueError) as exc:
            errors.append(f"{filename}: {format_syntax_error(exc)}")
            analyzer.forget()
            continue
        if tree is None:
            analyzer.forget()
            continue

        findings.extend(analyzer.analyze(tree, source, number))

    return findings, errors
