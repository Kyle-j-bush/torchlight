# What Torchlight can establish

Torchlight tracks known Spark identities and selected facts through a Python AST:
imports and aliases, session builders, supported readers and transformations,
type annotations, literal row limits, single-partition provenance, and
loop-carried DataFrames. Findings include evidence rather than relying on a name
such as `df` or a method such as `collect` alone.

Unknown APIs lose identity instead of being guessed to return DataFrames. This
precision-first boundary can miss risks in project helper functions, dynamic
wrappers, object attributes, or containers. Analysis is local to a file, not
interprocedural or cross-file. RDDs and SQL strings are not analyzed. Function
bodies use definition-site knowledge and annotations, not simulated calls.

A literal nonnegative `.limit()` or known global aggregation can establish a row
bound. Joins, unions, generators, and other recognized expanding operations can
discard it. A row bound does **not** establish memory safety: row width and driver
memory are unknown, and even a very large literal bound is still a bound.

## Jupyter notebook state

One analyzer processes code cells in **document order**, not historical kernel
execution order. Spark identities, aliases, bounds, and partition evidence can
flow between cells. Cell numbers count **code cells only**; line numbers are
relative to each code cell. Notebook outputs are never executed or analyzed.

Top-level `await`, shell escapes, `%matplotlib`, and Python cell magics
`capture`, `debug`, `prun`, `time`, and `timeit` are supported with line positions
preserved. Other magics (including `%run`, `%reset`, and SQL cells) are opaque:
the cell is skipped and previous state is discarded. Parse errors also discard
state, produce errors, and allow later cells to be scanned afresh.

Torchlight does not load `%run` targets or reconstruct interactive execution.

## Databricks Python source exports

Since v0.6.0, `.py` files with the first-line Databricks header use token-aware
cell and magic parsing. Exported cells share state until an opaque cell or parse
error invalidates it. Their cell numbers count all exported cells, and their
coordinates are physical file positions, including `# MAGIC` prefixes. Ordinary
`.py` files without the header are unchanged. See [format boundaries](databricks.md).

## Eager local iteration

TL005 proves `list()`/`tuple()` consumption of a known Spark local iterator; it
does not treat streaming itself as full driver collection. Known built-in and
iterator aliases propagate, while rebinding and opaque cells discard evidence.
Exhaustion, runtime monkey-patching, comprehensions, and custom consumers are
not modeled. See [TL005](rules/TL005.md).

## Interpretation

- A finding asks a reviewer to examine a potential consequence. Intentional small
  exports and carefully bounded driver work can be legitimate.
- No rule applies a semantics-changing automatic fix.
- Suppressions require specific rule IDs and nonempty reasons; annotate the
  reported write for TL002/TL004, not an earlier partition-changing assignment.
- A clean scan means no supported pattern was found. It does not mean every
  cell was analyzed or that the job is safe, correct, or efficient.

There are no independently measured real-world precision/recall figures yet.
See the [validation protocol](../benchmarks/real-world-protocol.md) rather than
inferring accuracy from the synthetic regression suite.
