# Open questions

Every `[NEEDS INPUT: …]` in docs 01–04, plus the decisions those documents leave to the owner. Each
item names where it comes from. Answer them before the numbers or wording go into the paper.

## A. Marked `[NEEDS INPUT]` in the documents

| # | Question | Where |
|---|---|---|
| 1 | Which legal texts (e.g. GDPR Art. 17, India's DPDP Act) the paper will cite as motivation, and from which official sources? Neither the specification nor the overview cites a specific law. | [02](02_project_and_method.md) §1 |
| 2 | How should the paper describe the human/AI division of work? Development used Claude Code under `CLAUDE.md`; git records one author for all 436 commits. | [02](02_project_and_method.md) §5.4 |
| 3 | Should the paper list the 20 attack kinds AT-1 … AT-20 (defined in `docs/SEVER-DB_BUILD_PLAN_PART_3-4.md`)? | [03](03_experiments_and_results.md) §4.2 |
| 4 | Why does EX-2's live-record recovery fall to 0 of 20 after rungs 1–3 (and back to 4–16 at rungs 4–5)? Neither the code nor the decision register explains it. | [03](03_experiments_and_results.md) §5.2 |
| 5 | Is the nDCG@10 normalisation (ideal ranking over live judged passages only, so nDCG rises as cohorts are deleted) intended? Should nDCG be reported at all? | [03](03_experiments_and_results.md) §8 |
| 6 | What was the uncommitted change to `crates/sever-format/src/image.rs` when P2-T5 passed (ledger L51)? Should P2-T5 be rerun on a clean tree? | [04](04_limitations_and_paper_outline.md) §2 item 1 |
| 7 | How should the paper state Part 2's freeze status, given no Part 2 fair-testing PASS exists (L72 FAIL) and FT-10 requires one? | [04](04_limitations_and_paper_outline.md) §2 item 7 |
| 8 | Verified related-work citations. The earlier report could not verify Pedersen 1991, Schnorr 1991, Fiat–Shamir, Okamoto, Camenisch–Stadler, Natural Questions, SciQ, BEIR and others (`project_report/17_verification_log.md` §7). | [04](04_limitations_and_paper_outline.md) §5 |
| 9 | Author names, affiliation, target venue and word limit. | [04](04_limitations_and_paper_outline.md) §6 |

## B. Decisions the documents leave open

| # | Question | Why it matters |
|---|---|---|
| 10 | Rerun P3-T4, P3-T5, P3-T9 mutants and P4-T3 on the frozen commit `94d0b24` (DB-116), or report them as results on earlier commits? | About 70 lines of non-test library code changed since those runs ([04](04_limitations_and_paper_outline.md) §2 item 2). |
| 11 | Report P4-T10 as "FAIL, accepted by the owner" (L189), as "PASS" (L220), or both? | The docs report both. |
| 12 | Rerun EX-8 on a larger machine, or report it as not completed? | No result exists; the memory figures are only in DB-114's text. |
| 13 | May the paper cite numbers from untracked files (`artefacts/partition-seed*.json` for P1-T6, `artefacts/demo/idea-nq-10k-seed42.json` for the ghost)? Should they be committed or regenerated under the ledger? | They have no ledger line and no hash in git. |
| 14 | Should the README be corrected (Part 3/4 status, "college HPC", 68 vs 69 requirements, T-5 not met) before the paper links to the repository? | [03](03_experiments_and_results.md) §9 |
| 15 | Is DB-116's "7c3c313 (DB-114)" a typo for `7c445b5`? | [04](04_limitations_and_paper_outline.md) §2 item 10 |
