# Citations notes (research librarian pass, accessed 2026-11-01)

STATUS: INCOMPLETE. The research session hit the tool usage limit (resets 00:10 UTC) part-way through.
Only the items in section A were actually opened with WebFetch in this session. Everything in section B
was NOT opened here: it is listed only so it is not lost, and each needs [CITATION NEEDED] until opened.
Tasks 3 (vector-DB deletion docs), 4 (verifiable-deletion related work) and 5 (learning resources) were
NOT done at all. Nothing in this file about those topics should be treated as researched.
Several fetches also timed out or returned 502 (rfc-editor.org, EUR-Lex); data fetched from
datatracker.ietf.org instead.

## 0. References already in the repo (where they appear)

- docs/SEVER-DB_PROJECT_OVERVIEW.md section 20 "References" ([R1]-[R55]) is the main list, "links checked 27 Sep 2026".
  Covers: RFC 2119, 9380, 9496, 9162, 8032, 8452, 2104, 6979; Pedersen CRYPTO '91 (R6); Schnorr 1991 (R7);
  Fiat-Shamir (R8); Okamoto (R9); Camenisch-Stadler (R10); Merlin (R11); NIST SP 800-88 Rev. 2 (R21);
  Boneh-Lipton 1996 (R22); Reardon-Basin-Capkun SoK 2013 (R23); Reardon et al. CCS 2013 (R24); Wei et al. FAST 2011 (R25);
  Hao-Clarke-Zorzo eprint 2014/364 (R26); Garg-Goldwasser-Vasudevan EUROCRYPT 2020 (R27); Naor-Teague (R28);
  Bourtoule et al. (R51); Jegou PQ TPAMI 2011 (R36); Faiss (R37); Kwiatkowski NQ (R43); BEIR (R44); SciQ (R45); SBERT + MiniLM (R46).
- Overview lines ~205-212 (secure deletion / verifiable deletion paragraph) cite R21-R27.
- docs/SEVER-DB_SPECIFICATION.md lines 46, 78, 619-626: RFC 2119, 9162, 9496, 9380, 2104, 8032, 8452.
- docs/SEVER-DB_BUILD_PLAN_PART_3-4.md lines 48, 111, 142, 166, 454: RFC 9162, 9380, 9496, 8032, 8452.
- README.md line 233: RFC 9162.
- No arXiv/GDPR/DPDP citations found by my grep in spec/build plans; GDPR and DPDP are not in the repo reference list.
- NOTE discrepancy: the task brief says NIST SP 800-88 Rev. 1; the repo cites Rev. 2. I checked: Rev. 1 (Dec 2014) was withdrawn
  26 Sep 2025 and superseded by Rev. 2. Cite Rev. 2 (and Rev. 1 only as historical).
- NOTE: the repo says Rev. 2 "singles out" cryptographic erase as a mechanism. I did NOT verify that sentence against the
  Rev. 2 text; the NIST landing page only lists "cryptographic erase" as a keyword. Check the PDF before repeating that claim.

## A. VERIFIED (opened) , 15 items

### Transparency logs, witnesses
- **RFC 9162** , B. Laurie, E. Messeri, R. Stradling, "Certificate Transparency Version 2.0", RFC 9162, Experimental, 2021.
  https://www.rfc-editor.org/rfc/rfc9162 . Accessed 2026-11-01. VERIFIED (opened; first 100,000 of 136,139 chars read).
  Supports: public append-only Merkle-tree logs with inclusion and consistency proofs (the log format SEVER-DB uses).
  Caveat: status is Experimental, not Standards Track.
- **RFC 6962** , B. Laurie, A. Langley, E. Kasper, "Certificate Transparency", RFC 6962, Experimental, June 2013.
  https://datatracker.ietf.org/doc/html/rfc6962 . Accessed 2026-11-01. VERIFIED (opened via datatracker).
  Supports: the original CT design; page states it is obsoleted by RFC 9162.
