# Security policy

Security fixes are provided on `main` and published in new releases. Use the
latest published version. Older releases do not receive backported fixes.

## Reporting a vulnerability

Please [report vulnerabilities privately through GitHub](https://github.com/Kyle-j-bush/torchlight/security/advisories/new),
not in a public issue. Include the affected commit, a minimal reproduction, and
the potential impact. Do not include real credentials or private datasets.

There is no guaranteed response time or paid support agreement.

## Safe use

Torchlight parses source files and notebooks; it never executes their code,
magics, or shell commands. It has no third-party runtime dependencies.
Analysis is local; source code is not sent to external APIs. Findings, JSON, and SARIF
reports can include file paths and source snippets, so review reports for secrets
or private code before publishing them.
Baseline files omit source snippets, but still reveal project paths and rule IDs.
Git comparison requires Git 2.45+, disables lazy fetching and execution helpers,
and never checks out historical source. Use a patched Git; parsing and invoking
Git on an untrusted repository are not a security sandbox.
The optional SARIF schema check is development tooling; it downloads a pinned
public schema, never uploads reports, and supports an offline local schema.

Since v0.7.0 the Python API can explicitly register trusted detector objects.
Plugins execute arbitrary local Python with your privileges: no sandbox, timeout,
dependency isolation, or network/filesystem restriction is provided. Rule selection
does not prevent plugin execution. Nothing auto-discovers plugins or loads them
from CLI/TOML policy. Inspect/pin their code and dependencies; never load an
untrusted plugin merely to scan untrusted source. See [plugin safety](docs/plugins.md).

The development corpus-validation runner requires local permission confirmation
and writes private artifacts outside this repository. Raw findings/labels/manifests
can contain private paths, snippets, and review notes. Even aggregate counts and
hashes can identify a small corpus: review publication permission separately.
The tooling never uploads these artifacts; filesystem modes are not encryption
or protection against privileged processes, shared ACLs, or backup/sync services.

Parsing is not a sandbox. Very large or specially crafted inputs can exhaust
memory or CPU. When scanning untrusted files, use an isolated environment with
resource limits, without credentials or access to sensitive files.
