# Torchlight

[![CI](https://github.com/Kyle-j-bush/torchlight/actions/workflows/ci.yml/badge.svg)](https://github.com/Kyle-j-bush/torchlight/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Kyle-j-bush/torchlight/actions/workflows/codeql.yml/badge.svg)](https://github.com/Kyle-j-bush/torchlight/actions/workflows/codeql.yml)

**Review risky Spark changes before they reach production—without running a cluster.**

Torchlight checks Python files and Jupyter notebooks for a small set of Spark
DataFrame risks. Warnings include receiver evidence, the potential consequence,
and a review suggestion. It does not blacklist every expensive-looking method,
execute your code, import Spark, or send your source to an API.

Requires Python 3.12+. No third-party runtime dependencies.

## Install and run

The safety checks below are available in **0.2.0**. The older `0.1.0` release only
matched method names.

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

## Three focused checks

| Rule | What deserves review | What is not automatically wrong |
| --- | --- | --- |
| **TL001** | `.collect()` or `.toPandas()` on a known Spark DataFrame without a recognized row bound | An intentional small result, or a literal `.limit(100)` before collection |
| **TL002** | A known `.coalesce(1)` feeding a terminal DataFrame write | A small single-partition export; `.coalesce()` without a write is not reported |
| **TL003** | Assigning `.withColumn()` back to a loop-carried DataFrame | A fresh DataFrame each iteration, independent projections, or a known single-iteration loop |

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

## Use in CI and pre-commit

```sh
torchlight --format json jobs/ notebooks/ > torchlight-report.json
torchlight --format github jobs/ notebooks/
```

JSON uses `schema_version: 1` and includes `findings` and `errors`. Findings carry
rule IDs, one-based line/column locations, optional code-cell numbers, evidence,
explanations, recommendations, and source snippets. Errors also go to stderr.
GitHub output produces escaped Actions annotations; notebooks use file-level
annotations with cell locations in the message, not misleading JSON line numbers.

Exit codes: **0** = no findings or errors, **1** = findings (even with errors),
**2** = errors only. A CI step therefore fails on any enabled, unsuppressed finding.

Add the isolated-install hook to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/Kyle-j-bush/torchlight
    rev: v0.2.0
    hooks:
      - id: torchlight
```

Pin a full commit SHA or immutable release containing the hook manifest;
`v0.1.0` does not contain it. To try a local checkout instead, run
`pre-commit try-repo . torchlight --all-files`. For development, install the
checkout with `python -m pip install .` or run `python -m torchlight` from it.

Baselines and comparison against a PR's base revision are **not implemented yet**.
Current runs report all enabled findings in the supplied paths, not just new ones.

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

## Regression coverage

```sh
python -m unittest discover -s tests
python -m scripts.check_benchmark
```

The [public corpus](benchmarks/README.md) has 30 labeled **synthetic** Python and
notebook cases, including intentional uses and unrelated methods. It is regression
coverage, not a measured production accuracy claim. Next comes validation with
real Spark reviewers and permissioned code before adding more rules.

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
