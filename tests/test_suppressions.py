# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import json
import tempfile
import unittest
from pathlib import Path

from torchlight.files import scan_file

SETUP = "from pyspark.sql import SparkSession\ndf = SparkSession.builder.getOrCreate().table('events')\n"


class SuppressionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def scan(self, source):
        path = self.root / "example.py"
        path.write_text(SETUP + source, encoding="utf-8")
        return scan_file(path)

    def test_reasoned_suppression_matches_only_its_rule(self):
        self.assertEqual(
            self.scan("df.collect() # torchlight: ignore[TL001] -- small lookup table"),
            ([], []),
        )
        findings, errors = self.scan(
            "df.collect() # torchlight: ignore[TL002] -- small export"
        )
        self.assertEqual([f.rule_id for f in findings], ["TL001"])
        self.assertEqual(errors, [])

    def test_multiple_codes_and_multiline_call(self):
        self.assertEqual(
            self.scan(
                "df.collect(\n) # torchlight: ignore[TL001, TL002] -- checked result size"
            ),
            ([], []),
        )
        self.assertEqual(
            self.scan(
                "df.collect( # torchlight: ignore[TL001] -- checked result size\n)"
            ),
            ([], []),
        )

    def test_string_contents_are_not_directives(self):
        findings, errors = self.scan(
            'text = """\n# torchlight: ignore[TL001] -- just a string\n"""\ndf.collect()'
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(errors, [])

    def test_directives_do_not_apply_to_other_lines(self):
        findings, errors = self.scan(
            "# torchlight: ignore[TL001] -- not a file-wide directive\ndf.collect()"
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(errors, [])

    def test_invalid_directives_are_errors_not_silent_suppressions(self):
        for directive in (
            "ignore[TL001]",
            "ignore[TL001] -- ",
            "ignore[] -- reason",
            "ignore[TL999] -- reason",
            "ignore[TL001,] -- reason",
            "ignore -- reason",
        ):
            with self.subTest(directive=directive):
                findings, errors = self.scan(f"df.collect() # torchlight: {directive}")
                self.assertEqual(len(findings), 1)
                self.assertEqual(len(errors), 1)
                self.assertIn("example.py:3: invalid suppression", errors[0])

    def test_suppressed_assignment_still_propagates_context(self):
        findings, errors = self.scan(
            "for name in columns:\n"
            "    df = df.withColumn(name, expr) # torchlight: ignore[TL003] -- bounded column list\n"
            "df.collect()"
        )
        self.assertEqual([f.rule_id for f in findings], ["TL001"])
        self.assertEqual(errors, [])

    def test_notebook_directives_are_cell_local_and_magics_are_cleaned(self):
        path = self.root / "example.ipynb"
        path.write_text(
            json.dumps(
                {
                    "cells": [
                        {"cell_type": "code", "source": SETUP},
                        {
                            "cell_type": "code",
                            "source": "%%time\n!echo 'not Python\ndf.collect() # torchlight: ignore[TL001] -- checked size",
                        },
                        {"cell_type": "code", "source": "df.collect()"},
                        {
                            "cell_type": "code",
                            "source": "df.collect() # torchlight: ignore[TL001]",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        findings, errors = scan_file(path)
        self.assertEqual([f.location.cell for f in findings], [3, 4])
        self.assertEqual(len(errors), 1)
        self.assertIn("cell 4,line 1: invalid suppression", errors[0])


if __name__ == "__main__":
    unittest.main()
