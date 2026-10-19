# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""SARIF 2.1.0 for code-review integrations, without runtime dependencies."""

from collections import Counter
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import quote

from torchlight.diagnostics import RULES, Finding
from torchlight.identity import project_path

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
REPOSITORY = "https://github.com/Kyle-j-bush/torchlight"


def sarif_report(findings: list[Finding], errors: list[str], root: Path) -> dict:
    root = root.resolve()
    root_uri = root.as_uri().rstrip("/") + "/"
    rules = [
        {
            "id": code,
            "name": code,
            "shortDescription": {"text": rule.title},
            "fullDescription": {"text": rule.explanation},
            "helpUri": f"{REPOSITORY}/blob/main/docs/rules/{code}.md",
            "help": {"text": f"{rule.explanation}\n\nReview: {rule.recommendation}"},
            "defaultConfiguration": {"level": "warning"},
            "properties": {
                "tags": ["pyspark", "reliability"],
                "problem.severity": "warning",
            },
        }
        for code, rule in RULES.items()
    ]
    indices = {code: index for index, code in enumerate(RULES)}
    results = []
    occurrences = Counter()
    for finding in findings:
        # Code Scanning cannot display symlink locations. Unlike baseline named
        # paths, SARIF locations refer to the resolved source artifact.
        path = Path(finding.path).resolve()
        relative = project_path(path, root)
        artifact = (
            {"uri": quote(relative, safe="/"), "uriBaseId": "%SRCROOT%"}
            if relative is not None
            else {"uri": path.as_uri()}
        )
        location = finding.location
        physical = {"artifactLocation": artifact}
        if location.cell is None or path.suffix == ".py":
            physical["region"] = {
                "startLine": location.line,
                "startColumn": location.column,
                "endLine": finding.end_line,
            }
        position = f"{location.describe()}: " if location.cell is not None else ""
        identity = finding.fingerprint
        occurrence_key = (artifact["uri"], finding.rule_id, identity)
        occurrences[occurrence_key] += 1
        properties = {
            "evidence": list(finding.evidence),
            "sourceSnippet": finding.snippet,
        }
        if location.cell is not None:
            properties["notebookLocation"] = {
                "cell": location.cell,
                "line": location.line,
                "column": location.column,
                "endLine": finding.end_line,
            }
        results.append(
            {
                "ruleId": finding.rule_id,
                "ruleIndex": indices[finding.rule_id],
                "level": "warning",
                "message": {
                    "text": (
                        f"{position}{finding.message}\n"
                        f"Evidence: {'; '.join(finding.evidence)}\n"
                        f"Why: {finding.rule.explanation}\n"
                        f"Review: {finding.rule.recommendation}"
                    )
                },
                "locations": [{"physicalLocation": physical}],
                "partialFingerprints": {
                    "torchlightStructural/v1": identity,
                    # GitHub consumes primaryLocationLineHash specifically. The
                    # occurrence suffix distinguishes repeated identical calls.
                    "primaryLocationLineHash": f"{identity.removeprefix('v1:')}:{occurrences[occurrence_key]}",
                },
                "properties": properties,
            }
        )
    driver = {"name": "Torchlight", "informationUri": REPOSITORY, "rules": rules}
    try:
        driver["version"] = version("torchlight-spark")
    except PackageNotFoundError:
        pass  # A source checkout need not be installed as a distribution.
    invocation = {
        "executionSuccessful": not errors,
        "workingDirectory": {"uri": root_uri},
    }
    if errors:
        invocation["toolExecutionNotifications"] = [
            {"level": "error", "message": {"text": error}} for error in errors
        ]
    return {
        "$schema": SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": driver},
                "columnKind": "unicodeCodePoints",
                "originalUriBaseIds": {"%SRCROOT%": {"uri": root_uri}},
                "invocations": [invocation],
                "results": results,
            }
        ],
    }
