# Report identity

JSON schema version 1 gains an additive `fingerprint` field in v0.3.0. Existing
fields and source coordinates are unchanged. Consumers should accept extra fields.

A `v1:<sha256>` fingerprint identifies the rule, normalized call syntax, and
enclosing function/class names. It ignores line/column/cell numbers, comments,
formatting, quote style, evidence wording, and checkout location. Variable names,
literal values, and enclosing scope names are significant. The analyzer does not
execute code to compute identity.

Fingerprints are **content identity, not globally unique IDs**. Match them with
the project-relative file path. Renaming a file or changing the call/scope can
make a finding new. Identical calls in one scope (including across notebook cells)
share a fingerprint; consumers must compare occurrence counts, not just sets.
If one identical old call is removed while another is added, static matching
cannot distinguish them. Fingerprints do not prove semantic equivalence or safety.

The `v1` algorithm is a compatibility contract. Any incompatible identity change
must use a new prefix and document baseline migration. Manually constructed
`Finding` objects without analyzer structure fall back to their snippet text.

## SARIF 2.1.0

```sh
torchlight --format sarif jobs/ notebooks/ > torchlight.sarif
```

SARIF includes the rule catalog, help links, evidence, review guidance, warning
levels, and structural partial fingerprints. GitHub's `primaryLocationLineHash`
also includes an occurrence suffix to distinguish identical calls. Rule metadata
does not claim measured precision or assign security severity to performance risks.
The installed distribution's version is included when available.

Python regions use one-based **Unicode code point** columns, matching JSON
coordinates, not UTF-8 byte offsets. In-project artifact URIs are percent-encoded
and relative to `%SRCROOT%`, the configuration root; outside-root artifacts use
absolute file URIs. For GitHub display, SARIF resolves symlink targets. Baselines
instead retain named paths, as documented in [baseline matching](baselines.md).

Jupyter notebooks have file-level physical locations, **no fake raw-JSON line regions**.
Messages include code-cell coordinates, also available under
`properties.notebookLocation`. GitHub may offer only limited file-level navigation;
this is not a cell-aware notebook review integration.

Databricks Python source exports (v0.6.0+) instead use physical `.py` regions,
including columns after `# MAGIC` prefixes, and exported cell metadata. Their
`line`, `column`, and `endLine` in `notebookLocation` are physical coordinates,
not Jupyter code-cell-local coordinates. JSON schema 1 is unchanged; integrations
must distinguish these source kinds. See [source mapping](databricks.md).

Scan, configuration, and baseline errors appear as invocation notifications with
`executionSuccessful: false`, even if findings are also present. A clean SARIF
result array alone does not establish that a scan completed successfully. CLI
exit semantics remain independent: findings exit 1, errors alone exit 2.

Use [the Code Scanning example](../.github/examples/torchlight-code-scanning.yml)
to upload **before** failing CI on findings. A plain failing scan followed by a
normal upload step would skip the upload. Code Scanning availability/permissions
depend on repository settings and GitHub plan; fork pull requests can have
restricted upload permissions. Do not switch to `pull_request_target` to run
untrusted pull-request code with a privileged token.

For persistent Code Scanning history, upload a complete report using
`--no-baseline`, then enforce the baseline separately. Uploading only new findings
is supported but intentionally omits existing debt and can close those alerts.
Reports contain source snippets and evidence; inspect them before uploading.

## Schema validation (development only)

```sh
python -m scripts.check_sarif
# Offline, using an exact copy of the pinned schema:
python -m scripts.check_sarif --schema /path/to/sarif-schema-2.1.0.json
```

This development check uses `jsonschema` and a commit- and SHA-256-pinned OASIS
schema. It validates Python, notebook, clean, and error reports in CI and release
validation. Without `--schema` it downloads only that public schema; no reports
or source are sent anywhere. The scanner itself remains dependency-free and
offline. Schema validity does not guarantee a platform supports every SARIF field.
