# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Public immutable scan/report objects shared by integrations and the CLI."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from torchlight.baseline import BaselineError, new_findings, read_baseline
from torchlight.config import Config
from torchlight.diagnostics import Finding
from torchlight.files import SOURCE_SUFFIXES, iter_source_files, scan_file, scan_source
from torchlight.git import GitComparison, GitError
from torchlight.identity import project_path
from torchlight.reporting import render


@dataclass(frozen=True)
class ScanReport:
    findings: tuple[Finding, ...] = ()
    errors: tuple[str, ...] = ()
    root: Path = field(default_factory=Path.cwd)

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(self, "errors", tuple(self.errors))
        object.__setattr__(self, "root", Path(self.root).resolve())

    @property
    def exit_code(self) -> int:
        """0 = clean, 1 = findings (even with errors), 2 = errors only."""
        return 1 if self.findings else (2 if self.errors else 0)

    def to_dict(self) -> dict:
        """Return a detached JSON schema version 1 document."""
        return {
            "schema_version": 1,
            "findings": [finding.to_dict() for finding in self.findings],
            "errors": list(self.errors),
        }

    def render(self, output_format: str = "text") -> str:
        """Serialize without writing to stdout, stderr, or the filesystem."""
        if output_format not in {"text", "json", "github", "sarif"}:
            raise ValueError(f"unsupported output format: {output_format}")
        return render(
            list(self.findings), list(self.errors), output_format, root=self.root
        )


@dataclass(frozen=True)
class Scanner:
    """Reusable policy, fresh analysis state on each scan; never executes source.

    Default construction uses built-in policy, not implicit config discovery.
    Relative input paths are interpreted from the calling working directory,
    just as CLI arguments are. Config.root anchors excludes and report identity.
    """

    config: Config = field(default_factory=Config)

    def __post_init__(self) -> None:
        if not isinstance(self.config, Config):
            raise TypeError("config must be a Config")

    def scan(
        self,
        paths: Iterable[str | Path] | str | Path,
        *,
        use_baseline: bool = True,
        changed_from: str | None = None,
    ) -> ScanReport:
        """Return findings/errors without printing or modifying baseline files.

        Invalid source, missing inputs, discovery failures, and baseline errors
        are report errors. Invalid API arguments raise TypeError/ValueError.
        changed_from compares changed files with REF/HEAD's merge base using
        current policy on both snapshots, ignoring any configured baseline.
        """
        if type(use_baseline) is not bool:
            raise TypeError("use_baseline must be a bool")
        if isinstance(paths, (str, Path)):
            paths = (paths,)
        # Validate before reading inputs, rather than partially scanning a bad call.
        inputs = tuple(Path(path) for path in paths)
        if not inputs:
            return ScanReport(
                errors=("no input paths supplied",), root=self.config.root
            )
        comparison = None
        if changed_from is not None:
            try:
                comparison = GitComparison.from_ref(self.config.root, changed_from)
            except GitError as exc:
                return ScanReport(
                    errors=(f"Git comparison error: {exc}",), root=self.config.root
                )
        baseline = None
        if comparison is None and use_baseline and self.config.baseline is not None:
            try:
                baseline = read_baseline(self.config.baseline)
            except BaselineError as exc:
                return ScanReport(
                    errors=(f"baseline error: {exc}",), root=self.config.root
                )

        findings: list[Finding] = []
        errors: list[str] = []
        seen: set[Path] = set()

        def discovery_error(exc: OSError) -> None:
            errors.append(f"{exc.filename}: {exc.strerror or exc}")

        def discovery_excluded(path: Path) -> bool:
            return self.config.is_excluded(path) or (
                comparison is not None
                and path.is_dir()
                and path.resolve() != comparison.root
                and (path / ".git").exists()
            )

        for path in inputs:
            try:
                if comparison is not None:
                    name = comparison.name(path)
                    if name in comparison.deleted and not path.exists():
                        continue
                if path.exists() and self.config.is_excluded(path):
                    continue
                if path.is_dir():
                    files = iter_source_files(
                        path,
                        is_excluded=discovery_excluded,
                        on_error=discovery_error,
                    )
                elif path.is_file() and path.suffix in SOURCE_SUFFIXES:
                    files = (path,)
                else:
                    reason = (
                        "unsupported file type (expected .py or .ipynb)"
                        if path.exists()
                        else "no such file or directory"
                    )
                    errors.append(f"{path}: {reason}")
                    continue

                for file in files:
                    if comparison is not None:
                        name = project_path(file, comparison.root)
                        if name not in comparison.changes:
                            continue
                        comparison.name(file)
                    resolved = file.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    file_findings, file_errors = scan_file(
                        file, assume_sessions=self.config.assume_sessions
                    )
                    errors.extend(file_errors)
                    if comparison is not None:
                        try:
                            previous_source = comparison.changes[name]
                            previous_path = (
                                comparison.root / previous_source.name
                                if previous_source is not None
                                else None
                            )
                            source = (
                                comparison.previous_source(name)
                                if previous_path is not None
                                and previous_path.suffix in SOURCE_SUFFIXES
                                and not self.config.is_excluded(previous_path)
                                else None
                            )
                            if source is not None:
                                previous, previous_errors = scan_source(
                                    previous_path,
                                    source,
                                    assume_sessions=self.config.assume_sessions,
                                )
                                errors.extend(
                                    f"Git base {comparison.base[:12]}: {error}"
                                    for error in previous_errors
                                )
                                if not previous_errors:
                                    counts = Counter(
                                        (f.rule_id, f.fingerprint) for f in previous
                                    )
                                    introduced = []
                                    for finding in file_findings:
                                        key = (finding.rule_id, finding.fingerprint)
                                        if counts[key] > 0:
                                            counts[key] -= 1
                                        else:
                                            introduced.append(finding)
                                    file_findings = introduced
                        except GitError as exc:
                            errors.append(f"{file}: Git comparison error: {exc}")
                    findings.extend(
                        f
                        for f in file_findings
                        if f.rule_id in self.config.enabled_rules
                    )
            except (OSError, ValueError) as exc:
                errors.append(f"{path}: {exc}")

        if baseline is not None:
            findings = new_findings(findings, baseline, self.config.root)
        return ScanReport(tuple(findings), tuple(errors), self.config.root)
