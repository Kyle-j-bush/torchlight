# Local permissioned-corpus pilot

**Tooling only (v0.7.0). No donated corpus or reviewer labels have been received,
and no real-world results are claimed.** This development script assists the
[full protocol](real-world-protocol.md); it does not complete it by itself.
Scripts are available in a source checkout/sdist, not as new installed CLI commands.

## 1. Permission and snapshot — before seeing scanner output

Keep the corpus and all artifacts **outside the Torchlight checkout**, in private
local storage. Confirm rights to analysis and local artifact storage; that does
not automatically grant rights to publish anything. Never install/import the
target project or execute notebook cells.

```sh
python -m scripts.validate_corpus snapshot /private/pilot/corpus \
  --permission "I have permission to analyze and store this corpus; approval reference XYZ" \
  --output /private/pilot/snapshot
```

The output directory must not exist, must have an existing parent, and cannot be
inside this repo or the corpus. POSIX modes request owner-only directories/files;
check ACLs, backups, synchronization, and Windows permissions yourself. Artifacts
are not encrypted. No network calls, telemetry, uploads, Git operations, or code
execution are performed. Do not put your private source in this repository.

`manifest.json` contains permission text, relative paths, byte hashes/sizes, source
line counts, file kinds, discovery exclusions, and initially unknown deployment
versions. `labels.json` is a **blank** review template bound to the manifest hash;
snapshot does not run the scanner or suggest sites. Keep the original corpus
unchanged: evaluation checks the complete eligible file list and every byte hash.
Use one snapshot per project/stratum and keep development/evaluation projects apart.
Document licensed attribution, inclusion criteria, selection bias, missing runtime
context, and declared versions separately; do not guess them from source.

Discovery uses the ordinary ignored-directory list, recorded in the manifest.
Directory symlinks are not followed; source-file symlinks are rejected. All other
eligible `.py`/`.ipynb` files are included, even if they later fail to parse.
No project configuration, excludes, baselines, plugins, or session assumptions
load. Existing inline suppressions are honored: for a primary unsuppressed study,
prepare a separately permissioned, documented source-only extract **before freezing**.
Do not silently edit away inconvenient sites or errors after seeing results.

## 2. Independent audit

Audit **every complete file**, without looking at Torchlight output. Independently
enumerate TL001–TL005 candidate sites, including intentional uses, unsupported
receiver flow, and unrelated lookalikes. Labeling just emitted warnings cannot
establish recall. For TL005, label the outer list/tuple call, not bare streaming.
For TL002/TL004, label the terminal write.

Fill `reviewed_files` with every manifest path only after the audit is complete,
and set `blind_review: true` only if it is true. The program checks the attestation
and coverage list; it cannot verify that a human audit occurred.

Each entry in `sites` must look like:

```json
{
  "path": "jobs/export.py",
  "rule_id": "TL001",
  "line": 12,
  "column": 5,
  "cell": null,
  "a": "surface",
  "b": null,
  "decision": "surface",
  "rationale": "Qualified full-result memory warning deserves review here.",
  "adjudication": ""
}
```

Coordinates are one-based **exact call-start** character columns, not byte offsets
or approximate spans. Ordinary Python uses null cell and physical coordinates.
Jupyter uses code-cell number and cell-relative coordinates. Databricks uses all
exported cell numbers and physical `.py` coordinates including magic prefixes.
Same-line calls need distinct columns. There is no fuzzy/span matching.

Allowed judgments: `surface`, `do-not-surface`, `uncertain`. `rationale` is required.
With `reviewer_count: 1`, `b` must be null and `decision` must equal `a`; all numbers
are provisional single-reviewer pilot counts, **not reviewer agreement**.

For the protocol's two independent reviewers, set `reviewer_count: 2` and preserve
both original decisions in `a` and `b`. Merge their independent inventories by
exact site; both reviewers must judge the union. Do not overwrite disagreements
with consensus. A changed/disagreed final decision needs third-reviewer rationale
in `adjudication`, or leave `decision: "uncertain"`. Pattern-presence labels and
independent inventories/adjudication records should be retained separately; the
script reports only initial **site-decision** agreement, not full inter-rater quality.

## 3. Evaluate offline and review artifacts

```sh
python -m scripts.validate_corpus evaluate /private/pilot/corpus \
  --manifest /private/pilot/snapshot/manifest.json \
  --labels /private/pilot/snapshot/labels.json \
  --output /private/pilot/result
```

The captured bytes are scanned in memory without executing source. Two local
files are written, never replacing existing results:

- `raw-findings.json`: **private** paths, snippets, findings and error details.
  Do not upload or commit this file.
- `summary.json`: counts, hashes, environment and limitations, with no source
  snippets, paths, permission statement, reviewer identities, or error messages.
  Review even these aggregates before deciding whether publication is permitted.
  Hashes/counts can still identify a small private corpus. Nothing publishes them.

Per rule the summary reports TP/FP/FN, uncertain sites, unreviewed emissions,
precision/recall, FP per source KLOC, and (only with two reviewers) original
agreement numerator/denominator/fraction. One diagnostic matches at most one site;
additional diagnostics at a reviewed surface site count as excess false positives.
An emitted site absent from the independent inventory is **unreviewed**, not
automatically a false positive. Arrange blind re-review before final classification.

`null` metrics mean a zero denominator, scan error, or unresolved/unreviewed sites;
those cases are not silently counted as correct. Definitive counts remain visible.
Source lines include blanks/comments and physical Databricks export lines; Jupyter
counts only code-cell source lines, never JSON, Markdown, or saved outputs.
Exit status is 2 for invalid inputs or scan errors, 0 when a count report is written;
0 does **not** certify complete metrics, accuracy, or successful notebook execution.

This small runner does not measure opaque-cell coverage, unresolved-identity
coverage, pattern-presence agreement, statistical confidence intervals, or memory.
Preserve and report those audits separately before making any generalization.
Run each format/project/sampling stratum separately rather than merging an enriched
sample into a population claim. Use the [timing harness](performance.md) for synthetic
scan timings; realistic performance measurements still require your frozen corpus.
