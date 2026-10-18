# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""One immutable project policy per CLI invocation, using only the standard library."""

import keyword
import os
import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

from torchlight.diagnostics import RULES

CONFIG_KEYS = {"select", "ignore", "exclude", "assume-spark-session", "baseline"}


class ConfigError(ValueError):
    """Invalid or unreadable project policy; scanning must not proceed."""


def valid_session_name(value: str) -> bool:
    return value.isidentifier() and not keyword.iskeyword(value)


def validate_pattern(pattern: str) -> str:
    """Validate a portable, project-relative glob without filesystem access."""
    parts = pattern.removesuffix("/").split("/")
    if (
        not pattern
        or "\\" in pattern
        or ":" in pattern
        or any(part in {"", ".", ".."} for part in parts)
        or any("**" in part and part != "**" for part in parts)
    ):
        raise ConfigError(
            "exclude patterns must be relative forward-slash globs without '.' or '..'; "
            "'**' must occupy a whole path segment"
        )
    return pattern


def _matches(
    parts: tuple[str, ...], pattern: str, *, is_directory: bool = False
) -> bool:
    """Match a path or an ancestor; '**' spans zero or more complete segments."""
    segments = pattern.removesuffix("/").split("/")
    if len(segments) == 1:
        segments.insert(0, "**")  # Basename patterns apply at any depth.
    positions = {0}
    for segment in segments:
        if not positions:
            return False
        if segment == "**":
            positions = set(range(min(positions), len(parts) + 1))
        else:
            positions = {
                index + 1
                for index in positions
                if index < len(parts) and fnmatchcase(parts[index], segment)
            }
    if pattern.endswith("/") and not is_directory:
        return any(index < len(parts) for index in positions)
    return bool(positions)


@dataclass(frozen=True)
class Config:
    select: frozenset[str] = frozenset(RULES)
    ignore: frozenset[str] = frozenset()
    exclude: tuple[str, ...] = ()
    assume_sessions: tuple[str, ...] = ()
    root: Path = field(default_factory=Path.cwd)
    baseline: Path | None = None

    @property
    def enabled_rules(self) -> frozenset[str]:
        return self.select - self.ignore

    def is_excluded(self, path: Path) -> bool:
        # Match the named path, not a symlink's target. Excludes are scan policy,
        # not a filesystem sandbox. Paths outside this project are never excluded.
        if not self.exclude:
            return False
        absolute = Path(os.path.abspath(path))
        try:
            relative = absolute.relative_to(self.root)
        except ValueError:
            # The project root may have another filesystem spelling (for example
            # /var and /private/var on macOS). Canonicalize only that prefix, not
            # symlinked names within the project that the policy should match.
            canonical_root = self.root.resolve()
            for ancestor in (absolute, *absolute.parents):
                try:
                    same_root = ancestor.resolve() == canonical_root
                except (OSError, RuntimeError):
                    continue
                if same_root:
                    relative = absolute.relative_to(ancestor)
                    break
            else:
                return False
        return any(
            _matches(
                relative.parts,
                pattern,
                is_directory=pattern.endswith("/") and path.is_dir(),
            )
            for pattern in self.exclude
        )


def _strings(table: dict, key: str) -> tuple[str, ...]:
    value = table[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ConfigError(f"{key} must be an array of strings")
    return tuple(value)


def read_config(path: Path, *, explicit: bool = False) -> Config:
    """Read [tool.torchlight]; an explicitly selected file must contain that table."""
    path = Path(os.path.abspath(path))
    try:
        with path.open("rb") as stream:
            document = tomllib.load(stream)
        tool = document.get("tool", {})
        if not isinstance(tool, dict):
            raise ConfigError("tool must be a table")
        if explicit and "torchlight" not in tool:
            raise ConfigError("expected a [tool.torchlight] table")
        table = tool.get("torchlight", {})
        if not isinstance(table, dict):
            raise ConfigError("tool.torchlight must be a table")
        unknown = table.keys() - CONFIG_KEYS
        if unknown:
            raise ConfigError(f"unknown setting(s): {', '.join(sorted(unknown))}")

        values = {key: _strings(table, key) for key in table if key != "baseline"}
        baseline = table.get("baseline")
        if "baseline" in table and (
            not isinstance(baseline, str) or not baseline.strip() or "\x00" in baseline
        ):
            raise ConfigError("baseline must be a nonempty path string")
        for key in ("select", "ignore"):
            unknown_rules = set(values.get(key, ())) - RULES.keys()
            if unknown_rules:
                raise ConfigError(
                    f"{key}: unknown rule ID(s): {', '.join(sorted(unknown_rules))}"
                )
        for name in values.get("assume-spark-session", ()):
            if not valid_session_name(name):
                raise ConfigError(
                    f"assume-spark-session: invalid Python variable name {name!r}"
                )
        for pattern in values.get("exclude", ()):
            validate_pattern(pattern)
        return Config(
            select=frozenset(values.get("select", RULES)),
            ignore=frozenset(values.get("ignore", ())),
            exclude=values.get("exclude", ()),
            assume_sessions=values.get("assume-spark-session", ()),
            root=path.parent.resolve(),
            baseline=path.parent / baseline if baseline is not None else None,
        )
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def load_config(
    *, cwd: Path | None = None, config_path: Path | None = None, no_config: bool = False
) -> Config:
    """Use an explicit file, or the nearest pyproject.toml above the working directory.

    Discovery stops at the first pyproject, even without a Torchlight table. There
    is no per-target discovery, parent merging, or execution of Python config.
    """
    root = (cwd or Path.cwd()).resolve()
    if no_config:
        return Config(root=root)
    if config_path is not None:
        return read_config(root / config_path, explicit=True)
    for directory in (root, *root.parents):
        candidate = directory / "pyproject.toml"
        if candidate.exists():
            return read_config(candidate)
    return Config(root=root)
