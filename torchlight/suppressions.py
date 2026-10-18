# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Rule-specific, reasoned suppressions parsed from actual Python comments."""

import io
import re
import tokenize

from torchlight.diagnostics import RULES, Finding

PREFIX = re.compile(r"^#\s*torchlight:")
DIRECTIVE = re.compile(r"^#\s*torchlight:\s*ignore\[([^\]]+)\]\s*--\s*(\S.*)$")


def apply_suppressions(
    source: str, findings: list[Finding], path: str, cell: int | None = None
) -> tuple[list[Finding], list[str]]:
    """Suppress only findings starting or ending on a valid directive's line."""
    ignored: dict[int, set[str]] = {}
    errors = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT or not PREFIX.match(token.string):
            continue
        directive = DIRECTIVE.fullmatch(token.string.strip())
        codes = (
            {code.strip() for code in directive[1].split(",")} if directive else set()
        )
        if not codes or not codes <= RULES.keys():
            position = (
                f"cell {cell},line {token.start[0]}"
                if cell is not None
                else token.start[0]
            )
            errors.append(
                f"{path}:{position}: invalid suppression; use "
                "# torchlight: ignore[TL001] -- reason (known rule IDs and a reason required)"
            )
        else:
            ignored[token.start[0]] = codes
    return [
        finding
        for finding in findings
        if finding.rule_id not in ignored.get(finding.location.line, set())
        and finding.rule_id not in ignored.get(finding.end_line, set())
    ], errors
