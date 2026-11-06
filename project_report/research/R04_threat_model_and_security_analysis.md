# R04 · Threat model and security analysis

> **Prerequisites.** [07a](../07a_crypto_overview.md)–[07g](../07g_crypto_attack_testing.md), [14](../14_status_gaps_and_pending.md).

## Parties and trust

| Party | Trusted for | Not trusted for |
|---|---|---|
| User app | nothing secret | — |
| Application backend | holds account keys and `r_t`, authenticates users, decides who may delete (§3.3) | — (it is the operator's side) |
| Engine / operator | running honestly *during* the claim's window | the certificate checks do not trust its word: they check signatures and arithmetic |
| Witnesses | an honest majority (≥ 4 of 5) checking log consistency | in v1 they are **simulated** on the operator's machine (L-7) |
| Platform | OS, filesystem overwrite in place, no swap/hibernation leakage (checked at startup) | hardware attacks, SSD firmware remapping, side channels (L-1, L-26) |
| Verifier user | runs `sever-verify` with correct anchors | — |

## Attackers

1. **Raw-storage attacker after deletion** (stolen disk image, backups of data dir): sees WAL, checkpoints,
   free space. **Guarantee:** nothing deleted is recoverable, given the key directory's old slots were
   overwritten (§13.5). **Evidence:** P4-T1/T2, 0 findings in 30 scans; SB-24 … SB-30 found
   [DATA: line 159]; startup refusals [CODE: crates/sever-platform/src/lib.rs:L69-L120].
2. **Dishonest operator forging receipts** (holds the operator key): **Guarantee:** any certificate whose
   arithmetic, proof, inclusion, witness cosignatures or ordering is wrong is rejected at a named step.
   **Evidence:** AT-1 … AT-20, 226,410 rejected [DATA: lines 206, 208]; auditor faults AF-1 … AF-5.
3. **Log equivocation** (different histories to different users): witnesses and the auditor's
   consistency checks — **weakened in v1** because witnesses are simulated.
4. **Crash / power loss**: no partial deletion, no lost acknowledged operation [DATA: lines 56, 144, 164, 192].

## What is NOT guaranteed

- A dishonest operator can copy data or keys before deleting (L-2); it holds every account key and `r_t` (L-27).
- A certificate does not prove its own deletion leaf was appended to the public log (L-13; auditor needed).
- No independent witnesses in v1 (L-7); no independent cryptographic review (L-21).
- Device-level erasure of the 512-byte key slot is assumed (L-1); SSD wear-levelling is out of scope.
- Side channels (L-26); the visible metadata of §13.2 (counts, `C_S`, centroids, group sizes, key versions) (L-5).
- An emptied group's proof is not context-bound (G-34); soundness relies on step 6 and the signature.

## Cryptographic assumptions

Discrete-log hardness in ristretto255; random-oracle model for Fiat–Shamir (SHA-512) [DOC: docs/SOUNDNESS.md];
Ed25519 unforgeability; AES-256-GCM-SIV security with random 96-bit nonces; collision resistance of SHA-256.

## Mapping guarantees to tests

| Guarantee | Tests |
|---|---|
| exactness | P1-T1/T2, survivors check, SB-1…SB-9 |
| crash atomicity | P2-T1…T3, P3-T4, P4-T3, SB-11…SB-15 |
| certificate soundness | P3-T1/T2, P4-T9, SB-16…SB-23, soundness tests |
| erasure | P4-T1/T2, SB-24…SB-30, INV-14 tests |
| platform | `sever-platform` contract and rule tests |
