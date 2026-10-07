# SEVER-DB — Software and Index Specification

| | |
|---|---|
| **Document** | SEVER-DB technical specification, version 1.0 |
| **Date** | 27 September 2026 |
| **Companion** | `SEVER-DB_PROJECT_OVERVIEW.md`: why, goals, decisions with rationale, phases, evaluation, limits, risks, references |
| **Status** | Normative. Nothing is built yet. Everything the software must do is defined here; no other document is needed to implement it |
| **Scope** | Data model, vector arithmetic, the SEVER index (frozen partition, drift detection, spawning, exact deletion), search, cryptography, transparency log, deletion certificates, storage engine, key hierarchy and physical erasure, byte formats, protocols, crash behaviour, API, configuration, toolchain |

---

## Contents

0. [Conventions](#0-conventions)
1. [The system on one page](#1-the-system-on-one-page)
2. [Constants and notation](#2-constants-and-notation)
3. [Data model](#3-data-model)
4. [Vector arithmetic](#4-vector-arithmetic)
5. [Groups, accumulators and exact deletion](#5-groups-accumulators-and-exact-deletion)
6. [The partition artefact and the partition builder](#6-the-partition-artefact-and-the-partition-builder)
7. [Routing, drift detection and spawning](#7-routing-drift-detection-and-spawning)
8. [Search](#8-search)
9. [Cryptography](#9-cryptography)
10. [Transparency log, log checkpoints and witnesses](#10-transparency-log-log-checkpoints-and-witnesses)
11. [Deletion certificates](#11-deletion-certificates)
12. [Storage engine](#12-storage-engine)
13. [Key hierarchy and physical erasure](#13-key-hierarchy-and-physical-erasure)
14. [On-disk formats](#14-on-disk-formats)
15. [Operation protocols and crash behaviour](#15-operation-protocols-and-crash-behaviour)
16. [API](#16-api)
17. [Errors](#17-errors)
18. [Configuration files](#18-configuration-files)
19. [Components and code layout](#19-components-and-code-layout)
20. [Toolchain and dependencies (checked 27 Sep 2026)](#20-toolchain-and-dependencies-checked-27-sep-2026)
21. [Invariants checklist](#21-invariants-checklist)
22. [Appendix A — derived sizes and bounds](#appendix-a--derived-sizes-and-bounds)
23. [Appendix B — golden vectors to generate in P1](#appendix-b--golden-vectors-to-generate-in-p1)

---

## 0. Conventions

### 0.1 Normative words

**MUST**, **MUST NOT**, **SHOULD** and **MAY** have their usual RFC 2119 meanings. In §2–§21 and the
appendices, these are also normative, with the force of MUST: numbered algorithm steps, formulas,
byte layouts, parser rejection rules, rows of normative tables, and definitions. Rationale ("Why …",
notes, soundness notes, explanations that follow a rule) and illustrative examples are explanatory.
Every normative statement has a requirement ID `SR-<section>-<n>` (overview DB-58).

### 0.2 Encodings

- All integers on disk, on the wire and inside hash or signature inputs are **big-endian,
  fixed-width** (`u8`, `u16be`, `u32be`, `u64be`, `i32be`, `i64be`).
- `‖` means raw byte concatenation, with no separators and no length prefixes unless shown.
- Strings are UTF-8. "Ascending by bytes" means lexicographic order of the raw UTF-8 bytes.
- Points are ristretto255 elements in their 32-byte canonical encoding. Scalars are 32-byte
  canonical little-endian encodings modulo ℓ (the only little-endian values in the system, because
  that is the ristretto255 and Ed25519 standard encoding).
- Every hash, signature and proof input is prefixed by a fixed ASCII domain string listed in §2.3.

### 0.3 Identifiers used across the two documents

| Prefix | Meaning | Defined in |
|---|---|---|
| `DB-N` | A design decision with its rationale | Overview §6 |
| `C-N` | A software component | This document §19 |
| `P-N` / `PN` | A build phase | Overview §8 |
| `T-N` | A pre-registered target | Overview §3 |
| `EX-N` | An experiment | Overview §11 |
| `L-N` | A known limit | Overview §14 |
| `INV-N` | An invariant the engine checks | This document §21 |

### 0.4 Two kinds of checkpoint

- A **log checkpoint** is a signed, witness-cosigned tree head of the transparency log (§10.3), which
  RFC 9162 calls a signed tree head.
- A **storage checkpoint** is a durable image of the engine's state that bounds recovery time (§12.4).

The bare word "checkpoint" is not used without one of these qualifiers.

---

## 1. The system on one page

**SEVER-DB** is an embedded, transactional, crash-safe vector database. It does three things that no
ordinary vector database does together:

1. **Exact deletion in the index.** Every group of vectors stores a running *sum* and a *count* in
   integers, never an average. Deleting a vector subtracts it, so the group becomes bit-for-bit
   identical to a group that never received it. Groups are fixed in advance on a public reference
   dataset and never move, so one deletion touches exactly one group.
2. **A public receipt for every deletion.** Each group also carries a Pedersen commitment to its
   sum. A deletion produces a certificate that anyone can check with no access to the database: the
   commitments before and after differ by exactly the commitment to the deleted vector, the operator
   proves it knows the resulting state, and the insert-time signature under the account's key and a
   witness-cosigned transparency log pin down what was deleted.
3. **Physical erasure on disk.** Everything secret is written to disk only as ciphertext, under a
   three-level key hierarchy. Every deletion rotates the keys of the group it touched and destroys
   the old top-level key, so every old copy of the deleted data — in the write-ahead log, old
   storage checkpoints, freed blocks or flash cells — becomes undecryptable at once.

Live data that does not resemble the reference dataset (measured by a Mahalanobis drift test) is not
forced into the frozen groups. It either spills into an existing *spawned* group that has room, or
waits in a *holding area* until 200 such vectors form one new spawned group. Spawned groups are
frozen from the moment they are created.

Search is IVF-flat: rank all group centroids, scan the closest 25 % of groups (empty ones included),
return the top *k*. Search results are approximate; deletion is exact.

Three parties take part (§3.3): a thin **user app** that sends text; the **application backend**,
which embeds the text, prepares and signs each insert, holds the account keys, and decides who may
delete; and the **engine** described in this document.

```
  user app ──text──► application backend (embed; SDK §16.2; account keys)
                                          │ insert/delete/search
                                          ▼
                                       Engine API (C-12)
                                          │
        ┌──────────────┬──────────────────┼─────────────────────┐
        ▼              ▼                  ▼                     ▼
  Routing (C-8)   Index core (C-9)   Search (C-10)   Certificates + log (C-11)
        └──────────────┴────────┬─────────┴─────────────────────┘
                                ▼
                  Transaction manager (C-5)
          ┌──────────────┬──────┴──────┬───────────────┐
          ▼              ▼             ▼               ▼
      WAL (C-3)   Storage ckpt (C-4)  Key mgr (C-6)  Crypto (C-7)
          └──────────────┴──────┬──────┘
                                ▼
                     Storage I/O, VFS (C-1), formats (C-2)
```

---

## 2. Constants and notation

### 2.1 Symbols

| Symbol | Meaning |
|---|---|
| `d` | Vector dimension. **384** in v1 |
| `f` | Fractional bits of the fixed-point encoding. **24** |
| `x` | A float32 embedding, L2-normalised, `x ∈ ℝ^d` |
| `x̃` | The quantised vector, `x̃_i ∈ ℤ` (§4.2) |
| `x̂` | The dequantised vector, `x̂_i = x̃_i / 2^f` |
| `S` | A group's running sum, `S_i ∈ ℤ` stored as `i64` |
| `n` | A group's member count, `u64` |
| `r_t` | A record's blinding scalar, drawn by the application backend and stored by the engine for every record |
| `r_agg` | A group's running blinding total, `Σ r_t mod ℓ` over current members |
| `C_t` | A record's commitment, `r_t·H + Σ x̃_i·G_i` |
| `C_S` | A group's commitment, `r_agg·H + Σ S_i·G_i` |
| `H, G_0 … G_{d−1}` | Independent ristretto255 generators derived from a public string (§9.2) |
| `ℓ` | The ristretto255 group order, `2^252 + 27742317777372353535851937790883648493` |
| `μ_j` | Centroid of group `j`, `f64^d` |
| `P` | Pooled Ledoit–Wolf precision matrix, `f64^{d×d}` |
| `τ` | Drift threshold, `f64` |
| `N` | `live_vectors`: records currently in any frozen or spawned group (holding area excluded) |
| `k` | `total_groups`: frozen + spawned groups (holding area excluded) |

### 2.2 Fixed parameters (v1)

| Name | Value | Where used |
|---|---|---|
| Dimension `d` | 384 | Everywhere |
| Fractional bits `f` | 24 (scale `2^24 = 16,777,216`) | §4 |
| Normalisation tolerance | 8 float32 ULPs at 1.0 = `8 · 2^−23 ≈ 9.54 × 10^−7` | §4.1 |
| Frozen groups | 128 | §6 |
| Hard cap per group | 1,000,000 members | §5.6 |
| Spawn target size | 200 | §7.4 |
| Capacity multiplier | 1.5 | §7.3 |
| Probe coverage | 25 % of all groups, rounded up | §8 |
| Buckets per group | 64 | §13 |
| Log checkpoint cadence | every 10,000 log leaves, and on demand | §10.3 |
| Witnesses | 5, threshold 4 | §10.4 |
| Operator and witness key epoch | 90 days | §9.8 |
| Record ID length | 1 to 256 bytes | §3.2 |
| Page size | 16,384 bytes | §14.2 |
| Key-file slot | 512 bytes | §14.7 |

The code accepts any dimension `d` that is a multiple of 8, any number of frozen groups from 1 to
10,000 (DB-63) and any spawn target size ≥ 1 (DB-62); the values above are the v1 configuration, and
every size in Appendix A and every golden vector uses them (overview DB-49).

### 2.3 Domain strings (all ASCII, exact bytes)

| Name | Bytes | Length | Used for |
|---|---|---|---|
| `DST_GEN` | `PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS` | 41 | Generator derivation (§9.2) |
| `DST_POSK` | `SEVERDB_POSK_V1` | 15 | Proof challenge (§9.5) |
| `DST_NONCE` | `SEVERDB_POSK_NONCE_V1` | 21 | Merlin transcript label (§9.6) |
| `DST_INSERT` | `SEVERDB-INSERT-V1` | 17 | User insert signature (§9.8) |
| `DST_STH` | `SEVERDB-STH-V1` | 14 | Operator log-checkpoint signature (§10.3) |
| `DST_COSIGN` | `SEVERDB-COSIGN-V1` | 17 | Witness cosignature (§10.4) |
| `DST_CERT` | `SEVERDB-CERT-V1` | 15 | Operator certificate signature (§11) |

`DST_GEN` is the public "nothing-up-my-sleeve" string of the earlier SEVER prototype. It is kept
deliberately (DB-14) so that the generators match that prototype and can be cross-checked against
it. No one holds a discrete-log relation between the generators, because they are hashed from this
public string.

---

## 3. Data model

### 3.1 Collections

A **collection** is an independent index: its own dimension, partition artefact, parameters, groups,
keys and log leaves. A collection is identified by a **`collection_id`: 16 random bytes** generated
from the OS CSPRNG at creation. A database directory MAY hold several collections. The transparency
log is shared by the whole database; every leaf names its collection.

### 3.2 Records

A **record** is `(record_id, x̃, C_t, user_public_key, insert_signature, passage?)`.

**Record ID rules (MUST, checked on every insert):**

1. A UTF-8 string of **1 to 256 bytes**.
2. It MUST NOT match `^[+-]?[0-9]+$` (a bare decimal integer, with or without sign or leading
   zeros). `doc0`, `nq-1234` and UUIDs are accepted; `1`, `007`, `-3` and `+3` are rejected.
3. It MUST NOT equal the ID of a record currently live in the same collection.

**Why rule 2 exists.** Group contents must not depend on arrival order, so IDs must come from the
dataset rather than an insertion counter. A counter cannot be detected from one value, so the rule
rejects the *shape* of a counter. This is a heuristic, not a proof; the property itself is tested by
checking that different insertion orders give byte-identical canonical groups (§5.5).

A record ID MAY be inserted again after its record has been deleted. The new record is a new
insert, with a new log leaf.

### 3.3 Users and blinding values

Three parties take part:

- **User app.** Thin: it sends text and authenticates to the user's account at the application
  backend. It holds no SEVER-DB secret.
- **Application backend** (the service, for example an AI server). It embeds the text, runs
  `prepare_insert` (§16.2: quantise, draw `r_t`, compute `C_t`, sign) and calls the engine. It holds
  every account's Ed25519 signing key in its own key store.
- **Engine.** It recomputes and checks `C_t`, stores the record, updates `S`, `n`, `r_agg` and `C_S`,
  appends to the log, deletes and issues certificates. It never embeds text.

The application backend MUST embed text with the encoder named in the partition artefact's `encoder`
field (§6.3). Neither the user app nor the engine embeds anything.

A **user** (an account) is identified by an Ed25519 key pair, the **user key**, which the application
backend generates for the account and keeps in its key store. The public key is published in the
transparency log with every insert. **User keys never rotate**, because an insert signature may need to
verify years later, when the deletion happens.

For every record, the application backend draws a fresh blinding scalar `r_t` (§9.4) and sends it with
the insert. The engine stores `r_t` for **every** record, encrypted under the record key (§13.2), so
destroying that key at deletion erases `r_t` with the record (§13.5).

**Deletion is authorised by the application backend**: it authenticates the account and then calls
`delete`. The engine performs no authorisation of its own. The insert signature records that the service
acted for an authenticated account; because the operator holds every user key and every `r_t`, neither
the signature nor deletion authorisation constrains a dishonest operator (overview DB-55, L-27).

### 3.4 Passage text (optional)

A collection MAY store the passage text of each record. When stored, it is encrypted under the
record's key (§13) and erased with it. It never influences routing, search or the accumulators.

### 3.5 Cohorts

A **cohort** is the set of records deleted together by `delete_user` (for example, everything one
person contributed). The engine does not store cohorts; the caller supplies the list of records.

---

## 4. Vector arithmetic

### 4.1 Normalisation check (every insert, no bypass)

Input: `x` as `d` float32 values.

0. The input MUST have exactly `d` components. Otherwise reject with `WrongDimension` (overview DB-60).
1. Every component MUST be finite. Otherwise reject with `NonFinite`.
2. Compute `norm = sqrt(Σ_{i=0}^{d−1} (f64)x_i²)` in float64, summing sequentially from `i = 0`.
3. `|norm − 1| ≤ 8 · 2^−23` MUST hold. Otherwise reject with `NotNormalised`.

The tolerance is 8 float32 ULPs at 1.0: correctly normalised float32 data lands within about 2 ULPs of 1.0
(the worst P0 row is 1.54 ULPs, DB-61),
while an un-normalised embedding has a norm several orders of magnitude further off.

### 4.2 Quantisation (Q24)

`x̃_i = round_half_to_even( (f64)x_i · 2^24 )`, stored as `i32`.

- The float32-to-float64 conversion and the multiplication by a power of two are both exact, so the
  only rounding is the final one.
- Ties go to even (IEEE 754 default; unbiased, so no drift accumulates in sums).
- Bound: `|x_i| ≤ norm ≤ 1 + 8·2^−23`, so `|x̃_i| ≤ 2^24 + 16 = 16,777,232 < 2^31`. The `i32`
  storage is safe.

The SDK on the application backend and the engine MUST use the same quantiser, because the
application backend builds `C_t` from `x̃`.

### 4.3 Dequantisation

`x̂_i = x̃_i / 2^24`. For routing it is computed in float64 (exact). For search it is converted to
float32 (exact whenever `|x̃_i| ≤ 2^24`, otherwise rounded to nearest even).

### 4.4 Accumulator bounds

`S_i = Σ x̃_i` over the group's members, stored as `i64`. With at most 10^6 members,
`|S_i| ≤ 10^6 · 16,777,232 = 1.6777232 × 10^13 < 2^44 ≈ 1.759 × 10^13`. That leaves 19 bits of
headroom in `i64`. **The 10^6 cap MUST be enforced on every insert** (INV-4); raising it requires
redoing this bound (at 10^7 members the bound is 48 bits, still safe).

### 4.5 Integer-to-scalar mapping (for commitments)

For `v ∈ i64`: `scalar(v) = v mod ℓ` if `v ≥ 0`, and `ℓ − (|v| mod ℓ)` if `v < 0`.
`i64::MIN` cannot occur (§4.4).

---

## 5. Groups, accumulators and exact deletion

### 5.1 Group kinds

| Kind | ID | Created | Accumulator | Searchable |
|---|---|---|---|---|
| **Frozen** | `frozen-NNNN` (4-digit, zero-padded partition label) | At collection creation, from the artefact | Yes | Yes |
| **Spawned** | `spawn-` + 16 lowercase hex characters (§7.5) | By a holding-area flush | Yes | Yes |
| **Holding area** | `holding` | At collection creation (one per collection) | **No** | **No** |

Group IDs are at most 32 bytes. Groups are never removed, merged, renamed or re-fitted. The 4-digit
form allows at most 10,000 frozen groups (labels 0–9999); an artefact with a larger `k_frozen` is
rejected (DB-63).

### 5.2 Group state

For each frozen or spawned group: `S` (`i64^d`), `n` (`u64`), `C_S` (point), `r_agg` (scalar),
the centroid `μ` (`f64^d`), and the member list (records with their `x̃`).

**Initial state:** `S = 0`, `n = 0`, `r_agg = 0`, `C_S = identity` (the 32-byte all-zero encoding).

### 5.3 Insert and delete arithmetic

Insert record `t` into group `g`:

```
S   ← S + x̃_t            n ← n + 1
r_agg ← r_agg + r_t mod ℓ   C_S ← C_S + C_t
```

Delete record `t` from group `g`:

```
S   ← S − x̃_t            n ← n − 1
r_agg ← r_agg − r_t mod ℓ   C_S ← C_S − C_t
```

All four fields MUST change together in one transaction (INV-2). Because integer and group
arithmetic are exact, after the deletion every field equals the value it would have had if `t` had
never been inserted.

### 5.4 Membership, idempotency and excision

- **Physical excision.** A deleted record is removed from the member list. There are no deletion
  markers. A marker would itself be the leftover trace this system exists to remove.
- **Idempotent deletion.** Before subtracting, the engine checks that the record is still a member.
  If it is absent, the deletion returns `AlreadyAbsent`, changes nothing, and issues no certificate.
  Without this check, an application backend retrying after a timeout could subtract a vector twice.
- **Empty groups.** When `n` reaches 0, `S = 0`, `r_agg = 0` and `C_S = identity` exactly. The group
  stays forever and still occupies a search probe slot (§8). Any computation that divides by `n`
  MUST handle `n = 0`.

### 5.5 The canonical group blob and the exactness relation

The **canonical group blob** is the byte string that the exactness claim is about. It is never
stored; the engine generates it in memory on demand and wipes it after use.

```
b"SEVERG"                         6 bytes
u16be format_version = 1
u16be d
u64be n
i64be × d                         S
32 bytes                          C_S
32 bytes                          r_agg
u64be member_count                (MUST equal n)
per member, ascending by record-ID bytes:
    u16be id_len ‖ id bytes ‖ i64be × d (x̃, widened from i32)
```

A parser MUST reject: `member_count ≠ n`, unsorted or duplicate IDs, empty IDs, and trailing bytes.
This layout is identical to the earlier SEVER prototype's, so its blobs can be compared directly.

**Extension region and core form (overview DB-47).** The bytes between `S` and `member_count` are the
group extension's region, and the extension chooses the magic. The layout above is the **full form**
(magic `SEVERG`, region `C_S ‖ r_agg`), produced once commitments exist (build Part 3). Before that,
the **core form** has magic `b"SEVERC"` and an empty region; every other field is as above. A parser
MUST reject a magic that does not match the form it expects.

**Exactness relation.** Two group states are *equivalent* if and only if all five of these are equal:
(1) `S`, (2) `n`, (3) `C_S`, (4) the canonical blob byte for byte, (5) the member ID list.

- The single helper `assert_state_equivalent(a, b)` MUST compare all five fields independently
  (fields 1, 2, 3 and 5 are also inside field 4; the redundancy is deliberate). It works on frozen
  snapshots whose blob is stored as data, so each field can be corrupted on its own in the sabotage
  test. A corruption of any one field MUST be caught.
- **Insertion-order independence.** Inserting the same set of records into a group in any order
  MUST yield an identical canonical blob.

**Outside the relation (declared, not hidden):** which groups exist and their centroids (the
index shape); holding-area contents; WAL and storage-checkpoint history (ciphertext); log leaves and
certificates (public by design); timestamps; file sizes; key-file slot order; each group's key
version. The companion overview lists each as a limit with its justification (L-3 to L-5).

### 5.6 Capacity

- **Hard cap (all groups):** an insert that would make `n > 1,000,000` MUST be rejected with
  `GroupCapacityExceeded`.
- **Spawn capacity (spawned groups only):** a spawned group *has room* when `2·k·n < 3·N`, which is
  exact integer arithmetic for `n < 1.5·N/k` (§7.3). This is a routing preference, not a rejection
  rule.
- At startup the engine MUST check that `⌊1.5·N/k⌋ ≤ 1,000,000` (INV-5).

---

## 6. The partition artefact and the partition builder

### 6.1 Purpose

The frozen partition is fitted **once, offline**, on a public reference dataset that contains no user
data, and then never changes. The engine never fits anything: it imports an artefact produced by the
partition builder (component C-15, Python). This keeps floating-point model fitting out of the
engine and makes the partition a hashed, reproducible file.

### 6.2 Builder algorithm

Inputs: the reference embeddings `X_ref` (float32, `m × d`, each row normalised per §4.1), a seed,
and `k_frozen = 128`.

1. **Quantise and dequantise** every reference row (§4.2–4.3), giving `X̂_ref` in float64. All later
   steps use `X̂_ref`, so the threshold is computed on exactly the representation the engine routes.
2. **k-means** on `X̂_ref` with scikit-learn `KMeans(n_clusters=128, init="k-means++", n_init=10,
   max_iter=300, tol=1e-4, algorithm="lloyd", random_state=seed_kmeans mod 2^32)`, where
   `seed_kmeans` is the `u64` derived from the run seed (overview §10.6); scikit-learn accepts only
   seeds below 2^32 (overview DB-57). Outputs: centroids `μ_0 … μ_127` (float64) and each
   row's label `c(j)`. Group `frozen-NNNN` is label `NNNN`.
3. **Pooled residuals.** `R_j = x̂_j − μ_{c(j)}` for every reference row, stacked into one
   `m × d` matrix.
4. **Pooled Ledoit–Wolf.** One Ledoit–Wolf shrinkage estimate over all rows of `R`
   (`assume_centered = False`), giving `Σ` and the shrinkage intensity. "Pooled" means one fit over
   the stacked residuals, **not** an average of per-group fits: shrinkage is derived for one sample
   and applied once.
5. **Precision matrix.** `P = Σ^{-1}`, computed by Cholesky factorisation in float64. Stored
   explicitly and used as stored; the engine never inverts anything.
6. **Drift threshold.** `τ = percentile_99( d_M(x̂_j, μ_{c(j)}) )` over all reference rows, where
   `d_M` is §7.2's Mahalanobis distance computed with the engine's summation order, and the
   percentile uses linear interpolation (NumPy `method="linear"`).
7. **Independent oracle (MUST).** The builder also computes the Ledoit–Wolf estimate from the
   published formula (Ledoit & Wolf 2004, Theorem 1) in plain NumPy, sharing no code with
   scikit-learn, and refuses to write the artefact unless the shrinkage intensities agree to 1e-12
   and the thresholds to 1e-9.

The threshold is a build-time output, never a hand-set constant. It depends on the reference set and
`k_frozen`, not on how much live data exists, so it only needs recomputing for a new dimension or
reference set.

### 6.3 Artefact format (`partition.svp`)

```
b"SVDBPART"                       8
u16be format_version = 1
u16be d
u16be k_frozen
u64be seed                        the run seed (not the derived k-means seed)
f64be tau
f64be lw_shrinkage
u64be m                           reference rows used
32 bytes  sha256_reference        SHA-256 of the reference embedding file (raw little-endian float32 rows as produced by the encoder, row order as in the manifest)
u16be encoder_len ‖ encoder bytes e.g. "sentence-transformers/all-MiniLM-L6-v2@<commit>"
f64be × (k_frozen × d)            centroids, row-major, label order
f64be × (d × d)                   precision matrix P, row-major
32 bytes  sha256_artefact         SHA-256 of every preceding byte
```

`create_collection` MUST verify `sha256_artefact`, `d`, and that `P` has finite entries; a failed
check is rejected with `IntegrityViolation` naming the check, never a value (DB-64). The
artefact's hash is recorded in the collection metadata and in every run ledger entry.

---

## 7. Routing, drift detection and spawning

Routing is a **pure function of the vector and the current state**: no clock, no arrival counter, no
"most recent group" rule. The same `(x̃, state)` MUST always give the same destination.

### 7.1 Nearest frozen group

`j* = argmin_j Σ_{i=0}^{d−1} (x̂_i − μ_{j,i})²` over frozen groups only, in float64 with a sequential
sum from `i = 0`. Ties go to the smaller label.

### 7.2 Mahalanobis drift test

```
δ   = x̂ − μ_{j*}                              (f64^d)
y_a = Σ_{b=0}^{d−1} P[a][b] · δ_b             (for each a, sequential in b)
q   = Σ_{a=0}^{d−1} δ_a · y_a                  (sequential in a)
d_M = sqrt(q)
```

`q < 0` MUST raise `IntegrityViolation` (`P` is positive definite). The vector is
**in-distribution** if `d_M ≤ τ` and **out-of-distribution (OOD)** if `d_M > τ`. Spawned groups
have no threshold of their own; drift is always measured against the frozen partition.

### 7.3 Destination rule

```
route(x̃, state):
    j* ← nearest frozen group (§7.1)
    if d_M(x̂, μ_{j*}) ≤ τ:                        # in-distribution
        return frozen group j*
    # out-of-distribution: spillover is checked first, on every OOD vector
    R ← { spawned groups g : 2·k·n_g < 3·N }        # has room
    if R non-empty:
        return argmin_{g ∈ R} Σ_i (x̂_i − μ_{g,i})²  # f64, sequential; ties → smaller group-ID bytes
    return holding area
```

`k` and `N` are the values **before** this insert.

### 7.4 Holding area and flush

- A record routed to the holding area is stored encrypted, with its `r_t` like every record (§9.4),
  but is not added to any accumulator, is not counted in `N`, and is **not searchable**.
- It is **always deletable immediately**. Deletion is never queued.
- When an insert brings the holding area to exactly **200** records, the same transaction performs a
  **flush**: exactly those 200 records form exactly one new spawned group. There is no clustering
  step inside a flush.
- The holding area has no other exit. Nothing ever spills into a group while a flush is creating it.
- Size at creation is exactly 200. Spawned groups can grow past 200 afterwards, but only through
  spillover.

### 7.5 A spawned group's identity and centroid

- **ID:** `spawn-` followed by the first 16 lowercase hex characters of
  `SHA-256( ‖_{ids ascending by bytes} u16be(len) ‖ id )` over the founding cohort's record IDs. The
  ID depends only on membership, never on the order in which groups were created. If the ID already
  exists in the collection, the flush MUST fail with `IntegrityViolation` (probability about
  `k²/2^65`).
- **Centroid:** `μ_i = ((f64)S_i / 2^24) / n`, computed once at creation from the new group's exact
  accumulator, then **frozen**. It does not move when spillover arrives, so it drifts away from the
  members' mean over time. That drift is intended and is reported.
- Spawned groups are frozen from creation, have no drift threshold, and never spawn further groups.

### 7.6 Counters

`N` increases on every insert into a frozen or spawned group and by 200 on each flush; it decreases
on every deletion from a frozen or spawned group. It never changes for holding-area inserts or
deletions. `k` increases by one on each flush.

### 7.7 Determinism claim (and its limit)

Given the same partition, configuration, code and **input order**, the engine produces byte-identical
state. It does **not** claim that different input *orders* yield the same index shape: a
size-triggered holding area fills with a different cohort under a different order, so different groups
spawn. Tests MUST check three things:
(1) the same `(x̃, state)` gives the same destination;
(2) two states that differ only in group creation order give the same destination;
(3) the same seed and input order give a byte-identical index.

---

## 8. Search

### 8.1 Algorithm

Input: a query `q` (float32, `d` values, checked per §4.1 steps 0–3: dimension, finiteness and normalisation) and `k_results`.

1. **Rank groups.** For every frozen and spawned group (holding area excluded), compute
   `D_g = Σ_i ((f64)q_i − μ_{g,i})²` in float64 with a sequential sum. Sort ascending by
   `(D_g, group-ID bytes)`.
2. **Probe budget.** `p = ⌈0.25 · k⌉`, where `k` counts all frozen and spawned groups, **empty ones
   included**. Take the first `p` groups. An empty group uses a probe slot and contributes nothing.
   This keeps "25 % coverage" meaning the same thing at every deletion level.
3. **Scan.** For every member of every probed group, compute `score = Σ_i (q_i − x̂_i)²` in float32
   using the pinned kernel of §8.2, where `x̂` is read from the float32 mirror (§12.6).
4. **Top-k.** Return the `k_results` smallest scores, ordered by `(score, record-ID bytes)`.

Holding-area records never appear. A deleted record MUST NOT appear in any result produced after its
deletion is acknowledged (INV-9).

### 8.2 The pinned distance kernel

Scalar and SIMD implementations MUST produce bit-identical scores:

- `d` MUST be a multiple of 8 (384 is).
- Eight float32 partial sums `L_0 … L_7`, all starting at `+0.0`. For `i = 0 … d−1`, lane
  `j = i mod 8` does `t = q_i − x̂_i; L_j = L_j + t·t`, with the multiply and the add as **separate
  IEEE operations (no fused multiply-add)**.
- Final reduction: `((L_0 + L_1) + (L_2 + L_3)) + ((L_4 + L_5) + (L_6 + L_7))`.
- The AVX2 kernel implements exactly this lane layout with 256-bit registers and is compiled with
  FMA contraction disabled. AVX2 is detected at runtime; the scalar kernel is the fallback. There is
  no AVX-512 path.

### 8.3 Why IVF-flat and not a graph index

In an IVF index, a record lives in exactly one posting list and can be removed exactly. In a graph
index (HNSW, DiskANN), the neighbours' edge lists were chosen partly *because* of the deleted node, so
the graph keeps a structural trace after the node is gone. v1 therefore supports only IVF-flat.

---

## 9. Cryptography

### 9.1 Primitive set

| Primitive | Standard | Crate (pinned, §20) | Used for |
|---|---|---|---|
| ristretto255 group | RFC 9496 | `curve25519-dalek 4.1.3` | Commitments, proof |
| `hash_to_group` (`expand_message_xmd`, SHA-512) | RFC 9380 §5.3.1, RFC 9496 §4.3.4 | `curve25519-dalek` + `sha2` | Generators |
| SHA-512 | FIPS 180-4 | `sha2 0.10.9` | Generators, challenge, HMAC, generator digest |
| SHA-256 | FIPS 180-4 | `sha2 0.10.9` | Log (RFC 9162), spawn IDs, artefact and manifest hashes |
| HMAC-SHA-512 | RFC 2104 | `hmac 0.12.1` | Scrambled record IDs |
| Ed25519 (`verify_strict`) | RFC 8032 | `ed25519-dalek 2.2.0` | User, operator and witness signatures |
| Merlin transcripts (STROBE) | Merlin 3 | `merlin 3.0.0` | Hedged proof nonces |
| AES-256-GCM-SIV | RFC 8452 | `aes-gcm-siv 0.11.1` | All encryption at rest |
| CRC-32C | Castagnoli | `crc32c 0.6.8` | Integrity of disk records (not security) |

No other primitive is used. No primitive is implemented by this project.

### 9.2 Generators

```
H   = ristretto255_from_uniform_bytes( expand_message_xmd_sha512( msg = b"H",                DST_GEN, 64 ) )
G_i = ristretto255_from_uniform_bytes( expand_message_xmd_sha512( msg = b"G" ‖ u32be(i),     DST_GEN, 64 ) )
      for i = 0 … d−1
```

One independent `expand_message` call per generator, one fixed DST, a fixed-width big-endian index.
This is the standard `hash_to_group` construction.

**Startup self-check (MUST, refuse to run on mismatch):** re-derive `H`, `G_0` and `G_{d−1}` and
compare them with the frozen golden file (Appendix B); run the RFC 9496 known-answer tests for the
one-way map and `expand_message_xmd`. The verifier (C-16) performs the same checks with its own code.

### 9.3 Commitments

- Record: `C_t = r_t·H + Σ_{i} scalar(x̃_i)·G_i`.
- Group: `C_S = r_agg·H + Σ_{i} scalar(S_i)·G_i`.
- Public transition check: `C_S_post + C_t = C_S_pre`.

On insert the engine MUST recompute `C_t` from the quantised vector and the supplied `r_t`, and
reject with `CommitmentMismatch` if it differs from the supplied `C_t`.

### 9.4 Blinding values

The application backend generates `r_t` as 64 bytes from the OS CSPRNG, reduced with
`Scalar::from_bytes_mod_order_wide`, and sends it with the insert. The engine stores `r_t` for every
record, and only encrypted under the record key, inside the slot payload (§13.2, §14.4). It adds `r_t`
into `r_agg` when the record joins a group (at insert or at a flush) and subtracts the stored `r_t` at
deletion. Deletion takes no `r_t` argument. Destroying the record key at deletion erases `r_t`
(§13.5).

### 9.5 Proof of knowledge of the group state

After a deletion, the operator proves it knows `(r_post, s_0 … s_{d−1})`, where
`s_i = scalar(S_post_i)`, such that

`C_S_post = r_post·H + Σ_i s_i·G_i`.

This is a proof of knowledge of a representation (Okamoto; Camenisch–Stadler), the multi-secret
generalisation of Schnorr's proof, made non-interactive by Fiat–Shamir.

**Deletion context.** `ctx = C_S_pre (32) ‖ C_t (32) ‖ scrambled_id (64) ‖ u64be(database_lsn) ‖
collection_id (16)`, 152 bytes.

**Prover:**

```
(k_r, k_0 … k_{d−1}) ← hedged nonces (§9.6)
A   = k_r·H + Σ_i k_i·G_i                                  (constant-time multiscalar mult.)
c   = from_bytes_mod_order_wide( SHA-512( DST_POSK ‖ C_S_post ‖ A ‖ ctx ) )   # 15+32+32+152 = 231-byte preimage
z_r = k_r + c·r_post  mod ℓ
z_i = k_i + c·s_i     mod ℓ
proof = A ‖ z_r ‖ z_0 ‖ … ‖ z_{d−1}                         # 32 + 32 + 32·d = 12,352 bytes at d = 384
```

**Verifier:** decode `A` and every `z` canonically (reject otherwise); recompute `c`; accept if and only
if `z_r·H + Σ_i z_i·G_i = A + c·C_S_post` (variable-time multiscalar multiplication is fine here,
because every input is public).

**Binding the context into the challenge.** Standard practice binds every part of a statement into
the Fiat–Shamir challenge. Here the proven statement is `C_S_post`; the context additionally binds
the pre-state, the deleted commitment, the record, the log position and the collection. A proof
therefore cannot be replayed in another certificate. All fields are fixed-width, so raw concatenation
is unambiguous.

**Soundness note.** Two accepting transcripts with the same `A` and different challenges reveal every
secret (`x = (z_1 − z_2)/(c_1 − c_2)` per component). Reusing a nonce vector once would leak the
group's entire sum, which is why §9.6 exists.

### 9.6 Hedged nonce derivation

The nonces are derived from three sources at once — the secret witness, the public statement and
fresh OS entropy — so neither a broken random source nor a fault injected mid-proof can repeat a
nonce vector.

```
gdigest = SHA-512( H ‖ G_0 ‖ … ‖ G_{d−1} )                 # computed once at startup
T = merlin::Transcript::new(DST_NONCE)
T.append_message(b"gens", gdigest)
T.append_message(b"stmt", C_S_post)
T.append_message(b"ctx",  ctx)
B = T.build_rng()
B = B.rekey_with_witness_bytes(b"r", bytes(r_post))
for i in 0 … d−1:  B = B.rekey_with_witness_bytes(b"s", bytes(s_i))
rng = B.finalize(&mut StrictProofRng)                      # injects 32 bytes of OsRng entropy
for each of k_r, k_0, …, k_{d−1} in that order:
    fill 64 bytes from rng;  nonce = from_bytes_mod_order_wide(bytes)
```

- `StrictProofRng` is a zero-sized wrapper around `OsRng` that implements `RngCore + CryptoRng` and
  deliberately does **not** implement `SeedableRng`. The prove function accepts only this concrete
  type, so wiring a seeded generator into proof generation is a compile error.
- The Python binding exposes no way to pass an RNG, a seed or a nonce; any attempt raises
  `SeededNonceForbidden`.
- The nonce derivation is not consensus-critical (the verifier never recomputes it), but it is pinned
  here so that it can be audited and tested.

### 9.7 Scrambled record IDs

`scrambled_id = HMAC-SHA-512( k_scramble, collection_id ‖ record_id_bytes )` — 64 bytes.

`k_scramble` is 64 bytes from the OS CSPRNG, generated once per database, held only by the operator,
and never rotated. The operator can prove to an auditor which record a certificate refers to by
recomputing the HMAC; a reader of the public log cannot build a list of deleted IDs. Every table,
WAL record and log leaf identifies records only by `scrambled_id`.

### 9.8 Signatures and key epochs

| Signer | Message | Key lifetime |
|---|---|---|
| User key (at insert; used by the application backend, §3.3) | `DST_INSERT ‖ collection_id ‖ C_t` (65 bytes) | Never rotates |
| Operator (log checkpoint) | `DST_STH ‖ u64be tree_size ‖ root ‖ u64be timestamp_ms ‖ u32be epoch` (66 bytes) | 90-day epochs |
| Witness (cosignature) | `DST_COSIGN ‖` the 66-byte log-checkpoint message (83 bytes) | 90-day epochs |
| Operator (certificate) | `DST_CERT ‖` certificate body (§11.1) | 90-day epochs |

- Epoch `e` covers `[genesis + 90·e days, genesis + 90·(e+1) days)`, where `genesis` is the database
  creation time. Old public keys stay resolvable forever, so old certificates keep verifying.
- All signature checks use `verify_strict` (rejects small-order keys and non-canonical encodings).
- In v1 the five witnesses are simulated by the project, and their keys live in the test harness.

### 9.9 Encoding rules

All points and scalars MUST be canonical on parse. Non-canonical encodings MUST be rejected; accepting
them would reintroduce malleability. `C_t` MUST NOT be the identity.

---

## 10. Transparency log, log checkpoints and witnesses

### 10.1 Structure

One append-only Merkle log per database, exactly as RFC 9162 §2.1 specifies: SHA-256,
`leaf_hash = SHA-256(0x00 ‖ leaf)`, `node_hash = SHA-256(0x01 ‖ left ‖ right)`, the left-heavy tree
built from the largest complete left subtree. Inclusion and consistency proofs use RFC 9162's own
algorithms. It is not a Merkle Mountain Range.

### 10.2 Leaves

| Type | Bytes | Appended when |
|---|---|---|
| **Insert** | `0x01 ‖ collection_id (16) ‖ scrambled_id (64) ‖ C_t (32) ‖ user_public_key (32) ‖ user_signature (64)` = 209 bytes | Every insert, including holding-area inserts |
| **Delete** | `0x02 ‖` certificate bytes (§11) | Every deletion that removes a record |

**`database_lsn`** of an operation is the 0-based index of its leaf. The log is ordered
chronologically, by append position. Publishing the user's public key in the insert leaf fixes which
account key signed each commitment. Because the application backend holds that key (§3.3), this records
that the service acted for an authenticated account; it does not stop a dishonest operator, who holds
the keys (overview L-27).

### 10.3 Log checkpoints

A **log checkpoint** is `(tree_size, root, timestamp_ms, epoch, operator_signature)`, signed over the
message in §9.8. The engine issues one:

- whenever `tree_size` reaches a multiple of 10,000 (both leaf types count), and
- **on demand** before a deletion, if the record's insert leaf is not yet covered by any log checkpoint,
  because the certificate must prove inclusion against a signed, cosigned log checkpoint (§11.2).

### 10.4 Witnesses

Five witnesses, threshold four. Each witness remembers the last log checkpoint it cosigned, requests the
RFC 9162 consistency proof from that log checkpoint to the new one, verifies it, and only then cosigns.
A log checkpoint with at least four valid cosignatures is **witnessed**. In v1 the witnesses are simulated
by the project; the mechanism is built and tested, but the guarantee it would give needs genuinely
independent witnesses (limit L-7 in the overview).

### 10.5 Storage

Leaf bytes of insert leaves and all leaf hashes are kept in append-only stores (§14.8). The engine
keeps every level of the tree's complete subtrees in memory so that any inclusion proof takes
`O(log n)` time; at 1.9 million leaves this costs about 122 MB (Appendix A).

---

## 11. Deletion certificates

### 11.1 Encoding

A certificate is a deterministic TLV sequence followed by the operator's signature. It is not
protobuf, because protobuf serialisation is not guaranteed to be canonical and signed bytes must be.

```
repeat for tag = 1 … 13, in ascending order, each exactly once:
    u8 tag ‖ u32be length ‖ value
then:
    u8 0xFF ‖ u32be 64 ‖ operator_signature over (DST_CERT ‖ all preceding bytes)
```

A parser MUST reject: missing, repeated or out-of-order tags; a wrong length for any fixed-size field;
and trailing bytes.

| Tag | Field | Value |
|---|---|---|
| 1 | `commitment_to_deleted_vector` | `C_t`, 32 |
| 2 | `group_commitment_before` | `C_S_pre`, 32 (empty for a holding-area deletion) |
| 3 | `group_commitment_after` | `C_S_post`, 32 (empty for a holding-area deletion) |
| 4 | `posk_proof` | `A ‖ z_r ‖ z_0…z_{d−1}`, 12,352 at d = 384 (empty for a holding-area deletion) |
| 5 | `user_authorisation_signature` | The user's insert signature, 64 |
| 6 | `insert_inclusion` | Nested, §11.2 |
| 7 | `witness_cosignatures` | `u8 count ‖ count × (u8 witness_index ‖ u32be witness_epoch ‖ signature 64)` over the log checkpoint in tag 6 |
| 8 | `key_period` | `u32be` operator epoch that signs this certificate |
| 9 | `scrambled_record_id` | 64 |
| 10 | `database_lsn` | `u64be`, this deletion's own leaf index |
| 11 | `group_emptied_by_this_deletion` | `u8`, 0 or 1 |
| 12 | `deletion_kind` | `u8`: 0 = from a group, 1 = from the holding area |
| 13 | `collection_id` | 16 |

Tags 1 to 11 have the same meanings, in the same order, as the earlier SEVER prototype's certificate;
tags 12 and 13 are new, and the encoding changes from protobuf to TLV (DB-22). A certificate for a
group deletion at d = 384 is about **14.1 KB** (Appendix A).

Tag 5 keeps its name from the earlier prototype. Its value is the insert signature made by the
application backend with the account's user key (§3.3). It attests the insert, not the deletion.

**Why `group_emptied_by_this_deletion` exists.** A spawned group persists after all its founders are
deleted, because other records joined it later and cannot be re-routed. That residue is accepted, and
the receipt discloses it rather than hiding it. A boolean discloses the fact without publishing the
group's size in every certificate.

### 11.2 The `insert_inclusion` field (tag 6)

```
u8 version = 1
insert_leaf (209 bytes, §10.2)
u64be leaf_index
log checkpoint: u64be tree_size ‖ root (32) ‖ u64be timestamp_ms ‖ u32be epoch ‖ operator_signature (64)
u8 path_len ‖ path_len × 32-byte hashes          (RFC 9162 inclusion path)
```

The field carries everything a verifier needs to check, **with no other input**, that this exact
commitment was inserted under a user key published in a signed, witnessed log checkpoint.

### 11.3 Verification algorithm (verifier, C-16)

Inputs: the certificate, and trust anchors bundled with the verifier release (operator public keys by
epoch, witness public keys by epoch, a genesis log checkpoint, and the generator golden file).

1. **Parse** strictly (§11.1). Decode every point and scalar canonically. Reject if `C_t` is the
   identity.
2. **Operator signature:** the key for tag 8's epoch MUST be in the anchors; verify the trailer.
3. **Insert inclusion (tag 6):** the leaf type is `0x01`; the leaf's `collection_id`, `scrambled_id`,
   `C_t` and `user_signature` equal tags 13, 9, 1 and 5. Verify the user signature over
   `DST_INSERT ‖ collection_id ‖ C_t` with the leaf's user key. Recompute the leaf hash and verify the
   inclusion path against the log checkpoint's root. Verify the log checkpoint's operator signature for its
   epoch.
4. **Witnesses (tag 7):** at least four cosignatures from distinct witnesses, each valid for its
   epoch, over that log checkpoint.
5. **Ordering:** `database_lsn` (tag 10) > `leaf_index` (tag 6).
6. **If `deletion_kind = 0` (from a group):**
   - `C_S_post + C_t = C_S_pre`;
   - the proof (tag 4) verifies with `ctx = C_S_pre ‖ C_t ‖ scrambled_id ‖ u64be(database_lsn) ‖
     collection_id`;
   - `group_emptied_by_this_deletion = 1` if and only if `C_S_post` is the identity (an empty group
     has `S = 0` and `r_agg = 0`, §5.4).
7. **If `deletion_kind = 1` (from the holding area):** tags 2, 3 and 4 are empty and tag 11 is 0.
   Only steps 1–5 apply: the certificate proves the deletion of a logged insert that was never added
   to any accumulator.
8. Accept only if every step passes.

**What a valid certificate proves.** The record was inserted under the account's key in a signed,
witnessed log. For a group deletion, the group's accounting moved by exactly that record (its
commitment moved from `C_S_pre` to `C_S_post` by exactly `C_t`), and the operator knows an opening of
the new state.

**What no certificate can prove**, by any means: that the operator kept no copy (no cryptography can),
or that the user personally authorised the deletion, because the application backend holds the user key
and decides who may delete (§3.3; overview L-2, L-27).

**What it does not prove** (auditor's job, done with log access by the `sever-audit` tool, C-17):

- that the deletion leaf itself was appended at `database_lsn` (a certificate cannot contain a proof
  of its own leaf);
- that consecutive certificates chain correctly (`C_S_pre` of one equals `C_S_post` of the previous
  one for the same group);
- that the log is consistent across log checkpoints.

**Forward limit.** A verifier with anchors fixed at release cannot check a certificate signed under an
operator epoch created after that release. A deployment would fetch anchors live.

---

## 12. Storage engine

### 12.1 Model: memory-resident, disk-durable

All live state is held in memory. The disk exists to rebuild that state after a crash, and it only
ever receives **ciphertext** for anything secret (§13, table in §13.2). Durability comes from a
write-ahead log (WAL) plus periodic full **storage checkpoints**. Files are laid out in fixed-size
pages, so a page cache can be added later without a format change. v1 requires the collection to fit
in RAM (about 3.8 GB at 10^6 vectors, Appendix A).

Certificates, passage text and log leaves are **not** held in RAM; they live in append-only on-disk
stores and are read on demand.

### 12.2 Storage I/O layer (VFS)

Every read and write goes through a `Vfs` trait: `open`, `read_at`, `write_at`, `append`, `fsync`,
`fsync_dir`, `rename`, `unlink`, `truncate`, `list`, `create_dir`, `remove_dir` (the last two for
storage checkpoint directories, §15.6; overview DB-65). There are two backends:

- `PosixVfs` — real files.
- `SimVfs` — in memory and seeded. It models the POSIX durability contract conservatively: only
  `fsync`ed data and `fsync_dir`ed directory entries survive a simulated crash. It can drop any
  unsynced write, tear a write at any byte, reorder unsynced writes, and make any `fsync` fail. All
  crash tests run on `SimVfs`, so they are deterministic.

### 12.3 Write-ahead log

- Segment files `wal/<seq>.wal`, 64 MiB each, append-only.
- A transaction is a `BEGIN` record, any number of change records, and a `COMMIT` record. **A
  transaction is committed exactly when its `COMMIT` record, with a valid CRC, is durable.**
- Change records carry **after-images in ciphertext form** (§14.6). Replay applies after-images and
  never decrypts anything.
- On recovery, a transaction without a valid `COMMIT` (including a torn or CRC-failing tail) is
  discarded whole. It is never repaired.
- The WAL MUST NOT contain plaintext vectors, record IDs, passage text, `r_t`, `S`, `r_agg` or
  unwrapped keys (INV-11). It MAY contain `scrambled_id`s, `n`, `C_S`, centroids and public log leaves.
- WAL positions are called `wal_seq`. They are unrelated to `database_lsn` (§10.2).

### 12.4 Storage checkpoints

A storage checkpoint writes the whole in-memory state, in ciphertext form, to a new directory,
installs it atomically, and deletes the WAL segments it covers (§15.6). It runs every 1 GiB of WAL
and at clean shutdown. An interrupted storage checkpoint leaves the previous one valid.

### 12.5 Transactions and isolation

- **One writer at a time** (a writer mutex). Searches take a shared lock. Applying a committed
  transaction to memory takes the exclusive lock briefly.
- This gives **serializable** isolation. A reader that starts before a deletion either finishes before
  the apply or sees the post-deletion state, never a mix.
- There are **no retained snapshots** (no MVCC): a snapshot that still contains a deleted record would
  be a copy of it in memory.
- `delete_user` removes many records, across many groups, in **one** transaction: all or nothing.

### 12.6 In-memory structures

| Structure | Contents | Plaintext in RAM? |
|---|---|---|
| Group table | Header, `n`, `C_S`, centroid, key version, bucket versions | Public fields only |
| Accumulators | Decrypted `S` and `r_agg` per group | Yes, in locked memory (§12.8) |
| Slot arrays | Member slots as ciphertext, exactly as on disk | No |
| Search mirror | Per member: `x̂` as float32 and the record ID | Yes (not locked, L-6 in the overview) |
| Locator | `scrambled_id → (group, slot index)` | Scrambled only |
| Key cache | Group keys, bucket keys | Yes, in locked memory |
| Log tree | Every level of complete-subtree hashes, plus the frontier | Public |
| Counters | `N`, `k`, next `database_lsn`, next `wal_seq` | Public |

Deleting a record overwrites its mirror entry, record ID bytes and any decrypted buffers with zeros
**before** the deletion is acknowledged.

### 12.7 Durability discipline

- Every file creation, rename or unlink is followed by `fsync` of the containing directory.
- An `fsync` error **aborts the process**. Recovery happens on restart from the WAL. A failed `fsync` is
  never retried, because after a failure the kernel may already have dropped the dirty pages.
- No writes go through `mmap`; a failed write through a mapping kills the process with a signal
  instead of returning an error.
- Every record on disk has a CRC-32C; every file has a magic number and a format version.

### 12.8 Memory hygiene

- Every secret type implements `Zeroize` and `ZeroizeOnDrop`.
- Key material and decrypted accumulators live in `mlock`ed pages.
- At startup the engine sets `RLIMIT_CORE = 0` and `PR_SET_DUMPABLE = 0`.
- The engine refuses to start if swap is enabled and not encrypted, or if hibernation is enabled,
  unless `memory.allow_unsafe_memory = true`, which is for development only and is recorded in every
  run ledger entry.

### 12.9 Platform checks at startup

- Linux x86-64.
- The data directory is on ext4 or XFS.
- The key file's filesystem overwrites in place: ZFS is refused, and btrfs is refused unless the key
  file carries the no-copy-on-write attribute.
- `ENGINE.lock` is taken exclusively (one process per data directory).
- The generator self-check (§9.2) and the configuration and artefact hash checks pass.

---

## 13. Key hierarchy and physical erasure

### 13.1 Three levels

| Level | Key | Stored | Count |
|---|---|---|---|
| 1 | **Group key** `GK_g` | **Only** in the key file (§14.7), plaintext, erasable | One per group, including the holding area |
| 2 | **Bucket keys** `BK_{g,b}`, b = 0…63 | Wrapped under `GK_g` | 64 per group |
| 3 | **Record key** `RK_t` | Wrapped under `BK_{g,b(t)}` | One per record |

A record's bucket is `b(t) = scrambled_id[0] mod 64`. It never changes while the record is live.

All keys are 32 bytes from the OS CSPRNG. **Only group keys ever need physical erasure.**

### 13.2 What is encrypted, under which key, with which associated data

All encryption is AES-256-GCM-SIV with a random 96-bit nonce and a 16-byte tag, so every ciphertext
costs 28 bytes of overhead. The associated data (AD) binds each ciphertext to its owner, so it cannot
be moved to another record, field or key version.

| Data | Key | Associated data |
|---|---|---|
| Slot payload (record ID, `x̃`, insert leaf index, `r_t`) | `RK_t` | `collection_id ‖ scrambled_id ‖ 0x01` |
| Passage text | `RK_t` | `collection_id ‖ scrambled_id ‖ 0x02` |
| Wrapped record key | `BK_{g,b}` | `collection_id ‖ group_id(32, zero-padded) ‖ scrambled_id ‖ u64be bucket_version` |
| Wrapped bucket key | `GK_g` | `collection_id ‖ group_id ‖ u8 b ‖ u64be group_key_version` |
| `S ‖ r_agg` | `GK_g` | `collection_id ‖ group_id ‖ u64be group_key_version ‖ u64be n` |

Record-level ciphertexts deliberately carry **no** group, position or key version. A slot can therefore
move within a group, or from the holding area into a new group, without being decrypted, and a key
rotation never re-encrypts member data — only keys and the accumulator.

**Plaintext on disk, on purpose:** `n` and group sizes; `C_S` (its differences are the public `C_t`s);
centroids (a spawned centroid is the founding cohort's mean, part of the disclosed index shape);
`scrambled_id`s; log leaves and certificates; group IDs; key versions.

### 13.3 Rotation rule

**Any committed transaction in which at least one record leaves a key domain rotates that domain.** A
record leaves a domain when it is deleted from a group, deleted from the holding area, or moved out of
the holding area by a flush. For each domain `g` that loses records, the same transaction:

1. generates a new group key `GK_g'` (version + 1);
2. generates new bucket keys for every bucket that lost a record (version + 1);
3. re-wraps all 64 bucket keys of `g` under `GK_g'`;
4. re-wraps the surviving record keys of every rotated bucket under their new bucket keys;
5. re-encrypts `S ‖ r_agg` under `GK_g'` (not applicable to the holding area).

Records **joining** a domain (insert, spillover, being moved into a new group by a flush) never rotate
anything; they are wrapped under the destination's current keys. A newly spawned group starts with
fresh keys.

**Invariant this rule guarantees (INV-12).** For every domain, any ciphertext on disk that the
domain's *current* keys can decrypt was written after the domain's last departure. Therefore:
no departed record's key is reachable through its old domain, and no two decryptable accumulator
versions straddle a deletion. That second point matters: if two versions of a group's sum survived,
`S_pre − S_post` would equal the deleted vector exactly, and `r_agg_pre − r_agg_post` would equal the
deleted record's `r_t`.

### 13.4 Key erasure rule and the two-slot key file

**Key erasure rule (INV-13).** An old group key MAY be destroyed only after every live byte it protects
exists durably re-encrypted under the new key. In practice the transaction's WAL records carry all
re-wrapped material, and the old key is erased only after `COMMIT` is durable.

**Two slots per domain.** The key file (§14.7) holds two 512-byte slots per domain; each slot is
`(version, key, CRC)`. Rotation writes the new key into the *inactive* slot and `fsync`s it **before**
the WAL commit (phase A), and overwrites the old slot with zeros and `fsync`s it **after** the commit
(phase C).

**Recovery rule (INV-14).** After replaying the storage checkpoint and the WAL, for every domain with
active version `v`: the slot holding `v` MUST exist with a valid CRC (otherwise refuse to start: that
data can no longer be decrypted); every other slot for that domain is erased; slots that belong to no
domain are erased.

### 13.5 Why deleted data cannot be recovered

Let a transaction remove record `t` from domain `g`, moving `g` from key version `v` to `v+1`.

1. Everything that contains `t`'s data — its slot payload (vector, record ID, `r_t`) and its passage
   text — is encrypted under `RK_t`.
2. `RK_t` was only ever written wrapped under a bucket key of a domain `t` belonged to. Every such
   domain rotated when `t` left it, and `t`'s old bucket key was never re-wrapped under a newer group
   key (step 2 of §13.3 replaces it).
3. Every older group key of those domains was destroyed at earlier departures, and `GK_{g,v}` is
   destroyed in phase C. So `RK_t` is unrecoverable, and with it every ciphertext in (1).
4. Every accumulator version that contains `t` was encrypted under `GK_{g,≤v}`, which is destroyed.
   Every version under `GK_{g,v+1}` excludes `t`.
5. All plaintext copies in memory were zeroed before the deletion was acknowledged (§12.6).

What remains visible is exactly the plaintext list in §13.2. The forensic experiment (overview EX-2)
tests this argument on raw disk images.

### 13.6 Cost per deletion

At a spawned group with 5,703 members (a capacity example), one deletion rewrites 64 wrapped bucket
keys with versions (4,352 bytes), about 90 surviving record keys in the rotated bucket (5,400 bytes)
and the accumulator (3,132 bytes): **about 12.9 KB**, versus about 342 KB if every record key in the
group had to be re-wrapped under a two-level scheme (Appendix A).

---

## 14. On-disk formats

All structures carry a magic number, a `u16be` format version and a trailing CRC-32C unless stated.

**Sealer marker (overview DB-48).** Every file in `<data_dir>` also records the `u16be sealer_id` it
was written with, immediately after its format version: `0` for the plaintext sealer (no encryption;
build Parts 2 and 3) and `1` for AES-256-GCM-SIV as in §13.2 (Part 4 and the released system). A
build MUST refuse to open a file whose `sealer_id` differs from its own (`IntegrityViolation`, naming
the check). A database written with sealer `0` makes no confidentiality claim; INV-11 and §13.2 apply
only to sealer `1`. The key directory (§14.7) exists only with sealer `1`.

### 14.1 Directory layout

```
<data_dir>/
  ENGINE.lock                      exclusive process lock
  MANIFEST                         current storage checkpoint id + first WAL position needed (atomic rename)
  checkpoint/<id>/                 one directory per storage checkpoint (atomic rename into place)
    meta.bin                       engine format, config hash, counters, collection list
    collections.bin                per collection: id, d, artefact hash, parameters
    partitions/<collection>.svp    copy of each partition artefact (§6.3)
    groups.bin                     group headers (§14.3)
    buckets.bin                    wrapped bucket keys (§14.5)
    slots.bin                      member and holding slots (§14.4), page-structured
    locator.bin                    scrambled_id → (group, slot index)
  wal/<seq>.wal                    WAL segments (§14.6)
  log/leaves.store                 insert-leaf bytes (§14.8)
  log/hashes.store                 every leaf hash, in order
  log/checkpoints.store            every log checkpoint with its cosignatures
  certs/<seq>.store                certificates (§14.8)
  payloads/<seq>.store             encrypted passage text (§14.8)
<key_dir>/                         MAY be a different filesystem (§12.9)
  KEYS                             the key file (§14.7)
  SECRETS                          k_scramble and operator signing keys by epoch (mode 0600)
```

`SECRETS` is never erased; nothing in it protects deleted data.

### 14.2 Pages

16,384-byte pages: `u32be page_type ‖ u64be page_no ‖ u64be wal_seq ‖ payload ‖ u32be crc32c`. In v1
pages are written only inside storage checkpoint files.

### 14.3 Group header (per group, including the holding area)

| Field | Bytes | Plaintext? |
|---|---|---|
| `group_id`, zero-padded | 32 | yes |
| `kind` (0 frozen, 1 spawned, 2 holding) | 1 | yes |
| `seal_version` (the group key version, §13.3) | 8 | yes |
| `n` | 8 | yes |
| `C_S` | 32 | yes |
| centroid, `d × f64` | 3,072 | yes (all zero for the holding area) |
| `nonce ‖ AES-GCM-SIV(S as d × i64 ‖ r_agg) ‖ tag` | 12 + 3,104 + 16 = 3,132 | encrypted (absent for the holding area) |
| **Total** | **6,285** | |

**Extension and sealer fields (overview DB-46).** `C_S` is the group extension's public state and
`r_agg` its secret state (EP-1; the same split as the blob's extension region, §5.5 and DB-47). The
accumulator `S as d × i64 ‖ extension secret` is sealed by the storage sealer, which maintains
`seal_version`; under AES-GCM-SIV it is the group key version, the `group_key_version` of §13.2's
associated data. With no extension (build Parts 1–2) both extension fields are empty. With the
plaintext sealer (DB-48) the accumulator is stored without nonce and tag, and `seal_version` is 0. The
sizes in the table are those of the released system (commitment extension, AES-GCM-SIV); Appendix A
also lists the Part 2 sizes.

### 14.4 Slot (fixed size, identical for group members and holding-area records)

| Field | Bytes |
|---|---|
| `scrambled_id` | 64 |
| Wrapped record key: `nonce ‖ AES-GCM-SIV(RK_t) ‖ tag` | 12 + 32 + 16 = 60 |
| `nonce ‖ AES-GCM-SIV(payload) ‖ tag` | 12 + 1,835 + 16 = 1,863 |
| Padding to 8-byte alignment | 5 |
| **Total** | **1,992** |

Payload plaintext (1,835 bytes): `u16be id_len ‖ id padded with zeros to 256 bytes ‖ x̃ as d × i32be
‖ extension record secret`. The commitment extension's record secret is `u64be insert_leaf_index ‖ u8
has_rt ‖ r_t (32)`, 41 bytes (overview DB-46). With no extension (build Parts 1–2) the record secret
is empty and the payload is 1,794 bytes; with the plaintext sealer (§14 sealer marker) the wrapped
record key is empty and the payload is stored without nonce and tag.

- Padding IDs to 256 bytes keeps slots fixed-size and hides ID length.
- `has_rt` MUST be 1 in every slot: the engine stores `r_t` for every record (§9.4, DB-55 in the
  overview). A slot whose payload has `has_rt ≠ 1` is an `IntegrityViolation`. The byte is kept so that
  the layout and the sizes in Appendix A do not change. A flush moves the payload ciphertext unchanged;
  it does not re-encrypt it.
- Removing a member moves the **last** slot of the group into the vacated position (ciphertext is
  moved, not decrypted) and updates the moved record's locator entry in the same transaction.

### 14.5 Bucket block (per group)

64 entries of `u64be bucket_version ‖ wrapped bucket key (60)` = 4,352 bytes.

### 14.6 WAL record

`u32be len ‖ u8 type ‖ u64be wal_seq ‖ u64be txn_id ‖ payload ‖ u32be crc32c`.

| Type | Payload (after-image) |
|---|---|
| `BEGIN` | — |
| `GROUP_CREATE` | New group header, bucket block |
| `GROUP_HEADER` | Replacement group header (§14.3) |
| `BUCKET_BLOCK` | Replacement bucket block |
| `SLOT_PUT` | `group_id ‖ slot index ‖ slot (1,992)` |
| `SLOT_TRUNCATE` | `group_id ‖ new slot count` |
| `LOCATOR_PUT` / `LOCATOR_DEL` | `scrambled_id ‖ (group_id ‖ slot index)` / `scrambled_id` |
| `LOG_LEAF` | Leaf hash; for insert leaves also the 209-byte leaf |
| `LOG_CHECKPOINT` | Log checkpoint with cosignatures |
| `CERT_REF` | `database_lsn ‖ store segment ‖ offset ‖ length ‖ SHA-256` of the certificate |
| `PAYLOAD_REF` | `scrambled_id ‖ store segment ‖ offset ‖ length` |
| `COUNTERS` | `N`, `k`, next `database_lsn` per collection |
| `EXTENSION` | `u16be participant_id ‖ bytes`, carried for a transaction participant and never interpreted by the storage engine (overview DB-45) |
| `COMMIT` | — |

Append-store bytes (certificates, payloads, leaves) are written and `fsync`ed **before** the `COMMIT`
that references them. Unreferenced bytes after a crash are ignored and overwritten.

### 14.7 Key file (`KEYS`)

- Header, 4,096 bytes: `b"SVDBKEYS" ‖ u16be version ‖ u32be slot_pairs ‖ zero padding ‖ u32be crc32c`.
- Per domain, two 512-byte slots. Each slot: `u32be magic ‖ u64be domain_index ‖ u64be key_version ‖
  32-byte key ‖ zero padding ‖ u32be crc32c`.
- 512-byte alignment keeps a slot inside one sector; a torn slot fails its CRC and is treated as absent.
- Domain indices are allocated in creation order (a declared visible layout, L-5).
- Size: 4 KB plus 1 KB per domain.

### 14.8 Append stores

Records: `u64be key ‖ u32be len ‖ bytes ‖ u32be crc32c` (the key is `database_lsn`, leaf index, or a
sequence number). Certificates and insert leaves are public; payload records are AES-GCM-SIV
ciphertexts under the record key, so erasing the record key erases the text wherever it lies.

---

## 15. Operation protocols and crash behaviour

### 15.1 Insert

1. Validate: collection exists; §4.1 normalisation; §3.2 record-ID rules; the ID is not live.
2. Quantise (§4.2). Recompute `C_t` from `x̃` and `r_t`; it MUST equal the supplied `C_t`. Verify the
   user signature over `DST_INSERT ‖ collection_id ‖ C_t`.
3. Route (§7.3). For a frozen or spawned destination, check the hard cap (§5.6).
4. Generate `RK_t`; encrypt the payload (with `r_t`, `has_rt = 1`) and the passage text;
   wrap `RK_t` under the destination bucket key.
5. For a group destination: decrypt `S ‖ r_agg`, add `x̃` and `r_t`, re-encrypt (fresh nonce, same
   key); `n += 1`; `C_S += C_t`; `N += 1`.
6. Build the insert leaf; if the tree reaches a multiple of 10,000, build a log checkpoint and collect
   cosignatures.
7. If the holding area now has 200 records, perform the flush (§15.2) **in the same transaction**.
8. Write append-store bytes and `fsync`; write the WAL transaction; `COMMIT`; `fsync`.
9. Apply to memory; update the mirror; zero `r_t` and temporaries; return
   `(database_lsn, placement)`.

A crash before the `COMMIT` is durable leaves the database unchanged; the application backend retries
and the retry is a normal insert. A crash after it leaves the insert done; a retry fails with
`DuplicateRecord { same_commitment: true }`, which the SDK treats as success.

### 15.2 Flush (inside the triggering insert's transaction)

1. Sort the 200 holding records by record ID; compute the spawn ID (§7.5).
2. Create the group: fresh group key (phase A write) and 64 bucket keys.
3. For each record: decrypt the payload; add `x̃` and `r_t` into the new group's `S` and `r_agg`;
   keep the payload ciphertext unchanged (`has_rt` stays 1, §14.4); re-wrap `RK_t` under the new
   group's bucket key.
4. `n = 200`; `C_S = r_agg·H + Σ scalar(S_i)·G_i`; centroid from §7.5; `N += 200`; `k += 1`.
5. Rotate the holding area (§13.3): new holding group key written in phase A, and all its bucket keys.
6. After `COMMIT`, erase the old holding group key (phase C).

### 15.3 Delete (one record)

1. Look up `scrambled_id`. If absent, return `AlreadyAbsent` and touch nothing.
2. Decrypt the record key and slot. Recompute `C_t` from the stored `x̃` and the stored `r_t`; it MUST
   equal the `C_t` in the record's insert leaf. Otherwise the stored state is corrupt: raise
   `IntegrityViolation` and touch nothing. This is an integrity check, not an authorisation check.
3. If the record's insert leaf is not covered by a witnessed log checkpoint, create one first
   (§10.3), as its own committed transaction.
4. Compute the post-state (§5.3). For a group deletion, compute `ctx` and the proof (§9.5). Build the
   certificate with `database_lsn` = the next leaf index, and sign it.
5. **Phase A.** Write the domain's new group key into its inactive key-file slot; `fsync`.
6. **Phase B.** One WAL transaction: slot move and truncate, locator updates, new group header
   (accumulator re-encrypted under the new key), new bucket block, re-wrapped surviving record keys,
   the delete leaf, the certificate reference, counters; then `COMMIT` and `fsync`. **This is the
   commit point.**
7. Apply to memory under the exclusive lock; remove the mirror entry; zero the old keys, the decrypted
   vector, `r_t`, the old accumulator and the record ID.
8. **Phase C.** Overwrite the old key slot with zeros; `fsync`.
9. Acknowledge with the certificate (§15.8).

The engine performs no authorisation. The application backend authenticates the account before it
calls `delete` or `delete_user` (§3.3; overview L-27).

`delete_user(list)` does steps 1–4 for every record in list order. Each certificate is built on the
state left by the previous one, so consecutive certificates chain. Phase A writes one new key per
affected domain, phase B commits one transaction, and phase C erases one old key per affected domain.

### 15.4 Crash table (delete)

| Crash point | State after recovery | Old group key | What the application backend sees and does |
|---|---|---|---|
| Before phase A | Unchanged | Present | Error or timeout; retrying is safe |
| After phase A, before `COMMIT` is durable | Unchanged; the new slot is an orphan (version ≠ active) | Present | Recovery erases the orphan; retrying is safe |
| After `COMMIT`, before phase C | Deleted | Present in its slot | Recovery erases it (version ≠ active); a retry returns `AlreadyAbsent` |
| During phase C (torn slot) | Deleted | CRC fails, so treated as absent and erased again | Same |
| After phase C, before acknowledgement | Deleted | Gone | A retry returns `AlreadyAbsent`; the certificate is retrievable by `database_lsn` |

### 15.5 Search

Take the shared lock and run §8.1. Never write.

### 15.6 Storage checkpoint

1. Serialise the in-memory ciphertext state into `checkpoint/<new>.tmp/`; `fsync` every file.
2. Rename it to `checkpoint/<new>/`; `fsync` `checkpoint/`.
3. Write `MANIFEST.tmp` naming the new storage checkpoint and the first WAL position still needed; `fsync`;
   rename to `MANIFEST`; `fsync` the directory.
4. Delete older storage checkpoints and covered WAL segments. Their bytes remain in free space as
   ciphertext under keys that are either current (covering only live data) or destroyed (§13.3).

### 15.7 Recovery (every startup)

1. Take `ENGINE.lock`. Run the platform checks (§12.9) and the memory hygiene setup (§12.8).
2. Re-derive and check the generators (§9.2); refuse on mismatch.
3. Read `MANIFEST`; load the storage checkpoint; replay every WAL transaction with a valid `COMMIT`;
   discard the rest.
4. Apply the key-file recovery rule (§13.4).
5. Decrypt into memory; rebuild the mirror, locator, counters and log tree.
6. **Full invariant check** (§21), including, for every group: `n` equals the slot count;
   `S = Σ x̃` over members; `C_S = r_agg·H + Σ scalar(S_i)·G_i`; every locator entry points at a slot
   with the same `scrambled_id`; the log root equals the latest log checkpoint's root at that size.
   Refuse to serve on any violation.
7. Serve.

### 15.8 Acknowledgement semantics

A deletion returns success only when all of these hold: its transaction is durable; the domain's new
group key is durable and the old key's slot has been overwritten and `fsync`ed; and memory no longer
contains the record, its keys or the old accumulator. An insert returns success when it is durable and
applied.

### 15.9 Drop collection

Erase every group key of the collection from the key file (overwrite and `fsync`), commit a WAL record
removing the collection, then delete its files. Dropping a collection is a cryptographic erase of all
its data.

---

## 16. API

### 16.1 Engine (Rust, C-12)

```rust
Engine::open(config: &EngineConfig) -> Result<Engine>
engine.create_collection(artefact: &Path, opts: CollectionOptions) -> Result<CollectionId>
engine.drop_collection(cid: CollectionId) -> Result<()>

engine.insert(cid, InsertRequest {
    record_id: String,            // §3.2
    vector: Vec<f32>,             // d values, normalised
    r_t: [u8; 32],                // blinding scalar drawn by the application backend; stored (§9.4)
    c_t: [u8; 32],                // commitment built by the application backend (checked)
    user_public_key: [u8; 32],
    user_signature: [u8; 64],     // over DST_INSERT ‖ collection_id ‖ C_t
    passage: Option<Vec<u8>>,
}) -> Result<InsertReceipt { database_lsn: u64, placement: Frozen | Spawned | Holding }>

engine.delete(cid, DeleteRequest { record_id: String })   // no r_t: the engine uses the stored one
    -> Result<DeleteOutcome { AlreadyAbsent | Deleted { database_lsn: u64, certificate: Vec<u8> } }>
engine.delete_user(cid, Vec<DeleteRequest>) -> Result<Vec<DeleteOutcome>>   // one transaction

engine.search(cid, query: &[f32], k: usize) -> Result<Vec<Hit { record_id: String, score: f32 }>>

engine.certificate(database_lsn: u64) -> Result<Vec<u8>>
engine.latest_log_checkpoint() -> Result<LogCheckpoint>
engine.inclusion_proof(leaf_index: u64, tree_size: u64) -> Result<Vec<[u8; 32]>>
engine.consistency_proof(old_size: u64, new_size: u64) -> Result<Vec<[u8; 32]>>
engine.storage_checkpoint_now() -> Result<()>
engine.stats(cid) -> Result<Stats>          // group counts, sizes, N, k, memory, disk

#[cfg(feature = "test-hooks")]  // never compiled into release or experiment builds that measure erasure
engine.group_snapshot(cid, group_id) -> Result<GroupSnapshot>   // S, n, C_S, r_agg, members, canonical blob
```

### 16.2 Application-backend SDK (Python, C-13)

The SDK runs on the application backend (§3.3), never on the user's device.

```python
from sever_db import Engine, UserKey, prepare_insert

# Every call below follows the backend's own authentication of the account.
user = UserKey.generate()                              # Ed25519, once per account; the backend keeps
                                                       # it in its own key store; it never rotates
vector = encoder.encode(text)                          # the encoder named in the partition artefact (§6.3)
req = prepare_insert(collection_id, record_id, vector, user)
# prepare_insert quantises (§4.2), draws r_t (§9.4), computes C_t, signs.
# r_t travels inside `req`; the engine stores it (§9.4). The caller has nothing to keep.

receipt = engine.insert(collection_id, req)
outcome = engine.delete(collection_id, record_id)      # no r_t argument
hits    = engine.search(collection_id, encoder.encode(query_text), k=10)
```

`encoder` stands for the backend's embedding model; it is not part of the SDK.

The SDK exposes no way to pass a random generator, seed or nonce into proof generation
(`SeededNonceForbidden`).

### 16.3 Command-line tools

| Tool | Component | Purpose |
|---|---|---|
| `sever-partition build` | C-15 | Build a partition artefact (§6) |
| `sever-verify <certificate>` | C-16 | Verify a certificate with bundled anchors (§11.3) |
| `sever-audit <data_dir or log export>` | C-17 | Check deletion leaves, certificate chains and log consistency |
| `sever-scan <disk image>` | test tool | Forensic scan used by EX-2 |

---

## 17. Errors

Every error is typed. **No error message may contain a record ID, a vector value, a key, `r_t` or
passage text.** Group sizes MAY appear (they are already visible).

| Error | Raised when |
|---|---|
| `WrongDimension`, `NonFinite`, `NotNormalised` | §4.1 fails |
| `InvalidRecordId` | §3.2 rules 1–2 fail |
| `DuplicateRecord { same_commitment }` | §3.2 rule 3 fails; `same_commitment` says whether the live record has the supplied `C_t` (a retried insert) |
| `CommitmentMismatch` | Supplied `C_t` ≠ recomputed `C_t` at insert |
| `BadUserSignature` | Insert signature fails |
| `GroupCapacityExceeded` | Hard cap (§5.6) |
| `UnknownCollection` | No such collection |
| `SeededNonceForbidden` | Any attempt to supply randomness to proof generation |
| `PlatformUnsafe` | A §12.8 or §12.9 check fails |
| `IntegrityViolation` | Any invariant (§21) fails, or the delete-time `C_t` check (§15.3 step 2) fails; the engine stops serving |
| `DurabilityFailure` | `fsync` failed; the process aborts |

---

## 18. Configuration files

Changing any value invalidates any run in progress. Every run ledger entry records the SHA-256 of each
file. Experiment settings are in `configs/experiments.yaml` (overview §12).

### 18.1 `configs/engine.yaml`

```yaml
format_version: "db-1.0"

engine:
  mode: embedded
  single_writer: true
  page_size_bytes: 16384
  max_record_id_bytes: 256
  vector_storage: i32                     # |x̃| ≤ 2^24 + 16
  store_passage_text: true                # per collection; always encrypted when stored

arithmetic:
  dimension: 384
  fractional_bits: 24
  rounding: round_half_to_even
  normalisation_tolerance_float32_ulps: 8
  accumulator: i64
  max_vectors_per_group: 1000000          # hard cap; the 44-bit bound depends on it
  max_accumulator_bits: 44

partition:
  artefact_required: true                 # engine never fits; §6
  frozen_groups: 128
  drift_test: mahalanobis_pooled_ledoit_wolf
  drift_threshold: from_artefact          # P99 over the reference set
  ood_rule: strictly_greater_than_tau

spawning:
  target_size: 200                        # holding area flushes at exactly this size
  flush_forms_exactly_one_group: true
  spillover_before_holding: true
  capacity_multiplier: 1.5                # room iff 2·k·n < 3·N
  spawned_groups_frozen: true
  spawned_groups_can_spawn: false
  holding_searchable: false
  holding_deletable: true                 # never queued

search:
  index: ivf_flat
  coverage_fraction: 0.25
  probe_count_rounding: ceil
  include_empty_groups: true
  group_rank_tiebreak: group_id_bytes_ascending
  result_tiebreak: record_id_bytes_ascending
  kernel: pinned_8_lane_no_fma            # §8.2
  simd: avx2_runtime_detected_with_scalar_fallback

durability:
  fsync_on_commit: true
  fsync_failure: abort_process
  storage_checkpoint_every_wal_bytes: 1073741824
  storage_checkpoint_on_clean_shutdown: true
  wal_segment_bytes: 67108864
  mmap_writes: false

keys:
  hierarchy: group > bucket > record
  buckets_per_group: 64
  bucket_of_record: "scrambled_id[0] mod 64"
  rotate_on: departure                    # deletion or flush-out of any record from a domain
  key_file_slot_bytes: 512
  slots_per_domain: 2
  erase_method: overwrite_zeros_then_fsync
  aead: aes-256-gcm-siv
  nonce: random_96_bit_os_csprng
  associated_data: per_ciphertext_type    # §13.2

memory:
  zeroize_secrets: true
  mlock_key_material: true
  disable_core_dumps: true
  require_no_unencrypted_swap: true
  require_no_hibernation: true
  allow_unsafe_memory: false              # development only; recorded in the run ledger
  max_resident_fraction_of_ram: 0.6       # refuse to start above this estimated budget

platform:
  os: linux-x86_64
  data_fs_allowed: [ext4, xfs]
  key_fs_forbidden: [zfs, btrfs_without_nocow]

crypto:
  curve: ristretto255
  generator_dst: "PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS"
  generator_self_check: refuse_to_start_on_mismatch
  commitment_integer_mapping: two_complement_mod_l   # §4.5
  proof: okamoto_camenisch_stadler_full_representation
  proof_domain: "SEVERDB_POSK_V1"
  proof_challenge: "sha512(DST_POSK || C_S_post || A || ctx) reduced wide"
  proof_context: [C_S_pre, C_t, scrambled_id, database_lsn, collection_id]
  proof_nonces: merlin_hedged_witness_and_os_entropy
  signatures: ed25519_verify_strict
  record_id_scrambling: hmac_sha512
  k_scramble_rotates: false
  operator_key_epoch_days: 90
  witness_key_epoch_days: 90
  user_keys_rotate: false

log:
  structure: rfc9162_merkle_tree
  hash: sha256
  ordering: append_position
  checkpoint_every_leaves: 10000
  checkpoint_on_demand_for_deletion: true
  witness_count: 5
  witness_threshold: 4
  witnesses_verify_consistency: true
  commit_with_state_change: true          # certificate, leaf and state commit atomically

certificates:
  encoding: deterministic_tlv
  fields: 13
  operator_signature: required
  retention: all                          # v1 keeps every certificate
```

### 18.2 `configs/partition.yaml`

```yaml
format_version: "part-1.0"
encoder: sentence-transformers/all-MiniLM-L6-v2   # revision pinned by commit hash in P0
dimension: 384
reference_dataset: allenai/sciq                   # revision pinned in P0
reference_text: support_else_question             # overview §10.1
frozen_groups: 128
kmeans:
  init: k-means++
  n_init: 10
  max_iter: 300
  tol: 1.0e-4
  algorithm: lloyd
  seed: derived_from_run_seed                     # overview §10.6
fit_on: dequantised_q24
covariance: ledoit_wolf_pooled_single_fit
assume_centered: false
precision: cholesky_inverse_f64
threshold_percentile: 99
percentile_method: linear
independent_oracle_tolerance:
  shrinkage: 1.0e-12
  threshold: 1.0e-9
```

---

## 19. Components and code layout

### 19.1 Components

Each component announces **what it is, why it exists, its goals, what it depends on and what proves
it**. A component is done only when its must-fail tests exist and fail against a deliberately broken
build.

| ID | Component | What | Why | Goals | Depends on | Proven by |
|---|---|---|---|---|---|---|
| C-1 | Storage I/O (`sever-vfs`) | `Vfs` trait; `PosixVfs`; seeded fault-injecting `SimVfs` | Deterministic crash testing | All I/O goes through it; `SimVfs` models POSIX durability conservatively | — | Contract tests: unsynced writes lost; un-`fsync_dir`ed renames may be lost |
| C-2 | Formats (`sever-format`) | Byte-exact encoders and parsers (§14, §11.1, §6.3) | Byte-equality claims need byte-level definitions | Magic, version and CRC everywhere; strict parsers | — | Round-trip property tests; every single-bit flip detected; fuzzing |
| C-3 | WAL | Segments, transactions, replay | Durability and multi-group atomicity | Ciphertext-only after-images; torn tails discarded | C-1, C-2 | Crash at every byte of sampled records; plaintext scan of all WAL bytes |
| C-4 | Storage checkpointer | Atomic full images | Bounded recovery and WAL size | Interrupted checkpoint leaves the previous valid | C-1, C-2 | Crash at every step; image + replay equals pre-crash state |
| C-5 | Transaction manager | Writer mutex, reader lock, commit protocol | Serializable isolation with no retained snapshots | §15 protocols exactly | C-3, C-4, C-6 | Deterministic interleaving tests |
| C-6 | Key manager | Three-level keys, rotation, two-slot key file, recovery rule | Physical erasure | Only group keys need erasure; about 12.9 KB rewritten per deletion | C-1, C-7 | Crash at every rotation step; forensic scans; sabotage |
| C-7 | Crypto (`sever-crypto`) | Generators, commitments, proof, hedged nonces, HMAC, Ed25519 and AEAD wrappers, quantiser | One audited place for every primitive | RFC KATs pass; golden vectors frozen | pinned crates (§20) | RFC 9496, RFC 8452, RFC 8032 vectors; golden files; must-fail order swaps |
| C-8 | Routing | §7.1–7.3 | Faithful drift handling | Pure function; pinned float order | C-7, C-15 artefact | Purity tests (§7.7); differential against C-18 |
| C-9 | Index core | Groups, slots, accumulators, holding area, flush, capacity, locator | The exact-deletion index | Every §5 and §7 rule | C-5, C-6, C-7, C-8 | Equivalence helper with sabotage suite; differential against C-18 |
| C-10 | Search | §8 | Answer queries; results must match C-18 | Pinned kernel; scalar = AVX2 | C-9 | Kernel equality; differential; brute-force recall harness |
| C-11 | Log and certificates | RFC 9162 tree, leaves, log checkpoints, simulated witnesses, certificate builder | Public receipts committed atomically | §10, §11 | C-5, C-7 | C-16 accepts every honest certificate and rejects every attack |
| C-12 | Engine API | §16.1 | One stable surface | Typed errors, no leakage | all above | API contract and leakage tests |
| C-13 | Python SDK (`sever-py`, PyO3) | Bindings and the application-backend helpers of §16.2 | Experiments and application backends are in Python | No engine secret crosses into Python; `r_t` exists in Python only inside a `prepare_insert` request on its way to the engine | C-12 | SDK runs the differential and experiment suites |
| C-14 | Server (optional) | gRPC front end with TLS | Multi-client use | Adds nothing the library does not guarantee | C-12 | Same suites over the network |
| C-15 | Partition builder (Python) | §6.2 | The engine never fits models | Independent Ledoit–Wolf oracle agreement | numpy, scikit-learn | Oracle agreement; artefact hash stability across reruns |
| C-16 | Verifier (separate Rust workspace) | §11.3 | Anyone can check a certificate | Shares no code with C-1…C-15; own generator derivation; same `curve25519-dalek` version | pinned crates only | Golden vectors; attack suite |
| C-17 | Auditor (`sever-audit`) | Log consistency, deletion leaves, certificate chains | What a certificate alone cannot prove | Detects a skipped deletion leaf or a broken chain | C-16 code copied, not shared | Tests with a deliberately skipped leaf |
| C-18 | Reference model (Python) | A slow, in-memory, obviously correct implementation of §3–§8 and §11's arithmetic, written from this document | The primary oracle for differential tests | Byte-identical canonical blobs and search results | C-7 via Python binding, C-15 | Its own unit tests; review against this document |
| C-19 | Experiment harness | Runs experiments, writes the run ledger | Reproducible, logged results | A run that cannot write its ledger entry does not start | C-13, C-18 | Ledger completeness checks |

### 19.2 Repository layout

The crate and package map follows the build plan (Build §3.2), one crate per responsibility, grouped
by the part that adds it (DB-56).

```
sever-db/
  Cargo.toml                     workspace: crates/*
  rust-toolchain.toml            channel = "1.98.1"
  deny.toml                      licence and advisory policy
  crates/
    Part 1  sever-types/  sever-quant/  sever-partition/  sever-index/  sever-search/
            sever-tracekit/  sever-p1/ (composition root, sever-demo CLI)
    Part 2  sever-vfs/  sever-format/  sever-wal/  sever-appendstore/  sever-checkpoint/
            sever-txn/  sever-engine/  sever-crashkit/  sever-py-p2/  sever-p2/
    Part 3  sever-crypto/  sever-commit/  sever-log/  sever-cert/  sever-py-p3/  sever-p3/
    Part 4  sever-keys/  sever-seal/  sever-erasure/  sever-platform/  sever-scan/  sever-py/
            sever-db/ (final composition root)
  verifier/                      separate workspace, own Cargo.lock, no path dependencies on crates/
  audit/                         separate workspace
  python/
    sever_partition/             C-15
    sever_refmodel_core/  sever_refmodel_durable/  sever_refmodel_certs/
                                 C-18, one package per part
    sever_testkit/               synthetic data, dataset slices, seeds, trace writing
    sever_demo/                  renders the sever-demo output (Build §4.4)
    sever_db_p2/  sever_db_p3/  sever_db/
                                 SDK modules (C-13)
    sever_experiments/  sever_report/
                                 C-19
  configs/                       engine.yaml, partition.yaml, experiments.yaml
  golden/                        generator vectors, proof challenge vectors, RFC KATs
  datasets/MANIFEST.sha256       data files are regenerated, not committed
  tests/                         crash/, forensic/, differential/, attack/, property/
  docs/                          these two documents, RUN_LEDGER.md, SOUNDNESS.md
  demo/                          the review prototype (Python, 5 Oct 2026): own environment, tests
                                 and container; not part of any part; nothing above depends on it
```

The optional server (C-14) has no crate in the build plan; it is added, if ever, after Part 4.

---

## 20. Toolchain and dependencies (checked 27 Sep 2026)

### 20.1 Rust

| Item | Value | Note |
|---|---|---|
| Toolchain | **1.98.1** (stable at the check; 1.99 is due 1 Oct 2026) | Pinned in `rust-toolchain.toml` |
| Edition | **2024** | Needs Rust ≥ 1.85 |
| Workspace MSRV | **1.85** | The highest crate MSRV: `zeroize 1.9.0` (1.85); CI also builds with 1.85 |

| Crate | Pinned | Newest available | Why this version | MSRV |
|---|---|---|---|---|
| `curve25519-dalek` | **4.1.3** | 5.0.0 (6 Jul 2026) | 5.0 moves to `rand_core 0.10` / `digest 0.11`; `merlin` has no release beyond 3.0.0 and stays on `rand_core 0.6`. One consistent family (DB-3) | 1.60 |
| `ed25519-dalek` | **2.2.0** | 3.0.0 (pairs with dalek 5) | Same family as dalek 4.1 | 1.81 |
| `merlin` | **3.0.0** | 3.0.0 | Only release line; depends on `rand_core ^0.6`, `keccak ^0.1`, `zeroize ^1` | — |
| `aes-gcm-siv` | **0.11.1** | 0.12.1 (21 Aug 2026) | 0.11 uses `aead 0.5`, same `rand_core 0.6` family | 1.56 |
| `sha2` | **0.10.9** | 0.11.0 | `digest 0.10` family, as dalek 4.1 (`digest ^0.10`) | — |
| `hmac` | **0.12.1** | 0.13.0 | `digest 0.10` family | — |
| `zeroize` | **1.9.0** | 1.9.0 | Works with both families (`^1`) | 1.85 |
| `crc32c` | **0.6.8** | 0.6.8 | Hardware CRC-32C | — |
| `pyo3` | **0.29.2** | 0.29.2 (5 Aug 2026) | SDK bindings | 1.83 |
| `rand_core` | 0.6.4 (with `getrandom`) | — | Pulled by dalek 4.1 (`^0.6.4`); source of `OsRng` | — |
| `proptest`, `criterion`, `cargo-fuzz`, `cargo-deny` | frozen by `Cargo.lock` in P0 | — | Tooling | — |

### 20.2 Python

| Package | Line to pin | Newest at the check | Note |
|---|---|---|---|
| Python | **3.13.x** | — | `numpy 2.5` requires ≥ 3.12 |
| `numpy` | 2.5.x | 2.5.3 | |
| `scikit-learn` | 1.9.x | 1.9.1 | k-means and Ledoit–Wolf (checked against the independent oracle, §6.2) |
| `sentence-transformers` | 6.1.x | 6.1.0 | Encoder runtime |
| `torch` (CPU build) | 2.14.x | 2.14.0 | Encoder backend |
| `datasets` | 5.0.x | 5.0.1 | Downloads SciQ and BEIR NQ |
| `pyarrow` | 25.0.x | 25.0.1 | Parquet |
| `maturin` | 1.15.x | 1.15.0 | Builds the PyO3 wheel |
| `faiss-cpu` | 1.15.x | 1.15.1 | Baselines only (overview §10.7); never used by the engine |

Exact versions and hashes are frozen in a hash-pinned lockfile in P0. **Embedding bytes are pinned by
SHA-256 in `datasets/MANIFEST.sha256`**: any library upgrade that changes a single embedding byte
invalidates runs that used the old bytes.

### 20.3 Compatibility checks (P0, then every CI run)

1. `cargo tree -d` shows no duplicate major versions of `rand_core`, `digest`, `getrandom` or
   `curve25519-dalek`.
2. `cargo tree -i curve25519-dalek` shows only 4.1.3, in both the main workspace and `verifier/`.
3. RFC 9496 (ristretto255 and `from_uniform_bytes`), RFC 9380 (`expand_message_xmd`), RFC 8452
   (AES-GCM-SIV) and RFC 8032 (Ed25519) test vectors pass.
4. The generator golden file matches in both the engine and the verifier.
5. `cargo deny check licenses advisories` passes.
6. `cargo build` succeeds with Rust 1.85 and with the pinned 1.98.1.
7. The Python lockfile resolves on Python 3.13 with every package above, and the encoder reproduces
   the manifest's embedding hashes.

### 20.4 Hardware and operating system

| Item | Value | Consequence |
|---|---|---|
| CPU | Intel Core Ultra 5 226V (Core Ultra 200V series) | AVX2, AES-NI, PCLMULQDQ and SHA extensions are available; there is no AVX-512, so there is no AVX-512 code path |
| RAM | 16 GB, not upgradeable | 10^6 vectors need about 3.8 GB resident; the startup budget refuses more than 60 % of RAM |
| Disk | Laptop SSD | Key-file overwrite is not guaranteed on flash (overview L-1); crash campaigns run in memory on `SimVfs` |
| OS | Native Linux, ext4 or XFS; swap off or encrypted; hibernation off | WSL2 or a VM is for development only; experiments run on native Linux |
| Forensics | `fuse2fs` (e2fsprogs) mounts ext4 images without root | Used by EX-2 |

---

## 21. Invariants checklist

"Startup" means the §15.7 full check; "commit" means checked before `COMMIT` in every build; "debug"
means checked after every operation in debug and test builds.

| ID | Invariant | Checked |
|---|---|---|
| INV-1 | Every stored `x̃` came through §4.1–4.2 | Insert path (no bypass) |
| INV-2 | `S`, `n`, `r_agg`, `C_S` change together in one transaction | Commit |
| INV-3 | `C_S = r_agg·H + Σ scalar(S_i)·G_i` for every group | Startup, debug |
| INV-4 | `n ≤ 1,000,000` for every group | Insert |
| INV-5 | `⌊1.5·N/k⌋ ≤ 1,000,000` | Startup |
| INV-6 | `n` equals the slot count and `S = Σ x̃` over members | Startup, debug |
| INV-7 | The locator and the slots are in exact one-to-one correspondence | Startup, commit (touched entries) |
| INV-8 | `N = Σ n` over frozen and spawned groups; `k` equals their count | Startup, commit |
| INV-9 | No acknowledged-deleted record is reachable by search, locator or mirror | Debug, tests |
| INV-10 | Generators equal the golden file | Startup |
| INV-11 | The WAL contains no forbidden plaintext (§12.3) | Tests (scanner), debug assertion on record builders |
| INV-12 | Rotation invariant (§13.3) | Tests, forensic scans |
| INV-13 | Key-erasure rule (§13.4) | Protocol order; crash tests |
| INV-14 | Key-file slot versions match active versions | Startup |
| INV-15 | The log root at every log-checkpoint size equals that checkpoint's root; every live record's insert leaf exists | Startup |
| INV-16 | Routing is a pure function of `(x̃, state)` | Tests (§7.7) |

---

## Appendix A — derived sizes and bounds

All at `d = 384`, recomputed by script on 27 Sep 2026.

| Quantity | Formula | Value |
|---|---|---|
| Largest absolute value of `x̃_i` | `2^24 + 16` (tolerance included) | 16,777,232 (< 2^31 − 1) |
| Largest absolute value of `S_i` at 10^6 members | `10^6 × 16,777,232` | 1.678 × 10^13 < 2^44 (19 bits spare in `i64`) |
| Sum bits at 10^7 members | `⌈log₂(10^7) + 24⌉` | 48 |
| Normalisation tolerance | `8 × 2^−23` | 9.54 × 10^−7 |
| Proof challenge preimage | 15 + 32 + 32 + 152 | 231 bytes |
| Proof size | 32 + 32 + 384 × 32 | 12,352 bytes |
| Hedged nonce output | 385 × 64 | 24,640 bytes |
| User insert-signature message | 17 + 16 + 32 | 65 bytes |
| Insert leaf | 1 + 16 + 64 + 32 + 32 + 64 | 209 bytes |
| Certificate, group deletion | 13 TLV fields + signature, 21-hash path | ≈ 14,093 bytes |
| Certificates at 900,000 deletions | 14,093 × 900,000 | ≈ 12.7 GB |
| Slot payload plaintext | 2 + 256 + 384 × 4 + 41 (DB-46) | 1,835 bytes |
| Slot | 64 + 60 + 1,863 → 8-aligned | **1,992 bytes** |
| Slots at 10^6 | 1,992 × 10^6 | 1.99 GB |
| Search mirror at 10^6 | 10^6 × 384 × 4 | 1.54 GB |
| Log tree levels at 1.9 × 10^6 leaves | ≈ 2 × leaves × 32 | ≈ 0.12 GB |
| Resident estimate at 10^6 | slots + mirror + log tree + locator and IDs | **≈ 3.8 GB** |
| Accumulator plaintext / ciphertext | 384 × 8 + 32 / + 28 | 3,104 / 3,132 bytes |
| Group header | §14.3 | 6,285 bytes |
| Part 2 slot payload (no extension) | 2 + 256 + 384 × 4 | 1,794 bytes |
| Part 2 slot (no extension, plaintext sealer) | 64 + 0 + 1,794 → 8-aligned | 1,864 bytes |
| Part 2 group header (no extension, plaintext sealer) | 32 + 1 + 8 + 8 + 0 + 3,072 + 384 × 8 | 6,193 bytes |
| Bucket block | 64 × (8 + 60) | 4,352 bytes |
| Deletion rewrite, three-level, full bucket | 4,352 + ⌈5,703/64⌉ × 60 + 3,132 | ≈ 12.9 KB |
| Deletion rewrite, two-level | 5,703 × 60 | 342,180 bytes |
| Probe count at 128 groups | ⌈0.25 × 128⌉ | 32 |
| Probe count at 263 groups | ⌈0.25 × 263⌉ | 66 |
| Key file | 4,096 + 1,024 per domain | 4 KB + 1 KB per group |
| Witness threshold | smallest t > 2·5/3 | 4 |

(5,703 is `1.5 × 10^6 / 263`, an illustrative capacity; the real value depends on each run's `N` and
`k`.)

---

## Appendix B — golden vectors

Each is generated by the build part that owns it (overview DB-44; Build 3-4 §3.4), once, committed under `golden/`, and checked by both the engine and the verifier
with independent code. A golden vector detects *drift* (a library bump, an edit, a corrupted build);
correctness of the underlying primitives rests on the third-party RFC test vectors.

1. `H`, `G_0`, `G_383` encodings (§9.2). Optional cross-check: they MUST equal the earlier SEVER
   prototype's values, because the DST is the same.
2. `gdigest = SHA-512(H ‖ G_0 ‖ … ‖ G_383)`.
3. A fixed `(C_S_post, A, ctx)` and its challenge scalar `c`; plus a must-fail test that swapping `A`
   and `C_S_post` changes `c`.
4. `scalar(v)` for `v ∈ {0, 1, −1, 2^44, −2^44}`.
5. Quantisation of hand-picked half-step inputs (ties to even).
6. A complete honest certificate (group deletion) and one holding-area certificate, with all
   intermediate values.
7. A spawn ID for a fixed 200-ID cohort.
8. A canonical group blob for a fixed three-member group, in the core form (`SEVERC`, Part 1) and the
   full form (`SEVERG`, Part 3) (§5.5).
9. RFC 9162 inclusion and consistency proofs for a fixed 7-leaf tree.

