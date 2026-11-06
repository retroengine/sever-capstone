# 07g · Attack testing: AT-1 … AT-20, AF-1 … AF-5 and SB-16 … SB-30

## In simple words

A verifier that accepts everything is useless. So SEVER-DB keeps a register of attacks — ways a
**dishonest operator holding the operator key** could try to forge or tamper with a certificate — and
checks that the independent verifier rejects every one at an allowed step. It also keeps registers of
log faults for the auditor, and of deliberate bugs (sabotage) that the tests must catch.

> **Prerequisites.** [07d](07d_deletion_certificate_and_verification.md) (verifier steps),
> [B05](background/B05_software_testing_concepts.md) (sabotage, oracles). Glossary:
> [attack register](16_glossary.md#at-n-attack-register), [sabotage build](16_glossary.md#sabotage-build).

## The problem this solves

Tests written by the author of the code tend to test what the author thought of. A register fixed in
advance (`spec/registers_p3.yaml`) and generated against real certificates forces every listed attack
to be tried thousands of times.

## How the attack suite works

- The attacker holds the operator key. `resign: true` means the forged certificate is re-signed, so the
  targeted rule is reached instead of failing at the signature; **AT-4 alone is not re-signed**, to show
  the trailer covers every field [CODE: spec/registers_p3.yaml:L4-L11].
- `sever-crashkit-p3 attacks` generates 1,000 honest certificates per seed and every applicable attack on
  each, and the independent `sever-verify` judges them; the suite checks each rejection step is one the
  register allows [CODE: crates/sever-crashkit-p3/src/attacks.rs].
- The Python reference model produced `golden/p3_attacks.json` with the expected step per variant.

**Illustrative example, not from the repository:** take an honest certificate, flip one bit of tag 10
(`database_lsn`) and do not re-sign it (AT-4). The verifier reaches step 2, recomputes the Ed25519
check over `DST_CERT ‖ body`, and rejects: "the operator signature does not verify".

## The attack register (Part 3; re-run on the final build as P4-T9)

| ID | Attack | Allowed steps | Instances, seed 42 (all rejected) |
|---|---|---|---|
| AT-1 | forged proof | 6 | 1,798 |
| AT-2 | proof copied from another certificate | 6 | 899 |
| AT-3 | substituted `C_t` | 3, 6 | 1,000 |
| AT-4 | single-field tamper of tags 1–13 and the trailer, **not** re-signed (14 variants) | 1, 2 | 12,586 |
| AT-5 | unknown operator epoch | 2 | 1,000 |
| AT-6 | insert leaf from another collection | 3 | 1,000 |
| AT-7 | wrong inclusion path | 3 | 1,999 |
| AT-8 | checkpoint signed by the wrong key | 3 | 1,000 |
| AT-9 | three instead of four cosignatures | 4 | 1,000 |
| AT-10 | cosignatures over a different checkpoint | 4 | 1,000 |
| AT-11 | non-canonical point or scalar | 1 | 1,798 |
| AT-12 | identity as `C_t` | 1 | 1,000 |
| AT-13 | holding-area certificate with arithmetic fields | 7 | 303 |
| AT-14 | `group_emptied` inconsistent with `C_S_post` | 6 | 899 |
| AT-15 | `database_lsn` not after the insert leaf | 5 | 1,000 |
| AT-16 | malformed TLV (missing, repeated, reordered tag, trailing bytes) | 1 | 5,000 |
| AT-17 | four cosignatures, two from the same witness | 4 | 1,000 |
| AT-18 | wrong fixed length, or tag 11/12 outside {0, 1} | 1 | 6,000 |
| AT-19 | insert leaf type ≠ `0x01`, or inclusion version ≠ 1 | 1, 3 | 2,000 |
| AT-20 | checkpoint or cosignature under an epoch/witness not in the anchors | 3, 4 | 3,000 |

[CODE: spec/registers_p3.yaml; DATA: results/p3-attacks-nq-10k-20261101T085746Z.json seed 42 `judged`].
Totals over five seeds: **5,000 honest accepted, 226,410 attacks rejected, 0 wrongly judged**
[DATA: docs/RUN_LEDGER.jsonl line 206 (P3-T1/T2) and line 208 (P4-T9 on the final build)]. Counts below
1,000 reflect which certificates an attack applies to; AT-2 and AT-13 donors exclude emptied-group
certificates since DB-95 [INFERRED; DOC: DB-95].

**Found by this suite:** the emptied-group replay (G-34): before DB-95, AT-2 was *accepted* in 3 of about
900 instances because an emptied group's proof verifies under any context
([07b Step 9](07b_pedersen_commitments_and_proofs.md)). The first three P3-T1/T2 runs are recorded FAIL
(ledger lines 103, 113, 119) before the PASS on line 123.

## Auditor faults AF-1 … AF-5 (gate P3-T6)

Listed in [07d Step 5](07d_deletion_certificate_and_verification.md#step-5--the-log-auditor-sever-audit);
expected findings come from `golden/p3_audit.json`, produced by `python/sever_refmodel_certs/audit.py`.

## Sabotage items of Parts 3 and 4

Each is the real code built with one deliberate bug (`--features sabotage-SB-N`); `tests/sabotage/run.sh`
passes only if a test turns red [CODE: tests/sabotage/run.sh].

| SB | Crate / location | Deliberate bug |
|---|---|---|
| SB-16 | sever-crypto posk.rs:L60-L69 | challenge hashes `A` before `C_S_post` |
| SB-17 | posk.rs:L70-L73 | deletion context left out of the challenge |
| SB-18 | nonce.rs:L91-L112, L159-L162 | zero-entropy nonces (nonce reuse) |
| SB-19 | group.rs:L43-L47 | non-canonical scalars reduced instead of rejected (points unaffected — see 14) |
| SB-20 | sever-log checkpoint.rs:L16-L20 | witness threshold 3 instead of 4 |
| SB-21 | sever-p3 lib.rs:L156-L167 | certificate and delete leaf made durable before COMMIT |
| SB-22 | sever-cert builder.rs:L140-L143 | `group_emptied` when `n_post ≤ 1` |
| SB-23 | posk.rs:L75-L83 | challenge reduced from 32 bytes instead of 64 |
| SB-24 | sever-seal ring.rs:L251 | skip group-key rotation |
| SB-25 | sever-erasure participant.rs:L256 | skip bucket-key rotation |
| SB-26 | participant.rs:L256 | skip holding-area rotation on flush |
| SB-27 | participant.rs:L316-L319 | erase the old key before COMMIT |
| SB-28 | sever-seal sealer.rs:L81-L99 | write a plaintext vector into the WAL |
| SB-29 | sever-seal block.rs:L75-L86 | write an unwrapped key to disk |
| SB-30 | sever-seal aead.rs:L21-L24 | reuse an AEAD nonce |

[CODE: locations from `grep -rn "sabotage-SB-"` in this session and _notes/part3.md §11; register: Build
§2.6 table, docs/SEVER-DB_BUILD_PLAN_PART_1-2.md:L282-L288].

The Part 4 items must also produce **scanner findings** on a real image (P4-T2). Recorded findings:
SB-24 2,374 (561 deleted payloads, 612 deleted record keys, 1,201 retired accumulators); SB-25 1,178;
SB-26 924; SB-28 4,246 (2,122 plaintext vectors, 2,124 `r_t`); SB-29 65,738 retired keys; SB-30 65,229
nonce reuses [DATA: results/p4-forensics-nq-10k-20261030T141339Z.json `sensitivity`]. SB-27 has no
scanner entry in that file; it is caught by the crash campaign and tests [INFERRED: absent from
`sensitivity.items`; DOC: Build 3-4 §2.10 "where it applies"].

## Everyday analogy

*Analogy:* The attack register is a bank's list of known forgery tricks; every new banknote design is
tested against each trick before release. *Where it stops:* a list only covers tricks someone thought
of. That is why the project also uses fuzzing and clean-room fair testing ([10](10_testing_methodology.md)).

## Key points to remember

- 20 attack types, generated against 1,000 honest certificates per seed, five seeds.
- 226,410 attacks rejected, 5,000 honest accepted, on both Part 3 and the final build.
- The attack suite found a real spec error (G-34).
- 15 sabotage items for Parts 3–4; Part 4's must also show up in the forensic scan.

## Check your understanding

1. *Why are most attacks re-signed?* — To reach the rule under test rather than fail at the signature.
2. *Which step rejects a forged proof?* — Step 6.
3. *What did AT-2 reveal?* — Emptied-group proofs are not bound to their context (G-34).
4. *What does SB-27 break?* — It erases the old key before the commit is durable.
5. *Which sabotage leaks the deleted vector through accumulators?* — SB-24 (1,201 retired accumulators found).
