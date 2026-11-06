# R03 · Contributions (with honest strength of each claim)

> **Prerequisites.** [01](../01_overview_and_core_idea.md), [R02](R02_related_work.md).

No contribution below is claimed to be "the first": the related-work search was incomplete
([R02](R02_related_work.md)). Each is stated as what the project built and showed.

| # | Contribution | Evidence | Contrast | Strength of the claim |
|---|---|---|---|---|
| C1 | An IVF-flat index with fixed, publicly fitted groups and exact Q24 integer accumulators, so deletion restores each group bit for bit (five-field equivalence) | [CODE: crates/sever-index/src/index.rs:L747-L836, blob.rs:L152-L234]; 0 survivor failures over 427,455 + 43,562 + 275,114 checks [DATA: lines 38, 13, 19] | float centroids/means keep a ghost; graph indexes keep structural traces (§8.3) | **Strong for the engineering result**; novelty unverified |
| C2 | Crash safety of that exactness, with an explicit commit point and all-or-nothing multi-group `delete_user` | 343,837 crash points (P2), 938,129 (P3), 0 failures [DATA: lines 56, 144] | standard WAL design; the contribution is the tested combination | **Strong evidence, standard technique** |
| C3 | Per-deletion certificate: homomorphic Pedersen arithmetic `C_S_post + C_t = C_S_pre`, a context-bound proof of knowledge, insert inclusion under a witnessed RFC 9162 checkpoint, verifiable offline by an independent verifier | [CODE: verifier/src/verify.rs:L76-L238]; 5,000 accepted, 226,410 attacks rejected [DATA: line 206] | CT logs do not cover content deletion | **Moderate**: own soundness argument only (L-21); witnesses simulated (L-7) |
| C4 | Crypto-shredding integrated into the deletion transaction (rotation, key written before COMMIT, old key zeroed after, recovery rule INV-14) | [CODE: crates/sever-erasure/src/participant.rs:L1-L9, L289-L340]; 0 findings in 30 raw-image scans; sabotage builds found [DATA: line 159] | generic crypto-erase guidance (NIST SP 800-88r2) | **Moderate**: evidence on tested images, not a proof (L-18); device-dependent (L-1) |
| C5 | An evaluation methodology: pre-registered gates vs measures, independent reference models, sabotage, red proofs, clean-room AI fair testing | [CODE: configs/experiments.yaml; configs/fair.yaml; tests/proofs/]; 293 requirements traced | — | **Methodological**; useful for the report's Testing chapter |
| C6 | Measured cost of provable deletion vs no-erasure vs soft delete (EX-7) | [DATA: lines 184, 186] | — | **Descriptive**, scoped to nq-10k (5 seeds) and nq-100k (1 seed) |
| C7 | A negative result: deletion drift target T-5 not met (0.008–0.013 vs 0.005) | [DATA: line 161] | — | **Honest finding** worth reporting |
| C8 | A spec-level finding: Schnorr-style proofs for the identity commitment are context-free (G-34) | [DOC: SPEC_GAPS G-34, DB-95] | — | **Small but concrete**; likely known in the literature [CITATION NEEDED] |

[TODO: author] decide which of C1–C4 to headline after a proper literature search.
