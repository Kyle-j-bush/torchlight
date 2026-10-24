# Review findings introduced by a Git change

Available in v0.5.0+. Git 2.45+ is required only for this mode; ordinary scans do not
require a repository or invoke Git.

```sh
torchlight . --changed-from origin/main
torchlight jobs/ notebooks/ --changed-from BASE_COMMIT --format github
```

## What is compared

1. Locate the repository containing the current configuration root. Resolve REF
   to a commit and find its **unique merge base with HEAD**. REF is not compared
   directly with the working tree if the two branches have diverged.
2. Discover changes between that base and the working tree: committed, staged,
   unstaged, and non-ignored untracked files. Git-ignored untracked files are not
   included, even if explicitly named. Tracked files still participate.
3. Within supplied paths and current excludes, analyze complete changed `.py`
   and `.ipynb` files in normal deterministic discovery order. Never analyze only
   added lines: changed setup code can affect an existing call elsewhere.
4. Analyze their base blobs using the **same current rule/session/suppression
   policy**, not historical configuration. Subtract matching rule/fingerprint
   occurrences. Report the remaining current findings at current coordinates.

Configured baseline files are ignored and never read or written. `--changed-from`
is mutually exclusive with `--baseline`, `--write-baseline`, and `--no-baseline`.
It is not a TOML setting. In Python:

```python
from torchlight import Config, Scanner

report = Scanner(Config.from_pyproject("pyproject.toml")).scan(
    ["jobs", "notebooks"], changed_from="origin/main"
)
raise SystemExit(report.exit_code)
```

## Matching and boundaries

- Git rename detection uses 50% similarity. Stage moves (`git add -A`) so their
  destinations participate in detection. Unstaged moves to untracked names,
  unmatched rewrites, and copies are additions, so existing warnings may reappear.
- A rename can match an old path outside the supplied scan paths. Historical
  non-source files and currently excluded old paths do not grandfather warnings
  when moved into reviewed source. A previous symlink is not parsed as source.
- Comments, formatting, line shifts, and notebook cell insertions do not change
  structural identity. Matching consumes counts: an additional identical call is
  new, but replacing one identical call with another is not distinguishable.
  The opt-in graph overlay is stricter: duplicate structural keys that make a
  match ambiguous are `unknown`, not confidently matched.
- Deleted files produce no current findings. Explicitly named deleted/renamed
  old files are skipped; other missing inputs remain errors.
- Notebooks retain complete document-order state on each side. Unchanged
  notebook output/metadata-only changes do not create new findings.
- Only one repository is compared. Inputs outside it and symlinks within it are
  rejected; aliases of the repository root are normalized as in ordinary scans.
  Nested repositories/submodules are not scanned as part of the parent;
  run separately with their own configuration root. Built-in directory skips
  and configured excludes still apply.
- Unchanged files are not analyzed, even if they contain existing syntax errors.
  This is not cross-file analysis, a full-repository health check, or a proof of
  safety. Changes to policy alone do not trigger reanalysis of unchanged source.

## Graph change overlay

`include_graph=True` also captures base operations and adds
`report.graph.comparison` and `report.graph.changes`. This is separate from
count-based finding subtraction.

- `comparison` records the requested ref, resolved merge base, whether base
  capture was complete, and that current source is the working tree.
- Each retained current node gets `matched`, `new-or-edited`, `unknown`, or
  `not-compared`. `matched` means structural syntax identity only; it does not
  establish semantic equivalence.
- A unique structural key on both sides is matched. An absent key in a complete
  base graph is new or edited. Duplicate keys that make a match ambiguous, any
  incomplete base graph, base errors, and unavailable base source are `unknown`.
  Existing artifacts with truncated current capture also become `unknown`, since
  missing operations can hide duplicates. Known added files remain new or edited.
- Matched changes retain base coordinates and facts. For example, a prior
  `limit(1000)` bound can remain attached to an unchanged current `df.collect()`.
- Renames use the same merge-base mapping as finding subtraction; cell and line
  shifts do not affect structural keys. Matching happens before pruning to
  finding-centered paths.

No graph JSON or HTML output format is available yet.

## Errors and read-only operation

Missing Git, refs, HEAD, merge bases or blobs, multiple merge bases, shallow
history, unresolved index conflicts, and skip-worktree/assume-unchanged index
entries are errors, not a fallback to a clean or full scan. Use a complete,
ordinary checkout and fetch missing history explicitly; Torchlight does not
fetch, checkout, refresh the index, or change refs. Git subprocesses have a
60-second timeout. Clean/process filters, external diff/textconv helpers, and
fsmonitor commands are disabled. Source and historical blobs are never executed.
Git's `--no-lazy-fetch` flag prevents partial clones from fetching implicitly;
older Git versions fail explicitly. Unavailable historical source (including
source replaced by LFS pointers) cannot establish a complete comparison.

Parse, decoding, notebook, and suppression errors in either analyzed snapshot
remain report errors. Base errors identify the base commit and old path; their
findings are not used to suppress current warnings. Exit codes remain **0** clean,
**1** findings (even with errors), **2** errors only. JSON/SARIF retain their
existing schemas. Review errors as well as findings.

## CI setup

Checkout full history (`fetch-depth: 0`) and ensure the PR base commit exists
locally. Pass it through an environment variable, not interpolated shell code:

```yaml
- name: Review introduced findings
  env:
    BASE_COMMIT: ${{ github.event.pull_request.base.sha }}
  run: torchlight . --changed-from "$BASE_COMMIT" --format github
```

See the [complete pinned example](../.github/examples/torchlight-code-scanning.yml).
Keep **full `--no-baseline` SARIF uploads** separate from comparison enforcement:
uploading a partial report can close existing Code Scanning alerts incorrectly.
Do not use `pull_request_target` to run untrusted code with elevated permissions.
