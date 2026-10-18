# Changelog

## 0.2.0 — 2026-10-18

### Changed

- Replace name-only detection with local Spark-aware analysis of imports, session
  builders, aliases, common DataFrame APIs, and DataFrame/SparkSession annotations.
- Stop reporting `.distinct()` alone and unknown receivers as Spark risks.
- Scan notebook code cells in document order, preserving context across cells and
  invalidating stale assumptions after opaque, malformed, or unparseable cells.
- Scanner functions now return structured `Finding` objects instead of strings;
  the old `find_spark_calls()` helper has been removed.

### Added

- **TL001:** potential driver-memory risk from unbounded `.collect()`/`.toPandas()`.
- **TL002:** potential single-partition write bottleneck from `.coalesce(1)`.
- **TL003:** potential logical-plan growth from loop-carried `.withColumn()` calls.
- Evidence, qualified explanations, and review suggestions without unsafe autofixes.
- Literal row-bound recognition and conservative handling of expanding operations,
  branch-dependent types, local scopes, reassignment, and non-accumulating loops.
- Rule-specific inline suppressions requiring reasons; malformed directives are errors.
- `--select`, `--ignore`, and repeatable `--assume-spark-session` options.
- Versioned JSON reports and escaped GitHub Actions annotations via `--format`.
- Deduplication of overlapping input paths, notebook structure validation, and
  a reusable Python/notebook pre-commit hook manifest.
- A public corpus of 30 labeled synthetic regression cases and a standalone runner.
- Isolated artifact verification via `scripts/check_distribution.py --dist-dir`.

No runtime dependencies, Spark cluster, API key, or code execution required.
Baselines, PR-base comparison, and real-world accuracy validation remain follow-ups.

## 0.1.0 — 2026-10-18

- Initial PyPI release as `torchlight-spark`, with the `torchlight` command.
- Find `.collect()` and `.distinct()` calls in Python files and notebooks.
- Recursively scan directories while skipping common generated folders.
- Handle notebook magics, shell escapes, and top-level `await` without execution.
- Report findings and errors with file, cell, and line locations.
- No third-party runtime dependencies. Requires Python 3.12 or newer.
