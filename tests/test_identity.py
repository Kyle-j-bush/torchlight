# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import json
import tempfile
import unittest
from pathlib import Path

from torchlight.analysis import SparkAnalyzer, parse_source
from torchlight.notebooks import scan_notebook

PRELUDE = "from pyspark.sql import SparkSession\ndf = SparkSession.builder.getOrCreate().table('events')\n"


def findings(source, path="job.py"):
    return SparkAnalyzer(path).analyze(parse_source(source, path), source)


class FingerprintTests(unittest.TestCase):
    def test_v1_golden_key_is_stable_across_supported_python_runtimes(self):
        self.assertEqual(
            findings(PRELUDE + "df.collect()")[0].fingerprint,
            "v1:b798999ee0076cbc89cbdc7d466615d0d3c8d4e4fc38b6d1489928127abd1e3b",
        )

    def test_whitespace_comments_quotes_and_line_shifts_do_not_change_identity(self):
        original = findings(PRELUDE + "df.filter('active').collect()\n")[0]
        changed = findings(
            "\n# inserted header\n"
            + PRELUDE
            + 'df.filter(\n    "active"\n).collect( )  # review\n'
        )[0]
        self.assertEqual(original.fingerprint, changed.fingerprint)
        self.assertNotEqual(original.location, changed.location)
        self.assertEqual(original.to_dict()["fingerprint"], original.fingerprint)
        self.assertRegex(original.fingerprint, r"^v1:[0-9a-f]{64}$")

    def test_call_shape_and_scope_distinguish_findings(self):
        source = (
            PRELUDE
            + "df.collect()\ndf.toPandas()\n"
            + "def export_a():\n    df.collect()\n"
            + "def export_b():\n    df.collect()\n"
        )
        self.assertEqual(len({f.fingerprint for f in findings(source)}), 4)

    def test_paths_and_evidence_wording_are_not_content_identity(self):
        from dataclasses import replace

        original = findings(PRELUDE + "df.collect()", "/checkout/a/job.py")[0]
        relocated = findings(PRELUDE + "df.collect()", "/checkout/b/job.py")[0]
        self.assertEqual(original.fingerprint, relocated.fingerprint)
        self.assertEqual(
            original.fingerprint,
            replace(original, evidence=("new explanation",)).fingerprint,
        )

    def test_identical_calls_have_same_key_and_need_multiset_matching(self):
        result = findings(PRELUDE + "df.collect()\ndf.collect()\n")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].fingerprint, result[1].fingerprint)

    def test_notebook_insertions_do_not_change_content_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job.ipynb"
            cells = [
                {"cell_type": "code", "source": PRELUDE},
                {"cell_type": "code", "source": "df.collect()"},
            ]
            path.write_text(json.dumps({"cells": cells}), encoding="utf-8")
            before, errors = scan_notebook(path)
            self.assertEqual(errors, [])
            cells.insert(0, {"cell_type": "code", "source": "# inserted"})
            path.write_text(json.dumps({"cells": cells}), encoding="utf-8")
            after, errors = scan_notebook(path)
            self.assertEqual(errors, [])
            self.assertEqual(before[0].fingerprint, after[0].fingerprint)
            self.assertNotEqual(before[0].location.cell, after[0].location.cell)

    def test_constant_types_not_supported_by_json_have_deterministic_keys(self):
        for literal in ("b'bytes'", "1j", "...", "{1, 2}"):
            with self.subTest(literal=literal):
                source = PRELUDE + f"df.filter({literal}).collect()"
                self.assertEqual(
                    findings(source)[0].fingerprint, findings(source)[0].fingerprint
                )


if __name__ == "__main__":
    unittest.main()
