# SEVER-DB — Build Plan: Part 3 and Part 4

| | |
|---|---|
| **Document** | SEVER-DB build plan, Parts 3–4 |
| **Companions** | `SEVER-DB_BUILD_PLAN_PART_1-2.md` (the four-part structure, standards, extension points, Parts 1–2) · `SEVER-DB_PROJECT_OVERVIEW.md` · `SEVER-DB_SPECIFICATION.md` |
| **Status** | Proposed for review |
| **Covers** | Part 3 (The Receipt), Part 4 (The Erasure and the complete system), and the cross-part registers |

---

## Contents

0. [Relation to the first plan](#0-relation-to-the-first-plan)
1. [Part 3 — The Receipt](#1-part-3--the-receipt)
2. [Part 4 — The Erasure](#2-part-4--the-erasure)
3. [Cross-part registers](#3-cross-part-registers)

---

## 0. Relation to the first plan

Everything in the first plan's sections 0–3 applies here unchanged and is not repeated:

- the freeze rule, including errata (F-1 to F-6);
- the engineering standards;
- the test levels L1–L14, spec-based testing, trace-based differential testing, and gates versus
  measurements;
- the sabotage register (SB-16 to SB-23 belong to Part 3, SB-24 to SB-30 to Part 4);
- the definition of done;
- extension points EP-1 to EP-9.

**Preconditions.** Part 3 starts only when Parts 1 and 2 are frozen. Part 4 starts only when Part 3 is
frozen. Neither part edits a frozen file. Each adds new crates and packages, and plugs into the
extension points the earlier parts declared.

---

## 1. Part 3 — The Receipt

### 1.1 Announcement

**What it is.** Verifiable deletion. Part 3 adds:

- the cryptography: generators, Pedersen commitments, the proof of knowledge, hedged nonces and
  signatures;
- the commitment extension that plugs into Part 1's groups;
- the RFC 9162 transparency log, with log checkpoints and simulated witnesses, as a transaction
  participant in Part 2;
- deletion certificates;
- an independent verifier and an auditor;
- the SDK helpers that run on the application backend (spec §3.3).

**Why it exists.** Parts 1 and 2 make deletion exact and durable, but only the operator can see that.
Part 3 lets anyone check a deletion from the certificate alone.

**What Part 3 may claim, once its gates pass.** Every deletion from a group yields a certificate that a
program sharing no code with the engine accepts. The certificate proves:

1. the record was inserted under the account's key in a signed, witnessed log;
2. the group's accounting moved by exactly that record (its commitment moved by exactly `C_t`);
3. the operator knows an opening of the new group state.

Every tampered certificate is rejected, and a certificate, its log leaf and its state change commit
atomically. Exactness now covers all five fields of the equivalence relation, including `C_S` and
`r_agg`.

**What Part 3 does not claim.** Anything about erasure or confidentiality: the database is still
plaintext on disk (first plan, DB-48). It also cannot protect against an operator who keeps a copy
(overview L-2), and it does not prove that the user personally authorised a deletion, because the
application backend holds the account keys and decides who may delete (overview L-27). The witnesses
are simulated (L-7).

### 1.2 Goals

| ID | Goal |
|---|---|
| **P3-G1** | The cryptographic primitives of spec §9, each checked against third-party test vectors |
| **P3-G2** | `CommitmentExtension` (EP-1): `C_S` and `r_agg` updated in lockstep with `S`; each deletion integrity-checked against the stored `r_t` |
| **P3-G3** | The transparency log (spec §10) as a transaction participant (EP-7), with on-demand log checkpoints |
| **P3-G4** | Simulated witnesses behind a new extension point (EP-10) |
| **P3-G5** | Deletion certificates (spec §11.1–11.2), committed atomically with their deletion |
| **P3-G6** | The verifier (spec §11.3) in a separate workspace that shares no code with the engine |
| **P3-G7** | The auditor, for what a certificate cannot prove by itself |
| **P3-G8** | The SDK helpers for the application backend (spec §16.2): account (user) keys, `prepare_insert`, and no way to inject randomness |
| **P3-G9** | `docs/SOUNDNESS.md`: completeness, special soundness with an extractor, and honest-verifier zero-knowledge with a simulator, each backed by an executable test |

### 1.3 Scope

**In:** spec §3.3, §4.5, §9 (all), §10, §11, the certificate and log steps of §15.1 and §15.3, §16.2,
§16.3 (`sever-verify`, `sever-audit`), INV-3, INV-10 and INV-15. Appendix B vectors 1, 2, 3, 4, 6, 8
(the full `SEVERG` blob) and 9.

**Out:** encryption, keys, rotation and physical erasure (Part 4).

### 1.4 Modules

| Crate or package | Responsibility | Spec |
|---|---|---|
| `sever-crypto` | Generators and their startup self-check; the integer-to-scalar map; commitments; proof of knowledge (prove and verify); hedged nonces with `StrictProofRng`; Ed25519 with domain strings and `verify_strict`; HMAC helpers; canonical decoding | §4.5, §9 |
| `sever-commit` | `CommitmentExtension` implementing EP-1 | §5.3, §9.3–9.4 |
| `sever-log` | The RFC 9162 tree, leaves, inclusion and consistency proofs, log checkpoints, and `LogParticipant` (EP-7); declares EP-10 `Witness` and ships `SimulatedWitness` | §10 |
| `sever-cert` | Certificate TLV encoding and parsing; the builder, which works from the `ChangeSet`, the proof and the inclusion data; operator signing by epoch | §11.1–11.2 |
| `sever-p3` | Composition root `Engine<CommitmentExtension, PlaintextSealer, (LogParticipant)>` and its CLI | — |
| `sever-py-p3` / `sever_db_p3` | SDK, run on the application backend: `UserKey`, `prepare_insert` (quantise, draw `r_t`, compute `C_t`, sign) | §16.2 |
| `verifier/` (separate workspace) | `sever-verify`: its own parser, generator derivation, proof check, Merkle check, signature checks and bundled trust anchors | §11.3 |
| `audit/` (separate crate) | `sever-audit`: deletion leaves, certificate chains, log consistency. Reuses verifier code by **copying** it, not by a path dependency | §11.3 "what it does not prove" |
| `sever_refmodel_certs` (Python) | Model of the certificate arithmetic, commitments and chaining | §5.3, §9.3, §11.3 |

**One primitive may need writing.** I believe `curve25519-dalek 4.1.3` provides
`RistrettoPoint::from_uniform_bytes` but not RFC 9380's `expand_message_xmd`. Check this at Part 3's
design review. If it is missing, `sever-crypto` implements it (about 60 lines, checked against the RFC
9380 test vectors), and spec §9.1's "no primitive is implemented by this project" is amended by a
decision entry (proposed DB-52).

### 1.5 How Part 3 plugs into the frozen parts

| Extension point | Part 3 implementation | What it does |
|---|---|---|
| EP-1 `GroupExtension` | `CommitmentExtension` | Group public state `C_S`; group secret state `r_agg`; record secret `insert_leaf_index ‖ has_rt ‖ r_t` (41 bytes). Admission checks `C_t` against the quantised vector and `r_t`, and the user signature. Removal checks integrity: the stored `x̃` and `r_t` must reproduce the `C_t` in the record's insert leaf, which it reads through a handle to the leaf store; otherwise `IntegrityViolation`. A flush folds each founder's `r_t` into `r_agg` and leaves `has_rt = 1`. Blob magic `SEVERG`, with blob fields `C_S ‖ r_agg` |
| EP-3 `ChangeSet` | Read by `LogParticipant` | The pre-state and post-state of the touched group give `C_S_pre`, `C_S_post` and the secrets for the proof |
| EP-7 `TxnParticipant` | `LogParticipant` | `pre_transaction`: create an on-demand log checkpoint if the insert leaf is not yet covered by a witnessed one. `prepare`: build the insert or delete leaf, the proof and the certificate. `wal_records`: `LOG_LEAF`, `CERT_REF`, `LOG_CHECKPOINT`. `replay` rebuilds the tree. `check_invariants`: INV-15 |
| EP-8 `AppendStore` | Leaf, hash, log-checkpoint and certificate stores | Written and `fsync`ed before the `COMMIT` that references them |
| EP-9 `Clock` | Log checkpoint timestamps; 90-day epochs | `SimClock` in tests crosses epoch boundaries deterministically |

**New extension point declared by Part 3:**

| ID | Interface | Default | Why it exists |
|---|---|---|---|
| **EP-10** | `Witness`: receives a new log checkpoint and a consistency proof from its last cosigned checkpoint; cosigns only if the proof verifies | `SimulatedWitness` | So that independent witnesses (overview O-6) can be added later without editing Part 3 |

### 1.6 Independence rules

These are checked by architecture tests (L13).

- **Verifier.** A separate workspace with its own `Cargo.lock`, no path dependencies, and no crate from
  the engine workspace. `cargo tree` must show exactly `curve25519-dalek 4.1.3` in both workspaces
  (spec §20.3, checks 1–2). Its generator derivation, TLV parser and Merkle code are written from the
  specification.
- **Auditor.** It may copy verifier source files, but it may not depend on the engine.
- **Reference model.** For the strongest independence, `sever_refmodel_certs` uses a small
  pure-Python ristretto255, written from RFC 9496 and checked against the RFC's test vectors, rather
  than a binding to the engine's crypto crate. It is slow, so it runs on small and medium streams; the
  large-scale differential runs compare against the engine's own Python binding as well (proposed
  DB-51).

### 1.7 Requirements owned by Part 3 (examples)

| Area | Spec | Examples |
|---|---|---|
| Generators | §9.2 | one `expand_message` call per generator; refuse to start on a self-check mismatch |
| Commitments | §9.3 | recompute `C_t` at insert; `CommitmentMismatch`; `C_t` is never the identity |
| Proof | §9.5 | 231-byte challenge preimage in a fixed order; wide reduction; 12,352-byte proof |
| Nonces | §9.6 | a Merlin transcript with every witness scalar rekeyed in; a seeded RNG is a compile error; `SeededNonceForbidden` in Python |
| Signatures | §9.8 | domain-separated messages of 65, 66 and 83 bytes; `verify_strict`; 90-day epochs; user keys never rotate |
| Encoding | §9.9 | reject non-canonical points and scalars |
| Log | §10 | the RFC 9162 hashes and proofs; checkpoints every 10,000 leaves and on demand; four of five witnesses |
| Certificates | §11 | 13 TLV tags in order, each exactly once; a strict parser; the eight-step verification algorithm |
| Atomicity | §15.3, DB-24 | the state change, the leaf and the certificate commit in one WAL transaction |

### 1.8 Test plan

**L1 Unit**

- The RFC 9496 ristretto255 and one-way-map vectors, the RFC 9380 `expand_message_xmd` vectors and
  the RFC 8032 Ed25519 vectors.
- Golden vectors 1–4 (generators, generator digest, challenge, `scalar(v)` for
  `v ∈ {0, 1, −1, 2^44, −2^44}`).
- The fixed 7-leaf tree for RFC 9162 inclusion and consistency proofs (golden vector 9).
- The TLV parser rejects a missing tag, a repeated tag, a tag out of order, a wrong length and
  trailing bytes.
- Message lengths asserted: 65, 66, 83 and 231 bytes (Appendix A).

**L2 Property**

- **Completeness.** For random group states, an honest proof always verifies.
- **Special soundness.** Two accepting transcripts with the same `A` and different challenges let the
  extractor recover every secret. The extractor is written as a test, which is the executable form of
  the argument in `SOUNDNESS.md`.
- **Zero-knowledge simulator.** The simulator produces transcripts that verify without the secrets.
- **Homomorphism.** `C_S` equals `r_agg·H + Σ scalar(S_i)·G_i` after any sequence of inserts and
  deletes.
- **Merkle.** Inclusion and consistency proofs verify for random tree sizes, and match a naive
  recomputation.

**L3 Spec conformance.** `spec-trace` at 100 % for Part 3's requirements; the §11.1 field table is
table-driven; the certificate size for a group deletion is checked against Appendix A (≈ 14,093 bytes
with a 21-hash path).

**L4 Differential**

- The engine's certificate arithmetic, commitments and blobs against `sever_refmodel_certs`.
- The full five-field equivalence, now including `C_S` and `r_agg`, on `nq-100k` for five seeds
  (overview T-3, complete).
- Optionally, the generators and the fixed three-member blob against the earlier SEVER prototype
  (overview EX-3b).

**L5 Model-based stateful.** Part 2's state machine with the Part 3 build, adding the operations
"corrupt a stored `r_t` through a test hook, then delete" (a terminal step: `IntegrityViolation`, and
nothing changes), "advance the clock across an epoch" and "issue an on-demand checkpoint".
After every deletion, the certificate is passed to the verifier binary.

**L6 Metamorphic**

- **Chaining.** For consecutive certificates on the same group, `C_S_pre` of one equals `C_S_post` of
  the previous one.
- **Emptiness.** `group_emptied_by_this_deletion = 1` exactly when `C_S_post` is the identity.
- A certificate verifies identically before and after a restart of the engine.

**L7 Contract**

- `CommitmentExtension` passes Part 1's frozen EP-1 suite, unchanged.
- `LogParticipant` passes Part 2's frozen EP-7 suite, unchanged.
- `SimulatedWitness` passes the new EP-10 suite: it refuses an inconsistent checkpoint, a rollback, and
  a checkpoint with a bad operator signature.

**L8 Integration**

- **The crash campaign re-run with `LogParticipant`**, including crashes around the on-demand
  checkpoint transaction. After recovery there must be no certificate for a rolled-back deletion, no
  leaf without its state change, and every committed certificate retrievable by its `database_lsn`.
- SDK `prepare_insert` to engine `insert` to `delete` to `sever-verify`.

**L9 End-to-end:**

| ID | Given | When | Then |
|---|---|---|---|
| E2E-3.1 | The application backend inserted records for an authenticated account through the SDK | One record is deleted | The certificate is accepted by `sever-verify` in a separate process, with only the bundled anchors and no database access |
| E2E-3.2 | An honest certificate | Any single byte is changed | `sever-verify` rejects it and names the failed check |
| E2E-3.3 | A record in the holding area | It is deleted | A holding-area certificate (`deletion_kind = 1`) that verifies |
| E2E-3.4 | A cohort across several groups | `delete_user` runs | The certificates chain, and `sever-audit` confirms the chains |
| E2E-3.5 | A live record whose stored `r_t` was altered through a `test-hooks` build | It is deleted | `IntegrityViolation`; nothing changes, and the engine stops serving |
| E2E-3.6 | A log with one deletion leaf removed from an export | `sever-audit` runs | It reports the missing leaf |
| E2E-3.7 | A certificate signed in a later operator epoch | An older verifier checks it | It is rejected with an "unknown epoch" reason (overview L-14) |
| E2E-3.8 | The Python SDK | A caller tries to pass an RNG, a seed or a nonce | `SeededNonceForbidden` |

**The attack suite** (overview EX-4), applied to 1,000 honest certificates per seed. Every attack must
be rejected:

| ID | Attack |
|---|---|
| AT-1 | A forged proof |
| AT-2 | A proof copied from another certificate |
| AT-3 | A substituted `C_t` |
| AT-4 | Each single-field tamper: tags 1–13 and the trailer (14 variants) |
| AT-5 | A certificate under an unknown operator epoch |
| AT-6 | An insert leaf from another collection |
| AT-7 | A wrong inclusion path |
| AT-8 | A log checkpoint signed by the wrong key |
| AT-9 | Three instead of four cosignatures |
| AT-10 | Cosignatures over a different log checkpoint |
| AT-11 | A non-canonical point or scalar |
| AT-12 | The identity as `C_t` |
| AT-13 | A holding-area certificate that carries arithmetic fields |
| AT-14 | `group_emptied_by_this_deletion` inconsistent with `C_S_post` |
| AT-15 | `database_lsn` not after the insert leaf |
| AT-16 | A malformed TLV: missing, repeated or reordered tag, or trailing bytes |
| AT-17 | Four cosignatures where two come from the same witness (spec §11.3 requires distinct witnesses) |

**Auditor fault injection.** Each fault must be reported:

| ID | Fault |
|---|---|
| AF-1 | A skipped deletion leaf |
| AF-2 | A broken chain (`C_S_pre` ≠ the previous `C_S_post`) |
| AF-3 | Two log checkpoints that are not consistent (a forked log) |
| AF-4 | A leaf at `database_lsn` that does not match its certificate |
| AF-5 | A log checkpoint root that does not match the tree at its size |

**L11 Fuzz.** The certificate TLV parser, **separately** in the engine and in the verifier; the leaf
parser; the log-checkpoint parser.

**L12 Mutation and sabotage.** SB-16 to SB-23 each turn a test red. SB-18 (reuse a proof nonce) is also
a **compile-fail** test: passing a seedable RNG to the prove function must not compile. Mutation
testing covers `sever-crypto`, `sever-cert`, `sever-log` and the verifier.

**L13 Architecture.** Verifier and auditor independence (§1.6); the freeze guards for Parts 1–2.

**L14 Benchmarks** (descriptive). Proof generation time, verification time, certificate size and log
checkpoint time.

### 1.9 Targets

| ID | Target | Kind |
|---|---|---|
| **P3-T1** | 100 % of honest certificates accepted by the independent verifier (overview T-4) | Gate |
| **P3-T2** | 100 % of attack certificates rejected: AT-1 to AT-17 on 1,000 honest certificates per seed (overview T-4) | Gate |
| **P3-T3** | 100 % of RFC test vectors and golden vectors pass, in the engine **and** in the verifier | Gate |
| **P3-T4** | Across the crash campaign: 0 exactness violations, 0 lost acknowledged operations, 0 certificates for rolled-back deletions, 0 orphaned leaves (overview T-1, complete) | Gate |
| **P3-T5** | 0 mismatches on the five-field equivalence and the certificate arithmetic against the model, `nq-100k`, five seeds (overview T-3, complete) | Gate |
| **P3-T6** | The auditor reports 100 % of injected faults AF-1 to AF-5 | Gate |
| **P3-T7** | 0 shared crates between the verifier and the engine workspace | Gate |
| **P3-T8** | The full suites of Parts 1 and 2 pass unchanged on the Part 3 build (F-5) | Gate |
| **P3-T9** | SB-16 to SB-23 each turn a test red; traceability 100 %; line coverage ≥ 95 % and mutation score ≥ 90 % on `sever-crypto` and the verifier; ≥ 90 % and ≥ 85 % on the other Part 3 crates | Gate |
| **P3-T10** | 0 fuzz crashes in ≥ 10^8 executions per parser, in both code bases | Gate |
| **P3-T11** | `SOUNDNESS.md` is complete, and its extractor and simulator run as passing tests | Gate |
| **P3-T12** | The EP-10 contract suite passes for `SimulatedWitness` and fails for a witness that skips the consistency check | Gate |
| **P3-T13** | Proof time, verification time and certificate size (predicted ≈ 14.1 KB) | Measure (descriptive) |

### 1.10 The demo

`sever-demo receipt --data nq-10k --seed 42`:

1. The application backend inserts records for an authenticated account through the SDK; the demo
   shows the insert leaf in the log.
2. The backend deletes one of the account's records; the certificate is saved as a file.
3. `sever-verify certificate.bin` runs in a separate directory with only its bundled anchors. It prints
   each of the checks in spec §11.3 and **ACCEPT**.
4. One byte of the certificate is flipped. The verifier prints **REJECT** and names the failed check.
5. The demo prints what the certificate does not prove: that the operator kept no copy (overview L-2),
   and that the user personally authorised the deletion (overview L-27).
6. `delete_user` on a cohort produces chained certificates; `sever-audit` confirms the chains.

### 1.11 Exit gate and freeze

Part 3 freezes when the definition of done holds, including P3-T1 to P3-T12 as gates and P3-T13
measured. Before freezing, one **proof spike** must pass: a throwaway `AeadSealer` that seals the
commitment extension's secret state (`r_agg`, `r_t`) with the Part 3 build, and a stub
`KeyRotationParticipant` registered alongside `LogParticipant`. This proves Part 4 can be added without
touching Part 3. Tag: `part-3-frozen`.

---

## 2. Part 4 — The Erasure

### 2.1 Announcement

**What it is.** Physical erasure, and the complete system. Part 4 adds:

- the three-level key hierarchy (group, bucket and record keys);
- the AEAD sealer;
- rotation whenever a record leaves a key domain;
- the two-slot key file, with its erasure and recovery rules;
- memory hygiene and the platform checks;
- the forensic scanner;
- the final composition, `sever-db`, and the final SDK;
- the full pre-registered evaluation (overview EX-1 to EX-8) and the report.

**Why it exists.** Parts 1–3 make deletion exact, durable and verifiable, but old copies of the data
still sit in the WAL, old storage checkpoints and free disk space. With exact sums, any two surviving
accumulator versions subtract to the deleted vector exactly. Part 4 makes every old copy
undecryptable.

**What Part 4 may claim, once its gates pass.** Under the stated threat model and platform
requirements, after a deletion is acknowledged, no deleted plaintext and no key that decrypts it can
be recovered from the engine's storage, free space included. No two decryptable accumulator versions
straddle a deletion.

**What Part 4 does not claim.** Every item in overview §14 still applies, in particular: SSD firmware
and copy-on-write filesystems (L-1), the operator (L-2), the index shape (L-3), and a memory image
taken before acknowledgement (L-6).

### 2.2 Goals

| ID | Goal |
|---|---|
| **P4-G1** | Key types and the key file: two 512-byte slots per domain, CRC, versions, the recovery rule (spec §13.4, §14.7) |
| **P4-G2** | `AeadSealer` (EP-6): AES-256-GCM-SIV, random 96-bit nonces, the associated data of spec §13.2, record-key envelopes and bucket blocks (§14.5) |
| **P4-G3** | `KeyRotationParticipant` (EP-7): rotation on departure, phases A and C, replay, recovery and the cryptographic erase on dropping a collection (spec §13.3, §15.3, §15.9) |
| **P4-G4** | Memory hygiene (spec §12.8), with an `mlock` provider for EP-4, and the platform checks (spec §12.9) |
| **P4-G5** | The forensic scanner `sever-scan` (overview EX-2) |
| **P4-G6** | The final composition `sever-db`, the final SDK, and the build variants the evaluation needs |
| **P4-G7** | The complete pre-registered evaluation, and the report |

### 2.3 Scope

**In:** spec §12.8, the key-file checks of §12.9, §13 (all), §14.5, §14.7, phases A and C of §15.3,
§15.4, §15.8, §15.9, INV-11 to INV-14, and overview §10–§12 (datasets, evaluation and experiment
configuration).

**Out:** anything overview §1.5 lists as a non-goal.

### 2.4 Modules

| Crate or package | Responsibility | Spec |
|---|---|---|
| `sever-keys` | Key types (zeroize on drop, locked memory); the key file with two slots per domain, 512-byte alignment and CRC; key versions; domain index allocation; the recovery rule | §13.1, §13.4, §14.7 |
| `sever-seal` | `AeadSealer` (EP-6); record-key envelopes; bucket blocks | §13.2, §14.4–14.5 |
| `sever-erasure` | `KeyRotationParticipant` (EP-7) | §13.3–13.4, §15.3, §15.9 |
| `sever-platform` | Startup checks and memory hygiene; the `mlock` provider (EP-4); declares EP-11 `PlatformProbe` | §12.8–12.9 |
| `sever-scan` | The forensic scanner | Overview EX-2 |
| `sever-db` | The final composition root: `Engine<CommitmentExtension, AeadSealer, (LogParticipant, KeyRotationParticipant)>`; the final CLI; build variants (§2.7) | §16 |
| `sever-py` / `sever_db` | The final Python SDK | §16.2 |
| `sever_experiments` (Python) | The full harness (C-19): EX-1 to EX-8, the four arms, statistics, the run ledger | Overview §10–§12 |
| `sever_report` (Python) | Figures and tables for the report, generated only from result files named in the ledger | Overview §13.3 |

**New extension point declared by Part 4:**

| ID | Interface | Default | Why it exists |
|---|---|---|---|
| **EP-11** | `PlatformProbe`: filesystem type, swap state, hibernation state, file attributes | `LinuxProbe` (reads `/proc` and `statfs`) | Lets every refusal rule be tested with a fake probe, without root and without reconfiguring the test machine |

### 2.5 How Part 4 plugs into the frozen parts

| Extension point | Part 4 implementation | What it does |
|---|---|---|
| EP-4 `SecretMemory` | `MlockProvider` | Keys and decrypted accumulators live in `mlock`ed pages and are zeroed on release |
| EP-6 `Sealer` | `AeadSealer` | Every stored secret becomes ciphertext; the layouts come out exactly as spec §14.3–14.4 (6,285-byte group header, 1,992-byte slot) |
| EP-7 `TxnParticipant` | `KeyRotationParticipant` | For every domain in the `ChangeSet`'s **departures**, it runs the rotation of spec §13.3 inside the same transaction |
| EP-3 `ChangeSet` | Read for departures and arrivals | A flush out of the holding area is a departure, so the holding area rotates (SB-26) |

**The deletion protocol with every participant,** mapped to spec §15.3. Participants are registered in
the order `LogParticipant`, then `KeyRotationParticipant`.

| Spec §15.3 step | Protocol step (first plan §5.4) | Who |
|---|---|---|
| 1–2 Look up; check that the stored `x̃` and `r_t` reproduce `C_t` (integrity) | `plan` | Part 1 index + EP-1 `CommitmentExtension` |
| 3 On-demand log checkpoint | `pre_transaction` | `LogParticipant` |
| 4 Post-state, proof, certificate | `prepare` | `LogParticipant` |
| 4 (keys) New group key and bucket keys; re-wraps; re-sealed accumulator | `prepare` | `KeyRotationParticipant` |
| 5 Phase A: new key into the inactive slot; `fsync` | `phase_a` | `KeyRotationParticipant` |
| 6 Phase B: one WAL transaction; `COMMIT`; `fsync` | WAL write | Part 2 |
| 7 Apply; zero temporaries | `apply` | Part 1, through Part 2 |
| 8 Phase C: overwrite the old slot; `fsync` | `after_commit` | `KeyRotationParticipant` |
| 9 Acknowledge with the certificate | Acknowledge | Part 2 |

### 2.6 Requirements owned by Part 4 (examples)

| Area | Spec | Examples |
|---|---|---|
| Key hierarchy | §13.1 | three levels; bucket `scrambled_id[0] mod 64`; 32-byte keys from the OS |
| Encryption | §13.2 | AES-256-GCM-SIV; 96-bit random nonces; the associated-data table; what stays plaintext |
| Rotation | §13.3 | any departure rotates the domain; arrivals never rotate; steps 1–5 |
| Erasure and recovery | §13.4 | erase only after `COMMIT` is durable; two slots; refuse to start if the active slot is missing |
| Acknowledgement | §15.8 | only after durability, phase C and memory wiping |
| Memory | §12.8 | zeroize; `mlock`; no core dumps; refuse unencrypted swap and hibernation |
| Platform | §12.9 | ext4 or XFS for data; refuse ZFS, and btrfs without no-copy-on-write, for the key file |
| WAL content | §12.3, INV-11 | no plaintext vectors, IDs, text, `r_t`, `S`, `r_agg` or unwrapped keys |

### 2.7 Build variants for the evaluation

All variants are composition roots or feature flags inside Part 4. None edits a frozen part.

| Variant | What differs | Used by |
|---|---|---|
| `sever-db` | Nothing: the measured build | Every experiment |
| `sever-db` + `key-export` | Also writes each generated key to a file **outside** the disk image, so the scanner knows what to look for | EX-2 only |
| `sever-db-noerase` | `AeadSealer` with a static key per domain; no `KeyRotationParticipant` | EX-7 (the cost of erasure) |
| `sever-softdelete` | A thin wrapper over the Part 2 API: deletion writes a tombstone to an append store and search filters it out; nothing is excised | EX-7 (the cost of excision and receipts) |
| `sabotage-SB-N` | Exactly one sabotage | Scanner-sensitivity runs |

An architecture test proves that `key-export` adds nothing except the export sink: the feature
appears in exactly one function, and the measured build's binary contains no export code.

The frozen-only control arm of EX-6 uses Part 1's `spawning_enabled = false` configuration switch.

### 2.8 Test plan

**L1 Unit**

- The RFC 8452 AES-GCM-SIV vectors.
- The associated data built for every row of the spec §13.2 table (table-driven).
- The key-file slot parser, including a torn slot that fails its CRC.
- The recovery rule for every combination of slot states (valid active, valid stale, torn, missing).
- The bucket function.

**L2 Property**

- `open(seal(x)) = x` for every data kind.
- Opening fails whenever any field of the associated data is swapped: another record, another kind,
  another group, another version.
- **The rotation invariant (INV-12) as a shadow model.** A test-only key journal records which key
  version encrypted every ciphertext ever written. After every operation, the property checks that, for
  every domain, the ciphertexts the current keys can open are exactly those written after the domain's
  last departure.

**L3 Spec conformance.** `spec-trace` at 100 % for Part 4's requirements; the sizes of §14.3 (6,285
bytes), §14.4 (1,992 bytes) and §14.5 (4,352 bytes) and the key-file size (4 KB plus 1 KB per domain)
asserted; **every row of the crash table in spec §15.4 is its own test.**

**L4 Differential.** The final build runs overview EX-3 in lockstep with the reference model on
`nq-100k`, five seeds: the Part 1 and Part 3 traces, unchanged.

**L5 Model-based stateful.** The full state machine of the earlier parts, with key-file faults added
(a torn slot, a lost slot), checked against the durable oracle and the rotation shadow model.

**L6 Metamorphic.** The canonical blobs, search results and certificates of the final build equal
those of the Part 3 build on the same stream. Encryption changes the bytes on disk and nothing else.

**L7 Contract.**

- `AeadSealer` passes Part 2's frozen EP-6 suite.
- `KeyRotationParticipant` passes Part 2's frozen EP-7 suite.
- `MlockProvider` passes Part 1's frozen EP-4 suite.
- `LinuxProbe` passes the new EP-11 suite.

**L8 Integration**

- **The crash campaign with every participant.** It covers every step, including phases A and C, torn
  key-file slots, and crashes during recovery. The oracle requires the acknowledged state, every live
  record decryptable, and every stale key slot erased after recovery.
- **Nonce uniqueness.** A test build records every nonce under every key across all suites.
- **Plaintext scan.** Every byte the WAL, storage checkpoints and append stores ever wrote is scanned
  for forbidden plaintext (INV-11).
- **Zeroization.** A test `SecretMemory` provider checks that every secret buffer is all zero when it
  is released.
- **Platform refusals.** Each unsafe configuration is presented through a fake `PlatformProbe`.

**Forensics (overview EX-2).** The campaign runs on native Linux, on a 16 GB ext4 image mounted with
`fuse2fs`. For each seed:

1. Ingest `nq-100k`, then run the five deletion rungs. After each rung, take a storage checkpoint, shut
   down cleanly and unmount.
2. Scan the **raw image, free space included**, for:
   - deleted `x̃` as `i32` and `i64`, in both byte orders;
   - the deleted original float32 vectors, in both byte orders;
   - every 32-byte window of deleted passage text;
   - each deleted `r_t`;
   - every retired group, bucket and record key.
3. Carve every engine record by its magic number and CRC, and try every **live** key on it.

The extended CI tier runs the same campaign at 10,000 passages on a small image.

**Scanner sensitivity.**

- **Positive controls.** Planted secrets are found 100 % of the time, which shows the scanner can see.
- **Sabotage.** Each erasure sabotage (SB-24 to SB-30) produces at least one finding.
- **The accumulator leak.** With SB-24 (skip group-key rotation), the scanner decrypts two accumulator
  versions and reconstructs the deleted vector as `S_pre − S_post`. This is overview §1.3's leak shown
  directly.

**L9 End-to-end:**

| ID | Given | When | Then |
|---|---|---|---|
| E2E-4.1 | `nq-10k` on an ext4 image | A cohort is deleted, and the image is unmounted and scanned | 0 findings |
| E2E-4.2 | The same, built with SB-24 | The same steps | The scanner reconstructs a deleted vector |
| E2E-4.3 | A crash after `COMMIT` and before phase C | The engine restarts | Recovery erases the old key; a later scan is clean; a retried delete returns `AlreadyAbsent` |
| E2E-4.4 | A collection | It is dropped | Every one of its group keys is gone, and a scan finds none of its data |
| E2E-4.5 | Unencrypted swap, hibernation, ZFS, or btrfs without no-copy-on-write | The engine starts | `PlatformUnsafe`, unless `allow_unsafe_memory` is set, and the flag is recorded in the ledger |
| E2E-4.6 | The final SDK | insert → search → delete → verify → scan | Every step succeeds, and the certificate verifies |
| E2E-4.7 | The active key slot is removed from the key file | The engine starts | It refuses to start (spec §13.4) |

**L11 Fuzz.** The key-file parser and the sealed-record parsers.

**L12 Mutation and sabotage.** SB-24 to SB-30 each turn a test red **and** produce a scanner finding
where one applies. Mutation testing covers `sever-keys`, `sever-seal` and `sever-erasure`.

**L13 Architecture.** The `key-export` isolation test; the freeze guards for Parts 1–3; Miri over the
`mlock` code.

**L14 Benchmarks.** These are overview EX-7 and EX-8, run as experiments (§2.9).

### 2.9 The evaluation

Every experiment runs on the final build and follows the overview exactly: the same sizes, seeds, arms
and statistics, committed before any run (pre-registration).

| Experiment | Question | Build | Target | Kind |
|---|---|---|---|---|
| **EX-1** | Exactness under crashes | `sever-db` on `SimVfs` | T-1 | Gate |
| **EX-2** | Physical erasure | `sever-db` + `key-export`, on native Linux | T-2 | Gate |
| **EX-3** | Engine against the reference model | `sever-db` | T-3 | Gate |
| **EX-3b** | Cross-check with the earlier prototype (optional) | `sever-db` | — | Descriptive |
| **EX-4** | Certificates: honest and attacked | `sever-db` + `sever-verify` | T-4 | Gate |
| **EX-5** | Cost of quantisation, at `nq-100k` and `nq-1m` | `sever-db` | T-6 | Measure |
| **EX-6** | Search stability across deletion rungs; four arms; stream-fraction sweep | `sever-db`, frozen-only, FAISS soft-delete, FAISS rebuild | T-5; Welch test; TOST | Measure |
| **EX-7** | The cost of provable deletion | `sever-db`, `sever-db-noerase`, `sever-softdelete` | — | Measure |
| **EX-8** | Scale: `nq-1m`, then a restart | `sever-db` | — | Measure |

A missed measurement is published as found, with its exact value. A missed gate is a bug: it is
recorded in the ledger, fixed, and the full campaign is re-run as a new entry (first plan §2.5).

### 2.10 Targets

| ID | Target | Kind |
|---|---|---|
| **P4-T1** | 0 findings in the forensic scan, five seeds (overview T-2) | Gate |
| **P4-T2** | Scanner sensitivity: 100 % of positive controls found; each of SB-24 to SB-30 produces ≥ 1 finding where it applies (overview T-2) | Gate |
| **P4-T3** | Crash campaign with every participant: 0 exactness violations, 0 lost acknowledged operations, 0 undecryptable live records, 0 stale key slots after recovery; refusal to start in 100 % of injected active-key losses (overview T-1 on the final build) | Gate |
| **P4-T4** | Every row of the spec §15.4 crash table behaves as specified | Gate |
| **P4-T5** | 0 repeated AEAD nonces under any key, across all suites | Gate |
| **P4-T6** | 0 forbidden plaintext in any WAL, storage checkpoint or append store (INV-11) | Gate |
| **P4-T7** | 100 % of released secret buffers are zero; core dumps are disabled; `mlock` is in effect | Gate |
| **P4-T8** | 100 % of unsafe platform configurations refused; 0 safe configurations refused | Gate |
| **P4-T9** | The full suites of Parts 1–3 pass unchanged on the final build; overview T-3 and T-4 re-run on the final build | Gate |
| **P4-T10** | SB-24 to SB-30 each turn a test red; traceability 100 %; line coverage ≥ 95 % and mutation score ≥ 90 % on `sever-keys`, `sever-seal` and `sever-erasure`; 0 fuzz crashes in ≥ 10^8 executions per parser | Gate |
| **P4-T11** | The freeze manifests of Parts 1–3 are unchanged | Gate |
| **P4-T12** | Per-seed standard deviation of Recall@10 across the five rungs (overview T-5, pre-registered ≤ 0.005); the Welch test and TOST as fixed in overview §3.4 | Measure |
| **P4-T13** | Recall@10 of dequantised against original-float brute force at `nq-1m` (overview T-6, second size, pre-registered ≥ 0.999) | Measure |
| **P4-T14** | EX-7 costs, including bytes rewritten per deletion against the predicted ≈ 12.9 KB | Measure |
| **P4-T15** | EX-8: resident memory against the predicted ≈ 3.8 GB, recovery time, disk use including certificates | Measure |

### 2.11 The demo

`sever-demo erase --data nq-10k --seed 42` runs on an ext4 image mounted with `fuse2fs`:

1. **Positive control.** Before any deletion, the scanner finds a chosen record's vector on the image,
   which shows the scanner works.
2. **Delete** that person's records. The certificate is shown and verified (Part 3).
3. **Scan.** Checkpoint, shut down, unmount, and scan the raw image, free space included: **0
   findings**.
4. **The leak, made visible.** The same steps with the SB-24 build (group-key rotation skipped). The
   scanner decrypts two old accumulator versions and prints the deleted vector, reconstructed as
   `S_pre − S_post`, next to the original.
5. **Crash.** A crash is injected between `COMMIT` and phase C. On restart, recovery erases the old key,
   and a new scan is clean.

This demo shows the whole project: the arithmetic (Part 1), crash safety (Part 2), the receipt
(Part 3) and the erasure (Part 4).

### 2.12 Final deliverables

- The tagged release `v1.0.0`, which is also `part-4-frozen`.
- The report or paper. Every number in it is traceable to a run-ledger entry, and every limit in
  overview §14 is stated.
- Partition artefacts, dataset manifests and result files, archived with a DOI, each data file under its
  upstream licence (overview DB-42).
- A reproduction script that rebuilds the minimum result on the reference hardware from a clean clone.
- The run ledger, the errata file and every freeze manifest.

### 2.13 Exit gate and final freeze

Part 4 freezes when the definition of done holds, including P4-T1 to P4-T11 as gates, P4-T12 to P4-T15
measured and recorded as found, and the final deliverables complete. Tag: `part-4-frozen` / `v1.0.0`.

---

## 3. Cross-part registers

### 3.1 Targets, mapped to the pre-registered targets

| Overview target | Where it is established |
|---|---|
| **T-1** Crash campaign | P2-T1 (without certificates) → P3-T4 (with certificates) → P4-T3 (final build) |
| **T-2** Forensic erasure | P4-T1, P4-T2 |
| **T-3** Engine against the reference model | P1-T2 (core fields, search) → P3-T5 (five fields) → P4-T9 (final build) |
| **T-4** Certificates | P3-T1, P3-T2 → P4-T9 (final build) |
| **T-5** Search stability | P4-T12 |
| **T-6** Quantisation cost | P1-T7 (`nq-100k`), P4-T13 (`nq-1m`) |

### 3.2 Components, mapped to parts

| Component | Part | Component | Part |
|---|---|---|---|
| C-1 Storage I/O | 2 | C-11 Log and certificates | 3 |
| C-2 Formats | 2 (and 3 for certificates, 4 for the key file) | C-12 Engine API | 2 (generic); 4 (final composition) |
| C-3 WAL | 2 | C-13 Python SDK | 2 (basic), 3 (backend crypto helpers), 4 (final) |
| C-4 Storage checkpointer | 2 | C-14 Server | Not in any part (optional, DB-38) |
| C-5 Transaction manager | 2 | C-15 Partition builder | 1 |
| C-6 Key manager | 4 | C-16 Verifier | 3 |
| C-7 Crypto | 1 (quantiser, scrambling), 3 (rest), 4 (AEAD) | C-17 Auditor | 3 |
| C-8 Routing | 1 | C-18 Reference model | 1 (core), 2 (durable oracle), 3 (certificates) |
| C-9 Index core | 1 | C-19 Experiment harness | 1 (demo and traces), 2 (crash kit), 4 (full) |
| C-10 Search | 1 | Forensic scanner | 4 |

### 3.3 Invariants, mapped to parts

| Invariant | Established by | Invariant | Established by |
|---|---|---|---|
| INV-1 Quantisation path | 1 | INV-9 Deleted records unreachable | 1 |
| INV-2 Fields change together | 1 (`ChangeSet`), 2 (commit) | INV-10 Generators match the golden file | 3 |
| INV-3 `C_S` consistent | 3 (through EP-1) | INV-11 No forbidden plaintext in the WAL | 4 |
| INV-4 Group cap | 1 | INV-12 Rotation invariant | 4 |
| INV-5 Capacity bound | 1 | INV-13 Key-erasure rule | 4 |
| INV-6 Counts and sums match members | 1, checked at startup by 2 | INV-14 Key-file slot versions | 4 |
| INV-7 Locator matches slots | 1, checked at startup by 2 | INV-15 Log roots and insert leaves | 3 |
| INV-8 `N` and `k` | 1, checked at startup by 2 | INV-16 Routing is pure | 1 |

### 3.4 Golden vectors (spec Appendix B), mapped to parts

| Vector | Part |
|---|---|
| 1 Generators `H`, `G_0`, `G_383` | 3 |
| 2 Generator digest | 3 |
| 3 Challenge scalar, and its order-swap must-fail | 3 |
| 4 `scalar(v)` | 3 |
| 5 Quantisation of half-step inputs | 1 |
| 6 A complete group-deletion certificate and a holding-area certificate | 3 |
| 7 Spawn ID for a fixed 200-ID cohort | 1 |
| 8 Canonical blob for a fixed three-member group | 1 (`SEVERC` core form), 3 (`SEVERG` full form, byte-identical to spec §5.5) |
| 9 RFC 9162 proofs for a 7-leaf tree | 3 |

### 3.5 Proposed decision entries from both plans

| Proposed | Summary | Plan |
|---|---|---|
| DB-44 | Four frozen parts; erasure built after certificates | First, §3.5 |
| DB-45 | Plan/apply `ChangeSet`; extension points; the WAL `EXTENSION` record | First, §3.5 |
| DB-46 | Slot payload order and the group header's `seal_version`, with sizes unchanged | First, §3.5 |
| DB-47 | Canonical blob extension region and magic | First, §3.5 |
| DB-48 | `sealer_id` in every file; no confidentiality claim before Part 4 | First, §3.5 |
| DB-49 | Runtime dimension and group count; v1 fixes 384 and 128 | First, §3.5 |
| DB-50 | `SecretMemory` provider installed once at startup | First, §3.5 |
| DB-51 | Pure-Python ristretto255 in the certificate reference model | This plan, §1.6 |
| DB-52 | `expand_message_xmd` implemented in `sever-crypto`, if the pinned library lacks it | This plan, §1.4 |
| DB-53 | EP-10 `Witness` and EP-11 `PlatformProbe` | This plan, §1.5 and §2.4 |
| DB-54 | The evaluation's build variants (`key-export`, `noerase`, `softdelete`) | This plan, §2.7 |

**Status (4 October 2026).** DB-44, DB-45, DB-47, DB-49 and DB-50 are accepted (overview §6.8); the rest
remain proposals. Overview DB-56 … DB-59 are new decisions, not build-plan proposals.
