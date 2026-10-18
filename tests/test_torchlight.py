# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from torchlight.analysis import format_syntax_error
from torchlight.cli import main
from torchlight.files import IGNORED_DIRS, iter_source_files, scan_file, scan_python
from torchlight.notebooks import prepare_cell, scan_notebook

SETUP = (
    "from pyspark.sql import SparkSession\n"
    "spark = SparkSession.builder.getOrCreate()\n"
    "df = spark.read.parquet('events')\n"
)


def signatures(findings):
    return [(f.rule_id, f.location.line, f.location.cell) for f in findings]


class AnalysisTests(unittest.TestCase):
    def test_error_messages(self):
        error = SyntaxError("bad code", ("example.py", 3, 1, "?"))
        self.assertEqual(format_syntax_error(error), "syntax error: bad code (line 3)")
        self.assertEqual(format_syntax_error(ValueError("bad source")), "bad source")


class TemporaryFiles(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, name, source):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def notebook(self, cells):
        return self.write("example.ipynb", json.dumps({"cells": cells}))


class FileTests(TemporaryFiles):
    def test_python_with_bom(self):
        path = self.write(
            "example.py", "\ufeff" + SETUP + "await df.collect()\ndf.distinct()\n"
        )
        findings, errors = scan_python(path)
        self.assertEqual(signatures(findings), [("TL001", 4, None)])
        self.assertEqual(errors, [])

    def test_python_without_findings(self):
        self.assertEqual(scan_python(self.write("example.py", "df.count()")), ([], []))

    def test_python_syntax_error(self):
        path = self.write("example.py", "df.collect()\n?")
        self.assertEqual(
            scan_python(path),
            ([], [f"{path}: syntax error: invalid syntax (line 2)"]),
        )

    def test_unreadable_files(self):
        for scanner in (scan_python, scan_notebook):
            with self.subTest(scanner=scanner.__name__):
                findings, errors = scanner(self.root / "missing")
                self.assertEqual(findings, [])
                self.assertEqual(len(errors), 1)
                self.assertIn("missing", errors[0])

    def test_invalid_utf8_is_reported(self):
        for suffix, scanner in ((".py", scan_python), (".ipynb", scan_notebook)):
            with self.subTest(suffix=suffix):
                path = self.root / f"invalid{suffix}"
                path.write_bytes(b"\xff")
                findings, errors = scanner(path)
                self.assertEqual(findings, [])
                self.assertEqual(len(errors), 1)
                self.assertTrue(errors[0].startswith(f"{path}: "))
                self.assertIn("codec can't decode", errors[0])

    def test_recursive_discovery_is_sorted_and_skips_noise(self):
        for name in ("z.py", "a.ipynb", "b/z.py", "a/a.py", "notes.txt", "UPPER.PY"):
            self.write(name, "")
        for directory in IGNORED_DIRS:
            self.write(f"{directory}/skip.py", "df.collect()")
        self.assertEqual(
            [
                path.relative_to(self.root).as_posix()
                for path in iter_source_files(self.root)
            ],
            ["a.ipynb", "z.py", "a/a.py", "b/z.py"],
        )

    def test_dispatch(self):
        python = self.write("example.py", SETUP + "df.collect()")
        notebook = self.notebook(
            [{"cell_type": "code", "source": SETUP + "df.toPandas()"}]
        )
        self.assertEqual(scan_file(python), scan_python(python))
        self.assertEqual(scan_file(notebook), scan_notebook(notebook))

    def test_explicit_assumptions_do_not_leak_between_files(self):
        path = self.write("example.py", "spark.table('events').collect()")
        findings, errors = scan_file(path, assume_sessions=("spark",))
        self.assertEqual(signatures(findings), [("TL001", 1, None)])
        self.assertEqual(errors, [])
        self.assertEqual(scan_file(path), ([], []))


