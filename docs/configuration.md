# Project configuration

Available in v0.3.0+. Older releases do not read project configuration.

```toml
[tool.torchlight]
select = ["TL001", "TL002", "TL003"]
ignore = []
exclude = ["generated/**", "vendor/**"]
assume-spark-session = ["spark"]
# Optional, after creating and reviewing a snapshot:
# baseline = ".torchlight-baseline.json"
```

Every setting is optional. List values must be arrays of strings; `baseline` is
a nonempty path string. Unknown keys,
unknown rule IDs, malformed TOML, invalid globs, and invalid session names stop
the run **before scanning**, with exit code 2. JSON and GitHub formats also report
configuration errors in their structured output. Python config is never executed.

| Setting | Default | Meaning |
| --- | --- | --- |
| `select` | All three current rule IDs | Rules to enable. `[]` disables all findings, not scan errors. |
| `ignore` | `[]` | Rules to disable; ignore wins over select. |
| `exclude` | `[]` | Project-relative file/directory globs; also apply to explicitly named existing paths. |
| `assume-spark-session` | `[]` | Existing names explicitly treated as SparkSession objects. Names must be Python identifiers, not keywords. |
| `baseline` | None | Reviewed baseline JSON path, relative to this configuration file. See [baselines](baselines.md). |

Assumptions are opt-in. Do not copy `spark` into your policy unless your
environment actually provides it. Reassignment or opaque notebook cells can
invalidate the assumption. `target-spark` and `fail-on` are **not
supported settings** and are rejected rather than silently ignored.

## Discovery and precedence

1. Start with built-in defaults.
2. Starting at the **current working directory**, walk upward to the nearest
   `pyproject.toml`. Stop there, even if it has no `[tool.torchlight]` table. A file
   without the table contributes only defaults. Do not merge parent projects.
3. If supplied, `--config PATH` **replaces discovery**, not just individual keys.
   This TOML file must contain `[tool.torchlight]`. Its filename need not be
   `pyproject.toml`. A relative `PATH` is relative to the working directory.
4. Explicit CLI settings replace their corresponding configured values. Other
   configured settings remain active. `ignore` still wins over `select`.

There is exactly **one policy per invocation**. Torchlight does not discover
separate configurations for input files or descend into nested project policies.
This keeps directory scans, pre-commit's explicit file list, and CI consistent
when invoked from the same repository root. Run from that root, or pin
`--config /path/to/pyproject.toml` when working elsewhere.

```sh
torchlight --config pyproject.toml jobs/ notebooks/
torchlight --select TL001,TL002 --ignore TL002 jobs/
torchlight --exclude 'generated/**' --exclude '*.ipynb' .
torchlight --assume-spark-session spark --assume-spark-session session notebooks/
torchlight --no-config jobs/
```

Repeated `--exclude` or `--assume-spark-session` flags form a replacement list,
not an addition to the config list. `--no-config` bypasses discovery and all file
settings, even malformed ones; it cannot be combined with `--config`. CLI rule
lists must be nonempty comma-separated IDs. To clear a configured list, change
it to `[]` in TOML or use `--no-config` and supply the desired CLI policy.

## Exclusion paths and globs

The project root is the selected configuration file's directory, including when
it is discovered above the working directory. Without any configuration file,
or with `--no-config`, it is the working directory. CLI excludes use that same
root, **not** the input directory or the config option's spelling.

- Use relative forward-slash patterns on every OS; quote shell wildcards.
- `*`, `?`, and `[ab]` match within one path segment.
- A whole `**` segment matches zero or more path segments.
- A pattern without a slash matches a basename at any depth: `*.ipynb`, `vendor`.
- A pattern with slashes is rooted: `generated/**` does not match
  `jobs/generated/code.py`. Use `**/generated/**` for that.
- A trailing slash excludes matching directories and their contents: `vendor/`.
- A matching ancestor excludes its entire subtree. Excluded directories are
  pruned, so their syntax errors and notebooks are not read.
- Matching is case-sensitive on every OS. Absolute paths, backslashes, drive
  prefixes, empty patterns, `.`/`..` segments, and embedded `**` such as `a**b`
  are rejected. There is no negation or gitignore syntax.

Excludes affect recursive discovery **and explicit existing file/directory
arguments**. Missing paths still produce errors even if their names would match.
Paths outside the project root are not excluded. Equivalent spellings of the
project root (such as macOS `/var` and `/private/var`) are normalized. Symlinks
inside the project are matched by their named path, not their target; this is
scan policy, not a security sandbox.
Built-in virtual-environment/VCS/cache directory skips remain in effect during
recursive discovery and cannot be re-enabled by configuration.

Without a baseline, scan exit semantics are unchanged. Baselines filter existing
findings before reporting and deciding the exit code; snapshot writing has its
own documented success/error contract. No runtime dependencies are added.
