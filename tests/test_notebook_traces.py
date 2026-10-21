# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_riskmap_preservation import CELLS, EXPECTED_CODES, RecordingDetector

from torchlight import Scanner
from torchlight.databricks import HEADER, SEPARATOR, scan_databricks_source
from torchlight.diagnostics import Location, Rule
from torchlight.files import scan_file, scan_python, scan_python_source, scan_source
from torchlight.graph import (
    AnalysisGraph,
    CaptureLimit,
    FindingAnchor,
    GraphArtifact,
    GraphEdge,
    GraphFacts,
    GraphNode,
    _GraphCollector,
)
from torchlight.notebooks import scan_notebook, scan_notebook_source
from torchlight.plugins import Diagnostic, Plugin, Value

SETUP = CELLS[0]
KINDS = ("python", "jupyter", "databricks")


def document(kind, cells):
    if kind == "python":
        return "".join(cells)
    if kind == "jupyter":
        return json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": "Not code."},
                    *(
                        {"cell_type": "code", "source": c.splitlines(keepends=True)}
                        for c in cells
                    ),
                ]
            }
        )
    return HEADER + "\n" + (SEPARATOR + "\n").join(cells)


class NotebookTraceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def scan(
        self, kind, *cells, source=None, budget=10_000, assume_sessions=(), plugins=()
    ):
        path = self.root / ("job.ipynb" if kind == "jupyter" else "job.py")
        source = document(kind, cells) if source is None else source
        data = source.encode("utf-8")
        path.write_bytes(data)
        observed, graphs = [], []
        for from_blob in (False, True):
            for enabled in (False, True):
                recorder = RecordingDetector()
                plugin = Plugin(
                    Rule("LOCAL001", "Record facts", "Test only.", "No action."),
                    recorder,
                )
                collector = (
                    _GraphCollector(
                        GraphArtifact(str(path), "python"), max_records=budget
                    )
                    if enabled
                    else None
                )
                scanner = scan_source if from_blob else scan_file
                args = (path, data) if from_blob else (path,)
                findings, errors = scanner(
                    *args,
                    assume_sessions=assume_sessions,
                    plugins=(plugin, *plugins),
                    _collector=collector,
                )
                observed.append(
                    ([f.to_dict() for f in findings], errors, recorder.facts)
                )
                self.assertEqual(observed[0], observed[-1])
                self.assertTrue(all(type(f.receiver) is Value for f in recorder.facts))
                if enabled:
                    graph = collector.build()
                    self.assertEqual(graph.artifacts[0].source_kind, kind)
                    self.assertLessEqual(
                        len(graph.nodes) + len(graph.edges) + len(graph.anchors), budget
                    )
                    indices = {n.id: i for i, n in enumerate(graph.nodes)}
                    self.assertTrue(
                        all(indices[e.source] < indices[e.target] for e in graph.edges)
                    )
                    graphs.append(graph)
        self.assertEqual(graphs[0], graphs[1])
        return findings, errors, graph

    def incoming(self, graph, node, relation):
        return {
            e.source
            for e in graph.edges
            if e.target == node.id and e.relation == relation
        }

    def test_every_rule_and_source_kind_has_operation_anchors_and_cross_cell_paths(
        self,
    ):
        for kind in KINDS:
            with self.subTest(kind=kind):
                findings, errors, graph = self.scan(kind, *CELLS)
                self.assertEqual(errors, [])
                self.assertEqual([f.rule_id for f in findings], EXPECTED_CODES)
                nodes = {n.id: n for n in graph.nodes}
                self.assertEqual(len(graph.anchors), len(findings))
                for finding, anchor in zip(findings, graph.anchors, strict=True):
                    self.assertEqual(
                        (anchor.rule_id, anchor.location),
                        (finding.rule_id, finding.location),
                    )
                    node = nodes[anchor.node_id]
                    self.assertEqual(node.location, finding.location)
                    self.assertEqual(
                        node.kind,
                        {"TL002": "sink", "TL004": "sink", "TL003": "transform"}.get(
                            finding.rule_id, "action"
                        ),
                    )
                    if finding.rule_id == "TL003":
                        controls = self.incoming(graph, node, "control")
                        self.assertEqual([nodes[n].kind for n in controls], ["loop"])
                sink = next(n for n in graph.nodes if n.kind == "sink")
                self.assertEqual(
                    sink.before.single_partition.cell, None if kind == "python" else 2
                )
                if kind != "python":
                    self.assertTrue(
                        any(
                            nodes[e.source].location.cell
                            < nodes[e.target].location.cell
                            for e in graph.edges
                            if e.relation == "receiver"
                        )
                    )

    def test_cross_cell_alias_bounds_and_partition_clearing_are_not_reconstructed(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                findings, errors, graph = self.scan(
                    kind,
                    SETUP,
                    "small = df.limit(2)\nalias = small\none = df.coalesce(1)\n",
                    "alias.collect()\nexpanded = small.selectExpr('explode(items)')\n"
                    "cleared = one.repartition(4)\n",
                    "expanded.collect()\ncleared.write.parquet('out')\n",
                )
                self.assertEqual(errors, [])
                self.assertEqual([f.rule_id for f in findings], ["TL001"])
                safe = next(n for n in graph.nodes if n.label == ".collect()")
                bound = next(n for n in graph.nodes if n.label == ".limit()")
                self.assertEqual(self.incoming(graph, safe, "receiver"), {bound.id})
                self.assertEqual(safe.before.row_limit, 2)
                self.assertEqual(graph.nodes[-1].before, GraphFacts("writer"))

    def test_regression_corpus_keeps_file_blob_and_capture_parity(self):
        cases = json.loads(
            (
                Path(__file__).resolve().parents[1] / "benchmarks" / "cases.json"
            ).read_text(encoding="utf-8")
        )["cases"]
        for case in cases:
            if "cells" in case:
                kind = "jupyter"
                source = document(
                    kind, ["\n".join(cell) + "\n" for cell in case["cells"]]
                )
            else:
                source = "\n".join(case["source"]) + "\n"
                kind = "databricks" if source.startswith(HEADER + "\n") else "python"
            for budget in (1, 10_000):
                with self.subTest(case=case["name"], budget=budget):
                    _, errors, _ = self.scan(
                        kind,
                        source=source,
                        budget=budget,
                        assume_sessions=tuple(case.get("assume_sessions", ())),
                    )
                    self.assertEqual(errors, [])

    def test_cross_cell_alternatives_loops_and_free_call_boundaries(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                findings, errors, graph = self.scan(
                    kind,
                    SETUP,
                    "if condition:\n    df = df.limit(2)\nelse:\n    df = df.select('id')\n"
                    "for column in columns:\n    df = df.withColumn(column, expr)\n",
                    "result = custom(df)\nresult.collect()\ndf.collect()\n",
                )
                self.assertEqual(errors, [])
                self.assertEqual([f.rule_id for f in findings], ["TL003", "TL001"])
                self.assertTrue(any(e.relation == "alternative" for e in graph.edges))
                boundary = next(n for n in graph.nodes if n.kind == "opaque")
                self.assertFalse(any(e.source == boundary.id for e in graph.edges))
                self.assertNotEqual(self.incoming(graph, boundary, "control"), set())

    def test_opaque_cells_invalidate_all_old_paths_and_allow_fresh_recovery(self):
        for kind in ("jupyter", "databricks"):
            for magic in (
                "%run other",
                "%reset -f",
                "%pip install other",
                "%%sql\nselect 1",
                "%%unknown",
            ):
                with self.subTest(kind=kind, magic=magic):
                    findings, errors, graph = self.scan(
                        kind,
                        SETUP + "alias = df\nrows = df.toLocalIterator()\n",
                        magic + "\ndf.collect()\n",
                        "df.collect()\nalias.collect()\nlist(rows)\n",
                        SETUP + "df.collect()\n",
                    )
                    self.assertEqual(errors, [])
                    self.assertEqual([f.rule_id for f in findings], ["TL001"])
                    self.assertEqual(findings[0].location.cell, 4)
                    boundary = next(n for n in graph.nodes if n.kind == "opaque")
                    self.assertIn("previous bindings invalidated", boundary.label)
                    self.assertEqual(boundary.location.cell, 2)
                    self.assertGreaterEqual(
                        len(self.incoming(graph, boundary, "control")), 2
                    )
                    self.assertEqual(self.incoming(graph, boundary, "receiver"), set())
                    self.assertFalse(any(e.source == boundary.id for e in graph.edges))
                    before = {n.id for n in graph.nodes[: graph.nodes.index(boundary)]}
                    after = {
                        n.id for n in graph.nodes[graph.nodes.index(boundary) + 1 :]
                    }
                    self.assertFalse(
                        any(
                            e.source in before and e.target in after
                            for e in graph.edges
                        )
                    )

    def test_unparseable_cells_preserve_errors_and_recover_without_stale_paths(self):
        for kind in ("jupyter", "databricks"):
            for invalid in (
                ("?\n", "df =\n", "\x00\n") if kind == "jupyter" else ("?\n", "df =\n")
            ):
                with self.subTest(kind=kind, invalid=invalid):
                    findings, errors, graph = self.scan(
                        kind, SETUP, invalid, "df.collect()\n", SETUP + "df.collect()\n"
                    )
                    self.assertEqual(len(errors), 1)
                    self.assertEqual([f.location.cell for f in findings], [4])
                    boundary = next(n for n in graph.nodes if n.kind == "opaque")
                    self.assertIn("Unparseable code cell 2", boundary.label)
                    self.assertEqual(boundary.location.cell, 2)
                    self.assertFalse(any(e.source == boundary.id for e in graph.edges))

    def test_boundaries_survive_without_prior_sources_or_downstream_findings(self):
        for kind in ("jupyter", "databricks"):
            with self.subTest(kind=kind):
                findings, errors, graph = self.scan(
                    kind, "%%unknown\n", "%%unknown\n", "df.collect()\n"
                )
                self.assertEqual((findings, errors), ([], []))
                self.assertEqual([n.kind for n in graph.nodes], ["opaque", "opaque"])
                self.assertEqual(graph.edges, ())
                self.assertNotEqual(graph.nodes[0].id, graph.nodes[1].id)

    def test_invalid_notebook_metadata_has_no_invented_source_coordinates(self):
        for invalid in (
            None,
            {"cell_type": "code", "source": [1]},
            {"cell_type": "code", "source": {}},
        ):
            with self.subTest(invalid=invalid):
                source = json.dumps(
                    {
                        "cells": [
                            {"cell_type": "code", "source": SETUP},
                            invalid,
                            {"cell_type": "code", "source": "df.collect()"},
                            {"cell_type": "code", "source": SETUP + "df.collect()"},
                        ]
                    }
                )
                findings, errors, graph = self.scan("jupyter", source=source)
                self.assertEqual(len(errors), 1)
                self.assertEqual(len(findings), 1)
                boundary = next(n for n in graph.nodes if n.kind == "opaque")
                self.assertIsNone(boundary.location)
                self.assertIn("2", boundary.label)
                self.assertTrue(self.incoming(graph, boundary, "control"))

    def test_code_cell_numbering_ignores_markdown_raw_and_empty_sources(self):
        source = json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": "df.collect()"},
                    {"cell_type": "code", "source": SETUP},
                    {"cell_type": "raw", "source": "df.collect()"},
                    {"cell_type": "code"},
                    {"cell_type": "code", "source": ["é = 1; df.collect()\n"]},
                ]
            }
        )
        findings, errors, graph = self.scan("jupyter", source=source)
        self.assertEqual(errors, [])
        self.assertEqual(findings[0].location, Location(1, 8, 3))
        self.assertEqual(graph.nodes[-1].location, findings[0].location)

    def test_databricks_magic_prefixes_and_unicode_use_physical_coordinates(self):
        findings, errors, graph = self.scan(
            "databricks",
            SETUP,
            "# MAGIC %python\n# MAGIC π = 1; list(\n# MAGIC     df.toLocalIterator()\n# MAGIC )\n",
        )
        self.assertEqual(errors, [])
        self.assertEqual(findings[0].location, Location(7, 16, 2))
        self.assertEqual(findings[0].end_line, 9)
        self.assertEqual(graph.nodes[-1].location, findings[0].location)
        self.assertEqual(graph.nodes[-2].location, Location(8, 13, 2))
        _, _, graph = self.scan(
            "databricks", SETUP, "# DBTITLE 1,Ignored\n# MAGIC %sql select 1\n"
        )
        self.assertEqual(graph.nodes[-1].location, Location(7, 9, 2))

    def test_supported_magics_and_shell_lines_keep_the_existing_state_policy(self):
        for kind in ("jupyter", "databricks"):
            for magic in (
                "%%capture",
                "%%debug",
                "%%prun",
                "%%time",
                "%%timeit",
                "%matplotlib inline",
                "!echo inert",
            ):
                with self.subTest(kind=kind, magic=magic):
                    findings, errors, graph = self.scan(
                        kind, SETUP, magic + "\ndf.collect()\n"
                    )
                    self.assertEqual(errors, [])
                    self.assertEqual([f.rule_id for f in findings], ["TL001"])
                    self.assertFalse(any(n.kind == "opaque" for n in graph.nodes))
                    self.assertEqual(
                        self.incoming(graph, graph.nodes[-1], "receiver"),
                        {graph.nodes[1].id},
                    )

    def test_magic_and_separator_text_inside_strings_does_not_create_boundaries(self):
        for kind in ("jupyter", "databricks"):
            with self.subTest(kind=kind):
                findings, errors, graph = self.scan(
                    kind,
                    SETUP,
                    'text = """\n%%sql\n# COMMAND ----------\n# MAGIC %run other\n"""\ndf.collect()\n',
                )
                self.assertEqual(errors, [])
                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0].location.cell, 2)
                self.assertFalse(any(n.kind == "opaque" for n in graph.nodes))

    def test_capture_budget_is_shared_across_cells_including_invalidation(self):
        for kind in ("jupyter", "databricks"):
            cells = (
                SETUP,
                "df.collect()\n",
                "%%sql\nselect 1\n",
                SETUP + "df.collect()\n",
            )
            _, _, graph = self.scan(kind, *cells)
            required = len(graph.nodes) + len(graph.edges) + len(graph.anchors)
            for budget in range(1, required + 2):
                with self.subTest(kind=kind, budget=budget):
                    findings, errors, graph = self.scan(kind, *cells, budget=budget)
                    self.assertEqual(errors, [])
                    self.assertEqual([f.rule_id for f in findings], ["TL001", "TL001"])
                    self.assertEqual(graph.capture_complete, budget >= required)

    def test_bom_and_universal_newlines_match_files_and_blobs(self):
        for kind in KINDS:
            for newline in ("\n", "\r\n", "\r"):
                with self.subTest(kind=kind, newline=repr(newline)):
                    source = document(kind, (SETUP, "é = 1; df.collect()\n"))
                    # JSON escapes code-cell newlines; physical line endings still decode identically.
                    findings, errors, _ = self.scan(
                        kind, source="\ufeff" + source.replace("\n", newline)
                    )
                    self.assertEqual(errors, [])
                    self.assertEqual([f.rule_id for f in findings], ["TL001"])

    def test_cell_insertion_preserves_structural_ids_and_distinguishes_duplicates(self):
        cells = (
            SETUP,
            "for column in columns:\n    df = df.withColumn(column, expr)\n",
            "%%unknown\n",
            SETUP + "df.collect()\ndf.collect()\n",
        )
        for kind in ("jupyter", "databricks"):
            with self.subTest(kind=kind):
                _, _, graph = self.scan(kind, *cells)
                _, _, shifted = self.scan(kind, "# inserted cell\n", *cells)
                self.assertEqual(
                    [n.id for n in graph.nodes], [n.id for n in shifted.nodes]
                )
                self.assertEqual(
                    [n.key for n in graph.nodes], [n.key for n in shifted.nodes]
                )
                self.assertEqual(
                    [n.location.cell + 1 for n in graph.nodes],
                    [n.location.cell for n in shifted.nodes],
                )
                self.assertEqual(graph.nodes[-1].key, graph.nodes[-2].key)
                self.assertNotEqual(graph.nodes[-1].id, graph.nodes[-2].id)

    def test_read_and_decoding_errors_are_unchanged_with_empty_capture(self):
        for suffix, kind in ((".py", "python"), (".ipynb", "jupyter")):
            path = self.root / ("unreadable" + suffix)
            for scanner in (
                scan_file,
                scan_python if suffix == ".py" else scan_notebook,
            ):
                with self.subTest(scanner=scanner.__name__):
                    collector = _GraphCollector(GraphArtifact(str(path), "python"))
                    self.assertEqual(scanner(path), scanner(path, _collector=collector))
                    self.assertEqual(collector.build().nodes, ())
                    self.assertEqual(collector.artifact.source_kind, kind)
            path.write_bytes(b"\xff")
            collector = _GraphCollector(GraphArtifact(str(path), "python"))
            baseline = scan_source(path, b"\xff")
            self.assertEqual(baseline, scan_file(path))
            self.assertEqual(baseline, scan_source(path, b"\xff", _collector=collector))
            self.assertEqual(collector.build().nodes, ())
            self.assertEqual(collector.artifact.source_kind, kind)

    def test_direct_low_level_entry_points_forward_the_private_collector(self):
        for kind in KINDS:
            path = self.root / ("direct.ipynb" if kind == "jupyter" else "direct.py")
            source = document(kind, (SETUP, "df.collect()\n"))
            path.write_text(source, encoding="utf-8")
            scanners = (
                (scan_notebook, scan_notebook_source)
                if kind == "jupyter"
                else (scan_python, scan_python_source)
            )
            if kind == "databricks":
                scanners = (*scanners, scan_databricks_source)
            for scanner in scanners:
                with self.subTest(kind=kind, scanner=scanner.__name__):
                    collector = _GraphCollector(GraphArtifact(str(path), "python"))
                    args = (
                        (path,)
                        if scanner in (scan_notebook, scan_python)
                        else (path, source)
                    )
                    findings, errors = scanner(*args, _collector=collector)
                    self.assertEqual(errors, [])
                    self.assertEqual(len(findings), 1)
                    self.assertEqual(collector.build().artifacts[0].source_kind, kind)
                    self.assertEqual(len(collector.build().anchors), 1)

    def test_document_errors_do_not_become_successful_or_fake_cell_paths(self):
        for kind, source in (
            ("python", "?"),
            ("jupyter", "{"),
            ("jupyter", "[]"),
            ("jupyter", '{"cells": null}'),
            (
                "databricks",
                HEADER + '\ntext = """\n# COMMAND ----------\ndf.collect()\n',
            ),
        ):
            with self.subTest(kind=kind, source=source):
                findings, errors, graph = self.scan(kind, source=source)
                self.assertEqual(findings, [])
                self.assertEqual(len(errors), 1)
                self.assertEqual(graph.nodes, ())

    def test_plugin_diagnostics_suppressions_and_failures_are_unchanged(self):
        class Count:
            rule_id = "TEAM001"

            def check(self, facts):
                if facts.method == "count":
                    yield Diagnostic(self.rule_id, ("verbatim <evidence>",))

        class Broken(Count):
            def check(self, facts):
                if facts.method == "count":
                    raise RuntimeError("private error")
                return ()

        rule = Rule("TEAM001", "Review count", "Test only.", "No action.")
        for kind in KINDS:
            with self.subTest(kind=kind):
                findings, errors, graph = self.scan(
                    kind,
                    SETUP,
                    "df.count() # torchlight: ignore[TEAM001] -- intentional\n"
                    "df.count()\ndf.collect() # torchlight: ignore[TL001]\n",
                    plugins=(Plugin(rule, Count()),),
                )
                self.assertEqual([f.rule_id for f in findings], ["TEAM001", "TL001"])
                self.assertEqual(findings[0].evidence, ("verbatim <evidence>",))
                self.assertEqual(len(errors), 1)
                self.assertEqual(
                    len(graph.anchors), 3
                )  # Anchors remain pre-policy until slice 07.
                findings, errors, _ = self.scan(
                    kind, SETUP, "df.count()\n", plugins=(Plugin(rule, Broken()),)
                )
                self.assertEqual(findings, [])
                self.assertIn("plugin TEAM001 failed (RuntimeError)", errors[0])
                self.assertNotIn("private error", errors[0])

    def test_assumed_sessions_are_not_restored_after_an_opaque_cell(self):
        for kind in ("jupyter", "databricks"):
            with self.subTest(kind=kind):
                findings, errors, graph = self.scan(
                    kind,
                    "spark.table('events').collect()\n",
                    "%%unknown\n",
                    "spark.table('events').collect()\n",
                    assume_sessions=("spark",),
                )
                self.assertEqual(errors, [])
                self.assertEqual(len(findings), 1)
                self.assertIn("prior trace unavailable", graph.nodes[-1].label)

    def test_default_notebook_scans_allocate_no_graph_records_even_at_boundaries(self):
        paths = []
        for kind in ("jupyter", "databricks"):
            path = self.root / ("plain.ipynb" if kind == "jupyter" else "export.py")
            path.write_text(
                document(
                    kind, (SETUP, "%%sql\nselect 1\n", "?\n", SETUP + "df.collect()\n")
                ),
                encoding="utf-8",
            )
            paths.append(path)
        with contextlib.ExitStack() as stack:
            for record in (
                AnalysisGraph,
                GraphArtifact,
                GraphNode,
                GraphEdge,
                GraphFacts,
                FindingAnchor,
                CaptureLimit,
                _GraphCollector,
            ):
                stack.enter_context(
                    patch.object(
                        record,
                        "__init__",
                        side_effect=AssertionError("default scan allocated graph data"),
                    )
                )
            for path in paths:
                report = Scanner().scan(path)
                self.assertEqual(len(report.findings), 1)
                self.assertEqual(len(report.errors), 1)

    def test_notebook_source_is_never_executed(self):
        marker = self.root / "executed"
        for kind in KINDS:
            with self.subTest(kind=kind):
                findings, errors, _ = self.scan(
                    kind,
                    SETUP,
                    f"open({str(marker)!r}, 'w').write('bad')\ndf.collect()\n",
                )
                self.assertEqual(errors, [])
                self.assertEqual(len(findings), 1)
                self.assertFalse(marker.exists())
