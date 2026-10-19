# Labeled regression corpus

`cases.json` contains 44 synthetic, labeled Python and notebook cases. Each case
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
