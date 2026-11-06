# 16 · Glossary

Each entry: **simple definition** · *In SEVER-DB* · See also. Alphabetical within each category.
Background files: B01 vectors, B02 databases, B03 numbers, B04 crypto, B05 testing, B06 Rust/Python,
B07 privacy (in [background/](background/)).

## General computing and systems

### Bit, byte, endianness
A bit is 0/1; a byte is 8 bits. **Big-endian** writes the most significant byte first. · *SEVER-DB*: all
integers on disk are big-endian fixed width; scalars are 32-byte little-endian (§0.2). · B03.

### Copy-on-write (COW)
A filesystem that writes changes to new blocks rather than overwriting. · *SEVER-DB*: refused for the key
file unless btrfs no-COW is set (§12.9) → [07f](07f_platform_safety_and_forensics.md).

### fsync
System call that forces a file's pending writes to the device. · *SEVER-DB*: one WAL fsync per
transaction; a failed fsync aborts, never retried (§12.7) → [06](06_part2_the_database.md). · B02.

### Hibernation
Saving all RAM to disk to power off. · *SEVER-DB*: startup refuses it (§12.8).

### mlock
Locks memory pages so they are never swapped. · *SEVER-DB*: `mlockall` at startup; refusal unless
`allow_unsafe_memory` → [07f](07f_platform_safety_and_forensics.md).

### SIMD / AVX2
Instructions processing several numbers at once; AVX2 = 256-bit x86 SIMD. · *SEVER-DB*: the search kernel,
the only `unsafe` code (crates/sever-search/src/kernel.rs).

### Swap
Disk space where the OS moves memory pages. · *SEVER-DB*: refused unless encrypted (zram/dm-crypt).

### WSL2
Windows Subsystem for Linux 2, a Linux VM on Windows. · *SEVER-DB*: development and gate-run platform.

### ULP
"Unit in the last place": spacing between adjacent floats. · *SEVER-DB*: normalisation tolerance is
8 float32 ULPs at 1.0 = 8·2⁻²³ (§4.1). · B03.

## Numbers and vector search

### Centroid
Mean point of a group. · *SEVER-DB*: 128 frozen centroids from k-means; a spawned group's centroid is
computed once and frozen (§7.5). · B01.

### Cosine similarity / L2 distance
Angle-based similarity / squared Euclidean distance; equivalent rankings for unit vectors. · *SEVER-DB*:
scores are squared L2 in float32 (§8). · B01.

### Embedding
A vector that encodes the meaning of a text. · *SEVER-DB*: 384-dim all-MiniLM-L6-v2 vectors. · B01.

### Fixed point / floating point
Integers counting fixed steps / sign-significand-exponent numbers. · *SEVER-DB*: Q24 fixed point. · B03.

### IVF (inverted file index), IVF-flat
Vectors grouped by nearest centroid; search scans the closest groups; "flat" = uncompressed. · *SEVER-DB*:
probes ⌈k/4⌉ groups (§8.1). · B01.

### k-means
Clustering into k groups by nearest centre. · *SEVER-DB*: scikit-learn KMeans, 128 clusters, on SciQ (C-15).

### Ledoit–Wolf shrinkage
Stable covariance estimate mixing sample covariance with a scaled identity. · *SEVER-DB*: one pooled fit,
checked by an independent oracle (§6.2).

### Mahalanobis distance
Distance scaled by data spread: `sqrt(δᵀPδ)`. · *SEVER-DB*: drift test vs threshold τ (§7.2).

### Q24
Fixed point with 24 fractional bits: `x̃ = round_half_to_even(x·2^24)` as `i32`. · crates/sever-quant. · B03.

### Recall@10
Fraction of the true top-10 neighbours that a search returns. · *SEVER-DB*: P1-T7 = 1.0; EX-6 per rung. · B01.

### Round half to even
Ties go to the even neighbour (2.5 → 2). · *SEVER-DB*: the only rounding in quantisation. · B03.

### Unit vector, normalisation
Length-1 vector. · *SEVER-DB*: checked, never performed (§4.1).

### Vector
An ordered list of numbers. · *SEVER-DB*: d = 384. · B01.

## Databases and storage

### Atomicity
All-or-nothing changes. · *SEVER-DB*: one `delete_user` = one transaction. · B02.

### Log checkpoint
An operator-signed `(tree_size, root, timestamp_ms, epoch)` of the transparency log (116 bytes), witnessed by ≥ 4 cosignatures. · §10.3.

