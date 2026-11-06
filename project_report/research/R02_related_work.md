# R02 · Related work

## In simple words

This file groups the work SEVER-DB builds on or differs from. Only sources opened in this session are
cited as verified; everything else is marked `[CITATION NEEDED]`. **A systematic literature search on
"verifiable deletion in vector databases" was not completed**, so no novelty claim is made here.

> **Prerequisites.** [B04](../background/B04_cryptography_basics.md), [B07](../background/B07_privacy_and_the_right_to_erasure.md).

## 1. How vector stores and databases delete (official documentation, opened 2026-11-01)

| System | What its documentation says | Source |
|---|---|---|
| FAISS | `remove_ids` supported for `IndexFlat`, `IndexIVFFlat`, `IDMap`; scans the whole database; unsupported for IVF with an `Array` direct map ("all the indices would be shifted") | github.com/facebookresearch/faiss/wiki/Special-operations-on-indexes |
| PostgreSQL (and so pgvector tables) | "an UPDATE or DELETE of a row does not immediately remove the old version of the row"; VACUUM reclaims dead versions later | postgresql.org/docs/current/routine-vacuuming.html |
| Milvus | the delete page only says entities can be deleted by filter or primary key; internal behaviour (marking, compaction) is not described there | milvus.io/docs/delete-entities.md [CITATION NEEDED: a Milvus architecture page on delete + compaction] |
| Qdrant, Weaviate, Pinecone, Chroma | not checked | [CITATION NEEDED] |

pgvector itself was not opened; the statement above is about PostgreSQL heap tables
[INFERRED: pgvector stores vectors in ordinary PostgreSQL tables — CITATION NEEDED].

## 2. Vector search

Johnson, Douze, Jégou, "Billion-scale similarity search with GPUs", arXiv:1702.08734 (2017, opened);
Douze et al., "The Faiss library", arXiv:2401.08281 (2024, opened). Sentence-BERT: Reimers & Gurevych,
EMNLP 2019, arXiv:1908.10084 (opened). all-MiniLM-L6-v2 maps text "to a 384 dimensional dense vector
space" (Hugging Face model card, opened). [CITATION NEEDED: Jégou et al. product quantization, TPAMI
2011; Kwiatkowski et al. Natural Questions, TACL 2019; Welbl et al. SciQ 2017; BEIR.]

## 3. Machine unlearning

Bourtoule et al., "Machine Unlearning", IEEE S&P 2021 (arXiv:1912.03817, opened): SISA training limits
each data point's influence so removal is cheaper. Unlearning targets *trained model parameters*;
SEVER-DB targets an *index's stored state*, where exact removal is possible by arithmetic.
[CITATION NEEDED: Cao & Yang 2015; Eisenhofer et al. 2022 verifiable unlearning.]

## 4. Verifiable / provable deletion

The repository's overview cites Hao–Clarke–Zorzo (eprint 2014/364) and Garg–Goldwasser–Vasudevan
(EUROCRYPT 2020) on deletion definitions and verification [DOC: Overview §20 R26, R27] —
[CITATION NEEDED: not opened in this session].

## 5. Transparency logs and witnesses

RFC 6962 (2013) and RFC 9162 (2021, Experimental) define Certificate Transparency's Merkle logs with
inclusion and consistency proofs (both opened). C2SP tlog-witness and tlog-cosignature specify witness
cosigning of checkpoints (opened). transparency.dev describes tamper-evident logs and their uses
(opened). [CITATION NEEDED: CONIKS (USENIX Security 2015), Sigsum, Merkle 1987.]

## 6. Commitments, proofs and signatures

RFC 9496 (ristretto255), RFC 9380 (hashing to curves), RFC 8032 (EdDSA), Merlin transcripts (merlin.cool)
— all opened. [CITATION NEEDED: Pedersen CRYPTO '91 (doi 10.1007/3-540-46766-1_9, Springer page not
reachable); Schnorr J. Cryptology 1991; Fiat–Shamir 1986; Okamoto 1992; Camenisch–Stadler 1997.]

## 7. Crypto-shredding and media sanitization

RFC 8452 (AES-GCM-SIV, opened). NIST SP 800-88 Rev. 2 (2025, landing page opened; Rev. 1 withdrawn
26 Sep 2025). [CITATION NEEDED: Boneh & Lipton 1996 "A revocable backup system"; Reardon, Basin, Čapkun
"SoK: Secure Data Deletion" (IEEE S&P 2013); Wei et al. "Reliably erasing data from flash-based SSDs"
(FAST 2011).]

## 8. Comparison table

| Approach | Guarantees | Misses | How SEVER-DB differs (evidence) |
|---|---|---|---|
| Logical delete + later compaction (PostgreSQL VACUUM; FAISS `remove_ids` where supported) | record no longer returned | bytes until clean-up; summaries keep influence; no external proof | physical excision + exact integer sums; survivors check 0 failures [DATA: ledger line 38] |
| Machine unlearning (SISA) | cheaper retraining without the data | targets models, not an index; no third-party receipt | exact arithmetic on index state; signed certificate |
| Transparency logs (CT) | tamper-evident append-only history | not about deletion of content | log used to pin inserts/deletes; certificate verified offline [DATA: line 206] |
| Crypto-shredding / NIST crypto erase | old ciphertext unreadable once key destroyed | needs correct key management and in-place key overwrite | per-deletion key rotation with phase A/C and recovery rule; 0 forensic findings [DATA: line 159] |
| SEVER-DB | exact, crash-safe, verifiable, crypto-shredded deletion | simulated witnesses; operator holds keys (L-2, L-7, L-27); ~75–110 ms and ~39 KB per delete | — |

## Key points to remember

- Mainstream stores document logical-then-physical deletion; none of the opened pages offer a third-party proof.
- SEVER-DB combines known primitives; whether the combination is new needs a proper literature search.
