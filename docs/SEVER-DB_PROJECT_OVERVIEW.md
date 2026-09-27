# SEVER-DB — Project Overview

**A vector database built from scratch, in which deletion is exact, provable and physical.**

| | |
|---|---|
| **Document** | SEVER-DB project overview, version 1.0 |
| **Date** | 27 September 2026 |
| **Companion** | `SEVER-DB_SPECIFICATION.md`: the normative software and index specification (every algorithm, byte format, protocol and setting) |
| **Status** | Plan of record for a new, independent project. Nothing is built yet |
| **Team** | One person |
| **Hardware** | Intel Core Ultra 5 226V laptop, 16 GB RAM (not upgradeable), SSD, native Linux |
| **Deliverables** | The SEVER-DB engine, SDK, partition builder, verifier and auditor; an evaluation; one research paper |

Together, these two documents are self-contained. Nothing else is needed to understand, build or
evaluate SEVER-DB.

---

## Contents

0. [How to read this document](#0-how-to-read-this-document)
1. [Announcement](#1-announcement)
2. [Background: the problem, prior evidence and related work](#2-background-the-problem-prior-evidence-and-related-work)
3. [Research questions, claims, non-claims and pre-registered targets](#3-research-questions-claims-non-claims-and-pre-registered-targets)
4. [Threat model](#4-threat-model)
5. [The design in plain words](#5-the-design-in-plain-words)
6. [Decision register (DB-1 … DB-43)](#6-decision-register-db-1--db-43)
7. [Components at a glance](#7-components-at-a-glance)
8. [Phases P0–P9](#8-phases-p0p9)
9. [Testing strategy](#9-testing-strategy)
10. [Datasets and experimental setup](#10-datasets-and-experimental-setup)
11. [Evaluation plan](#11-evaluation-plan)
12. [Experiment configuration](#12-experiment-configuration)
13. [Engineering practice](#13-engineering-practice)
14. [Known limits](#14-known-limits)
15. [Risks](#15-risks)
16. [Timeline](#16-timeline)
17. [Open items](#17-open-items)
18. [Recommendations](#18-recommendations)
19. [Glossary](#19-glossary)
20. [References](#20-references)

---

## 0. How to read this document

- **Sections 1–5** say what SEVER-DB is, why it exists, what it will and will not claim, and how it
  works, in plain words.
- **Section 6** records every design decision, with the options weighed and the reason for the choice.
- **Sections 7–13** are the build plan: components, phases, tests, data, experiments, configuration
  and engineering practice.
- **Sections 14–18** are the honest part: known limits, risks, timeline, open items and
  recommendations.

Byte-level detail lives in the specification and is referenced as "spec §N".

**Identifiers** (shared by both documents): `DB-N` decision, `C-N` component, `P-N` phase, `T-N`
pre-registered target, `EX-N` experiment, `RQ-N` research question, `L-N` known limit, `R-N` risk,
`O-N` open item, `INV-N` engine invariant, `[RN]` reference.

**Discipline that applies everywhere:**

1. Targets are fixed before anything is measured and are never moved afterwards.
2. All five seeds `[42, 123, 777, 2024, 9999]` are run every time, and all five are reported.
3. A deliberately broken build that leaves the tests green means a test is missing.
4. Anything excluded from a claim gets a written line in §14.
5. Every run is logged automatically; a run that cannot write its log entry does not start.
6. Nothing that is not measured is claimed.

---

## 1. Announcement

### 1.1 What SEVER-DB is

SEVER-DB is an **embedded, transactional, crash-safe vector database written from scratch in Rust**.
It is built for AI search systems (retrieval-augmented generation, semantic search) that store text as
embedding vectors. It owns everything: file formats, write-ahead log, storage checkpoints, crash
recovery, transactions, key management, index and search.

### 1.2 Why it exists

**The problem.** AI search systems store text as vectors and, to search quickly, sort the vectors
into groups, each with a summary such as a centroid. When a person asks to be deleted, most systems
only hide the record. The summaries still carry that person's contribution, and so do the write-ahead
log, old storage files, freed disk blocks and backups. We call these surviving traces **the ghost**.
And nobody outside the company can check that a deletion really happened.

**Why no existing system solves it:**

- *Soft deletion* (hide the record, filter it at query time) leaves the record in the data structure
  and its influence in the summaries.
- *Rebuilding the index* after deletions is exact but expensive, and still leaves old copies on disk.
- *Certificate schemes that track record IDs* prove an ID was removed, not that its numbers left the
  summaries.
- *Secure-deletion storage systems* erase bytes, but know nothing about vector summaries and give no
  public receipt.

**The idea**, in three parts:

1. **Store sums, not averages.** Each group keeps an integer running total and a count. Subtracting a
   vector restores the group bit for bit to its never-inserted state; an average cannot be undone.
2. **Issue a receipt.** Each group's total is sealed in a cryptographic commitment. Every deletion
   yields a certificate that anyone can check with no database access.
3. **Destroy the old keys.** Everything secret goes to disk only as ciphertext, and every deletion
   destroys the key that protected every old copy of the deleted data.

### 1.3 What is new

To our knowledge, no existing system makes vector deletion simultaneously:

- **exact** in the index arithmetic (bit-for-bit restoration of every group summary),
- **publicly verifiable** (a receipt checkable without database access),
- **transactional and crash-safe** across many groups at once, and
- **physically erased** from storage (write-ahead log, old storage checkpoints, free space).

The storage engine itself is a contribution: it is designed around a leak specific to exact
accumulators. If two versions of a group's total survive on disk, one before and one after a deletion,
subtracting them gives back the deleted vector exactly (`S_pre − S_post = x̃`), and the same
subtraction on the blinding totals gives back the user's secret (`r_agg_pre − r_agg_post = r_t`).
Exactness, the system's strength, turns any retained old version into a perfect leak. SEVER-DB's key
rotation rule (spec §13.3) closes it.

### 1.4 Project goals (each one is testable)

| ID | Goal | How it is checked |
|---|---|---|
| **G1** | Exact deletion: every group returns bit for bit to its never-inserted state | Differential tests against the reference model; sabotage-tested equivalence helper (T-3) |
| **G2** | ACID transactions across groups, surviving a crash at any point | Deterministic fault injection at every protocol step (T-1) |
| **G3** | Physical erasure of deleted data | Forensic scans of raw disk images, free space included (T-2) |
| **G4** | Anyone can verify a deletion from the certificate alone | Independent verifier accepts every honest certificate and rejects every attack (T-4) |
| **G5** | Search quality stays stable as deletions accumulate | Per-seed standard deviation of Recall@10 across deletion rungs (T-5) |
| **G6** | The fixed-point encoding costs no search quality | Quantised vs original-float brute-force recall (T-6) |
| **G7** | Run 10^6 vectors on the owner's 16 GB laptop | Measured memory, disk and recovery time (EX-8) |
| **G8** | Every cost of provable deletion measured and reported as found | EX-7 |

### 1.5 Non-goals for v1

- Distributed operation, replication and sharding.
- Graph indexes (HNSW, DiskANN): they cannot excise a node exactly (DB-13).
- Removing data from model weights. SEVER-DB deletes from the search index only, and assumes the
  encoder model was trained on public data.
- An erasure guarantee against the **operator**, who can always copy a key (§4).
- Beating other vector databases on speed. Speed is measured, not claimed.
- 768-dimensional vectors and 10^7-vector scale (future work, §17).

---

## 2. Background: the problem, prior evidence and related work

### 2.1 Origins

SEVER-DB grows out of an earlier research prototype by the same author, **SEVER** ("provable deletion
from AI search databases"), written in Python with a small Rust cryptography module. SEVER-DB is a
**new, independent project**: it has its own specification, its own code, its own reference model and
its own experiments, and it does not depend on the prototype's code, data or documents. Wherever
SEVER-DB keeps one of the prototype's design choices, the choice is restated in full here or in the
specification, with its reasoning. The prototype is used for exactly one optional purpose: cross-checking
a few byte-level results that are deliberately kept compatible (the generators and the canonical group
blob, DB-14 and DB-33).

### 2.2 What the prototype established (prior evidence, not claimed by SEVER-DB)

These results came from the prototype on a 30,000-passage sample of Natural Questions, 384-dimensional
MiniLM embeddings, mostly at seed 42. SEVER-DB treats them as **design guidance only**: it re-measures
everything it relies on, under its own pre-registration.

| Finding | Prototype result | Status for SEVER-DB |
|---|---|---|
| 24-bit fixed-point quantisation costs no search quality | Recall ratio 1.0000; 0.9776 at much lower precision | Re-measured as T-6 |
| Integer deletion is exact | Totals after deletion matched never-inserted totals bit for bit | Re-established as T-3 |
| Overflow headroom | Largest group seen (3,510 vectors) used 31 of 63 bits; worst case at 10^6 members is 44 bits | Re-derived analytically (spec §4.4) |
| Encoder truncation | 5.3 % of passages exceed MiniLM's 256-token limit | Truncation accepted (DB-41) |
| Live data drifts from the reference set | Pooled Ledoit–Wolf threshold τ = 25.49; 89.44 % of live vectors out-of-distribution (seed 42, verified against an independent oracle) | Re-measured per seed by the partition builder |
| Freezing costs recall; spawning recovers it | Exploratory notebook: about 0.74 frozen-only vs about 0.98 re-fitted | **Unreproduced**; the notebook was never committed. Not cited; EX-6 measures it afresh |
| Group sizes are uneven | Balance target 0.4 missed at every setting (0.549 at target size 200) | Measured and reported, not managed (DB-11, L-10) |

Two methodological lessons from the prototype shaped SEVER-DB directly:

- A figure that cannot be reproduced from committed code must not be cited. Hence the run ledger and
  the rule that every number comes from the harness (§13).
- A metric defined after the data exists cannot be trusted. The prototype's "privacy trace" metric was
  never defined and had to be retired, so **SEVER-DB reports no privacy-trace number at all**, and its
  spawn target size of 200 rests on search quality alone (DB-11).

### 2.3 Related work

- **Secure deletion.** Reardon, Basin and Čapkun's systematisation [R23] frames secure deletion
  across storage layers; flash drives do not reliably overwrite in place [R25]. Cryptographic erasure
  (encrypt, then destroy the key) goes back to Boneh and Lipton's revocable backups [R22] and is the
  mechanism NIST SP 800-88 Rev. 2 singles out [R21]. Key trees that bound re-encryption per deletion
  appear in Reardon et al. [R24]; SEVER-DB's three-level hierarchy is an instance.
- **Verifiable deletion.** Hao, Clarke and Zorzo give publicly verifiable deletion of secret data in a
  tamper-resistant device [R26]. Garg, Goldwasser and Vasudevan formalise deletion under the right to
  be forgotten [R27]; their notion that the state after deletion should look as if the data never
  arrived is the spirit of SEVER-DB's exactness relation. History-independent data structures [R28]
  motivate insertion-order independence.
- **Transparency logs.** Certificate Transparency's Merkle log [R4] provides append-only, witnessed,
  consistency-provable logs; SEVER-DB uses it unchanged.
- **Commitments and proofs.** Pedersen commitments [R6]; Schnorr [R7] generalised to representations by
  Okamoto [R9] and Camenisch–Stadler [R10], made non-interactive by Fiat–Shamir [R8]; hedged nonces
  [R11], [R13].
- **Vector search.** IVF and product quantisation [R36]; FAISS [R37]; graph indexes HNSW [R35] and
  FreshDiskANN [R38], whose deletion handling repairs graphs approximately rather than exactly;
  ANN-Benchmarks [R39].
- **Machine unlearning** removes data influence from model weights [R51]. It is complementary and out of
  scope: SEVER-DB removes data from the retrieval index, not the model.

---

## 3. Research questions, claims, non-claims and pre-registered targets

### 3.1 Research questions

- **RQ-1 — Exactness under failure.** Does a transactional engine keep deletion exact, and lose no
  acknowledged operation, when it crashes at any point of any protocol?
- **RQ-2 — Physical erasure.** After a deletion is acknowledged, can the deleted vector, record ID,
  passage text, the user's blinding value, or a pair of accumulator versions from which they follow by
  subtraction, be recovered from raw storage, including free space?
- **RQ-3 — Faithfulness and verifiability.** Does the engine match an independent, obviously correct
  reference model byte for byte, and does every certificate it issues verify, while every attack is
  rejected?
- **RQ-4 — Search stability.** Does search quality stay stable as deletions accumulate, compared with a
  soft-delete index, and does the fixed-point encoding cost any quality?
- **RQ-5 — Cost.** What do durability, certificates and cryptographic erasure cost in latency,
  throughput, bytes written and memory?

### 3.2 Claims SEVER-DB will make if the targets are met

1. Deletion is exact — five fields return bit for bit to their never-inserted values — for every
   deletion, inside multi-group ACID transactions, across crashes at every enumerated protocol step.
2. Under the stated threat model and platform requirements, no deleted plaintext and no key that
   decrypts it can be recovered from the engine's storage after acknowledgement.
3. Every certificate is verifiable by a program that shares no code with the engine.
4. Search stability and quantisation cost, as measured.
5. The measured costs, as found.

### 3.3 Non-claims

- Only deletion is exact; search results are approximate.
- No erasure guarantee against the operator; no guarantee that SSD firmware or copy-on-write
  filesystems honour an overwrite of the key file (confined to one small file, L-1).
- No claim about a memory image taken before a deletion is acknowledged.
- The shape of the index — which groups exist and where spawned centroids sit — is not restored by
  deletion. This residue is disclosed in every certificate (`group_emptied_by_this_deletion`).
- No distinguisher-based privacy claim (an adversary guessing whether a record was ever present is not
  tested), and no privacy-trace metric.
- Witnesses are simulated; the mechanism is tested, but the guarantee needs independent witnesses.
- Tested to 10^6 vectors, not 10^7. 384 dimensions only.

### 3.4 Pre-registered targets (fixed 27 September 2026, before any code exists)

| ID | Target | Kind | Experiment |
|---|---|---|---|
| **T-1** | 0 exactness violations and 0 lost acknowledged operations across the full crash campaign | Deterministic | EX-1 |
| **T-2** | 0 findings in the forensic erasure scan, and every erasure sabotage produces ≥ 1 finding (scanner sensitivity) | Deterministic | EX-2 |
| **T-3** | 100 % byte-identical canonical group blobs and identical search results, engine vs reference model | Deterministic | EX-3 |
| **T-4** | 100 % of honest certificates accepted; 100 % of attack certificates rejected | Deterministic | EX-4 |
| **T-5** | Per-seed standard deviation (ddof = 0) of Recall@10 across the five deletion rungs ≤ **0.005**, on each of the five seeds | Measured, per seed | EX-6 |
| **T-6** | Recall@10 of brute-force search over dequantised vectors, against brute force over the original floats, ≥ **0.999** at both corpus sizes (10^5 and 10^6); the corpora do not depend on the seed | Measured | EX-5 |

**One confirmatory statistical test**, fixed now: Welch's two-sided t-test comparing the per-seed
standard deviations of Recall@10 (T-5's statistic) between SEVER-DB and the soft-delete baseline, n = 5
per side, **α = 0.005**. Alongside it, a TOST equivalence test at margin Δ = 0.005 is reported, with the
expectation, recorded now, that five seeds are too few to establish equivalence. Everything else is
descriptive: means with 95 % percentile-bootstrap confidence intervals (10,000 resamples), and no
p-values.

A missed target is a result and is published with the exact counterexample or number. Continuous
integration never fails a build for missing a target; otherwise moving the target would become the
fastest way to go green.

---

## 4. Threat model

### 4.1 Adversaries

| Adversary | Capabilities | What SEVER-DB defends |
|---|---|---|
| **Dishonest operator** | Controls memory, disk and network; may fabricate state, rewrite history, or reuse proofs | Public certificates: the commitment transition check, the proof of knowledge bound to the deletion's full context, the user's insert signature under a key published in the log, and witnessed log checkpoints. **Physical erasure is not a defence against the operator** |
| **Verifier** | Holds a certificate and the verifier's bundled trust anchors; has no database access and no knowledge of any group's total | Can check everything in spec §11.3 unaided |
| **Forensic storage adversary** | At any time after a deletion is acknowledged, obtains a complete raw image of every storage device the engine uses — free space, deleted files, old storage checkpoints, WAL segments and the key file as it is then. Knows all public parameters and formats | Cannot recover deleted vectors, IDs, text, `r_t`, or any pair of accumulator versions straddling the deletion |
| **Forensic adversary holding `k_scramble`** | The above plus the operator's ID-scrambling key | Can test whether a *candidate* record ID once existed (L-4); still cannot recover content |

### 4.2 Assumptions

1. The standard primitives are secure: ristretto255 discrete log, SHA-2, HMAC, Ed25519,
   AES-256-GCM-SIV.
2. The operating system's random number generator works (the proof nonces also withstand its failure,
   DB-17).
3. An overwrite plus `fsync` of a 512-byte key-file slot destroys the old key on that device (L-1).
4. Swap, hibernation images and core dumps do not capture secrets (enforced by startup checks, DB-35).
5. At least four of the five witnesses are honest (simulated in v1, L-7).

### 4.3 Out of scope

Timing and cache side channels; hardware attacks; a compromised kernel; SSD firmware; the encoder
model; availability (an operator can always refuse service).

---

## 5. The design in plain words

**Turning vectors into integers.** Every embedding is checked to have length 1 (within 8 float32 ULPs),
multiplied by 2^24 and rounded to the nearest integer (ties to even). Integer addition and subtraction
are exact, so a subtraction always undoes an addition.

**Groups that never move.** Before any user data arrives, 128 groups are fitted with k-means on a public
reference dataset (SciQ science passages), and frozen. The same fit gives a drift threshold: the 99th
percentile of how far reference vectors sit from their group centre, measured by a Mahalanobis distance
that accounts for the shape of the data. Because groups never move, a deletion touches exactly one
group, so checking that group is enough.

**Sums and counts.** Each group stores an integer sum, a count, a commitment to the sum, and a blinding
total. Insert adds; delete subtracts. After a deletion the group is identical, bit for bit, to one that
never received the vector. Deleted records are physically removed from the member list, never marked.
Retrying a deletion is harmless: if the record is already gone, nothing changes.

**Data that does not fit.** A live vector further than the threshold from its nearest frozen group does
not join it. It first tries to spill into an existing spawned group that has room. If none has room, it
waits in a holding area, where it can be deleted at any time but not searched. When 200 vectors are
waiting, they form one new spawned group, frozen at birth. The group's name is a hash of its founders'
IDs, and its centre is their mean at that moment.

**Search.** Rank every group by the distance from the query to its centre; scan the closest quarter
(empty groups still count); return the closest records. A fixed percentage, not a fixed number, keeps
coverage constant as groups multiply.

**Receipts.** Each record carries a Pedersen commitment `C_t` to its integer vector, blinded by a
random value `r_t` that the user generates and keeps; possessing `r_t` is the right to delete. The user
signs `C_t` at insert, and the signature and the user's public key go into a public, append-only Merkle
log, cosigned by witnesses. On deletion, the group's commitment drops by exactly `C_t`, and the operator
attaches a proof that it knows the whole new group state (not just part of it), bound to this specific
deletion. A certificate carries everything needed to check all this offline.

**Transactions and crashes.** The engine keeps its state in memory and makes it durable with a
write-ahead log and periodic storage checkpoints. One writer at a time; searches run concurrently. A
deletion of all of one person's records is a single all-or-nothing transaction.

**Physical erasure.** On disk, everything secret is ciphertext under a three-level key tree: a group
key (only in a small key file), 64 bucket keys per group, and one key per record. When any record leaves
a group, the group's key and the affected bucket key are replaced, survivors are re-wrapped, and the old
group key is overwritten. Every older copy of the deleted data — in the log, old storage checkpoints or
free space — then becomes permanently unreadable.

```
insert ─► check & quantise ─► route ──► frozen group ─┐
                                 ├────► spawned group ─┼─► encrypt, update sums & commitment,
                                 └────► holding area ──┘   log the insert, commit
                                          (200 ⇒ new spawned group)

delete ─► find ─► check r_t opens C_t ─► subtract ─► prove ─► certificate
        ─► new key (phase A) ─► commit (phase B) ─► wipe memory ─► erase old key (phase C) ─► acknowledge
```

---

## 6. Decision register (DB-1 … DB-43)

Every choice, with the options weighed. A decision is changed only by a new, dated entry that names
the one it supersedes and says why; nothing is edited silently.

### 6.1 Foundations

#### DB-1 — An independent project with its own specification

**Decision.** SEVER-DB is a new repository with its own normative specification. It depends on no code,
data or document of the earlier prototype. **Why.** The prototype's code must stay frozen to keep
producing its paper's numbers, and a new system needs a single, self-contained source of truth.
**Rejected.** Evolving the prototype in place (would change the code behind published numbers);
importing its decision register by reference (a reader would need a second, 3,000-line document to
understand this one). **Consequence.** Every inherited choice is restated with its reasoning. The
prototype remains an optional cross-check for the generators and canonical blob only.

#### DB-2 — Engine in Rust; Python for tooling

**Decision.** The engine is Rust (edition 2024). Python is used for the SDK, the partition builder, the
reference model and the experiments. **Why.** Rust gives memory safety in the component that handles
secrets, real memory wiping (`zeroize`, `mlock`), no garbage collector and no global interpreter lock.
**Rejected.** Python (cannot guarantee memory wiping; too slow); C++ (memory-safety risk exactly where
secrets live). **Consequence.** A PyO3 boundary; the SDK is a thin wrapper.

#### DB-3 — Pin one cryptography dependency family

**Decision.** `curve25519-dalek 4.1.3`, `ed25519-dalek 2.2.0`, `merlin 3.0.0`, `aes-gcm-siv 0.11.1`,
`sha2 0.10.9`, `hmac 0.12.1` — all on `rand_core 0.6` and `digest 0.10` (spec §20). **Why.**
`curve25519-dalek 5.0.0` (6 July 2026) moves to `rand_core 0.10` and `digest 0.11`, but `merlin` has no
release beyond 3.0.0 and stays on `rand_core 0.6`. One consistent family halves the audit surface, and
the verifier must use the same curve library version as the engine. **Rejected.** Adopting dalek 5 now
(mixed families, or dropping Merlin). **Consequence.** One later, separate migration, gated on every
golden vector (O-5).

#### DB-4 — A reference model is the primary oracle

**Decision.** A slow, simple, in-memory Python implementation of the index semantics (spec §3–§8 and
the certificate arithmetic), written from the specification (C-18), is the oracle for differential
tests. **Why.** An engine with encryption, a WAL and crash recovery has many places to hide a
semantic bug; a second implementation that has none of that machinery makes such bugs visible.
Byte-equality against it is T-3. **Rejected.** Testing the engine only against itself; using the old
prototype as the oracle (it would make the new project depend on the old one, DB-1). **Consequence.**
About three extra weeks in P1, which buy most of the correctness evidence.

### 6.2 Arithmetic and data model

#### DB-5 — 24-bit fixed point; exact integer accumulators

**Decision.** Normalisation check within 8 float32 ULPs; quantise with `round_half_to_even(x·2^24)`;
store `x̃` as `i32`; sums in `i64`; hard cap of 10^6 members per group (spec §4). **Why.** Integer
arithmetic makes deletion exactly reversible. 24 bits were lossless in prior evidence (to be confirmed,
T-6). Ties-to-even is unbiased, so no bias accumulates in sums. 8 ULPs is 8× the float32 floor at 1.0,
yet four orders of magnitude tighter than any un-normalised embedding. With the tolerance, the largest
`|x̃|` is `2^24 + 16`, so the sum at 10^6 members fits in 44 bits, leaving 19 bits spare. **Rejected.**
Floating-point sums (not exactly reversible); ties away from zero (biased); storing `x̃` as `i64` (twice
the space for no benefit). **Consequence.** The quantiser is shared by the SDK and the engine, because
clients commit to `x̃`.

#### DB-6 — What "exact deletion" means

**Decision.** Exactness means five fields equal their never-inserted values: sum, count, commitment,
canonical group blob, member list (spec §5.5). Deleted records are physically removed (no markers).
Deletion is idempotent (absent ⇒ no change). Empty groups stay forever. **Why.** This covers 100 % of
deletions and claims only what is provably true. The shape of the index (which groups exist) cannot be
restored, because other records joined spawned groups and cannot be re-routed retroactively.
**Rejected.** Claiming full equivalence only for deletions that created no group (covers about 10 % of
live data); deleting groups when they empty (needs removal rules that break the frozen partition).
**Consequence.** One equivalence helper, tested by corrupting each field separately; the index-shape
residue is disclosed per certificate (DB-22).

#### DB-7 — Record IDs from the dataset, never counters

**Decision.** 1–256 UTF-8 bytes, not a bare decimal integer, unique among live records (spec §3.2).
**Why.** Group contents must not depend on arrival order; an insertion counter encodes order.
**Rejected.** Type-only checks (`"1"` is a counter in disguise); a configurable regex (a locked value with
no justification). **Consequence.** A shape heuristic, backed by the real test: different insertion
orders yield identical canonical blobs.

#### DB-8 — Collections with random 16-byte IDs

**Decision.** A database holds collections; each has its own partition, parameters and keys, and a
16-byte random ID that appears in every leaf, signature and certificate. **Why.** Fixed-width IDs keep
every hash and signature input unambiguous by concatenation. **Consequence.** `drop_collection` is a
cryptographic erase of every key in the collection (spec §15.9).

### 6.3 Partition, drift, spawning and search

#### DB-9 — The partition is built offline and imported; one per seed

**Decision.** A Python partition builder (C-15) fits 128 k-means groups on the dequantised reference
set and writes a hashed artefact; the engine only imports it (spec §6). Each of the five seeds gets its
own partition. **Why.** Keeps floating-point model fitting out of the engine; the artefact is a
reproducible, hashed file. Per-seed partitions make the reported variation include partition
variation, which is honest. **Rejected.** Fitting inside the engine (a second, divergent numeric
implementation); one partition for all seeds (understates variance). **Consequence.** An independent
Ledoit–Wolf oracle in the builder is required (spec §6.2 step 7).

#### DB-10 — The drift test

**Decision.** Assign to the nearest frozen centroid by Euclidean distance; measure the Mahalanobis
distance to it using one pooled Ledoit–Wolf covariance estimate; out-of-distribution if and only if the
distance exceeds τ, the 99th percentile of the same distance over the reference set (spec §7.1–7.2).
**Why.** Mahalanobis distance accounts for correlated dimensions; shrinkage keeps a 384×384 covariance
well-conditioned; "pooled" means **one** fit over all within-group residuals. **Rejected.** Averaging
per-group fits (the shrinkage then depends on how balanced the partition is — prior evidence showed
this changes τ by about 3 units, 22.4 vs 25.5); unshrunk covariance (can be singular). **Consequence.**
All float operations have a pinned order, so the engine and the reference model agree bit for bit.

#### DB-11 — Spawning: spillover first, then a holding area that forms exactly one group of 200

**Decision.** An out-of-distribution vector goes to the nearest spawned group with room
(`2·k·n < 3·N`); otherwise to the holding area. At exactly 200 waiting vectors, one flush forms exactly
one new spawned group, named by a hash of its founders' IDs, with its centroid fixed at creation.
Spawned groups never move, have no threshold of their own and never spawn (spec §7.3–7.5). **Why.**
Frozen centroids are what make one-group certificates sound, so new data gets new groups instead of
moving old ones. Checking spillover first is what keeps spawned groups full and the group count low.
200 matched a rebuilt index's quality in prior evidence; **it is justified on search quality alone**.
**Rejected.** A timer-based flush (unpredictable group sizes); clustering inside a flush (with a size
trigger at the target size, there is only ever one group's worth); counter-based group names (encode
creation order); moving centroids (breaks the frozen partition). **Consequence.** Newly arrived
out-of-distribution data is not searchable until its group forms (L-12); group balance is measured,
not managed (L-10).

#### DB-12 — The holding area: deletable, never searchable, holds `r_t`

**Decision.** Holding-area records are encrypted like any record, including their `r_t` (needed to
fold them into the new group's blinding total at flush); they are not searchable; a deletion is honoured
immediately and yields a holding-area certificate (DB-22). **Why.** A system that promises deletion must
never queue a deletion. **Consequence.** A holding-area deletion changes no accumulator, which makes it
distinguishable from a group deletion (declared, L-5).

#### DB-13 — Search: IVF-flat with pinned coverage, tie-breaks and kernel

**Decision.** Probe `⌈0.25·k⌉` groups, empty ones included, ranked by float64 centroid distance with
group-ID tie-break; score members with a pinned 8-lane float32 kernel without fused multiply-add; ties
by record ID (spec §8). No graph index. **Why.** A percentage keeps coverage constant as groups
multiply; counting empty groups keeps "25 %" meaning the same at every deletion level; pinned arithmetic
makes the scalar and AVX2 kernels and the reference model agree exactly. Graph indexes keep neighbour
edges shaped by the deleted node. **Rejected.** A fixed probe count (coverage would shrink as groups
spawn); skipping empty groups (makes deletion rungs incomparable). **Consequence.** Recall at high
deletion rungs is reported as found, empty groups included.

### 6.4 Cryptography

#### DB-14 — Pedersen commitments on ristretto255 with public-string generators

**Decision.** Generators by the RFC 9496 `hash_to_group` construction from the public string
`PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS`; startup self-check against a frozen golden file plus the
RFC test vectors; refuse to run on mismatch (spec §9.2). **Why.** Nobody, including the operator, holds a
trapdoor between generators hashed from a public string. Keeping the prototype's string costs nothing
and lets the generators be cross-checked against an existing implementation. **Rejected.** A fresh DST
(loses that cross-check for no security gain); one `expand_message` call for all generators (a verifier
could not derive `G_i` without deriving every earlier one). **Consequence.** The self-derived golden file
detects drift; correctness rests on the third-party RFC vectors.

#### DB-15 — Integer-to-scalar mapping; groups start at the identity

**Decision.** Negative sums map to `ℓ − |v|`; every group starts with `S = 0`, `r_agg = 0`,
`C_S = identity` (spec §4.5, §5.2). **Why.** Both are needed for byte-exact golden vectors, and the
identity start makes emptiness publicly checkable: a group is empty exactly when its commitment is the
identity. **Consequence.** The verifier checks `group_emptied_by_this_deletion` against `C_S_post`.

#### DB-16 — Proof of knowledge of the whole group state, bound to the deletion

**Decision.** An Okamoto / Camenisch–Stadler proof of knowledge of `(r_post, S_post)` — all 385
secrets — with a Fiat–Shamir challenge over `C_S_post`, the prover's commitment `A`, and the deletion
context (`C_S_pre`, `C_t`, scrambled ID, log position, collection) (spec §9.5). 12,352 bytes at
d = 384. **Why.** A verifier with no database access cannot evaluate a proof about the blinding value
alone, because that equation needs the group's sum, which must stay secret. Binding the full context
follows standard practice and makes a proof unusable in any other certificate. **Rejected.** Publishing
the group's sum commitment separately (consecutive values would reveal an unblinded commitment to each
deleted vector); a logarithmic-size proof (the only available implementation is marked experimental by
its maintainers). **Consequence.** About 12 KB per certificate (L-15). A written soundness argument
(completeness, special soundness with an extractor, honest-verifier zero-knowledge with a simulator) is a
deliverable of P2.

#### DB-17 — Hedged proof nonces

**Decision.** Nonces from a Merlin transcript that absorbs the statement and context, is rekeyed with
every secret, and is finalised with fresh OS entropy; the prove function accepts only a type that cannot
be seeded (spec §9.6). **Why.** Reusing one nonce vector would leak the entire group sum. Pure OS
randomness fails under VM snapshot replay; deterministic nonces (RFC 6979 style) fail under fault
injection and are specified for one scalar, not 385. **Consequence.** A seeded generator reaching the
proof is a compile error in Rust and an exception in Python.

#### DB-18 — Users generate blinding values; `r_t` is the deletion capability

**Decision.** The client draws `r_t`, computes and signs `C_t`, and keeps `r_t`; the engine accepts a
deletion only if the supplied `r_t` opens the logged `C_t` (spec §3.3, §9.4). **Why.** Only the user
(and the operator, who necessarily saw `r_t` at insert) can authorise a deletion, with no separate
authentication scheme. **Consequence.** Losing `r_t` means the user cannot delete through the API;
the SDK makes storing it the caller's explicit duty.

#### DB-19 — Scrambled record IDs

**Decision.** `HMAC-SHA-512(k_scramble, collection_id ‖ record_id)`, with a non-rotating operator key
(spec §9.7). **Why.** The operator can prove to an auditor which record a certificate concerns, while log
readers cannot enumerate deleted IDs. SHA-512 reuses a primitive already in the system. **Rejected.** A
stored mapping table (extra durable state with no benefit); rotating the key (the certificate would need
an epoch field for a key that never needs one). **Consequence.** L-4.

#### DB-20 — Ed25519 everywhere; user keys never rotate

**Decision.** Domain-separated messages for user, operator-log-checkpoint, witness and certificate
signatures; `verify_strict`; 90-day epochs for operator and witness keys; user keys never rotate (spec
§9.8). **Why.** An insert signature may need to verify years later. **Consequence.** Verifier anchors
list keys by epoch; certificates from epochs after a verifier's release cannot be checked by it (L-14).

### 6.5 Log and certificates

#### DB-21 — An RFC 9162 transparency log with simulated witnesses

**Decision.** One RFC 9162 Merkle log (SHA-256); insert and delete leaves; log checkpoints every 10,000
leaves and on demand; five witnesses with threshold four, each verifying consistency before cosigning
(spec §10). **Why.** A standard, citable construction with published proof algorithms. Publishing user
keys at insert stops an operator from signing a fabricated commitment with its own key. **Rejected.**
A Merkle Mountain Range (no equally authoritative standard). **Consequence.** L-7.

#### DB-22 — A self-sufficient certificate in a deterministic encoding

**Decision.** 13 TLV fields plus an operator signature (spec §11.1). Field 6 carries the record's insert
leaf, its inclusion path, and the signed log checkpoint; field 7 carries witness cosignatures over that
same log checkpoint; field 12 marks holding-area deletions; field 13 names the collection. **Why.** This
lets a verifier check user authorisation, log inclusion and witnessing with no other input. It fixes
two weaknesses of the earlier prototype's certificate (the verifier needed out-of-band leaves and user
keys, and cosignatures did not attest a real log checkpoint). TLV replaces protobuf because signed bytes
must be canonical. **Rejected.** Protobuf (not canonical); proving inclusion of the deletion's own leaf (a
certificate cannot contain a proof about itself). **Consequence.** About 14.1 KB per certificate; that
the deletion leaf itself was logged is an auditor's check (C-17, L-13).

#### DB-23 — `database_lsn` is the leaf index

**Decision.** An operation's `database_lsn` is the 0-based index of its log leaf. **Why.** It names a
position in the database's own log, needs no new state, and is checkable by an auditor.

#### DB-24 — Certificate, leaf and state change commit atomically

**Decision.** A deletion's state change, its delete leaf and its certificate are one WAL transaction.
**Why.** Neither can exist without the others. This is strictly stronger than "append to the log as the
last step". **Consequence.** No orphaned leaves, and no certificate for a rolled-back deletion.

#### DB-25 — The proof is computed inside the deletion

**Decision.** Proof generation happens before commit. **Why.** Computing it later would require keeping
a copy of the secret post-state, itself a hazard. **Consequence.** Deletion latency includes the proof;
if measured latency is unacceptable, an encrypted, erasure-covered asynchronous queue is the fallback,
decided by a new entry (O-1).

### 6.6 Storage, keys and erasure

#### DB-26 — Memory-resident, disk-durable storage

**Decision.** All live state in RAM; a WAL plus full storage checkpoints for durability; page-structured
files (spec §12). **Why.** 10^6 vectors need about 3.8 GB on a 16 GB machine; this is the simplest
design to make correct. **Rejected.** A copy-on-write B+tree with a page cache (twice the work, needed
only beyond RAM); in-place pages with ARIES undo and redo (most complex, no benefit). **Consequence.**
L-9; a page cache can be added later without a format change.

#### DB-27 — One writer, shared readers, no retained snapshots

**Decision.** A writer mutex plus a reader lock. **Why.** Serializable isolation with the least code, and
no MVCC snapshot can keep a deleted record alive in memory. **Rejected.** MVCC (every retained snapshot is
an in-memory ghost); multiple writers (no benefit at this scale). **Consequence.** Searches may wait
briefly for an apply.

#### DB-28 — Physical erasure by cryptographic erasure with three key levels

**Decision.** Group key (key file only) → 64 bucket keys → one key per record (spec §13.1). **Why.** Only
a small file then needs physical erasure. With two levels, every deletion would re-wrap every surviving
record key in the group: about 342 KB per deletion and about 169 GB of writes over a 90 % deletion rung at
10^6 vectors. Three levels cut this to about 12.9 KB per deletion. Key trees for deletion are standard
[R24]. **Rejected.** Overwriting data in place (flash and copy-on-write filesystems do not honour it
[R25]); two levels. **Consequence.** Only group keys need erasure; the key file is about 1 KB per group.

#### DB-29 — Rotate a key domain whenever any record leaves it

**Decision.** Deletion from a group or the holding area, and a flush out of the holding area, rotate the
domain's group key and affected bucket keys in the same transaction (spec §13.3). **Why.** This
guarantees that no decryptable pair of accumulator versions straddles a deletion, and that no departed
record's key stays reachable through an old wrapping. Rotating on a flush is required: otherwise a
flushed record's key would remain reachable through the holding area's old wrapping after the record is
later deleted from its new group. **Consequence.** Inserts never rotate anything.

#### DB-30 — The key-erasure rule, a two-slot key file, one recovery rule

**Decision.** An old group key is destroyed only after everything it protects is durable under the new
key; two slots per domain; after replay, keep only the slot with the active version (spec §13.4).
**Why.** Destroying a key too early would make live data unreadable; one rule then covers every crash
point (spec §15.4). **Consequence.** If the active version's slot is missing, the engine refuses to start
rather than serve undecryptable data.

#### DB-31 — AES-256-GCM-SIV with typed associated data

**Decision.** AES-256-GCM-SIV (RFC 8452), random 96-bit nonces, associated data per ciphertext type
(spec §13.2). **Why.** RFC-specified and resistant to nonce misuse (VM snapshots, cloned state); the CPU
has AES-NI. Record-level ciphertexts carry no group or key version, so slots move without decryption and
rotation never re-encrypts member data. **Rejected.** AES-GCM (catastrophic on nonce reuse);
XChaCha20-Poly1305 (specified only by an expired draft).

#### DB-32 — What is plaintext on disk

**Decision.** Plaintext: counts, commitments, centroids, scrambled IDs, group IDs, key versions, log
leaves and certificates. Everything else is ciphertext (spec §13.2). **Why.** Each plaintext item is
either already public (commitments, leaves), needed to route, or declared visible (counts). The sums and
blinding totals are encrypted because two versions of them subtract to the deleted data.

#### DB-33 — Canonical blob on demand; fixed-size slots

**Decision.** The canonical group blob is generated in memory, never stored, and is byte-compatible with
the earlier prototype's; the physical layout uses 1,992-byte slots with record IDs padded to 256 bytes
(spec §5.5, §14.4). **Why.** Rewriting a whole group blob per operation costs O(group size); fixed-size
slots allow swap-with-last removal; padding hides ID length. **Consequence.** The moved slot's locator
entry must be updated in the same transaction (a classic bug, with its own test).

#### DB-34 — Acknowledgement means durable, erased from memory, and old key gone

**Decision.** A deletion is acknowledged only after commit, memory wiping and phase C (spec §15.8).
**Why.** An acknowledgement is the moment the erasure claim begins to apply.

#### DB-35 — Memory hygiene

**Decision.** `zeroize` on every secret; `mlock` for keys and accumulators; core dumps disabled; refuse to
start with unencrypted swap or hibernation unless an explicit development flag is set (spec §12.8).
**Consequence.** The 1.5 GB search mirror is not locked (L-6).

#### DB-36 — Platform

**Decision.** Linux x86-64; data on ext4 or XFS; the key file refused on ZFS and on btrfs without
no-copy-on-write; AVX2 detected at runtime with a scalar fallback; no AVX-512 (the target CPU has none);
experiments on native Linux only (spec §12.9). **Why.** Each requirement closes a known way for old key
bytes or data to survive, or matches the hardware. **Consequence.** L-8.

#### DB-37 — `fsync` discipline

**Decision.** Directory `fsync` after every create, rename or unlink; abort on any `fsync` error, never
retry; no writes through `mmap` (spec §12.7). **Why.** After a failed `fsync` the kernel may already have
dropped the dirty pages, so a retry can report success for lost data [R30], [R31].

### 6.7 Process

#### DB-38 — Library first, SDK second, server last

**Decision.** Embedded Rust library → Python SDK → optional gRPC server. **Why.** The server adds no
research claim and waits until everything beneath it passes its gates.

#### DB-39 — Two kinds of crash and erasure testing

**Decision.** Deterministic fault injection on the in-memory `SimVfs` at every protocol step and every
byte of sampled records; and forensic scans of real ext4 images mounted without root through `fuse2fs`,
free space included. **Why.** The first is exhaustive and deterministic; the second tests the real
filesystem. Neither is flaky.

#### DB-40 — Pre-registration, five seeds, as-found reporting, automatic logging

**Decision.** The targets in §3.4 are fixed now and timestamped by commit (optionally also on OSF); all
five seeds, all reported; every run writes a ledger entry with the code commit, configuration hashes,
dataset manifest hash, seed and platform report. **Why.** A result that can be tuned after the fact
cannot be trusted.

#### DB-41 — Datasets, text fields, encoder and experiment design

**Decision.** Reference set SciQ; live set BEIR Natural Questions; MiniLM-L6-v2 embeddings, truncated at
the model's 256-token limit; exact text fields, splits, cohorts, stream fractions and deletion rungs as in
§10. The 0 %-live condition of a mix-ratio design is replaced by a *frozen-only* control arm. **Why.** The
two-dataset split is essential: groups must be fixed on data that contains no user data. Streaming 0 % of
the live corpus gives an empty index, which cannot answer the question; a frozen-only arm (spawning
disabled) shows what spawning buys. **Consequence.** The drift thesis is tested where it matters: about
90 % of live data is out-of-distribution in prior evidence.

#### DB-42 — Licences

**Decision.** Code under `MIT OR Apache-2.0`. Derived data are released as a labelled collection, each
file under its upstream licence: SciQ-derived files CC BY-NC 3.0, NQ-derived files CC BY-SA 3.0, never
merged into one file. **Why.** Compatible with every dependency's licence (BSD-3-Clause, MIT,
Apache-2.0). **Consequence.** SciQ's non-commercial term would block a commercial product that ships the
reference partition; a commercial use would need another reference set (L-19).

#### DB-43 — Keep every certificate in v1

**Decision.** v1 retains all certificates (about 12.7 GB at 900,000 deletions). **Why.** Every certificate
must be independently checkable, and aggregation reduces verifier computation, not stored bytes.
**Consequence.** A retention policy is future work (O-7); L-15.

---

## 7. Components at a glance

Each component announces what it is, why it exists, its goals and what proves it in spec §19.1. In
brief:

| ID | Component | One line |
|---|---|---|
| C-1 | Storage I/O | All I/O through a `Vfs`; a seeded fault-injecting `SimVfs` for crash tests |
| C-2 | Formats | Byte-exact, checksummed, versioned encoders and strict parsers |
| C-3 | WAL | Ciphertext-only after-images; a transaction exists when its `COMMIT` is durable |
| C-4 | Storage checkpointer | Atomic full images; bounds recovery time |
| C-5 | Transaction manager | One writer, shared readers, the §15 protocols |
| C-6 | Key manager | Three-level keys, rotation on departure, two-slot key file |
| C-7 | Crypto | Generators, commitments, proof, nonces, HMAC, signatures, encryption, quantiser |
| C-8 | Routing | Nearest frozen group, Mahalanobis drift test, spillover, holding area |
| C-9 | Index core | Groups, slots, sums, counts, commitments, flushes, capacity, locator |
| C-10 | Search | IVF-flat with a pinned kernel |
| C-11 | Log and certificates | RFC 9162 log, log checkpoints, witnesses, certificate builder |
| C-12 | Engine API | The stable Rust surface |
| C-13 | Python SDK | Bindings plus client-side quantise, commit and sign |
| C-14 | Server | Optional gRPC front end |
| C-15 | Partition builder | Offline k-means, pooled Ledoit–Wolf, threshold, independent oracle |
| C-16 | Verifier | Separate program, no shared code, checks a certificate alone |
| C-17 | Auditor | Checks what a certificate cannot: deletion leaves, chains, log consistency |
| C-18 | Reference model | Slow, obviously correct Python model; the primary oracle |
| C-19 | Experiment harness | Runs experiments; writes the run ledger |

---

## 8. Phases P0–P9

Each phase announces **what it is, why it exists, its goals, its exit gate, the sabotage it must catch
(must-fail tests), and its duration**. A phase closes only when its exit gate is met and recorded in
the run ledger. Durations assume one person full time; they will slip, but the order will not.

### P0 — Bootstrap (2 weeks)

- **What.** Repository, pinned toolchains, CI skeleton, licence policy; dataset download with pinned
  revisions; embeddings computed once and pinned by SHA-256; the pre-registration commit.
- **Why.** Every later number depends on exact data and exact tools.
- **Goals.**
  - P0.G1 Rust 1.98.1 and the crate set of spec §20.1; Python 3.13 lockfile (spec §20.2).
  - P0.G2 Pin the SciQ and BEIR NQ dataset revisions and the MiniLM model commit; build the 10^5 and 10^6
    corpora (§10.4); write `datasets/MANIFEST.sha256`.
  - P0.G3 Split non-overlap tests (§10.5).
  - P0.G4 Commit §3.4's targets and `configs/experiments.yaml` unchanged. That commit is the
    pre-registration timestamp.
- **Exit gate.** Spec §20.3 checks 1, 5, 6 and 7 pass; the manifest verifies on a fresh clone after
  regeneration or download.
- **Must-fail.** Changing one corpus row changes the manifest hash, and the harness refuses to run.
- **Recommended start.** After the earlier SEVER paper is submitted (§18).

### P1 — Partition builder and reference model (3 weeks)

- **What.** C-15 (spec §6) and C-18, the slow, obviously correct Python model of spec §3–§8 and the
  certificate arithmetic. The golden vectors that do not need the engine (spec Appendix B, items 4, 5,
  7, 8).
- **Why.** The oracle must exist before the thing it checks. Writing the model is also the best test of
  whether the specification is complete.
- **Goals.** P1.G1 Artefacts for all five seeds, with the independent Ledoit–Wolf oracle agreeing.
  P1.G2 The model's equivalence helper passes its sabotage suite. P1.G3 A traceability matrix: every
  specification rule is named by at least one test ID.
- **Exit gate.** All of the above; any specification gap found is fixed in the specification and
  recorded as a decision.
- **Must-fail.** Swapping in per-group Ledoit–Wolf averaging changes τ and the builder's oracle check
  fails; corrupting each of the five exactness fields is caught separately.

### P2 — Cryptography and verifier (3 weeks)

- **What.** C-7 and C-16 (spec §9, §11.3), plus `docs/SOUNDNESS.md`: completeness, special soundness with
  an explicit extractor, and honest-verifier zero-knowledge with an explicit simulator for the proof of
  knowledge.
- **Why.** Every later phase depends on these primitives, and the verifier must be written from the
  specification, not from the engine.
- **Goals.** RFC 9496, 9380, 8452 and 8032 vectors pass; the generator golden file is produced and
  matches in both code bases; honest proofs verify.
- **Exit gate.** Spec §20.3 checks 2, 3 and 4 pass.
- **Must-fail.** Swapped challenge order; 32-byte instead of 64-byte wide reduction; a seeded RNG passed
  to proof generation (a compile-fail test); skipping the witness rekeying step; a non-canonical point
  accepted.

### P3 — Durable core, without SEVER (4 weeks)

- **What.** C-1 to C-5 for generic fixed-size records.
- **Why.** Separating "is the database correct" from "is the index correct" gives each bug one home.
- **Goals.** `SimVfs` fault model; WAL, storage checkpoints, recovery; a reusable crash-campaign harness.
- **Exit gate.** On generic records: 0 lost acknowledged writes and 0 corrupt recoveries across the
  campaign; recovery equals the pre-crash state byte for byte.
- **Must-fail.** No directory `fsync` after rename; a WAL tail with a bad CRC accepted; an uncommitted
  transaction replayed; a failed `fsync` retried.

### P4 — Keys and physical erasure (3 weeks)

- **What.** C-6 and encryption (spec §13); the key file; rotation; platform checks; the forensic scanner,
  first with synthetic secrets.
- **Why.** Erasure is the new claim, so it must be proven on simple data before index data rides on it.
- **Exit gate.** Clean scans on five seeds, and every sabotage below detected.
- **Must-fail.** Group-key rotation skipped; bucket-key rotation skipped; holding-area rotation on flush
  skipped; old key erased before commit (must lose data *and* be refused at startup); a record key
  written unwrapped to the WAL; an AEAD nonce reused (a nonce-uniqueness audit in tests).

### P5 — The SEVER index on the new storage (4 weeks)

- **What.** C-8 and C-9: partition import, routing, groups, slots, encrypted sums, holding area, flush,
  spillover, capacity, locator, `insert`, `delete`, `delete_user`, canonical blob, invariants.
- **Why.** The index semantics, on crash-safe, erasable storage.
- **Exit gate.** T-3's canonical-blob part at 10^5 passages on all five seeds; the startup invariant check
  passes after every EX-1 crash.
- **Must-fail.** One bit of a sum flipped; the count decrement skipped; a retry subtracting twice; the
  locator not updated after a slot move; routing to "the most recently created group with room";
  buffering before checking spillover.

### P6 — Transparency log and certificates (3 weeks)

- **What.** C-11 inside the deletion transaction, simulated witnesses, and C-17.
- **Exit gate.** T-4 on the attack suite (EX-4); the auditor detects a deliberately skipped deletion leaf
  and a broken certificate chain.
- **Must-fail.** A certificate for a rolled-back deletion; a proof reused in another certificate;
  cosignatures over a different log checkpoint; a wrong `group_emptied_by_this_deletion`.

### P7 — Search (3 weeks)

- **What.** C-10 with the float32 mirror, the scalar and AVX2 kernels, and the recall harness.
- **Exit gate.** T-3's search part (identical top-k lists against the reference model) on all seeds;
  scalar and AVX2 outputs identical.
- **Must-fail.** A deleted record in any result after acknowledgement; empty groups skipped when filling
  the probe budget; FMA contraction enabled in the SIMD kernel.

### P8 — API, SDK, collections; optional server (3 weeks, plus 2–3 optional)

- **What.** C-12, C-13, `create_collection` and `drop_collection`; C-14 only if time allows.
- **Exit gate.** Every experiment runs end to end through the SDK; no error message leaks an ID, a vector
  value or a key.

### P9 — Evaluation and paper (5 weeks)

- **What.** EX-1 to EX-8 at 10^5 and 10^6, five seeds; the paper.
- **Exit gate.** Every target reported as found; every limit in §14 stated in the paper; a tagged
  release with an archived DOI.

**Minimum publishable result:** P0–P7 (about 25 weeks) answers RQ-1 to RQ-4 at 10^5 passages. P8–P9 add
usability, scale and the cost study.

---

## 9. Testing strategy

### 9.1 Oracles

| Oracle | Checks | Independence |
|---|---|---|
| Reference model (C-18) | Canonical blobs, routing, search results, certificate arithmetic | Separate language and code, written from the specification |
| Verifier (C-16) | Every certificate | Separate workspace, no shared code |
| RFC test vectors | Primitives | Third party |
| Independent Ledoit–Wolf formula | Partition builder | Separate code from scikit-learn |
| Brute-force search over original floats | Recall | Trivially correct |
| `SimVfs` crash model | Durability and atomicity | Conservative POSIX model |
| Raw-image forensic scanner | Erasure | Reads bytes, not engine structures |
| Earlier SEVER prototype (optional) | Generators, canonical blob for fixed inputs | Separate project |

### 9.2 Sabotage list (each must turn a test red; run before every published result)

Flip a bit of a sum; skip the count decrement; subtract twice on retry; skip group-key rotation; skip
bucket-key rotation; skip holding-area rotation on flush; erase the old key before commit; write a
plaintext vector into the WAL; write an unwrapped key to disk; forget the locator update on a slot move;
keep a deleted vector in the search mirror; reuse an AEAD nonce; reuse a proof nonce; accept a WAL record
with a bad CRC; skip a directory `fsync`; swap the challenge preimage order; omit the context from the
challenge; skip empty groups in the probe budget; route by recency; buffer before spillover; enable FMA
in the kernel; accept a non-canonical encoding; accept three of five cosignatures.

### 9.3 Techniques and rules

- Property tests (`proptest`, `hypothesis`) over random operation streams; fuzzing of every parser
  (`cargo-fuzz`); Miri over the small, listed set of `unsafe` code (SIMD kernels, `mlock`); compile-fail
  tests for the RNG type rule; `clippy -D warnings`.
- **No flaky tests and no retries.** Concurrency is tested by deterministic interleaving, and crashes by
  `SimVfs`, never by racing threads or killing processes at random.
- Python runs with `PYTHONHASHSEED=0` and fixed thread counts.

---

## 10. Datasets and experimental setup

### 10.1 Reference set (group fitting only)

- **SciQ** [R45], Hugging Face `allenai/sciq`, revision pinned by commit in P0. Licence CC BY-NC 3.0.
- All three splits: 11,679 train + 1,000 validation + 1,000 test = **13,679 passages**.
- Passage text: the `support` field; where `support` is empty, the `question` field, so that every row
  yields a passage (DB-41). The number of rows using the fallback is reported.
- Role: fitting the frozen partition and computing τ. Never inserted into an index.

### 10.2 Live set (indexed data and queries)

- **Natural Questions** [R43] in its **BEIR** form [R44]: `BeIR/nq` (2,681,468 passages) and
  `BeIR/nq-qrels`, test split (3,452 queries, 4,201 relevance judgements). Revisions pinned in P0.
  Licence CC BY-SA 3.0.
- Passage text: `title + " " + text` (the BEIR convention for dense retrievers).
- Record ID: the corpus `_id` (for example `doc0`), which satisfies the record-ID rules.
- "User data" is simulated with these public passages. Deletion does not depend on content, so this does
  not weaken the exactness or erasure results (L-22).

### 10.3 Encoder

`sentence-transformers/all-MiniLM-L6-v2` [R46], 384 dimensions, commit pinned in P0; its 256-token limit,
with truncation; `normalize_embeddings=True`; float32; CPU encoding. Embeddings are computed once and
pinned by SHA-256. The truncation rate is reported (prior evidence: about 5 %).

### 10.4 Corpora

| Corpus | Size | Construction |
|---|---|---|
| `nq-100k` | 100,000 | All 4,201 judged passages, then a uniform random sample of the rest |
| `nq-1m` | 1,000,000 | All 4,201 judged passages, then a uniform random sample of the rest |

Every judged passage is always kept: shrinking at random would delete correct answers and depress
recall for reasons unrelated to search. The fill uses a fixed corpus seed (§10.6), so the corpora are the
same for every run seed.

### 10.5 Splits and non-overlap

Three roles: **reference** (SciQ), **indexed** (NQ corpus) and **queries** (NQ test queries). A test
asserts zero overlap between reference and indexed passages, and between queries and indexed passages,
both by ID and by SHA-256 of whitespace-normalised, lower-cased text. Overlap would make recall look
better than it is and would contaminate the drift measurement.

### 10.6 Seeds

Run seeds `[42, 123, 777, 2024, 9999]`. Each experiment derives sub-seeds as
`u64 from the first 8 bytes of SHA-256(u64be(seed) ‖ label)` for the labels `kmeans`, `stream` and
`cohort-order`. The corpus seed is the same derivation from 42 with label `corpus`, and is shared by all
runs. Proof nonces, keys and blinding values never come from any seed (DB-17).

### 10.7 Streams, arms and fractions

- **Stream.** Each run inserts corpus passages in a seed-determined random order (`stream` sub-seed).
- **Primary condition.** 100 % of the corpus is streamed.
- **Arms** in EX-6:
  1. **SEVER-DB** (full design).
  2. **Frozen-only control**: spawning disabled; every vector goes to its nearest frozen group. It shows
     what spawning buys.
  3. **Soft-delete IVF baseline**: FAISS `IndexIVFFlat` trained by k-means on the streamed corpus, with
     `nlist` equal to SEVER-DB's measured total group count for that seed and `nprobe = ⌈0.25·nlist⌉`.
     Deletions are ID-filtered at query time; records stay in the lists and centroids keep the deleted
     data's influence. It must be a *grouped* index: a flat index has no summaries, and so no ghost to
     show.
  4. **Rebuild baseline**: the same IVF retrained from scratch on the surviving records after every rung.
     Exact but expensive; the no-ghost reference.
- **Stream-fraction sweep** (descriptive): 25, 50, 75 and 100 % of the corpus streamed, reporting group
  counts, out-of-distribution rate, holding-area occupancy and recall. (A 0 % condition would be an
  empty index and is not run, DB-41.)

### 10.8 Cohorts and deletion rungs

- A **cohort** (a simulated person) is all indexed passages that share a Wikipedia article `title`. Real
  people's data clusters together, which makes the test harder, not easier.
- Cohorts are ordered by the `cohort-order` sub-seed. **Rungs** are cumulative fractions of cohorts
  deleted: **10, 25, 50, 75 and 90 %** of the cohorts present when deletion starts. Each cohort is
  deleted with one `delete_user` call.
- Measurements are taken before any deletion (rung 0) and after each rung.

### 10.9 Metrics

- **Recall@k** (k = 10, 100): the mean over all 3,452 queries of the fraction of the true top-k found,
  where the true top-k is brute force over the **original float32 vectors** of the records currently in
  groups. Holding-area records are excluded from both sides. The comparison uses original floats, not
  quantised ones, so quantisation loss is visible.
- **nDCG@10** against the relevance judgements (descriptive).
- **Drift statistic:** the standard deviation of Recall@10 across the five rungs, per seed, with
  `ddof = 0` (the five rungs are the whole pre-registered ladder, not a sample). `ddof = 1` is reported
  alongside, since `ddof = 0` gives a value about 11 % smaller and so is the easier one to meet.
- **Balance:** the coefficient of variation of group sizes, reported **separately** for frozen and
  spawned groups, because about 90 % of data sits in spawned groups and a combined figure would hide
  which population is uneven.
- **Index shape:** total groups, spawned groups, out-of-distribution rate, and the distance between
  each spawned group's frozen centroid and its members' current mean.

---

## 11. Evaluation plan

All sizes below are fixed now (pre-registration) and are not changed after any run.

| ID | Question | Method | Metric | Target |
|---|---|---|---|---|
| **EX-1** | RQ-1 | On `SimVfs`, per seed: a 20,000-operation stream (inserts, deletes, user deletes, flushes) over the first 10,000 passages of the seed's stream order. Crash at every protocol step boundary of every operation, at every 512-byte offset of 200 sampled WAL writes, and at 1,000 random points. After each crash: recover, run the invariant check, and compare with the reference model's state for the acknowledged prefix | Exactness violations; lost acknowledged operations; startup refusals | **T-1** |
| **EX-2** | RQ-2 | On a `fuse2fs`-mounted 16 GB ext4 image, per seed: ingest `nq-100k`, then run the five rungs. After each rung: storage checkpoint, clean shutdown, unmount. Scan the **raw image, free space included**, for: deleted `x̃` as `i32` and `i64` in both byte orders; the deleted original float32 vectors in both byte orders; every 32-byte window of deleted passage text; each deleted `r_t`; every retired group, bucket and record key. Then carve every engine record by magic and CRC and try every **live** key on it. The instrumented build exports each generated key to a file outside the image so the scanner knows what to look for; it is otherwise identical to the measured build | Findings | **T-2** |
| **EX-3** | RQ-3 | Per seed, `nq-100k`: the engine and the reference model run the same stream in lockstep. After every operation, compare the canonical blobs of the touched groups; after each rung, compare every group and the top-10 and top-100 lists for all 3,452 queries | Mismatches | **T-3** |
| **EX-3b** | RQ-3 (optional) | Generators and the canonical blob of a fixed three-member group, compared with the earlier SEVER prototype | Equality | Descriptive |
| **EX-4** | RQ-3 | Verify every certificate from EX-3 with C-16. Apply each attack below to 1,000 honest certificates per seed | Acceptance and rejection rates | **T-4** |
| **EX-5** | RQ-4 | Brute-force Recall@10 over dequantised vectors against brute force over the original floats, for `nq-100k` and `nq-1m` | Recall@10 | **T-6** |
| **EX-6** | RQ-4 | Per seed, `nq-100k`, 100 % streamed, all four arms of §10.7, rungs 0–5; plus the stream-fraction sweep | Recall@10/100, nDCG@10, drift statistic, balance, shape | **T-5**; Welch test against soft-delete; everything else descriptive |
| **EX-7** | RQ-5 | Three builds on `nq-100k` and `nq-1m`, five seeds: erasure on; erasure off (encryption kept, no rotation, no key erase); a soft-delete test build (marks instead of excision) | Insert and delete latency p50/p99; throughput; bytes written and `fsync`s per operation; proof time; certificate size; resident memory | Descriptive, 95 % bootstrap CIs |
| **EX-8** | G7 | Load `nq-1m`, then restart | Resident memory against the spec Appendix A budget; recovery time; disk use including certificates | Descriptive |

**EX-4 attack list** (every one must be rejected): a forged proof; a proof copied from another
certificate; a substituted `C_t`; each single-field tamper (tags 1–13 and the trailer); a certificate
under an unknown operator epoch; an insert leaf from another collection; a wrong inclusion path; a log
checkpoint signed by the wrong key; three instead of four cosignatures; cosignatures over a different log
checkpoint; a non-canonical point or scalar; the identity as `C_t`; a holding-area certificate with
arithmetic fields; `group_emptied_by_this_deletion` inconsistent with `C_S_post`; `database_lsn` not after
the insert leaf; a malformed TLV (missing, repeated or reordered tag; trailing bytes).

**Statistics** (§3.4). One confirmatory test: Welch's t-test on per-seed drift, SEVER-DB against
soft-delete, n = 5 each, α = 0.005, two-sided [R53]. TOST at Δ = 0.005 is reported with the recorded
expectation that it will fail to establish equivalence at n = 5 [R54]. Everything else is descriptive:
means with 95 % percentile-bootstrap intervals (10,000 resamples, resampling seeds), no p-values and no
significance language.

---

## 12. Experiment configuration

`configs/experiments.yaml`, committed in P0 as part of the pre-registration and never changed afterwards.
Engine and partition settings are in spec §18.

```yaml
format_version: "exp-1.0"
seeds: [42, 123, 777, 2024, 9999]
sub_seed: "first8(sha256(u64be(seed) || label))"
labels: [kmeans, stream, cohort-order]
corpus_seed: {seed: 42, label: corpus}

datasets:
  reference: {name: allenai/sciq, splits: [train, validation, test], text: support_else_question,
              licence: CC-BY-NC-3.0, revision: PIN_IN_P0}
  live_corpus: {name: BeIR/nq, text: "title + ' ' + text", id: _id,
                licence: CC-BY-SA-3.0, revision: PIN_IN_P0}
  live_queries: {name: BeIR/nq-qrels, split: test, queries: 3452, judgements: 4201}
encoder: {name: sentence-transformers/all-MiniLM-L6-v2, revision: PIN_IN_P0,
          max_tokens: 256, truncate: true, normalise: true, device: cpu, dtype: float32}
corpora:
  nq-100k: {size: 100000, keep_all_judged: true}
  nq-1m:   {size: 1000000, keep_all_judged: true}
non_overlap_checks: [id, sha256_normalised_text]

cohorts: {by: title}
deletion_rungs: [0.10, 0.25, 0.50, 0.75, 0.90]
stream_fractions: [0.25, 0.50, 0.75, 1.00]
arms: [sever_db, frozen_only, soft_delete_ivf, rebuild_ivf]
baseline_ivf: {library: faiss-cpu, index: IndexIVFFlat, nlist: match_sever_total_groups,
               nprobe: ceil_25_percent, training: kmeans_on_streamed_corpus}

metrics:
  recall_k: [10, 100]
  ground_truth: brute_force_original_float32
  exclude_holding_area: true
  ndcg_at: 10
  drift_statistic: stddev_recall10_across_rungs
  ddof_primary: 0
  ddof_also_reported: 1
  balance: coefficient_of_variation_by_population   # frozen, spawned separately

targets:
  T1_crash_violations: 0
  T2_forensic_findings: 0
  T3_engine_vs_reference_mismatches: 0
  T4_honest_accept: 1.0
  T4_attack_accept: 0.0
  T5_max_drift_stddev_per_seed: 0.005
  T6_min_quantised_recall10: 0.999

statistics:
  confirmatory_test: {name: welch_t, alpha: 0.005, sides: 2,
                      compare: [sever_db, soft_delete_ivf], unit: seed}
  equivalence: {name: tost, delta: 0.005, expectation: likely_underpowered_at_n5}
  descriptive: {bootstrap_resamples: 10000, interval: percentile_95, p_values: false}

ex1_crash:
  operations_per_seed: 20000
  passages_used: 10000
  crash_at_every_protocol_step: true
  sampled_wal_writes: 200
  byte_offset_step: 512
  random_crash_points: 1000
ex2_forensic:
  image_size_gb: 16
  filesystem: ext4
  mount: fuse2fs
  scan_free_space: true
  text_window_bytes: 32
ex4_attacks:
  honest_certificates_per_seed: 1000
run_ledger: required
pythonhashseed: 0
```

---

## 13. Engineering practice

### 13.1 Repository

The layout is in spec §19.2. `verifier/` is a separate workspace with its own lockfile and no path
dependencies on the engine; CI fails if it imports anything from `crates/`.

### 13.2 Continuous integration

| Tier | Runs | Contents |
|---|---|---|
| Every commit | Minutes | `fmt`, `clippy -D warnings`, unit tests, bounded property tests, golden vectors, the attack suite, a small crash campaign (one seed, 1,000 operations), `cargo deny`, the Rust 1.85 build, the Python lockfile check |
| Nightly | Hours | The differential test at 10,000 passages on five seeds; a larger crash sample; one hour of fuzzing per parser |
| Weekly | Hours | A forensic scan at 10,000 passages |

CI never fails because a *target* was missed; it fails only on a broken test.

### 13.3 Run ledger and results

- `docs/RUN_LEDGER.md` is append-only and written by the harness, never by hand. Each entry records: date,
  command, code commit, SHA-256 of each configuration file, dataset manifest hash, partition artefact
  hash, seed, platform report (CPU flags, kernel, filesystem, swap state, `allow_unsafe_memory`), outcome,
  and the SHA-256 of the result file.
- `results/` is write-once. A result is never edited; a corrected run is a new entry that names the one it
  replaces.
- A run that cannot write its ledger entry does not start.

### 13.4 Documentation rules

- The specification is normative. A behaviour change is a specification change plus a decision entry, in
  the same commit.
- The limits list (§14) may grow freely; an item leaves it only by a decision entry explaining why.
- Every number in the paper is traceable to a ledger entry.

### 13.5 Release

A tagged release; the partition artefacts, manifests and results archived with a DOI (for example on
Zenodo); per-file data licences (DB-42); an artefact-evaluation package that runs the minimum result on
the reference hardware.

---

## 14. Known limits

Each limit gets one honest sentence in the paper. None is claimed to be harmless; together they are the
declared surface.

**Erasure and storage**

- **L-1 Key-file erasure depends on the device.** Overwriting and `fsync`ing a 512-byte slot is assumed
  to destroy the old group key. Flash translation layers and copy-on-write filesystems may keep old copies
  [R25]; cryptographic erasure is only as good as key sanitisation [R21]. SEVER-DB confines the residue to
  one small file and refuses known copy-on-write filesystems for it. A production system would keep group
  keys in a TPM or HSM.
- **L-2 No erasure guarantee against the operator**, who can copy keys. Certificates cover the
  arithmetic; nothing covers copies.
- **L-3 The index shape persists.** Which groups exist, and spawned centroids (the founding cohort's
  mean), persist after the founders are deleted. Disclosed per certificate.
- **L-4 A deleted ID's existence is testable with `k_scramble`.** Old ciphertext pages keyed by scrambled
  IDs let a holder of `k_scramble` confirm that a *candidate* ID once existed. Content stays unrecoverable,
  and the public log already reveals that some deletion happened.
- **L-5 Visible metadata.** Group counts, commitments, the number of groups, key versions, key-file slot
  order, file sizes and timestamps. A holding-area deletion changes no sum, which distinguishes it from a
  group deletion.
- **L-6 Memory.** The 1.5 GB search mirror is not locked in memory; copies made by the allocator or kernel
  outside SEVER-DB's buffers are not covered by `zeroize`; a memory image taken before acknowledgement is
  out of scope.
- **L-16 A flushed record's `r_t` survives in old ciphertext until the record is deleted.** Its old
  holding-area slot copies stay encrypted under its still-live record key; deleting the record destroys
  that key.
- **L-17 No replication and no backups in v1.** A backup that includes the key file defeats erasure.
- **L-18 The forensic scan is evidence, not proof.** It detects known encodings and formats. The
  argument in spec §13.5 is the reasoning; EX-2 is the test.

**Index and search**

- **L-9 The data must fit in RAM** (about 3.8 GB at 10^6 vectors).
- **L-10 Group balance is not managed**; it is measured and reported separately for frozen and spawned
  groups.
- **L-11 Search results are approximate**, and **slight drift is not detected**: data that drifts only a
  little from the reference set passes the threshold and joins frozen groups.
- **L-12 New out-of-distribution data is not searchable until its group forms.**
- **L-24 Determinism is over input order only.** A different arrival order fills the holding area with a
  different cohort, so a different index shape is expected and is not claimed to match.

**Verification**

- **L-7 The witnesses are simulated.** The tamper-detection mechanism is built and tested; the guarantee it
  would give needs genuinely independent witnesses.
- **L-13 A certificate does not prove that its own deletion leaf was appended.** It cannot contain a proof
  about itself; the auditor checks this with log access.
- **L-14 Verifier trust anchors are fixed at release.** A certificate signed under a later operator epoch
  cannot be checked by an older verifier, and the generator golden file is self-derived (it detects drift;
  correctness rests on the RFC test vectors).
- **L-15 Certificates are large**: about 14.1 KB each, about 12.7 GB at 900,000 deletions; all are kept in
  v1.
- **L-21 No independent cryptographic review.** The soundness argument is the author's own, and the
  verifier, though sharing no code, shares an author. Mitigations: citable constructions only, third-party
  test vectors, a written soundness argument.

**Scope and method**

- **L-8 Platform.** Linux x86-64, ext4 or XFS, AVX2 or scalar; under WSL2 or a VM the host may keep old
  blocks, so experiments run on native Linux.
- **L-19 The reference set is non-commercial** (SciQ, CC BY-NC 3.0).
- **L-20 Statistics.** No distinguisher-based privacy claim; the five-seed design is very likely
  underpowered for equivalence; `ddof = 0` is the more permissive convention (both are reported); one
  confirmatory test, by design.
- **L-22 User data is simulated** with public Wikipedia passages, grouped into people by article title.
- **L-23 Scale and dimension:** tested to 10^6 vectors and 384 dimensions only.
- **L-25 Two properties are argued, not machine-proven**: that creating a spawned group never changes any
  existing group, and the ordering guarantee between log checkpoints.
- **L-26 Side channels** (timing, cache) are out of scope.

---

## 15. Risks

| ID | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R-1 | No independent cryptography reviewer | Certain | Textbook constructions only; RFC-specified primitives; written soundness argument; seek an informal review (§18) |
| R-2 | An engine bug silently corrupts state | Medium | Reference-model differential tests; startup invariant check; crash campaigns; the sabotage list |
| R-3 | Schedule overrun (one person) | High | Minimum publishable cut after P7; the server is optional |
| R-4 | SEVER-DB work delays the earlier SEVER paper | High if unmanaged | Start P0 after that paper is submitted |
| R-5 | Dependency churn (dalek 5, RustCrypto 0.11+) | Medium | One pinned family; lockfiles; one gated migration later |
| R-6 | The encoder is not bit-reproducible across machines | Medium | Embeddings computed once and pinned by hash; reproduction verifies hashes; recorded if recomputation differs |
| R-7 | `fuse2fs` unavailable or unreliable | Low | A Linux VM with loop devices, disclosed as a deviation |
| R-8 | SSD wear from experiments | Medium | Crash campaigns in memory; three-level keys cut deletion writes from about 169 GB to about 20 GB per 90 % rung at 10^6 |
| R-9 | The 16 GB RAM ceiling | Low at 10^6 | Startup budget check; about 3.8 GB resident |
| R-10 | T-5 is missed, as in prior evidence at reduced scale | Medium | Reported as found; the paper's core claims (T-1 to T-4) do not depend on it |

---

## 16. Timeline

| Phase | Weeks | Cumulative | Output |
|---|---|---|---|
| P0 Bootstrap | 2 | 2 | Pinned tools and data; pre-registration commit |
| P1 Partition builder and reference model | 3 | 5 | Artefacts for five seeds; the oracle |
| P2 Cryptography and verifier | 3 | 8 | Primitives, verifier, soundness argument |
| P3 Durable core | 4 | 12 | Crash-safe transactional store |
| P4 Keys and erasure | 3 | 15 | Physical erasure on generic data |
| P5 Index on storage | 4 | 19 | Exact deletion on the new engine |
| P6 Log and certificates | 3 | 22 | Verifiable receipts |
| P7 Search | 3 | **25** | **Minimum publishable result** |
| P8 API and SDK (+ optional server) | 3 (+2–3) | 28 (31) | Usable system |
| P9 Evaluation and paper | 5 | **33 (36)** | Paper and release |

About eight months full time, after the earlier SEVER paper is submitted.

---

## 17. Open items

| ID | Question | Default until decided |
|---|---|---|
| O-1 | What proof-generation latency would justify the asynchronous fallback of DB-25? | Fix a threshold in P2, before measuring |
| O-2 | Is 64 buckets per group right? | Keep 64; justified by the cost arithmetic (spec §13.6) |
| O-3 | Group commit (several transactions per `fsync`)? | Not in v1 |
| O-4 | Native partition fitting inside the engine | Future work |
| O-5 | Migration to the `curve25519-dalek` 5 family | After P9, gated on every golden vector and a verifier migration |
| O-6 | Real, independent witnesses | Future work |
| O-7 | A certificate retention policy | v1 keeps all |
| O-8 | 768 dimensions (all-mpnet-base-v2) | Future work; needs quantisation losslessness, truncation rate and τ re-measured first |
| O-9 | A page cache for data larger than RAM | Future work; the format already allows it |

---

## 18. Recommendations

1. **Finish the earlier SEVER paper first.** Run its full-scale experiment and submit it before P0. Its
   own document still states some figures that its later decisions retired (the "74 % → 98 %" recovery
   and the privacy-trace numbers), and its headline results exist only at a reduced scale; fixing those
   is quick and protects that paper.
2. **Write the reference model before the engine** (P1). It is the cheapest way to find gaps in the
   specification, and it provides most of the correctness evidence.
3. **Timestamp the pre-registration.** Commit §3.4 and `configs/experiments.yaml` in P0 and, ideally,
   also register them publicly (for example on OSF), so the timing is checkable by others.
4. **Build the durable core on generic records first** (P3), before any index code, so each bug has one
   home.
5. **Seek an informal cryptography review** of spec §9 and `SOUNDNESS.md` — for example a university
   cryptography group or a practitioner forum. It is the largest risk (R-1) and is cheap to reduce.
6. **Use native Linux** (dual boot or a spare disk) for EX-2. Under WSL2 or a VM, the host's disk layer
   can keep old blocks, which would make the forensic test unsound.
7. **Keep the server optional.** It adds no research claim.
8. **Aim for a venue with artefact evaluation.** The contribution is systems plus security; a venue that
   checks artefacts rewards exactly this project's reproducibility discipline.
9. **Treat a missed T-5 as a finding, not a failure.** The paper's core claims are exactness under crashes,
   physical erasure and verifiability (T-1 to T-4); stability is an important measurement, not the
   foundation.
10. **Do not reuse the old prototype's code**, only its lessons. That keeps SEVER-DB's claims independent,
    and it keeps the earlier paper reproducible.

---

## 19. Glossary

- **Accumulator** — a group's integer sum `S`, count `n`, commitment `C_S` and blinding total `r_agg`.
- **Blinding value (`r_t`)** — a random scalar inside a record's commitment; generated by the user; also
  the capability to delete.
- **Bucket key** — the middle level of the key hierarchy; 64 per group.
- **Canonical group blob** — the byte encoding of a group that the exactness claim is about.
- **Certificate** — the public receipt for a deletion (spec §11).
- **Cohort** — a simulated person: all passages sharing one Wikipedia article title.
- **Commitment** — a Pedersen commitment: a seal over numbers plus a secret, whose seals can be added and
  subtracted publicly.
- **Cryptographic erasure** — making data unrecoverable by destroying the key that encrypts it.
- **Deletion rung** — one step of the 10/25/50/75/90 % cohort-deletion ladder.
- **Domain (key domain)** — a group or the holding area, together with its group key and bucket keys.
- **Drift** — live data that does not resemble the reference set; measured by Mahalanobis distance.
- **Frozen group** — a group fitted on the reference set, never changed.
- **Ghost** — a deleted record's surviving influence or copy, in summaries or on disk.
- **Group key** — the top of the key hierarchy; the only key that needs physical erasure.
- **Holding area** — where out-of-distribution vectors wait until 200 can form a new group.
- **Log checkpoint** — a signed, witness-cosigned tree head of the transparency log.
- **Mirror** — the float32 copy of live vectors used for search.
- **Proof of knowledge** — the operator's proof that it knows the whole post-deletion state.
- **Reference model** — the slow, obviously correct Python implementation used as the oracle.
- **Rotation** — replacing a domain's keys when a record leaves it.
- **Scrambled ID** — `HMAC-SHA-512(k_scramble, collection_id ‖ record_id)`.
- **Spawned group** — a group created from 200 holding-area vectors, frozen at creation.
- **Spillover** — routing an out-of-distribution vector to the nearest spawned group with room.
- **Storage checkpoint** — a durable image of the engine's state.
- **Witness** — a party that checks log consistency and cosigns log checkpoints.

---

## 20. References

Links checked on 27 September 2026 unless noted.

**Standards and primitives**
- [R1] RFC 2119, *Key words for use in RFCs to Indicate Requirement Levels*. https://www.rfc-editor.org/rfc/rfc2119
- [R2] RFC 9380, *Hashing to Elliptic Curves*. https://www.rfc-editor.org/rfc/rfc9380
- [R3] RFC 9496, *The ristretto255 and decaf448 Groups*. https://www.rfc-editor.org/rfc/rfc9496
- [R4] RFC 9162, *Certificate Transparency Version 2.0*. https://www.rfc-editor.org/rfc/rfc9162
- [R5] RFC 8032, *Edwards-Curve Digital Signature Algorithm (EdDSA)*. https://www.rfc-editor.org/rfc/rfc8032
- [R6] T. P. Pedersen, "Non-interactive and information-theoretic secure verifiable secret sharing", CRYPTO '91. https://doi.org/10.1007/3-540-46766-1_9
- [R7] C. P. Schnorr, "Efficient signature generation by smart cards", *Journal of Cryptology* 4, 1991. https://doi.org/10.1007/BF00196725
- [R8] A. Fiat, A. Shamir, "How to prove yourself", CRYPTO '86. https://doi.org/10.1007/3-540-47721-7_12
- [R9] T. Okamoto, "Provably secure and practical identification schemes and corresponding signature schemes", CRYPTO '92. https://doi.org/10.1007/3-540-48071-4_3
- [R10] J. Camenisch, M. Stadler, "Proof systems for general statements about discrete logarithms", ETH Zürich Technical Report 260, 1997. https://crypto.ethz.ch/publications/CamSta97b.html
- [R11] Merlin transcripts. https://merlin.cool
- [R12] STROBE protocol framework. https://strobe.sourceforge.io
- [R13] *Deterministic nonce-based signatures with noise*, IRTF CFRG draft. https://datatracker.ietf.org/doc/draft-irtf-cfrg-det-sigs-with-noise/
- [R14] RFC 6979, *Deterministic Usage of DSA and ECDSA*. https://www.rfc-editor.org/rfc/rfc6979
- [R15] The Ristretto group. https://ristretto.group
- [R16] curve25519-dalek. https://github.com/dalek-cryptography/curve25519-dalek
- [R17] O. Ledoit, M. Wolf, "A well-conditioned estimator for large-dimensional covariance matrices", *Journal of Multivariate Analysis* 88(2), 2004. https://doi.org/10.1016/S0047-259X(03)00096-4
- [R18] XChaCha20-Poly1305, IRTF CFRG draft (expired; the rejected option of DB-31). https://datatracker.ietf.org/doc/draft-irtf-cfrg-xchacha/
- [R19] RFC 8452, *AES-GCM-SIV: Nonce Misuse-Resistant Authenticated Encryption*. https://www.rfc-editor.org/rfc/rfc8452
- [R20] RFC 2104, *HMAC: Keyed-Hashing for Message Authentication*. https://www.rfc-editor.org/rfc/rfc2104
- [R52] FIPS 180-4, *Secure Hash Standard*. https://doi.org/10.6028/NIST.FIPS.180-4

**Secure and verifiable deletion**
- [R21] NIST SP 800-88 Rev. 2, *Guidelines for Media Sanitization*, final 26 September 2025. https://csrc.nist.gov/pubs/sp/800/88/r2/final — https://doi.org/10.6028/NIST.SP.800-88r2
- [R22] D. Boneh, R. Lipton, "A revocable backup system", 6th USENIX Security Symposium, 1996. https://www.usenix.org/conference/6th-usenix-security-symposium/revocable-backup-system
- [R23] J. Reardon, D. Basin, S. Čapkun, "SoK: Secure Data Deletion", IEEE S&P 2013. https://doi.org/10.1109/SP.2013.28
- [R24] J. Reardon, H. Ritzdorf, D. Basin, S. Čapkun, "Secure data deletion from persistent media", ACM CCS 2013. https://doi.org/10.1145/2508859.2516699
- [R25] M. Wei, L. Grupp, F. Spada, S. Swanson, "Reliably erasing data from flash-based solid state drives", USENIX FAST 2011. https://www.usenix.org/conference/fast11/reliably-erasing-data-flash-based-solid-state-drives
- [R26] F. Hao, D. Clarke, A. F. Zorzo, "Deleting secret data with public verifiability". https://eprint.iacr.org/2014/364
- [R27] S. Garg, S. Goldwasser, P. N. Vasudevan, "Formalizing data deletion in the context of the right to be forgotten", EUROCRYPT 2020. https://eprint.iacr.org/2020/254 — https://doi.org/10.1007/978-3-030-45724-2_13
- [R28] M. Naor, V. Teague, "Anti-persistence: history independent data structures", STOC 2001. https://doi.org/10.1145/380752.380844
- [R51] L. Bourtoule et al., "Machine Unlearning", IEEE S&P 2021. https://arxiv.org/abs/1912.03817

**Storage engines and durability**
- [R29] T. S. Pillai et al., "All file systems are not created equal", USENIX OSDI 2014. https://www.usenix.org/conference/osdi14/technical-sessions/presentation/pillai
- [R30] PostgreSQL wiki, "Fsync Errors". https://wiki.postgresql.org/wiki/Fsync_Errors
- [R31] A. Rebello et al., "Can applications recover from fsync failures?", USENIX ATC 2020. https://www.usenix.org/conference/atc20/presentation/rebello
- [R32] C. Mohan et al., "ARIES", *ACM TODS* 17(1), 1992. https://doi.org/10.1145/128765.128770
- [R33] J. Hellerstein, M. Stonebraker, J. Hamilton, "Architecture of a Database System", 2007. https://doi.org/10.1561/1900000002
- [R34] SQLite: atomic commit https://www.sqlite.org/atomiccommit.html ; file format https://www.sqlite.org/fileformat.html ; testing https://www.sqlite.org/testing.html
- [R40] LMDB documentation. http://www.lmdb.tech/doc/
- [R41] CMU 15-445/645 Database Systems. https://15445.courses.cs.cmu.edu/
- [R42] A. Petrov, *Database Internals*, O'Reilly, 2019. ISBN 978-1-492-04034-7

**Vector search**
- [R35] Y. Malkov, D. Yashunin, "Efficient and robust approximate nearest neighbor search using HNSW graphs". https://arxiv.org/abs/1603.09320
- [R36] H. Jégou, M. Douze, C. Schmid, "Product quantization for nearest neighbor search", *IEEE TPAMI* 33(1), 2011. https://doi.org/10.1109/TPAMI.2010.57
- [R37] M. Douze et al., "The Faiss library". https://arxiv.org/abs/2401.08281
- [R38] A. Singh et al., "FreshDiskANN". https://arxiv.org/abs/2105.09613
- [R39] M. Aumüller, E. Bernhardsson, A. Faithfull, "ANN-Benchmarks", *Information Systems* 87, 2020. https://doi.org/10.1016/j.is.2019.02.006

**Data and models**
- [R43] T. Kwiatkowski et al., "Natural Questions", *TACL* 2019. https://doi.org/10.1162/tacl_a_00276
- [R44] N. Thakur et al., "BEIR". https://arxiv.org/abs/2104.08663 ; data: https://huggingface.co/datasets/BeIR/nq , https://huggingface.co/datasets/BeIR/nq-qrels
- [R45] J. Welbl, N. F. Liu, M. Gardner, "Crowdsourcing multiple choice science questions" (SciQ). https://arxiv.org/abs/1707.06209 ; data: https://huggingface.co/datasets/allenai/sciq
- [R46] N. Reimers, I. Gurevych, "Sentence-BERT". https://arxiv.org/abs/1908.10084 ; model: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2

**Statistics**
- [R53] B. L. Welch, "The generalization of 'Student's' problem when several different population variances are involved", *Biometrika* 34, 1947. https://doi.org/10.1093/biomet/34.1-2.28
- [R54] D. J. Schuirmann, "A comparison of the two one-sided tests procedure and the power approach for assessing the equivalence of average bioavailability", *Journal of Pharmacokinetics and Biopharmaceutics* 15, 1987. https://doi.org/10.1007/BF01068419

**Tooling and platform (versions checked 27 September 2026)**
- [R47] crates.io: https://crates.io/crates/curve25519-dalek , https://crates.io/crates/ed25519-dalek , https://crates.io/crates/merlin , https://crates.io/crates/aes-gcm-siv , https://crates.io/crates/zeroize , https://crates.io/crates/pyo3 , https://crates.io/crates/sha2 , https://crates.io/crates/hmac , https://crates.io/crates/crc32c
- [R55] PyPI: https://pypi.org/project/numpy/ , https://pypi.org/project/scikit-learn/ , https://pypi.org/project/sentence-transformers/ , https://pypi.org/project/torch/ , https://pypi.org/project/datasets/ , https://pypi.org/project/pyarrow/ , https://pypi.org/project/maturin/ , https://pypi.org/project/faiss-cpu/
- [R48] Rust release channels: https://releases.rs/ ; Rust 2024 edition guide: https://doc.rust-lang.org/edition-guide/rust-2024/index.html
- [R49] Intel Core Ultra 200V series datasheet, instruction-set extensions (the page may require an Intel account). https://edc.intel.com/content/www/us/en/secure/design/confidential/products/platforms/details/lunar-lake-mx/core-ultra-200v-series-processors-datasheet-volume-1-of-2/intel-advanced-vector-extensions-2-intel-avx2/
- [R50] e2fsprogs (includes `fuse2fs`). https://e2fsprogs.sourceforge.net/