### Checkpoint (storage) vs log checkpoint
Storage checkpoint: a durable full image of the database installed via `MANIFEST` (§12.4). Log checkpoint:
an operator-signed Merkle root (§10.3). Two different things (§0.4).

### Commit point
The instant after which a transaction counts. · *SEVER-DB*: fsync of the WAL COMMIT record (protocol step 5).

### Compaction / VACUUM
Later rewriting that physically removes deleted records. · Other systems; SEVER-DB excises immediately. · B02, R02.

### CRC-32C
4-byte checksum detecting accidental corruption (not a security tool). · every on-disk record.

### MANIFEST
32-byte file naming the current storage checkpoint; its install is the checkpoint's commit point.

### Recovery
Startup procedure: load checkpoint, replay committed WAL, check invariants, refuse on violation (§15.7).

### Tombstone
A marker saying a record is deleted while its bytes remain. · SEVER-DB uses none (§5.4). · B02.

### Soft delete / tombstone
Marking a record deleted while keeping its bytes. · *SEVER-DB*: never used (§5.4). · B02.

### Torn write / torn tail
A write cut off by a crash / a half-written last WAL record (discarded). · [06](06_part2_the_database.md).

### Transaction
A group of changes applied all-or-nothing. · sever-txn protocol.

### WAL (write-ahead log)
Append-only log written and fsynced before data changes. · crates/sever-wal. · B02.

## Cryptography

### AEAD
Authenticated encryption with associated data: confidentiality + tamper detection. · B04.

### AES-256-GCM-SIV
Nonce-misuse-resistant AEAD (RFC 8452). · *SEVER-DB*: every ciphertext, random 96-bit nonce, 28 B overhead.

### Associated data (AD)
Public bytes authenticated with a ciphertext. · binds owner, field, key version (§13.2).

### Bucket key
Level-2 key; 64 per group; wraps record keys. · [07e](07e_encryption_and_crypto_shredding.md).

### Commitment
A value that hides and binds a number. · B04.

### Consistency proof
Proof that an old Merkle root is a prefix of a newer tree (RFC 9162). · [07c](07c_transparency_log_and_signatures.md).

### Crypto-shredding
Making data unreadable by destroying its key. · Part 4.

### Digital signature
Private-key signing, public-key verification. · Ed25519.

### Domain separation (DST)
A fixed label prefixed to every hashed/signed message. · seven DSTs (§2.3).

### Ed25519 / verify_strict
EdDSA signatures on Curve25519 (RFC 8032) / strict verification rejecting malformed keys and signatures.

### Elliptic curve, group, discrete log
A group of points with hard "division" (discrete-log problem). · B04.

### expand_message_xmd
RFC 9380 hash-to-bytes; the only primitive the project implements itself (DB-52).

### Fiat-Shamir
Turns an interactive proof into one message by hashing the transcript for the challenge. · [07b](07b_pedersen_commitments_and_proofs.md).

### Generators (H, G_i)
Base points hashed from `DST_GEN`. · §9.2.

### Group key
Level-1 key, only in `KEYS`, destroyed on rotation. · [07e](07e_encryption_and_crypto_shredding.md).

### Hash function
Fixed-size fingerprint (SHA-256, SHA-512). · B04.

### Hedged nonce
Proof nonce from witness + statement + OS entropy (Merlin). · §9.6.

### HMAC
Keyed hash. · scrambled IDs (HMAC-SHA-512).

### Homomorphic
Operations on commitments match operations on the hidden values. · `C_S = Σ C_t`.

### Inclusion proof
Sibling hashes proving a leaf is under a Merkle root.

### Key hierarchy / key wrapping
Keys encrypting keys / encrypting a key under another. · group → bucket → record.

### Key slot
512-byte record in `KEYS`: version, key, CRC; two per domain (§14.7).

### Merkle tree
Hash tree with one root. · RFC 9162 log.

### Merlin
STROBE-based transcript library (merlin 3.0.0). · nonces.

### Nonce
Number used once per encryption/proof.

### Pedersen commitment
`r·H + Σ v_i·G_i`; hiding, binding, additive. · `C_t`, `C_S`.

### Proof of knowledge / zero-knowledge
Proving you know a secret without revealing it. · [07b](07b_pedersen_commitments_and_proofs.md).

### Record key
Level-3 key per record; encrypts payload and passage.

### ristretto255
Prime-order group over Curve25519 (RFC 9496), order ℓ ≈ 2^252.

### Schnorr / Okamoto protocol
Σ-protocols proving knowledge of discrete logs / representations.

