# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import json
import subprocess
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from torchlight import Config, ConfigError, Rule, Scanner
from torchlight.baseline import BaselineError, read_baseline, write_baseline
from torchlight.plugins import API_VERSION, CallFacts, Diagnostic, Plugin, Value

SOURCE = "from pyspark.sql import SparkSession\ndf = SparkSession.builder.getOrCreate().table('events')\ndf.count()\n"
RULE = Rule(
    "ACME001", "Review count", "A local team policy.", "Review the job's needs."
)


class CountDetector:
    rule_id = "ACME001"

    def check(self, facts: CallFacts):
        if facts.receiver.kind == "frame" and facts.method == "count":
            yield Diagnostic(self.rule_id, (facts.receiver.origin,), " from .count()")


class PluginTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / "job.py"
        self.path.write_text(SOURCE, encoding="utf-8")
        self.plugin = Plugin(RULE, CountDetector())

    def config(self, **kwargs):
        return Config(root=self.root, plugins=[self.plugin], **kwargs)

    def test_public_registration_is_scoped_and_reports_own_metadata(self):
        plugins = [self.plugin]
        config = Config(root=self.root, plugins=plugins)
        plugins.clear()
        config.rules.clear()
        self.assertEqual(API_VERSION, 1)
        self.assertEqual(Scanner().scan(self.path).exit_code, 0)
        report = Scanner(config).scan(self.path)
        self.assertEqual(report.errors, ())
        self.assertEqual([f.rule_id for f in report.findings], [RULE.code])
        self.assertEqual(report.findings[0].rule, RULE)
        self.assertEqual(
            report.to_dict()["findings"][0]["explanation"], RULE.explanation
        )
        for output_format in ("text", "json", "github", "sarif"):
            self.assertIn(RULE.code, report.render(output_format))
        descriptors = json.loads(report.render("sarif"))["runs"][0]["tool"]["driver"][
            "rules"
        ]
        self.assertEqual(descriptors[-1]["id"], RULE.code)
        self.assertNotIn("helpUri", descriptors[-1])
        self.assertEqual(Scanner().scan(self.path).exit_code, 0)
        self.assertEqual(
            Scanner(self.config(ignore={RULE.code})).scan(self.path).exit_code, 0
        )
        self.assertEqual(Scanner(self.config(select=[])).scan(self.path).exit_code, 0)

    def test_invalid_registration_and_versions_are_rejected(self):
        for version in (0, 2, True, "1"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                Plugin(RULE, CountDetector(), api_version=version)
        for rule in (
            None,
            Rule("TL999", "a", "b", "c"),
            Rule("bad", "a", "b", "c"),
            Rule("ACME001", "", "b", "c"),
        ):
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                Plugin(rule, CountDetector())
        with self.assertRaises(ValueError):
            Plugin(RULE, object())
        with self.assertRaises(ConfigError):
            Config(plugins=None)
        for plugins in ([self.plugin, self.plugin], [object()], "module:plugin"):
            with self.subTest(plugins=plugins), self.assertRaises(ConfigError):
                Config(plugins=plugins)
        with self.assertRaises(ConfigError):
            Config(select={RULE.code})
        policy = self.root / "pyproject.toml"
        policy.write_text(
            '[tool.torchlight]\nplugins = ["must.not.import"]\n', encoding="utf-8"
        )
        with self.assertRaises(ConfigError):
            Config.from_pyproject(policy)

    def test_facts_and_plugin_registration_are_frozen(self):
        for value, attribute, replacement in (
            (self.plugin, "rule", RULE),
            (Value("frame", "source"), "kind", "module"),
            (CallFacts(Value("frame", "source"), "count"), "method", "collect"),
        ):
            with self.assertRaises(FrozenInstanceError):
                setattr(value, attribute, replacement)

    def test_bad_results_and_exceptions_fail_closed_without_leaking_messages(self):
        class Broken(CountDetector):
            def check(self, facts):
                raise RuntimeError("private-secret")

        class Returns(CountDetector):
            def __init__(self, result):
                self.result = result

            def check(self, facts):
                return self.result

        for detector in (
            Broken(),
            Returns(None),
            Returns([None]),
            Returns([Diagnostic("TL001", ("x",))]),
            Returns([Diagnostic(RULE.code, ())]),
            Returns([Diagnostic(RULE.code, (123,))]),
            Returns([Diagnostic(RULE.code, ("x",), None)]),
        ):
            with self.subTest(detector=detector):
                report = Scanner(
                    Config(root=self.root, plugins=[Plugin(RULE, detector)])
                ).scan(self.path)
                self.assertEqual(report.exit_code, 2)
                self.assertIn("plugin ACME001 failed", report.errors[0])
                self.assertNotIn("private-secret", report.render("json"))
                self.assertFalse(
                    json.loads(report.render("sarif"))["runs"][0]["invocations"][0][
                        "executionSuccessful"
                    ]
                )

    def test_alias_identity_suppression_and_all_notebook_formats(self):
        scanner = Scanner(self.config(select={RULE.code}))
        first = scanner.scan(self.path).findings[0]
        self.path.write_text(
            "# shifted\n" + SOURCE.replace("df.count()", "df.count( )"),
            encoding="utf-8",
        )
        self.assertEqual(
            first.fingerprint, scanner.scan(self.path).findings[0].fingerprint
        )
        self.path.write_text(
            SOURCE.replace("df.count()", "alias = df\nalias.count()"), encoding="utf-8"
        )
        self.assertEqual(len(scanner.scan(self.path).findings), 1)
        for suffix, source in (
            (
                ".py",
                SOURCE.rstrip() + " # torchlight: ignore[ACME001] -- team exception\n",
            ),
            (
                ".ipynb",
                json.dumps({"cells": [{"cell_type": "code", "source": SOURCE}]}),
            ),
            (
                ".py",
                "# Databricks notebook source\n"
                + SOURCE.rsplit("df.count()", 1)[0]
                + "# COMMAND ----------\n# MAGIC %python\n# MAGIC df.count()\n",
            ),
        ):
            path = self.root / ("notebook" + suffix)
            path.write_text(source, encoding="utf-8")
            report = scanner.scan(path)
            self.assertEqual(report.errors, ())
            self.assertEqual(len(report.findings), 0 if "ignore[" in source else 1)

    def test_plugin_baselines_are_strict_and_duplicate_aware(self):
        baseline = self.root / "debt.json"
        config = self.config(baseline=baseline)
        scanner = Scanner(config)
        findings = list(scanner.scan(self.path, use_baseline=False).findings)
        write_baseline(baseline, findings, self.root, rules=config.rules)
        with self.assertRaises(BaselineError):
            read_baseline(baseline)
        self.assertEqual(scanner.scan(self.path).exit_code, 0)
        write_baseline(baseline, findings, self.root, rules=config.rules)
        self.path.write_text(SOURCE + "df.count()\n", encoding="utf-8")
        self.assertEqual(len(scanner.scan(self.path).findings), 1)

    def test_plugin_registration_preserves_all_builtin_outputs(self):
        self.path.write_text(
            SOURCE
            + "df.collect()\nlist(df.toLocalIterator())\ndf.coalesce(1).write.parquet('out')\ndf.repartition(1).write.parquet('out')\nfor name in names:\n    df = df.withColumn(name, expr)\n",
            encoding="utf-8",
        )
        plain = Scanner(Config(root=self.root)).scan(self.path)
        extended = Scanner(self.config(ignore={RULE.code})).scan(self.path)
        self.assertEqual(
            {f.rule_id for f in plain.findings},
            {"TL001", "TL002", "TL003", "TL004", "TL005"},
        )
        for output_format in ("text", "json", "github", "sarif"):
            self.assertEqual(
                plain.render(output_format), extended.render(output_format)
            )

    def test_git_comparison_uses_same_plugins_on_both_snapshots(self):
        for args in (
            ("init", "--template=", "-b", "main"),
            ("config", "user.name", "Tests"),
            ("config", "user.email", "tests@example.invalid"),
            ("add", "job.py"),
            ("commit", "-m", "base"),
        ):
            subprocess.run(
                ["git", "-c", "commit.gpgsign=false", *args],
                cwd=self.root,
                capture_output=True,
                check=True,
            )
        scanner = Scanner(self.config(select={RULE.code}))
        self.path.write_text("# shifted\n" + SOURCE, encoding="utf-8")
        self.assertEqual(scanner.scan(self.path, changed_from="HEAD").exit_code, 0)
        self.path.write_text(SOURCE + "df.count()\n", encoding="utf-8")
        report = scanner.scan(self.path, changed_from="HEAD")
        self.assertEqual(report.errors, ())
        self.assertEqual(len(report.findings), 1)
