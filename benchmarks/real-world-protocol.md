# Real-world validation protocol — draft 1

**Status:** protocol only, October 18, 2026. No real-world corpus has been collected
or independently labeled, and no production accuracy figures are claimed. The
existing [30 synthetic cases](README.md) remain regression coverage, not benchmark
evidence. Do not execute any submitted source or notebook cells.

## Research questions

For each of TL001, TL002, and TL003, measure whether the warning is worth a Spark
reviewer's attention, how often relevant sites are missed, and the cost of
scanning. Report Python and notebook results separately. Do not rank tools or
claim runtime savings from source-pattern counts.

## 1. Permission and reproducible snapshots

- Obtain explicit permission or verify the license permits the intended analysis,
  storage, and publication. Record attribution and restrictions. Publicly visible
  code is not automatically permission to redistribute it.
- Use exact repository commits or content-addressed donated snapshots. Record
  retrieval date, repository ID, relative path, SHA-256, license/permission record,
  declared Python/Spark versions, vendor/runtime, file kind, and any missing
  environment context. Use `unknown`, not guessed version values.
- Screen for secrets, private data, notebook outputs, and personal information
  before storage or publication. Prefer source-only extracts with permission.
  Do not publish proprietary snippets, reviewer identities, or paths without
  consent. Report private-only results separately from reproducible public data.
- Freeze an inclusion/exclusion manifest **before** inspecting scanner results.
  Include full eligible Python/notebook files with the context needed to resolve
  Spark origins. Record all exclusions and parse failures; never silently drop
  hard cases or only retain files where the tool emits a warning.

## 2. Sampling and evaluation split

Start with a pilot across at least three unrelated, permissioned Spark projects,
including notebooks and `.py` jobs. A small pilot is feasibility evidence, not a
generalization claim. Expand across Spark versions, project sizes, vendors, and
intentional/non-Spark uses before establishing release quality floors.

Separate development and evaluation sets **by project**, not random lines or
cells. Keep shared/copied examples in the same split. Record strata, sampling
method, sample sizes, and any enrichment for rare rule patterns. Freeze the
evaluation manifest before tuning rules; do not tune against held-out labels.
Never combine a deliberately enriched sample with a representative sample into
an unqualified overall prevalence or false-positives-per-KLOC claim.

## 3. Independent source audit

Two Spark reviewers independently audit the complete sampled files **without
seeing Torchlight output**. Enumerate candidate sites for all three rules,
including intentional uses, non-Spark lookalikes, and sites the scanner cannot
currently resolve. This independent inventory is needed for recall; labeling only
emitted warnings can measure precision but cannot establish recall.

For each site, record:

| Field | Meaning |
| --- | --- |
| Snapshot, path, rule ID | Exact source and rule under review. |
| Line, end line, code-cell number | One-based coordinates; `null` cell for Python. Notebook cell numbers count code cells in document order. |
| Receiver/pattern evidence | Why it is Spark or not Spark; bound, partition, or loop evidence as relevant. |
| Pattern present | `yes`, `no`, or `uncertain`; distinct from usefulness. |
| Review decision | `surface`, `do-not-surface`, or `uncertain`, with rationale. |
| Context and uncertainty | Known intent, unavailable size information, opaque cells, helper-returned DataFrames, or vendor-specific behavior. |
| Reviewer labels and adjudication | Preserve both original judgments and final consensus, not just an overwritten result. |

"Surface" means the reviewer believes the **qualified, evidence-based warning**
deserves review at that site. It does not mean a job will fail. An intentional
small export is not automatically a false positive: the reviewers must decide
whether surfacing it is useful in context. Do not label ordinary `.distinct()` or
an unrelated `.collect()` as an expected warning.

Resolve disagreements through a documented third-reviewer adjudication. Report
initial agreement and counts of unresolved/uncertain sites. Keep unresolved sites
out of definitive metric denominators and publish their rate and sensitivity
bounds so uncertainty cannot inflate the result.

## 4. Freeze the tool and run offline

Record tool commit/distribution hash, Python version, OS/architecture, exact
command, explicit config contents/hash, session assumptions, corpus manifest hash,
and timing method. Disable project discovery with `--no-config` unless the benchmark
specifically evaluates a frozen policy. The primary run should use no preexisting
suppressions or ignore lists that hide audited sites; preserve raw files and
record any permissioned evaluation-only normalization separately.

```sh
torchlight --no-config --format json corpus/ > raw-findings.json
```

Status 1 means findings, not a failed benchmark runner. Persist raw output,
stderr, and status; status 2, parse errors, skipped opaque cells, and unresolved
Spark identities must be accounted for, not treated as complete coverage.
Document-order notebook analysis must not be compared to a fabricated kernel
execution trace. All code remains inert; do not install or import target projects.

## 5. Match and compute per-rule metrics

Match emitted and independently audited sites on snapshot, relative path, rule
ID, code-cell number, and the reviewed call's source span. TL002 is matched at
the terminal write, not `coalesce(1)`. Manually adjudicate ambiguous multi-call
lines. Match one diagnostic to one site; duplicates are excess diagnostics, not
extra true positives. Current coordinates are snapshot-specific and are **not**
a proposed persistent finding fingerprint.

Against final `surface` / `do-not-surface` judgments:

- **TP:** a matched diagnostic at a `surface` site.
- **FP:** a diagnostic judged `do-not-surface`, including an audited emitted site
  missing from the original candidate inventory after blind re-review.
- **FN:** a `surface` site with no matched diagnostic.
- **Precision:** `TP / (TP + FP)`; **recall:** `TP / (TP + FN)`.
- **Reviewer burden:** `FP / scanned source KLOC`; state how blank/comment lines
  and notebook code-cell lines are counted. Do not count notebook JSON or outputs.
- **Actionability:** fraction of reviewed emitted warnings agreed worth surfacing,
  plus dismissal reasons and pattern-presence agreement as separate measures.

Publish numerator/denominator counts, per-project/per-rule breakdowns, uncertainty
intervals, and sample selection caveats. Use `not estimable` for zero denominators.
Do not report generic "accuracy" over arbitrary negative source lines. A formal
FPR needs a predefined negative candidate-site population; FP/KLOC is usually
more interpretable for this product. Report missed sites involving unsupported
flow separately **and** in overall recall, rather than hiding them from results.

## 6. Performance and publication

Measure scan-only wall time, source lines, files/cells, and peak resident memory
on a fixed environment. Record at least five repetitions, warm/cold-cache policy,
median and range; include failures. Separate tool setup from scan time. Do not
make noisy hosted-runner microbenchmarks blocking during this pilot.

Publish a versioned results document with the manifest (or justified redactions),
labeling guide, raw labels where permitted, adjudication log, raw scanner reports,
commands, environment, and a limitations section. Review source-containing
artifacts before publishing. No telemetry or source upload should be added to the
scanner to collect these measurements.

## Pilot exit and next work

The first pilot is complete only when permission records, frozen manifests,
independent labels, adjudication, reproducible runs, and per-rule counts exist.
Use that pilot to set sample-size goals and explicit release precision/burden
thresholds **before** the next held-out evaluation. Do not declare 98% precision,
beat a competitor, or establish a 1.0 quality gate from this protocol alone.
Dataset collection and reviewer recruitment remain follow-up work; no external
reviewers or datasets are represented as secured by this PR.
