# Initial Python compatibility assessment

**Decision, October 18, 2026:** keep the advertised scanner runtime at Python
3.12+ for this change. Investigate 3.11 as the first backport candidate, rather
than promising 3.10 support or adding a TOML dependency now.

## Runtime is not the scanned project's environment

Torchlight parses source without importing PySpark or the target project. A
Python 3.12 scanner can review older-Python Spark source from an isolated tool
environment. The project's interpreter does not have to be upgraded. The
scanner's native Python parser limits which source syntax it can parse; this is
not an independent target-language parser or a Spark/Python compatibility check.

For example, an environment with Python 3.12 installed can use:

```sh
python3.12 -m venv .torchlight-venv
.torchlight-venv/bin/python -m pip install torchlight-spark
.torchlight-venv/bin/torchlight jobs/
```

On Windows use the environment's `Scripts` directory. For pre-commit, an explicit
`language_version: python3.12` can decouple the hook from the project runtime.

## Source-level experiment

On macOS arm64, run the development source suite directly with isolated
CPython interpreters. This deliberately bypasses package metadata for research;
it is **not** evidence that the distribution supports older Python versions.

```sh
python3.10 -m unittest discover -s tests
python3.11 -m unittest discover -s tests
python3.12 -m unittest discover -s tests
python3.14 -m unittest discover -s tests
```

Initial observation with 94 tests, before later integration-test additions:

| Interpreter | Observation | Interpretation |
| --- | --- | --- |
| CPython 3.10.22 | Test imports fail on missing `tomllib`; 3.12 `type` statement also fails to parse. | Not a metadata-only backport. |
| CPython 3.11.17 | 93 pass; one error in `test_type_aliases_replace_existing_bindings` on `type df = int`. | Core and config are promising, but newer source grammar is unavailable. |
| CPython 3.12.15 | 94 pass. | Supported oldest-runtime source validation. |
| CPython 3.14.8 | 94 pass. | Supported newest-runtime source validation. |

These are local correctness probes, not performance, Spark-runtime, installation,
or cross-platform compatibility measurements. Reproduce the commands on a fixed
commit before making a support decision; the test count will grow.

## Audit and tradeoffs

- `torchlight/config.py` uses standard-library `tomllib`, available from 3.11.
  The existing distribution verification script also imports it. Supporting 3.10
  would require a parser dependency, vendored code, or a different config policy.
  None is justified while the dependency-free core remains a product goal.
- The runtime uses union annotations, built-in generic types, slotted-free
  dataclasses, pattern AST visitors, and ordinary pathlib operations. The initial
  probe did not expose another 3.11 import blocker. This is not a full API audit.
- `visit_TypeAlias` is name-dispatched and does not import `ast.TypeAlias`
  directly, but 3.11's parser cannot produce that 3.12 AST node. Other newer source
  grammar would also be unavailable on an older scanner runtime.
- The new tests use `contextlib.chdir` (3.11+). Lowering to 3.10 also requires a
  test helper replacement and an audit of all development/release scripts.
- Metadata, Ruff's `py312` target, supported-version documentation, CI, and
  installed wheel/sdist tests are an intentional support contract. Merely
  changing `requires-python` would not establish support.

## Next decision gate

Before advertising 3.11 support:

1. Ask early users whether an isolated 3.12 scanner solves their installation
   problem and collect the runtime versions they actually need.
2. Make syntax-specific tests conditional on parser capability, while preserving
   the 3.12+ checks and explicitly testing errors for unsupported source syntax.
3. Run the full corpus, CLI, pre-commit, wheel, and sdist verification on 3.11;
   add a permanent oldest-supported-runtime CI job, including platform coverage.
4. Audit newer grammar and AST-version behavior, and document source-language
   limits separately from scanner and Spark runtime compatibility.
5. Change metadata and lint targets only in that dedicated compatibility PR.

No Spark-version support matrix, Python backport, standalone executable, or
runtime dependency is introduced by this assessment.
