# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Internal immutable Spark facts; no detector performs receiver inference."""

from dataclasses import dataclass

from torchlight.diagnostics import Location


@dataclass(frozen=True)
class Value:
    kind: str
    origin: str
    row_limit: int | None = None
    single_partition: Location | None = None
    # Identity on entry to a possibly repeated loop. Fresh reads drop it.
    loop_origins: frozenset[tuple[int, str]] = frozenset()


@dataclass(frozen=True)
class CallFacts:
    receiver: Value
    method: str
    terminal_write: bool = False
    carries_loop_frame: bool = False
