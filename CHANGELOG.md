# Changelog

## 0.4.0 — 2026-10-18

### Added

- **TL004:** a literal `repartition(1)` on a known Spark DataFrame feeding a
  recognized V1/V2 terminal write, with source provenance, notebook state,
  reasoned suppression, and conservative invalidation after partition changes.
  Coalesce provenance keeps TL002 without duplicate write warnings. This is a
  review request, not proof of a slow job or a promise of one output file.
- Public `Config`, `ConfigError`, `Scanner`, `ScanReport`, `Finding`, `Location`,
  and `Rule` imports. Immutable policy/results, explicit TOML loading, read-only
  baseline filtering, fresh analysis state per scan, and all four output formats.
  The API defaults to built-in policy; CLI configuration discovery is unchanged.
- Internal semantic-fact/detector boundary, contributor guide, and v0.3.0 golden
  JSON/text/fingerprint tests for the original rules. This is not a plugin API.
- Six additional synthetic corpus cases (36 total), positive/negative and
  metamorphic TL004 tests, public API/CLI parity tests, and installed API checks.

### Changed

- The CLI and Python API share scan orchestration. Directory discovery failures
  are surfaced as scan errors rather than silently appearing clean.
- Programmatic Config values are validated and caller-owned collections copied
  into immutable containers. Relative baseline paths are anchored to project root.

TL004 is enabled by default; use explicit rule selection or ignore it when
upgrading if needed. Existing TL001–TL003 output and fingerprints, JSON schema 1,
baseline schema 1, and the CLI 0/1/2 exit contract are retained. No new runtime
dependencies, confidence claims, configurable severities, or autofixes. Python
3.12+ remains required. The Python API is pre-1.0; incompatible changes require a
minor release and release notes. Real-world validation and the rest of the
research roadmap remain follow-up work, not completed benchmark claims.

## 0.3.0 — 2026-10-18

### Added

- Shared `[tool.torchlight]` policy for rule selection, ignores, path exclusions,
  and explicit SparkSession assumptions using the standard-library TOML parser.
- Deterministic working-directory discovery, explicit `--config`/`--no-config`,
  CLI overrides, and repeatable `--exclude` globs applying to explicit inputs too.
  Invalid configuration aborts before scanning with exit code 2.
- User guides, a generated rule catalog checked in CI, and curated rule examples.
- An initial Python-compatibility assessment and a permissioned, independently
  labeled real-world benchmark protocol (not a new accuracy claim).
- Versioned structural finding fingerprints, stable across formatting and
  line/cell insertions, exposed as an additive JSON schema version 1 field.
- Portable, occurrence-counted baselines through `--baseline` or project policy;
  only new findings are reported. `--no-baseline` restores the complete report.
- Explicit, atomic `--write-baseline` capture/update after error-free scans,
  refusing to overwrite unrelated files or symlinks. Successful capture exits 0;
  failed capture exits 2 without changing the snapshot.
- SARIF 2.1.0 output with rule help, evidence, occurrence-aware fingerprints,
  Unicode source coordinates, honest notebook file locations, and unsuccessful
  invocation notifications for scan errors.
- SHA-pinned GitHub Code Scanning workflow example and development-only OASIS
  schema validation in CI and release checks. No scanner network calls are added.

No runtime dependencies or new rules. Python 3.12+ remains required. Without a
baseline, scan exit semantics are unchanged. JSON schema version 1 gains only an
additive field. Git-base comparison is not implemented.

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
