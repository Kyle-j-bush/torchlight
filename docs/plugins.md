# Trusted in-process detectors — API version 1

Available in v0.7.0+. Register **already constructed Python objects**, explicitly,
through `Config(plugins=...)`. Nothing discovers entry points, imports a module
named in project configuration, installs dependencies, or loads notebook code.
The standard CLI/TOML supports built-in rules only; integrations own their Python
entry point. There is no process-global registry.

```python
from torchlight import Config, Rule, Scanner
from torchlight.plugins import CallFacts, Diagnostic, Plugin


class CountReview:
    rule_id = "ACME001"

    def check(self, facts: CallFacts):
        if facts.receiver.kind == "frame" and facts.method == "count":
            yield Diagnostic(self.rule_id, (facts.receiver.origin,))


rule = Rule("ACME001", "Review count", "A team-specific policy.", "Review the job.")
config = Config(plugins=(Plugin(rule, CountReview(), api_version=1),))
report = Scanner(config).scan("jobs/")
print(report.render("sarif"))
```

This example is an extension demonstration, **not** a recommended new Spark risk
rule. Plugin findings are warnings with no automatic fix, like built-in findings.

## Registration, policy, and failures

- `Plugin(rule, detector, api_version=1)` is frozen. The detector implements the
  public `Detector` protocol: matching `rule_id` and callable `check(facts)` yielding
  `Diagnostic` objects. Unsupported API versions, malformed metadata, and duplicate
  rule IDs fail before scanning. IDs use uppercase letters/digits followed by at
  least three digits, e.g. `ACME001`. The entire `TL` prefix is reserved.
- `Config` snapshots the plugin list. Its default selection includes registered
  rules; explicit `select`/`ignore` can name them. Unknown IDs still fail. Selection
  filters findings after analysis; **it is not an execution/security boundary**.
- Plugins must be deterministic, stateless functions of facts, including across
  repeated scans and Git base/current snapshots. Config freezes registration, not
  arbitrary detector internals. The same detector objects may be called repeatedly;
  stateful plugins can invalidate Git/baseline comparisons or concurrent use.
- A detector exception, invalid result, wrong ID, or missing evidence becomes a
  scan error, never a clean pass. Exception type and plugin ID are reported without
  the exception message (which could contain private data). Failed file analysis
  is discarded; other files continue and Git-base failures remain explicit. Exit-code semantics remain
  0 clean / 1 findings, possibly with errors / 2 errors only. Check `report.errors`.
- Plugins are **trusted arbitrary local code**. They can access files/network,
  mutate global state, hang, print, or raise process-control exceptions. There is
  no sandbox, timeout, isolation, or promise of side-effect-free plugin execution.
  Only scanned source is never executed. Inspect and pin plugin code yourself.

## Version 1 facts and results

Import extension types from `torchlight.plugins`, not the implementation modules.
`API_VERSION == 1` versions this contract separately from the distribution.

`CallFacts` is frozen and exposes:

| Field | Meaning |
| --- | --- |
| `receiver: Value` | Proven receiver before the call; unknown receivers do not invoke detectors. |
| `method: str` | Called attribute name (or a proven `list`/`tuple` materializer). No argument AST is exposed. |
| `terminal_write: bool` | A recognized V1/V2 writer terminal call. |
| `carries_loop_frame: bool` | Assignment carries the receiver through a potentially repeated loop. |

`Value` is frozen: `kind`, human-readable `origin`, optional integer `row_limit`,
optional `single_partition: Location`, `single_partition_method` (`coalesce` or
`repartition`), and `loop_origins` (a frozen set of opaque loop-token/name pairs).
Use `carries_loop_frame`, not token numbers, for loop decisions. Known kinds include
`frame`, `grouped`, `writer`, `writer_v2`, `frame_na`, `local_iterator`, `module`,
`session`, `session_type`, `frame_type`, `builder`, `reader`, `generator`, and
`materializer`. Ignore unfamiliar kinds for forward compatibility. Defaults remain
the dataclass defaults; absent facts are not proof of safety. Origin text is
evidence, not a stable machine-parsed field or a dataset-size measurement.

Yield `Diagnostic(rule_id, evidence, detail="")`: evidence must be a nonempty
tuple of nonempty strings, and detail is appended to the registered rule title.
The engine owns source locations, snippets, qualified scope, and structural
fingerprints. One rule emits at most one finding per call location. Plugins cannot
change inference, add receiver identities, inspect syntax/arguments, or register
automatic fixes through this contract. No callbacks fire for unresolved calls.

## Reports, suppressions, and baselines

Findings retain their immutable plugin `Rule` metadata, so detached reports render
correctly after a scanner is discarded. Schema 1 and fingerprint v1 are unchanged.
SARIF includes descriptors for emitted plugin rules, without fake Torchlight guide
links. Inline suppression requires the registered ID and a reason:
`# torchlight: ignore[ACME001] -- reviewed team exception`.

Python, Jupyter, Databricks, excludes, and `changed_from` use the same pipeline.
Plugin definitions must remain identical across compared snapshots. Changed
diagnostic wording does not change identity. Version incompatible rule meaning
under a new rule ID, or deliberately recapture reviewed baseline debt.

The existing baseline helpers are lower-level, not newly promoted stable APIs.
For plugin-aware capture/update pass the full catalog explicitly:

```python
from torchlight.baseline import write_baseline

write_baseline(destination, list(report.findings), config.root, rules=config.rules)
```

`Scanner` reads baselines with its registered catalog. A built-in-only scanner
rejects a baseline containing unregistered plugin rules rather than silently
ignoring them. No CLI plugin capture/loading is added. The Python API remains
pre-1.0; breaking extension-contract changes require another plugin API version.
