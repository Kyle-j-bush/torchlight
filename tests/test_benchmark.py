# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from torchlight.files import scan_file


class LabeledRegressionTests(unittest.TestCase):
    def test_public_corpus_matches_rule_and_source_locations(self):
        root = Path(__file__).resolve().parents[1]
        document = json.loads(
            (root / "benchmarks" / "cases.json").read_text(encoding="utf-8")
        )
        self.assertEqual(document["schema_version"], 1)
        names = [case["name"] for case in document["cases"]]
        self.assertEqual(len(names), len(set(names)))
        with tempfile.TemporaryDirectory() as directory:
            for index, case in enumerate(document["cases"]):
                with self.subTest(case=case["name"]):
                    if "rationale" in case:
                        self.assertIsInstance(case["rationale"], str)
                        self.assertTrue(case["rationale"].strip())
                    notebook = "cells" in case
                    path = (
                        Path(directory)
                        / f"case-{index}{'.ipynb' if notebook else '.py'}"
                    )
                    if notebook:
                        source = json.dumps(
                            {
                                "cells": [
                                    {
                                        "cell_type": "code",
                                        "source": "\n".join(lines) + "\n",
                                    }
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
                    self.assertEqual(errors, [])
                    self.assertEqual(
                        Counter(
                            (f.rule_id, f.location.line, f.location.cell)
                            for f in findings
                        ),
                        Counter(tuple(item) for item in case["expected"]),
                    )


if __name__ == "__main__":
    unittest.main()