class NotebookTests(TemporaryFiles):
    def test_cell_preparation_preserves_line_numbers(self):
        source = "%%time\n%matplotlib inline\n !echo hello\ndf.collect()\n"
        self.assertEqual(prepare_cell(source), "\n\n\ndf.collect()\n")
        self.assertEqual(prepare_cell(""), "")
        self.assertEqual(prepare_cell("df.collect()"), "df.collect()")
        self.assertIsNone(prepare_cell("%%bash\necho hello"))
        self.assertIsNone(prepare_cell("%%"))

    def test_python_cell_magics(self):
        for magic in ("capture", "debug", "prun", "time", "timeit"):
            with self.subTest(magic=magic):
                self.assertEqual(
                    prepare_cell(f"  %%{magic} options\ndf.collect()"),
                    "\ndf.collect()",
                )

    def test_code_cell_numbering_and_source_formats(self):
        path = self.notebook(
            [
                {"cell_type": "markdown", "source": "df.collect()"},
                {"cell_type": "code", "source": SETUP.splitlines(keepends=True)},
                {"cell_type": "raw", "source": "df.collect()"},
                {"cell_type": "code"},
                {
                    "cell_type": "code",
                    "source": ["await df.collect()\n", "df.distinct()"],
                },
            ]
        )
        findings, errors = scan_notebook(path)
        self.assertEqual(signatures(findings), [("TL001", 1, 3)])
        self.assertEqual(errors, [])
        self.assertIn("cell 1, line 3", findings[0].evidence[0])

    def test_magics_shell_escapes_and_non_python_cells(self):
        path = self.notebook(
            [
                {"cell_type": "code", "source": "%%sql\nselect * from trucks"},
                {
                    "cell_type": "code",
                    "source": "%%time\n!echo hi\n%matplotlib inline\n"
                    + SETUP
                    + "df.collect()",
                },
                {"cell_type": "code", "source": "!echo hi\ndf.toPandas()"},
            ]
        )
        findings, errors = scan_notebook(path)
        self.assertEqual(signatures(findings), [("TL001", 7, 2), ("TL001", 2, 3)])
        self.assertEqual(errors, [])

    def test_valid_python_is_not_cleaned(self):
        source = SETUP + 'text = """hello\n%%sql\n!not a command\n"""\ndf.collect()'
        path = self.notebook([{"cell_type": "code", "source": source}])
        findings, errors = scan_notebook(path)
        self.assertEqual(signatures(findings), [("TL001", 8, 1)])
        self.assertEqual(errors, [])

    def test_cell_errors_do_not_stop_other_cells(self):
        path = self.notebook(
            [
                {"cell_type": "code", "source": "?"},
                {"cell_type": "code", "source": "%matplotlib inline\n?"},
                {"cell_type": "code", "source": SETUP + "df.collect()"},
            ]
        )
        findings, errors = scan_notebook(path)
        self.assertEqual(signatures(findings), [("TL001", 4, 3)])
        self.assertEqual(
            errors,
            [
                f"{path}:cell 1: syntax error: invalid syntax (line 1)",
                f"{path}:cell 2: syntax error: invalid syntax (line 2)",
            ],
        )

    def test_reassignment_and_opaque_cells_discard_stale_types(self):
        for opaque in (
            "df = other",
            "%%sql\nselect * from events",
            "%run other.ipynb",
            "%reset -f",
            "?",
        ):
            with self.subTest(opaque=opaque):
                path = self.notebook(
                    [
                        {"cell_type": "code", "source": SETUP},
                        {"cell_type": "code", "source": opaque},
                        {"cell_type": "code", "source": "df.collect()"},
                    ]
                )
                findings, _ = scan_notebook(path)
                self.assertEqual(findings, [])

    def test_bounds_and_partition_evidence_cross_cells(self):
        path = self.notebook(
            [
                {"cell_type": "code", "source": SETUP},
                {
                    "cell_type": "code",
                    "source": "small = df.limit(10)\nexport = df.coalesce(1)",
                },
                {
                    "cell_type": "code",
                    "source": "small.collect()\nexport.write.parquet(path)",
                },
            ]
        )
        findings, errors = scan_notebook(path)
        self.assertEqual(signatures(findings), [("TL002", 2, 3)])
        self.assertEqual(errors, [])
        self.assertIn("cell 2, line 2", findings[0].evidence[1])

    def test_invalid_notebooks(self):
        for source, message in (
            ("{", "invalid notebook JSON:"),
            ("[]", "not a Jupyter notebook"),
            ('{"cells": null}', "notebook cells must be a list"),
            ('{"cells": [null]}', "notebook cell entry 1 must be an object"),
            (
                '{"cells": [{"cell_type": "code", "source": [1]}]}',
                "cell 1: source must be a string",
            ),
        ):
            with self.subTest(source=source):
                path = self.write("invalid.ipynb", source)
                findings, errors = scan_notebook(path)
                self.assertEqual(findings, [])
                self.assertEqual(len(errors), 1)
                self.assertTrue(errors[0].startswith(f"{path}:"))
                self.assertIn(message, errors[0])

    def test_empty_notebook_with_bom(self):
        self.assertEqual(scan_notebook(self.write("empty.ipynb", "\ufeff{}")), ([], []))


class CliTests(TemporaryFiles):
    def run_cli(self, *paths):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main([str(path) for path in paths])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_no_findings(self):
        self.assertEqual(
            self.run_cli(self.write("clean.py", "df.count()")), (0, "", "")
        )
        self.assertEqual(self.run_cli(self.root), (0, "", ""))

    def test_findings(self):
        path = self.write("example.py", SETUP + "df.collect()")
        self.assertEqual(self.run_cli(path), (1, str(scan_file(path)[0][0]) + "\n", ""))

    def test_path_errors(self):
        unsupported = self.write("notes.txt", "df.collect()")
        missing = self.root / "missing"
        self.assertEqual(
            self.run_cli(missing, unsupported),
            (
                2,
                "",
                f"torchlight: {missing}: no such file or directory\n"
                f"torchlight: {unsupported}: unsupported file type (expected .py or .ipynb)\n",
            ),
        )

    def test_syntax_errors(self):
        path = self.write("bad.py", "?")
        self.assertEqual(
            self.run_cli(path),
            (
                2,
                "",
                f"torchlight: {path}: syntax error: invalid syntax (line 1)\n",
            ),
        )

    def test_findings_take_precedence_over_errors(self):
        found = self.write("found.py", SETUP + "df.collect()")
        bad = self.write("bad.py", "?")
        for paths in ((found, bad), (bad, found), (self.root,)):
            with self.subTest(paths=paths):
                status, stdout, stderr = self.run_cli(*paths)
                self.assertEqual(status, 1)
                self.assertEqual(stdout, str(scan_file(found)[0][0]) + "\n")
                self.assertIn(f"torchlight: {bad}: syntax error:", stderr)

    def test_entry_points(self):
        path = self.write("example.py", SETUP + "df.collect()")
        root = Path(__file__).resolve().parents[1]
        for entry in ([str(root / "main.py")], ["-m", "torchlight"]):
            with self.subTest(entry=entry):
                result = subprocess.run(
                    [sys.executable, *entry, str(path)],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, str(scan_file(path)[0][0]) + "\n")
                self.assertEqual(result.stderr, "")

    def test_argument_errors_and_help(self):
        for args, expected in (([], 2), (["--help"], 0)):
            with self.subTest(args=args):
                with (
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    with self.assertRaises(SystemExit) as raised:
                        main(args)
                self.assertEqual(raised.exception.code, expected)


if __name__ == "__main__":
    unittest.main()
