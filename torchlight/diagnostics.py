# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Stable rule identities and structured, evidence-based findings."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Rule:
    code: str
    title: str
    explanation: str
    recommendation: str


RULES = {
    "TL001": Rule(
        "TL001",
        "Potential driver-memory risk",
        "collect() and toPandas() materialize the entire result in driver memory. "
        "Whether it fits depends on result size, row width, and available memory.",
        "Keep the computation distributed, or explicitly limit the result if partial "
        "data is intended. If the full result is required, verify its memory footprint.",
    ),
    "TL002": Rule(
        "TL002",
        "Potential single-partition write bottleneck",
        "coalesce(1) reduces the input to one partition, limiting write parallelism. "
        "This can be intentional for small exports.",
        "Remove coalesce(1) or choose suitable partitioning for large outputs. "
        "Keep it only when a small, single-partition export is intentional.",
    ),
    "TL003": Rule(
        "TL003",
        "Loop-carried withColumn() can grow the logical plan",
        "Repeatedly assigning withColumn() back to the same DataFrame in a loop "
        "can build a large nested projection plan and increase planning overhead.",
        "Consider constructing the expressions together with select() or withColumns(). "
        "Preserve dependencies between columns; this is not a safe automatic rewrite.",
    ),
}


@dataclass(frozen=True)
class Location:
    line: int
    column: int = 1
    cell: int | None = None

    def describe(self) -> str:
        prefix = f"cell {self.cell}, " if self.cell is not None else ""
        return f"{prefix}line {self.line}"


@dataclass(frozen=True)
class Finding:
    path: str
    rule_id: str
    location: Location
    end_line: int
    message: str
    evidence: tuple[str, ...]
    snippet: str

    @property
    def rule(self) -> Rule:
        return RULES[self.rule_id]

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "rule_id": self.rule_id,
            "severity": "warning",
            **asdict(self.location),
            "end_line": self.end_line,
            "message": self.message,
            "evidence": list(self.evidence),
            "explanation": self.rule.explanation,
            "recommendation": self.rule.recommendation,
            "snippet": self.snippet,
        }

    def __str__(self) -> str:
        location = self.location
        position = (
            f"cell {location.cell},line {location.line}"
            if location.cell is not None
            else str(location.line)
        )
        evidence = "\n".join(f"  Evidence: {item}" for item in self.evidence)
        return (
            f"{self.path}:{position}: {self.rule_id}: {self.message}\n"
            f"{evidence}\n"
            f"  Review: {self.rule.recommendation}"
        )
