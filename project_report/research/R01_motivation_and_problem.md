# R01 · Motivation and problem statement

## In simple words

People have a legal right to have their data erased in some cases, and AI systems increasingly keep
personal text as embeddings in vector stores. Deleting from those stores is usually logical (hide now,
clean later), summaries keep the deleted data's influence, and nobody outside can check that deletion
happened. SEVER-DB's measured results show that exact, verifiable, permanent deletion is possible, and
what it costs.

> **Prerequisites.** [B07](../background/B07_privacy_and_the_right_to_erasure.md), [B01](../background/B01_vectors_embeddings_and_search.md).

## 1. The right to erasure

- **EU GDPR Art. 17**: "The data subject shall have the right to obtain from the controller the erasure
  of personal data concerning him or her" (via unofficial mirror gdpr-info.eu, accessed 2026-11-01)
  [CITATION NEEDED: official EUR-Lex reference, Regulation (EU) 2016/679].
- **India DPDP Act 2023, §12**: rights to correction and erasure [CITATION NEEDED: official India Code /
  gazette text; the official PDF returned HTTP 403 in this session; commencement date of §12 unverified].

## 2. Vector stores hold personal data

Retrieval-augmented systems embed user text and store it for nearest-neighbour search
[CITATION NEEDED: Lewis et al. 2020, "Retrieval-Augmented Generation…" (NeurIPS) — not opened in this
session]. Embeddings are not anonymous: Morris et al. (EMNLP 2023, arXiv:2310.06816, opened) recover
92 % of 32-token inputs exactly from embeddings and recover full names from clinical notes.
[CITATION NEEDED: Song & Raghunathan 2020 (CCS), not opened.]

## 3. How deletion usually works — and what remains

- PostgreSQL: "an UPDATE or DELETE of a row does not immediately remove the old version of the row";
  VACUUM later reclaims it (postgresql.org/docs/current/routine-vacuuming.html, opened 2026-11-01).
- FAISS `remove_ids` is supported for `IndexFlat`, `IndexIVFFlat`, `IDMap`, scans the whole database,
  and is not supported for IVF with an `Array` direct map (FAISS wiki "Special operations on indexes",
  opened 2026-11-01).
- Summaries computed with the deleted vector (centroids, running means) keep its influence; float
  subtraction does not undo it exactly ([B03](../background/B03_floating_point_vs_exact_integers.md)).
- Copies persist in logs, checkpoints and free blocks ([B02](../background/B02_how_databases_store_and_delete.md));
  NIST SP 800-88 Rev. 2 (2025; DOI 10.6028/NIST.SP.800-88r2, landing page opened) is the current media
  sanitization guidance, with "cryptographic erase" among its keywords.

## 4. The ghost, in this project's own numbers

| Measure | Value | Source |
|---|---|---|
| Soft-delete IVF summary distance after deleting a cohort (nq-10k, seed 42) | 5.0e-3 | [DOC: README.md L133] — not in ledger |
| Float running mean, distance from survivors-only mean | 1.9e-8 | [DOC: README.md L133] — not in ledger |
| SEVER-DB | 0 (bit-identical) | [DOC: README.md L133]; survivors check 427,455 groups, 0 failures [DATA: ledger line 38] |
| Soft-delete delete cost vs SEVER-DB (EX-7, nq-100k seed 42) | p50 907 µs vs 109,129 µs; 11 B vs 39,525 B written per deleted record | [DATA: ledger line 186] |

The ghost magnitudes should be re-recorded through a ledgered run before publication [TODO: author].

## 5. Problem statement (for the report)

Design and evaluate a vector database in which (1) deleting a vector returns its group exactly to the
never-inserted state, (2) this survives crashes with all-or-nothing multi-record deletion, (3) every
deletion yields a certificate any third party can verify offline, and (4) nothing deleted is recoverable
from raw storage after acknowledgement — and measure the cost.

## Key points to remember

- Legal rights exist; technical proof of deletion is missing in common systems.
- Embeddings can leak text; logical deletion leaves bytes and influence behind.
- SEVER-DB's numbers: 0 ghost in its own index, at a large per-delete cost.
