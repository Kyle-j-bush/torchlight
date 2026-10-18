# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Test each built distribution in a fresh environment, outside the source tree."""

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
        source.write_text("df.collect()\n", encoding="utf-8")
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
            if (result.returncode, result.stdout, result.stderr) != (
                1,
                f"{source}:1: spark method .collect()\n",
                "",
            ):
                raise SystemExit(f"Installed CLI failed: {result}")


def main() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    for pattern in ("*.whl", "*.tar.gz"):
        archives = list((ROOT / "dist").glob(pattern))
        if len(archives) != 1:
            raise SystemExit(
                f"Expected exactly one {pattern} in dist/, found {len(archives)}"
            )
        check_install(archives[0], project)


if __name__ == "__main__":
    main()