### Transparency log
Public append-only Merkle log with signed roots (RFC 6962/9162).

### Witness
An independent party that checks a log checkpoint extends the previous one and cosigns it. · *SEVER-DB*: five, threshold four, **simulated in v1** (L-7). · [07c](07c_transparency_log_and_signatures.md).

### Witness / cosignature
Party checking log consistency and countersigning checkpoints; 4 of 5 needed; **simulated in v1**.

### Wrapped key
A key stored encrypted under its parent key. · wrapped-key store `wrapped/`.

## Testing

### Contract suite
Shared tests every implementation of an extension point must pass (L7).

### Coverage
Share of lines/branches executed by tests.

### Differential testing
Comparing two independent implementations. · engine vs reference model.

### Fair testing
Clean-room testing by fresh AI sessions in a `bwrap` sandbox (FT-1 … FT-10). · [10](10_testing_methodology.md).

### Fuzzing
Feeding random inputs to find crashes (cargo-fuzz, 10⁸ runs per parser).

### Golden file
Frozen expected values from spec/model/RFC (`golden/`).

### Metamorphic test
Checks a relation between two runs (order independence).

### Mutation testing
Automatic small code changes that tests must catch (cargo-mutants). · score thresholds 85/90 %.

### Oracle (test oracle)
Source of a test's expected value: A spec, B independent, B-shared, C frozen Part 1, D code itself (CLAUDE.md §6.3).

### Property-based test
A rule checked on many generated inputs (proptest, Hypothesis).

### Red proof
A patch that breaks exactly one rule; the tests labelled with that rule must pass without it and fail with it. · tests/proofs/. · B05.

### Red proof / green proof
Patch breaking one rule that must turn a labelled test red / that shows a test could not fail (tests/proofs/).

### Reference model
Independent, slow, spec-only implementation (`python/sever_refmodel_*`).

### Regression test
A test added (failing first) to keep a fixed bug fixed.

### Sabotage build
Same source built with one deliberate bug (`--features sabotage-SB-N`); a test must turn red.

### Survivors check
Compare a group after deletion with a group rebuilt from its survivors only.

### Trace
JSONL record of a reference-model run, replayed by `sever-tracekit`.

## Tools and languages

### Cargo / crate
Rust's build tool / a Rust package. · B06.

### Crate
See Cargo. 35 crates in `crates/`.

### Lock file
`Cargo.lock` / `uv.lock`: exact resolved versions.

### maturin
Builds PyO3 crates into Python packages.

### MSRV
Minimum supported Rust version: 1.85.

### PyO3
Rust ↔ Python binding library (0.29.2).

### Tag (git)
A named pointer to a commit (e.g. `part-1-frozen`).

### SDK
Software development kit: here the Python package (`sever_db`) that applications call. · [08](08_interfaces_sdk_cli_studio.md).

### uv
Python environment and package manager.

### Workspace (Cargo)
Several crates built with one lock file.

## Privacy and law

### DPDP Act 2023
India's Digital Personal Data Protection Act; §12 erasure rights (official text not yet verified). · B07.

### GDPR Art. 17
EU right to erasure. · B07.

### Personal data
Information about an identifiable person; embeddings of a person's text count in practice. · B07.

### Right to erasure
A person's right to have their data deleted on stated grounds. · B07.

## Project-specific terms

### Anchors
JSON of operator and witness public keys by epoch, `d`, `gdigest`, given to the verifier.

### Application backend
The service that embeds text, runs `prepare_insert`, holds account keys and authorises deletion (§3.3).

### C_S
Group commitment `r_agg·H + Σ S_i·G_i`; `C_S_pre`/`C_S_post` before/after a deletion; check
`C_S_post + C_t = C_S_pre`.

### C_t
Record commitment `r_t·H + Σ x̃_i·G_i`; never the identity.

### Canonical blob
Deterministic byte string of a group's state (`SEVERC`/`SEVERG`), never stored; the object of the
exactness claim (§5.5).

### ChangeSet
Output of `plan`: everything a mutation changes (EP-3).

### cid / collection_id
16 random bytes naming a collection.

