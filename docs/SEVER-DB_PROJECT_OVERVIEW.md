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
6. [Decision register (DB-1 … DB-53, DB-55 … DB-92)](#6-decision-register-db-1--db-53-db-55--db-92)
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
- [Changelog](#changelog)

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
And nobody outside the company can check even the accounting of a deletion: that the record's numbers
really left the summaries.

SEVER-DB changes what an outsider can check, and it is precise about the limits. Anyone can check a
deletion's **accounting** from its certificate. **Erasure** is guaranteed against anyone who later
obtains the disks, not against the operator, who runs the service and holds its keys.

> **What SEVER-DB proves, and what it does not**
>
> **Proves:** the record was inserted under the account's key in a signed, witnessed log; the group's
> accounting moved by exactly that record; after deletion, anyone who later obtains the disks cannot
> recover the record, its `r_t`, or two accumulator versions straddling the deletion.
>
> **Does not prove:** that the operator kept no copy (no cryptography can); that the user personally
> authorised the deletion (DB-55, L-2, L-27).

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
subtraction on the blinding totals gives back the record's blinding value (`r_agg_pre − r_agg_post = r_t`).
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
- Cryptographic user control over deletion. The application backend holds every account's signing key,
  and the engine holds every `r_t`; deletion is authorised by the service's account check (DB-55, L-27).
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
  passage text, the record's blinding value, or a pair of accumulator versions from which they follow by
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
- A certificate does not prove that the operator kept no copy (no cryptography can), nor that the user
  personally authorised the deletion: the service holds the account keys and decides who may delete
  (L-2, L-27).
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
| **Dishonest operator** | Controls memory, disk and network, and runs the application backend, so it holds every account's signing key and every `r_t`; may fabricate state, rewrite history, or reuse proofs | Public certificates: the commitment transition check, the proof of knowledge bound to the deletion's full context, and witnessed log checkpoints. The insert signature only records that the service acted for an authenticated account; it does not constrain the operator (L-27). **Physical erasure is not a defence against the operator** |
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
6. The operator runs the application backend, which authenticates the account before every insert and
   every deletion. SEVER-DB does not check this (DB-55, L-27).

### 4.3 Out of scope

Timing and cache side channels; hardware attacks; a compromised kernel; SSD firmware; the encoder
model; availability (an operator can always refuse service); account authentication between the user
app and the application backend.

---

## 5. The design in plain words

**Who does what.** Three parties take part (spec §3.3). The **user app** is thin: it sends text and
signs in to the user's account. The **application backend** (the AI server) embeds the text with the
exact encoder pinned in the partition artefact, prepares each insert (quantises, draws `r_t`, computes
and signs `C_t`) and calls the engine; it keeps every account's signing key in its own key store. The
**engine**, SEVER-DB itself, checks and stores records, keeps the sums, writes the log, deletes, and
issues certificates.

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
random value `r_t` that the application backend draws. The engine stores `r_t` with the record,
encrypted under the record's key, so it is erased with the record. The backend signs `C_t` at insert
with the account's key, and the signature and the account's public key go into a public, append-only
Merkle log, cosigned by witnesses. The signature records that the service acted for an authenticated
account; it is not the user's own consent, because the service holds the key (L-27). Deletion is
authorised the same way: the backend checks the account, then calls `delete`. On deletion, the group's commitment drops by exactly `C_t`, and the operator
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
user app ─text─► backend: authenticate account, embed, prepare_insert (quantise, draw r_t, sign C_t)
insert ─► check & quantise ─► route ──► frozen group ─┐
                                 ├────► spawned group ─┼─► encrypt (with r_t), update sums & commitment,
                                 └────► holding area ──┘   log the insert, commit
                                          (200 ⇒ new spawned group)

user app ─request─► backend: authenticate account ─► delete(collection_id, record_id)
delete ─► find ─► check stored x̃ and r_t reproduce C_t (integrity) ─► subtract ─► prove ─► certificate
        ─► new key (phase A) ─► commit (phase B) ─► wipe memory ─► erase old key (phase C) ─► acknowledge
```

---

## 6. Decision register (DB-1 … DB-53, DB-55 … DB-105)

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
the application backend commits to `x̃`.

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

**Superseded by DB-55 (2 October 2026).** The application backend now draws `r_t`, the engine stores
it for every record, and deletion is authorised by the backend's account check.

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

**Rationale qualified by DB-55 (2 October 2026).** The operator now holds every account's key, so a
published user key records which account the service acted for; it no longer stops a dishonest
operator (L-27).

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

**Rationale qualified by DB-55 (2 October 2026).** "User authorisation" now means that the insert was
signed under the account's key by the service acting for an authenticated account; it is not the
user's own consent to the deletion (L-27). The certificate format is unchanged.

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

### 6.8 Amendments

DB-44 … DB-54 are reserved for the amendments proposed in the build plans (Build §3.5, Build 3-4 §3.5)
and are recorded here once accepted. DB-44, DB-45, DB-47, DB-49 and DB-50 were accepted on 4 October
2026, DB-46 and DB-48 on 7 October 2026 (Part 2's design review), and DB-51, DB-52 and the EP-10
half of DB-53 on 15 October 2026 (Part 3's design review), and the EP-11 half of DB-53 and DB-54 on
18 October 2026 (Part 4, the owner: "choose the option which is best for long term and short term").

#### DB-44 — Build in four frozen parts; erasure after certificates (4 October 2026)

**Decision.** SEVER-DB is built in four parts, each adding exactly one claim: Part 1 The Idea, Part 2
The Database, Part 3 The Receipt, Part 4 The Erasure (Build §0.1). When a part passes its exit gate,
every file it owns is hashed into `freeze/PART-N.sha256` and the commit is tagged `part-N-frozen`; CI
fails on any change to a frozen file; later parts change behaviour only through the extension points
an earlier part declared; a defect in a frozen part is fixed only through an erratum (Build §0.3,
F-1 … F-6). Erasure (phase P4) is built after certificates (phase P6). **Why.** Each part depends only
on the parts before it. Encryption is the outermost wrapper, so building it last means it encrypts
whatever bytes Parts 1–3 define without changing their formats. Freezing turns each finished part's
suite into a permanent regression suite. **Rejected.** Building in phase order P0–P9 (keys before
certificates would force the certificate work to change sealed formats); no freezing (nothing would
stop a later change from silently breaking an earlier claim). **Consequence.** The phases of §8 are
grouped into parts as in Build §0.2; spec Appendix B vectors are generated by the part that owns them
(Build 3-4 §3.4); errata are recorded in `ERRATA.md`.

#### DB-45 — Plan, then apply; extension points; the WAL `EXTENSION` record (4 October 2026)

**Decision.** Every mutation of the index is computed by a pure `plan` step that returns a
`ChangeSet` (EP-3), then installed by an `apply` step that cannot fail; all validation happens in
`plan`. Extension points EP-1 … EP-9 (Build §3.3) are declared by the part that owns the code they
extend, each with a default implementation and a contract suite. The WAL gains an `EXTENSION` record
type, `u16be participant_id ‖ bytes`, which the storage engine carries but never interprets (spec
§14.6). **Why.** Part 2 can then log a change before applying it, Part 3 build a certificate from it
and Part 4 rotate keys for it, all without editing frozen code. A `ChangeSet` spanning many groups
makes `delete_user` one atomic unit from Part 1 onward. **Rejected.** Later parts editing the index
directly (breaks the freeze rule); callbacks inside `apply` (`apply` could then fail halfway).
**Consequence.** Before a part freezes, proof spikes show that its extension points can express every
later user (Build §3.4).

#### DB-46 — Slot payload order and the header's `seal_version` (7 October 2026)

**Decision.** The slot payload is `u16be id_len ‖ id padded to 256 ‖ x̃ as d × i32be ‖ extension
record secret`. The commitment extension's record secret is `u64be insert_leaf_index ‖ u8 has_rt ‖
r_t` (41 bytes), so the released payload is still 1,835 bytes and the slot still 1,992 bytes. In the
group header, `C_S` is the extension's public state and `r_agg` (inside the sealed accumulator) its
secret state; the field `group_key_version` becomes `seal_version`, maintained by the storage sealer
(EP-6), which under AES-GCM-SIV is the group key version: the same bytes in the released system (spec
§14.3–§14.4). **Why.** Part 2 stores slots and headers before commitments exist. With the extension's
bytes at the end of the payload and in named extension fields, Part 2's codec writes the core fields
and appends whatever the extension supplies, and Part 3 adds `r_t` without editing a frozen format.
**Rejected.** Keeping the old order (Part 2 would have to reserve Part 3's 41 bytes in the middle of
the payload, with no meaning in Part 2); a separate per-record extension file (one more file to keep
consistent across a crash). **Consequence.** Part 2's sizes at `d = 384` are a 1,794-byte payload, a
1,864-byte slot and a 6,193-byte header (spec Appendix A). Every released size is unchanged.

#### DB-47 — The canonical blob's extension region and magic (4 October 2026)

**Decision.** The canonical group blob (spec §5.5) has an extension region between `S` and
`member_count`, and its 6-byte magic is chosen by the group extension (EP-1). With no extension
(Part 1) the magic is `SEVERC` and the region is empty. With the commitment extension (Part 3) the
magic is `SEVERG` and the region is `C_S ‖ r_agg`, byte-identical to spec §5.5. **Why.** Part 1 has no
commitments, yet its exactness claim needs a canonical blob. A distinct magic stops a core blob ever
being compared with a full blob by mistake. **Rejected.** Zero-filled `C_S` and `r_agg` in Part 1 (32
zero bytes is the identity encoding, a real value meaning "empty group", so the blob would make a
false statement). **Consequence.** Golden vector 8 exists in two forms: `SEVERC` (Part 1) and `SEVERG`
(Part 3). Part 1's equivalence helper compares the core fields (`S`, `n`, blob, member IDs); `C_S`
joins in Part 3.

#### DB-48 — A sealer marker in every file; no confidentiality before Part 4 (7 October 2026)

**Decision.** Every file in the data directory records the `u16be sealer_id` it was written with,
right after its format version: `0` for `PlaintextSealer`, `1` for AES-256-GCM-SIV (spec §14). A build
refuses to open a file written with another sealer (`IntegrityViolation`, naming the check). Parts 2
and 3 store plaintext through `PlaintextSealer` and make **no** confidentiality claim; the
ciphertext-only rule (INV-11, spec §13.2) applies from Part 4. **Why.** Encryption is built last
(DB-44), yet Parts 2 and 3 need a working database. The marker makes the difference explicit on disk,
so a plaintext database can never be mistaken for, or silently opened as, an encrypted one, and the
reverse. **Rejected.** Encrypting from Part 2 (pulls Part 4's key hierarchy forward and breaks the
one-claim-per-part order); no marker (a Part 2 database opened by the released build would be read as
corrupt ciphertext, or worse, accepted). **Consequence.** The key file `KEYS` exists only with
sealer `1`; `SECRETS` exists in every database (DB-68). Part 2 and Part 3 demos and reports say "plaintext database" wherever they show stored bytes.

#### DB-49 — Runtime dimension and group count (4 October 2026)

**Decision.** The code accepts any dimension `d` that is a multiple of 8 and any number of frozen
groups ≥ 1. The v1 configuration fixes `d = 384` and 128 frozen groups (spec §2.2). **Why.** Small
fixtures (for example `d = 16` and 4 frozen groups, Build §2.7) let state-machine tests reach flushes,
spillover and empty groups quickly. **Rejected.** Compile-time constants (fast tests would need a
second build of every crate). **Consequence.** Every size in spec Appendix A and every byte-exact
golden vector is for the v1 configuration. The multiple-of-8 rule is spec §8.2's kernel requirement.
The spawn target size is a runtime value too (DB-62); frozen groups are at most 10,000 (DB-63).

#### DB-50 — One `SecretMemory` provider, installed once at startup (4 October 2026)

**Decision.** Where secret buffers live is decided by one `SecretMemory` provider (EP-4), installed
exactly once, by the composition root, at startup. It is the only global state in the code. Part 1's
default keeps secrets on the heap and zeroes them on drop; Part 4 installs a provider that uses
`mlock`ed pages (spec §12.8). **Why.** Every secret type must allocate from the same place without a
provider argument threading through every frozen API, and Part 4 must be able to lock keys in memory
without editing Part 1. **Rejected.** Passing a provider through every API (it would leak into frozen
signatures); a global that can be replaced later (one secret could then straddle two providers).
**Consequence.** A second installation attempt is an error. Tests use a provider that checks every
released buffer is all zero (Build 3-4 §2.8).

#### DB-51 — A pure-Python ristretto255 in the certificate model (15 October 2026)

**Decision.** The certificate reference model `sever_refmodel_certs` (C-18's Part 3 package) uses its
own small pure-Python ristretto255 and `expand_message_xmd` (SHA-512), written from RFC 9496 and
RFC 9380 and checked against those RFCs' test vectors, never a binding to the engine's crypto crate.
It is slow (a 385-term commitment takes a fraction of a second), so it runs the small and medium
streams; the large differential runs (P3-T5 on `nq-100k`, five seeds) compute the curve operations
through the engine's Python binding, while the model's state tracking (`S`, `n`, `r_agg`, the
transition `C_S_post + C_t = C_S_pre`) stays its own at every scale (Build 3-4 §1.6). **Why.** A
shared misreading of the spec in the curve code would otherwise pass both sides; the RFC vectors give
the model's primitives an oracle independent of this project. **Rejected.** A binding to
`sever-crypto` everywhere (the model would inherit the engine's crypto bugs); libsodium through PyNaCl
for the large runs (one more dependency for little gain: primitive errors already show on the small
streams); pure Python at every scale (days of CPU per gate run). **Consequence.** Closes G-3: spec
§19.1 C-18 no longer depends on C-7. In the large runs the curve arithmetic is checked only against
the engine (oracle D for that part), so the small and medium streams carry the primitive checks.

#### DB-52 — `expand_message_xmd` is implemented by the project (15 October 2026)

**Decision.** `curve25519-dalek 4.1.3` provides the RFC 9496 one-way map
(`RistrettoPoint::from_uniform_bytes`) but not RFC 9380's `expand_message_xmd` (checked in the crate
source on 15 October 2026). `sever-crypto` implements `expand_message_xmd` with SHA-512 (RFC 9380
§5.3.1, about 60 lines), checked against the RFC 9380 Appendix K.3 vectors; the verifier implements
it again from the RFC with its own code (Build 3-4 §1.6). **Why.** §9.2's generators need it, and the
construction is short, fully specified and has published test vectors. **Rejected.** A crate that
provides it (for example `elliptic-curve`'s `hash2curve`): a large new dependency tree in both
workspaces for 60 lines of code, and more for the §20.3 duplicate-crate check to cover.
**Consequence.** Spec §9.1's "no primitive is implemented by this project" names this one exception;
§9.2's startup self-check takes the `expand_message_xmd` known answers from RFC 9380 Appendix K.3
(RFC 9496 has vectors only for the one-way map).

#### DB-53 — EP-10 `Witness` (15 October 2026) and EP-11 `PlatformProbe` (18 October 2026)

**Decision.** Part 3 declares extension point EP-10 `Witness`: a witness receives a new log
checkpoint and the consistency proof from the last checkpoint it cosigned, and cosigns only if the
proof verifies (spec §10.4). The default is `SimulatedWitness`, five instances with threshold four.
It has a contract suite that passes for `SimulatedWitness` and fails for a witness that skips the
consistency check (P3-T12, Build 3-4 §1.5). The proposal's other half, EP-11 `PlatformProbe`
(Build 3-4 §2.4), is decided at Part 4's design review. **Why.** Independent witnesses (overview
O-6, limit L-7) can then be added later without editing frozen Part 3 code. **Rejected.** Witnesses
built into `sever-log` with no extension point (adding a real witness would need an erratum);
accepting EP-11 now (its design belongs to Part 4 and cannot be checked yet). **Consequence.** v1's
witnesses are simulated, so the witness guarantee stays a limit (L-7).

**EP-11, accepted 18 October 2026 (Part 4).** Part 4 declares EP-11 `PlatformProbe`: the filesystem
type of a directory, the no-copy-on-write attribute of a file, the active swap devices with their
device-mapper UUIDs, the hibernation state (`/sys/power/state`, `/sys/power/resume`) and whether
memory can be locked. The default `LinuxProbe` reads `/proc`, `/sys` and `statfs`; every refusal rule
of §12.8–12.9 (as fixed by DB-90) is a pure function of the probe's answers, so the P4-T8 matrix runs
with a fake probe, without root and without reconfiguring the machine. A contract suite checks that
`LinuxProbe` answers on the test machine and that the rules refuse exactly the register's unsafe
rows. **Why.** The refusals cannot otherwise be tested on one machine (this one has unencrypted swap
and hibernation listed). **Rejected.** Testing on real misconfigured machines only (not
reproducible); checks hard-wired into `sever-platform` (no fake possible).

#### DB-54 — The evaluation's build variants (18 October 2026)

**Decision.** The evaluation uses four builds, all composition roots or feature flags inside Part 4,
none editing a frozen part (Build 3-4 §2.7): `sever-db` (the measured build); `sever-db` with feature
`key-export` (writes each generated key to a sink outside the disk image, for the forensic scanner
only; an architecture test shows the feature touches exactly one function and is absent from the
measured binary); `sever-db-noerase` (`AeadSealer` with a static key per domain and no key-rotation
participant, the cost of erasure, EX-7); `sever-softdelete` (a tombstone over the Part 2 API, the cost
of excision and receipts, EX-7); plus one `sabotage-SB-N` build per sabotage item. **Why.** EX-2
needs the retired keys to look for, and EX-7 needs arms that differ from the measured build in one
mechanism each. **Rejected.** Exporting keys from the measured build (a leak by construction);
variants as forks of the code (they would drift). **Consequence.** Every number in the report names
the build that produced it.

#### DB-61 — The ULP sentence of §4.1 (6 October 2026)

**Decision.** Spec §4.1's explanatory sentence says correctly normalised data lands "within about
2 ULPs of 1.0 (the worst P0 row is 1.54 ULPs)", not "within 1 ULP". **Why.** The P0 data measured
1.54 ULPs (`meta.json`, NQ 1M). **Rejected.** Leaving a sentence the project's own data contradicts.
**Consequence.** Closes G-9. The 8-ULP tolerance (the rule) is unchanged.

#### DB-62 — Spawn target size is a runtime value (6 October 2026)

**Decision.** The spawn target size is a configuration value ≥ 1, like `d` and the frozen-group
count (DB-49). v1 fixes 200 (spec §2.2); the small fixtures use 8 (Build §2.7). **Why.** State-machine
and stream tests at `d = 16` need many flushes; at 200 they would need tens of thousands of
operations per flush. **Rejected.** Testing flushes only at 200 (the L4 and L5 suites would rarely
reach a second flush). **Consequence.** Closes G-10. `IndexConfig::spawn_target` (default 200);
0 is refused. The `nq-*` runs and every golden vector use 200.

#### DB-63 — At most 10,000 frozen groups (6 October 2026)

**Decision.** A collection has at most 10,000 frozen groups; an artefact with a larger `k_frozen` is
rejected. **Why.** `frozen-NNNN` has four digits, so labels stop at 9999, while `k_frozen` is a
`u16be`. **Rejected.** A wider ID form (it changes the 32-byte group-ID bound's examples and the
golden vectors for no v1 benefit). **Consequence.** Closes G-11. Spec §2.2 and §5.1 state the limit;
`sever-partition` and `sever-types` already enforce it. v1 uses 128.

#### DB-64 — The error for a bad artefact (6 October 2026)

**Decision.** A failed §6.3 check is rejected with `IntegrityViolation`, naming the check (for
example `"§6.3 artefact d"`), never a value. **Why.** §6.3 required the checks but §17 had no error
for them. **Rejected.** A new §17 row `InvalidArtefact` (one more variant with no different handling:
a bad artefact stops collection creation either way). **Consequence.** Closes G-12; matches the code
written in Part 1.

#### DB-65 — Directory operations in the `Vfs` (7 October 2026)

**Decision.** The `Vfs` trait (spec §12.2, EP-5) also has `create_dir` and `remove_dir`. **Why.** A
storage checkpoint is written into a new directory, renamed into place and later deleted (spec
§15.6), so the storage engine must create and remove directories, and every file operation must go
through the `Vfs` so that `SimVfs` can crash it. **Rejected.** Creating the directories outside the
trait (a crash test could then never lose a directory entry); fixed, reused checkpoint directories
(loses the atomic directory rename that makes an interrupted checkpoint harmless). **Consequence.**
Closes G-13. In `SimVfs` a new directory is durable only after `fsync_dir` of its parent, like a file.

#### DB-66 — WAL record framing and payloads (7 October 2026)

**Decision.** In a WAL record (spec §14.6) `len` is the length of the whole record and the CRC covers
every byte before it. Every payload that changes a collection starts with its `collection_id`;
unspecified widths are `u64be`; the type codes are fixed (1–17). Two record types are added,
`COLLECTION_CREATE` (metadata and the partition artefact) and `COLLECTION_DROP`. `COUNTERS` carries
`N` and `k`; the next `database_lsn` is carried by the log participant's own records (Part 3). The
payloads of `BUCKET_BLOCK`, `LOG_LEAF`, `LOG_CHECKPOINT`, `CERT_REF` and `EXTENSION` are carried
verbatim. **Why.** One WAL serves every collection, so a change must name its collection; a reader
must know the record length before it can check the CRC; Part 2 must create collections durably
before the log exists. **Rejected.** One WAL per collection (cross-collection operations and
checkpoints would need two commit points); `len` excluding the framing (one more arithmetic step to
get wrong, for no gain). **Consequence.** Closes G-14.

#### DB-67 — File layouts and paged checkpoint files (7 October 2026)

**Decision.** Spec §14.9 fixes the byte layout of the store file header, `MANIFEST`, WAL segment
headers, `SECRETS`, the collection metadata and every storage checkpoint file. Every checkpoint file
is paged (§14.2): a header page with magic, version, `sealer_id` and stream length, then data pages,
each carrying the covered `wal_seq` and a CRC. A new checkpoint file `payloads.bin` holds the
passage-text references. **Why.** §12.7 requires a magic, version and CRC everywhere, and a format
claim needs bytes. Paging puts every checkpoint byte under a CRC and stops a page from another
checkpoint being mixed in. **Rejected.** Unpaged checkpoint files with one CRC per file (a single
bit flip in a 2 GB file would only be found after reading all of it, and the error could not say
where). **Consequence.** Closes G-15.

#### DB-68 — `SECRETS` exists in every database (7 October 2026)

**Decision.** `<key_dir>/SECRETS`, holding `k_scramble` (spec §9.7), exists in every database,
plaintext or not; only the key file `KEYS` is tied to the AES-GCM-SIV sealer (correcting DB-48's
wording). **Why.** Scrambled IDs are computed in every part, so every database needs its scrambling
key after a restart. **Rejected.** Storing `k_scramble` in the data directory (it would then sit
next to the data it scrambles, against §14.1's separation). **Consequence.** Closes G-16.

#### DB-69 — Each part's demo is its own binary (7 October 2026)

**Decision.** Part 2's demo is `sever-demo-p2 durable`; Parts 3 and 4 ship `sever-demo-p3` and
`sever-demo-p4` the same way. **Why.** `sever-demo` belongs to Part 1's frozen crate, and a frozen
part never gains features (F-3). **Rejected.** Editing `sever-p1` (breaks the freeze); one binary in
a later crate with the same name (two crates in one workspace cannot both produce `sever-demo`).
**Consequence.** Closes G-17; Build §5.9 and CLAUDE.md §6.1 name the new binary.

#### DB-105 — Every §13.2 associated data carries the zero-padded group ID (22 October 2026)

**Decision.** In spec §13.2, the wrapped bucket key's and `S ‖ r_agg`'s associated data name
`group_id(32, zero-padded)`, as the wrapped record key's already did: the group's §5.1 label
zero-padded to 32 bytes, as stored in §14.3. Closes G-2.
**Why.** The table gave the width in one row of three and left the other two open, so an
independent implementation could encode them differently and fail to open the engine's
ciphertexts. `sever-seal` (`ad.rs`, through `sever_keys::Domain`, whose `group_id` is `[u8; 32]`)
already pads it in all three rows, as do the `BUCKET_BLOCK` WAL record (§14.6) and the
wrapped-key store (§14.8).
**Rejected.** The bare label (variable length): the AD would then need a length prefix to stay
unambiguous, and every other place that stores a group ID beside a key uses the padded form.
**Consequence.** No code or stored byte changes; `sever-seal`'s module comment shows the width.

#### DB-104 — P4-T3 closes and reopens after every recovery (21 October 2026)

**Decision.** After each crash point's recovery, P4-T3's campaign also takes a copy of the
recovered disks, closes the engine on it cleanly (a storage checkpoint, which deletes the WAL
segments it covers) and opens it again; the state must be the recovered one. A refusal or another
state counts in a new zero-gated field, `reopen_mismatches` (`sever-crashkit-p4`,
`sever_testkit_p4.gates.ZERO`, `scripts/ops/p4-interim.sh`). The gate's thresholds are unchanged;
the procedure gains one check before the gate's first run on the final build.
**Why.** BH-5 (G-43, DB-102): recovery kept the rotated keys' bucket blocks only in memory, and the
next checkpoint deleted the WAL copy, so the second start refused (`INV-14`). The campaign
recovered once per crash point and stopped, so it could not see this. On a 10-operation deletion
window (seed 42, ops 17,000–17,010) the check counts 0 with the fix and more than 0 with the fix
switched off by PR4-E22's patch (command and output in `docs/PROGRESS.md`).
**Rejected.** A separate gate: the campaign already makes every crash point, and the check only
needs one more open. Sampling every n-th point: the BH-5 window is one VFS step per deletion, and a
sample could miss it. Adding it to P3-T4: Part 3's log participant already appends what it
replays, and P3-T4's own result stands; the final build's campaign covers both participants.

#### DB-103 — Part 3 stops serving too; the frozen Part 2 fixes wait for v1.1's erratum (21 October 2026)

**Decision.** (1) Part 3's composition root (`sever-p3`'s `Opened::serve` and `close`, used by its
SDK) takes the same guard as Part 4 (DB-101): no call is served after an `IntegrityViolation`, no
storage checkpoint is written at close after one, and a data directory whose `ENGINE.lock` is no
longer the file the process locked is refused (`§12.9 data directory replaced`). SR-17-8 and
SR-12.9-5 move to Part 3, so Part 4 inherits them. (2) The bug hunt's proposals for the frozen
parts are numbered after E-3 (the v1.1 layout erratum, already planned) and applied together with
it after v1.0, not before: **E-4** (`sever_db_p2` lets a record ID with no UTF-8 encoding raise
`UnicodeEncodeError`, BH-7), **E-5** (the frozen tracer and Part 2's oracle check read
`#[spec(…)]` one line at a time; `sever_db_p2_native.pyi` is in no freeze list, BH-1), **E-6**
(Part 2's builds keep serving after an `IntegrityViolation` and checkpoint at close, G-42). Until
then they are a stated limit (L-28).
**Why.** (1) Part 3 is not frozen yet, so the guard costs one small change with its proofs
(PR3-F06, PR3-F07), and the receipt build is then as safe as the final one. (2) Each erratum
re-freezes Parts 1–2 and re-runs every later exit gate; E-3 does that anyway, and none of E-4 …
E-6 touches the v1 build (`sever-db`), which already has every fix. The bug hunt's report named
its proposals E-2 and E-3, which were taken.
**Rejected.** Three errata now, before the VM run: three re-freezes and gate re-runs for defects
that only the frozen Part 2 builds (its demo, CLI and SDK) can show.

#### DB-102 — The October bug hunt: participant stores keep what recovery replays; every Part 3 and Part 4 requirement traced in the fast tier (21 October 2026)

**Decision.** (1) Recovery makes what a participant replays from the WAL durable in that
participant's own store before the database serves (§15.7 step 3, G-43): the key-rotation
participant appends to the wrapped-key store each replayed value newer than the store's own state,
as the log participant already appended its replayed leaves. (2) The fast tier runs
`spec-trace-p3` and `spec-trace-p4` with `--complete`, and both refuse a `#[spec(…)]` or
`@pytest.mark.spec(…)` split over lines outside frozen files, because the frozen tracer, oracle
check and proofs check read one line at a time (BH-1). (3) Part 4's freeze list owns
`golden/p4_*` (the RFC 8452 vectors), which no part's list held (BH-6).
**Why.** (1) A SIGKILL between a deletion's `COMMIT` and its phase C store append, then a clean
restart, made the database refuse every later startup with `INV-14` and lost the rotated domains'
bucket blocks (BH-5). (2) rustfmt had split the plaintext test's attribute, so Part 4's INV-11 and
§13.2 requirements counted as untraced (64 of 70) while the fast tier passed.
**Rejected.** (1) Keeping the WAL segments a participant still needs at a checkpoint: Part 2's
engine is frozen, and the store write is the participant's own job (the log participant does it).
Re-appending the whole tail on every startup: duplicates grow the store until compaction. (2)
Fixing the frozen tracer: an erratum for Parts 1 and 2 (the owner decides); the wrappers' guard
covers every file that can still change.

#### DB-101 — Two tours on one work directory: errors name their check, the final build stops serving after an integrity violation and refuses a replaced data directory, one session per demo directory (20 October 2026)

**Decision.** (1) An `IntegrityViolation` names the check that failed; a stored leaf that cannot
be read or verified is reported as that failure, not as `§15.3 insert leaf` (G-41, §17).
(2) The final build stops serving after an `IntegrityViolation`: no later call, and no storage
checkpoint at close. Before each call and before its closing checkpoint it also checks that
`data/ENGINE.lock` is still the file it locked, and refuses (`§12.9 data directory replaced`)
otherwise, so it never writes into another database (G-42, §12.9, §17). Both live in Part 4's
composition root (`sever-db`'s `Opened::serve` and `close`, used by the SDK), because Part 2's
engine is frozen. (3) The demo takes a lock beside each work directory, so a second tour or shell
on the same directory is refused before it wipes anything.
**Why.** The 5,000-row engine tour of 20 October failed in chapter 6, and the database then would
not reopen. Two `demo.sh tour` runs had shared one work directory (two windows): the second run's
wipe deleted the first run's open database. The first run kept writing to unlinked files, read
the second run's leaf store by path at its delete, and wrote its closing checkpoint and `MANIFEST`
into the second run's directory. The swallowed read error made this look like an engine bug.
**Rejected.** Changing the error type: §17 already makes it an `IntegrityViolation`. An erratum to
Part 2's engine now: the owner decides (G-42 records it). Locking the directory against deletion:
no POSIX lock does.

#### DB-100 — The second Part 3 bug hunt: the artefact's dimension check, and which part checks the key file's filesystem (20 October 2026)

**Decision.** (1) The roots of Parts 3 and 4 refuse an artefact whose dimension differs from the
database's with `IntegrityViolation` naming the check (`§6.3 artefact d`), as §6.3 and DB-64
require and as Part 2's engine already did; they had raised `WrongDimension`, which §17 keeps for
an input vector (§4.1 step 0). (2) §12.9's key-file filesystem check applies from Part 4, which
brings the key file (G-40). Fixed by hand as in DB-99. **Why.** Fair run 20261020T141334Z (170 of
172 clean-room tests passed). **Rejected.** Adding the key-directory check to Part 3's build: it
stores secrets in plaintext by design (DB-48), so the check would protect nothing.

#### DB-99 — The fair-testing findings of 20 October: witness keys from creation, placement text, a log leaf past the committed WAL (20 October 2026)

**Decision.** (1) Every witness creates its epoch-0 key when the database is created, as the
operator does, and records it in `WITNESSES` before use; the anchors list them from creation
(G-37, §11.3). (2) The SDKs and command-line tools of Parts 3 and 4 report an insert's placement
as the group's §5.1 text form (`frozen-NNNN`, `spawn-` + 16 hex characters, `holding`), not as a
debug rendering (G-38, §16.2); Part 2's frozen SDK keeps its own. (3) Recovery refuses to open
when the log's last leaf has no committed transaction behind it: an insert leaf whose record is
not live in a collection that still exists, or a deletion leaf whose record is still live
(`IntegrityViolation`, INV-15; G-39, §12.3). No crash produces that state, since leaves are
written only after `COMMIT` is durable (§10.5), and the WAL discards only a suffix, so the last
leaf is the one to check. (4) The owner chose to have these fixed by hand, following FT-9's
steps (a red regression test committed first, the smallest fix, the gap and spec entries in the
same commit), instead of `fair.sh fix` sessions, to save cost; the fair runs after the VM are the
independent re-check. **Why.** The bug-hunt runs of DB-98. **Rejected.** Truncating the log back to
the WAL (a published log never shrinks, §10.4).

#### DB-98 — Fair testing of Parts 3 and 4: Part 4's scope, the final ownership lists, bug hunts before the VM (20 October 2026)

**Decision.** (1) `configs/fair.yaml` gains Part 4, registered before any Part 4 run (FT-8). Its
scope is §12.6, §12.8–12.9, §13, §14.5, §14.7, §15.3–15.4, §15.8–15.9 and §16.2–16.3. Its public
interface is the README's "Use the database" and "Part 4" sections and the final SDK's stub; the
SDK is `sever_db`, the CLI `sever-db`; its modules are `sever-keys`, `sever-seal`, `sever-erasure`
and `sever-platform`. (2) A part may carry `environment`: a fact about the machine that runs the
tests (not about the engine), put into the tester's prompt. Part 4's says that the machine has
unencrypted swap and cannot lock memory, so §12.8 refuses to open a database there without the
development override. (3) The tester's prompt names the part's own SDK (it named `sever_db_p2`
for every part), and every room exports `SEVER_SDK`; the dry-run stub imports that package, so a
dry run now checks the plumbing of any part. (4) The ownership lists in `scripts/freeze.sh` for
Part 3 (now with `spikes/p3-proof`) and Part 4 are final; FT-10 hashes them. (5) Runs made before
the VM's gates are bug hunts. Their verdict cannot be PASS, because DB-75 counts planted bugs only
once the part's cargo-mutants gate has passed in the ledger. The runs that count for the freeze
come after the VM run (owner, 20 October 2026). **Why.** Finding an engine bug before the VM run
costs one fair run; finding it after costs a rerun of the VM's gates. Without (2), every Part 4
test that opens a database would fail on a correct refusal and the run would measure almost
nothing. Without (3), the tester of Part 3 or 4 is told the wrong package. **Rejected.** Running
the cargo-mutants gates on the laptop first (DB-94 keeps the full gates on the VM). Saying nothing
about the platform. **Consequence.** Parts 3 and 4 each get two fair runs, about $5 each typically
(the per-session caps bound each at $25; a command stops at $40).

#### DB-97 — `demo-engine/`: the final database used as an application uses it (19 October 2026)

**Decision.** A top-level folder `demo-engine/` holds a tour of the final build that goes only
through its public surfaces: the SDK `sever_db`, the command-line tool `sever-db`, and the
independent `sever-verify` and `sever-audit`. It contains a guided tour on real NQ passages
(twelve chapters, each checking its claim), an interactive shell, the same story on the command
line, two example programs for an application backend, and its own offline tests. The forensic
proof stays Part 4's demo (`scripts/demo-p4.sh`), which the folder runs. It is owned by no part, is
in no freeze manifest, and nothing outside it depends on it. It uses the repository's environment
and the SDK built into it; its Python is checked by the repository's `ruff` settings and by `mypy
--strict` (`demo-engine/demo.sh test`). On a machine the startup checks refuse (§12.8), it shows the
refusal and then opens with the recorded development override; `SEVER_STRICT=1` leaves it out. Its
checks probe the database only through the API: a record is stored if a second insert of its ID is
refused as a duplicate, deleted if deleting it again returns `"absent"`, and counts are `N` plus the
holding area, since §8 never searches the holding area. **Why.** G-36: nothing showed the database
in use end to end; the owner asked for it. **Rejected.** A package under `python/`, which would
enter the root test suite and Part 4's ownership list. A folder in `demo/`, which is the prototype's
own environment (DB-56). **Consequence.** §19.2 lists the folder. Writing the tour corrected two
of its own first checks, not the engine: a record in the holding area is stored but never searched
(§8), and `N` excludes the holding area (§5).

#### DB-96 — EX-2 on `fuse2fs` with `allow_unsafe_fs`; how the evaluation's builds are made (19 October 2026)

**Decision.** (1) EX-2 mounts its ext4 image with `fuse2fs` and opens the engine with
`allow_unsafe_fs`, recorded in every result (G-35). `fuse2fs` runs single-threaded in the
foreground (`-s -f`): on the owner's machine the multi-threaded daemon never exits after
`fusermount -u`. If it lingers, SIGTERM runs libfuse's clean exit, and `e2fsck -fn` must pass before
each scan. (2) The EX-2 driver is `sever-ex2` (feature `forensics` of `sever-scan`: the measured
engine plus `key-export`); the scanner gets every generated key that is not in a key-file slot, and
no such key may appear on the image in the clear. (3) `sever-db-noerase` (DB-54) is feature
`noerase` of `sever-seal` and `sever-erasure`: the sealer keeps the group key's version on a
departure and the rotation participant rotates and erases nothing. The participant stays
registered, because it holds the bucket keys that open records. (4) EX-7 and EX-8 run through
`sever-bench` (crate `sever-eval`), which counts bytes, `fsync`s and WAL records by type on both
disks. (5) The demo (`sever-demo-p4 erase`, Build 3-4 §2.11) lays simulated disks out as one image
instead of mounting ext4 with `fuse2fs`, so it runs anywhere in seconds; the run on a real ext4 image
is EX-2. (6) P4-T2's positive controls are, as Build 3-4 §2.8 says, secrets planted on the image
before every scan (a vector as `i32` and `f32`, passage text, an `r_t`, a key; fresh OS randomness
each time), and every one must be found. Live records the scanner recovers by carving the engine's
own structures are reported, not gated: after a storage checkpoint their only copy may be in
checkpoint pages, and older copies in free space are overwritten as the disk is reused. The scanner
also carves the rotation participant's append stores, where the current bucket blocks and
re-wrapped envelopes live. **Why.** G-35. DB-54 names the builds but not their mechanism; a demo that needs FUSE and
minutes of ingest would not run from a clean clone. **Rejected.** Removing the
rotation participant from the no-erase build: records could not be opened. **Consequence.** EX-2's
result carries `allow_unsafe_fs` (and `allow_unsafe_memory` where `mlockall` is not allowed). EX-2
on `fuse2fs` found a real defect: compaction removed `wrapped.old` while a segment was still open,
which FUSE and NFS refuse. It is fixed with a regression test.

#### DB-95 — An emptied group's deletion proof is not bound to its context; AT-2's donor never empties its group (19 October 2026)

**Decision.** §9.5 states the exception: when `C_S_post` is the identity, the proof's check does not
depend on the challenge, so the proof carries no context and may be copied between emptied
certificates; the certificate's claim rests on step 6 and the operator's signature. The attack
generators (`sever-crashkit-p3`, `sever-crashkit-p4`) take the donor certificate for AT-2, AT-3 and
AT-13 from group certificates that do not empty their group, so every AT-2 instance still swaps in a
proof that cannot verify. **Why.** G-34: the interim P3-T2 run of 19 October found AT-2 accepted on 3
of about 900 instances, each a copy from one emptied certificate to another; the verifier was right
and the attack was empty. **Rejected.** A fixed proof form for the identity (a format change for no
security gain); dropping AT-2 on emptied certificates (with a non-emptied donor the copied proof
still fails the proof check there). **Consequence.** P3-T2 reruns; the register text of AT-2 is unchanged.

#### DB-94 — Part 3's full gates run once, on a cloud VM, at the end; interim checks on the laptop (18 October 2026)

**Decision.** Part 3's pre-registered gates (P3-T1 … P3-T12, unchanged in size: P3-T4 on `nq-10k`
with five seeds of 20,000 operations, P3-T5 on `nq-100k` with five seeds, fuzzing at 10^8
executions) run once, on a cloud Linux VM, together with Part 4's gates, when the whole system is
built. Until then the laptop runs **interim checks**, which are evidence and are never reported as
the gates: (1) the crash campaign's insert phase already run (operations 0 to about 7,700 on every
seed, 351,866 crash points, 0 failures, kept in `traces/interim-insert-phase/`); (2) the crash
campaign with crash points from operation 17,000 (`--crash-from 17000`: single deletions, every
multi-group deletion and the inserts after them) on every seed; (3) the `nq-100k` replay of seed 42;
(4) the attacks, checks, coverage, measures and spikes as specified; (5) fuzzing at 10^7 executions.
Part 3 freezes (F-1) only after the VM run passes; Part 4 keeps building on `p4-prep` (DB-89).
**Why.** The laptop needs about 1.5 days for the full gates, and two replays at once exhausted WSL's
10 GB on 18 October (the kernel killed a replay and WSL restarted). **Rejected.** Shrinking the gates
themselves (it would move pre-registered targets after a run began, overview §3.4); waiting 1.5 days
per attempt on the laptop. **Consequence.** `part-3-frozen` and the rebase of Part 4 onto it come
after the VM run; a Part 3 defect found there is fixed as an ordinary pre-freeze change, not an
erratum. **Part 4's interim crash check (19 October 2026).** A Part 4 run holds snapshots of both
disks (2 to 3.5 GB per seed, about a third of Part 3's speed), so five seeds from operation 17,000
did not fit (the memory guard stopped two and paused three after 50 operations). The interim check
is instead three windows of 80 operations per seed, two seeds at a time: single deletions from
operation 17,000, multi-group deletions from 17,844 and the inserts after them from 18,860
(`scripts/ops/p4-interim.sh`). It is evidence only; P4-T3 runs in full on the VM.

#### DB-93 — Memory is locked process-wide at startup; the btrfs attribute before `KEYS` exists (18 October 2026)

**Decision.** (1) Startup locks the whole process with `mlockall(MCL_CURRENT | MCL_FUTURE |
MCL_ONFAULT)`, through EP-11's `lock_memory`, so every page the engine touches afterwards is locked:
the key ring, the AES key schedules, and the decrypted accumulators that the frozen Part 1 index
keeps in ordinary vectors. If it fails, startup refuses ("§12.8 mlock", PL-6) unless
`allow_unsafe_memory`. Linux checks the process's whole virtual size against `RLIMIT_MEMLOCK`, so a
production engine needs `ulimit -l unlimited` (or `CAP_IPC_LOCK`); with a finite limit an allocation
would fail once the engine grows past it, so a finite limit counts as a failed lock. (2) `MlockProvider` (EP-4) can only
be built from the startup report's proof that the lock took effect. Its regions come from that
locked heap and are zeroed on release by `SecretBuf`. Under `allow_unsafe_memory` with a failed lock,
Part 1's heap provider stays and the ledger records the override. (3) On btrfs, before `KEYS`
exists, the key directory's no-copy-on-write attribute decides (a new file inherits it); once `KEYS`
exists, its own attribute decides. (4) Turning core dumps off (`RLIMIT_CORE = 0`, `PR_SET_DUMPABLE =
0`) runs first; if it fails, startup refuses ("§12.8 core dumps") unless `allow_unsafe_memory`. (5) A
probe that cannot answer fails its check closed. **Why.** §12.8 puts decrypted accumulators in locked
pages, but they live in Part 1's frozen index, which allocates them from the ordinary heap (only
`SecretBuf` goes through EP-4), so locking region by region cannot reach them. **Rejected.**
Per-region `mlock` in the provider (it locks keys only, leaving the accumulators unlocked); an erratum
moving Part 1's accumulators into `SecretBuf` (F-6 re-runs every later exit gate, and the index works
on plain `i64` vectors); `MADV_DONTDUMP` (it covers core dumps, not swap). **Consequence.** Closes
G-33; spec §12.8 and §12.9 each gain a sentence. A machine with a finite memory-lock limit (64 MiB on
the development laptop) refuses to start without the override. This laptop's runs need
`allow_unsafe_memory` anyway, because its swap (`/dev/sdc`) is unencrypted.

#### DB-92 — Where the group-key rotation and its sabotage live; `GROUP_CREATE` carries no block (18 October 2026)

**Decision.** (1) The new group key of a rotation is made by the sealer, when the frozen core asks
for a domain's next version after a departure (EP-6 `next_version`), because the core seals the
accumulator under it while it plans, before any participant runs; the participant then rotates the
buckets and re-wraps the survivors in `prepare`. So SB-24 ("skip group-key rotation") is built in
`sever-seal`: the new version keeps the old key's bytes. The register row moves from `sever-erasure`
to `sever-seal` (no Part 4 result existed). (2) The core's `GROUP_CREATE` record keeps its bucket
block empty; the block is the participant's `BUCKET_BLOCK` record of the same transaction, so it is
logged once. (3) The participant prunes the key ring's stage in `prepare` to what the transaction's
change set justifies, because a plan that fails after the sealer staged keys runs no participant
hook. **Why.** These follow from the frozen EP-6 and EP-7 calls' order. **Rejected.** Rotating the
group key in the participant (the accumulator would already be sealed under the old key).
**Consequence.** Spec §14.6 amended (two table rows); `spec/registers_p4.yaml` SB-24.

#### DB-91 — Re-wrapped record keys live in the wrapped-key store, not in the slots (18 October 2026)

**Decision.** At the owner's choice (18 October 2026, closing G-32): when a bucket rotates, the
survivors' new envelopes are written by the key-rotation participant (ID 4) to its wrapped-key store
`wrapped/<seq>.store` (renamed from DB-90's `buckets/`) and, in the same transaction, to the WAL as
its `EXTENSION` records, each `scrambled_id ‖ u64be bucket_version ‖ envelope (60)`. A record's
current envelope is the store's entry if its `bucket_version` is the bucket's current version, else
the slot's (§14.4). The store also holds the bucket blocks (`u64be group_key_version`, highest wins)
and a drop marker per dropped collection; every merge rule is monotonic, so the store and the WAL
tail merge in any order; the store is compacted when it holds four times its live bytes. **Why.** The
frozen EP-7 participant sees only the transaction's own records, never a survivor's slot, so it cannot
write `SLOT_PUT`s for survivors (G-29's plan). Writing only envelopes is also what §13.6's 12.9 KB
counts, and costs about 17 KB of WAL per deletion instead of about 180 KB. **Rejected.** A mirror of
every slot in the participant (slot memory doubled, about +2 GB at nq-1m); an erratum exposing the
image to participants (F-6 re-runs every later exit gate, including Part 3's running gates).
**Consequence.** Closes G-32; revises DB-90 (3) and (4); spec §13.3, §13.6, §14.1, §14.4, §14.6 and
§14.8 amended. A stale envelope left in a slot is wrapped under a rotated bucket key whose only
wrappings were under erased group keys, so INV-12 and §13.5 hold unchanged.

#### DB-90 — Part 4 design-review decisions: drop order, key-file slots, bucket store, the P4-T14 count, platform detection, two override flags (18 October 2026)

**Decision.** The owner accepted the six fixes Part 4's design review proposed (18 October 2026), each
as written in `docs/SPEC_GAPS.md`. (1) **G-26:** drop collection commits `COLLECTION_DROP` first, then
erases the collection's key slots and deletes its files in phase C, acknowledging after the erase; a
crash in between is finished by §13.4's rule (slots of no domain are erased). (2) **G-27:** each
key-file slot carries magic `SVKS` and names its domain (`collection_id ‖ group_id`); a domain's index
is its pair's position, appended and never reused; the pair count comes from the file length, a
trailing partial pair is truncated at recovery, and the header is written once (no `slot_pairs`).
(3) **G-28:** bucket blocks are the key-rotation participant's durable state in an append store
`buckets/<seq>.store` (as DB-81 keeps the log's), not `checkpoint/<id>/buckets.bin`. (4) **G-29:** the
§13.6 12.9 KB counts secret material; P4-T14 also reports the WAL bytes by record type (`SLOT_PUT`
carries whole slots). (5) **G-30:** encrypted swap means zram or dm-crypt (`CRYPT-` uuid) for every
active entry of `/proc/swaps`; hibernation means `disk` in `/sys/power/state` with a resume device;
a failed `mlock` refuses to start unless `allow_unsafe_memory`. (6) **G-31:** two flags,
`allow_unsafe_memory` (§12.8) and `allow_unsafe_fs` (both filesystem checks of §12.9), each recorded
in the ledger; the key directory is an allow-list (ext4, XFS, btrfs with no-CoW on `KEYS`). **Why.**
G-26 as specified bricks a database on one crash; G-27 and G-28 leave recovery unable to do what §13.4
and §15.7 require; G-29 to G-31 leave a pre-registered measure and gate without a fixed meaning.
**Rejected.** An erratum to the frozen Part 2 core for `buckets.bin` (the participant store needs
none); keeping `slot_pairs` (a torn header rewrite has no recovery rule). **Consequence.** Closes
G-26 … G-31; spec §12.8, §12.9, §13.6, §14.1, §14.7, §14.8, §15.9, §18 and Appendix A amended; Build 3-4
E2E-4.5 and P4-T14 reworded; `spec/requirements.yaml` gains SR-12.8-5/6, SR-12.9-4, SR-14.7-6 and
SR-14.8-4 (65 Part 4 requirements); the P4-T8 platform register names `allow_unsafe_fs` for the
key-directory cases.

#### DB-89 — Part 4 is built before Part 3 is frozen, on its own branch (18 October 2026)

**Decision.** At the owner's request (18 October 2026), Part 4's modules are built while Part 3's gate
runs finish, against Build 3-4 §0 ("Part N starts only when Part N−1 is frozen"). Conditions: the work
is on its own branch and worktree (`p4-*`, `~/sever-db-p4prep`), never in the working copy the gates
run in; no file Part 3 owns is edited (F-3: Part 4 changes behaviour only through EP-6, EP-7, EP-11);
nothing merges to `main` before `part-3-frozen`; after the freeze the branch is rebased onto that tag
and every Part 4 test, proof and check runs again; every Part 4 build and test runs at the lowest CPU
priority on at most two cores while a gate runs. **Why.** Part 3's remaining work is machine time (the
crash campaign and the replay, about a day on the owner's laptop); the owner prefers to build meanwhile.
**Rejected.** Waiting (a day idle); building in the gates' working copy (the ledger records its HEAD
and dirty state). **Consequence.** If a Part 3 gate fails and Part 3 changes, the Part 4 branch is
rebased and any Part 4 code built on the changed behaviour is checked again; Part 4's own freeze still
needs every Part 3 gate (F-5).

#### DB-88 — Crash points from the main line's snapshots; smaller segments in the replay (17 October 2026)

**Decision.** (1) The Part 3 crash campaign (P3-T4) wraps the main line's data disk in a `SnapVfs`
(`sever-crashkit-p3::snap`) that forks both simulated disks before every mutating VFS operation. A
crash point during the `k`-th operation with no torn bytes restarts the fork taken before it,
instead of reopening the disks from before the operation and running it again up to `k`: in
`SimVfs` the crashing operation does not complete, so the two give the same disks. A torn write
(the 512-byte offsets and the random points that land on a write) is still made by replay. (2) The
gate checks this on its own run: every 50th operation's points are made both ways
(`--compare-every 50`), the two disks must hold the same files with the same lengths and recover to
the same state and log, and any difference (`method_mismatches`) fails the gate. (3) The trace
replay (P3-T5) uses 4 MiB segments for the WAL, the payload store and the log's stores. (4) The
campaign remembers, by SHA-256 of the anchors and the bytes, each certificate that passed §11.3 in
the run (a point that recovers to the committed state holds the main line's own certificate; §11.3
is a pure function of both); a rejection is never remembered. (5) The campaign saves its progress every 30 s and
`gates p3-crash --resume` continues an interrupted run, exactly as Part 2's `p2-crash --resume`
(the same commit only; the results file cut back to the saved progress; a new ledger line naming
the run it resumes); a run killed after 45 s and resumed gave the same 2,555 result lines as one
that was never interrupted. **Why.**
Reopening and replaying was 45 % of every crash point (measured: 193 s against 115 s for the same
2,451 inserts' points; at the first deletions 315 ms against 148 ms a point), and `SimVfs` copies a file on its first write after an `fsync`, so with 64 MiB
segments every insert of the replay copied up to 64 MiB (an insert took 33 ms in the engine, 16 ms
with 4 MiB). Together they bring Part 3's gate runs from about two days to under a day on the
owner's laptop; a 14-hour campaign without (5) lost 5 hours when its session ended. **Evidence.** `--method compare` (every point both ways) on seed 42: the first 120
operations (1,033 points, inserts) and operations 10,000–10,060 (deletions) and 17,843–17,873 (user
deletions), 0 mismatches; a build that forks *after* the operation instead is caught (38 of 64
compared points differ, exit 1). **Rejected.** Fewer crash points or fewer seeds (EX-1 fixes both);
changing `SimVfs` (frozen Part 2); more parallel jobs (the laptop overheats). **Consequence.**
Nothing in the engine changes. The old method stays available (`--method replay`).

#### DB-87 — Part 3's gate tooling and demo (16 October 2026)

**Decision.** (1) The Part 3 gates run through a test-only crate, `sever-crashkit-p3`: the crash
campaign with certificates (P3-T4) reuses Part 2's oracle streams and compares recovered states in
the core blob form (the full form minus `C_S ‖ r_agg`, which no Part 2 oracle knows), and adds the
log checks; the trace replay (P3-T5) checks every certificate and every group against a model in
which `C_S` is the sum of the members' `C_t`; the attack generator (P3-T1/T2) re-signs attacks with
the operator key it reads from `SECRETS`, as a dishonest operator would. (2) A feature `memo-checks`
of `sever-commit`, enabled only by that crate, remembers group states that already passed INV-3 in
the process: a crash campaign reopens the database hundreds of thousands of times and each open
recomputes `C_S` of every group (5 ms each at d = 384); the check is the same, and a changed state
is always recomputed. (3) `sever-verify` gains `--explain` (each §11.3 step, for the demo) and
`--batch` (one process for a gate's hundreds of thousands of certificates). (4) The demo is a Python
program (`sever_demo_p3`) because §16.2's backend is the SDK. **Why.** Without (2) one crash point
takes 4.5 s and the campaign months; without (3) one process per certificate. **Rejected.** A smaller
dimension for the campaign (T-1 asks for the same data as Part 2's); variable-time INV-3 (the group
sums are secret). **Consequence.** Spec §16.3 amended; nothing in a measured or shipped build changes.

#### DB-86 — Leaf placements and the log export, for the auditor (16 October 2026)

**Decision.** (1) Every leaf's hash-store entry and its `LOG_LEAF` record carry the leaf's
**placement**: the group its record joined (an insert) or left (a deletion) and, when an insert
triggers a flush, the spawned group the flush created, each as a group ID zero-padded to 32 bytes
(the stored form of §13.2). Placements are written and recovered exactly as the hashes are (DB-81);
they are not in the leaves, so the public log is unchanged. (2) The engine exports the committed log
(`sever-db-p3 export-log`, `Database.export_log()`): `{"version": 1, "leaves": [hex], "placements":
[{"group", "flush"}], "checkpoints": [hex]}`. (3) `sever-audit <export> --anchors FILE
[--certificate FILE]…` reports: a delete leaf whose certificate does not verify or names another
`database_lsn`, or a checkpoint beyond the log (AF-1); a group certificate whose `C_S_pre` is not the
sum of the group's members' `C_t` or whose record is not a member (AF-2); inconsistent checkpoints
(AF-3); a held certificate that is not the leaf at its `database_lsn` (AF-4); a checkpoint root that
is not the tree's (AF-5); and unsigned or under-witnessed checkpoints. The auditor copies nine verifier
files, kept identical by an architecture test. **Why.** A certificate does not name its group and
inserts move `C_S` between deletions, so "consecutive certificates chain" cannot be checked from the
leaves alone (G-25). Group IDs and group membership are plaintext the spec already allows (§13.2).
Summing `C_t` checks every deletion, not only consecutive ones. **Rejected.** A group ID in the
certificate (a format change that would publish each record's group to every holder); chaining by
value alone (a broken chain looks like a deletion from another group); a data-directory mode
(engine-internal formats in an auditor that must not depend on the engine). **Consequence.** Closes
G-25; spec §10.5, §11.3, §14.6, §16.3 and §19.2 amended; `sever-log`, `sever-cert`, `sever-p3` and
`audit/` implement it.

#### DB-85 — The verifier's anchors file and command line (16 October 2026)

**Decision.** (1) The trust anchors are a JSON file the engine publishes (`sever-db-p3 anchors`,
`Database.anchors()`): `{"d": N, "gdigest": hex, "operator": {"<epoch>": hex key}, "witnesses":
[{"<epoch>": hex key}, …]}`, the witnesses listed by index. The generator golden file is compiled
into the verifier. The verifier refuses anchors whose `gdigest` is not the one it derives itself.
(2) `sever-verify <certificate> --anchors FILE [--hex]` runs the §9.2 self-check with its own code,
then the eight steps of §11.3, and prints one JSON line: `{"accepted": true, "deletion_kind",
"database_lsn", "leaf_index", "group_emptied", "collection_id"}`, or `{"accepted": false, "step":
1–7, "reason"}`; exit 0 accepted, 1 rejected, 2 usage, 3 self-check or anchors refused. (3) The
verifier's tests take the `#[spec]` attribute crate as a dev-dependency (a no-op test label, no
verification code); its build links nothing of the engine. **Why.** In v1 every database has its own
operator key and simulated witnesses, so "bundled with the release" means the anchors of the
database the release serves; a file names them explicitly. Naming the step is E2E-3.2's
requirement. **Rejected.** Anchors compiled into the binary (one build per database); a binary
format (the anchors are public and small). **Consequence.** Closes G-24; spec §11.3 and §16.3
amended; `verifier/` implements it.

#### DB-84 — The Part 3 SDK: where randomness, `r_t` and the dimension live (16 October 2026)

**Decision.** (1) `prepare_insert(collection_id, record_id, vector, user)` takes the dimension from
the vector's length (§16.2 gives it no engine handle); the engine refuses another one with
`WrongDimension` (§4.1 step 0). It calls the engine's own quantiser through the binding (§4.2).
(2) The request is an opaque native object: `C_t`, the public key and the signature are readable,
`r_t` is not, and it cannot be pickled; a lost acknowledgement is retried with **the same request**
(a fresh one would carry another `r_t`, hence another `C_t`, and fail as `DuplicateRecord { false }`).
(3) Every SDK function that draws randomness or leads to a proof (`UserKey.generate`,
`prepare_insert`, `Database.open`, `insert`, `delete`, `delete_user`) raises `SeededNonceForbidden`
for any argument beyond its documented ones, positional or keyword. (4) A user key is stored by the
backend as its 32-byte Ed25519 secret (`secret_bytes`, `from_secret_bytes`). (5) The engine checks
the insert signature over the collection inserted into, whatever collection the request names.
**Why.** §16.2 asks that no RNG, seed or nonce can be passed; a closed signature makes "any attempt"
observable instead of a generic `TypeError`. `r_t` is a secret the backend never needs again
(§3.3: "The caller has nothing to keep"). **Rejected.** A `d` argument to `prepare_insert` (not in
§16.2's signature); exposing `r_t` for retries (it would invite logging it, §17).
**Consequence.** Spec §16.2 amended; `sever-py-p3` and `sever_db_p3` implement it; `Engine` is an
alias of `Database` so §16.2's example runs with the package name changed.

#### DB-83 — Part 3's composition root: operator keys, simulated witnesses, dimension, INV-15 (16 October 2026)

**Decision.** (1) The operator's signing keys live in `SECRETS` as entry kind 2 (`u32be epoch ‖
secret`), with the database creation time as kind 3; each new epoch's secret comes from the OS and
is written (atomically, mode 0600) before its first signature. The genesis checkpoint is signed when
the log is created, after the engine has created the database and `SECRETS`. (2) The five simulated
witnesses keep their keys by epoch and their last cosigned checkpoint in `WITNESSES` in the key
directory, written before a new key signs and after every cosignature; a witness with no memory
yet starts from the empty tree (it accepts any first checkpoint, as from the genesis one, DB-79) and
trusts the operator keys the key store publishes. (3) A database has one dimension `d`, given when
it is opened (384 by default, §2.2); a partition artefact of another `d` is refused with
`WrongDimension`. (4) INV-15's second half is checked at each deletion, not at startup (G-23).
**Why.** A key regenerated after a crash would give one epoch two keys and break every older
signature; a witness that forgot what it cosigned would accept any later tree, which is the whole
point of a witness (§10.4). The frozen engine already writes `SECRETS` and §14.9 lets later parts add
kinds. **Rejected.** A separate operator key file (§14.1 names `SECRETS`); witnesses rebuilt from the
log's own checkpoints at each start (a witness must not take the operator's word for its memory).
**Consequence.** Closes G-23; spec §14.1, §14.9 and §21 amended; `sever-p3` implements it.

#### DB-82 — Log checkpoints cover committed leaves only, each in its own transaction (15 October 2026)

**Decision.** Every log checkpoint, the cadence one at each multiple of 10,000 leaves and the
on-demand one before a deletion, is signed over leaves that are already committed and is committed
as its own WAL transaction before the next operation (EP-7 `pre_transaction`, after erratum E-2), at
the exact size it names. If four witnesses do not cosign a deletion's checkpoint, the deletion fails
with `IntegrityViolation` and nothing changes. **Why.** §15.1 step 6 collected cosignatures inside
the insert's own transaction: a crash before its `COMMIT` would leave witnesses remembering a tree
that never existed, and after the retry they would see a fork at that size and refuse every later
checkpoint (G-22). A checkpoint of committed leaves can never be contradicted. In v1 the witnesses
are simulated and honest, so a refusal of an honest checkpoint means the log forked: an invariant
failure, and §17 has no other error for it. **Rejected.** Cosigning after the `COMMIT` in phase C
(the cosignatures would need another durable write the protocol does not offer); a new error kind
(the error enum is frozen in Part 1). **Consequence.** Closes G-22; spec §10.3, §15.1 step 6 and
§17 amended; a cadence checkpoint can come one operation after its multiple is reached, with a
later timestamp.

#### DB-81 — The log's durable layout and where `LogParticipant` lives (15 October 2026)

**Decision.** `LogParticipant` lives in `sever-cert` beside the certificate builder (Build 3-4 §1.4
placed it in `sever-log`, which `sever-cert` depends on); `sever-log` holds its durable side
(`LogStore`). Insert leaves and certificates are appended and `fsync`ed before the `COMMIT` that
covers them (§14.8); leaf hashes, each with its leaf's type byte, and log checkpoints are appended
only after the `COMMIT` (phase C), so their stores hold committed entries only and the WAL tail
restores what a crash cut off. For a leaf index the committed insert leaf or certificate is the last
store entry with that key. `LOG_LEAF` starts with `u64be leaf_index`. The stores are
`log/leaves/`, `log/hashes/`, `log/checkpoints/` and `certs/`, each with `<seq>.store` segments, and
are created at the participant's first recovery, after the engine has created the database (the
frozen engine refuses unknown files in a new data directory). Operator keys reach the log through
an `OperatorKeys` trait, so the composition root can store each new epoch's secret before its first
signature. **Why.** A storage checkpoint truncates the WAL but snapshots only the core image, so the
log must know which store entries are committed without the WAL; writing the committed-only stores
in phase C, which always ends before a storage checkpoint can run, gives that without an extra
marker file. Placing the participant beside the builder avoids a crate cycle. **Rejected.** A
separate "committed size" marker file (one more file and `fsync`); a `CertificateIssuer` trait in
`sever-log` (an indirection with no second implementation). **Consequence.** Spec §10.5, §14.1 and
§14.6 amended; Build 3-4 §1.4 table updated.

#### DB-80 — When a deletion needs an on-demand log checkpoint (15 October 2026)

**Decision.** Before a deletion the log issues an on-demand checkpoint whenever the latest
witnessed checkpoint does not cover every committed leaf. **Why.** EP-7's frozen
`pre_transaction(kind, collection)` does not name the records a deletion removes, so the log cannot
test §10.3's "the record's insert leaf is not yet covered" (G-21); "every leaf is covered" implies
it for every record. **Rejected.** Changing the frozen hook's signature (a larger erratum for a
condition that only saves some checkpoints); learning the records through the planner's side
effects before `prepare` (fragile across failed plans). **Consequence.** Closes G-21; spec §10.3
and §15.3 step 3 amended. A deletion right after inserts costs one checkpoint even if the deleted
record was already covered.

#### DB-79 — The genesis log checkpoint (15 October 2026)

**Decision.** The genesis log checkpoint is `(tree_size 0, root SHA-256(""), timestamp_ms =
database creation time, epoch 0)`, signed by the operator when the database is created. Every
witness starts from it as its last cosigned checkpoint; a witness accepts any first real checkpoint
as an extension of it (every tree extends the empty one, and RFC 9162 proofs need `0 < first`). The
verifier's anchors no longer list a genesis checkpoint. **Why.** §11.3 listed a genesis checkpoint
as a verifier input that no step used, and §10.4's witnesses needed a starting point that was never
defined (G-4). The empty-tree root is RFC 9162's `MTH({})`, and signing it at creation fixes the
genesis time from which epochs count (§9.8). **Rejected.** Keeping genesis in the verifier anchors
(no step would use it, and it would tie each verifier release to one database); witnesses starting
from the first real checkpoint unchecked (that first cosignature would vouch for nothing).
**Consequence.** Closes G-4; spec §10.3, §10.4 and §11.3 amended; `sever-log` implements
`LogCheckpoint::genesis` and starts `SimulatedWitness` from it.

#### DB-78 — A malformed insert credential is a `CommitmentMismatch` (15 October 2026)

**Decision.** At insert, a supplied `C_t` that is not a canonical point or is the identity, or an
`r_t` that is not a canonical scalar, is rejected with `CommitmentMismatch` (spec §17), before the
signature is checked. **Why.** §9.9 requires canonical encodings and forbids the identity as `C_t`,
but §17 has no row of its own for them; each case means the supplied `C_t` is not a valid
commitment to the record, which is what `CommitmentMismatch` reports. A new error kind would add a
§17 row and an SDK error for a case only a broken or hostile backend produces. **Rejected.** A new
`InvalidCredential` error (more surface for no behavioural gain); `IntegrityViolation` (that stops
the engine, and nothing stored is corrupt). **Consequence.** Implemented in `sever-commit`'s
`admit`; the SDK maps it like any `CommitmentMismatch`. No specification section changes (it applies
§9.9 and §17 as written).

#### DB-77 — The generator self-check at any dimension (15 October 2026)

**Decision.** The startup self-check of spec §9.2 compares `H`, `G_0` and `G_383` with the golden
file at every dimension `d` (deriving `G_383` for the check when `d ≤ 383`), and compares `gdigest`
(§9.6) only when `d = 384`; the RFC known-answer tests are unchanged. **Why.** The golden file holds
the v1 values (d = 384, Appendix B), while the code runs at any `d` (DB-49), for example the d = 16
fixtures, so "`G_{d−1}`" had no golden value to compare with (G-20). Every generator comes from the
same derivation, so `H`, `G_0` and `G_383` catch a drift at every `d`, and `G_0` and `G_383` exercise
both ends of the 4-byte index. **Rejected.** Golden values for every `d` in use and a refusal at
any other `d` (narrows DB-49 and catches nothing more); comparing `G_{d−1}` with a fresh derivation
of itself (it can never fail). **Consequence.** Closes G-20; spec §9.2 amended; `sever-crypto`'s
`self_check` follows it, and the verifier will too.

#### DB-76 — Four more certificate attacks (15 October 2026)

**Decision.** The certificate attack suite (EX-4; Build 3-4 §1.8, AT-N) gains AT-18 (a fixed-size
field of the wrong length, or tag 11 or 12 outside {0, 1}), AT-19 (an insert leaf whose type is not
`0x01`, or an `insert_inclusion` version other than 1) and AT-20 (a log checkpoint or a cosignature
under an epoch or witness index not in the anchors), and the EX-4 list now also names the build
plan's AT-17 (two cosignatures from one witness). AT-13 explicitly includes a holding-area
certificate with tag 11 = 1. The target is unchanged: 100 % of attack certificates rejected (T-4,
gate P3-T2). **Why.** At Part 3's design review each rule of spec §11.1–11.3 was matched to an
attack; these rules had none, and AT-4's random single-field tampers would hit them only by chance.
No certificate exists yet, so no target moves after a result (§3.4). **Rejected.** Keeping the 17
attacks (the rules would rest on parser unit tests alone). **Consequence.** P3-T2 runs AT-1 … AT-20;
the Part 3 register (`spec/registers_p3.yaml`) ties every attack to the requirements it checks.

#### DB-75 — Blind bugs from cargo-mutants, not an AI planter (15 October 2026)

**Decision.** Fair testing (DB-73) takes its blind planted bugs from the part's own `cargo-mutants`
gate (`gates pN-mutants`, Build §2.1 L11) instead of an AI planter session; a fairness run passes
only when that gate's PASS is in the run ledger (`configs/fair.yaml`, `planted_bugs: cargo-mutants`).
The clean-room tester, the triage judge and the oracle audit are unchanged. **Why.** A tool chooses
the mutants, so nobody who is scored on them chose them, which is what FT-6 asks; the gate is already
required for every part (P2-T9, P3-T9) and costs no tokens, while each AI planter run cost about
$5–10 of the owner's plan. The bug that fair testing found in Part 2 came from the clean-room
tester, not from planted bugs (erratum E-1). **Rejected.** Keeping the AI planter (cost, and it
largely repeats the mutants gate); no planted bugs at all (FT-6 needs evidence that the suite catches
bugs). **Consequence.** Mutants are syntactic; subtler semantic bugs (durability order) stay the job
of the sabotage items (SB-N) and the crash campaign. Amends DB-73.

#### DB-74 — Fair testing within a token budget (8 October 2026)

**Decision.** `fair.sh` starts nothing without `--yes` and first prints the sessions and their
estimated cost; every session runs with a cost cap and one command stops starting sessions at a
total cap (`configs/fair.yaml`, `budget`); on the plan's usage limit a command stops instead of
waiting. These settings are excluded from the FT-8 digest. **Why.** The first real runs spent the
owner's plan quickly: a full cycle started without a cap, and an automatic wait-for-reset turned it
into an all-day drain (owner, 8 October 2026: stop the burn, with no loss of testing quality).
**Rejected.** Cheaper models, fewer planted bugs or audited tests, fewer fix rounds (each weakens the
test; the owner asked for no loss of quality). **Consequence.** A run may stop part-way more often;
`resume` continues it without redoing finished stages. Amends DB-73.

#### DB-73 — Fair testing: clean-room sessions, blind bugs, a freeze condition (8 October 2026)

**Decision.** Every part is tested by an automated system (`docs/FAIR_TESTING.md`, rules FT-1 …
FT-10; `scripts/fair.sh`): fresh headless Claude sessions in a `bwrap` sandbox that holds only the
spec, the public API and inputs write tests against a sealed engine; the tests are hashed and run by a
script against the real engine; a different model judges failures; a separate session plants blind
bugs that the script scores against both suites; a judge re-derives a random sample of the suite's
expected values; findings are fixed red-first under diff guards and the run repeats. A part freezes
only after a PASS on its exact owned files; the settings in `configs/fair.yaml` are pre-registered.
**Why.** The engine, its tests, its oracle labels and its proofs had one author; such a suite can be
self-consistent and still wrong (CLAUDE.md §6.3 keeps that author honest but is no second reader).
The owner asked (8 October 2026) for testing that is fair and real, fully automated, on one machine.
**Rejected.** Subagents of a working session (they inherit its files and prompt); a rule in
CLAUDE.md alone (an instruction, not an enforcement); the owner planting bugs and hand-checking
oracles (the owner asked for full automation); a second machine (not available; isolation is about
what a tester can see, which the sandbox fixes). **Consequence.** `scripts/freeze.sh` refuses a part
≥ 2 without a PASS (FT-10); the Fast tier checks kept clean-room tests against their manifests.
Limit: every session is a Claude model, so a misreading all of them share can survive.

#### DB-72 — Format versions, the store magic and identifier widths on disk (8 October 2026)

**Decision.** Every `version` and `format_version` of spec §14.9 is `1` in v1, as for the blob
(§5.5) and the partition artefact (§6.3); the append stores' file header uses the magic `SVDBSTOR`; a
`group_id` written in a WAL payload (§14.6) or a checkpoint stream (§14.9) is 32 bytes, its §5.1 label
zero-padded as in §14.3, and a `scrambled_id` is 64 bytes. **Why.** Tests written from the spec
alone (CLAUDE.md §6.3) could not state these bytes: §14.9 named no version value and no store magic,
and §14.6's "widths not given are `u64be`" read literally would make a `group_id` 8 bytes. **Rejected.**
Leaving them to the code (the spec would then not define the files byte for byte); a `u64be` group
number (group IDs are labels, §5.1). **Consequence.** Closes G-18 and G-19. The values are those the
Part 2 code already wrote, found by tests written before reading it.

#### DB-71 — Licence allow-list: Apache-2.0 WITH LLVM-exception (8 October 2026)

**Decision.** `deny.toml` also allows the SPDX expression `Apache-2.0 WITH LLVM-exception`. **Why.**
The Part 2 Python SDK uses PyO3 (owner decision, 7 October 2026), whose build-time dependency
`target-lexicon` carries this licence; the LLVM exception only adds permissions to Apache-2.0
(already allowed), and the crate is used at build time, not linked into the engine. Found by the
Full-tier `cargo deny` step (spec §20.3 check 5). **Rejected.** Dropping the PyO3 SDK; a per-crate
exception (the expression is as permissive as Apache-2.0 for every crate). **Consequence.** Spec §20.3
check 5 passes with PyO3 in the workspace.

#### DB-70 — E2E-2.6 without mounting (7 October 2026)

**Decision.** E2E-2.6 packs a closed database into an ext4 image with `mkfs.ext4 -d` and reads it
back with `debugfs`, then reopens it and compares; no mount. **Why.** Mounting needs root, and the
development machine has no passwordless sudo (owner decision, 7 October 2026). The test still shows
that the database's files carry its whole state through a filesystem image. **Rejected.** Mounting
through sudo; skipping the test. **Consequence.** Build §5.7 E2E-2.6 notes the method.

#### DB-60 — The dimension check (4 October 2026)

**Decision.** Spec §4.1 gains step 0: the input MUST have exactly `d` components, otherwise
`WrongDimension`; the search query of spec §8.1 is checked by the same steps. **Why.** §17 listed
`WrongDimension` as raised "when §4.1 fails", but §4.1 had no rule that could raise it; without one,
a short vector would be read out of bounds or silently padded. **Rejected.** Leaving the check to each
caller (the engine API, the SDK and the reference model would each invent their own). **Consequence.**
Closes G-8. Step 0 runs first, so a wrong-length vector is never scanned for NaN.

#### DB-55 — Service-side custody of `r_t` and user keys (2 October 2026)

**Decision.** Three parties (spec §3.3). The **user app** is thin: it sends text, authenticates to the
user's account, and holds no SEVER-DB secret. The **application backend** embeds text with the exact
encoder pinned in the partition artefact, never in the engine and never on the user's device; runs
`prepare_insert` (Q24 quantisation, `r_t` drawn from the OS CSPRNG, `C_t`, signature); calls the
engine; and holds each account's Ed25519 signing key in its own key store. The **engine** keeps its
role: it recomputes and checks `C_t`, stores, updates `S`, `r_agg` and `C_S`, writes the log, deletes
and issues certificates. The engine stores `r_t` for **every** record (`has_rt = 1` always), encrypted
under the record key `RK_t` inside the slot payload, so the record-key destruction that already happens
at deletion erases `r_t`. A flush keeps `has_rt = 1` and no longer re-encrypts the payload. The delete
API is `delete(collection_id, record_id)`, with no `r_t` argument. The recomputation of `C_t` at
deletion stays, as an **integrity** check: the stored `x̃` and `r_t` must reproduce the logged `C_t`,
otherwise `IntegrityViolation`. `AuthorisationFailed` is removed. Deletion is authorised by the
application backend, which authenticates the account and then calls `delete`; SEVER-DB no longer
claims that only the user can delete. The user signatures in insert leaves remain, and the leaf format,
the certificate format and the verifier are unchanged. The signatures now record that the service acted
for an authenticated account; they do not constrain a dishonest operator, who holds the keys.
**Why.** A simpler build; no lost-device problem (a lost `r_t` or key no longer makes a record
undeletable); and it matches standard RAG practice, where embedding happens on the backend.
**Rejected.** (A) Embedding and `r_t` on the user device (every device would have to run the pinned
encoder, and a lost device would leave its records undeletable). (B) The backend embeds while the
device holds `r_t`: this adds a round trip and protects only against a later breach, since the engine
sees `r_t` at insert anyway. **Consequence.** Supersedes DB-18; qualifies the rationale of DB-21 and
DB-22; retires L-16; adds L-27. What a certificate proves is restated in §1.2 and spec §11.3.

#### DB-56 — Repository layout follows the build plan; the review demo lives apart in `demo/` (4 October 2026)

**Decision.** The repository layout is the build plan's crate and package map (Build §3.2): one crate
per responsibility, grouped by the part that adds it (`sever-types`, `sever-quant`, `sever-partition`,
`sever-index`, `sever-search`, `sever-tracekit`, `sever-p1` in Part 1, and so on), and one reference
model package per part (`sever_refmodel_core`, `sever_refmodel_durable`, `sever_refmodel_certs`).
Spec §19.2 is amended to match; the crates `sever-store` and `sever-server` and the single package
`sever_refmodel` are gone. The Python prototype built for the 5 October 2026 review lives in `demo/`
with its own `pyproject.toml`, `uv.lock`, tests, scripts and container image; its only outside input
is the data (`datasets/`, read only). **Why.** Closes G-5 before Part 1's first crate. Smaller crates
match the freeze rule (Build §0.3): a part freezes whole crates, so a crate must not straddle two
parts. Keeping the prototype apart stops it from leaking into the frozen parts or their environment
(its packages, `rich` and `pandas`, are not engine dependencies), while it stays runnable as the
record of what was shown. **Rejected.** (A) Keep spec §19.2's coarser crates (`sever-store` would hold
Part 2 and Part 4 code, so it could never freeze). (B) Delete the prototype (it is the evidence for
the review's claims and the run ledger refers to its result files). **Consequence.** Nothing outside
`demo/` may import from it; the future `python/sever_demo` of Build §4.4 (the renderer for
`sever-demo`) is a different package that shares only the name.


#### DB-57 — The k-means seed is reduced modulo 2^32 (4 October 2026)

**Decision.** The partition builder passes `random_state = seed_kmeans mod 2^32` to scikit-learn's
`KMeans`; `seed_kmeans` itself stays the `u64` derived in §10.6. **Why.** scikit-learn accepts only
seeds below 2^32, so the `u64` crashed the build (checked 27 September 2026: `ValueError: Seed must
be between 0 and 2**32 - 1`). **Rejected.** Changing the §10.6 derivation to 4 bytes (it would change
every other sub-seed too). **Consequence.** Spec §6.2 step 2 amended; closes G-1. The artefact's
`seed` field stays the run seed (spec §6.3).

#### DB-58 — Which statements of the specification are normative (4 October 2026)

**Decision.** Spec §0.1 is amended: besides sentences with MUST, MUST NOT, SHOULD or MAY, numbered
algorithm steps, formulas, byte layouts, parser rejection rules, rows of normative tables and
definitions in spec §2–§21 and the appendices are normative. Rationale ("Why …", notes, soundness
notes, explanations that follow a rule) and illustrative examples are explanatory. Every normative
statement gets a requirement ID `SR-<section>-<n>` (Build §2.2). **Why.** Only 39 lines of the
specification contain MUST; the Q24 formula, the byte layouts and the builder steps had none, yet
they are exactly what the tests must check. **Rejected.** Rewriting every rule as a MUST sentence
(hundreds of lines edited, with no change in meaning). **Consequence.** Build §2.2 amended to match;
`spec/requirements.yaml` records each statement's kind (must, step, formula, layout, table row,
definition). Closes G-6.

#### DB-59 — The `nq-10k` development slice (4 October 2026)

**Decision.** `nq-10k` is the first 10,000 rows of `nq-100k` (and so of `nq-1m`): all 4,201 judged
passages, then the first 5,799 rows of the seeded fill. It is the same for every run seed; each run
streams it in its own seed-derived order (§10.7). It is a development slice for tests and demos and
is not used for any pre-registered target. **Why.** The build plan uses it in every Part 1
differential test, end-to-end scenario and demo, but no document defined it. A prefix needs no new
data file, is covered by the existing manifest, and keeps every judged passage, so the relevance
judgements stay meaningful on it. **Rejected.** A per-seed stream prefix, as EX-1 uses (the corpus
itself would then vary with the seed). **Consequence.** §10.4 gains the row; closes G-7.
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
| C-13 | Python SDK | Bindings plus backend-side quantise, commit and sign (runs on the application backend) |
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
| `nq-10k` | 10,000 | The first 10,000 rows of `nq-100k`: all 4,201 judged passages, then the first 5,799 fill rows. Development slice for tests and demos only; no pre-registered target uses it (DB-59) |
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
runs. Proof nonces, keys and blinding values never come from any seed (DB-17). scikit-learn accepts
only seeds below 2^32, so k-means receives `seed_kmeans mod 2^32` (DB-57).

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
the insert leaf; a malformed TLV (missing, repeated or reordered tag; trailing bytes); four
cosignatures where two come from the same witness; a fixed-size field of the wrong length or a flag
outside {0, 1}; an insert leaf of the wrong type or an `insert_inclusion` of the wrong version; a log
checkpoint or cosignature under an epoch or witness not in the anchors (the last four added by DB-76,
before any result).

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
  that key. *Retired by DB-55 (2 October 2026):* every record now stores `r_t` under its record key until
  deletion, by design, so this is no longer a leftover; deleting the record destroys that key (spec
  §13.5).
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
- **L-27 Service-held keys.** The operator holds every account's signing key and every `r_t`, so insert
  signatures and deletion authorisation do not constrain a dishonest operator; they record that the
  service acted on an authenticated account.
- **L-28 Frozen Part 2 builds keep three known defects until erratum E-4 … E-6** (DB-103): its SDK lets a
  record ID with no UTF-8 encoding raise `UnicodeEncodeError` instead of `InvalidRecordId`; its builds keep
  serving after an `IntegrityViolation` and checkpoint at close; the frozen tracer misses a split `#[spec]`
  attribute. The v1 build (`sever-db`) has none of them.

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
- **Application backend** — the service (for example an AI server) that authenticates accounts, embeds
  text, prepares and signs inserts, holds the account keys and calls the engine (DB-55).
- **Blinding value (`r_t`)** — a random scalar inside a record's commitment; drawn by the application
  backend and stored, encrypted, by the engine with every record; erased with the record (DB-55).
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
- **User key** — an account's Ed25519 signing key; generated and held by the application backend; never
  rotates (DB-20, DB-55).
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

---

## Changelog

- **22 October 2026 — The group ID's width in the AD.** DB-105 (§13.2's three group-bound
  associated data all carry `group_id(32, zero-padded)`; closes G-2). Specification sections
  touched: §13.2.
- **21 October 2026 — P4-T3 reopens after recovery.** DB-104 (the final build's crash campaign
  closes and reopens a copy after every recovery, zero-gated as `reopen_mismatches`). Build 3-4
  §2.10 P4-T3 amended.
- **21 October 2026 — Part 3 stops serving too.** DB-103 (Part 3's root takes Part 4's
  stop-serving and replaced-directory guard; the frozen Part 2 fixes become errata E-4 … E-6, applied
  with E-3 after v1.0; adds L-28). Specification sections touched: §12.9.
- **21 October 2026 — The October bug hunt.** DB-102 (participant stores keep what recovery
  replays; complete traces for Parts 3 and 4 in the fast tier; closes G-43). Specification
  sections touched: §15.7.
- **20 October 2026 — Two tours on one work directory.** DB-101 (an `IntegrityViolation` names
  the check that failed; the final build stops serving after one and refuses a replaced data
  directory; closes G-41, G-42). Specification sections touched: §12.9, §17.
- **20 October 2026 — The second Part 3 bug hunt.** DB-100 (the artefact's dimension check names
  the check; the key-file filesystem check is Part 4's; closes G-40). Specification sections
  touched: §12.9.
- **20 October 2026 — The fair-testing findings.** DB-99 (witness keys from creation; placement
  text; a log leaf past the committed WAL; closes G-37, G-38, G-39). Specification sections
  touched: §11.3, §12.3, §16.2, §19.
- **20 October 2026 — Fair testing of Parts 3 and 4.** DB-98 (Part 4's pre-registered scope; the
  machine's platform told to the tester; the tester told the part's own SDK; final ownership lists;
  bug hunts before the VM). Specification sections touched: none.
- **19 October 2026 — The engine demo.** DB-97 (`demo-engine/`: the final database used as an
  application uses it; closes G-36). Specification sections touched: §19.2.
- **19 October 2026 — The evaluation's harness.** DB-96 (EX-2 on `fuse2fs` with `allow_unsafe_fs`;
  `sever-ex2`, `sever-db-noerase`, `sever-bench`; closes G-35). Specification sections touched:
  none.
- **19 October 2026 — Emptied-group proofs.** DB-95 (an emptied group's deletion proof is not bound
  to its context; AT-2's donor never empties its group; closes G-34). Specification sections
  touched: §9.5.
- **18 October 2026 — Part 3 gates on a VM.** DB-94 (the full gates run once on a cloud VM at
  the end; interim checks on the laptop). Specification sections touched: none.
- **18 October 2026 — Startup checks.** DB-93 (memory is locked process-wide at startup; the
  btrfs attribute before `KEYS` exists; core dumps off first; probes fail closed; closes G-33).
  Specification sections touched: §12.8, §12.9.
- **18 October 2026 — The key-rotation participant.** DB-92 (the group key rotates in the sealer;
  SB-24 in `sever-seal`; `GROUP_CREATE` carries no block; the stage is pruned in `prepare`).
  Specification sections touched: §14.6.
- **18 October 2026 — Build-plan proposals accepted.** DB-53's EP-11 half (`PlatformProbe`) and
  DB-54 (the evaluation's build variants). Specification sections touched: none.
- **18 October 2026 — Re-wrapped record keys.** DB-91 (survivors' envelopes in the wrapped-key
  store; closes G-32). Specification sections touched: §13.3, §13.6, §14.1, §14.4, §14.6, §14.8.
- **18 October 2026 — Part 4 starts.** DB-89 (Part 4 built before Part 3's freeze, on its own
  branch) and DB-90 (the owner accepted the design review's fixes; closes G-26 … G-31). Specification
  sections touched: §12.8, §12.9, §13.6, §14.1, §14.7, §14.8, §15.9, §18, Appendix A.
- **17 October 2026 — Faster Part 3 gate runs.** DB-88 (crash points from the main line's
  snapshots, checked against the old method on every 50th operation; accepted certificates
  remembered within a run; 4 MiB segments in the trace replay; `p3-crash --resume`). Specification sections touched: none.
- **16 October 2026 — Part 3 gate tooling.** DB-87 (`sever-crashkit-p3`, INV-3 memo in test
  builds, `sever-verify --explain` and `--batch`, the Python demo). Specification sections
  touched: §16.3.
- **16 October 2026 — Part 3 auditor.** DB-86 (leaf placements beside the hashes and in
  `LOG_LEAF`; the log export; `sever-audit`; closes G-25). Specification sections touched: §10.5,
  §11.3, §14.6, §16.3, §19.2.
- **16 October 2026 — Part 3 verifier.** DB-85 (the anchors file, `sever-verify --anchors`, its
  output naming the failed step; closes G-24). Specification sections touched: §11.3, §16.3.
- **16 October 2026 — Part 3 SDK.** DB-84 (the request carries `r_t` unreadably and is reused
  for a retry; the dimension is the vector's; any extra argument is `SeededNonceForbidden`; the
  signature binds the collection inserted into). Specification sections touched: §16.2.
- **16 October 2026 — Part 3 composition root.** DB-83 (operator keys in `SECRETS`, simulated
  witnesses' memory in `WITNESSES`, one dimension per database; INV-15's second half at deletion,
  closes G-23). Specification sections touched: §14.1, §14.9, §21.
- **15 October 2026 — The log as a transaction participant.** Erratum E-2 (Part 2 engine calls EP-7
  `pre_transaction`); DB-80 (on-demand checkpoint whenever a leaf is uncovered; closes G-21), DB-81
  (the log's durable layout; `LogParticipant` in `sever-cert`), DB-82 (checkpoints of committed
  leaves only, each its own transaction; closes G-22). Specification sections touched: §10.3,
  §10.5, §14.1, §14.6, §15.1, §15.3, §17.
- **15 October 2026 — Genesis log checkpoint.** DB-79 (defined; witnesses start from it; dropped
  from the verifier anchors; closes G-4). Specification sections touched: §10.3, §10.4, §11.3.
- **15 October 2026 — Insert credential errors.** DB-78 (a malformed `C_t` or `r_t` is
  `CommitmentMismatch`). No specification section touched.
- **15 October 2026 — Generator self-check.** DB-77 (H, G_0 and G_383 at every d; gdigest at
  d = 384; closes G-20). Specification sections touched: §9.2.
- **15 October 2026 — Part 3 attack suite.** DB-76 (AT-18 … AT-20 added before any result; AT-17 in
  the EX-4 list). Specification sections touched: none.
- **15 October 2026 — Part 3 design review.** DB-51 (pure-Python ristretto255 in the certificate
  model, closes G-3), DB-52 (`expand_message_xmd` implemented by the project) and DB-53's EP-10
  `Witness` accepted from the build plan; EP-11 waits for Part 4. Specification sections touched:
  §9.1, §9.2, §19.1 (C-18).
- **15 October 2026 — Erratum E-1 and blind bugs from cargo-mutants.** DB-75 (fair testing takes
  its planted bugs from the cargo-mutants gate). Erratum E-1 (`ERRATA.md`): Part 2 SDK deadlock.
- **8 October 2026 — Fair testing within a budget.** DB-74 (confirm before spending, cost caps,
  stop on the usage limit; no change to what is tested).
- **8 October 2026 — Fair testing.** DB-73 (clean-room sessions, blind planted bugs, random oracle
  audit, guarded fixes, freeze condition; `docs/FAIR_TESTING.md`). No specification section touched.
- **8 October 2026 — Test-oracle audit.** DB-72 (format versions, the store magic and identifier
  widths on disk, closes G-18 and G-19). Specification sections touched: §14.6, §14.9.
- **7 October 2026 — Part 2 design review.** DB-46 (slot payload order and the header's
  `seal_version`) and DB-48 (`sealer_id` in every file; no confidentiality claim before Part 4)
  accepted from the build plan. New: DB-65 (`create_dir` and `remove_dir` in the `Vfs`, closes
  G-13), DB-66 (WAL framing, closes G-14), DB-67 (file layouts, new spec §14.9, closes G-15), DB-68
  (`SECRETS` in every database, closes G-16), DB-69 (`sever-demo-p2`, closes G-17), DB-70
  (E2E-2.6 without mounting). Specification sections touched: §12.2, §13.2 (payload row), §14 (sealer marker), §14.3,
  §14.4, Appendix A. Build §3.5; Build 3-4 §3.5.
- **6 October 2026 — Part 1 gaps closed.** DB-61 (the ULP sentence of §4.1, closes G-9), DB-62
  (spawn target size is a runtime value, closes G-10), DB-63 (at most 10,000 frozen groups, closes
  G-11), DB-64 (the error for a bad artefact, closes G-12). Specification sections touched: §2.2,
  §4.1, §5.1, §6.3. Overview §6.8 (DB-49 consequence).
- **4 October 2026 — Part 1 decisions accepted.** DB-44 (four frozen parts), DB-45 (plan/apply,
  extension points, the WAL `EXTENSION` record), DB-47 (blob extension region, `SEVERC`/`SEVERG`),
  DB-49 (runtime dimension and group count) and DB-50 (one `SecretMemory` provider) accepted from the
  build plan. New: DB-57 (k-means seed mod 2^32, closes G-1),
  DB-58 (normative statements, closes G-6), DB-59 (`nq-10k`, closes G-7). Specification sections
  touched: spec §0.1, §2.2, §5.5, §6.2, §14.6, Appendix B. Overview §6.8, §10.4, §10.6. Build
  §2.2, §3.5; Build 3-4 §3.5.
- **2 October 2026 — Service-side custody of `r_t` and user keys (DB-55).** Three parties: a thin user
  app, an application backend and the engine. Text is embedded on the backend with the pinned encoder,
  never in the engine or on the device. The engine stores `r_t` for every record under its record key
  (`has_rt = 1` always); the flush no longer clears it; `delete` takes no `r_t`; the delete-time `C_t`
  check is an integrity check (`IntegrityViolation`); `AuthorisationFailed` is removed. The backend
  authorises deletion after authenticating the account. Insert signatures, the leaf and certificate
  formats and the verifier are unchanged, but the signatures now record service action. The claims are
  restated in a "Proves / Does not prove" box in §1.2, and the problem statement no longer overclaims.
  L-27 is added and L-16 retired. DB-55 supersedes DB-18 and qualifies DB-21 and DB-22. Specification
  sections touched: spec §1, §2.1, §3.3, §4.2, §5.4, §7.4, §9.3, §9.4, §9.8, §10.2, §11.1, §11.3,
  §13.2, §13.3, §13.5, §14.4, §15.1–15.4, §16.1, §16.2, §17, §19.1. Build plans: Build §0.2, §3.3, §3.4,
  §5.7; Build 3-4 §1.1, §1.2, §1.4, §1.5, §1.8, §1.10, §2.5, §3.2.
