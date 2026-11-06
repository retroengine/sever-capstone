# R10 · Likely viva and guide questions (with answers)

## Concepts

1. **What is a vector database?** — Stores embeddings and returns the nearest ones to a query ([B01](../background/B01_vectors_embeddings_and_search.md)).
2. **What is a "ghost"?** — The trace a deletion leaves: tombstone, biased centroid, float drift, disk copies.
3. **Why do floats cause ghosts?** — Rounding: `(a+b)−b ≠ a` in general ([B03](../background/B03_floating_point_vs_exact_integers.md)).
4. **What is Q24?** — `x̃ = round_half_to_even(x·2^24)` stored as `i32`.
5. **Why can `S` not overflow?** — ≤ 10⁶ members × |x̃| ≤ 2^24+16 < 2^44 in an `i64`.
6. **Why round half to even?** — Unbiased in long sums.
7. **What is IVF-flat?** — Centroid-selected groups scanned exhaustively; probes ⌈k/4⌉ groups.
8. **Why not HNSW?** — A deleted node leaves traces in neighbours' edges (§8.3).
9. **What is the holding area?** — A non-searchable waiting room for out-of-distribution vectors until 200 form a spawned group.
10. **What are the five fields of equivalence?** — `S`, `n`, `C_S`, canonical blob, member IDs.

## Design choices

11. **Why fit groups on SciQ, not user data?** — Groups must hold no user data and never move (DB-41); one deletion touches one group.
12. **Why ban counter-shaped IDs?** — Group contents must not depend on arrival order (§3.2).
13. **Why plan/apply?** — All validation before any change; `apply` cannot fail.
14. **Where is the commit point?** — The fsync of the WAL COMMIT record (protocol step 5).
15. **Why never retry a failed fsync?** — Linux may have dropped the data; a retry can falsely succeed.
16. **How is `delete_user` all-or-nothing?** — One ChangeSet, one transaction.
17. **Why is search never exact?** — IVF probes only some groups; deletion is exact, search approximate.

## Cryptography

18. **What is a Pedersen commitment?** — `r·H + Σ v_i·G_i`; hiding and binding; additive.
19. **How does the verifier check the deletion arithmetic?** — `C_S_post + C_t == C_S_pre` (step 6).
20. **What does the proof prove?** — Knowledge of the opening of `C_S_post`, bound to a 152-byte context.
21. **Why hedged nonces?** — A repeated nonce would reveal the group's whole sum.
22. **What is G-34?** — An emptied group's proof verifies under any context; spec corrected, attack donors changed.
23. **Why a transparency log?** — Pins the record's insert under a signed, witnessed, append-only history.
24. **Are the witnesses independent?** — No; simulated in v1, keys on the operator's machine (L-7).
25. **Why AES-GCM-SIV?** — AEAD with nonce-misuse resistance.
26. **What is crypto-shredding?** — Destroying keys so all ciphertext copies become unreadable.
27. **Why write the new key before COMMIT and erase the old after?** — Re-wrapped data must stay decryptable; rollback must remain possible (INV-13; SB-27).
28. **What if the crash is between COMMIT and erase?** — Recovery erases the stale slot (INV-14).
29. **Why must two accumulator versions never survive?** — `S_pre − S_post` would be the deleted vector.
30. **Does the verifier share code with the engine?** — No; separate workspace; one no-op dev-dependency for test labels.

## Testing and results

31. **What is the main oracle?** — Independent Python reference models; golden values never from the engine.
32. **What is a sabotage build?** — Same source with one deliberate bug; a test must turn red.
33. **What is a red proof?** — A patch breaking one rule that must turn its labelled test red.
34. **What is fair testing?** — Fresh sandboxed AI sessions test the sealed engine from the spec; a different model judges.
35. **Biggest bug found?** — BH-5 (keys lost after a crash + clean restart) and BH-9 (log erased on open).
36. **Headline numbers?** — 0 survivor failures (427,455), 0 crash failures (938,129 points), 226,410 attacks rejected, 0 forensic findings ([11](../11_results.md)).
37. **What failed?** — T-5 search stability not met; EX-8 not completed; P4-T10 first passed by owner acceptance.
38. **Cost of provable erasure?** — ~75–110 ms and ~39 KB per delete vs ~1 ms and 11 B for soft delete (EX-7).

## Limitations and "why not X?"

39. **Why not just use FAISS `remove_ids`?** — No exactness of summaries, no receipt, no disk erasure; unsupported for some IVF types.
40. **Why not just encrypt the disk?** — Disk encryption does not destroy per-record keys on deletion; the live key opens old copies.
41. **Can SEVER-DB stop a dishonest operator?** — No; it can copy data first (L-2, L-27).
42. **Does erasure hold on SSDs?** — It assumes in-place overwrite of a 512-byte slot (L-1); firmware remapping is out of scope.
43. **Why a laptop run instead of HPC?** — HPC became unavailable (DB-113); sizes scoped in advance by cost.
44. **What would you do next?** — Independent witnesses, client-held keys, full-size runs, EX-8, cheaper recovery check.