- **C2SP tlog-witness** , "Transparency Log Witness Protocol", C2SP specification (no authors named on the page; editor's copy).
  https://github.com/C2SP/C2SP/blob/main/tlog-witness.md (stable rendering stated as c2sp.org/tlog-witness). Accessed 2026-11-01. VERIFIED (opened).
  Supports: HTTP protocol where a log submits a checkpoint with a consistency proof and a witness returns a timestamped cosignature.
- **C2SP tlog-cosignature** , "Transparency Log Cosignatures", C2SP specification.
  https://github.com/C2SP/C2SP/blob/main/tlog-cosignature.md . Accessed 2026-11-01. VERIFIED (opened).
  Supports: defines checkpoint and subtree cosignatures; signing algorithms ML-DSA-44 and Ed25519.
  Quote: "A cosignature is a statement by a cosigner that it verified the consistency" of a log hash.

### Cryptographic standards
- **RFC 9380** , A. Faz-Hernandez, S. Scott, N. Sullivan, R. S. Wahby, C. A. Wood, "Hashing to Elliptic Curves", RFC 9380, Informational (IRTF), August 2023.
  https://datatracker.ietf.org/doc/html/rfc9380 . Accessed 2026-11-01. VERIFIED (opened). Supports: hash-to-curve (deriving the second Pedersen generator H).
- **RFC 9496** , H. de Valence, J. Grigg, M. Hamburg, I. Lovecruft, G. Tankersley, F. Valsorda, "The ristretto255 and decaf448 Groups", RFC 9496, Informational (IRTF), December 2023.
  https://datatracker.ietf.org/doc/html/rfc9496 . Accessed 2026-11-01. VERIFIED (opened). Supports: ristretto255 prime-order group and canonical 32-byte encoding.
- **RFC 8032** , S. Josefsson, I. Liusvaara, "Edwards-Curve Digital Signature Algorithm (EdDSA)", RFC 8032, Informational (IRTF), January 2017.
  https://www.rfc-editor.org/info/rfc8032 . Accessed 2026-11-01. VERIFIED (opened; first 100,000 of 117,253 chars). Supports: Ed25519 signatures on certificates and checkpoints.
- **RFC 8452** , S. Gueron, A. Langley, Y. Lindell, "AES-GCM-SIV: Nonce Misuse-Resistant Authenticated Encryption", RFC 8452, Informational (IRTF), April 2019.
  https://datatracker.ietf.org/doc/html/rfc8452 . Accessed 2026-11-01. VERIFIED (opened). Supports: the AEAD used for encrypted storage. The brief says AES-256-GCM-SIV; I did not check the RFC for the 256-bit variant (the RFC does define AEAD_AES_256_GCM_SIV per my background knowledge, UNVERIFIED here).
- **RFC 3394** , J. Schaad, R. Housley, "Advanced Encryption Standard (AES) Key Wrap Algorithm", RFC 3394, Informational, September 2002.
  https://datatracker.ietf.org/doc/html/rfc3394 . Accessed 2026-11-01. VERIFIED (opened). Relevance to SEVER-DB NOT established: I did not check whether the spec uses key wrap; only cite if it does.
- **Merlin transcripts** , H. de Valence (design input I. Lovecruft, O. Andreev), "Merlin: a STROBE-based transcript construction for zero-knowledge proofs".
  https://merlin.cool . Accessed 2026-11-01. VERIFIED (opened; website, no year). Supports: Fiat-Shamir transcript construction (repo Overview [R11]).

### Media sanitization, law
- **NIST SP 800-88 Rev. 2** , R. Chandramouli, E. Hibbard, "Guidelines for Media Sanitization", NIST SP 800-88r2, final 26 Sep 2025. DOI 10.6028/NIST.SP.800-88r2.
  https://csrc.nist.gov/pubs/sp/800/88/r2/final . Accessed 2026-11-01. VERIFIED (opened, landing page only). Supports: current NIST sanitization guidance; "cryptographic erase" appears in its keywords.
- **NIST SP 800-88 Rev. 1** , R. Kissel, A. Regenscheid, M. Scholl, K. Stine, "Guidelines for Media Sanitization", Dec 2014, DOI 10.6028/NIST.SP.800-88r1. WITHDRAWN 26 Sep 2025, superseded by Rev. 2.
  https://csrc.nist.gov/pubs/sp/800/88/r1/final . Accessed 2026-11-01. VERIFIED (opened). Historical only.
- **GDPR Article 17** , Regulation (EU) 2016/679, Art. 17 "Right to erasure". Opened via the UNOFFICIAL mirror https://gdpr-info.eu/art-17-gdpr/ (accessed 2026-11-01).
  Quote (<=25 words): "The data subject shall have the right to obtain from the controller the erasure of personal data concerning him or her".
  The official EUR-Lex page returned empty content, so the OFFICIAL text is NOT verified: cite EUR-Lex (CELEX 32016R0679) once opened. [CITATION NEEDED for official OJ reference]

### Vector search
- **Johnson, Douze, Jegou** , "Billion-scale similarity search with GPUs", arXiv:1702.08734, submitted 28 Feb 2017 (arXiv metadata: no journal ref listed).
  https://arxiv.org/abs/1702.08734 . Accessed 2026-11-01. VERIFIED (opened). The IEEE Trans. Big Data publication details (the brief says IEEE TBD) were NOT confirmed; cite as arXiv preprint unless confirmed.
- **Douze et al.** , M. Douze, A. Guzhva, C. Deng, J. Johnson, G. Szilvasy, P.-E. Mazare, M. Lomeli, L. Hosseini, H. Jegou, "The Faiss library", arXiv:2401.08281, first submitted 16 Jan 2024 (page shows a revised version of Oct 2025).
  https://arxiv.org/abs/2401.08281 . Accessed 2026-11-01. VERIFIED (opened). Supports: Faiss, IVF/PQ indexes background.

## B. COULD NOT VERIFY (not opened in this session) , all [CITATION NEEDED]

Springer DOIs redirected to a login/authorize page, so these were not opened:
- Pedersen, "Non-interactive and information-theoretic secure verifiable secret sharing", CRYPTO '91, https://doi.org/10.1007/3-540-46766-1_9 (as listed in repo R6). [CITATION NEEDED]
- Schnorr, "Efficient signature generation by smart cards", J. Cryptology 4, 1991, https://doi.org/10.1007/BF00196725 (repo R7). [CITATION NEEDED]
From the repo reference list only (not opened; check each before use): Fiat-Shamir 1986 (R8); Okamoto 1992 (R9); Camenisch-Stadler 1997 (R10);
Boneh-Lipton 1996 (R22); Reardon-Basin-Capkun 2013 (R23); Reardon et al. CCS 2013 (R24); Wei et al. FAST 2011 (R25);
Hao-Clarke-Zorzo (R26); Garg-Goldwasser-Vasudevan 2020 (R27); Bourtoule et al. 2021 (R51); Jegou et al. PQ TPAMI 2011 (R36);
Kwiatkowski et al. NQ TACL 2019 (R43); Welbl et al. SciQ (R45); Reimers-Gurevych SBERT + all-MiniLM-L6-v2 card (R46); BEIR (R44).
Requested but absent from the repo and not looked up: India DPDP Act 2023 (official gazette/MeitY); Merkle 1987/1979; CONIKS (USENIX Security 2015);
Google Key Transparency; Sigsum (fetch attempt cut off by the usage limit); Cao and Yang 2015; Morris et al. 2023 (vec2text); Song and Raghunathan 2020;
Lewis et al. 2020 (RAG); Eisenhofer et al. 2022; RFC 6979/2104/2119 (cited in repo, not opened); EUR-Lex GDPR official text.
NOT STARTED: task 3 (FAISS/Milvus/pgvector/Qdrant/Weaviate/Pinecone/Chroma deletion docs and quotes), task 4 (verifiable-deletion related-work search;
I make NO claim about novelty or absence of similar work), task 5 (learning resources).

## C. BibTeX (verified items only)

```bibtex
@techreport{rfc9162,
  author = {Laurie, B. and Messeri, E. and Stradling, R.},
  title = {Certificate Transparency Version 2.0},
  institution = {IETF},
  type = {RFC},
  number = {9162},
  year = {2021},
  note = {Experimental. \url{https://www.rfc-editor.org/rfc/rfc9162}}
}
@techreport{rfc6962,
  author = {Laurie, B. and Langley, A. and Kasper, E.},
  title = {Certificate Transparency},
  institution = {IETF},
  type = {RFC},
  number = {6962},
  year = {2013},
  note = {Experimental; obsoleted by RFC 9162. \url{https://datatracker.ietf.org/doc/html/rfc6962}}
}
@techreport{rfc9380,
  author = {Faz-Hern{\'a}ndez, A. and Scott, S. and Sullivan, N. and Wahby, R. S. and Wood, C. A.},
  title = {Hashing to Elliptic Curves},
  institution = {IRTF},
  type = {RFC},
  number = {9380},
  year = {2023},
  note = {\url{https://datatracker.ietf.org/doc/html/rfc9380}}
}
@techreport{rfc9496,
  author = {de Valence, H. and Grigg, J. and Hamburg, M. and Lovecruft, I. and Tankersley, G. and Valsorda, F.},
  title = {The ristretto255 and decaf448 Groups},
  institution = {IRTF},
  type = {RFC},
  number = {9496},
  year = {2023},
  note = {\url{https://datatracker.ietf.org/doc/html/rfc9496}}
}
@techreport{rfc8032,
  author = {Josefsson, S. and Liusvaara, I.},
  title = {Edwards-Curve Digital Signature Algorithm ({EdDSA})},
  institution = {IRTF},
  type = {RFC},
  number = {8032},
  year = {2017},
  note = {\url{https://www.rfc-editor.org/info/rfc8032}}
}
@techreport{rfc8452,
  author = {Gueron, S. and Langley, A. and Lindell, Y.},
  title = {{AES-GCM-SIV}: Nonce Misuse-Resistant Authenticated Encryption},
  institution = {IRTF},
  type = {RFC},
  number = {8452},
  year = {2019},
  note = {\url{https://datatracker.ietf.org/doc/html/rfc8452}}
}
@techreport{rfc3394,
  author = {Schaad, J. and Housley, R.},
  title = {Advanced Encryption Standard ({AES}) Key Wrap Algorithm},
  institution = {IETF},
  type = {RFC},
  number = {3394},
  year = {2002},
  note = {\url{https://datatracker.ietf.org/doc/html/rfc3394}}
}
@techreport{nist80088r2,
  author = {Chandramouli, Ramaswamy and Hibbard, Eric},
  title = {Guidelines for Media Sanitization},
  institution = {NIST},
  type = {Special Publication},
  number = {800-88 Rev. 2},
  year = {2025},
  doi = {10.6028/NIST.SP.800-88r2},
  note = {\url{https://csrc.nist.gov/pubs/sp/800/88/r2/final}}
}
@techreport{nist80088r1,
  author = {Kissel, Richard and Regenscheid, Andrew and Scholl, Matthew and Stine, Kevin},
  title = {Guidelines for Media Sanitization},
  institution = {NIST},
  type = {Special Publication},
  number = {800-88 Rev. 1},
  year = {2014},
  doi = {10.6028/NIST.SP.800-88r1},
  note = {Withdrawn 26 September 2025. \url{https://csrc.nist.gov/pubs/sp/800/88/r1/final}}
}
@misc{c2sptlogwitness,
  title = {Transparency Log Witness Protocol},
  howpublished = {C2SP specification (tlog-witness)},
  note = {\url{https://github.com/C2SP/C2SP/blob/main/tlog-witness.md}, accessed 2026-11-01}
}
@misc{c2sptlogcosignature,
  title = {Transparency Log Cosignatures},
  howpublished = {C2SP specification (tlog-cosignature)},
  note = {\url{https://github.com/C2SP/C2SP/blob/main/tlog-cosignature.md}, accessed 2026-11-01}
}
@misc{merlin,
  author = {de Valence, Henry},
  title = {Merlin: a {STROBE}-based transcript construction for zero-knowledge proofs},
  howpublished = {\url{https://merlin.cool}},
  note = {Accessed 2026-11-01}
}
@misc{gdpr2016art17,
  title = {Regulation ({EU}) 2016/679 (General Data Protection Regulation), Article 17: Right to erasure},
  note = {Text read via unofficial mirror \url{https://gdpr-info.eu/art-17-gdpr/}, accessed 2026-11-01. Replace with the EUR-Lex official citation once opened.}
}
@misc{johnson2017billion,
  author = {Johnson, Jeff and Douze, Matthijs and J{\'e}gou, Herv{\'e}},
  title = {Billion-scale similarity search with {GPUs}},
  year = {2017},
  eprint = {1702.08734},
  archivePrefix = {arXiv},
  url = {https://arxiv.org/abs/1702.08734}
}
@misc{douze2024faiss,
  author = {Douze, Matthijs and Guzhva, Alexandr and Deng, Chengqi and Johnson, Jeff and Szilvasy, Gergely and Mazar{\'e}, Pierre-Emmanuel and Lomeli, Maria and Hosseini, Lucas and J{\'e}gou, Herv{\'e}},
  title = {The Faiss library},
  year = {2024},
  eprint = {2401.08281},
  archivePrefix = {arXiv},
  url = {https://arxiv.org/abs/2401.08281}
}
```
