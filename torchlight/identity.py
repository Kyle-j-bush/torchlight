# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Versioned structural identity, independent of source display coordinates."""

import ast
import hashlib
import json


def _syntax(value):
    if isinstance(value, ast.AST):
        # Ignore empty optional fields so new Python AST defaults do not churn
        # identity. Context and source offsets are not part of a call's shape.
        return [
            type(value).__name__,
            [
                [name, _syntax(item)]
                for name, item in ast.iter_fields(value)
                if name != "ctx" and item is not None and item != []
            ],
        ]
    if isinstance(value, list):
        return [_syntax(item) for item in value]
    # AST constants can include bytes, complex numbers, and Ellipsis. Their repr
    # is deterministic; JSON alone cannot encode all of them.
    return [type(value).__name__, repr(value)]


def call_key(node: ast.Call, parents: dict[ast.AST, ast.AST]) -> str:
    """Keep call syntax and named lexical scopes, but not line/cell numbers."""
    scopes = []
    parent = parents.get(node)
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scopes.append([type(parent).__name__, parent.name])
        elif isinstance(parent, ast.Lambda):
            scopes.append(["Lambda", "<lambda>"])
        parent = parents.get(parent)
    return json.dumps([list(reversed(scopes)), _syntax(node)], ensure_ascii=True)


def fingerprint(rule_id: str, structural_key: str) -> str:
    """A content fingerprint; consumers must also key by the artifact path."""
    payload = json.dumps(["v1", rule_id, structural_key], ensure_ascii=True)
    return "v1:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
