# Spark-version targeting assessment

Assessed 2026-10-18 for v0.6.0. This is a documentation/source survey, not a Spark
runtime test or a vendor compatibility certification. Representative upstream
tags are 3.3.4, 3.4.4, and 3.5.7; these are not claims about the newest releases.
Spark 4.x and vendor backports are outside this assessment.

## Evidence and consequences

| API/advice | Spark 3.3 | Spark 3.4 | Spark 3.5 | Torchlight consequence |
| --- | --- | --- | --- | --- |
| `collect()` / `toPandas()` | Entire result returned locally | Spark Connect support added; local result still retained | Same materialization concern | TL001 stays version-independent; Arrow does not make a full local result distributed. |
| `coalesce(1)` / `repartition(1)` before writes | Single output partition; repartition shuffles | Connect availability changes, not the single-partition concern | Same review concern | Keep TL002/TL004 qualified; do not prescribe interchangeable rewrites or one-file guarantees. |
| `withColumns()` | Introduced in 3.3.0 | Connect support added | Available | TL003 may suggest it within this survey, but `select()` remains the broadly applicable alternative. Older runtimes need explicit availability caveats. |
| `withColumnsRenamed()` | Not in the surveyed API | Introduced in 3.4.0 | Available | Recognizing identity through a method is not proof that the method exists in the deployed runtime. |
| `offset()` | Not in the surveyed API | Available in Connect, absent from classic DataFrame | Classic PySpark support added | A single major/minor target is insufficient to represent every classic/Connect difference. |
| `toLocalIterator(prefetchPartitions=...)` | Streams; memory can reach largest partition, or two largest with prefetch | Connect added; prefetch argument does not take effect for Connect | Same documented distinction | Do not treat bare iteration like `collect()`. Eager Python container construction is a separate, evidenced risk. |

Primary sources inspected:

- Upstream DataFrame definitions/docstrings:
  [3.3.4](https://github.com/apache/spark/blob/v3.3.4/python/pyspark/sql/dataframe.py),
  [3.4.4](https://github.com/apache/spark/blob/v3.4.4/python/pyspark/sql/dataframe.py),
  [3.5.7](https://github.com/apache/spark/blob/v3.5.7/python/pyspark/sql/dataframe.py).
- Pandas conversion notes explicitly describe loading the result into driver memory:
  [3.3.4](https://github.com/apache/spark/blob/v3.3.4/python/pyspark/sql/pandas/conversion.py),
  [3.4.4](https://github.com/apache/spark/blob/v3.4.4/python/pyspark/sql/pandas/conversion.py),
  [3.5.7](https://github.com/apache/spark/blob/v3.5.7/python/pyspark/sql/pandas/conversion.py).
- Connect's separate `offset` implementation:
  [3.4.4](https://github.com/apache/spark/blob/v3.4.4/python/pyspark/sql/connect/dataframe.py)
  and [3.5.7](https://github.com/apache/spark/blob/v3.5.7/python/pyspark/sql/connect/dataframe.py).
- Python's [list and tuple constructors](https://docs.python.org/3/library/stdtypes.html#sequence-types-list-tuple-range)
  consume an iterable into a container; wrapping a streamed Spark iterator retains
  the consumed rows in the Python process regardless of prefetch behavior.

## Decision for v0.6.0

Do **not** add `target-spark` yet. None of the existing risk warnings needs a
version switch to remain useful; a version flag alone would misrepresent Connect
and vendor capabilities. Keep current output/fingerprint contracts and retain
the documented `withColumns()` availability limit. This is an assessment of
targeting, not an implementation of a version-aware API validator.

TL005 should report proven built-in `list()`/`tuple()` consumption of a known
DataFrame's unbounded `toLocalIterator()`, not the iterator by itself. Reuse
receiver and row-bound facts; invalidate on unknown calls/rebindings. The
warning must describe eager retention, not assert that streaming always exhausts
driver memory. No semantics-changing automatic rewrite is justified.

Databricks source-notebook recognition is independent of Spark API versions.
Use the documented first-line header and cell delimiter from
[Databricks import/export guidance](https://docs.databricks.com/aws/en/notebooks/notebook-export-import).
Support Python source exports only, not DBC archives, SQL analysis, Scala/R, or
vendor-specific execution-order claims. Exported cells still need conservative
state invalidation at opaque magics.

## When to revisit targeting

Add a target only when a concrete rule/recommendation needs it, with explicit
unknown-target behavior, classic/Connect distinctions, vendor/backport limits,
validated CLI/TOML/API precedence, and regression tests at each boundary. Do not
infer a deployment version by importing Spark, executing notebook setup, or
guessing from Databricks Runtime names. Runtime validation and independent
real-world precision/recall remain separate follow-up work.
