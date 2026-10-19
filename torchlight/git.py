# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

"""Read-only Git-base discovery; no checkouts, network requests, or source execution."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from torchlight.identity import project_path


class GitError(ValueError):
    """An incomplete comparison must never be presented as a clean scan."""


def _git(root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", *arguments],
            cwd=root,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"},
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(str(exc)) from exc
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(
            message or f"git {arguments[0]} failed (exit {result.returncode})"
        )
    return result.stdout


@dataclass(frozen=True)
class PreviousSource:
    name: str
    blob: str


@dataclass(frozen=True)
class GitComparison:
    root: Path
    base: str
    changes: dict[str, PreviousSource | None]
    deleted: frozenset[str]

    @classmethod
    def from_ref(cls, root: Path, ref: str) -> "GitComparison":
        if not isinstance(ref, str):
            raise TypeError("changed_from must be a string")
        if not ref.strip() or "\x00" in ref:
            raise ValueError("changed_from must be a nonempty Git revision")
        root = Path(
            os.fsdecode(_git(root, "rev-parse", "--show-toplevel").removesuffix(b"\n"))
        )
        if _git(root, "rev-parse", "--is-shallow-repository").strip() == b"true":
            raise GitError(
                "shallow repository: fetch full history (fetch-depth: 0 in CI)"
            )
        if _git(root, "ls-files", "--unmerged", "-z"):
            raise GitError("unresolved merge conflicts; resolve the index first")
        if any(
            entry and (entry[:1].islower() or entry[:1] == b"S")
            for entry in _git(root, "ls-files", "-v", "-z").split(b"\x00")
        ):
            raise GitError(
                "skip-worktree/assume-unchanged entries require a full, ordinary checkout"
            )
        target = _git(
            root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"
        )
        bases = _git(
            root, "merge-base", "--all", target.decode().strip(), "HEAD"
        ).splitlines()
        if len(bases) != 1:
            raise GitError("comparison requires exactly one merge base")
        base = bases[0].decode()

        # Raw diffs still use clean filters. Disable them as well as external diff,
        # textconv, and fsmonitor so repository configuration cannot execute code.
        filters = {
            key.rsplit(".", 1)[0]
            for entry in _git(root, "config", "--null", "--list").split(b"\x00")
            if (key := os.fsdecode(entry.split(b"\n", 1)[0])).startswith("filter.")
            and key.rsplit(".", 1)[-1] in {"clean", "process", "required"}
        }
        options = []
        for name in sorted(filters):
            for key, value in (("clean", ""), ("process", ""), ("required", "false")):
                options.extend(("-c", f"{name}.{key}={value}"))
        records = iter(
            _git(
                root,
                *options,
                "diff",
                "--raw",
                "-z",
                "--no-abbrev",
                "--find-renames=50%",
                "--no-ext-diff",
                "--no-textconv",
                base,
                "--",
            ).split(b"\x00")
        )
        changes: dict[str, PreviousSource | None] = {}
        deleted: set[str] = set()
        for record in records:
            if not record:
                continue
            old_mode, _, old_blob, _, status = record.split()
            name = os.fsdecode(next(records))
            old_name = name
            if status.startswith(b"R"):
                deleted.add(name)
                name = os.fsdecode(next(records))
            if status == b"D":
                deleted.add(name)
            elif status == b"U":
                raise GitError(f"{name}: unresolved merge conflict")
            else:
                changes[name] = (
                    PreviousSource(old_name, old_blob.decode())
                    if old_mode in {b":100644", b":100755"}
                    else None
                )
        # shortcut: unstaged moves to untracked names are additions; stage the move
        # to enable Git's similarity-based rename matching.
        for name in _git(
            root, "ls-files", "--others", "--exclude-standard", "-z"
        ).split(b"\x00"):
            if name:
                changes[os.fsdecode(name)] = None
        return cls(root, base, changes, frozenset(deleted))

    def previous_source(self, name: str) -> bytes | None:
        previous = self.changes[name]
        return (
            None
            if previous is None
            else _git(self.root, "cat-file", "blob", previous.blob)
        )

    def name(self, path: Path) -> str:
        try:
            name = Path(os.path.abspath(path)).relative_to(self.root).as_posix()
        except ValueError:
            name = project_path(path, self.root)
        if name is None:
            raise GitError("comparison inputs must be inside the Git repository")
        candidate = self.root / name
        for ancestor in (candidate, *candidate.parents):
            if ancestor == self.root:
                break
            if ancestor.is_symlink():
                raise GitError("Git comparison does not follow symlinks")
            if ancestor.is_dir() and (ancestor / ".git").exists():
                raise GitError("scan nested repositories/submodules separately")
        return name
