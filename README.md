# Torchlight

[![CI](https://github.com/Kyle-j-bush/torchlight/actions/workflows/ci.yml/badge.svg)](https://github.com/Kyle-j-bush/torchlight/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Kyle-j-bush/torchlight/actions/workflows/codeql.yml/badge.svg)](https://github.com/Kyle-j-bush/torchlight/actions/workflows/codeql.yml)

Find `.collect()` and `.distinct()` calls without running your code. Uses only
the Python standard library (Python 3.12+).

## Install and run

```sh
pip install torchlight-spark
torchlight path/to/file.py path/to/notebook.ipynb path/to/directory
```

For an isolated CLI installation, use `pipx install torchlight-spark` instead.
The distribution is named `torchlight-spark`, but the command and Python package
are named `torchlight`. Do not install it alongside the unrelated `torchlight`
PyPI distribution in the same environment.

You can also run directly from a checkout:

```sh
python main.py path/to/file.py path/to/notebook.ipynb path/to/directory
# Or: python -m torchlight <paths...>
```

- Directories are scanned recursively, skipping virtual environments, version
  control folders, notebook checkpoints, `__pycache__`, and `node_modules`.
- Notebooks support top-level `await`, line magics, shell escapes, and Python
  cell magics (`capture`, `debug`, `prun`, `time`, `timeit`). Other cell magics
  are skipped. Cell numbers count code cells only.
- Detection is based on method names, not Spark type information.

Findings go to stdout; errors go to stderr:

```text
pipeline.py:4: spark method .collect()
report.ipynb:cell 3,line 2: spark method .distinct()
```

Exit codes: **0** = no findings or errors, **1** = findings (even with errors),
**2** = errors only.

Run the regression tests:

```sh
python -m unittest discover -s tests
```

## Development and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, linting, and the pull request
workflow. CI tests Python 3.12–3.14 on Linux and Python 3.12 on macOS and Windows.
It also builds and tests both the wheel and source distribution in clean environments.
The `main` branch requires passing CI and CodeQL checks through pull requests;
direct pushes and protection bypasses are disabled.

See [SECURITY.md](SECURITY.md) for safe-use guidance and private vulnerability
reporting. Never share credentials or private notebooks in issues.

Release notes are in [CHANGELOG.md](CHANGELOG.md).

## License

Copyright 2026 Kyle Bush. Licensed under the [Apache License 2.0](LICENSE)
(`Apache-2.0`). See [NOTICE](NOTICE) for attribution.
