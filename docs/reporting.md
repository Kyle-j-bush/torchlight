# Report identity

JSON schema version 1 gains an additive `fingerprint` field in v0.3.0. Existing
fields and source coordinates are unchanged. Consumers should accept extra fields.

A `v1:<sha256>` fingerprint identifies the rule, normalized call syntax, and
enclosing function/class names. It ignores line/column/cell numbers, comments,
formatting, quote style, evidence wording, and checkout location. Variable names,
literal values, and enclosing scope names are significant. The analyzer does not
execute code to compute identity.

Fingerprints are **content identity, not globally unique IDs**. Match them with
the project-relative file path. Renaming a file or changing the call/scope can
make a finding new. Identical calls in one scope (including across notebook cells)
share a fingerprint; consumers must compare occurrence counts, not just sets.
If one identical old call is removed while another is added, static matching
cannot distinguish them. Fingerprints do not prove semantic equivalence or safety.

The `v1` algorithm is a compatibility contract. Any incompatible identity change
must use a new prefix and document baseline migration. Manually constructed
`Finding` objects without analyzer structure fall back to their snippet text.
