# Torchlight documentation

Torchlight is a local PySpark source reviewer, not an experiment tracker, runtime
profiler, cost estimator, or proof of safety. It never imports Spark or executes
the files it scans. Its core has no third-party runtime dependencies.

## Start here

- [Getting started](getting-started.md): installation and a first finding.
- [Configuration](configuration.md): shared project policy and exact precedence.
- [CI and pre-commit](integrations.md): use the same policy locally and in CI.
- [Rule catalog](rules/README.md): examples, required evidence, and review guidance.
- [Analysis boundaries and notebook behavior](analysis.md): what the scanner can
  and cannot establish.

## Project and validation

- [Python compatibility assessment](development/python-compatibility.md).
- [Real-world benchmark protocol](../benchmarks/real-world-protocol.md).
- [Synthetic regression corpus](../benchmarks/README.md).
- [Contributing](../CONTRIBUTING.md) and [security](../SECURITY.md).

Configuration in these docs is **unreleased**: use a checkout containing this
change, not the v0.2.0 PyPI release. Stable Python APIs, SARIF, baselines,
Spark-version targeting, and editor integrations remain future work. There is no
hosted documentation site yet; these Markdown guides are the initial information
architecture.
