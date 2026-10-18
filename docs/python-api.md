# Python API

Available in v0.4.0+. Integrations can use the same orchestration as the CLI
without subprocess parsing or access to the analyzer's mutable state.

```python
from pathlib import Path
from torchlight import Config, Scanner

config = Config.from_pyproject(Path("pyproject.toml"))
report = Scanner(config=config).scan([Path("jobs"), Path("notebooks")])

for finding in report.findings:
    print(finding.rule_id, finding.path, finding.location, finding.fingerprint)
for error in report.errors:
    print(error)

raise SystemExit(report.exit_code)
```

## Configuration

`Config.from_pyproject(path)` reads an **explicit** TOML file and requires
`[tool.torchlight]`. It raises `ConfigError` for missing/invalid policy. The
configuration root is the file's directory, as with CLI `--config`.

Alternatively construct `Config(select=frozenset({"TL001", "TL004"}),
exclude=("generated/**",), assume_sessions=("spark",), root=Path("project"))`.
`ignore` defaults to empty and `select` defaults to every current rule. Collections
are validated and copied to frozen sets/tuples; changing an input list cannot
change an existing policy. A relative `baseline` path is anchored to `root`.

`Scanner()` uses built-in policy and the construction-time working directory as
its root. **It does not discover configuration.** This avoids silently changing
an embedding application's behavior based on an unrelated `pyproject.toml`.
The CLI retains its documented working-directory discovery.

## Scanning and reports

- `Scanner(config).scan(paths, *, use_baseline=True)` accepts one string/`Path`
  or an iterable of them, including generators. Relative inputs are relative to
  the **working directory at scan time**, not `Config.root`, matching the CLI.
- Project root anchors excludes, baseline identity, and SARIF relative locations.
  Pass absolute input paths when your application may change its directory.
- Directories use deterministic discovery; overlapping resolved paths are scanned
  once. Selection, ignores, assumptions, inline suppressions, notebook state, and
  baselines have the same behavior as the CLI.
- Each call has fresh analysis state. A scanner can be reused; files do not share
  Spark state. Notebook cells within one file still share document-order state.
- Invalid/unreadable source, missing/unsupported inputs, directory discovery
  failures, and invalid baselines are `report.errors`. An invalid baseline aborts
  before scanning. An empty input iterable is an error, not a clean scan.
- `use_baseline=False` produces the full report without reading a configured
  baseline. Scanning never captures or modifies a baseline.
- Invalid API argument types raise `TypeError`/`ValueError`; configuration errors
  raise `ConfigError`. Do not treat an exception as a clean report.

`ScanReport` contains immutable `findings` and `errors` tuples and the absolute
`root`. `exit_code` is 0 for clean, 1 for findings (even with errors), or 2 for
errors only. Both findings and errors must be reviewed if present.

`report.to_dict()` returns a detached [JSON schema 1](reporting.md) document.
`report.render("text" | "json" | "github" | "sarif")` returns serialized text;
the default is `"text"`. Unknown formats raise `ValueError`. These methods do not
print, execute source, send network requests, or write files. Paths and snippets
may contain sensitive source; review reports before sharing them.

## Public surface and compatibility

Supported imports from `torchlight` are `Config`, `ConfigError`, `Scanner`,
`ScanReport`, `Finding`, `Location`, and `Rule`. Existing immutable finding/rule
fields and structural fingerprint semantics are retained. No measured confidence
or new severity policy is introduced.

This is the initial, **pre-1.0** Python API. Incompatible changes require release
notes and a minor-version change, not a patch. Rule IDs, JSON schema, and
fingerprint/baseline versions retain their existing contracts. Modules containing
AST traversal, semantic facts, detector registration, and mutable analyzer state
are internal; they are not a supported plugin API. No `py.typed` support promise
is made yet. [Detector contributor guide](development/detectors.md).
