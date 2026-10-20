# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Offline permissioned-corpus pilot: freeze, blind-label, then evaluate locally."""

import argparse
import hashlib
import json
import os
import platform
from collections import Counter
from pathlib import Path, PurePosixPath

import torchlight
from torchlight.diagnostics import RULES
from torchlight.files import IGNORED_DIRS, iter_source_files, scan_source

REPO = Path(__file__).resolve().parents[1]
DECISIONS = {"surface", "do-not-surface", "uncertain"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def private_json(path: Path, document: dict) -> None:
    with open(
        path,
        "x",
        encoding="utf-8",
        opener=lambda name, flags: os.open(name, flags, 0o600),
    ) as stream:
        stream.write(json.dumps(document, indent=2, ensure_ascii=True) + "\n")


def read_json(path: Path) -> dict:
    document = json.loads(path.read_bytes())
    if (
        not isinstance(document, dict)
        or type(document.get("schema_version")) is not int
        or document["schema_version"] != 1
    ):
        raise ValueError("expected a schema_version 1 object")
    return document


def capture(root: Path) -> dict[str, bytes]:
    if not root.is_dir() or root.is_relative_to(REPO):
        raise ValueError("corpus must be an existing directory outside this repository")

    def failed(exc):
        raise exc

    sources = {}
    for path in iter_source_files(root, on_error=failed):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("corpus source symlinks are not supported")
        sources[path.relative_to(root).as_posix()] = path.read_bytes()
    if not sources:
        raise ValueError("no eligible .py/.ipynb files found")
    return dict(sorted(sources.items()))


def inventory(sources: dict[str, bytes]) -> list[dict]:
    entries = []
    for name, data in sources.items():
        lines = None
        kind = "jupyter" if name.endswith(".ipynb") else "python"
        try:
            text = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
            if kind == "jupyter":
                cells = json.loads(text)["cells"]
                lines = sum(
                    len(
                        (
                            "".join(cell["source"])
                            if isinstance(cell["source"], list)
                            else cell["source"]
                        ).splitlines()
                    )
                    for cell in cells
                    if cell["cell_type"] == "code"
                )
            else:
                kind = (
                    "databricks"
                    if text.split("\n", 1)[0].rstrip() == "# Databricks notebook source"
                    else "python"
                )
                lines = len(text.splitlines())
        except (ValueError, TypeError, KeyError, AttributeError):
            pass  # Invalid inputs remain in the manifest and become scan errors.
        entries.append(
            {
                "path": name,
                "sha256": digest(data),
                "bytes": len(data),
                "kind": kind,
                "source_lines": lines,
            }
        )
    return entries


def destination(output: Path, root: Path) -> None:
    if output.is_relative_to(REPO) or output.is_relative_to(root):
        raise ValueError("output must be outside both this repository and the corpus")
    output.mkdir(mode=0o700)  # Never overwrite an existing pilot or unrelated files.


def snapshot(root: Path, output: Path, permission: str) -> None:
    if not permission.strip():
        raise ValueError("a nonempty permission/rights confirmation is required")
    sources = capture(root)
    manifest = {
        "schema_version": 1,
        "permission": permission,
        "declared_environment": {
            "spark": "unknown",
            "python": "unknown",
            "vendor": "unknown",
        },
        "discovery": {
            "ignored_directories": sorted(IGNORED_DIRS),
            "symlink_directories": "not followed",
        },
        "files": inventory(sources),
    }
    destination(output, root)
    private_json(output / "manifest.json", manifest)
    private_json(
        output / "labels.json",
        {
            "schema_version": 1,
            "manifest_sha256": digest((output / "manifest.json").read_bytes()),
            "blind_review": False,
            "labeler": None,
            "reviewer_count": 1,
            "reviewed_files": [],
            "sites": [],
        },
    )


def site_key(site: dict) -> tuple:
    # shortcut: match exact call starts, add reviewed span matching if a pilot needs it.
    return (site["path"], site["rule_id"], site["cell"], site["line"], site["column"])


def audit_labels(labels: dict, manifest_hash: str, sources: dict[str, bytes]) -> dict:
    if (
        labels.get("manifest_sha256") != manifest_hash
        or labels.get("blind_review") is not True
    ):
        raise ValueError("labels must attest blind review of this exact manifest")
    reviewers = labels.get("reviewer_count")
    if type(reviewers) is not int or reviewers not in (1, 2):
        raise ValueError("reviewer_count must be 1 or 2")
    if not isinstance(labels.get("labeler"), str) or labels["labeler"] not in {
        "human",
        "agent",
    }:
        raise ValueError(
            "labeler must be 'human' or 'agent'; older labels need explicit provenance"
        )
    reviewed = labels.get("reviewed_files")
    if (
        not isinstance(reviewed, list)
        or any(not isinstance(name, str) for name in reviewed)
        or len(reviewed) != len(set(reviewed))
        or set(reviewed) != set(sources)
    ):
        raise ValueError(
            "every manifest file must be completely audited by the declared reviewers"
        )
    if not isinstance(labels.get("sites"), list):
        raise ValueError("sites must be a list from the independent source audit")
    sites = {}
    for site in labels["sites"]:
        if (
            not isinstance(site, dict)
            or not {
                "path",
                "rule_id",
                "cell",
                "line",
                "column",
                "a",
                "b",
                "decision",
                "rationale",
                "adjudication",
            }
            <= site.keys()
        ):
            raise ValueError(
                "site is missing required coordinates, labels, or rationale"
            )
        if (
            not isinstance(site["path"], str)
            or site["path"] not in sources
            or not isinstance(site["rule_id"], str)
            or site["rule_id"] not in RULES
        ):
            raise ValueError(
                "site path/rule must belong to the frozen built-in evaluation"
            )
        if any(
            type(site[field]) is not int or site[field] < 1
            for field in ("line", "column")
        ) or (
            site["cell"] is not None
            and (type(site["cell"]) is not int or site["cell"] < 1)
        ):
            raise ValueError(
                "site coordinates must be positive integers (cell may be null)"
            )
        if (
            any(
                not isinstance(site[field], str) or site[field] not in DECISIONS
                for field in ("a", "decision")
            )
            or (
                reviewers == 2
                and (not isinstance(site["b"], str) or site["b"] not in DECISIONS)
            )
            or (reviewers == 1 and site["b"] is not None)
        ):
            raise ValueError("invalid reviewer labels")
        if (
            not isinstance(site["rationale"], str)
            or not site["rationale"].strip()
            or not isinstance(site["adjudication"], str)
        ):
            raise ValueError(
                "each site needs a nonempty rationale and string adjudication"
            )
        if reviewers == 1 and site["decision"] != site["a"]:
            raise ValueError("single-reviewer decisions must match the original label")
        if (
            reviewers == 2
            and not (site["a"] == site["b"] == site["decision"])
            and site["decision"] != "uncertain"
            and not site["adjudication"].strip()
        ):
            raise ValueError(
                "disagreements need documented adjudication or an uncertain decision with rationale"
            )
        key = site_key(site)
        if key in sites:
            raise ValueError("duplicate audited site; use exact call-start columns")
        sites[key] = site
    return sites


def evaluate(root: Path, manifest_path: Path, labels_path: Path, output: Path) -> dict:
    manifest = read_json(manifest_path)
    labels = read_json(labels_path)
    sources = capture(root)
    if (
        not isinstance(manifest.get("permission"), str)
        or not manifest["permission"].strip()
        or manifest.get("files") != inventory(sources)
    ):
        raise ValueError(
            "corpus changed or permission is missing; freeze and audit a new snapshot"
        )
    # Names come from fresh discovery, not arbitrary paths in a supplied manifest.
    for name in sources:
        if PurePosixPath(name).is_absolute() or any(
            part in {"", ".", ".."} for part in name.split("/")
        ):
            raise ValueError("invalid corpus-relative path")
    manifest_hash = digest(manifest_path.read_bytes())
    sites = audit_labels(labels, manifest_hash, sources)
    human_agreement = labels["reviewer_count"] == 2 and labels["labeler"] == "human"
    emitted = Counter()
    raw = {"schema_version": 1, "findings": [], "errors": []}
    for name, data in sources.items():
        findings, errors = scan_source(root / name, data)
        raw["errors"].extend(errors)
        for finding in findings:
            document = finding.to_dict()
            raw["findings"].append(document)
            emitted[
                (
                    name,
                    finding.rule_id,
                    document["cell"],
                    document["line"],
                    document["column"],
                )
            ] += 1
    line_counts = [entry["source_lines"] for entry in manifest["files"]]
    lines = None if any(value is None for value in line_counts) else sum(line_counts)
    rules = {}
    for code in RULES:
        tp = fp = fn = uncertain = unreviewed = agree = total = 0
        for key in sites.keys() | emitted.keys():
            if key[1] != code:
                continue
            count, site = emitted[key], sites.get(key)
            if site is None:
                unreviewed += count
                continue
            if human_agreement:
                total += 1
                agree += site["a"] == site["b"]
            if site["decision"] == "uncertain":
                uncertain += 1
            elif site["decision"] == "surface":
                tp += min(count, 1)
                fp += max(count - 1, 0)
                fn += count == 0
            else:
                fp += count
        complete = not raw["errors"] and not unreviewed and not uncertain
        rules[code] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "uncertain_sites": uncertain,
            "unreviewed_emissions": unreviewed,
            "precision": tp / (tp + fp) if complete and tp + fp else None,
            "recall": tp / (tp + fn) if complete and tp + fn else None,
            "fp_per_kloc": fp * 1000 / lines if complete and lines else None,
            "initial_agreement": {
                "agreed": agree,
                "total": total,
                "fraction": agree / total if total else None,
            }
            if human_agreement
            else None,
        }
    package = Path(torchlight.__file__).parent
    summary = {
        "schema_version": 1,
        "status": "pilot counts only; not a production accuracy claim",
        "manifest_sha256": manifest_hash,
        "labels_sha256": digest(labels_path.read_bytes()),
        "tool_source_sha256": digest(
            b"".join(
                path.name.encode() + b"\0" + path.read_bytes()
                for path in sorted(package.glob("*.py"))
            )
        ),
        "runner_sha256": digest(Path(__file__).read_bytes()),
        "scanner_python": platform.python_version(),
        "platform": platform.platform(),
        "reviewer_count": labels["reviewer_count"],
        "labeler": labels["labeler"],
        "files": len(sources),
        "formats": dict(Counter(entry["kind"] for entry in manifest["files"])),
        "source_lines_including_blank_comments": lines,
        "scan_errors": len(raw["errors"]),
        "rules": rules,
        "limits": [
            "agent labels are not independent human validation; agreement is withheld"
            if labels["labeler"] == "agent"
            else "human provenance is self-attested, not verified by this runner",
            "counts without two independent human reviewers are provisional"
            if not human_agreement
            else "agreement is site-decision agreement, not pattern-presence agreement",
            "opaque-cell/receiver coverage and confidence intervals not measured",
            "inline suppressions honored; no project config, baseline, plugins, or session assumptions",
            "null metrics mean zero denominator or incomplete/uncertain evaluation",
            "review all aggregates before publication",
        ],
    }
    destination(output, root)
    private_json(output / "raw-findings.json", raw)
    private_json(output / "summary.json", summary)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser(
        "snapshot", help="freeze permissioned source hashes; do not scan yet"
    )
    freeze.add_argument("root", type=Path)
    freeze.add_argument("--permission", required=True)
    freeze.add_argument("--output", type=Path, required=True)
    run = commands.add_parser(
        "evaluate", help="compare audited labels with frozen-source scans"
    )
    run.add_argument("root", type=Path)
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--labels", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            snapshot(args.root.resolve(), args.output.resolve(), args.permission)
        else:
            summary = evaluate(
                args.root.resolve(), args.manifest, args.labels, args.output.resolve()
            )
            return 2 if summary["scan_errors"] else 0
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"validation error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
