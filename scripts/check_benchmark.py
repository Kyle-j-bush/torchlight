# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Check labeled synthetic regressions, without executing any fixture code."""

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path

from torchlight.files import scan_file

ROOT = Path(__file__).resolve().parents[1]


def check_cases(document: dict) -> bool:
    if document.get("schema_version") != 1 or not isinstance(
        document.get("cases"), list
    ):
        raise ValueError("expected schema_version 1 and a cases list")
    matched = unexpected = missed = scan_errors = 0
    with tempfile.TemporaryDirectory() as directory:
        for index, case in enumerate(document["cases"]):
            notebook = "cells" in case
            path = Path(directory) / f"case-{index}{'.ipynb' if notebook else '.py'}"
            if notebook:
                source = json.dumps(
                    {
                        "cells": [
                            {"cell_type": "code", "source": "\n".join(lines) + "\n"}
                            for lines in case["cells"]
                        ]
                    }
                )
            else:
                source = "\n".join(case["source"]) + "\n"
            path.write_text(source, encoding="utf-8")
            findings, errors = scan_file(
                path, assume_sessions=tuple(case.get("assume_sessions", ()))
            )
            actual = Counter(
                (f.rule_id, f.location.line, f.location.cell) for f in findings
            )
            expected = Counter(tuple(item) for item in case["expected"])
            matched += sum((actual & expected).values())
            unexpected += sum((actual - expected).values())
            missed += sum((expected - actual).values())
            scan_errors += len(errors)
            if actual != expected or errors:
                print(
                    f"FAIL {case['name']}: unexpected={dict(actual - expected)}, "
                    f"missed={dict(expected - actual)}, errors={errors}"
                )
    print(
        f"{len(document['cases'])} synthetic regression cases: {matched} findings matched, "
        f"{unexpected} unexpected, {missed} missed, {scan_errors} scan errors."
    )
    return unexpected == missed == scan_errors == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases", type=Path, default=ROOT / "benchmarks" / "cases.json"
    )
    args = parser.parse_args()
    try:
        document = json.loads(args.cases.read_text(encoding="utf-8"))
        return 0 if check_cases(document) else 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        parser.error(f"invalid regression corpus: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