### Cohort
Records deleted together by one `delete_user` (one article's passages in tests).

### Composition root
The crate that wires generic parts into a concrete engine (`sever-db`).

### database_lsn
0-based index of an operation's own log leaf. (Not the WAL position `wal_seq`.)

### Deletion certificate
13-field TLV receipt + operator signature (§11).

### Domain (key domain)
A group or holding area with its own key set.

### Five-field equivalence
`S`, `n`, `C_S`, blob, member IDs all equal (§5.5).

### Flush
When the holding area reaches the spawn target, its records form one spawned group.

### Forensic scan
`sever-scan` search of a raw disk image for deleted data (EX-2).

### Freeze
Hashing a finished part's files into `freeze/PART-N.sha256` and tagging (F-1); CI then forbids edits (F-2).

### Frozen group / spawned group
One of 128 groups from the artefact (`frozen-NNNN`) / created by a flush (`spawn-<16 hex>`).

### Gate
Pre-registered pass/fail check; a miss is a bug.

### Ghost
The trace a conventional deletion leaves (tombstone, centroid bias, float drift, disk copies).

### Group
A cluster of vectors with exact `S`, `n` (and `C_S`, `r_agg` from Part 3).

### Holding area
Per-collection, non-searchable buffer for out-of-distribution vectors (§7.4).

### Interim check
Laptop evidence before the final gate run; never reported as the gate (DB-94).

### IntegrityViolation
Error naming a broken invariant; the final engine stops serving (DB-117).

### LSN / wal_seq
Position of a WAL record (`wal_seq`), unrelated to `database_lsn`.

### Measure
Recorded result with no pass/fail; never a reason to rerun (Build §2.5).

### n, S
Group member count (`u64`) and exact component sums (`i64`).

### Participant
Pluggable transaction member (EP-7): log (P3), key rotation (P4).

### Partition artefact (.svp)
Hashed file with centroids, precision matrix and τ (§6.3).

### Phase A / phase C
Participant actions just before / just after the commit point.

### Plan / apply
Pure validation-and-planning step / installing step that cannot fail.

### r_t
A record's random blinding scalar (64 OS bytes reduced mod ℓ), drawn by the SDK, stored encrypted, erased with the record key. · §9.4.

### r_t, r_agg
Record blinding scalar (from the OS, stored encrypted) / sum over a group's members mod ℓ.

### Rung
Cumulative deletion level (10/25/50/75/90 % of cohorts).

### Scrambled ID
HMAC-SHA-512 pseudonym of a record ID (64 bytes).

### Sealer
EP-6 interface: `PlaintextSealer` (P2, P3) or `AeadSealer` (P4).

### Seed
One of 42, 123, 777, 2024, 9999 — for data order, synthetic data, k-means only.

### SimVfs
Simulated disk with current/durable views for crash testing.

### Spawn target
Holding-area size that triggers a flush: 200 (8 in fixtures).

### Studio
SEVER-DB Studio, the PySide6 demo app (not frozen).

### TLV
Tag–length–value encoding used by certificates.

### x̃, x̂
Quantised vector (`i32`) / dequantised vector (`x̃/2^24`).

## ID schemes

### AT-N (attack register)
AT-1 … AT-20 certificate attacks (spec/registers_p3.yaml). · [07g](07g_crypto_attack_testing.md).

### AF-N
AF-1 … AF-5 auditor faults.

### BH-N
Bug-hunt findings (October and November reuse BH-6/BH-7).

### C-N
Components of spec §19.1 (C-15 partition builder, C-16 verifier, C-18 reference model, …).

### DB-N
Decision-register entries in the overview (e.g. DB-113 laptop run).

### Erratum (E-N)
A fix to a frozen part with a red-first test and a new tag (E-1, E-2).

### E2E-N
End-to-end test IDs per part (e.g. E2E-2.1 … 2.8).

### EP-N (extension point)
Interfaces later parts plug into (EP-1 … EP-11). · [04](04_architecture.md).

### EX-N
Pre-registered experiments EX-1 … EX-8.

### F-1 … F-6
Freeze rules: freeze, guard, extend-never-edit, …, regression by reuse, errata.

### FT-N
Fair-testing rules FT-1 … FT-10.

### G-N (spec gap)
A place the spec was unclear, closed by a decision (G-1 … G-52, all closed).

### INV-N
Invariants of spec §21 (e.g. INV-13 key erasure rule, INV-14 recovery rule).

### L-N (limit)
Declared limitations L-1 … L-28. · [14](14_status_gaps_and_pending.md).

### L1–L14
Test levels (unit … benchmark).

### P1-T1 … P4-T15
Per-part gates and measures.

### RQ-N, G-N goals, T-N
Research questions; overview goals; pre-registered targets T-1 … T-6.

### SB-N
Sabotage items SB-1 … SB-30.

### SR-x-n (requirement ID)
Requirement ID for each spec MUST (`spec/requirements.yaml`, 293 IDs).
