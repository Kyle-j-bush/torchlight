# CI and pre-commit

Run from the repository root so local commands, hooks, and CI discover the same
[project policy](configuration.md). Do not treat an errors-only scan as clean.

```sh
torchlight --format json jobs/ notebooks/ > torchlight-report.json
torchlight --format github jobs/ notebooks/
```

Exit codes: **0** clean, **1** findings (even if errors also occurred), **2** errors
only. Configuration errors abort before scanning with status 2. All enabled,
unsuppressed findings are warnings and fail the run. Baselines, "new findings
only", configurable severities, and SARIF are not implemented.

JSON uses `schema_version: 1`, with `findings` and `errors`; errors also go to
stderr. Findings include rule ID, source coordinates, evidence, explanation,
recommendation, and snippet. GitHub output escapes workflow-command characters.
Notebook annotations are file-level, with code-cell coordinates in the message;
they do not pretend cell lines are physical JSON lines.

## GitHub Actions

After setting up Python 3.12+ in your workflow:

```yaml
- name: Install Torchlight
  run: python -m pip install torchlight-spark==0.2.0
- name: Review Spark code
  run: torchlight --format github jobs/ notebooks/
```

The published 0.2.0 version supports the rules and output above, **not project
configuration**. To use the unreleased configuration on your own project, install
an immutable commit containing it, then run from your project's root. Pin setup
and checkout actions by full commit SHA in production workflows.

## Pre-commit

```yaml
repos:
  - repo: https://github.com/Kyle-j-bush/torchlight
    rev: v0.2.0
    hooks:
      - id: torchlight
```

Use an immutable revision containing the desired feature. For unreleased project
configuration, replace `v0.2.0` with a full commit SHA containing this change.
Pre-commit supplies explicit changed file paths; configured excludes still apply
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
