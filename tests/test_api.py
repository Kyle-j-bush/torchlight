# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from torchlight import Config, ConfigError, Finding, Location, Rule, Scanner, ScanReport
from torchlight.baseline import write_baseline
from torchlight.cli import main

SOURCE = "from pyspark.sql import DataFrame\ndef export(df: DataFrame):\n    df.repartition(1).write.csv('out')\n"


class PublicApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.write("job.py", SOURCE)

    def write(self, name, source):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def test_public_imports_and_default_scan(self):
        report = Scanner().scan(self.path)
        self.assertIsInstance(report, ScanReport)
        self.assertEqual(report.exit_code, 1)
        self.assertEqual(report.errors, ())
        self.assertEqual([f.rule_id for f in report.findings], ["TL004"])
        finding = report.findings[0]
        self.assertIsInstance(finding, Finding)
        self.assertIsInstance(finding.location, Location)
        self.assertIsInstance(finding.rule, Rule)

    def test_configuration_is_explicit_not_discovered_by_default(self):
        policy = self.write("pyproject.toml", "[tool.torchlight]\nselect = []\n")
        with contextlib.chdir(self.root):
            self.assertEqual(Scanner().scan("job.py").exit_code, 1)
            config = Config.from_pyproject("pyproject.toml")
            self.assertEqual(Scanner(config).scan("job.py").exit_code, 0)
        self.assertEqual(config.root, policy.parent)

    def test_explicit_policy_errors_raise_before_scanning(self):
        for source in (
            "[",
            "[project]\nname = 'other'",
            '[tool.torchlight]\nselect = ["TL999"]',
        ):
            self.write("pyproject.toml", source)
            with self.assertRaises(ConfigError):
                Config.from_pyproject(self.root / "pyproject.toml")
        with self.assertRaises(ConfigError):
            Config.from_pyproject(self.root / "absent.toml")

    def test_policy_objects_and_report_graph_are_immutable(self):
        selections, exclusions, sessions = ["TL004"], ["generated/**"], ["spark"]
        config = Config(select=selections, exclude=exclusions, assume_sessions=sessions)
        selections.clear()
        exclusions.clear()
        sessions.clear()
        self.assertEqual(config.select, frozenset({"TL004"}))
        self.assertEqual(config.exclude, ("generated/**",))
        self.assertEqual(config.assume_sessions, ("spark",))
        scanner = Scanner(config)
        report = scanner.scan(self.path)
        for obj, attribute, value in (
            (config, "select", frozenset()),
            (scanner, "config", Config()),
            (report, "findings", ()),
            (report.findings[0], "message", "changed"),
            (report.findings[0].location, "line", 99),
            (report.findings[0].rule, "title", "changed"),
        ):
            with (
                self.subTest(attribute=attribute),
                self.assertRaises(FrozenInstanceError),
            ):
                setattr(obj, attribute, value)

    def test_report_and_finding_snapshot_caller_owned_lists(self):
        evidence = ["source"]
        finding = Finding(
            "job.py", "TL004", Location(1), 1, "message", evidence, "code"
        )
        findings, errors = [finding], ["error"]
        report = ScanReport(findings, errors, self.root)
        evidence.clear()
        findings.clear()
        errors.clear()
        self.assertEqual(report.findings, (finding,))
        self.assertEqual(report.errors, ("error",))
        self.assertEqual(finding.evidence, ("source",))
        detached = report.to_dict()
        detached["findings"][0]["evidence"].clear()
        detached["errors"].clear()
        self.assertEqual(report.findings[0].evidence, ("source",))
        self.assertEqual(report.errors, ("error",))

    def test_programmatic_config_validates_values(self):
        for kwargs in (
            {"select": "TL004"},
            {"ignore": [123]},
            {"select": ["TL999"]},
            {"ignore": ["TL999"]},
            {"exclude": ["../outside"]},
            {"assume_sessions": ["spark.session"]},
            {"baseline": ""},
            {"baseline": "bad\x00path"},
            {"root": None},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ConfigError):
                Config(**kwargs)

    def test_relative_baseline_anchors_to_config_root(self):
        config = Config(root=self.root, baseline=Path("debt.json"))
        self.assertEqual(config.baseline, self.root / "debt.json")
        self.assertTrue(config.root.is_absolute())

    def test_scans_are_silent_and_do_not_execute_or_import_source(self):
        marker = self.root / "executed"
        self.path.write_text(
            f"open({str(marker)!r}, 'w').write('bad')\n"
            + SOURCE
            + "raise RuntimeError('must never execute')\n",
            encoding="utf-8",
        )
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            report = Scanner().scan(self.path)
            for output_format in ("text", "json", "github", "sarif"):
                report.render(output_format)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertFalse(marker.exists())
        self.assertEqual(report.errors, ())
        self.assertEqual([f.rule_id for f in report.findings], ["TL004"])

    def test_reusable_scanner_has_fresh_state_across_files_and_runs(self):
        path = self.write("unknown.py", "df.repartition(1).write.csv('out')")
        scanner = Scanner(Config(root=self.root))
        report = scanner.scan((self.path, path))
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(scanner.scan(path).findings, ())
        self.path.write_text("df.collect()", encoding="utf-8")
        self.assertEqual(scanner.scan(self.path).exit_code, 0)
        self.assertEqual(len(report.findings), 1)

    def test_discovery_selection_excludes_and_overlapping_inputs(self):
        self.write("generated/bad.py", "?")
        self.write("other.py", "spark.table('events').collect()")
        scanner = Scanner(
            Config(
                root=self.root,
                exclude=("generated/**",),
                select={"TL004"},
                assume_sessions=("spark",),
            )
        )
        report = scanner.scan(path for path in (self.root, self.path))
        self.assertEqual(report.errors, ())
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].rule_id, "TL004")
        ignored = Scanner(Config(ignore={"TL004"})).scan(self.path)
        self.assertEqual(ignored.exit_code, 0)

    def test_notebook_state_and_suppression_use_shared_engine(self):
        path = self.write(
            "job.ipynb",
            json.dumps(
                {
                    "cells": [
                        {
                            "cell_type": "code",
                            "source": "small = spark.table('events').repartition(1)",
                        },
                        {
                            "cell_type": "code",
                            "source": "small.write.csv('out')\nsmall.write.csv('out') # torchlight: ignore[TL004] -- intentional",
                        },
                    ]
                }
            ),
        )
        report = Scanner(Config(assume_sessions=("spark",))).scan(path)
        self.assertEqual(report.errors, ())
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].location, Location(1, 1, 2))

    def test_exit_codes_include_findings_with_errors(self):
        scanner = Scanner(Config(root=self.root))
        invalid = self.write("invalid.py", "?")
        for paths, expected in (
            ([self.path], 1),
            ([invalid], 2),
            ([self.root / "missing.py"], 2),
            ([self.write("other.txt", "text")], 2),
            ([self.path, invalid], 1),
            ([], 2),
            ([self.write("clean.py", "pass")], 0),
        ):
            with self.subTest(paths=paths):
                self.assertEqual(scanner.scan(paths).exit_code, expected)

    def test_discovery_permission_failures_cannot_be_clean_scans(self):
        with patch(
            "torchlight.files.os.scandir",
            side_effect=PermissionError(13, "denied", str(self.root)),
        ):
            report = Scanner().scan(self.root)
        self.assertEqual(report.exit_code, 2)
        self.assertIn("denied", report.errors[0])

    def test_baseline_filtering_is_read_only_and_reloaded_each_scan(self):
        baseline = self.root / "debt.json"
        scanner = Scanner(Config(root=self.root, baseline=baseline))
        all_findings = scanner.scan(self.path, use_baseline=False)
        write_baseline(baseline, list(all_findings.findings), self.root)
        content = baseline.read_bytes()
        self.assertEqual(scanner.scan(self.path).exit_code, 0)
        self.assertEqual(scanner.scan(self.path, use_baseline=False).exit_code, 1)
        self.assertEqual(baseline.read_bytes(), content)
        baseline.write_text("{}", encoding="utf-8")
        with patch("torchlight.scanner.scan_file") as scan:
            report = scanner.scan(self.path)
        scan.assert_not_called()
        self.assertEqual(report.exit_code, 2)
        self.assertIn("baseline error:", report.errors[0])

    def test_cli_and_api_reports_match_in_every_format(self):
        policy = self.write("pyproject.toml", '[tool.torchlight]\nselect = ["TL004"]\n')
        report = Scanner(Config.from_pyproject(policy)).scan(self.path)
        for output_format in ("text", "json", "github", "sarif"):
            with self.subTest(output_format=output_format):
                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    status = main(
                        [
                            "--config",
                            str(policy),
                            "--format",
                            output_format,
                            str(self.path),
                        ]
                    )
                self.assertEqual(status, report.exit_code)
                self.assertEqual(stdout.getvalue(), report.render(output_format) + "\n")
                self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(json.loads(report.render("json")), report.to_dict())

    def test_bad_api_arguments_and_formats_are_rejected(self):
        with self.assertRaises(TypeError):
            Scanner(config={})
        with self.assertRaises(TypeError):
            Scanner().scan([None])
        with self.assertRaises(TypeError):
            Scanner().scan(self.path, use_baseline="false")
        with self.assertRaises(ValueError):
            ScanReport().render("yaml")

    def test_cli_baseline_override_is_cwd_relative_not_config_relative(self):
        policy = self.write(
            "policy/pyproject.toml", '[tool.torchlight]\nselect = ["TL004"]'
        )
        source = self.write("policy/job.py", SOURCE)
        report = Scanner(Config.from_pyproject(policy)).scan(source)
        write_baseline(self.root / "debt.json", list(report.findings), report.root)
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            contextlib.chdir(self.root),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = main(
                [
                    "--config",
                    "policy/pyproject.toml",
                    "--baseline",
                    "debt.json",
                    "policy/job.py",
                ]
            )
        self.assertEqual((status, stdout.getvalue(), stderr.getvalue()), (0, "", ""))
