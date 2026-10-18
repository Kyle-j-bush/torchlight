# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Scan notebook code cells, allowing IPython magics and shell escapes."""

import ast
import json
from pathlib import Path

from torchlight.analysis import find_spark_calls, format_syntax_error, parse_source

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
        cleaned = prepare_cell(source)
        return None if cleaned is None else parse_source(cleaned, filename)


def scan_notebook(path: Path) -> tuple[list[str], list[str]]:
    """Return (findings, errors), numbering code cells and their lines from 1."""
    try:
        notebook = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError) as exc:
        return [], [f"{path}: {exc}"]
    except json.JSONDecodeError as exc:
        return [], [f"{path}: invalid notebook JSON: {exc}"]

    if not isinstance(notebook, dict):
        return [], [f"{path}: not a Jupyter notebook"]

    findings = []
    errors = []
    code_cells = (
        cell for cell in notebook.get("cells", []) if cell.get("cell_type") == "code"
    )

    for number, cell in enumerate(code_cells, 1):
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)

        filename = f"{path}:cell {number}"
        try:
            tree = _parse_cell(source, filename)
        except (SyntaxError, ValueError) as exc:
            errors.append(f"{filename}: {format_syntax_error(exc)}")
            continue
        if tree is None:
            continue

        findings.extend(
            f"{filename},line {lineno}: spark method .{method}()"
            for method, lineno in find_spark_calls(tree)
        )

    return findings, errors
