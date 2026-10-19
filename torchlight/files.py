# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Find Python files and notebooks, and scan Python files."""

import os
from collections.abc import Callable
from pathlib import Path

from torchlight.analysis import SparkAnalyzer, format_syntax_error, parse_source
from torchlight.databricks import HEADER, scan_databricks_source
from torchlight.diagnostics import Finding
from torchlight.notebooks import scan_notebook, scan_notebook_source
from torchlight.suppressions import apply_suppressions

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


def iter_source_files(
    root: Path,
    *,
    is_excluded: Callable[[Path], bool] | None = None,
    on_error: Callable[[OSError], None] | None = None,
):
    """Yield .py and .ipynb files under root, in name order."""
    for dirpath, dirnames, filenames in os.walk(root, onerror=on_error):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in IGNORED_DIRS
            and (is_excluded is None or not is_excluded(Path(dirpath) / d))
        )
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix in SOURCE_SUFFIXES and (
                is_excluded is None or not is_excluded(path)
            ):
                yield path


def scan_python(
    path: Path, *, assume_sessions: tuple[str, ...] = ()
) -> tuple[list[Finding], list[str]]:
    """Return (findings, errors) for a Python file."""
    try:
        source = path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError) as exc:
        return [], [f"{path}: {format_syntax_error(exc)}"]
    return scan_python_source(path, source, assume_sessions=assume_sessions)


def scan_python_source(
    path: Path, source: str, *, assume_sessions: tuple[str, ...] = ()
) -> tuple[list[Finding], list[str]]:
    """Analyze in-memory Python without importing or executing it."""
    if source.split("\n", 1)[0].rstrip() == HEADER:
        return scan_databricks_source(path, source, assume_sessions=assume_sessions)
    try:
        tree = parse_source(source, str(path))
    except (SyntaxError, ValueError) as exc:
        return [], [f"{path}: {format_syntax_error(exc)}"]

    analyzer = SparkAnalyzer(str(path), assume_sessions)
    return apply_suppressions(source, analyzer.analyze(tree, source), str(path))


def scan_file(
    path: Path, *, assume_sessions: tuple[str, ...] = ()
) -> tuple[list[Finding], list[str]]:
    """Scan one source file, dispatching on its suffix."""
    if path.suffix == ".ipynb":
        return scan_notebook(path, assume_sessions=assume_sessions)
    return scan_python(path, assume_sessions=assume_sessions)


def scan_source(
    path: Path, source: bytes, *, assume_sessions: tuple[str, ...] = ()
) -> tuple[list[Finding], list[str]]:
    """Analyze a Git blob, matching file decoding and universal newline handling."""
    try:
        text = source.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeError as exc:
        return [], [f"{path}: {exc}"]
    scanner = scan_notebook_source if path.suffix == ".ipynb" else scan_python_source
    return scanner(path, text, assume_sessions=assume_sessions)
