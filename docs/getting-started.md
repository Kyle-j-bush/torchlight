# Getting started

Use Python 3.12 or newer. The scanner runtime can be separate from your Spark
project's environment; Spark itself is not needed to scan source.

```sh
python -m pip install torchlight-spark
torchlight jobs/ notebooks/
```

The distribution is `torchlight-spark`, while the command and import package are
`torchlight`. Do not install the unrelated `torchlight` distribution alongside it.
For isolation, use `pipx install torchlight-spark`.

To try **unreleased configuration support**, install a checkout containing it:

```sh
python -m pip install .
python -m torchlight jobs/ notebooks/
```

Save this as `pipeline.py`:

```python
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()
events = spark.read.parquet("events")
rows = events.collect()
```

`torchlight pipeline.py` exits with status 1 and reports TL001 at line 5, with
Spark-origin evidence, an explanation of driver-memory risk, and a review
suggestion. It does not read `events`, start a cluster, or prove that collection
will exhaust memory.

Review the expected result size and row width. Keep computation distributed when
appropriate; use a literal limit only when returning partial data is intended.
For an intentional operation, an auditable suppression is possible:

```python
rows = events.collect()  # torchlight: ignore[TL001] -- verified small lookup result
```

The reason is mandatory. Suppressions apply only to the finding's first or last
line in that cell, not the whole file. Invalid rule IDs or missing reasons are
errors, not silent ignores.

Next: [share project configuration](configuration.md), [enable CI](integrations.md),
or read [the rules](rules/README.md) and [analysis limits](analysis.md).
