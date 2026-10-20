# RiskMap implementation contract

Status: internal foundations only, not a shipped feature. Slices 01–02 add
preservation tests, stacked-review CI, and an immutable graph model with a bounded
collector. Scanners do not import or allocate the graph model yet. Analyzer
instrumentation, public graph APIs, and HTML/graph-JSON formats are still planned;
they are not available in v0.8.0. No release version changes until release readiness.

## Product boundary

RiskMap will explain why an existing Torchlight finding was reported and where
analysis stopped. It is a **static evidence map, not a Catalyst execution plan**.
Source stays inert and local; the core keeps zero third-party runtime dependencies.

The first release includes finding-centered paths for TL001–TL005, recognized
fact changes, analysis boundaries, Python/Jupyter/Databricks locations, conservative
Git-change highlighting, graph JSON, and self-contained accessible HTML/SVG.

It does not add rules, execution, cost estimates, event-log ingestion, cross-file
or interprocedural analysis, complete multi-input lineage, an all-operations
explorer, graph-layout dependencies, JavaScript interaction, plugin discovery,
or a plugin graph API. Native links and expandable details are sufficient initially.

## Compatibility requirements

- Graph capture is observational: it cannot affect inference or detector results.
- Keep `Value`, `CallFacts`, `Diagnostic`, and plugin API version 1 unchanged.
  Detectors receive existing semantic values, never private tracked wrappers.
- Preserve findings, evidence text, Unicode coordinates, structural keys,
  fingerprints, ordering, suppression and selection behavior, duplicate counts,
  baselines, Git subtraction, and error/exit-code semantics.
- Existing `text`, `json`, `github`, and `sarif` output stays unchanged apart from
  already-variable installation/root metadata. `ScanReport.to_dict()` keeps schema 1.
- Existing low-level scanners retain `(findings, errors)` returns. They may accept
  an optional private collector; default callers and corpus tools need no changes.
- No graph records are allocated when capture is disabled. Measure any private
  wrapper overhead instead of assuming the default scan is unaffected.
- Never execute source, import Spark, load repository helpers, or add network
  access. Retain existing read-only Git safeguards and explicit trusted plugins.

### Preservation baseline

`tests/test_riskmap_preservation.py` captures the unmodified analyzer at
`ee47c973b9ddd2d5565dc6c9afeb093673344875` before provenance work. Its inert,
agent-authored fixture covers all five rules, bounds and invalidation, aliases,
loop-carried state, iterator materialization, duplicate calls, and negative cases.
Jupyter and Databricks variants carry state across cells.

The golden digests cover full finding dictionaries and all four legacy renders,
plus the semantic facts observed by a non-emitting version-1 plugin. Only the
temporary root URI is normalized and SARIF package-version lookup is pinned for
the output snapshot. Plugin loop tokens are sorted for deterministic serialization.
Existing original-rule goldens remain intact. Do not refresh either baseline to
make an observational refactor pass; investigate any changed output first.
These are regression fixtures, not independent production validation.

