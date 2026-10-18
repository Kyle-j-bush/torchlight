# Torchlight documentation

Torchlight is a local PySpark source reviewer, not an experiment tracker, runtime
profiler, cost estimator, or proof of safety. It never imports Spark or executes
the files it scans. Its core has no third-party runtime dependencies.

## Start here

- [Getting started](getting-started.md): installation and a first finding.
- [Configuration](configuration.md): shared project policy and exact precedence.
- [CI and pre-commit](integrations.md): use the same policy locally and in CI.
- [Baselines](baselines.md): adopt with reviewed existing debt, fail only on new findings.
- [Report identity and SARIF](reporting.md): stable fingerprints and Code Scanning.
- [Rule catalog](rules/README.md): examples, required evidence, and review guidance.
- [Python API](python-api.md): immutable policy/reports and the shared scanner.
- [Analysis boundaries and notebook behavior](analysis.md): what the scanner can
  and cannot establish.

## Project and validation

- [Python compatibility assessment](development/python-compatibility.md).
- [Follow-up roadmap](development/roadmap.md).
- [Internal detector contributor guide](development/detectors.md).
- [Real-world benchmark protocol](../benchmarks/real-world-protocol.md).
- [Synthetic regression corpus](../benchmarks/README.md).
- [Contributing](../CONTRIBUTING.md) and [security](../SECURITY.md).

These guides describe v0.4.0, including the initial pre-1.0 Python API. Spark-version
targeting, Git-base comparison, and editor integrations remain future work. There
is no hosted documentation site yet; these Markdown guides are the initial information
architecture. The real-world protocol is not a claim of measured accuracy.
