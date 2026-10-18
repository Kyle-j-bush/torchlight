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
   ```

   To fix formatting, run `python -m ruff format .`.

5. Push your branch and open a pull request against `main`.

Do not commit credentials, private data, virtual environments, or notebook
outputs containing sensitive information. Report security issues privately as
described in [SECURITY.md](SECURITY.md).

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

GitHub Actions have read-only repository access by default. CodeQL alone has
permission to upload security results. Actions are pinned to commit SHAs;
Dependabot proposes updates to those pins and development dependencies. Updates
must pass the same checks and are not merged automatically.

## License

Contributions are accepted under the [Apache License 2.0](LICENSE). Only submit
code you have the right to contribute, and preserve applicable notices.
