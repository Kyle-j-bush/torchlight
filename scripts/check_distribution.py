# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Test each built distribution in a fresh environment, outside the source tree."""

import argparse
import json
import os
import subprocess
import tempfile
import tomllib
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METADATA_CHECK = """
import sys
from importlib.metadata import distribution
from pathlib import Path
import torchlight

d = distribution(sys.argv[1])
assert d.version == sys.argv[2]
assert not d.requires
assert d.metadata['License-Expression'] == 'Apache-2.0'
assert all(any(str(f).endswith('/licenses/' + name) for f in d.files)
           for name in ('LICENSE', 'NOTICE'))
assert Path(torchlight.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
"""
API_CHECK = """
import json
import sys
from pathlib import Path
from torchlight import Config, ConfigError, Finding, Location, Rule, Scanner, ScanReport

report = Scanner(Config(root=Path.cwd())).scan(Path(sys.argv[1]))
assert isinstance(report, ScanReport)
assert report.exit_code == 1 and not report.errors
assert len(report.findings) == 1 and isinstance(report.findings[0], Finding)
assert isinstance(report.findings[0].location, Location)
assert isinstance(report.findings[0].rule, Rule)
assert report.findings[0].rule_id == 'TL001'
assert report.graph is None
assert json.loads(report.render('json')) == report.to_dict()
assert report.to_dict()['schema_version'] == 1
assert report.findings[0].fingerprint.startswith('v1:')
captured = Scanner(Config(root=Path.cwd())).scan(Path(sys.argv[1]), include_graph=True)
assert captured.to_dict() == report.to_dict()
assert captured.graph is not None and captured.graph.capture_complete
assert len(captured.graph.links) == 1 and captured.graph.links[0].node_id
"""
COMPARISON_API_CHECK = """
from pathlib import Path
from torchlight import Config, Scanner

report = Scanner(Config(root=Path.cwd(), assume_sessions=('spark',))).scan(
    'job.py', changed_from='HEAD'
)
assert report.exit_code == 1 and not report.errors
assert len(report.findings) == 1
assert 'toPandas' in report.findings[0].message
captured = Scanner(Config(root=Path.cwd(), assume_sessions=('spark',))).scan(
    'job.py', changed_from='HEAD', include_graph=True
)
assert captured.to_dict() == report.to_dict()
assert captured.graph is not None
comparison = captured.graph.comparison
assert comparison.requested_ref == 'HEAD'
assert comparison.merge_base and comparison.base_capture_complete
assert comparison.current_source == 'working-tree'
assert len(captured.graph.links) == 1 and captured.graph.links[0].node_id
changed = {
    change.node_id: change.label for change in captured.graph.changes
}
assert changed[captured.graph.links[0].node_id] == 'new-or-edited'
"""
SOURCE_EXPORT_API_CHECK = """
from pathlib import Path
from torchlight import Config, Location, Scanner

report = Scanner(Config(root=Path.cwd())).scan('export.py', changed_from='HEAD')
assert report.exit_code == 1 and not report.errors
assert len(report.findings) == 1 and report.findings[0].rule_id == 'TL005'
assert report.findings[0].location == Location(7, 9, 2)
"""
PLUGIN_API_CHECK = """
import json
import sys
from torchlight import Config, Rule, Scanner
from torchlight.plugins import API_VERSION, CallFacts, Diagnostic, Plugin

class Review:
    rule_id = 'DIST001'
    def check(self, facts: CallFacts):
        if facts.receiver.kind == 'frame' and facts.method == 'collect':
            yield Diagnostic(self.rule_id, (facts.receiver.origin,))

assert API_VERSION == 1
rule = Rule('DIST001', 'Distribution plugin', 'Local policy.', 'Review it.')
report = Scanner(Config(plugins=(Plugin(rule, Review()),), select={'DIST001'})).scan(sys.argv[1])
assert not report.errors and len(report.findings) == 1
assert report.findings[0].rule == rule
assert report.to_dict()['findings'][0]['rule_id'] == 'DIST001'
assert json.loads(report.render('sarif'))['runs'][0]['tool']['driver']['rules'][-1]['id'] == 'DIST001'
assert [f.rule_id for f in Scanner().scan(sys.argv[1]).findings] == ['TL001']
"""


