# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Conservative, local Spark DataFrame analysis without importing or executing Spark."""

import ast
from dataclasses import dataclass, replace

from torchlight.detectors import DETECTORS
from torchlight.diagnostics import RULES, Finding, Location
from torchlight.facts import CallFacts, Value
from torchlight.graph import GraphFacts, NodeKind, _GraphCollector
from torchlight.identity import call_key
from torchlight.plugins import Plugin

PARSE_FLAGS = ast.PyCF_ONLY_AST | ast.PyCF_ALLOW_TOP_LEVEL_AWAIT


def parse_source(source: str, filename: str) -> ast.Module:
    """Parse Python source, allowing top-level await as Jupyter notebooks do."""
    return compile(source, filename, "exec", flags=PARSE_FLAGS, dont_inherit=True)


def format_syntax_error(exc: Exception) -> str:
    """Include the line number for syntax errors; otherwise use the error text."""
    if isinstance(exc, SyntaxError):
        return f"syntax error: {exc.msg} (line {exc.lineno})"
    return str(exc)


# Only known APIs propagate DataFrame identity. Unknown calls do not become Spark
# calls just because their receiver or variable happens to be named "df".
FRAME_METHODS = {
    "alias",
    "cache",
    "checkpoint",
    "coalesce",
    "distinct",
    "drop",
    "dropDuplicates",
    "drop_duplicates",
    "dropna",
    "fillna",
    "filter",
    "hint",
    "join",
    "limit",
    "localCheckpoint",
    "offset",
    "orderBy",
    "persist",
    "repartition",
    "repartitionByRange",
    "replace",
    "sample",
    "select",
    "selectExpr",
    "sort",
    "sortWithinPartitions",
    "subtract",
    "toDF",
    "union",
    "unionAll",
    "unionByName",
    "unpersist",
    "where",
    "withColumn",
    "withColumnRenamed",
    "withColumns",
    "withColumnsRenamed",
    "withMetadata",
    "withWatermark",
}
SHUFFLING_METHODS = {
    "distinct",
    "dropDuplicates",
    "drop_duplicates",
    "join",
    "orderBy",
    "repartition",
    "repartitionByRange",
    "subtract",
    "sort",
    "union",
    "unionAll",
    "unionByName",
}
EXPANDING_METHODS = {
    "join",
    "sample",
    "selectExpr",
    "union",
    "unionAll",
    "unionByName",
}
READ_METHODS = {"csv", "jdbc", "json", "load", "orc", "parquet", "table", "text"}
WRITE_METHODS = {
    "csv",
    "insertInto",
    "jdbc",
    "json",
    "orc",
    "parquet",
    "save",
    "saveAsTable",
    "text",
    "xml",
}
WRITE_OPTIONS = {
    "bucketBy",
    "clusterBy",
    "format",
    "mode",
    "option",
    "options",
    "partitionBy",
    "sortBy",
}
V2_WRITE_METHODS = {
    "append",
    "create",
    "createOrReplace",
    "overwrite",
    "overwritePartitions",
    "replace",
}
# Graph roles only; recognizing an action does not infer its return value.
FRAME_ACTIONS = {
    "collect",
    "count",
    "first",
    "foreach",
    "foreachPartition",
    "head",
    "isEmpty",
    "show",
    "tail",
    "take",
    "toLocalIterator",
    "toPandas",
}
GENERATORS = {
    "explode",
    "explode_outer",
    "posexplode",
    "posexplode_outer",
    "inline",
    "inline_outer",
}


class Bindings(ast.NodeVisitor):
    """Collect bindings in one scope, without descending into nested scopes."""

    def __init__(self):
        self.names: set[str] = set()
        self.external: set[str] = set()

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_Import(self, node):
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node):
        for alias in node.names:
            self.names.add(alias.asname or alias.name)

    def visit_FunctionDef(self, node):
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Lambda(self, node):
        pass

    def visit_Global(self, node):
        self.external.update(node.names)

    visit_Nonlocal = visit_Global

    def visit_ExceptHandler(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node):
        if node.name:
            self.names.add(node.name)

    def visit_MatchMapping(self, node):
        if node.rest:
            self.names.add(node.rest)
        self.generic_visit(node)

    def visit_ListComp(self, node):
        # Comprehension targets do not leak into their enclosing scope.
        pass

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


