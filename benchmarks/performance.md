# Reproducible scan timing

```sh
python -m scripts.benchmark_scan --files 100 --cells 8 --samples 5 > scan-timing.md
```

The dependency-free development script generates a temporary, deterministic
corpus: 100 ordinary Python files, 100 Jupyter notebooks, and 100 Databricks
Python exports. Each file has setup plus eight repeated workload blocks covering
TL001/TL004/TL005. Unknown real-world size/shape is not simulated or inferred.
Source remains inert, and generated files are removed by the temporary-directory
context. No user corpus, Git history, project config, baseline, or plugins load.

Generation, content hashing, and report rendering are excluded from the measured
`Scanner.scan` calls; discovery, reads, parsing, inference, and findings are included.
One warm-up is discarded, then five samples are reported with median/range,
Python/platform, tool-source digest, and corpus digest. Repeated scans use warm
filesystem caches; this is not cold-start timing. Correct finding counts are
checked on every repetition. No peak-memory figure is claimed.

Release verification runs the harness and retains its Markdown as a separate
GitHub Actions artifact, not a PyPI distribution. There are no elapsed-time
thresholds: correctness checks may fail, shared-runner timing variance may not.
The normal tests exercise only a tiny workload and verify reproducibility.

Results from different hardware/interpreters/workloads are not directly comparable.
Record an exact release/commit alongside the digests when publishing measurements.
This harness does not establish production throughput, memory ceilings, speed
against competitors, Spark runtime savings, or precision/recall. Measure realistic
permissioned repositories before proposing caching or concurrency.

## Initial local observation (2026-10-18)

On CPython 3.14.8, macOS 27.0.1 arm64, using the default 300-file / eight-block
workload above and the core at commit `14a8b7c`:

- Tool-source digest: `95b067e403f583e2714cdc523626529b5799b829d5ad43134ee79a11ff441ceb`.
- Corpus digest: `cbba51e93175bcec0cec8812ad481da39704c3794e1df96a3401f5277c49f3be`.
- Five wall-second samples: 0.208892, 0.209985, 0.209136, 0.211084, 0.209621.
- Median 0.209621 seconds, range 0.208892–0.211084; 7,200 findings each scan.

This was an uncontrolled developer machine (the test suite also ran concurrently),
not a production benchmark or a release performance floor. No cold-cache or
peak-memory measurements were taken.

## Pre-RiskMap local baseline (2026-10-20)

Before any provenance changes, the same default command above was run against
commit `ee47c973b9ddd2d5565dc6c9afeb093673344875` on CPython 3.14.8,
macOS 27.0.1 arm64. No other Torchlight checks were running concurrently.

- Tool-source digest: `0dab5bd2807271fc158b7b06ab2db574d14c991ee78bb24de44f9e1677293bf3`.
- Corpus digest: `cbba51e93175bcec0cec8812ad481da39704c3794e1df96a3401f5277c49f3be`.
- Five wall-second samples: 0.195931, 0.196633, 0.203613, 0.198272, 0.197470.
- Median 0.197470 seconds, range 0.195931–0.203613; 7,200 findings each scan.

This is a warm-cache observation on an uncontrolled developer machine, not a
speed threshold or a comparison with the earlier observation. Later RiskMap
measurements must rerun the baseline under matching conditions rather than use
these elapsed times as a CI gate. Rendering, cold-cache behavior, and peak memory
were not measured; no production performance or accuracy claim follows.
