# R06 · Paper draft (IEEE style, first draft)

Real numbers only; every number has a source in [11](../11_results.md). `[TODO: author]` marks what
the author must add. `[CITATION NEEDED]` marks unverified references (see [R07](R07_references.bib)).

## Title options

1. SEVER-DB: Exact, Verifiable and Crypto-Shredded Deletion in a Vector Database
2. Deleting Without Ghosts: Provable Erasure for IVF Vector Indexes
3. Receipts for Forgetting: Commitment-Backed Deletion Certificates for Vector Stores

## Abstract (≤ 250 words)

Vector databases that back retrieval-augmented AI store personal text as embeddings, which can reveal
much of their source text [Morris et al. 2023]. Common stores delete logically and reclaim space later,
and summaries such as centroids keep the influence of deleted vectors. We present SEVER-DB, an IVF-flat
vector database in which deletion is exact, crash-safe, verifiable and permanent. Groups are fitted once
on public data and keep exact Q24 integer sums, so deleting a vector restores its group bit for bit to
the never-inserted state. A write-ahead log with a single commit point makes multi-group deletion
all-or-nothing. Each group carries a Pedersen commitment on ristretto255; every deletion yields a signed
certificate with the homomorphic transition, a context-bound proof of knowledge and an RFC 9162 inclusion
proof under a witness-cosigned checkpoint, checkable offline by an independent verifier. Every secret is
stored under AES-256-GCM-SIV in a three-level key hierarchy whose affected keys are rotated, and the old
group key destroyed, before a deletion is acknowledged. On the Natural Questions corpus with five seeds,
we observed 0 exactness failures over 427,455 survivor checks, 0 failures over 938,129 crash points with
192,964 certificates checked, 5,000 honest certificates accepted and 226,410 attack certificates
rejected, and 0 forensic findings in 30 raw-disk scans. Provable erasure costs about 75–110 ms and
about 39 KB written per deletion, against about 1 ms and 11 bytes for soft deletion. A pre-registered
search-stability target was not met. Witnesses are simulated in this version. [TODO: author — trim to
the venue's limit]

## I. Introduction

[TODO: author — motivation from R01; the four claims; contributions C1–C4 from R03; paper outline.]

## II. Background

Vectors and IVF ([B01](../background/B01_vectors_embeddings_and_search.md)); floating point vs fixed
point ([B03](../background/B03_floating_point_vs_exact_integers.md)); WAL and recovery
([B02](../background/B02_how_databases_store_and_delete.md)); commitments, Schnorr proofs, Merkle logs,
AEAD ([B04](../background/B04_cryptography_basics.md)).

## III. Related Work

From [R02](R02_related_work.md): logical deletion in PostgreSQL and FAISS; machine unlearning (Bourtoule
et al.); transparency logs (RFC 6962/9162, C2SP witnesses); crypto-erase (NIST SP 800-88r2);
[CITATION NEEDED: verifiable deletion literature, secure deletion SoK, SSD erasure].

## IV. System Design

A. Fixed partition and routing (128 frozen groups on SciQ; Mahalanobis drift; spawned groups of 200;
holding area). B. Exact accumulators and the canonical blob; five-field equivalence. C. Transaction
protocol with eight steps and one commit point. D. Commitments and certificate (13 TLV fields, eight
verification steps). E. Key hierarchy, rotation rule, phases A/C, INV-14. Figures: architecture
([04](../04_architecture.md)), delete sequence ([07e](../07e_encryption_and_crypto_shredding.md)),
verifier flow ([07d](../07d_deletion_certificate_and_verification.md)).

## V. Implementation

Rust 1.98.1 workspace of 35 crates (~59.5k lines of Rust), Python 3.13 tooling (~37.1k lines), PyO3 SDK;
curve25519-dalek 4.1.3, ed25519-dalek 2.2.0, merlin 3.0.0, aes-gcm-siv 0.11.1; independent verifier and
auditor workspaces; `unsafe` only in the AVX2 kernel ([03](../03_tech_stack_and_toolchain.md),
[09](../09_coding_style_and_engineering_rules.md)).

## VI. Evaluation

Setup: [R05](R05_experimental_methodology.md). Results (ledger lines in [11](../11_results.md)):

| Claim | Result |
|---|---|
| Exactness vs reference model | 10,648,947 (nq-10k) and 12,389,642 (nq-100k) values compared, 0 mismatches |
| Survivors check | 43,562 / 427,455 / 275,114 groups, 0 failures |
| Quantisation cost | Recall@10 = 1.0 at nq-100k and nq-1m (target ≥ 0.999) |
| Crash safety | 343,837 (Part 2) and 938,129 (Part 3) crash points, 0 failures; Part 4 scoped windows PASS |
| Certificates | 5,000 accepted, 226,410 attacks rejected (Part 3 and final build) |
| Forensics | 0 findings in 30 scans of 16 GiB ext4 images; all applicable sabotage builds detected |
| Cost (EX-7, nq-100k, seed 42) | delete p50: 109.1 ms (SEVER), 59.9 ms (no erase), 0.9 ms (soft delete); bytes per deleted record 39,525 / 27,279 / 11 |
| Proof (P3-T13, d = 384) | prove median 15.78 ms, verify median 2.74 ms; certificate 1,197–13,645 B |
| Search stability (T-5) | drift 0.0079–0.0130 per seed, target 0.005 **not met** |

## VII. Discussion and Limitations

Simulated witnesses (L-7); operator-held keys (L-2, L-27); device-dependent key erasure (L-1); scoped
laptop run (DB-113); EX-8 not completed; T-5 not met; author's own soundness argument (L-21); G-34
emptied-group exception. [TODO: author]

## VIII. Conclusion and Future Work

[TODO: author — independent witnesses; client-held keys; cheaper recovery check (DB-116 follow-up);
full-size runs; EX-8.]
