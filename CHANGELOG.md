# Changelog

## 0.7.0 — 2026-10-18

### Added

- Public `torchlight.plugins` API version 1: immutable facts, diagnostics, detector
  protocol, and explicit `Plugin` registration through programmatic `Config`.
  Duplicate/reserved IDs, malformed metadata, unsupported API versions, and bad
  detector results fail explicitly. No plugin discovery, module/dependency loading,
  or new CLI/TOML plugin setting is introduced.
- Scoped plugin rule catalogs shared by inference, inline suppressions, strict
  baselines, all report formats, and Git base/current scans. Detached findings
  retain their rule metadata. Built-in-only output and identity are preserved;
  plugin SARIF descriptors do not invent links to Torchlight rule guides.
- A deterministic Python/Jupyter/Databricks scan-timing harness with warm-up,
  five samples, source/workload digests, and median/range. Release verification
  retains a separate timing artifact; elapsed time never gates CI. A local
  synthetic observation is documented, not presented as production throughput.
- Local real-world pilot tooling: permission attestation, frozen byte-hash manifest,
  blank blind-label template, exact source-site matching, per-rule counts and
  provisional fractions, and two-reviewer decision agreement when supplied.
  Private artifacts must stay outside the repository; no source is uploaded.
  Source changes, incomplete review attestations, and malformed labels fail;
  uncertain/unreviewed sites and scan failures withhold definitive metrics.
- Public extension/security guides, pilot workflow, installed-plugin verification,
  and a ninth pinned OASIS SARIF schema variant.

### Trust and compatibility notes

Plugins are opt-in **arbitrary trusted Python code**, not sandboxed. They must be
stateless/deterministic for repeated and differential scans. Selection filters
findings, not plugin execution. Exceptions become scan errors without echoing
their messages; process-control exceptions, timeouts, and malicious plugins are
not isolated. Never-execute guarantees apply to scanned source, not plugin code.

Default `Config.select` is normalized to the registered catalog (built-ins when
no plugins are supplied); explicit selections still replace defaults. Existing
CLI behavior, exports, built-in warnings, JSON/fingerprint/baseline schemas,
coordinates, exit codes, Python 3.12+, and zero runtime dependencies remain.
Python interfaces are still pre-1.0, with a separately versioned plugin contract.

**Real-world validation is not complete:** no permissioned corpus or independent
labels have been received, and no production accuracy figures are claimed.
Single-reviewer runs are provisional. Opaque-cell coverage, statistical intervals,
and realistic performance/memory validation remain protocol work. Spark-version
flags, automatic fixes, SQL analysis, and LSP remain deferred.

## 0.6.0 — 2026-10-18

### Added

- **TL005:** proven built-in `list()`/`tuple()` consumption of an unbounded known
  Spark `toLocalIterator()`, including local aliases, row-bound invalidation,
  shadowing, notebook boundaries, reasoned suppression, baselines, and Git review.
  Bare streaming iteration is not reported; this rule targets eager retention.
- Databricks Python source exports: first-line header recognition, token-aware
  cell delimiters and `# MAGIC` decoding, `%python`, shared document-order state,
  and conservative invalidation at opaque language/magic cells. Strings cannot
  spoof cell markers. No notebook code, magic, dependencies, or shell escapes run.
- Exported cell numbers with physical `.py` line/column/end-line mapping, including
  magic prefixes and Unicode. GitHub/SARIF link to physical source; `.ipynb`
  coordinates remain cell-relative. New source-format and rule guides explain limits.
- An upstream Spark 3.3–3.5 API/Connect assessment. No `target-spark` flag is added:
  the current warnings do not require one, and version alone omits runtime/vendor
  distinctions. No Spark runtime or vendor compatibility certification is implied.
- Eight additional synthetic cases (44 total), source mapping and iterator tests,
  an eighth SARIF schema variant, and installed archive/API/CLI verification.

### Upgrade notes

TL005 is enabled by default; explicit selections must include it to opt in.
Databricks-header `.py` files now follow notebook cell boundaries rather than
ordinary whole-file semantics. Their `cell` field is populated, but coordinates
are physical file positions, **not** Jupyter cell-local positions. Consumers
must distinguish `.py` source exports from `.ipynb`. Opaque cells can remove stale
findings; unterminated multiline constructs fail rather than guessing boundaries.
Ordinary Python and Jupyter behavior, original-rule output/fingerprints, public
exports, schemas, exit codes, Python 3.12+, and zero runtime dependencies remain.
No public plugin API, automatic fixes, new severities, or production accuracy claims.

## 0.5.0 — 2026-10-18

### Added

- `--changed-from REF` and `Scanner.scan(..., changed_from=REF)` report findings
  introduced since the unique merge base of REF and HEAD. Complete changed Python
  files/notebooks are analyzed, including committed, staged, unstaged, and
  non-ignored untracked source. Deleted files are skipped.
- Duplicate-aware structural matching across Git-detected renames, formatting,
  and notebook cell insertions. Moving source out of an excluded path or changing
  a non-source file into source is treated as newly reviewed code.
- Read-only historical blob analysis without checkout, source execution, or
  enabled Git clean/process, external diff/textconv, or fsmonitor helpers.
- Explicit errors for shallow/missing/ambiguous history, unresolved conflicts,
  unavailable blobs, and skip-worktree/assume-unchanged index entries. Changed
  source errors in either snapshot are never treated as a clean comparison.
- Git comparison guide, PR enforcement example retaining full SARIF uploads,
  temporary-repository regressions, and installed-distribution comparison checks.

Comparison mode ignores configured baselines and is mutually exclusive with all
three baseline CLI flags. Ordinary scans, rule output, JSON/baseline/fingerprint
schemas, exit codes, and public exports are unchanged. Git is required only for
comparison; no Python runtime dependency is added. Stage file moves for rename
detection; unstaged moves to untracked names are additions. Symlink inputs are
rejected, nested repositories/submodules are not traversed by comparison, and
identical findings only detect net count increases—not individual replacements.
No additional rules, Spark-version targeting, or production accuracy claims.

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