def check_install(archive: Path, project: dict) -> None:
    print(f"Checking {archive.name}", flush=True)
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        environment = work / "venv"
        venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt").create(environment)
        bin_dir = environment / ("Scripts" if os.name == "nt" else "bin")
        python = bin_dir / ("python.exe" if os.name == "nt" else "python")
        command = bin_dir / ("torchlight.exe" if os.name == "nt" else "torchlight")

        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                str(archive),
            ],
            cwd=work,
            check=True,
        )
        subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                METADATA_CHECK,
                project["name"],
                project["version"],
            ],
            cwd=work,
            check=True,
        )
        subprocess.run(
            [
                str(python),
                "-I",
                "-m",
                "unittest",
                "discover",
                "-s",
                str(ROOT / "tests"),
                "-v",
            ],
            cwd=work,
            check=True,
        )

        source = work / "example.py"
        source.write_text(
            "from pyspark.sql import SparkSession\n"
            "spark = SparkSession.builder.getOrCreate()\n"
            "spark.table('events').collect()\n",
            encoding="utf-8",
        )
        subprocess.run(
            [str(python), "-I", "-c", API_CHECK, str(source)],
            cwd=work,
            check=True,
        )
        subprocess.run(
            [str(python), "-I", "-c", PLUGIN_API_CHECK, str(source)],
            cwd=work,
            check=True,
        )
        for entry in ([str(command)], [str(python), "-I", "-m", "torchlight"]):
            subprocess.run(
                [*entry, "--help"], cwd=work, check=True, capture_output=True
            )
            result = subprocess.run(
                [*entry, str(source)],
                cwd=work,
                capture_output=True,
                text=True,
                check=False,
            )
            if (
                result.returncode != 1
                or not result.stdout.startswith(f"{source}:3: TL001:")
                or "Evidence:" not in result.stdout
                or "Review:" not in result.stdout
                or result.stderr
            ):
                raise SystemExit(f"Installed CLI failed: {result}")

        # Exercise configuration from outside the checkout through both installed
        # entry points, including explicit paths as supplied by pre-commit.
        (work / "pyproject.toml").write_text(
            '[tool.torchlight]\nselect = ["TL002"]\n'
            'exclude = ["generated/**"]\nassume-spark-session = ["spark"]\n',
            encoding="utf-8",
        )
        source.write_text("spark.table('events').collect()\n", encoding="utf-8")
        excluded = work / "generated" / "invalid.py"
        excluded.parent.mkdir()
        excluded.write_text("?", encoding="utf-8")
        for entry in ([str(command)], [str(python), "-I", "-m", "torchlight"]):
            for arguments, expected_status in (
                ([str(source)], 0),
                (["--select", "TL001", str(source), str(excluded)], 1),
                (["--select", "TL001", str(work)], 1),
                (["--no-config", str(source)], 0),
            ):
                result = subprocess.run(
                    [*entry, *arguments],
                    cwd=work,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if (
                    result.returncode != expected_status
                    or result.stderr
                    or (expected_status == 0 and result.stdout)
                    or (
                        expected_status == 1
                        and not result.stdout.startswith(f"{source}:1: TL001:")
                    )
                ):
                    raise SystemExit(f"Installed configuration failed: {result}")

        # Capture debt and report a new finding from the installed archives,
        # rather than accidentally exercising imports from the checkout.
        baseline = work / "baseline.json"
        for entry in ([str(command)], [str(python), "-I", "-m", "torchlight"]):
            source.write_text("spark.table('events').collect()\n", encoding="utf-8")
            captured = subprocess.run(
                [
                    *entry,
                    "--select",
                    "TL001",
                    "--write-baseline",
                    str(baseline),
                    str(source),
                ],
                cwd=work,
                capture_output=True,
                text=True,
                check=False,
            )
            if captured.returncode != 0 or captured.stderr or not baseline.is_file():
                raise SystemExit(f"Installed baseline capture failed: {captured}")
            source.write_text(
                "spark.table('events').collect()\nspark.table('other').toPandas()\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    *entry,
                    "--select",
                    "TL001",
                    "--baseline",
                    str(baseline),
                    "--format",
                    "sarif",
                    str(source),
                ],
                cwd=work,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 1 or result.stderr:
                raise SystemExit(f"Installed baseline/SARIF scan failed: {result}")
            run = json.loads(result.stdout)["runs"][0]
            if (
                len(run["results"]) != 1
                or "toPandas" not in run["results"][0]["message"]["text"]
                or run["tool"]["driver"]["version"] != project["version"]
                or not run["invocations"][0]["executionSuccessful"]
                or not run["results"][0]["partialFingerprints"]
            ):
                raise SystemExit(f"Installed SARIF report failed: {result.stdout}")

        repository = work / "comparison"
        repository.mkdir()
        source = repository / "job.py"
        source.write_text("spark.table('events').collect()\n", encoding="utf-8")
        for arguments in (
            ["init", "--template=", "-b", "main"],
            ["config", "user.name", "Torchlight Packaging"],
            ["config", "user.email", "tests@example.invalid"],
            ["add", "job.py"],
            ["commit", "-m", "base snapshot"],
        ):
            subprocess.run(
                ["git", "-c", "commit.gpgsign=false", *arguments],
                cwd=repository,
                check=True,
                capture_output=True,
            )
        source.write_text(
            "spark.table('events').collect()\nspark.table('other').toPandas()\n",
            encoding="utf-8",
        )
        subprocess.run(
            [str(python), "-I", "-c", COMPARISON_API_CHECK],
            cwd=repository,
            check=True,
        )
        for entry in ([str(command)], [str(python), "-I", "-m", "torchlight"]):
            result = subprocess.run(
                [
                    *entry,
                    "--no-config",
                    "--assume-spark-session",
                    "spark",
                    "--changed-from",
                    "HEAD",
                    "--format",
                    "json",
                    "job.py",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 1 or result.stderr:
                raise SystemExit(f"Installed Git comparison failed: {result}")
            document = json.loads(result.stdout)
            if (
                document["errors"]
                or len(document["findings"]) != 1
                or "toPandas" not in document["findings"][0]["message"]
            ):
                raise SystemExit(
                    f"Installed Git comparison report failed: {result.stdout}"
                )

        source = repository / "export.py"
        export_base = (
            "# Databricks notebook source\nfrom pyspark.sql import SparkSession\n"
            "df = SparkSession.builder.getOrCreate().table('events')\ndf.collect()\n"
        )
        source.write_text(export_base, encoding="utf-8")
        for arguments in (["add", "export.py"], ["commit", "-m", "source export base"]):
            subprocess.run(
                ["git", "-c", "commit.gpgsign=false", *arguments],
                cwd=repository,
                check=True,
                capture_output=True,
            )
        source.write_text(
            export_base
            + "# COMMAND ----------\n# MAGIC %python\n# MAGIC list(df.toLocalIterator())\n",
            encoding="utf-8",
        )
        subprocess.run(
            [str(python), "-I", "-c", SOURCE_EXPORT_API_CHECK],
            cwd=repository,
            check=True,
        )
        for entry in ([str(command)], [str(python), "-I", "-m", "torchlight"]):
            result = subprocess.run(
                [
                    *entry,
                    "--no-config",
                    "--changed-from",
                    "HEAD",
                    "--format",
                    "sarif",
                    "export.py",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 1 or result.stderr:
                raise SystemExit(f"Installed source notebook failed: {result}")
            run = json.loads(result.stdout)["runs"][0]
            results = run["results"]
            if (
                not run["invocations"][0]["executionSuccessful"]
                or len(results) != 1
                or results[0]["ruleId"] != "TL005"
                or results[0]["locations"][0]["physicalLocation"]["region"]
                != {"startLine": 7, "startColumn": 9, "endLine": 7}
                or results[0]["properties"]["notebookLocation"]["cell"] != 2
            ):
                raise SystemExit(f"Installed source mapping failed: {result.stdout}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=ROOT / "dist",
        help="Directory containing exactly one wheel and one source archive.",
    )
    args = parser.parse_args()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    for pattern in ("*.whl", "*.tar.gz"):
        archives = list(args.dist_dir.glob(pattern))
        if len(archives) != 1:
            raise SystemExit(
                f"Expected exactly one {pattern} in {args.dist_dir}, found {len(archives)}"
            )
        check_install(archives[0], project)


if __name__ == "__main__":
    main()
