# Specification gaps

A gap is a place where the specification is wrong, ambiguous or incomplete. Each one is fixed **in the
specification**, with a decision entry, in the same commit that closes it (Overview §13.4; P1 exit gate).

| ID | Where | Problem | Proposed fix | Status |
|---|---|---|---|---|
| G-1 | Spec §6.2 step 2; Overview §10.6 | `random_state = seed_kmeans` is a u64; scikit-learn accepts only seeds below 2^32, so the build crashes (checked 27 Sep 2026: `ValueError: Seed must be between 0 and 2**32 - 1`). | `random_state = seed_kmeans mod 2^32`; add a decision entry. | open |
| G-2 | Spec §13.2 | `group_id` is "32, zero-padded" in the wrapped-record-key AD but unspecified in the wrapped-bucket-key and `S ‖ r_agg` ADs; §14.3 stores it zero-padded. | Write "`group_id` (32, zero-padded)" in all three rows. | open |
| G-3 | Spec §19.1, C-18 | C-18 "depends on C-7 via Python binding", but C-7 is built in P2, after P1. | C-18 uses libsodium via `rbcl` (an independent implementation, which strengthens the differential test); record as a decision. | open |
| G-4 | Spec §11.3 inputs; §10.4 | A "genesis log checkpoint" is a verifier input but is never defined and no step uses it; witnesses need a starting checkpoint. | Define genesis as tree_size 0, root `SHA-256("")`, signed at database creation; use it in a step or drop it from the inputs. | open |
