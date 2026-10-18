# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Test each built distribution in a fresh environment, outside the source tree."""

import argparse
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
