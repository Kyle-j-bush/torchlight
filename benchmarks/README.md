# Labeled regression corpus

`cases.json` contains 68 synthetic, labeled Python and notebook cases. Each case
states its purpose and expected `(rule ID, line, code-cell number)` findings.
Ordinary Python cases use `null` for the cell number. Databricks source exports
use physical file lines and exported cell numbers; Jupyter uses code-cell-local
lines and code-cell numbers. Fixtures are parsed, never executed.

Run the corpus separately:

```sh
python -m scripts.check_benchmark
```

The same expectations run in the normal unit suite, including against installed
distributions. Cases cover targeted risks, intentional uses, unrelated methods,
aliases, row bounds, branching, loop resets, and notebook state changes.
The 24 `pipeline-` cases added in v0.8.0 are agent-authored proposals with an
optional `rationale` field explaining each expectation, including non-findings.
They exercise longer reader/writer/helper flows, intentional small exports,
projections, local iterators, and notebook boundaries without executing code.
Existing schema-1 cases need no new field; old expectations remain unchanged.
In particular, helper-return boundaries can miss real risks, and the analyzer
currently drops bounds at union even when both inputs have literal limits.

**This is a regression suite, not a real-world accuracy benchmark.** An empty
expected list means no diagnostic is expected for the supported analysis; it does
not certify that a program is safe. Matching all fixtures does not establish
production precision, recall, runtime savings, or superiority to another tool.

For a new rule or bug fix, add a minimal positive case and a related negative case
with an explanation. Never contribute private notebooks, credentials, or data.
The next validation step is independently labeled, permissioned real-world code
and feedback from Spark reviewers, including dismissed findings and missed risks.

The [draft real-world protocol](real-world-protocol.md) defines permission records,
frozen project-level splits, independent source audits, adjudication, per-rule
precision/recall and reviewer burden, plus performance reporting. It is a plan,
not a collected dataset or a claim of measured accuracy.

The [local pilot tools](local-validation.md) freeze permissioned source and blank
labels before evaluation. The [public-example rehearsal](../docs/development/public-corpus-rehearsal.md)
uses one agent's labels on 147 Apache Spark files; it is not independent or
production accuracy validation, and supplies no positive sites for recall.
The separate [timing harness](performance.md) measures a deterministic synthetic
workload; it does not benchmark production accuracy or Spark runtime savings.
