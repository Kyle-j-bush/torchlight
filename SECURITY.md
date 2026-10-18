# Security policy

Security fixes are currently provided on `main`; there are no released versions.
Use the latest commit.

## Reporting a vulnerability

Please [report vulnerabilities privately through GitHub](https://github.com/Kyle-j-bush/torchlight/security/advisories/new),
not in a public issue. Include the affected commit, a minimal reproduction, and
the potential impact. Do not include real credentials or private datasets.

There is no guaranteed response time or paid support agreement.

## Safe use

Torchlight parses source files and notebooks; it never executes their code,
magics, or shell commands. It has no third-party runtime dependencies.

Parsing is not a sandbox. Very large or specially crafted inputs can exhaust
memory or CPU. When scanning untrusted files, use an isolated environment with
resource limits, without credentials or access to sensitive files.