The [pre-RiskMap timing observation](../../benchmarks/performance.md#pre-riskmap-local-baseline-2026-10-20)
records the same pre-refactor commit and workload digests.

## Capture architecture

Keep public facts separate from a private `_TrackedValue(value: Value, trace)`.
Capture during existing AST traversal; do not parse `Value.origin`, replay the
program, or build another inference engine. A collector lives for one artifact,
including its notebook cells; base and current snapshots use separate collectors.

Adapt expressions, bindings, attributes, annotations, scope snapshots, merges,
and loop tagging. Semantic decisions operate on the original `Value` facts;
trace equality never determines type identity or branch merges. Equal facts may
still have different provenance. Record those as explicit analyzed alternatives,
not a sequence of operations that supposedly all executed.

Record recognized sources, transforms, constraint changes, actions, writes,
merge alternatives, loop context, and opaque boundaries. TL003 ends at the
repeated transformation; it does not need a fabricated terminal action. A loop
summary does not claim an observed iteration count.

An unknown return remains unknown. For `result = custom(df)`, close the result's
proven path without invalidating an independently known `df` binding. Keep a
separate analysis-boundaries section: pruning to findings alone would hide
identity loss that prevented downstream findings. Notebook invalidation must
emit a boundary even when no downstream finding survives.

Describe only tracked facts: a row bound is not a memory guarantee; clearing
single-partition evidence does not prove multiple partitions. An annotation is
an annotation-backed source, not a traced read. Joins/unions show receiver-path
evidence and disclose untracked inputs rather than imply complete lineage.

### Graph contract and identity

Use immutable records for artifacts, nodes, edges, finding links, comparison
metadata, and incomplete-capture status. Artifacts identify source kind; node
locations may be absent when parsing never established a coordinate. Jupyter
locations remain code-cell-local; Databricks locations remain physical `.py`
coordinates including `# MAGIC` prefixes. Never use raw notebook JSON line numbers.

Node roles are source, transform, constraint, action, sink, merge, loop context,
and opaque. Relationships distinguish receiver flow, alternatives, and control
context. Every displayed edge must have captured support and valid endpoints.

IDs identify occurrences within one report. Keep a separate structural matching
key using existing call identity machinery without changing fingerprint v1.
Deterministic occurrence suffixes distinguish duplicate nodes; fingerprints alone
are not unique finding IDs. Do not promise stable duplicate identity across edits.

Bound collector growth and visibly label incomplete capture. Graph limits cannot
drop scan findings or turn analysis errors into successful scans. A finding whose
trace is unavailable still appears with its ordinary evidence and an explicit gap.

### Internal model (slice 02)

`torchlight/graph.py` is internal, with no top-level public exports or new output
format. It defines frozen artifact, fact, node, edge, pre-policy finding-anchor,
and capture-limit records. `AnalysisGraph` snapshots its sequences as tuples and
checks unique IDs and anchors, valid endpoints/artifacts, and no cross-file edges.
Tests use standard-library dataclass serialization for reproducibility; this is
not the public graph-JSON schema, which is introduced in slice 09.

The file-scoped `_GraphCollector` accepts structural call keys from its eventual
caller. It hashes those keys with node roles instead of retaining raw AST text.
Matching keys omit artifact paths; node IDs include artifact identity and an
occurrence suffix. Coordinates, labels, and facts do not change those IDs.
Document traversal determines occurrence order. Parent references are sorted and
deduplicated, preserving explicit receiver/alternative/control relationships.

The private default budget is 10,000 records per artifact, counting nodes, edges,
and finding anchors together. It is a count limit, not a byte or report-wide memory
ceiling. A node and all incoming edges are accepted or rejected together. Once
truncated, no new records or occurrence counters grow. Existing anchors can be
replaced without growing the budget, matching the analyzer's last-diagnostic-wins
behavior at a rule/location. The collector never owns the actual scan findings.

Snapshots identify truncated artifacts through `CaptureLimit`; `capture_complete`
describes only capture-budget status, not full source coverage or safety. Missing
trace anchors can explicitly hold `None`. Scanner filtering, fallback evidence,
and report-local finding IDs remain slice 07 work. No configuration knob or
graph allocation is added to ordinary scans in this slice.

### Scanner integration and comparison

Resolve finding links after suppressions, rule selection, baseline matching, and
existing Git finding subtraction. Filtered findings must not reappear as graph
warnings. Keep plugin evidence verbatim and anchor it to the analyzed operation;
do not infer plugin-specific edges from arbitrary evidence strings.

Capture recognized safe operations too: a bounded action in the base revision
may have no finding but still be needed to explain a current unbounded action.
Match before pruning the final public graph to finding-centered paths.

Git finding subtraction stays unchanged. A separate graph overlay uses existing
merge-base blobs and rename mapping. Change labels are **matched syntax**,
**new or edited**, **unknown**, and **not compared**. Matched syntax does not
establish semantic equivalence. Duplicate ambiguity, missing base traces, and
base errors must not become confident unchanged labels.

Where operation matching is established, show changed facts such as a prior
`limit(1000)` bound becoming unproven at an unchanged `df.collect()` call.
Record the requested ref, resolved merge base, and that current source comes
from the working tree, not necessarily HEAD. Never reread source while rendering.

## Planned public surface

Add `Scanner.scan(..., include_graph=False)` and an optional keyword-only
`ScanReport.graph` field. Validate the new bool before source I/O. Graph records
are immutable; ASTs, collectors, and tracked values remain private.

Add `report.render("graph-json")` and `report.render("html")` when those slices
are complete. Rendering a graph format without captured graph data must fail
clearly, never silently rescan. Graph JSON has a distinct document type and
schema version; ordinary finding JSON does not gain graph fields.

The planned CLI formats enable capture automatically, keeping stdout as the
artifact destination. Do not add an output writer or new configuration policy.
Handle configuration/baseline errors before scanning as well as partial scans;
no successful-looking empty map may hide errors. Preserve exit codes 0/1/2.

## HTML, privacy, and accessibility

Build the semantic document before its diagram. Every finding, relationship,
fact change, and boundary shown visually has an equivalent ordered/table view.
Use native links and details, visible focus, logical keyboard order, readable
contrast, text labels beyond color, reflow, and no required animation. Decorative
SVG must not create a competing keyboard interface. Target WCAG 2.2 AA, checked
with browser automation plus documented keyboard and screen-reader review;
automated checks alone do not establish conformance.

Treat source, paths, snippets, evidence, and plugin messages as hostile strings.
Escape them for their exact HTML/SVG context. Do not interpolate source into
scripts, CSS, executable markup, or arbitrary links. Use generated fragment IDs,
no JavaScript or remote resources, and a restrictive CSP blocking scripts and
connections. Browser tests must verify inert hostile strings and zero network
requests when opening the artifact as a local file.

Keep existing finding snippets rather than embedding every visited source line
or whole files. Include a confidentiality warning covering paths, snippets,
table names, and evidence. Reports are not automatically public or safe to upload.

## Delivery stack

Every slice includes its own tests and documents any newly usable behavior.
Numbers are dependency order, not one release per PR. All later slices are planned.

| PR | Branch suffix under `riskmap/` | Scope and required evidence |
| --- | --- | --- |
| 01 | `01-contracts` | Stack CI, this contract, all-rule/source-format preservation goldens, pre-refactor timing. No analyzer change. |
| 02 | `02-graph-model` | Immutable records, collector, deterministic IDs, endpoint/duplicate/limit tests. No public format. |
| 03 | `03-tracked-state` | Private wrapper and scope/merge/loop refactor. Original outputs and plugin facts unchanged; default timing measured. |
| 04 | `04-linear-traces` | Sources, transforms, bounds, partition facts, writers, actions, and iterator materialization; graph on/off parity. |
| 05 | `05-control-flow` | Branch/try/match alternatives, scope restoration, loop summaries and TL003. No fabricated paths. |
| 06 | `06-notebooks` | Collector plumbing, cross-cell state, source kinds, Unicode coordinates, invalidation boundaries, file/blob parity. |
| 07 | `07-scan-reports` | Opt-in API, immutable report graph, final filtering/linking/pruning, errors, duplicate and plugin compatibility. |
| 08 | `08-change-overlay` | Conservative syntax/fact comparison, safe base operations, renames, cell shifts, duplicates, and incomplete-base tests. |
| 09 | `09-graph-json` | Separate versioned format, CLI/API parity including early errors, installed wheel/sdist verification. |
| 10 | `10-html-evidence` | Semantic HTML, security/CSP/privacy, keyboard workflow, browser checks. No diagram yet. |
| 11 | `11-visual-paths` | Deterministic SVG from the same records, explicit alternatives, non-color states, long-path handling and text equivalence. |
| 12 | `12-release-readiness` | Cross-browser/accessibility results, scan/render measurements, installed-package checks, safe artifact example, guides and release notes/version. |

### Review gates

- After 01: local checks and baseline recorded; hosted CI/CodeQL verification
  against a stack target remains necessary once pushing is authorized.
- After 03: inference preserved, plugin facts unchanged, no unexplained default
  scan regression. Stop here if the representation refactor fails this gate.
- After 06: every built-in rule and source kind has faithful evidence, with
  branches/loops/opacity tested. Required before public reporting work.
- After 09: installed graph JSON, comparison, policy filtering, and error reports
  work independently of HTML. Required before visual polish.
- After 10: inert hostile strings, zero requests, complete semantic evidence,
  and keyboard navigation pass. Required before diagrams.
- After 12: full compatibility, browser, security, manual accessibility, and
  measurement evidence is recorded before release approval.

Use the existing non-gating timing harness. Initial targets are graph-enabled
median scan time at most 1.25 times graph-disabled time and no unexplained
graph-disabled regression against the pre-refactor code. Measure rendering and
allocation peaks separately; Python allocation peaks are not process RSS.
These are engineering targets, not public speed claims or shared-CI thresholds.
Independent reviewers should compare explanation accuracy and completion time
against text. If unavailable, document that gap and make no productivity claims.

## Stack review and merging

Keep only the next two or three dependent PRs open. Each child initially targets
its predecessor's `riskmap/**` branch so review shows the incremental slice.
Both CI and CodeQL run for those base branches as well as `main`; push triggers
remain restricted to `main`. Required-check names, permissions, action pins,
and main/release protections are unchanged. Never use `pull_request_target`.

Local Git history must retain a separate commit boundary for each slice. Set
`branch.<branch>.gh-merge-base` to its predecessor (`main` for slice 01), and use
explicit `gh pr create --base <predecessor> --head <branch>` when publication is
authorized. The standard GitHub CLI supports this stack; no additional service
is needed. Do not use its dry-run mode as a no-push safeguard: it may still push.

Final merges always go to `main`, bottom-up, using the existing squash policy.
Do not merge children into feature branches or introduce an integration branch.
After a parent merges:

1. Preserve its old tip before restacking; use that as the boundary for the
   child's unique commits, not a guessed merge base after squash.
2. Rebase only that child delta onto updated `main` and retarget its PR to `main`.
3. Restack descendants onto their updated parents using their old boundaries.
4. When pushing is authorized, update only owned feature branches using lease
   protection; never force-push `main` or overwrite someone else's work.
5. Rerun required checks on the updated base and review the incremental diff.

Retargeting alone is insufficient after squash: it can leave previously reviewed
parent commits in the child's history. Stop at each slice's review boundary.
Local branch creation does not authorize pushing, opening PRs, or publishing.

Each PR description records stack position/predecessor, outcome, non-goals,
interfaces/files changed, compatibility tests, measurements, known limits,
and reviewer focus. The release-readiness PR is not a place to accumulate test debt.
