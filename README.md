# Torchlight

[![CI](https://github.com/Kyle-j-bush/torchlight/actions/workflows/ci.yml/badge.svg)](https://github.com/Kyle-j-bush/torchlight/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Kyle-j-bush/torchlight/actions/workflows/codeql.yml/badge.svg)](https://github.com/Kyle-j-bush/torchlight/actions/workflows/codeql.yml)
[![PyPI](https://img.shields.io/pypi/v/torchlight-spark)](https://pypi.org/project/torchlight-spark/)
[![Python](https://img.shields.io/pypi/pyversions/torchlight-spark)](https://pypi.org/project/torchlight-spark/)

**Review risky Spark changes before they reach production—without running a cluster.**

Torchlight checks Python files and Jupyter notebooks for a small set of Spark
DataFrame risks. Warnings include receiver evidence, the potential consequence,
and a review suggestion. It does not blacklist every expensive-looking method,
execute your code, import Spark, or send your source to an API.

Requires Python 3.12+. No third-party runtime dependencies.

## Install and run

**v0.6.0** adds Databricks Python source notebooks and TL005 for eager
`list()`/`tuple()` consumption of Spark local iterators. Git-base comparison
shipped in v0.5.0; the scanner API shipped in v0.4.0. See the
[Spark-version assessment](docs/development/spark-versions.md) for targeting limits.

```sh
python -m pip install --upgrade torchlight-spark
torchlight path/to/file.py path/to/notebook.ipynb path/to/directory
```

For an isolated installation, use `pipx install torchlight-spark`. The distribution
is named `torchlight-spark`; its command and import package are `torchlight`.
Do not install it alongside the unrelated `torchlight` PyPI distribution.

You can also run without installing:

```sh
python -m torchlight jobs/ notebooks/
# Or: python main.py <paths...>
```

## Five focused checks

| Rule | What deserves review | What is not automatically wrong |
| --- | --- | --- |
| **TL001** | `.collect()` or `.toPandas()` on a known Spark DataFrame without a recognized row bound | An intentional small result, or a literal `.limit(100)` before collection |
| **TL002** | A known `.coalesce(1)` feeding a terminal DataFrame write | A small single-partition export; `.coalesce()` without a write is not reported |
| **TL003** | Assigning `.withColumn()` back to a loop-carried DataFrame | A fresh DataFrame each iteration, independent projections, or a known single-iteration loop |
| **TL004** | A known literal `.repartition(1)` feeding a terminal DataFrame write | A small intentional export; no warning for repartition alone or restored parallelism |
| **TL005** | Built-in `list()`/`tuple()` eagerly retaining an unbounded known Spark local iterator | Ordinary streaming iteration or a recognized explicit row bound |

**`.distinct()` alone is not a finding.** It often expresses a legitimate requirement.

For example:

```python
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()
events = spark.read.parquet("events")
rows = events.collect()
```

The warning starts with:

```text
pipeline.py:5: TL001: Potential driver-memory risk from .collect()
```

It then explains where `events` came from, that no explicit row limit was
recognized, why driver memory matters, and what to review. It does **not** claim
the job will crash or prescribe a potentially data-losing automatic fix.

## Control noise

Enable only selected rules or disable one for a run:

```sh
torchlight --select TL001,TL002 jobs/
torchlight --ignore TL003 notebooks/
```

For an intentional operation, suppress its rule with a reason on the finding's
first or last line:

```python
rows = events.collect()  # torchlight: ignore[TL001] -- verified small lookup result
```

Multiple IDs are supported: `ignore[TL001,TL002] -- reason`. Invalid IDs or missing
reasons are scan errors, not silent ignores. Directives only apply to that line
and cell, not the whole file. For TL002, annotate the **write**, where the finding
is reported, rather than an earlier `.coalesce(1)` assignment.

### Shared project policy

Torchlight v0.3.0+ reads `[tool.torchlight]` from the nearest `pyproject.toml` at
or above the working directory.

```toml
[tool.torchlight]
select = ["TL001", "TL002", "TL003", "TL004", "TL005"]
ignore = []
exclude = ["generated/**", "vendor/**"]
# Optional, after capturing and reviewing existing debt:
# baseline = ".torchlight-baseline.json"
# Opt in only if your environment supplies a session:
# assume-spark-session = ["spark"]
```

One policy applies to the entire run, including pre-commit's explicit files.
`--config PATH` replaces discovery; `--no-config` bypasses it. Explicit CLI values
replace the corresponding configured lists; ignored rules still win. Excludes
are relative to the config file's directory and also skip explicit existing
inputs. Invalid settings fail before scanning. See the
[configuration reference](docs/configuration.md) for exact precedence and globs.

### Managed notebook sessions

Torchlight recognizes Spark imports, session builders, common DataFrame-producing
APIs, simple aliases, and imported `DataFrame`/`SparkSession` annotations. It does
not assume an unknown object is Spark just because it is called `df` or `spark`.

For a session supplied by Databricks or another managed environment, opt in:

```sh
torchlight --assume-spark-session spark notebooks/
```

The option is repeatable. Explicit reassignments and opaque cells still invalidate
these assumptions.

Exported Databricks `.py` notebooks are recognized by their first-line header.
Cell boundaries and `# MAGIC %python` are understood; opaque magics invalidate
state. Reports include exported cell numbers and physical file coordinates.
See [source-notebook support and limits](docs/databricks.md).

## Use in CI and pre-commit

```sh
torchlight --format json jobs/ notebooks/ > torchlight-report.json
torchlight --format github jobs/ notebooks/
torchlight --format sarif jobs/ notebooks/ > torchlight.sarif
```

JSON uses `schema_version: 1` and includes `findings` and `errors`. Findings carry
rule IDs, one-based line/column locations, optional code-cell numbers, evidence,
explanations, recommendations, source snippets, and versioned structural
fingerprints. Errors also go to stderr.
GitHub output produces escaped Actions annotations; Jupyter notebooks use
file-level annotations with cell locations, not misleading JSON line numbers.
Databricks source exports use physical `.py` positions plus exported cell numbers.

Exit codes: **0** = no findings or errors, **1** = findings (even with errors),
**2** = errors only. A CI step fails on any enabled, unsuppressed **new** finding
when a baseline or Git comparison is active, or all findings without either.
Scan errors are never baselined. Snapshot writing has the separate contract below.

For persistent Code Scanning history, upload a full SARIF report with
`--no-baseline`, then enforce project policy separately. The
[SHA-pinned workflow example](.github/examples/torchlight-code-scanning.yml)
uploads before failing CI on findings. See [CI integration](docs/integrations.md)
and [SARIF details](docs/reporting.md), including notebook navigation limits.

Add the isolated-install hook to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/Kyle-j-bush/torchlight
    rev: v0.6.0
    hooks:
      - id: torchlight
```

Pin a full commit SHA or immutable release containing the hook manifest;
`v0.1.0` does not contain it. To try a local checkout instead, run
`pre-commit try-repo . torchlight --all-files`. For development, install the
checkout with `python -m pip install .` or run `python -m torchlight` from it.

### Adopt without fixing all existing debt

```sh
# Review the findings, then commit the snapshot.
torchlight . --write-baseline .torchlight-baseline.json
# Fail only on new findings; scan errors still fail.
torchlight . --baseline .torchlight-baseline.json
```

Successful snapshot writing exits 0, even when it records findings. Any scan or
write error exits 2 without changing the snapshot. Normal baseline-enabled scans
retain the standard 0/1/2 exit contract. Put `baseline = ".torchlight-baseline.json"`
in project policy to share it with local runs and hooks; `--no-baseline` shows
everything again.

Fingerprints ignore formatting, comments, and line/cell insertions. Baselines
match relative paths and occurrence counts, so additional identical calls are
new. Renames and call edits can change identity. See [baseline limits and safe
updates](docs/baselines.md).

### Review only findings introduced by a change

```sh
torchlight . --changed-from origin/main
```

Requires Git 2.45+ and full local history. Compares the merge base of the reference and
HEAD against the working tree, including local edits and non-ignored untracked
source. Complete changed files and notebooks are analyzed; existing findings are
matched by structural identity and count, including Git-detected renames.
Configured baselines are ignored. See [comparison behavior and CI setup](docs/git-comparison.md)
for history errors, rename limits, and why full SARIF uploads remain necessary.

## Analysis boundaries

- This is local, conservative analysis, **not a full type checker or cost model**.
  Unknown APIs and ambiguous receiver types lose Spark identity. RDDs,
  interprocedural/cross-file flow, DataFrames stored in containers or attributes,
  and risks inside SQL strings are not analyzed.
- Literal nonnegative `.limit()` bounds and global aggregation are recognized.
  Known expanding operations, including joins and common generators, discard
  row bounds. A row limit—even a very large one—does **not** prove memory safety.
  Dynamic limits, custom generators, and runtime sizes cannot be fully inferred.
- Notebook cells are analyzed in **document order**, not execution-counter order.
  Definitions, aliases, and bounds flow across code cells. Cell numbers count code
  cells only. Top-level `await`, shell escapes, `%matplotlib`, and Python cell
  magics (`capture`, `debug`, `prun`, `time`, `timeit`) are supported.
- Other line/cell magics are opaque: their cells are skipped and prior context is
  discarded. Parse errors also discard context, but scanning continues. No notebook
  outputs or shell commands are executed.
- Functions are analyzed with local scopes and annotations, using knowledge at
  their definition site, not by simulating calls. Dynamic rebinding and complex
  control flow may yield missed or unnecessary warnings.
- Directories are scanned recursively, skipping virtual environments, version
  control folders, notebook checkpoints, `__pycache__`, and `node_modules`.

**A clean scan means no supported pattern was found—not that every cell was
analyzed, or that the job is safe or efficient.** Review findings in context.

## Python integrations

```python
from pathlib import Path
from torchlight import Config, Scanner

config = Config.from_pyproject(Path("pyproject.toml"))
report = Scanner(config=config).scan([Path("jobs"), Path("notebooks")])
print(report.render("json"))
raise SystemExit(report.exit_code)
```

Policy and results are immutable; scanning prints nothing and never executes
source. `Scanner()` uses built-in policy without implicit configuration discovery.
See the [Python API reference](docs/python-api.md) for paths, baselines, errors,
and the pre-1.0 compatibility policy.

## Regression coverage

```sh
python -m unittest discover -s tests
python -m scripts.check_benchmark
```

The [public corpus](benchmarks/README.md) has 36 labeled **synthetic** Python and
notebook cases, including intentional uses and unrelated methods. It is regression
coverage, not a measured production accuracy claim. Next comes validation with
real Spark reviewers and permissioned code before adding more rules.
The [real-world benchmark protocol](benchmarks/real-world-protocol.md) specifies
permission, independent labeling, and per-rule metrics; no results are claimed yet.

## Documentation

Start with the [user guides](docs/README.md), [rule catalog](docs/rules/README.md),
and [analysis boundaries](docs/analysis.md). The
[Python compatibility assessment](docs/development/python-compatibility.md)
explains why the supported scanner runtime remains Python 3.12+ for now.
The [follow-up roadmap](docs/development/roadmap.md) separates shipped CI features
from future analysis, notebook, and validation work.

## Development and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, linting, and the pull request
workflow. CI tests Python 3.12–3.14 on Linux and Python 3.12 on macOS and Windows.
It also builds and tests both the wheel and source distribution in clean environments.
The `main` branch requires passing CI and CodeQL checks through pull requests;
direct pushes and protection bypasses are disabled.

See [SECURITY.md](SECURITY.md) for safe-use guidance and private vulnerability
reporting. Reports can contain source snippets; review them before sharing.
Never share credentials or private notebooks in issues.

Release notes are in [CHANGELOG.md](CHANGELOG.md).

## License

Copyright 2026 Kyle Bush. Licensed under the [Apache License 2.0](LICENSE)
(`Apache-2.0`). See [NOTICE](NOTICE) for attribution.
