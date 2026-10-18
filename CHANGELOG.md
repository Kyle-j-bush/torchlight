# Changelog

## 0.1.0 — 2026-10-18

- Initial PyPI release as `torchlight-spark`, with the `torchlight` command.
- Find `.collect()` and `.distinct()` calls in Python files and notebooks.
- Recursively scan directories while skipping common generated folders.
- Handle notebook magics, shell escapes, and top-level `await` without execution.
- Report findings and errors with file, cell, and line locations.
- No third-party runtime dependencies. Requires Python 3.12 or newer.
