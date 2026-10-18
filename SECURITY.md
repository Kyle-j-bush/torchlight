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
The optional SARIF schema check is development tooling; it downloads a pinned
public schema, never uploads reports, and supports an offline local schema.

Parsing is not a sandbox. Very large or specially crafted inputs can exhaust
memory or CPU. When scanning untrusted files, use an isolated environment with
resource limits, without credentials or access to sensitive files.
