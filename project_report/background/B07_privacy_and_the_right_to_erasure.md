# B07 · Privacy and the right to erasure

## In simple words

Laws in the EU and India give people a right to have their personal data erased in certain cases. AI
systems make this hard: text is turned into embeddings, copied into indexes, averaged into summaries,
and logged. Research shows embeddings can leak the original text. SEVER-DB is an engineering answer to
"how do we *show* that something was deleted?". This file explains the background, with verified
sources only.

> **Prerequisites.** Embeddings ([B01](B01_vectors_embeddings_and_search.md)); soft delete
> ([B02](B02_how_databases_store_and_delete.md)). Glossary: [personal data](../16_glossary.md#personal-data),
> [right to erasure](../16_glossary.md#right-to-erasure).

## The problem this solves

A company receives an erasure request. Its retrieval-augmented AI stores the person's messages as
embeddings in a vector store. Deleting the row may leave the vector in the index, the centroid, the
write-ahead log and the disk — and the company cannot prove to anyone that it is gone.

## Build up step by step

1. **Personal data** — information relating to an identifiable person. Embeddings of a person's text
   are derived from it.
2. **The right to erasure (EU).** GDPR Article 17: "The data subject shall have the right to obtain
   from the controller the erasure of personal data concerning him or her" — read via the unofficial
   mirror https://gdpr-info.eu/art-17-gdpr/ (accessed 2026-11-01). [CITATION NEEDED: the official
   EUR-Lex text of Regulation (EU) 2016/679 could not be opened.] The right applies on stated grounds
   and has exceptions; this report does not give legal advice.
3. **India — DPDP Act 2023.** Section 12 of the Digital Personal Data Protection Act, 2023 gives a data
   principal rights to correction and erasure of personal data. [CITATION NEEDED: the official India
   Code PDF (https://www.indiacode.nic.in/bitstream/123456789/22037/2/a2023-22.pdf) returned HTTP 403;
   only secondary summaries were seen, and they disagree on when Section 12 comes into force. Verify
   the wording and commencement date from the gazette before citing.]
4. **Embeddings leak text.** Morris, Kuleshov, Shmatikov and Rush, "Text Embeddings Reveal (Almost) As
   Much As Text" (EMNLP 2023, arXiv:2310.06816, opened 2026-11-01) report recovering 92 % of 32-token
   inputs exactly from their embeddings, and recovering full names from clinical notes. So an
   embedding should be treated like the text it came from.
5. **Why deletion is hard in vector stores.** Common systems delete logically first: PostgreSQL docs
   state "an UPDATE or DELETE of a row does not immediately remove the old version of the row"
   (postgresql.org routine-vacuuming, opened 2026-11-01); FAISS `remove_ids` scans the database and is
   unsupported for some IVF direct-map types (FAISS wiki, opened 2026-11-01). Details in
   [R02](../research/R02_related_work.md).
6. **The ghost.** Even after physical removal, summaries (centroids, running means) computed with the
   deleted vector keep its influence; floating-point subtraction does not restore them exactly
   ([B03](B03_floating_point_vs_exact_integers.md)). SEVER-DB measures this as P1-T14 (README values;
   not in the ledger, see [11](../11_results.md)).

## Everyday analogy

*Analogy:* Asking a library to "forget" your book is not just removing it from the shelf: it is also in
the catalogue, the photocopies, and the librarian's summary of "what this shelf is about".
*Where it stops:* a library summary is written by a person; an AI index summary is arithmetic, which
SEVER-DB can make exactly reversible.

## How SEVER-DB addresses it

Exact group sums (no ghost in the index), physical excision (no tombstone), crash-safe all-or-nothing
`delete_user` (one person's records together), a certificate anyone can verify, and crypto-shredding of
every on-disk copy. What it does **not** solve: a dishonest operator who copied data beforehand (L-2),
and legal questions of when erasure is required.

## Key points to remember

- GDPR Art. 17 and DPDP Act 2023 §12 create erasure rights (official texts still to be cited).
- Embeddings can reveal their source text, so they are personal data in practice.
- Many stores delete logically first; summaries keep a trace (the ghost).
- SEVER-DB targets technical, verifiable erasure, not legal compliance by itself.

## Check your understanding

1. *Why treat an embedding as personal data?* — It can be inverted to recover much of the text (Morris et al. 2023).
2. *Does PostgreSQL remove a deleted row immediately?* — No; VACUUM reclaims it later.
3. *Can SEVER-DB prove an operator kept no copy?* — No (L-2).
