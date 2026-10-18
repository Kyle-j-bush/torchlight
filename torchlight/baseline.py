# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Strict, portable baselines with occurrence counts and atomic updates."""

import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath

from torchlight.diagnostics import RULES, Finding
from torchlight.identity import project_path

type Key = tuple[str, str, str]


class BaselineError(ValueError):
    """A baseline must not hide findings when it cannot be safely interpreted."""


def read_baseline(path: Path) -> Counter[Key]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != 1
            or type(document.get("schema_version")) is not int
            or document.get("fingerprint_version") != "v1"
            or not isinstance(document.get("findings"), list)
        ):
            raise BaselineError(
                "expected baseline schema 1 with fingerprint_version 'v1'"
            )
        counts: Counter[Key] = Counter()
        for entry in document["findings"]:
            if not isinstance(entry, dict) or set(entry) != {
                "path",
                "rule_id",
                "fingerprint",
                "count",
            }:
                raise BaselineError(
                    "each finding needs path, rule_id, fingerprint, count"
                )
            name, rule, identity, count = (
                entry[key] for key in ("path", "rule_id", "fingerprint", "count")
            )
            if (
                not isinstance(name, str)
                or not name
                or "\\" in name
                or ":" in name
                or "\x00" in name
                or PurePosixPath(name).is_absolute()
                or any(part in {"", ".", ".."} for part in name.split("/"))
            ):
                raise BaselineError(
                    "finding paths must be normalized project-relative paths"
                )
            if not isinstance(rule, str) or rule not in RULES:
                raise BaselineError("unknown rule ID in baseline")
            if not isinstance(identity, str) or not re.fullmatch(
                r"v1:[0-9a-f]{64}", identity
            ):
                raise BaselineError("invalid or unsupported finding fingerprint")
            if type(count) is not int or count < 1:
                raise BaselineError("finding count must be a positive integer")
            key = (name, rule, identity)
            if key in counts:
                raise BaselineError(
                    "duplicate baseline entry; use its occurrence count"
                )
            counts[key] = count
        return counts
    except (OSError, ValueError) as exc:
        raise BaselineError(f"{path}: {exc}") from exc


def _key(finding: Finding, root: Path) -> Key | None:
    name = project_path(finding.path, root)
    if name is not None and ("\\" in name or ":" in name):
        return None  # Such filenames cannot be represented portably on Windows.
    return (name, finding.rule_id, finding.fingerprint) if name is not None else None


def new_findings(
    findings: list[Finding], baseline: Counter[Key], root: Path
) -> list[Finding]:
    remaining = baseline.copy()
    result = []
    for finding in findings:
        key = _key(finding, root)
        if key is not None and remaining[key] > 0:
            remaining[key] -= 1
        else:
            result.append(finding)
    return result


def validate_destination(path: Path) -> None:
    # Explicit updates may replace a valid baseline, never an unrelated file or
    # a symlink. Parent directories are not created implicitly.
    if path.is_symlink():
        raise BaselineError(f"{path}: refusing to replace a symlink")
    if path.exists():
        read_baseline(path)


def write_baseline(path: Path, findings: list[Finding], root: Path) -> None:
    validate_destination(path)
    counts: Counter[Key] = Counter()
    for finding in findings:
        key = _key(finding, root)
        if key is None:
            raise BaselineError(
                f"{finding.path}: cannot baseline a finding outside project root {root} "
                "or with a nonportable path"
            )
        counts[key] += 1
    document = {
        "schema_version": 1,
        "fingerprint_version": "v1",
        "findings": [
            {"path": name, "rule_id": rule, "fingerprint": identity, "count": count}
            for (name, rule, identity), count in sorted(counts.items())
        ],
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".torchlight-",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(document, indent=2, ensure_ascii=True) + "\n")
        os.replace(temporary, path)
    except (OSError, ValueError) as exc:
        raise BaselineError(f"{path}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
