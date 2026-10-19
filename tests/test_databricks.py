# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from torchlight import Config, Location, Scanner
from torchlight.baseline import write_baseline
from torchlight.cli import main
from torchlight.databricks import HEADER, SEPARATOR
from torchlight.files import scan_file, scan_source

SETUP = "from pyspark.sql import SparkSession\ndf = SparkSession.builder.getOrCreate().table('events')\n"


class DatabricksTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "export.py"

    def source(self, *cells):
        return (
            HEADER
            + "\n"
            + (SEPARATOR + "\n").join(c.rstrip("\n") + "\n" for c in cells)
        )

    def scan(self, *cells, **policy):
        self.path.write_text(self.source(*cells), encoding="utf-8")
        return Scanner(Config(root=self.root, **policy)).scan(self.path)

    def test_document_order_cells_and_physical_source_coordinates(self):
        report = self.scan(
            SETUP,
            "small = df.repartition(1)\n",
            "small.write.csv('out')\nlist(df.toLocalIterator())\n",
        )
        self.assertEqual(report.errors, ())
        self.assertEqual([f.rule_id for f in report.findings], ["TL004", "TL005"])
        self.assertEqual(
            [f.location for f in report.findings],
            [Location(7, 1, 3), Location(8, 1, 3)],
        )
        self.assertIn("cell 2, line 5", report.findings[0].evidence[1])

    def test_python_magic_decoding_maps_unicode_columns_and_multiline_calls(self):
        report = self.scan(
            SETUP,
            "# MAGIC %python\n# MAGIC π = 1; list(\n# MAGIC     df.toLocalIterator()\n# MAGIC )\n",
        )
        self.assertEqual(report.errors, ())
        finding = report.findings[0]
        self.assertEqual(finding.location, Location(6, 16, 2))
        self.assertEqual(finding.end_line, 8)
        self.assertEqual(finding.snippet, "# MAGIC π = 1; list(")
        self.assertIn("line=6,col=16", report.render("github"))
        result = json.loads(report.render("sarif"))["runs"][0]["results"][0]
        self.assertEqual(
            result["locations"][0]["physicalLocation"]["region"],
            {"startLine": 6, "startColumn": 16, "endLine": 8},
        )
        self.assertEqual(result["properties"]["notebookLocation"]["cell"], 2)

    def test_opaque_magics_discard_python_and_iterator_provenance(self):
        for magic in (
            "%sql SELECT 1",
            "%run ./other",
            "%pip install package",
            "%scala println(1)",
            "%md text",
            "%%unknown",
            "%python unexpected",
        ):
            with self.subTest(magic=magic):
                report = self.scan(
                    SETUP + "rows = df.toLocalIterator()\n",
                    f"# MAGIC {magic}\n# MAGIC df.collect()\n",
                    "df.collect()\nlist(rows)\n",
                )
                self.assertEqual(report.findings, ())
                self.assertEqual(report.errors, ())

    def test_known_python_cell_magics_reuse_notebook_behavior(self):
        report = self.scan(SETUP, "# MAGIC %%time\n# MAGIC df.collect()\n")
        self.assertEqual(report.errors, ())
        self.assertEqual(report.findings[0].location, Location(6, 9, 2))

    def test_syntax_errors_invalidate_state_but_later_cells_can_recover(self):
        report = self.scan(
            SETUP, "? invalid\n", "df.collect()\n", SETUP + "df.collect()\n"
        )
        self.assertEqual(len(report.errors), 1)
        self.assertIn("cell 2", report.errors[0])
        self.assertIn("line 5", report.errors[0])
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].location.cell, 4)

    def test_ambiguous_unclosed_strings_are_errors_not_fake_boundaries(self):
        report = self.scan(SETUP + 'text = """\n', "df.collect()\n")
        self.assertEqual(report.exit_code, 2)
        self.assertIn("tokenization error", report.errors[0])

    def test_markers_inside_strings_do_not_split_cells_or_decode_contents(self):
        report = self.scan(
            SETUP
            + 'text = """\n# COMMAND ----------\n# MAGIC %run other\n"""\ndf.collect()\n'
        )
        self.assertEqual(report.errors, ())
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].location.cell, 1)

    def test_plain_python_without_header_keeps_its_original_behavior(self):
        source = SETUP + SEPARATOR + "\n# MAGIC %run other\ndf.collect()\n"
        self.path.write_text(source, encoding="utf-8")
        findings, errors = scan_file(self.path)
        self.assertEqual(errors, [])
        self.assertEqual(len(findings), 1)
        self.assertIsNone(findings[0].location.cell)

    def test_suppressions_are_cell_local_and_use_decoded_python_comments(self):
        report = self.scan(
            SETUP,
            "# MAGIC %python\n# MAGIC list(df.toLocalIterator()) # torchlight: ignore[TL005] -- small export\n",
            "list(df.toLocalIterator())\n",
        )
        self.assertEqual(report.errors, ())
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].location.cell, 3)
        report = self.scan(
            SETUP, "# MAGIC %python\n# MAGIC df.collect() # torchlight: ignore[TL001]\n"
        )
        self.assertEqual(len(report.errors), 1)
        self.assertIn("cell 2,line 6", report.errors[0])

    def test_empty_title_and_magic_lines_and_explicit_session_assumption(self):
        report = self.scan(
            "# DBTITLE 1,Example\n# MAGIC %python\n# MAGIC\n# MAGIC spark.table('events').collect()\n",
            assume_sessions=("spark",),
        )
        self.assertEqual(report.errors, ())
        self.assertEqual(report.findings[0].location, Location(5, 9, 1))
        self.assertEqual(self.scan("", "").exit_code, 0)

    def test_bom_crlf_and_in_memory_git_blobs_match_file_scanning(self):
        source = self.source(SETUP, "df.collect()\n")
        data = ("\ufeff" + source.replace("\n", "\r\n")).encode("utf-8")
        self.path.write_bytes(data)
        self.assertEqual(scan_file(self.path), scan_source(self.path, data))

    def test_decoded_source_and_shell_escapes_are_never_executed(self):
        marker = self.root / "executed"
        report = self.scan(
            SETUP,
            "# MAGIC %python\n"
            f"# MAGIC open({str(marker)!r}, 'w').write('bad')\n"
            "# MAGIC df.collect()\n"
            "# MAGIC raise RuntimeError('must never execute')\n",
        )
        self.assertEqual(report.errors, ())
        self.assertEqual(len(report.findings), 1)
        self.assertFalse(marker.exists())

    def test_baselines_survive_cell_insertion_and_cli_api_agree(self):
        report = self.scan(SETUP, "df.collect()\n")
        baseline = self.root / "baseline.json"
        write_baseline(baseline, list(report.findings), self.root)
        report = self.scan(
            "# inserted cell\n", SETUP, "df.collect()\n", baseline=baseline
        )
        self.assertEqual(report.exit_code, 0)
        report = self.scan(SETUP, "df.collect()\n", select={"TL001"})
        for output_format in ("text", "json", "github", "sarif"):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = main(
                    [
                        str(self.path),
                        "--no-config",
                        "--select",
                        "TL001",
                        "--format",
                        output_format,
                    ]
                )
            self.assertEqual((status, stderr.getvalue()), (1, ""))
            # Root identity is relevant to SARIF and should match CLI --no-config.
            expected = (
                Scanner(Config(select={"TL001"})).scan(self.path).render(output_format)
            )
            self.assertEqual(stdout.getvalue(), expected + "\n")
