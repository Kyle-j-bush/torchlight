# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Internal evidence records and a file-scoped collector; no analysis or rendering."""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal, get_args

from torchlight.diagnostics import Location

type SourceKind = Literal["python", "jupyter", "databricks"]
type NodeKind = Literal[
    "source", "transform", "constraint", "action", "sink", "merge", "loop", "opaque"
]
type EdgeRelation = Literal["receiver", "alternative", "control"]


def _digest(parts: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class GraphArtifact:
    path: str
    source_kind: SourceKind
    id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path:
            raise ValueError("artifact path must be a nonempty string")
        if self.source_kind not in get_args(SourceKind.__value__):
            raise ValueError(f"unsupported source kind: {self.source_kind}")
        object.__setattr__(
            self, "id", "a-" + _digest(["artifact-v1", self.path, self.source_kind])
        )


@dataclass(frozen=True)
class GraphFacts:
    kind: str
    row_limit: int | None = None
    single_partition: Location | None = None
    single_partition_method: Literal["coalesce", "repartition"] | None = None

    def __post_init__(self) -> None:
        if self.row_limit is not None and (
            type(self.row_limit) is not int or self.row_limit < 0
        ):
            raise ValueError("row limit must be a nonnegative integer or None")
        if self.single_partition_method not in {None, "coalesce", "repartition"}:
            raise ValueError("unsupported single-partition method")
        if (self.single_partition is None) != (self.single_partition_method is None):
            raise ValueError("single-partition location and method must be paired")


@dataclass(frozen=True)
class GraphNode:
    id: str
    artifact_id: str
    kind: NodeKind
    label: str
    key: str
    location: Location | None = None
    before: GraphFacts | None = None
    after: GraphFacts | None = None

    def __post_init__(self) -> None:
        if self.kind not in get_args(NodeKind.__value__):
            raise ValueError(f"unsupported node kind: {self.kind}")


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: EdgeRelation

    def __post_init__(self) -> None:
        if self.relation not in get_args(EdgeRelation.__value__):
            raise ValueError(f"unsupported edge relation: {self.relation}")


@dataclass(frozen=True)
class FindingAnchor:
    """Pre-policy anchor; final report finding IDs are assigned after filtering."""

    artifact_id: str
    rule_id: str
    location: Location
    node_id: str | None


@dataclass(frozen=True)
class CaptureLimit:
    artifact_id: str
    max_records: int

    def __post_init__(self) -> None:
        if type(self.max_records) is not int or self.max_records < 1:
            raise ValueError("max_records must be a positive integer")


@dataclass(frozen=True)
class AnalysisGraph:
    artifacts: tuple[GraphArtifact, ...] = ()
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    anchors: tuple[FindingAnchor, ...] = ()
    limits: tuple[CaptureLimit, ...] = ()

    def __post_init__(self) -> None:
        for name in ("artifacts", "nodes", "edges", "anchors", "limits"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        artifacts = {artifact.id for artifact in self.artifacts}
        nodes = {node.id: node for node in self.nodes}
        if len(artifacts) != len(self.artifacts) or len(nodes) != len(self.nodes):
            raise ValueError("graph artifact and node IDs must be unique")
        if any(node.artifact_id not in artifacts for node in self.nodes):
            raise ValueError("node references an unknown artifact")
        if len(set(self.edges)) != len(self.edges):
            raise ValueError("graph edges must be unique")
        for edge in self.edges:
            if edge.source not in nodes or edge.target not in nodes:
                raise ValueError("edge references an unknown node")
            if nodes[edge.source].artifact_id != nodes[edge.target].artifact_id:
                raise ValueError("cross-artifact edges are not supported")
        anchors = set()
        for anchor in self.anchors:
            key = (anchor.artifact_id, anchor.rule_id, anchor.location)
            if key in anchors:
                raise ValueError("finding anchors must be unique")
            anchors.add(key)
            if anchor.artifact_id not in artifacts:
                raise ValueError("finding anchor references an unknown artifact")
            if anchor.node_id is not None and (
                anchor.node_id not in nodes
                or nodes[anchor.node_id].artifact_id != anchor.artifact_id
            ):
                raise ValueError("finding anchor references an unknown or foreign node")
        if len({limit.artifact_id for limit in self.limits}) != len(self.limits):
            raise ValueError("capture limits must be unique per artifact")
        if any(limit.artifact_id not in artifacts for limit in self.limits):
            raise ValueError("capture limit references an unknown artifact")

    @property
    def capture_complete(self) -> bool:
        """Only describes budget truncation, not analysis coverage or Spark safety."""
        return not self.limits


class _GraphCollector:
    """Capture a deterministic traversal prefix, without owning scan findings."""

    def __init__(self, artifact: GraphArtifact, *, max_records: int = 10_000):
        self.artifact = artifact
        # shortcut: budget records per artifact, revisit with real-repository measurements.
        self._limit = CaptureLimit(artifact.id, max_records)
        self._truncated = False
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._anchors: dict[tuple[str, Location], FindingAnchor] = {}
        self._occurrences: Counter[str] = Counter()

    def _reserve(self, count: int) -> bool:
        size = len(self._nodes) + len(self._edges) + len(self._anchors)
        if self._truncated or size + count > self._limit.max_records:
            self._truncated = True
            return False
        return True

    def add_node(
        self,
        kind: NodeKind,
        label: str,
        *,
        structural_key: str,
        location: Location | None = None,
        parents: tuple[tuple[str, EdgeRelation], ...] = (),
        before: GraphFacts | None = None,
        after: GraphFacts | None = None,
    ) -> str | None:
        if kind not in get_args(NodeKind.__value__):
            raise ValueError(f"unsupported node kind: {kind}")
        if not isinstance(structural_key, str) or not structural_key:
            raise ValueError("structural_key must be a nonempty string")
        parents = tuple(sorted(set(parents)))
        for source, relation in parents:
            if source not in self._nodes:
                raise ValueError("parent references an unknown node")
            if relation not in get_args(EdgeRelation.__value__):
                raise ValueError(f"unsupported edge relation: {relation}")
        # Reserve the node and all incoming edges together; never invent a new root.
        if not self._reserve(1 + len(parents)):
            return None
        key = "g1-" + _digest(["node-v1", kind, structural_key])
        occurrence = self._occurrences[key] + 1
        node_id = "n-" + _digest([self.artifact.id, key]) + f"-{occurrence}"
        node = GraphNode(
            node_id, self.artifact.id, kind, label, key, location, before, after
        )
        self._occurrences[key] = occurrence
        self._nodes[node_id] = node
        self._edges.extend(
            GraphEdge(source, node_id, relation) for source, relation in parents
        )
        return node_id

    def anchor(self, rule_id: str, location: Location, node_id: str | None) -> bool:
        if node_id is not None and node_id not in self._nodes:
            raise ValueError("finding anchor references an unknown node")
        key = (rule_id, location)
        if key not in self._anchors and not self._reserve(1):
            return False
        self._anchors[key] = FindingAnchor(self.artifact.id, rule_id, location, node_id)
        return True

    def build(self) -> AnalysisGraph:
        return AnalysisGraph(
            artifacts=(self.artifact,),
            nodes=tuple(self._nodes.values()),
            edges=tuple(self._edges),
            anchors=tuple(self._anchors.values()),
            limits=(self._limit,) if self._truncated else (),
        )
