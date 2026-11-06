# 17 · Verification log

What was read, skipped and run, which numbers were cross-checked, and what could not be verified.
Work dates: 2026-11-01 (inventory, notes) and 2026-11-06 (writing, verification). Repo HEAD `4a03951`.

## 1. Process

- Phase 1 inventory by direct read-only commands (results in [_notes/inventory.md](_notes/inventory.md)).
- Nine reader sub-agents were started for Phase 2 notes; **eight hit the usage limit** before finishing.
  Notes saved anyway: part1, part2, part3, testing, interfaces, repomap, history, citations (partial).
  Never written: part4, results, style — those sections were researched directly by reading code and
  data. At the owner's request no further sub-agents were used.
- All final documents were written by the main session from the notes plus direct re-reads.

## 2. Files read (main session, beyond the notes)

CLAUDE.md; docs/PROGRESS.md; README.md (whole); docs/SEVER-DB_SPECIFICATION.md §1–§8, §12.8–§13.5,
§14.7 (headings of all); docs/SEVER-DB_PROJECT_OVERVIEW.md DB-112 … DB-114, EX table, T table, line 1061;
Cargo.toml; rust-toolchain.toml; pyproject.toml; deny.toml (head); rustfmt.toml; clippy.toml;
.cargo/config.toml; crates/README.md; verifier/ and audit/ manifests; fuzz*/ and spikes manifests;
crates/sever-quant/src/lib.rs L20-L80; crates/sever-types/src/constants.rs (greps), error.rs L30-L60,
L155-L170; crates/sever-search/src/kernel.rs L10-L40; crates/sever-index/src/index.rs L825-L836 and
function list; crates/sever-txn/src/protocol.rs L1-L40, L110-L140; crates/sever-erasure/src/participant.rs
L1-L14, L300-L340; crates/sever-seal/src/aead.rs L15-L35; crates/sever-platform/src/lib.rs L69-L120,
rules.rs (greps); crates/sever-scan/src/lib.rs L1-L40; crates/sever-db/src/lib.rs (grep);
configs/experiments.yaml; datasets/PINS.json; docs/RUN_LEDGER.jsonl (all 224 lines parsed);
results/*.json for every result quoted in [11](11_results.md).

## 3. Skipped (never opened)

`target/`, `.venv/`, `artefacts/`, `traces/`, `jobs/`, `datasets/raw|processed` data, fuzz corpora and
artifacts, `studio/work/`, every database or key directory, binaries.

## 4. Commands run (all read-only)

| Command | Result used |
|---|---|
| `git status --short` (start and end) | start: clean except later `?? project_report/`; end: only `?? project_report/` |
| `git log`, `git tag`, `git for-each-ref refs/tags`, `git rev-parse tag^{commit}`, `git branch -vv`, `git rev-list --count origin/main..HEAD` | timeline, tags (annotated tags resolved to commits b1d4576, 7729302, a244264), 53 commits ahead |
| `cargo metadata --format-version 1 --no-deps` | crate list, dependencies, features |
| `git ls-files` + line counts | 1,217 files; Rust 59,523 lines; Python 37,113 |
| Python parsers of Cargo.lock, uv.lock | locked versions |
| Python parsers of the run ledger and results files | every number in 11 |
| `wc -l freeze/*.sha256` | 81 / 250 / 342 / 191 |
| `grep -rln "allow(unsafe_code)"` | only crates/sever-search/src/kernel.rs |
| `grep -c sever-explain|studio/ freeze/*` | 0 everywhere |
| `python3 -c` float demos | B03 numbers (`0.30000000000000004`, `0.20000000000000004`, Q24 values) |
| link and line-range checker over project_report | all links resolve; all `path:Lx-Ly` refs within file length (one out-of-range ref existed only in _notes/part3.md: `crates/sever-crypto/src/lib.rs:L506-L508`, file is 70 lines; not used in final docs) |

Not run (forbidden or not needed): any gate, `scripts/ci.sh`, cargo build/test, fuzzing, mutants,
fair.sh, demos. So the "try it yourself" commands in 08 are **unexecuted**.

## 5. Numbers cross-checked against the ledger

All values in [11_results.md](11_results.md) were computed from the ledger summaries or result files
in this session (ledger line numbers given there). The README-vs-ledger table in 11 lists 5 matches
with rounding, 4 values with no ledger source (P1-T4 10⁷ random pairs, P1-T6 differences, P1-T14 ghost,
P2 "28,707 generic-record points"), and these mismatches: README status of Parts 3/4 (stale), "college
HPC" (stale), P4 traceability 68/68 vs 69/69, P3-T13 interim vs final timings, and omission of T-5 not met.

## 6. Spot checks of code references

Re-read after writing: verifier/src/verify.rs L191-L194 (step 6 branch), crates/sever-crypto/src/generators.rs
L17-L19, crates/sever-log/src/checkpoint.rs L13-L17 (5 witnesses, threshold 4, SB-20 cfg),
crates/sever-search/src/lib.rs L39-L41, crates/sever-index/src/index.rs L141-L143,
tests/architecture/test_architecture.py L117 — all match the claims. Code references taken from the
sub-agent notes were checked for existence and line range only, not all for content [INFERRED risk: a
few line ranges may be off by a few lines].

Corrections made during verification: a paraphrased Rust excerpt in 05 replaced with the exact lines;
a wrong excerpt comment in 09 replaced with the real lines; coverage threshold wording in 11 corrected
to `COVERAGE_MIN = 0.95`; the sub-agent's tag hashes (tag objects) corrected to commit hashes; the final
engine type corrected to `FinalEngine = Engine<CommitmentExtension, AeadSealer>` plus participants.

## 7. Citations

Verified by opening (2026-11-01 by the research agent, 2026-11-06 by the main session): RFC 9162, 6962,
9380, 9496, 8032, 8452, 3394 (not used), NIST SP 800-88 Rev. 2 and Rev. 1 (landing pages), C2SP
tlog-witness and tlog-cosignature, merlin.cool, GDPR Art. 17 (unofficial mirror), Johnson et al. 2017,
Douze et al. 2024, FAISS wiki, PostgreSQL VACUUM docs, Milvus delete page, Morris et al. 2023,
Bourtoule et al. 2021, Reimers & Gurevych 2019, all-MiniLM-L6-v2 model card, SQLite WAL, Python float
tutorial, Hypothesis docs, Rust book, PyO3 guide, transparency.dev.

`[CITATION NEEDED]` (not verified): official EUR-Lex GDPR text; DPDP Act 2023 official text and §12
commencement (India Code PDF returned 403); Pedersen 1991; Schnorr 1991; Fiat–Shamir; Okamoto;
Camenisch–Stadler; Boneh–Lipton 1996; Reardon et al. SoK 2013; Wei et al. FAST 2011; Hao et al.;
Garg et al. 2020; Cao & Yang 2015; Eisenhofer et al.; Song & Raghunathan 2020; Lewis et al. 2020 (RAG);
Natural Questions; SciQ; BEIR; Jégou PQ; CONIKS; Sigsum; Merkle; Milvus internal delete/compaction;
Qdrant/Weaviate/Pinecone/Chroma; pgvector. The NIST Rev. 2 "singles out crypto erase" sentence in the
repo overview was not checked against the PDF.

No novelty claim is made; the related-work search was incomplete.

## 8. Beginner check

Done mechanically: every glossary link used in the docs resolves (script, 0 missing anchors); every
project and background file has "In simple words", "Prerequisites", "The problem this solves", an
analogy, "Key points" and "Check your understanding", and every flow file has a Mermaid diagram.
**Deviation:** the research files R03–R10 and 15 use purpose-specific formats (tables, paper draft,
BibTeX, Q&A) instead of the ten-part structure of §2 of the prompt; R01, R02 have only part of it.
A full human read-through "as a beginner" was not performed line by line [TODO: author].

## 9. Claims that could not be verified

- Ghost magnitudes (P1-T14) — README only.
- P1-T6 oracle differences, P1-T4 10⁷ random kernel pairs, P2 28,707 generic points — README only.
- Interim P4-T3 "16/16 runs" — PROGRESS/README only.
- Which coverage tool flags and exact thresholds per crate for P3-T9 beyond Build 3-4 §1.9 — doc only.
- Whether `docs/PROOFS_P3.md`/`P4.md` would show all proofs holding if regenerated — not run.
- Studio feature claims — from notes on its README and code headers; not run.

## 10. git status at the end

Only `?? project_report/` — no file outside `project_report/` was changed.
