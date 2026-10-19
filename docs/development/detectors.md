# Internal detector boundary

The analyzer owns Python traversal, scopes, Spark identity inference, and state
transitions. `facts.py` defines immutable `Value` and `CallFacts` snapshots.
Detectors in `detectors.py` consume these facts and return `Diagnostic` records;
the analyzer attaches source coordinates, snippets, and structural fingerprints.

To add a detector:

1. Propose the required semantic evidence and known intentional uses first.
2. Add stable metadata to `diagnostics.RULES` and a detector with a matching ID.
3. Implement `check(CallFacts)` without accessing analyzer state, inferring types
   from variable names, or executing source. Add it to `DETECTORS`.
4. If necessary, add rule-independent facts to the analyzer, with tests for
   propagation, merging, shadowing, and notebook invalidation.
5. Add direct fact tests, positive/negative source tests, synthetic corpus cases,
   and a curated rule guide. Regenerate the catalog.

TL001–TL003 were migrated without changing their findings. Golden tests captured
from v0.3.0 protect their complete JSON/text output and fingerprints for Python
and notebook locations; the existing regression corpus protects broader behavior.

Implementation modules remain **internal**. Since v0.7.0 third parties instead use
the separately versioned exports in [torchlight.plugins](../plugins.md), registering
trusted objects explicitly through programmatic Config. The analyzer and built-in
registry remain private. No dynamic discovery, dependency loading, or sandbox is added.
