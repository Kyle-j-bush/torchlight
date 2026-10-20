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

## RiskMap tracked-state observation (2026-10-20)

Slice 03 reran the pre-RiskMap commit above from a temporary archive, then the
tracked-state analyzer, using the same CPython 3.14.8 interpreter, platform,
300-file/eight-block corpus, and harness. Each run discarded one warm-up and
verified 7,200 findings per scan. Graph capture was disabled; no graph records
were allocated. No other Torchlight checks ran concurrently, but unrelated
processes were using CPU on this uncontrolled developer machine.

- Baseline tool digest: `0dab5bd2807271fc158b7b06ab2db574d14c991ee78bb24de44f9e1677293bf3`.
- Tracked-state tool digest: `6bb0ad19ebc896100531612648efbeb77530aeef71fea60d6e1f9b0499deee4f`.
- Shared corpus digest: `cbba51e93175bcec0cec8812ad481da39704c3794e1df96a3401f5277c49f3be`.

Runs are listed in execution order. The first four used the default command;
after a noisy tracked run, the final three used `--samples 15`, bracketing the
tracked run with baseline runs instead of treating the old timing as a threshold.
All samples, including the outliers, are retained below.

| Run | Samples | Median seconds | Range seconds |
| --- | --- | --- | --- |
| Baseline A | 5 | 0.224350 | 0.217532–0.239840 |
| Tracked A | 5 | 0.224472 | 0.219561–0.250373 |
| Baseline B | 5 | 0.219683 | 0.212971–0.222604 |
| Tracked B | 5 | 0.329877 | 0.240746–0.566033 |
| Baseline C | 15 | 0.228988 | 0.219727–0.293650 |
| Tracked C | 15 | 0.232387 | 0.224488–0.240637 |
| Baseline D | 15 | 0.235905 | 0.219402–0.345240 |

```text
Baseline A: 0.239840, 0.225728, 0.221554, 0.224350, 0.217532
Tracked A:  0.232742, 0.224472, 0.219781, 0.219561, 0.250373
Baseline B: 0.215720, 0.222604, 0.219683, 0.219718, 0.212971
Tracked B:  0.329877, 0.566033, 0.527884, 0.328338, 0.240746
Baseline C: 0.237675, 0.224617, 0.220159, 0.219727, 0.221327, 0.222655, 0.221012, 0.242569, 0.255187, 0.293650, 0.278369, 0.237628, 0.229778, 0.220873, 0.228988
Tracked C:  0.233630, 0.228685, 0.227500, 0.224488, 0.232387, 0.240637, 0.233026, 0.230224, 0.233777, 0.228580, 0.230358, 0.225968, 0.233334, 0.238243, 0.233319
Baseline D: 0.219402, 0.234259, 0.231186, 0.227898, 0.222403, 0.238280, 0.242488, 0.246075, 0.262196, 0.231457, 0.242945, 0.231706, 0.235905, 0.266085, 0.345240
```

The final tracked median falls between the bracketing baseline medians, about
1.5% above the first and 1.5% below the second. The overlapping ranges and
transient spikes in both implementations do not establish a sustained default
scan regression, nor do they isolate the wrapper's allocation cost. Repeat on
quiet hardware before making performance claims. This remains warm-cache,
synthetic scan timing, not a CI gate; rendering, cold caches, peak memory,
graph-enabled overhead, and production performance were not measured.
