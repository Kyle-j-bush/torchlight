# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Parse Python source and find calls to selected Spark methods."""

import ast

SPARK_METHODS = {"collect", "distinct"}
PARSE_FLAGS = ast.PyCF_ONLY_AST | ast.PyCF_ALLOW_TOP_LEVEL_AWAIT


def parse_source(source: str, filename: str) -> ast.Module:
    """Parse Python source, allowing top-level await as Jupyter notebooks do."""
    return compile(source, filename, "exec", flags=PARSE_FLAGS, dont_inherit=True)


def find_spark_calls(tree: ast.Module) -> list[tuple[str, int]]:
    """Return (method, lineno) for every Spark method call in the tree."""
    calls = [
        (node.func.attr, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in SPARK_METHODS
    ]
    return sorted(calls, key=lambda call: call[1])


def format_syntax_error(exc: Exception) -> str:
    """Include the line number for syntax errors; otherwise use the error text."""
    if isinstance(exc, SyntaxError):
        return f"syntax error: {exc.msg} (line {exc.lineno})"
    return str(exc)
