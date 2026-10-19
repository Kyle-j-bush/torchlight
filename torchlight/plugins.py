# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Version 1 explicit, trusted, in-process detector API; no discovery or imports."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from torchlight.detectors import Detector, Diagnostic
from torchlight.diagnostics import Rule
from torchlight.facts import CallFacts, Value

API_VERSION = 1

__all__ = [
    "API_VERSION",
    "CallFacts",
    "Detector",
    "Diagnostic",
    "Plugin",
    "PluginError",
    "Value",
]


class PluginError(RuntimeError):
    """A registered detector failed; a scan must not silently appear clean."""


@dataclass(frozen=True)
class Plugin:
    rule: Rule
    detector: Detector
    api_version: int = API_VERSION

    def __post_init__(self) -> None:
        if type(self.api_version) is not int or self.api_version != API_VERSION:
            raise ValueError(f"unsupported plugin API version: {self.api_version!r}")
        if not isinstance(self.rule, Rule) or any(
            not isinstance(value, str) or not value.strip()
            for value in (
                self.rule.code,
                self.rule.title,
                self.rule.explanation,
                self.rule.recommendation,
            )
        ):
            raise ValueError("plugin rule must be a Rule with nonempty string fields")
        if not re.fullmatch(
            r"[A-Z][A-Z0-9]*[0-9]{3}", self.rule.code
        ) or self.rule.code.startswith("TL"):
            raise ValueError(
                "plugin rule IDs need an uppercase namespace and three digits; TL is reserved"
            )
        if getattr(self.detector, "rule_id", None) != self.rule.code or not callable(
            getattr(self.detector, "check", None)
        ):
            raise ValueError(
                "detector needs a matching rule_id and callable check(facts)"
            )

    def check(self, facts: CallFacts) -> Iterable[Diagnostic]:
        try:
            for diagnostic in self.detector.check(facts):
                if (
                    not isinstance(diagnostic, Diagnostic)
                    or diagnostic.rule_id != self.rule.code
                    or not isinstance(diagnostic.detail, str)
                    or not isinstance(diagnostic.evidence, tuple)
                    or not diagnostic.evidence
                    or any(
                        not isinstance(item, str) or not item.strip()
                        for item in diagnostic.evidence
                    )
                ):
                    raise ValueError(
                        "expected Diagnostic with matching rule_id, nonempty tuple of evidence strings, and string detail"
                    )
                yield diagnostic
        except Exception as exc:
            # Plugin exceptions may contain user data; do not echo their messages.
            raise PluginError(
                f"plugin {self.rule.code} failed ({type(exc).__name__})"
            ) from exc
