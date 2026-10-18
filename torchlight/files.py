# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Find Python files and notebooks, and scan Python files."""

import os
from pathlib import Path

from torchlight.analysis import find_spark_calls, format_syntax_error, parse_source
from torchlight.notebooks import scan_notebook

SOURCE_SUFFIXES = {".py", ".ipynb"}

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    ".ipynb_checkpoints",
    "__pycache__",
    "node_modules",
    "venv",
}


def iter_source_files(root: Path):
    """Yield .py and .ipynb files under root, in name order."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix in SOURCE_SUFFIXES:
                yield path


def scan_python(path: Path) -> tuple[list[str], list[str]]:
    """Return (findings, errors) for a Python file."""
    try:
        tree = parse_source(path.read_text(encoding="utf-8-sig"), str(path))
    except (OSError, SyntaxError, ValueError) as exc:
        return [], [f"{path}: {format_syntax_error(exc)}"]

    findings = [
        f"{path}:{lineno}: spark method .{method}()"
        for method, lineno in find_spark_calls(tree)
    ]
    return findings, []


def scan_file(path: Path) -> tuple[list[str], list[str]]:
    """Scan one source file, dispatching on its suffix."""
    if path.suffix == ".ipynb":
        return scan_notebook(path)
    return scan_python(path)
