# Databricks Python source notebooks

Available in v0.6.0+. Scan exported `.py` notebooks with the same CLI or API used
for Python files. No Databricks SDK, credentials, Spark runtime, or new option is
required. Source is parsed, never imported or executed.

```python
# Databricks notebook source
from pyspark.sql import SparkSession

df = SparkSession.builder.getOrCreate().table("events")

# COMMAND ----------
# MAGIC %python
# MAGIC rows = list(df.toLocalIterator())
```

This reports TL005 at **physical file line 8, column 16, cell 2**. It does not
pretend that the decoded Python column is the physical column after `# MAGIC `.

## Recognition and state

- The first line must be `# Databricks notebook source` (trailing whitespace is
  accepted). A UTF-8 BOM and CRLF are supported through ordinary file decoding.
  Without that header, marker-like comments retain ordinary Python behavior.
- Exact top-level `# COMMAND ----------` comments separate cells. Markers inside
  strings do not create boundaries. Cells are numbered from 1 in export order,
  including empty and non-Python cells, not by execution counters.
- Top-level `# MAGIC ` lines are decoded only when they are actual comments, not
  text inside Python strings. `%python` headers are blanked without shifting rows.
  `# DBTITLE` remains an ordinary comment.
- Normal Python cells and supported Python cell magics share existing analysis:
  definitions, aliases, iterator/partition provenance, and row bounds flow across
  cells in document order. Session assumptions remain explicitly opt-in.
- Opaque language/magic cells (`%sql`, `%scala`, `%r`, `%run`, `%pip`, `%sh`, `%md`,
  and unknown magics) are skipped and invalidate prior knowledge. This deliberately
  includes Markdown rather than assuming opaque cell contents cannot affect the
  environment. No SQL, shell commands, dependencies, or imported notebooks execute.
- Parse errors invalidate state; scanning continues at reliable later boundaries.
  Unterminated multiline strings/other tokenization failures can make boundaries
  ambiguous: the file then reports an error instead of guessing cell locations.

## Reports and policy

For Databricks source exports, `Finding.location.cell` is the exported cell number,
while `line`, `column`, and `end_line` refer to the **physical `.py` file**.
Jupyter `.ipynb` findings retain code-cell-relative coordinates and numbering.
JSON schema 1 is unchanged; consumers must account for the source file kind.

GitHub annotations and SARIF regions point to physical `.py` locations. SARIF
also retains `notebookLocation` cell metadata; its line/column fields are physical
for `.py`, cell-local for `.ipynb`. Jupyter annotations remain file-level rather
than pointing to arbitrary JSON lines.

Rule selection, excludes, reasoned inline suppressions, baselines, and
[Git comparison](git-comparison.md) all use the shared scanner. Put suppressions
on the decoded Python call's line, retaining its export prefix:

```python
# MAGIC rows = list(df.toLocalIterator())  # torchlight: ignore[TL005] -- reviewed small result
```

Suppression scope does not cross cells. Structural fingerprints ignore source
line and cell shifts, so inserting a cell does not by itself create a new warning.
Changes to the actual call or named scope can still change identity.

Only Python source exports are supported here. DBC/ZIP/HTML archives, Scala/R/SQL
source notebooks, runtime environment metadata, widget values, vendor extensions,
and actual notebook execution order are not analyzed. See the upstream
[format guidance](https://docs.databricks.com/aws/en/notebooks/notebook-export-import)
and the [Spark-version assessment](development/spark-versions.md). A clean scan
does not prove every cell was analyzed or that the notebook is safe.
