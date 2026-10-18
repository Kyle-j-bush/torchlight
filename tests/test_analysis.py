# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import unittest

from torchlight.analysis import SparkAnalyzer, parse_source
from torchlight.diagnostics import RULES

SETUP = (
    "from pyspark.sql import SparkSession, DataFrame\n"
    "spark = SparkSession.builder.appName('test').getOrCreate()\n"
    "df = spark.read.parquet('events')\n"
)


class SparkAnalysisTests(unittest.TestCase):
    def analyze(self, source, setup=SETUP):
        source = setup + source
        return SparkAnalyzer("example.py").analyze(
            parse_source(source, "example.py"), source
        )

    def codes(self, source, setup=SETUP):
        return [f.rule_id for f in self.analyze(source, setup)]

    def test_unbounded_driver_materialization(self):
        findings = self.analyze("df.collect()\ndf.toPandas()\n")
        self.assertEqual([f.rule_id for f in findings], ["TL001", "TL001"])
        self.assertEqual([f.location.line for f in findings], [4, 5])
        self.assertIn("parquet", findings[0].evidence[0])
        self.assertIn("No explicit row limit", findings[0].evidence[1])
        self.assertIn(".collect()", findings[0].message)

    def test_unrelated_unknown_and_non_call_methods_are_ignored(self):
        source = (
            "unknown.collect()\nunknown.toPandas()\nunknown.coalesce(1).write.parquet('x')\n"
            "df.collect\ncollect()\ndf.distinct()\ndf.count()\ndf.count().collect()\n"
            "text = 'df.collect()'\n# df.collect()\n"
        )
        self.assertEqual(self.codes(source), [])
        self.assertEqual(self.codes("df.collect()", setup=""), [])

    def test_import_and_builder_aliases(self):
        for setup in (
            "from pyspark.sql import SparkSession as Session\ns = Session.builder.config('x', 'y').getOrCreate()\n",
            "import pyspark.sql as sql\ns = sql.SparkSession.builder.master('local').getOrCreate()\n",
            "import pyspark.sql\ns = pyspark.sql.SparkSession.builder.getOrCreate()\n",
            "from pyspark.sql.session import SparkSession\ns = SparkSession(sc)\n",
            "from pyspark.sql.connect.session import SparkSession\ns = SparkSession.builder.remote('x').create()\n",
        ):
            with self.subTest(setup=setup):
                self.assertEqual(
                    self.codes("s.table('events').collect()", setup), ["TL001"]
                )

    def test_reader_and_session_apis(self):
        for expression in (
            "spark.range(100)",
            "spark.createDataFrame(records)",
            "spark.sql('select * from events')",
            "spark.read.format('delta').option('x', 'y').options(a=1).schema(schema).load(path)",
            "spark.newSession().table('events')",
            "spark.read.csv(path)",
        ):
            with self.subTest(expression=expression):
                self.assertEqual(self.codes(f"{expression}.collect()"), ["TL001"])

    def test_frame_identity_propagates_only_through_known_apis(self):
        for expression in (
            "df.filter('x > 0').select('x').distinct()",
            "df.groupBy('x').count()",
            "df.groupBy('x').agg(expr)",
            "df.na.drop().fillna(0)",
            "df.withColumns(columns).cache()",
        ):
            with self.subTest(expression=expression):
                self.assertEqual(self.codes(f"{expression}.toPandas()"), ["TL001"])
        for expression in ("df.unknown()", "df.rdd", "df.schema", "df.count()"):
            with self.subTest(expression=expression):
                self.assertEqual(self.codes(f"{expression}.collect()"), [])

    def test_aliases_and_reassignment(self):
        self.assertEqual(self.codes("alias = df\nalias.collect()"), ["TL001"])
        for reset in (
            "df = other",
            "df = []",
            "del df",
            "df, other = pair",
            "df += other",
        ):
            with self.subTest(reset=reset):
                self.assertEqual(self.codes(f"{reset}\ndf.collect()"), [])

    def test_bounded_calls_are_not_reported(self):
        for expression in (
            "df.limit(10)",
            "df.limit(num=0)",
            "df.limit(10).select('x').filter('x > 0')",
            "df.limit(10).distinct().coalesce(1)",
            "df.agg(expr)",
        ):
            with self.subTest(expression=expression):
                self.assertEqual(self.codes(f"{expression}.collect()"), [])
        self.assertEqual(self.codes("small = df.limit(10)\nsmall.toPandas()"), [])
        self.assertEqual(self.codes("df.limit(amount).collect()"), ["TL001"])
        self.assertEqual(self.codes("df.limit(-1).collect()"), ["TL001"])

    def test_expanding_operations_drop_known_row_bounds(self):
        for expression in (
            "df.limit(10).join(other, 'x')",
            "df.limit(10).union(other)",
            "df.limit(10).sample(withReplacement=True, fraction=2.0)",
            "df.limit(10).select(F.explode('items'))",
            "df.limit(10).selectExpr('explode(items)')",
            "df.limit(10).withColumn('item', explode('items'))",
        ):
            with self.subTest(expression=expression):
                self.assertEqual(self.codes(f"{expression}.collect()"), ["TL001"])

    def test_coalesce_only_warns_when_it_feeds_a_write(self):
        self.assertEqual(self.codes("df.coalesce(1)"), [])
        findings = self.analyze(
            "small = df.coalesce(1)\nsmall.write.mode('overwrite').parquet(path)"
        )
        self.assertEqual([f.rule_id for f in findings], ["TL002"])
        self.assertEqual(findings[0].location.line, 5)
        self.assertIn("coalesce(1) at line 4", findings[0].evidence[1])
        self.assertEqual(
            self.codes("df.coalesce(numPartitions=1).write.save(path)"), ["TL002"]
        )
        self.assertEqual(
            self.codes("df.coalesce(1).writeTo('table').using('delta').create()"),
            ["TL002"],
        )
        self.assertEqual(
            self.codes("writer = df.coalesce(1).write\nwriter.csv(path)"), ["TL002"]
        )

    def test_partition_changes_remove_single_partition_evidence(self):
        for operation in (
            "repartition(8)",
            "groupBy('x').count()",
            "distinct()",
            "join(other, 'x')",
        ):
            with self.subTest(operation=operation):
                self.assertEqual(
                    self.codes(f"df.coalesce(1).{operation}.write.parquet(path)"), []
                )
        self.assertEqual(self.codes("df.coalesce(2).write.parquet(path)"), [])
        # coalesce cannot increase an already single-partition input.
        self.assertEqual(
            self.codes("df.coalesce(1).coalesce(4).write.parquet(path)"), ["TL002"]
        )

    def test_loop_carried_withcolumn(self):
        for loop in ("for name in columns:", "for name in range(5):", "while more:"):
            with self.subTest(loop=loop):
                self.assertEqual(
                    self.codes(f"{loop}\n    df = df.withColumn(name, expression)"),
                    ["TL003"],
                )
        self.assertEqual(
            self.codes(
                "for name in columns:\n    df = df.select('*')\n    df = df.withColumn(name, expr)"
            ),
            ["TL003"],
        )

    def test_non_accumulating_and_single_iteration_loops_are_ignored(self):
        for body in (
            "result = df.withColumn(name, expr)",
            "df = spark.table('events')\n    df = df.withColumn(name, expr)",
            "df = base.withColumn(name, expr)",
            "df.withColumn(name, expr)",
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.codes(f"base = df\nfor name in columns:\n    {body}"), []
                )
        for iterator in ("[]", "['x']", "range(0)", "range(1)"):
            with self.subTest(iterator=iterator):
                self.assertEqual(
                    self.codes(
                        f"for name in {iterator}:\n    df = df.withColumn(name, expr)"
                    ),
                    [],
                )
        self.assertEqual(
            self.codes(
                "for name in columns:\n    df = df.withColumn(name, expr)\n    break"
            ),
            [],
        )

    def test_annotations_including_forward_references(self):
        for annotation in ("DataFrame", "'DataFrame'", "sql.DataFrame"):
            with self.subTest(annotation=annotation):
                source = f"import pyspark.sql as sql\ndef run(events: {annotation}):\n    events.collect()"
                self.assertEqual(self.codes(source), ["TL001"])
        self.assertEqual(
            self.codes("def run(s: SparkSession):\n    s.table('events').toPandas()"),
            ["TL001"],
        )
        self.assertEqual(
            self.codes("events: DataFrame = load_events()\nevents.collect()"), ["TL001"]
        )
        self.assertEqual(self.codes("def run(*dfs: DataFrame):\n    dfs.collect()"), [])

    def test_function_and_lambda_scopes_do_not_leak(self):
        self.assertEqual(
            self.codes("def f():\n    df = other\nf()\ndf.collect()"), ["TL001"]
        )
        self.assertEqual(self.codes("def f(df):\n    df.collect()"), [])
        self.assertEqual(self.codes("def f():\n    df.collect()\n    df = other"), [])
        self.assertEqual(self.codes("f = lambda df: df.collect()"), [])
        self.assertEqual(self.codes("f = lambda: df.collect()"), ["TL001"])
        self.assertEqual(
            self.codes(
                "class C:\n    local = df\n    def f(self):\n        local.collect()"
            ),
            [],
        )

    def test_branches_merge_conservatively(self):
        self.assertEqual(self.codes("if condition:\n    df = other\ndf.collect()"), [])
        self.assertEqual(
            self.codes(
                "if condition:\n    df = spark.table('a')\nelse:\n    df = spark.table('b')\ndf.collect()"
            ),
            ["TL001"],
        )
        self.assertEqual(
            self.codes("if condition:\n    df = df.limit(5)\ndf.collect()"), ["TL001"]
        )
        self.assertEqual(
            self.codes("df = df.limit(5) if condition else df\ndf.collect()"), ["TL001"]
        )
        self.assertEqual(self.codes("if False:\n    df.collect()"), [])
        self.assertEqual(
            self.codes(
                "if condition:\n    df = df.coalesce(1)\ndf.write.parquet(path)"
            ),
            [],
        )

    def test_loop_targets_comprehensions_and_imports_shadow(self):
        self.assertEqual(
            self.codes("for df in objects:\n    df.collect()\ndf.collect()"), []
        )
        self.assertEqual(
            self.codes("[df.collect() for df in objects]\ndf.collect()"), ["TL001"]
        )
        self.assertEqual(self.codes("import other as df\ndf.collect()"), [])
        self.assertEqual(self.codes("from other import thing as df\ndf.collect()"), [])
        self.assertEqual(self.codes("from other import *\ndf.collect()"), [])

    def test_try_match_and_with(self):
        self.assertEqual(
            self.codes(
                "try:\n    df = other\nexcept Exception:\n    pass\ndf.collect()"
            ),
            [],
        )
        self.assertEqual(
            self.codes("match obj:\n    case {'df': df}:\n        df.collect()"), []
        )
        self.assertEqual(self.codes("with context() as df:\n    df.collect()"), [])

    def test_assumed_sessions_are_explicit_and_can_be_shadowed(self):
        analyzer = SparkAnalyzer("example.py", ("spark",))
        source = "spark.table('events').collect()\nspark = other\nspark.table('events').collect()"
        findings = analyzer.analyze(parse_source(source, "example.py"), source)
        self.assertEqual(len(findings), 1)
        self.assertIn("SparkSession.table()", findings[0].evidence[0])
        self.assertIn("Explicitly assumed SparkSession", findings[0].evidence[0])

    def test_short_circuit_assignments_are_not_assumed_to_execute(self):
        self.assertEqual(
            self.codes(
                "condition and (events := spark.table('events'))\nevents.collect()"
            ),
            [],
        )
        self.assertEqual(self.codes("condition and (df := other)\ndf.collect()"), [])

    def test_type_aliases_replace_existing_bindings(self):
        self.assertEqual(self.codes("type df = int\ndf.collect()"), [])

    def test_findings_are_structured_and_character_columns_are_one_based(self):
        finding = self.analyze("é = 1; df.collect()")[0]
        self.assertEqual(finding.location.column, 8)
        payload = finding.to_dict()
        self.assertEqual(payload["rule_id"], "TL001")
        self.assertEqual(payload["severity"], "warning")
        self.assertEqual(payload["explanation"], RULES["TL001"].explanation)
        self.assertIn("Evidence:", str(finding))
        self.assertIn("Review:", str(finding))


if __name__ == "__main__":
    unittest.main()
