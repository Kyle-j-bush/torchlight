# Adopt Torchlight without fixing all existing debt

Available in v0.3.0. A baseline records reviewed existing findings so normal scans
report and fail only on **new findings**. It does not change analysis, weaken
suppression validation, or hide scan errors.

```sh
# Run from the repository root with the policy you intend to enforce.
torchlight . --write-baseline .torchlight-baseline.json
# Review and commit the snapshot, then use it locally and in CI.
torchlight . --baseline .torchlight-baseline.json
```

Or share it with pre-commit and CI through project configuration:

```toml
[tool.torchlight]
baseline = ".torchlight-baseline.json"
```

A configured path is relative to the configuration file's directory. CLI
`--baseline` and `--write-baseline` paths are relative to the working directory.
`--no-baseline` reports all findings without disabling other project policy.
`--no-config` also ignores the configured baseline. These three baseline CLI
options are mutually exclusive. Writing ignores any configured input baseline.

## Snapshot and update behavior

`--write-baseline` captures **all enabled, unsuppressed findings in the supplied
paths**, emits their normal report, and exits 0 on successful capture. Any scan
or write error exits 2 and leaves the existing baseline untouched. Updates are
atomic; a destination that already exists must be a valid baseline. Unrelated
files and destination symlinks are never overwritten. Parent directories must
already exist. There is no implicit or automatic baseline update.

To intentionally refresh debt after review, repeat the full-repository capture
command. A partial-file scan, narrower rule selection, or changed excludes will
produce a narrower replacement snapshot. Review that diff before committing.
Do not automatically refresh a baseline on every pull request: doing so would
accept regressions instead of enforcing the policy.

## Matching and limits

Baseline schema version 1 contains `fingerprint_version: "v1"` and a sorted
`findings` array. Each entry has `path`, `rule_id`, `fingerprint`, and a positive
integer `count`. Paths use project-relative forward slashes, not absolute machine
paths. No snippets, notebook outputs, or evidence text are stored.

Matching uses path + rule + [structural fingerprint](reporting.md) and consumes
at most the saved count. New duplicate calls beyond that count are reported.
Blank lines, comments, formatting, and notebook cell insertions do not churn
identity. File renames, call edits, variable renames, or named-scope changes may
be new. Identical calls cannot be individually distinguished if one replaces
another; the count only detects net additions. Stale entries are harmless but
can match a later reintroduction, so prune fixed debt in reviewed updates.

Only findings beneath the configured project root can be captured. Outside-root
findings are always new when reading a baseline. Nonportable filenames containing
backslashes or colons cannot be captured. Invalid schemas, rules, counts, paths,
or unsupported fingerprints abort before scanning, rather than silently hiding
findings. Use the same project root and policy in all environments.

This release still scans complete supplied files. It does **not** implement
`--changed-from`, Git-base comparison, rename tracking, or cross-file analysis.
