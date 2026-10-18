# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Human-readable, JSON, and safely escaped GitHub Actions output."""

import json

from torchlight.diagnostics import Finding


def escape_command(value: str, *, property_value: bool = False) -> str:
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if property_value:
        value = value.replace(":", "%3A").replace(",", "%2C")
    return value


def github_annotation(finding: Finding) -> str:
    location = finding.location
    properties = [f"file={escape_command(finding.path, property_value=True)}"]
    if location.cell is None:
        properties.extend((f"line={location.line}", f"col={location.column}"))
    # Notebook cell coordinates are not raw .ipynb JSON line numbers. Use a
    # file-level annotation rather than pointing GitHub to an unrelated JSON line.
    properties.append(f"title={finding.rule_id}")
    position = f"{location.describe()}: " if location.cell is not None else ""
    message = (
        f"{position}{finding.message}\n"
        f"Evidence: {'; '.join(finding.evidence)}\n"
        f"Why: {finding.rule.explanation}\n"
        f"Review: {finding.rule.recommendation}"
    )
    return f"::warning {','.join(properties)}::{escape_command(message)}"


def render(findings: list[Finding], errors: list[str], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(
            {
                "schema_version": 1,
                "findings": [finding.to_dict() for finding in findings],
                "errors": errors,
            },
            indent=2,
            ensure_ascii=True,
        )
    if output_format == "github":
        annotations = [github_annotation(finding) for finding in findings]
        annotations.extend(
            f"::error title=Torchlight scan error::{escape_command(error)}"
            for error in errors
        )
        return "\n".join(annotations)
    return "\n".join(str(finding) for finding in findings)
