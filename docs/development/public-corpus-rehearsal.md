# Apache Spark examples: agent-labeled rehearsal

**2026-10-19 — workflow rehearsal, not independent or production validation.**
One agent reviewed public framework examples before viewing scanner output.
That agent also developed Torchlight; there were **zero independent human
reviewers**. Agent decisions are proposals, not ground truth. No production
accuracy, tool comparison, or 1.0 quality gate follows from these numbers.

## Frozen scope and permissions

- Project: Apache Spark, tag `v3.5.1`, exact commit
  `fd86f85e181fc2dc0f50a096855acf83a6cc5d9c`.
- Source: the complete recursive
  [`examples/src/main/python` subtree](https://github.com/apache/spark/tree/fd86f85e181fc2dc0f50a096855acf83a6cc5d9c/examples/src/main/python),
  retrieved 2026-10-19. The preliminary 142-file estimate missed nested examples;
  the frozen set has **147 `.py` files, 9,447 physical source lines** including
  blanks, comments, and four license-only package initializers. No notebooks.
- Breakdown: 12 top-level, 70 ML, 46 MLlib, 11 SQL/structured-streaming,
  and eight classic-streaming files. No selection based on scanner findings.
- [Pinned source archive](https://codeload.github.com/apache/spark/tar.gz/fd86f85e181fc2dc0f50a096855acf83a6cc5d9c)
  SHA-256: `dd1fcdc17dea45e57620572b8e05a4d559df9df198f175ba994d6e7df0d215e8`.
- Copyright The Apache Software Foundation, under
  [Apache-2.0](https://github.com/apache/spark/blob/fd86f85e181fc2dc0f50a096855acf83a6cc5d9c/LICENSE).
  The upstream LICENSE, NOTICE, and original headers were retained locally.
  Only aggregates are published here: no Spark source, snippets, paths from the
  local machine, per-file labels, or raw findings are redistributed. No endorsement
  by Apache Spark or the ASF is implied.

## Audit and execution

The source archive and all pilot artifacts stayed outside this repository.
The existing `scripts.validate_corpus snapshot` command froze the full source
manifest **before** scanner evaluation. All 147 files were then read, including
the complete code and context rather than just matching lines. Repeated license
headers and blank lines were omitted only from the local reading view; original
source bytes and physical coordinates were unchanged.

A separate Python AST inventory cross-checked candidate call locations without
running Torchlight or executing/importing any example. It found 35 candidate
sites: 30 `collect`, one `toPandas`, three `withColumn`, and one `repartition`.
The single agent's judgments were frozen before the first scan:

- 26 collections were RDD/MLlib calls or explicit DataFrame-to-RDD conversions,
  outside TL001's DataFrame scope. They are not certified memory-safe.
- Four ML collections used tiny literal test inputs and row-preserving predictions;
  the agent judged memory warnings unhelpful in those demonstrations.
- One Arrow round-trip used an explicitly generated 100-by-3 numeric array;
  the agent likewise judged it an intentional small conversion.
- Three one-off column projections were not loop-carried; the single partition
  transformation did not feed a terminal write. No target TL002/TL005 sites occurred.

The resulting 35 judgments were all `do-not-surface`. Files without candidates
were still fully audited and retained. Labels record `labeler: agent`,
`reviewer_count: 1`, and a complete `reviewed_files` list, with no invented human
agreement. The labels hash below was recorded before scanning and remained unchanged.

The runner at commit `dbdbfca` then evaluated these bytes with built-in rules only:
no implicit project configuration, baseline, plugins, session assumptions, source
normalization, dependency installs, or sample execution. This branch's engine is
byte-identical to v0.7.0; **no detector was tuned against this rehearsal**.
The [local workflow](../../benchmarks/local-validation.md) documents the exact
`snapshot` and `evaluate` command forms; only private paths and permission text vary.
The primary run used CPython 3.14.8 on macOS arm64. A CPython 3.12.15 repeat matched
all source/label/tool/runner hashes and all per-rule counts and fractions.

## Outcome and interpretation

One TL001 warning was emitted, on the small Arrow conversion. Under the frozen
agent usefulness judgment it is an **agent-judged false positive**, not proof of
an inference bug: the rule does not currently propagate this constructor's size.
There were no scan errors, unresolved judgments, or unreviewed emitted sites.

**There were no agent-labeled positive sites. Recall is therefore not estimable
for any rule.** The single-warning TL001 precision fraction below is only `0 / 1`
against this agent's decisions, not a population or production estimate. Other
rules have zero precision denominators too. Zero warnings on the many RDD/ML
examples do not validate unsupported inference or prove absence of risk. No
generic accuracy, true-negative count, confidence interval, or human agreement
is claimed. This is one framework/version, Python-only, with deliberately small
examples; it does not satisfy the multi-project independent benchmark protocol.

### Exact aggregate summary

```json
{
  "schema_version": 1,
  "status": "pilot counts only; not a production accuracy claim",
  "manifest_sha256": "ee1749844b109fe8b48dcbb38b9621ef9412030bcb3c9734786e77749e3e9325",
  "labels_sha256": "5493a6e28fc148b4e695c4506297b3207bb1c8d856a358a81c254f6f758bb2f4",
  "tool_source_sha256": "0dab5bd2807271fc158b7b06ab2db574d14c991ee78bb24de44f9e1677293bf3",
  "runner_sha256": "a367d4d3c7953f3be289998a1807509fda2f67f48bb40df8f3fc3bfa1688793f",
  "scanner_python": "3.14.8",
  "platform": "macOS-27.0.1-arm64-arm-64bit-Mach-O",
  "reviewer_count": 1,
  "labeler": "agent",
  "files": 147,
  "formats": {
    "python": 147
  },
  "source_lines_including_blank_comments": 9447,
  "scan_errors": 0,
  "rules": {
    "TL001": {
      "tp": 0,
      "fp": 1,
      "fn": 0,
      "uncertain_sites": 0,
      "unreviewed_emissions": 0,
      "precision": 0.0,
      "recall": null,
      "fp_per_kloc": 0.10585371017254155,
      "initial_agreement": null
    },
    "TL002": {
      "tp": 0,
      "fp": 0,
      "fn": 0,
      "uncertain_sites": 0,
      "unreviewed_emissions": 0,
      "precision": null,
      "recall": null,
      "fp_per_kloc": 0.0,
      "initial_agreement": null
    },
    "TL003": {
      "tp": 0,
      "fp": 0,
      "fn": 0,
      "uncertain_sites": 0,
      "unreviewed_emissions": 0,
      "precision": null,
      "recall": null,
      "fp_per_kloc": 0.0,
      "initial_agreement": null
    },
    "TL004": {
      "tp": 0,
      "fp": 0,
      "fn": 0,
      "uncertain_sites": 0,
      "unreviewed_emissions": 0,
      "precision": null,
      "recall": null,
      "fp_per_kloc": 0.0,
      "initial_agreement": null
    },
    "TL005": {
      "tp": 0,
      "fp": 0,
      "fn": 0,
      "uncertain_sites": 0,
      "unreviewed_emissions": 0,
      "precision": null,
      "recall": null,
      "fp_per_kloc": 0.0,
      "initial_agreement": null
    }
  },
  "limits": [
    "agent labels are not independent human validation; agreement is withheld",
    "counts without two independent human reviewers are provisional",
    "opaque-cell/receiver coverage and confidence intervals not measured",
    "inline suppressions honored; no project config, baseline, plugins, or session assumptions",
    "null metrics mean zero denominator or incomplete/uncertain evaluation",
    "review all aggregates before publication"
  ]
}
```

## Reproduction boundary and follow-up

The pinned source and runner make a fresh scan reproducible. The aggregate-only
publication intentionally omits the local label ledger and raw findings, so the
usefulness classifications cannot be independently recomputed from this report
alone; a labels hash is not a substitute for labels or review. A new reviewer
should audit the complete frozen source afresh, not copy judgments from tool output.
Keep the public example source and derived artifacts outside the checkout, and
follow the upstream license if choosing to redistribute anything separately.

Next useful evidence is independent human review of permissioned, diverse
production-like projects, with actual positive sites, held-out project splits,
coverage accounting, uncertainty intervals, and realistic time/memory measurement.
The [full protocol](../../benchmarks/real-world-protocol.md) remains open.
