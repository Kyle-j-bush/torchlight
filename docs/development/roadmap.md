# Follow-up roadmap

The October 2026 research report is a direction, not a claim that its full
20-week program is shipped. v0.3.0 completed the CI adoption foundation; v0.4.0
adds an internal detector boundary, one narrowly evidenced rule, and an initial
public Python API without weakening conservative Spark identity analysis.

## Shipped in v0.3.0

- Shared `pyproject.toml` policy, deterministic discovery, excludes, and CLI overrides.
- Versioned structural finding fingerprints and duplicate-aware, portable baselines.
- Explicit atomic baseline capture/update; scan errors cannot be grandfathered.
- SARIF 2.1.0, pinned Code Scanning example, and OASIS schema validation.
- User/rule guides, Python compatibility assessment, and real-world benchmark protocol.

## Shipped in v0.4.0

- Immutable semantic facts and a separate internal detector registry for TL001–TL004.
- Original-rule JSON/text/fingerprint golden tests captured before the refactor.
- TL004 for proven literal `repartition(1)` provenance feeding terminal writes,
  with six new synthetic cases and intentional-use, notebook, and invalidation tests.
- Public immutable Config/Scanner/ScanReport and finding types, explicit TOML
  loading, read-only baseline filtering, format rendering, and CLI/API parity.
- Contributor/API docs and installed wheel/sdist API verification. Detector
  internals remain private and Python interfaces remain pre-1.0.

## Next: analysis and review contracts

1. Evaluate Spark-version targeting against documented API differences before
   adding version-dependent advice. Vendor-specific behavior needs explicit limits.
2. Exercise the internal detector boundary on further independently justified
   rules before considering a public plugin API. Preserve CLI/JSON/fingerprint
   compatibility and avoid exposing analyzer state.
3. Evaluate severity and confidence policy without presenting unmeasured precision
   as fact. Keep existing warnings and no semantics-changing automatic fixes.
4. Add Git-base comparison only with explicit rename, shallow-clone, deleted-file,
   notebook, and error behavior. Baselines alone are not diff analysis.

## Notebook and integration work

- Databricks source-format notebooks with tested cell/source mapping and opaque boundaries.
- Better notebook cell navigation where supported; retain document-order semantics.
- Editor protocol/LSP research after a stable library or subprocess interface exists.
- GitLab/reviewdog adapters; keep integrations separate from the dependency-free core.

## Validation before breadth or 1.0

- Obtain permissioned real-world source and independent labels from Spark reviewers
  under the [benchmark protocol](../../benchmarks/real-world-protocol.md). No such
  results are published yet. Report per-rule precision, recall, reviewer agreement,
  false positives/KLOC, notebook coverage, and Spark/Python versions.
- Add metamorphic cases, parser fuzzing, and optional heavyweight Spark semantic
  checks without importing Spark in production scans.
- Measure scan time and memory on realistic repositories before adding caching
  or concurrency. Avoid noisy blocking microbenchmarks on shared CI runners.
- Revisit older scanner runtimes or standalone packaging based on user demand;
  the [compatibility assessment](python-compatibility.md) currently retains 3.12+.
- Consider optional constant-SQL analysis and plugin loading only with clear
  dependency, dialect, security, and compatibility boundaries.

A 1.0 decision should be gated on stable interfaces, reproducible real-world
quality evidence, and dependable CI ergonomics—not a target rule count. The
synthetic corpus is regression coverage, not production accuracy. No external
review, benchmark, performance, or broad-roadmap completion is implied by v0.4.0.