def literal_integer(node: ast.expr) -> int | None:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = literal_integer(node.operand)
        return -value if value is not None else None
    return None


def integer_argument(node: ast.Call, keyword: str) -> int | None:
    argument = (
        node.args[0]
        if node.args
        else next((kw.value for kw in node.keywords if kw.arg == keyword), None)
    )
    return literal_integer(argument) if argument is not None else None


@dataclass(frozen=True, slots=True)
class _TrackedValue:
    """Keep private trace endpoints separate from plugin-visible semantic facts."""

    value: Value
    trace: str | None = None


def _graph_facts(value: Value | None) -> GraphFacts | None:
    if value is None:
        return None
    return GraphFacts(
        value.kind,
        value.row_limit,
        value.single_partition,
        value.single_partition_method if value.single_partition is not None else None,
    )


class SparkAnalyzer(ast.NodeVisitor):
    """Track known Spark values within a file or notebook, in document order.

    Analysis is deliberately not interprocedural. Unrecognized APIs, attributes,
    and branch-dependent types lose identity rather than guessing a Spark type.
    """

    def __init__(
        self,
        path: str,
        assume_sessions: tuple[str, ...] = (),
        *,
        plugins: tuple[Plugin, ...] = (),
        _collector: _GraphCollector | None = None,
    ):
        self.path = path
        self._collector = _collector
        self.detectors = (*DETECTORS, *plugins)
        self.rules = {**RULES, **{plugin.rule.code: plugin.rule for plugin in plugins}}
        self.state: dict[str, _TrackedValue] = {
            name: _TrackedValue(Value("materializer", name))
            for name in ("list", "tuple")
        }
        self.state.update(
            {
                name: _TrackedValue(
                    Value("session", f"Explicitly assumed SparkSession '{name}'")
                )
                for name in assume_sessions
            }
        )
        self.source = ""
        self.lines: list[str] = []
        self.cell: int | None = None
        self.findings: list[Finding] = []
        self.loop_ids: list[int] = []
        self.next_loop_id = 0
        self.assignment_targets: set[str] = set()
        self.class_globals: dict[str, _TrackedValue] | None = None
        self.parents: dict[ast.AST, ast.AST] = {}

    def analyze(
        self, tree: ast.Module, source: str, cell: int | None = None
    ) -> list[Finding]:
        if source is not self.source:
            self.lines = source.splitlines()
        self.source, self.cell = source, cell
        self.findings = []
        self.parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        self._block(tree.body)
        unique = {(f.rule_id, f.location): f for f in self.findings}
        return sorted(
            unique.values(),
            key=lambda f: (f.location.line, f.location.column, f.rule_id),
        )

    def forget(self) -> None:
        """Discard stale knowledge after an unparseable or opaque notebook cell."""
        self.state.clear()

    def _location(self, node: ast.AST) -> Location:
        # AST columns are UTF-8 byte offsets; diagnostics use character columns.
        line = self.lines[node.lineno - 1]
        column = len(line.encode("utf-8")[: node.col_offset].decode("utf-8")) + 1
        return Location(node.lineno, column, self.cell)

    def _origin(self, node: ast.AST, description: str) -> str:
        return f"{description} ({self._location(node).describe()})"

    def _trace(
        self,
        node: ast.AST,
        kind: NodeKind,
        label: str,
        before: _TrackedValue | None,
        after: Value | None,
    ) -> str | None:
        if self._collector is None:
            return None
        parents = ()
        if before is not None:
            if before.trace is not None:
                parents = ((before.trace, "receiver"),)
            elif kind != "source":
                label += "; prior trace unavailable"
        return self._collector.add_node(
            kind,
            label,
            structural_key=call_key(node, self.parents),
            location=self._location(node),
            parents=parents,
            before=_graph_facts(before.value if before is not None else None),
            after=_graph_facts(after),
        )

    def _emit(self, code: str, node: ast.Call, evidence: tuple[str, ...], detail=""):
        message = self.rules[code].title + detail
        self.findings.append(
            Finding(
                self.path,
                code,
                self._location(node),
                node.end_lineno or node.lineno,
                message,
                evidence,
                self.lines[node.lineno - 1].strip(),
                custom_rule=self.rules[code] if code not in RULES else None,
                structural_key=call_key(node, self.parents),
            )
        )

    def visit(self, node):
        if isinstance(node, ast.expr):
            return self._expr(node)
        return super().visit(node)

    def _block(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            self.visit(statement)
            if isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                break

    def _bind(self, target: ast.expr, value: _TrackedValue | None = None) -> None:
        if isinstance(target, ast.Name):
            if value is None:
                self.state.pop(target.id, None)
            else:
                self.state[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._bind(item)
        elif isinstance(target, ast.Starred):
            self._bind(target.value)
        else:
            self._expr(target)

    def visit_Import(self, node):
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            module = alias.name if alias.asname else alias.name.split(".")[0]
            value = (
                _TrackedValue(Value("module", module))
                if module.startswith("pyspark")
                else None
            )
            self._bind(ast.Name(id=name), value)

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name == "*":
                self.forget()
                continue
            value = None
            if not node.level and node.module and node.module.startswith("pyspark"):
                value = self._attribute(
                    _TrackedValue(Value("module", node.module)), alias.name
                )
            self._bind(ast.Name(id=alias.asname or alias.name), value)

    def _attribute(
        self, tracked: _TrackedValue | None, name: str
    ) -> _TrackedValue | None:
        if tracked is None:
            return None
        value = tracked.value
        if value.kind == "module":
            symbol = f"{value.origin}.{name}"
            if value.origin == "pyspark.sql.functions" and name in GENERATORS:
                return _TrackedValue(Value("generator", symbol))
            if symbol in {
                "pyspark.sql.SparkSession",
                "pyspark.sql.session.SparkSession",
                "pyspark.sql.connect.session.SparkSession",
            }:
                return _TrackedValue(Value("session_type", symbol))
            if symbol in {
                "pyspark.sql.DataFrame",
                "pyspark.sql.dataframe.DataFrame",
                "pyspark.sql.connect.dataframe.DataFrame",
            }:
                return _TrackedValue(Value("frame_type", symbol))
            if symbol in {
                "pyspark.sql",
                "pyspark.sql.session",
                "pyspark.sql.dataframe",
                "pyspark.sql.functions",
                "pyspark.sql.connect",
                "pyspark.sql.connect.session",
                "pyspark.sql.connect.dataframe",
            }:
                return _TrackedValue(Value("module", symbol))
        if value.kind == "session_type" and name == "builder":
            return _TrackedValue(Value("builder", value.origin), tracked.trace)
        if value.kind == "session" and name in {"read", "readStream"}:
            return _TrackedValue(Value("reader", value.origin), tracked.trace)
        if value.kind == "frame":
            if name == "write":
                return _TrackedValue(replace(value, kind="writer"), tracked.trace)
            if name == "na":
                return _TrackedValue(replace(value, kind="frame_na"), tracked.trace)
        return None

    def _expr(self, node: ast.expr | None) -> _TrackedValue | None:
        if node is None:
            return None
        if isinstance(node, ast.Name):
            return self.state.get(node.id)
        if isinstance(node, ast.Attribute):
            receiver = self._expr(node.value)
            result = self._attribute(receiver, node.attr)
            if (
                self._collector is not None
                and receiver is not None
                and receiver.value.kind == "frame"
            ):
                trace = self._trace(
                    node,
                    "transform" if result is not None else "opaque",
                    f".{node.attr}"
                    if result is not None
                    else f".{node.attr}; attribute result not tracked",
                    receiver,
                    result.value if result is not None else None,
                )
                if result is not None:
                    result = _TrackedValue(result.value, trace)
            return result
        if isinstance(node, ast.Call):
            receiver = None
            if isinstance(node.func, ast.Attribute):
                receiver = self._expr(node.func.value)
                function = self._attribute(receiver, node.func.attr)
            else:
                function = self._expr(node.func)
            arguments = [
                self._expr(argument)
                for argument in [*node.args, *(kw.value for kw in node.keywords)]
            ]
            if function and function.value.kind == "session_type":
                value = Value("session", self._origin(node, "SparkSession constructor"))
                return _TrackedValue(
                    value,
                    self._trace(
                        node, "source", "SparkSession constructor", None, value
                    ),
                )
            if (
                function
                and function.value.kind == "materializer"
                and len(node.args) == 1
                and not node.keywords
                and arguments[0] is not None
            ):
                return self._method(arguments[0], function.value.origin, node)
            if receiver is not None:
                return self._method(receiver, node.func.attr, node)
            # shortcut: free calls lack boundary nodes, add with slice 05 opacity capture.
            return None
        if isinstance(node, ast.NamedExpr):
            previous = self.assignment_targets
            self.assignment_targets = {node.target.id}
            value = self._expr(node.value)
            self.assignment_targets = previous
            self._bind(node.target, value)
            return value
        if isinstance(node, ast.IfExp):
            self._expr(node.test)
            if isinstance(node.test, ast.Constant):
                return self._expr(node.body if node.test.value else node.orelse)
            initial = self.state.copy()
            left = self._expr(node.body)
            left_state = self.state.copy()
            self.state = initial
            right = self._expr(node.orelse)
            self.state = self._merge(left_state, self.state)
            return self._merge_value(left, right)
        if isinstance(node, ast.BoolOp):
            branches = []
            for index, expression in enumerate(node.values):
                self._expr(expression)
                if isinstance(expression, ast.Constant):
                    stops = (isinstance(node.op, ast.And) and not expression.value) or (
                        isinstance(node.op, ast.Or) and expression.value
                    )
                    if stops:
                        branches.append(self.state.copy())
                        break
                if index == len(node.values) - 1 or not isinstance(
                    expression, ast.Constant
                ):
                    branches.append(self.state.copy())
            self.state = self._merge(*branches)
            return None
        if isinstance(node, ast.Lambda):
            state = self.state.copy()
            loops, targets = self.loop_ids, self.assignment_targets
            self.loop_ids, self.assignment_targets = [], set()
            self._parameters(node.args)
            self._expr(node.body)
            self.state, self.loop_ids, self.assignment_targets = state, loops, targets
            return None
        if isinstance(
            node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        ):
            state = self.state.copy()
            for generator in node.generators:
                self._expr(generator.iter)
                self._bind(generator.target)
                for condition in generator.ifs:
                    self._expr(condition)
            if isinstance(node, ast.DictComp):
                self._expr(node.key)
                self._expr(node.value)
            else:
                self._expr(node.elt)
            self.state = state
            return None
        for child in ast.iter_child_nodes(node):
            self.visit(child)
        return None

    def _method(
        self, tracked: _TrackedValue, name: str, node: ast.Call
    ) -> _TrackedValue | None:
        value = tracked.value
        facts = CallFacts(
            receiver=value,
            method=name,
            terminal_write=(value.kind == "writer" and name in WRITE_METHODS)
            or (value.kind == "writer_v2" and name in V2_WRITE_METHODS),
            carries_loop_frame=any(
                (loop, target) in value.loop_origins
                for loop in self.loop_ids
                for target in self.assignment_targets
            ),
        )
        start = len(self.findings)
        for detector in self.detectors:
            for diagnostic in detector.check(facts):
                self._emit(
                    diagnostic.rule_id, node, diagnostic.evidence, diagnostic.detail
                )
        result = self._method_result(tracked, name, node)
        if self._collector is not None:
            emitted = self.findings[start:]
            trace = self._trace_call(node, facts, tracked, result, bool(emitted))
            for finding in emitted:
                self._collector.anchor(finding.rule_id, finding.location, trace)
            if result is not None:
                result = _TrackedValue(result.value, trace)
        return result

    def _trace_call(
        self,
        node: ast.Call,
        facts: CallFacts,
        tracked: _TrackedValue,
        result: _TrackedValue | None,
        has_findings: bool,
    ) -> str | None:
        value, name = facts.receiver, facts.method
        label = f".{name}()"
        if result is not None and (
            value.kind in {"session", "reader"}
            and result.value.kind == "frame"
            or value.kind in {"builder", "session_type"}
            and result.value.kind == "session"
        ):
            kind = "source"
            label = (
                "Spark reader" if value.kind == "reader" else "SparkSession"
            ) + f" {label}"
        elif facts.terminal_write:
            kind = "sink"
        elif value.kind == "frame" and name in FRAME_ACTIONS:
            kind = "action"
        elif value.kind == "local_iterator" and name in {"list", "tuple"}:
            kind = "action"
            label = f"Built-in {name}(); eager iterator materialization"
        elif (
            value.kind in {"frame", "grouped", "frame_na", "writer", "writer_v2"}
            or has_findings
        ):
            kind = "transform" if result is not None else "opaque"
            if result is not None and name in {
                "limit",
                "coalesce",
                "repartition",
                "repartitionByRange",
            }:
                kind = "constraint"
            if result is None:
                label += "; return value not tracked"
        else:
            return result.trace if result is not None else None
        if value.kind == "frame" and name in {
            "join",
            "union",
            "unionAll",
            "unionByName",
            "subtract",
        }:
            label += "; receiver path only; other inputs untracked"
        return self._trace(
            node, kind, label, tracked, result.value if result is not None else None
        )

    def _method_result(
        self, tracked: _TrackedValue, name: str, node: ast.Call
    ) -> _TrackedValue | None:
        value = tracked.value
        if value.kind == "builder":
            if name in {"getOrCreate", "create"}:
                return _TrackedValue(
                    Value("session", self._origin(node, "SparkSession builder"))
                )
            if name in {"appName", "config", "enableHiveSupport", "master", "remote"}:
                return tracked
        if value.kind == "session_type" and name in {
            "getActiveSession",
            "getDefaultSession",
        }:
            return _TrackedValue(
                Value("session", self._origin(node, "SparkSession lookup"))
            )
        if value.kind == "session":
            if name in {"createDataFrame", "range", "sql", "table"}:
                origin = self._origin(node, f"SparkSession.{name}()")
                return _TrackedValue(
                    Value("frame", f"{origin}; session: {value.origin}")
                )
            if name == "newSession":
                return tracked
        if value.kind == "reader":
            if name in READ_METHODS:
                origin = self._origin(node, f"Spark reader .{name}()")
                return _TrackedValue(
                    Value("frame", f"{origin}; session: {value.origin}")
                )
            if name in {"format", "option", "options", "schema"}:
                return tracked
        if value.kind == "writer":
            if name in WRITE_OPTIONS:
                return tracked
        if value.kind == "writer_v2":
            if name in {
                "using",
                "option",
                "options",
                "partitionedBy",
                "clusterBy",
                "tableProperty",
            }:
                return tracked
        if value.kind == "grouped" and name in {
            "agg",
            "avg",
            "count",
            "max",
            "mean",
            "min",
            "pivot",
            "sum",
        }:
            return (
                tracked
                if name == "pivot"
                else _TrackedValue(replace(value, kind="frame"), tracked.trace)
            )
        if value.kind == "frame_na" and name in {"drop", "fill", "replace"}:
            return _TrackedValue(replace(value, kind="frame"), tracked.trace)
        if value.kind != "frame":
            return None
        if name in {"collect", "toPandas"}:
            return None
        if name == "toLocalIterator":
            return _TrackedValue(
                replace(
                    value,
                    kind="local_iterator",
                    origin=f"{value.origin}; {self._origin(node, 'Spark .toLocalIterator()')}",
                ),
                tracked.trace,
            )
        if name == "writeTo":
            return _TrackedValue(replace(value, kind="writer_v2"), tracked.trace)
        if name in {"groupBy", "groupby", "rollup", "cube"}:
            return _TrackedValue(
                replace(value, kind="grouped", row_limit=None, single_partition=None),
                tracked.trace,
            )
        if name == "agg":
            return _TrackedValue(
                replace(value, row_limit=1, single_partition=None), tracked.trace
            )
        if name not in FRAME_METHODS:
            return None
        bound, single = value.row_limit, value.single_partition
        partition_method = value.single_partition_method
        if name in EXPANDING_METHODS or self._has_generator(node):
            bound = None
        if name == "sample":
            replacement = next(
                (kw.value for kw in node.keywords if kw.arg == "withReplacement"),
                node.args[0] if node.args else ast.Constant(value=False),
            )
            if isinstance(replacement, ast.Constant) and replacement.value is False:
                bound = value.row_limit
        if name == "limit":
            limit = integer_argument(node, "num")
            if limit is not None and limit >= 0:
                bound = limit if bound is None else min(bound, limit)
        if name in SHUFFLING_METHODS:
            # Repartitioning back to one partition does not remove this bottleneck.
            if (
                name not in {"repartition", "repartitionByRange"}
                or integer_argument(node, "numPartitions") != 1
            ):
                single = None
        if name == "repartition" and integer_argument(node, "numPartitions") == 1:
            if single is None:
                single = self._location(node)
                partition_method = "repartition"
        if name == "coalesce":
            if integer_argument(node, "numPartitions") == 1:
                single = self._location(node)
                partition_method = "coalesce"
        return _TrackedValue(
            replace(
                value,
                row_limit=bound,
                single_partition=single,
                single_partition_method=partition_method,
            ),
            tracked.trace,
        )

    def _has_generator(self, node: ast.Call) -> bool:
        for argument in [*node.args, *(kw.value for kw in node.keywords)]:
            for child in ast.walk(argument):
                if isinstance(child, ast.Call):
                    name = (
                        child.func.attr
                        if isinstance(child.func, ast.Attribute)
                        else (child.func.id if isinstance(child.func, ast.Name) else "")
                    )
                    alias = self.state.get(name)
                    if name in GENERATORS or (
                        alias is not None and alias.value.kind == "generator"
                    ):
                        return True
        return False

    def visit_Assign(self, node):
        previous = self.assignment_targets
        self.assignment_targets = {
            t.id for t in node.targets if isinstance(t, ast.Name)
        }
        value = self._expr(node.value)
        self.assignment_targets = previous
        for target in node.targets:
            self._bind(target, value)

    def _annotation(
        self, annotation: ast.expr | None, node: ast.AST
    ) -> _TrackedValue | None:
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            try:
                annotation = ast.parse(annotation.value, mode="eval").body
            except SyntaxError:
                return None
        if isinstance(annotation, ast.Name):
            tracked = self.state.get(annotation.id)
        elif isinstance(annotation, ast.Attribute):

            def resolve(item):
                if isinstance(item, ast.Name):
                    return self.state.get(item.id)
                if isinstance(item, ast.Attribute):
                    return self._attribute(resolve(item.value), item.attr)
                return None

            tracked = resolve(annotation)
        else:
            return None
        if tracked and tracked.value.kind in {"frame_type", "session_type"}:
            value = tracked.value
            kind = "frame" if value.kind == "frame_type" else "session"
            value = Value(kind, self._origin(node, f"Annotated as {value.origin}"))
            return _TrackedValue(
                value,
                self._trace(
                    node,
                    "source",
                    "Annotated DataFrame (not a traced read)"
                    if kind == "frame"
                    else "Annotated SparkSession",
                    None,
                    value,
                ),
            )
        return None

    def visit_AnnAssign(self, node):
        previous = self.assignment_targets
        self.assignment_targets = (
            {node.target.id} if isinstance(node.target, ast.Name) else set()
        )
        value = self._expr(node.value)
        self.assignment_targets = previous
        self._bind(node.target, value or self._annotation(node.annotation, node))

    def visit_AugAssign(self, node):
        self._expr(node.value)
        self._bind(node.target)

    def visit_Delete(self, node):
        for target in node.targets:
            self._bind(target)

    def visit_TypeAlias(self, node):
        self._bind(node.name)

    @staticmethod
    def _merge_value(
        left: _TrackedValue | None, right: _TrackedValue | None
    ) -> _TrackedValue | None:
        if left is None or right is None or left.value.kind != right.value.kind:
            return None
        # shortcut: distinct traces have no endpoint until slice 05 adds merge nodes.
        trace = left.trace if left.trace == right.trace else None
        left, right = left.value, right.value
        if left.kind not in {"frame", "grouped", "writer", "writer_v2", "frame_na"}:
            return _TrackedValue(left, trace) if left == right else None
        bound = None
        if left.row_limit is not None and right.row_limit is not None:
            bound = max(left.row_limit, right.row_limit)
        return _TrackedValue(
            replace(
                left,
                origin=left.origin
                if left.origin == right.origin
                else "Spark DataFrame on all analyzed paths",
                row_limit=bound,
                single_partition=left.single_partition
                if left.single_partition == right.single_partition
                and left.single_partition_method == right.single_partition_method
                else None,
                loop_origins=left.loop_origins & right.loop_origins,
            ),
            trace,
        )

    @classmethod
    def _merge(cls, *states: dict[str, _TrackedValue]) -> dict[str, _TrackedValue]:
        result = states[0].copy()
        for state in states[1:]:
            for name in list(result):
                value = cls._merge_value(result[name], state.get(name))
                if value is None:
                    del result[name]
                else:
                    result[name] = value
        return result

    def visit_If(self, node):
        self._expr(node.test)
        if isinstance(node.test, ast.Constant):
            self._block(node.body if node.test.value else node.orelse)
            return
        initial = self.state.copy()
        self._block(node.body)
        left = self.state.copy()
        self.state = initial
        self._block(node.orelse)
        self.state = self._merge(left, self.state)

    def _loop(self, node, repetitions: int | None):
        initial = self.state.copy()
        if repetitions == 0:
            self._block(node.orelse)
            return
        if isinstance(node, (ast.For, ast.AsyncFor)):
            self._bind(node.target)
        loop_id = self.next_loop_id
        self.next_loop_id += 1
        repeated = repetitions != 1 and not any(
            isinstance(s, ast.Break) for s in node.body
        )
        if repeated:
            self.loop_ids.append(loop_id)
            self.state = {
                name: _TrackedValue(
                    replace(
                        tracked.value,
                        loop_origins=tracked.value.loop_origins | {(loop_id, name)},
                    ),
                    tracked.trace,
                )
                if tracked.value.kind == "frame"
                else tracked
                for name, tracked in self.state.items()
            }
        self._block(node.body)
        if repeated:
            self.loop_ids.pop()
            self.state = {
                name: _TrackedValue(
                    replace(
                        tracked.value,
                        loop_origins=frozenset(
                            token
                            for token in tracked.value.loop_origins
                            if token[0] != loop_id
                        ),
                    ),
                    tracked.trace,
                )
                for name, tracked in self.state.items()
            }
        if repetitions is None or repetitions == 0:
            self.state = self._merge(initial, self.state)
        self._block(node.orelse)

    def visit_For(self, node):
        self._expr(node.iter)
        repetitions = None
        if isinstance(node.iter, (ast.List, ast.Tuple)) and not any(
            isinstance(element, ast.Starred) for element in node.iter.elts
        ):
            repetitions = len(node.iter.elts)
        elif isinstance(node.iter, ast.Set) and all(
            isinstance(element, ast.Constant) for element in node.iter.elts
        ):
            repetitions = len({element.value for element in node.iter.elts})
        elif (
            isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Name)
            and node.iter.func.id == "range"
            and "range" not in self.state
            and not node.iter.keywords
        ):
            args = [literal_integer(arg) for arg in node.iter.args]
            if args and all(arg is not None for arg in args):
                try:
                    repetitions = len(range(*args))
                except (TypeError, ValueError, OverflowError):
                    pass
        self._loop(node, repetitions)

    visit_AsyncFor = visit_For

    def visit_While(self, node):
        self._expr(node.test)
        repetitions = (
            0 if isinstance(node.test, ast.Constant) and not node.test.value else None
        )
        self._loop(node, repetitions)

    def _parameters(self, arguments: ast.arguments):
        parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        if arguments.vararg:
            parameters.append(arguments.vararg)
        if arguments.kwarg:
            parameters.append(arguments.kwarg)
        annotated = {p.arg: self._annotation(p.annotation, p) for p in parameters}
        for parameter in parameters:
            # *args: DataFrame annotates each element, not the tuple/dict itself.
            value = (
                annotated[parameter.arg]
                if parameter
                in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
                else None
            )
            self._bind(ast.Name(id=parameter.arg), value)

    def visit_FunctionDef(self, node):
        for expression in [
            *node.decorator_list,
            *node.args.defaults,
            *(d for d in node.args.kw_defaults if d is not None),
        ]:
            self._expr(expression)
        self.state.pop(node.name, None)
        outer = self.state.copy()
        self.state = (
            self.class_globals if self.class_globals is not None else outer
        ).copy()
        bindings = Bindings()
        for statement in node.body:
            bindings.visit(statement)
        for name in bindings.names - bindings.external:
            self.state.pop(name, None)
        self._parameters(node.args)
        loops, targets, class_globals = (
            self.loop_ids,
            self.assignment_targets,
            self.class_globals,
        )
        self.loop_ids, self.assignment_targets, self.class_globals = [], set(), None
        self._block(node.body)
        self.state = outer
        self.loop_ids, self.assignment_targets, self.class_globals = (
            loops,
            targets,
            class_globals,
        )

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        for expression in [
            *node.decorator_list,
            *node.bases,
            *(kw.value for kw in node.keywords),
        ]:
            self._expr(expression)
        outer, class_globals = self.state.copy(), self.class_globals
        self.class_globals = class_globals if class_globals is not None else outer
        self.state = outer.copy()
        loops, targets = self.loop_ids, self.assignment_targets
        self.loop_ids, self.assignment_targets = [], set()
        self._block(node.body)
        self.state, self.class_globals = outer, class_globals
        self.loop_ids, self.assignment_targets = loops, targets
        self.state.pop(node.name, None)

    def visit_With(self, node):
        for item in node.items:
            value = self._expr(item.context_expr)
            if item.optional_vars:
                self._bind(item.optional_vars, value)
        self._block(node.body)

    visit_AsyncWith = visit_With

    def visit_Try(self, node):
        initial = self.state.copy()
        self._block(node.body)
        self._block(node.orelse)
        branches = [self.state.copy()]
        bindings = Bindings()
        for statement in node.body:
            bindings.visit(statement)
        for handler in node.handlers:
            self.state = {k: v for k, v in initial.items() if k not in bindings.names}
            if handler.name:
                self.state.pop(handler.name, None)
            self._block(handler.body)
            if handler.name:
                self.state.pop(handler.name, None)
            branches.append(self.state.copy())
        self.state = self._merge(*branches)
        self._block(node.finalbody)

    visit_TryStar = visit_Try

    def visit_Match(self, node):
        self._expr(node.subject)
        initial = self.state.copy()
        branches = []
        exhaustive = False
        for case in node.cases:
            self.state = initial.copy()
            bindings = Bindings()
            bindings.visit(case.pattern)
            for name in bindings.names:
                self.state.pop(name, None)
            self._expr(case.guard)
            self._block(case.body)
            branches.append(self.state.copy())
            if (
                isinstance(case.pattern, ast.MatchAs)
                and case.pattern.pattern is None
                and case.guard is None
            ):
                exhaustive = True
        self.state = self._merge(*(branches if exhaustive else [initial, *branches]))
