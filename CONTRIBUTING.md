# Contributing

Use Python 3.12 or newer. Create a virtual environment, activate it, then install
the development tools:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell instead.

## Making changes

1. Fork the repository if you do not have write access.
2. Create a branch, for example `git switch -c fix/notebook-parsing`.
3. Keep changes focused and add regression tests for behavior changes.
4. Run the same checks as CI:

   ```sh
   python -m ruff check .
   python -m ruff format --check .
    python -m unittest discover -s tests -v
    python -m scripts.check_benchmark
   ```

    To fix formatting, run `python -m ruff format .`.

5. Push your branch and open a pull request against `main`.

For packaging changes, also build and test both distributions:

```sh
python -m build
python -m twine check --strict dist/*
python scripts/check_distribution.py
```

Start with an empty build directory so that old versions are not tested or
published accidentally. To avoid disturbing existing `dist/` artifacts, build
into a fresh directory with `python -m build --outdir <directory>` and verify it
with `python scripts/check_distribution.py --dist-dir <directory>`.

The verification script installs each archive in a
fresh virtual environment and checks metadata and license files, runs the test
suite against the installed package, and tests both CLI entry points outside
the source tree.

Do not commit credentials, private data, virtual environments, or notebook
outputs containing sensitive information. Report security issues privately as
described in [SECURITY.md](SECURITY.md).

## Adding or changing checks

- Keep rule IDs in `torchlight/diagnostics.py` stable. Findings must contain
  receiver/pattern evidence, a qualified explanation, and a useful review suggestion.
- Do not turn unknown method names into Spark evidence. Prefer losing type
  knowledge over propagating a guessed DataFrame through an unsupported API.
- Add both positive and negative unit tests, including intentional uses and
  unrelated receivers. Extend the [labeled regression corpus](benchmarks/README.md)
  when changing analysis behavior. Fixture code must never be executed.
- Test notebook state, scopes, aliases, and invalidation when relevant. A limit is
  not a memory guarantee, and an expensive operation is not automatically wrong.
- Do not add automatic rewrites that can change result semantics. Suppressions
  must remain specific and reasoned; malformed directives must not hide findings.
- Treat JSON fields and rule IDs as integration interfaces. Explain incompatible
  changes in `CHANGELOG.md`. Scanners return structured `Finding` objects.

To exercise the repository's hook manifest, install pre-commit in a development
environment, then run:

```sh
pre-commit validate-manifest .pre-commit-hooks.yaml
pre-commit try-repo . torchlight --all-files
```

Remote configurations should pin an immutable revision containing the manifest.
Do not document an unreleased hook or CLI option as available in an older release.

## Main branch policy

All changes, including the owner's, must go through pull requests. CI and CodeQL
must pass against an up-to-date branch, and review conversations must be resolved.
High- and critical-severity CodeQL security findings block merging. Another
person's approval is welcome but is not required for this single-maintainer
project. Only squash merges are enabled.

Direct pushes, force-pushes, and deletion of `main` are blocked, with no bypass
actors. These protections are configured in GitHub; the intended rules are
recorded in [`.github/rulesets/main.json`](.github/rulesets/main.json). Editing
that file does not automatically change the live settings. Repository owners
can still edit the settings in GitHub.

GitHub Actions have read-only repository access by default. CodeQL has permission
to upload security results; only the publishing job can request a PyPI OIDC
identity token. Actions are pinned to commit SHAs;
Dependabot proposes updates to those pins and development dependencies. Updates
must pass the same checks and are not merged automatically.

## Publishing a release

The PyPI distribution is `torchlight-spark`; its CLI and import package remain
`torchlight`. Releases use GitHub Trusted Publishing, not stored API tokens.

One-time setup in PyPI's account publishing settings:

- Project: `torchlight-spark`
- GitHub owner/repository: `Kyle-j-bush/torchlight`
- Workflow: `publish.yml`
- Environment: `pypi`

The GitHub `pypi` environment permits only `v*` tags. Version tags cannot be
changed or deleted; the intended rules are in
[`.github/rulesets/releases.json`](.github/rulesets/releases.json). The repository
allows the official PyPA publishing action in addition to GitHub-owned actions,
and requires full commit-SHA pins for both.

For each release:

1. Update `project.version` in `pyproject.toml` and `CHANGELOG.md` through a PR.
2. Merge the PR and wait for CI and CodeQL to pass on `main`.
3. Tag that tested commit as `v<version>` and push the tag.
4. Publish a GitHub release for that tag. This starts `publish.yml`.
5. Verify the workflow and installation from PyPI before announcing the release.

The release workflow verifies that the tag matches the package version and is
on `main`'s history, rebuilds and tests both archives, then passes only those
artifacts to the isolated publishing job. It publishes provenance attestations
alongside the package. TestPyPI is not used.

PyPI versions and version tags are immutable: fix a bad release with a new
version rather than replacing existing files.

## License

Contributions are accepted under the [Apache License 2.0](LICENSE). Only submit
code you have the right to contribute, and preserve applicable notices.
