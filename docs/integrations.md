# CI and pre-commit

Run from the repository root so local commands, hooks, and CI discover the same
[project policy](configuration.md). Do not treat an errors-only scan as clean.

```sh
torchlight --format json jobs/ notebooks/ > torchlight-report.json
torchlight --format github jobs/ notebooks/
torchlight --format sarif jobs/ notebooks/ > torchlight.sarif
```

Exit codes: **0** clean, **1** findings (even if errors also occurred), **2** errors
only. Configuration and baseline errors abort before scanning with status 2.
All findings are warnings. An active [baseline](baselines.md) removes reviewed
existing findings before reporting and deciding the exit code, but never hides
scan errors. Successful `--write-baseline` capture exits 0; failed capture exits
2 without updating the file. Configurable severities are not implemented.

JSON uses `schema_version: 1`, with `findings` and `errors`; errors also go to
stderr. Findings include rule ID, source coordinates, evidence, explanation,
recommendation, snippet, and structural fingerprint. GitHub output escapes workflow-command characters.
Notebook annotations are file-level, with code-cell coordinates in the message;
they do not pretend cell lines are physical JSON lines.

## GitHub Actions

After setting up Python 3.12+ in your workflow:

```yaml
- name: Install Torchlight
  run: python -m pip install torchlight-spark==0.3.0
- name: Review Spark code
  run: torchlight --format github jobs/ notebooks/
```

Version 0.3.0 supports project configuration, baselines, and SARIF. Run from your
project's root. Pin setup and checkout actions by full commit SHA in production
workflows.

### GitHub Code Scanning

Copy the [complete pinned workflow](../.github/examples/torchlight-code-scanning.yml)
into your project's `.github/workflows/` directory. It uses SARIF 2.1.0 and
`security-events: write`. It uploads a full `--no-baseline` report **before** a
separate policy-enforcement scan fails on new findings. This preserves existing
alert history without requiring all existing debt to pass CI.

Do not let exit 1 skip the upload, or treat all nonzero exits as harmless.
Scan errors mark the SARIF invocation unsuccessful, and still fail the workflow.
Code Scanning availability depends on your repository and GitHub plan. Upload
permissions can be restricted on fork pull requests; do not execute untrusted
code with a privileged `pull_request_target` token. See [SARIF locations,
fingerprints, and limitations](reporting.md).

## Pre-commit

```yaml
repos:
  - repo: https://github.com/Kyle-j-bush/torchlight
    rev: v0.3.0
    hooks:
      - id: torchlight
```

Use an immutable release or full commit SHA containing the desired feature.
Pre-commit supplies explicit changed file paths; configured excludes and baselines still apply
to those paths. It uses an isolated scanner environment, not the Spark runtime.
If its default interpreter is older than 3.12, set `language_version: python3.12`
under the hook and ensure that interpreter is installed.

To test a local checkout without publishing:

```sh
pre-commit validate-manifest .pre-commit-hooks.yaml
pre-commit try-repo . torchlight --all-files
```

Reports can contain source snippets; inspect them before uploading artifacts.
Never put private code, notebook outputs, or credentials in issue reports.
