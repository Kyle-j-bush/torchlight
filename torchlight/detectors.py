# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Internal detectors consume resolved facts, not Python syntax or mutable state.

This interface is intentionally not a public plugin API yet.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from torchlight.facts import CallFacts


@dataclass(frozen=True)
class Diagnostic:
    rule_id: str
    evidence: tuple[str, ...]
    detail: str = ""


class Detector(Protocol):
    rule_id: str

    def check(self, facts: CallFacts) -> Iterable[Diagnostic]: ...


class UnboundedMaterialization:
    rule_id = "TL001"

    def check(self, facts: CallFacts) -> Iterable[Diagnostic]:
        value = facts.receiver
        if (
            value.kind == "frame"
            and facts.method in {"collect", "toPandas"}
            and value.row_limit is None
        ):
            yield Diagnostic(
                self.rule_id,
                (value.origin, "No explicit row limit recognized."),
                f" from .{facts.method}()",
            )


class CoalescedWrite:
    rule_id = "TL002"

    def check(self, facts: CallFacts) -> Iterable[Diagnostic]:
        value = facts.receiver
        if (
            facts.terminal_write
            and value.single_partition is not None
            and value.single_partition_method == "coalesce"
        ):
            yield Diagnostic(
                self.rule_id,
                (
                    value.origin,
                    f"coalesce(1) at {value.single_partition.describe()} feeds this write; "
                    "no operation recognized that restores multiple output partitions.",
                ),
            )


class LoopCarriedProjection:
    rule_id = "TL003"

    def check(self, facts: CallFacts) -> Iterable[Diagnostic]:
        if (
            facts.receiver.kind == "frame"
            and facts.method == "withColumn"
            and facts.carries_loop_frame
        ):
            yield Diagnostic(
                self.rule_id,
                (
                    facts.receiver.origin,
                    "The assignment carries this DataFrame forward through a potentially "
                    "repeated loop; it is not reset to a fresh DataFrame first.",
                ),
            )


class RepartitionedWrite:
    rule_id = "TL004"

    def check(self, facts: CallFacts) -> Iterable[Diagnostic]:
        value = facts.receiver
        if (
            facts.terminal_write
            and value.single_partition is not None
            and value.single_partition_method == "repartition"
        ):
            yield Diagnostic(
                self.rule_id,
                (
                    value.origin,
                    f"repartition(1) at {value.single_partition.describe()} feeds this write; "
                    "no operation recognized that restores multiple output partitions.",
                ),
            )


class EagerLocalIterator:
    rule_id = "TL005"

    def check(self, facts: CallFacts) -> Iterable[Diagnostic]:
        value = facts.receiver
        if (
            value.kind == "local_iterator"
            and facts.method in {"list", "tuple"}
            and value.row_limit is None
        ):
            yield Diagnostic(
                self.rule_id,
                (
                    value.origin,
                    f"Built-in {facts.method}() consumes a known Spark toLocalIterator(); no explicit row limit recognized.",
                ),
                f" via {facts.method}()",
            )


DETECTORS: tuple[Detector, ...] = (
    UnboundedMaterialization(),
    CoalescedWrite(),
    LoopCarriedProjection(),
    RepartitionedWrite(),
    EagerLocalIterator(),
)
