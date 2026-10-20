# Torchlight documentation

Torchlight is a local PySpark source reviewer, not an experiment tracker, runtime
profiler, cost estimator, or proof of safety. It never imports Spark or executes
the files it scans. Its core has no third-party runtime dependencies.

## Start here

- [Getting started](getting-started.md): installation and a first finding.
- [Configuration](configuration.md): shared project policy and exact precedence.
- [CI and pre-commit](integrations.md): use the same policy locally and in CI.
- [Baselines](baselines.md): adopt with reviewed existing debt, fail only on new findings.
- [Git comparison](git-comparison.md): review findings introduced since a PR's merge base.
- [Report identity and SARIF](reporting.md): stable fingerprints and Code Scanning.
- [Rule catalog](rules/README.md): examples, required evidence, and review guidance.
- [Python API](python-api.md): immutable policy/reports and the shared scanner.
- [Trusted detector plugins](plugins.md): explicit in-process registration, API version 1.
- [Databricks source notebooks](databricks.md): cells, magic boundaries, and physical source mapping.
- [Analysis boundaries and notebook behavior](analysis.md): what the scanner can
  and cannot establish.

## Project and validation

- [Python compatibility assessment](development/python-compatibility.md).
- [Spark-version assessment](development/spark-versions.md): upstream API/Connect differences, not runtime certification.
- [Follow-up roadmap](development/roadmap.md).
- [Internal detector contributor guide](development/detectors.md).
- [RiskMap implementation contract](development/riskmap.md): planned evidence maps, compatibility gates, and the dependent PR stack; no graph formats are available yet.
- [Real-world benchmark protocol](../benchmarks/real-world-protocol.md).
- [Local validation pilot](../benchmarks/local-validation.md): frozen corpus, explicit labeler provenance, and independent-review requirements.
- [Apache Spark example rehearsal](development/public-corpus-rehearsal.md): full 147-file agent audit and aggregate-only results, not production validation.
- [Synthetic scan timing](../benchmarks/performance.md): reproducible workload and non-gating release artifacts.
- [Synthetic regression corpus](../benchmarks/README.md).
- [Contributing](../CONTRIBUTING.md) and [security](../SECURITY.md).

These guides describe v0.8.0, including rationale-backed regressions, labeler
provenance, a public-example rehearsal, explicit plugins, validation tooling,
five rules, Databricks Python exports, Git comparison, and the pre-1.0 Python API.
Spark-version targeting flags and
editor integrations remain future work. There
is no hosted documentation site yet; these Markdown guides are the initial information
architecture. The real-world protocol is not a claim of measured accuracy.
