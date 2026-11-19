# 05 · Discrepancies, gaps and limitations (audit)

Labels: OBSERVED, CLAIMED, INFERRED, as in 01. IDs D1… are referenced by 02 and 03.

## 1. Conflicts between sources

| ID | Topic | Source A (value, date) | Source B (value, date) | Ruling and why |
|---|---|---|---|---|
| **D1** | **EX-8 (P4-T15), memory and recovery at 10^6 vectors** | CLAIMED: overview DB-114:1142 and PROGRESS.md:21 (31 Oct / 1 Nov) say "killed by the out-of-memory killer at 10.39 GB after 6 h 11 min"; "not completed, no result" | OBSERVED: `docs/RUN_LEDGER.jsonl` has **no p4-ex8 row at all**, and there is **no results file**. `traces/hpc-p4-ex8.log` holds only its two header lines. `hpc-run.out` logs 4 START lines and no `rc=`. Owner (9 Nov 2026, this session): "not failed but more like never runned due to device constraints" | **EX-8 was not run to completion because of the laptop's memory limits, and produced no measurement.** It must not be reported as a failure, and it has no number. The prose OOM figures (10.39 GB, 6.4–6.9 GB) are E1, with no raw memory log found. The ~3.8 GB figure is an Appendix A *prediction*. P4-T15 is a measure, not a gate, so no exit gate depends on it (CLAIMED, DB-114). The separate nq-1m **recall** measure (EX5, P1-T7, L180) did run and gave 1.0 |
| D2 | T-5 outcome | README.md (2026-10-31): Part 4 results list no T-5 or EX-6 entry | `results/p4-ex6-…json` (2026-10-30): `t5_met: false`; recomputed: 0 of 5 seeds ≤ 0.005. docs/03 and project_report/11 report "not met" | **Target missed** (E4). The README omits it |
| D3 | Which results are on the final engine | DB-116 (1 Nov): "The changed code is covered by the full suites above and the red-first regression tests" | OBSERVED (freshness.csv): on 1 Nov the sources of sever-cert, sever-log and sever-erasure changed (a35c5c2, c629c6a, d5e41db, 09ecb78). Every P3-T4, P3-T5, P4-T1/T2, P4-T3, fuzz, P3-T13, EX-6 and EX-7 result predates this | **SETTLED (9 Nov, code diff).** The results are on the pre-final build. `git diff 7c445b5 94d0b24` changes production code in 4 files and about 70 lines: sever-cert `encoding.rs` and `participant.rs`, sever-log `store.rs`, sever-erasure `store.rs`. All of it adds refusals (`IntegrityViolation`) when stores are opened, recovered or checked: a certificate's checkpoint missing from the log (BH-7), a sealed segment cut short (BH-6), a lost checkpoint store (BH-9). No line changes the insert, delete, key-rotation, sealing or erasure write paths (OBSERVED in the diff). INFERRED: the pre-final T-1/T-2 results still describe the final build's write and erase behaviour. What the final build adds is refusal of damaged stores. That refusal is covered by the final-commit check suites (L196, L198) and by the partial final-commit crash run (D4: 0 refusals) |
| D4 | P4-T3 on the final commit | DB-116: "p4-crash-a ran 1.9 h … about 4,900 crash points each; 0 mismatches, 0 bad certificates" | Ledger L211 has only `started`. `traces/final-p4-crash-a.log`: `rc=stopped (owner decision 1 Nov, partial)`. No result file | **SETTLED (9 Nov, raw data found).** The stopped run left per-point records: `traces/p4-crash-nq-10k-seed{42,123,777}.jsonl` plus `.progress`, mtimes 13:00:39–13:01:20 on 1 Nov, matching `final-p4-crash-a.log` (commit 94d0b24). Recomputed (`recompute/recompute_p4crash_partial.out`): **14,784 crash points** (4,910 + 4,961 + 4,913) over operations 17,694–17,787 / 17,791 / 17,788. That is 94, 98 and 95 of the window's 300 operations. Kinds: step 12,136, keytear 2,552, offset 81, random 15. Every failure counter in the progress summaries is 0 (mismatches, not-oracle states, bad certificates, refusals, stale key slots, unreadable records); E3. Key-loss injection had not yet run (0 injected). DB-116's "about 4,900 crash points each; 0 mismatches, 0 bad certificates" is **confirmed** |
| D5 | DB-116's not-rerun list | overview:1061: "Not rerun on the final commit: the rest of p4-crash-a, p4-crash-b, p3-mutants, p4-mutants, p3-replay and p3-crash; their last results are on 7c3c313" | (a) p4-mutants **was** rerun: L220 PASS, 2026-11-01T17:50, commit 77ca977 (started at e00e31d, L218). (b) The cited 7c3c313 is a docs commit. The actual result commits are 7c445b5, 11f00f2 (ran) / fd40dfe (logged), 9e11156 and 96f9370. (c) The list omits p4-forensics, p3-fuzz, p4-fuzz, p3-measures, p4-ex6, p4-ex7 and p4-quant-recall, which also did not rerun | The ledger wins (E3). DB-116 is incomplete and miscites a commit |
| D6 | README Part 3 numbers | README.md:301–307 (last commit 10-31): P3-T4 145,919 / 76,852; P3-T5 seed 42; P3-T10 10^7; P3-T13 prove 12.2 ms, verify 2.2 ms; coverage verifier 95.2 % | Ledger final runs: 938,129 / 192,964 (L144); 5 seeds (L148); 10^8 (L162); prove 15.78 ms, verify 2.74 ms (L182); verifier 0.962707 (L200) | The README holds interim values (19 Oct). Use the ledger values |
| D7 | Where the gates ran | README.md:294–295, :355–356: "on the college HPC" | DB-113 (29 Oct): the HPC is no longer available, so the run is on the laptop. Ledger: one WSL2 kernel throughout; logs named `hpc-*` | Laptop. The README is stale |
| D8 | Part 2 freeze vs FT-10 | CLAUDE.md:272 and FAIR_TESTING.md:52: freeze needs a fair-testing PASS | Ledger: Part 2 fair outcomes are DRY (L68) and FAIL (L72) only. Run 42fc06df has no outcome (L74). Tags part-2-frozen-e1/e2 exist | **SETTLED (9 Nov, git).** The Part 2 freeze commit 23ac9be (2026-10-08 12:41:42) came **6 minutes before** FT-10 was added (f4772a3, 12:47:34, "automated fair testing … required for a freeze (DB-73)"). So the original freeze could not have needed a fair PASS. The errata E-1 and E-2 (15 Oct) re-hashed `freeze/PART-2.sha256` inside their erratum commits (061d785, a244264), after FT-10 existed. They did not pass a Part 2 fair run. Report it as: "Part 2 predates the fair-testing rule and has no fair-testing PASS" |
| D9 | T-4 attack set | Pre-registration (T-4): "100 % of attack certificates rejected" | L103 and L119: the verifier accepted 3 forgeries per run. The generator was then changed (47,000 → 45,282 attacks per seed; AT-2/AT-3/AT-13 donors restricted, CLAIMED docs/03:141–146, commit 59e0a45). G-34 documents the AT-2 property | T-4 passes on the **final** attack set. The paper should say that the set changed after failures and that G-34's weakness remains |
| D10 | Fair-testing planted bugs | CLAUDE.md:263: "a separate session plants blind bugs that the script scores" | Every non-dry `results/fair-*.json` has `planted: []`. The check row is "planted bugs: cargo-mutants gate PASS in the ledger (DB-75)" | Planted-bug scoring was replaced by the mutation gate. CLAUDE.md is stale |
| D11 | Proof counts | README.md:361: "84 proofs" (P4) | `docs/PROOFS_P4.md`: "79 of 79 proofs hold" (run 2026-10-19). `tests/proofs/p4/`: 93 files. `PROOFS_P3.md`: "31 of 31" (2026-10-15), vs 172 files in `tests/proofs/p3/` | No current proof run exists for Parts 3 and 4. Use "UNKNOWN on the final commit" |
| D12 | Part 4 traceability | README.md:361: "68 / 68" | `docs/TRACE_PART_4.md` (2026-10-21): "69 of 69" | The generated file wins (E2). Both are unconfirmed |
| D13 | Hardware and OS | overview:12: "… native Linux". DB-113: "WSL2 Ubuntu 24.04 with 12 GB" | Ledger `wsl: true` in all rows. Today: Ubuntu 26.04 LTS, 11 GiB visible (`free -g`) | The runs were in WSL2. **The owner confirmed Ubuntu 26.04 LTS (9 Nov 2026, `lsb_release`: 26.04, codename resolute).** DB-113's 24.04 is an error. The 12 GB WSL limit and swap state remain CLAIMED |
| D14 | Branch state | PROGRESS.md:35 (6 Nov): Studio branch "pushed and not merged into main" | `main` = `af8fed2` = HEAD (today) | PROGRESS is stale |
| D15 | "Python tests pass" | README.md:362 | Re-run today: the CI invocation passes (271). A plain `pytest -m "not slow"` from the root errors in collection (3 errors in `tests/cleanroom/p4/…`), the same as in `traces/full-checks-635a8c9.log` | Passes only with `--ignore=tests/cleanroom`. The clean-room suites need their own processes (`scripts/ci.sh:43–51`) |
| D16 | EX-6 ground truth | docs/03:218–219: "holding area … excluded from the ground truth of every arm" | Code `ex6.py:193–206`: the exclusion is computed from **SEVER's** holding area and applied to SEVER's truth. FAISS arms index all 10,000 records (`records` 10000 vs 9821 at rung 0, seed 42) | INFERRED fairness issue: the arms' recall is not measured against identical truth sets. The size of the effect is UNKNOWN |
| D17 | Pre-registered corpus sizes | overview EX-6 row (:1233): "Per seed, nq-100k". EX-2 and P4-T9 replay were also planned at nq-100k | Run at nq-10k (L159, L161, L210) by DB-113 (29 Oct, after pre-registration and before these results) | A scope change after pre-registration but before the results. It must be reported |
| D18 | P4-T10 mutation verdict | L189 (31 Oct): outcome FAIL (1 untriaged survivor). DB-114: "accepted as a pass by the owner" | L220 (1 Nov): PASS with 0 untriaged | The final PASS (L220) stands. The accepted FAIL is superseded, but it is part of the history |
| D19 | Ledger commit vs code commit | Ledger row commit for P3-T9 mutants: fd40dfe (L158) | DB-114: "the mutants ran on 11f00f2's code". Also L218 started at e00e31d and L220 finished at 77ca977 | A ledger `commit` can name a docs-only commit after the code that ran. Small risk to freshness rulings |
| D20 | Dirty trees | — | 52 of 224 ledger rows have `git_dirty: true`. They include both fair PASS runs (L215, L224), P1 nq-10k differential (L13), P1-T7 nq-100k (L9) and P3 attacks L141 | **SETTLED (9 Nov, ledger `dirty_paths`).** L215 and L224 (fair PASS): only their own generated report (`docs/audit/FAIRNESS_P3.md`, `…P4.md`). L141: `scripts/hpc/steps.sh`. L13 and L19: demo files under `demo/` and `spikes/`, not engine code. L53: `crates/sever-crashkit/*` (test harness). **L51 (P2-T5): `crates/sever-format/src/image.rs`, engine code, uncommitted.** Later clean-tree replays supersede it (P3-T5 L148, P4-T9 L210). L9 (P1-T7 nq-100k) records no paths, but the nq-1m measure L180 is clean. Every headline run is clean (Q10) |
| D21 | Demo artefact | README P1-T14 (from a demo run) | `artefacts/demo/idea-nq-10k-seed42.json` mtime 2026-11-09 19:51, not in the ledger | Regenerated today outside the ledger. Values agree with the README |

## 2. Stale files and why

| File | Last commit | Why stale |
|---|---|---|
| `README.md` | 1479019, 2026-10-31 | It predates the 1 Nov fixes, freezes and tags. It shows interim P3/P4 numbers and says "HPC". It omits T-5, P3-T4 final, EX-6/EX-7 and the EX-8 status (D2, D6, D7, D11, D12) |
| `docs/PROGRESS.md` | b51404a, 2026-11-06 | The branch merge state is wrong (D14) |
| `CLAUDE.md` §6.1 / §6.4 | — | It says "current part is Part 3", names tag `part-2-frozen` (it does not exist), and describes planted bugs (D10) |
| `docs/PROOFS_P3.md`, `docs/PROOFS_P4.md` | 2026-10-15, 2026-10-19 | Not regenerated after later patches (D11) |
| Overview DB-116 text | 2026-11-01 | Incomplete and miscited not-rerun list (D5) |
| Overview §1 hardware row | — | "native Linux" (D13) |
| `results/` interim and failed runs (for example `p3-*-20261019*`, `p4-*-20261030T2*` FAILs) | — | Superseded by later runs. Kept as history (status STALE-POSSIBLE in MANIFEST) |
| `traces/archive-before-final/`, `traces/archive-pre-laptop-run/`, `docs/archive/` | — | Archived by name. Not used as evidence |
| All Part 3/4 results at or before 7c445b5 / 9e11156 | — | Engine sources changed on 1 Nov (D3) |

## 3. Claims with no raw evidence (E0–E1)

| Claim | Source | Note |
|---|---|---|
| EX-8 memory / recovery at 10^6 | overview EX-8, DB-114 | **Never measured because of device limits** (D1) |
| P4-T3 interim "16 / 16 runs, three windows of 80 operations" | README.md:360 | `traces/p4-interim/` not analysed |
| Chroma spike "3/3 IDs, 6/6 text windows, 3/3 vectors" | DB-119 | No output file |
| Flaky-test fix "old test 98 failures, new 0 in 20,000 runs" | DB-114 | No log |
| EX-8 OOM figures (10.39 GB, 6.8 GB, 9.4 GB spike) | DB-114 | `traces/oomguard.log` not parsed for them |
| "Reference model written from the spec only, never from engine code" | CLAUDE.md §7 | Not verifiable from files. Authorship question (Q1) |
| Groq / LLM assistant behaviour in Studio | DB-119 | No recorded run |

## 4. Experiments and comparisons a reviewer would expect but that do not exist

1. **Real-system baselines.** There is no comparison with production vector databases (Milvus,
   Qdrant, Weaviate, pgvector, LanceDB). The only one is an unrecorded 3-note Chroma spike. The
   FAISS arms in EX-6 and the "softdelete" Part 2 arm in EX-7 are in-house baselines.
2. **Scalability.** There is no throughput, latency or memory curve over N. EX-8 (10^6) produced no
   result, and EX-7 has nq-100k at 1 seed only. The quantisation recall exists at 10^6 (EX5).
3. **Dimension.** Only d = 384 (one encoder). The synthetic fixture uses d = 16.
4. **Concurrency.** There is no multi-client or multi-thread load test; only the P2-T4
   reader-at-every-step test.
5. **Physical crash.** Crashes are simulated (SimVfs). There is no power-cut or kill -9 on real
   storage, and no SSD or controller-cache study. The forensic scan used fuse2fs images with
   `allow_unsafe_fs`, not raw block devices of a real SSD (no wear-levelling or over-provisioning
   study).
6. **Statistical power.** n = 5 seeds. TOST was expected to fail, and it did.
7. **Cost of erasure at scale.** One seed at nq-100k. Timings overlapped other jobs (CLAIMED DB-114).
8. **Independent replication.** Every run is on one laptop by one operator. The clean-room
   AI testing is the only independent check, and it is itself AI.
9. **Search-quality baselines with equal ground truth** (D16). Also missing: a rebuild-SEVER arm and
   tuned FAISS parameters.
10. **Security evaluation beyond the in-house attack register.** There is no external review of
    the cryptographic construction (G-34 is self-reported).

## 5. Failed or missed targets and failed runs (recorded as honestly as successes)

| Item | What happened | Source |
|---|---|---|
| **T-5 (EX-6)** | **Missed on 5 of 5 seeds** (drift 0.0079–0.0130 vs ≤ 0.005) | `p4-ex6-…json`, recomputed |
| **EX-8 (P4-T15)** | **Not run to completion because of device memory limits; no result.** Not a failed measurement | D1 |
| T-1 on the final build | One 300-op window per seed (L164, L192). The final-commit rerun was stopped after 94–98 ops per seed: 14,784 crash points, 0 failures, no key-loss injection reached, no result file (D4) | D4 |
| T-4 history | Verifier accepted forgeries in 2 runs (L103, L119), before generator changes | 03 EX4 |
| P1-T12 fuzz | L18 FAIL: real OOM bug in `artefact_parse` (fixed) | `p1-fuzz-20261005T134622Z.json` |
| P2-T6 fuzz | L43, L45 FAIL (harness: no target built) | results |
| P1/P2 checks | L34 FAIL (sabotage step), L62 FAIL (ruff-format, python-tests, deny) | results |
| P3-T9 coverage | L107 and L115 FAIL (verifier 0.7776, 0.9448) | results |
| P3-T9 mutants | L147 FAIL (verifier mutants never ran; cert 0.8013). L156 FAIL (setup) | results |
| P4-T10 coverage | L179 FAIL (all three crates < 0.95) | results |
| P4-T10 mutants | L170 FAIL (0.7652 / 0.9070 / 0.7793). L189 FAIL accepted by the owner. L220 PASS | results |
| P4-T3 window B | L168 FAIL (harness method check, DB-114 item 5) | results |
| EX-6 first attempt | Crashed (`OverflowError` in the faiss seed, `traces/hpc-p4-ex6.log`). The harness was fixed and EX-6 rerun on 4810d8f (DB-114). Note: the run-all log says "never rerun, Build §2.5", but a rerun on the fix commit was recorded (L161). The stated reason was a harness fault, not a measured miss | hpc-summary.log, L161 |
| Fair testing | 11 non-dry runs: 8 FAIL, 2 PASS (P3, P4), 1 without outcome (P2 42fc06df). Part 2 never passed | 03 EX12 |
| Part 2 known defects | Three defects kept as limit L-28 in the frozen Part 2 builds (CLAIMED PROGRESS.md:13, DB-112). Errata E-4…E-6 were dropped | overview:1171 |

## 6. AI-written documents and their unconfirmed claims

INFERRED from git, style and the session's own notes:
- `docs/01_background_concepts.md`, `02_project_and_method.md`, `03_experiments_and_results.md`
  and `04_limitations_and_paper_outline.md` were added together in one commit, 0d71615 on
  2026-11-09 ("research-paper documentation set").
- `project_report/` (52 files) was added together in 635a8c9 on 2026-11-06. It is described in the
  assistant's own memory notes as written by Claude.
- They use uniform templated tables with `[NEEDS INPUT]` and `[CITATION NEEDED]` placeholders
  (for example docs/03:120, :186).
- **Owner statement (9 Nov 2026): everything in the project was done by AI.**
- The commit author is the owner's name for all commits. The assistant's notes say that Claude
  commits without AI attribution, so **git authorship cannot separate human-written from
  AI-written text or code** (Q1).
- The README, PROGRESS.md, the DB-entries and the ledger runners were probably also written or
  operated by AI sessions (CLAUDE.md "write mode").

**Spot-check of the AI-written results docs against raw data (OBSERVED by this audit).**
docs/03 and project_report/11 agree with every recomputed number this audit checked:
- 343,837 / 321,689 / 17,148 / 5,000
- 938,129 / 914,464 / 18,665 / 192,964
- 226,410 and 5,000
- the per-seed drifts, Welch t = −9.571, p = 0.00015, TOST p = 0.997
- the EX-2 live-record table
- the EX-7 means 75,333 [74,539, 76,381]
- coverage and mutation ratios

Both docs already flag the README's staleness and T-5.

**Unconfirmed in those docs:**
- docs/03 P4-T3 window-B and final-run narrative (E1 parts).
- docs/03:186: the reason for live-record recovery dropping to 0 (`[NEEDS INPUT]`).
- docs/03:25–27: hardware, CLAIMED from DB-113.
- project_report: GDPR/DPDP and the citations of Pedersen, Schnorr and secure-deletion literature
  (`[CITATION NEEDED]`, per its 17_verification_log).
- Any statement about novelty or related work. Nothing in the repo supports these with evidence.

## 7. Questions for the author: answers received and what remains

| # | Question | Status | Answer / consequence |
|---|---|---|---|
| Q1 | Authorship | **ANSWERED** (owner, 9 Nov 2026) | Everything was done by AI. Code, spec, reference model, tests, gate runs and docs. The independence of the reference model (C-18) is session-level, not human. The clean-room fair runs are the strongest independence evidence, and they are AI too |
| Q2 | EX-8 wording | **ANSWERED** (owner, 9 Nov 2026) | "Not run to completion because of device (memory) limits; no result." Not a failure, and no number |
| Q3 | OS at run time | **ANSWERED** (owner, 9 Nov 2026) | Ubuntu 26.04 LTS (`lsb_release`: 26.04, codename resolute). DB-113's "24.04" is wrong. The WSL memory cap and swap state remain CLAIMED |
| Q4 | Part 2 frozen without a fair PASS | Settled by disclosure | Fact from the ledger: there is no Part 2 fair PASS. Report it (D8). Whether FT-10 existed at the time is not material to the results |
| Q5 | Reruns on the final commit | **ANSWERED** (owner, 9 Nov 2026): no reruns | T-1 (final build) and T-2 are reported on the pre-final builds 7c445b5 / 9e11156, with the 1 Nov changes named (D3) |
| Q6 | T-4 attack-set change and G-34 | Settled by disclosure | Report the two failing runs and the generator change as findings (D9) |
| Q7 | EX-6 ground truth | Settled by disclosure | One-sentence caveat (D16). There is no rerun, so the size of the effect stays UNKNOWN |
| Q8 | README's P4-T3 interim "16 / 16 runs" | Settled | Not cited. The ledger gate runs (L164, L192) supersede it |
| Q9 | Chroma spike output | Settled | Not cited as a result. It may appear in the live demo only, labelled as a demonstration |
| Q10 | Dirty-tree runs (52 rows) | Settled by disclosure | The runs that matter for the headline numbers are clean (L56, L144, L148, L159, L161, L164, L192, L206, L208, L210 have `git_dirty: false`). The dirty ones are the two fair PASS runs (L215, L224), early Part 1 runs and P3 attacks L141, which was superseded by clean L206 |

No open questions remain that block the paper.

## 8. Final rulings on every discrepancy

Ruling types:
- **DOC ERROR**: a document is wrong. Cite the ledger or result value instead.
- **DISCLOSE**: the documents agree with the evidence, but the paper must state the fact.
- **SETTLED BY OWNER**: answered on 9 Nov 2026.

| ID | Ruling | What to use in the paper (all values from 03 and 02) |
|---|---|---|
| D1 | SETTLED BY OWNER + DISCLOSE | "EX-8 (memory and recovery at 10^6 vectors) could not be run to completion on the 16 GB laptop and produced no result." Give no memory number. The 10^6 *recall* result (1.0) stands separately |
| D2 | DISCLOSE (README omission) | "T-5 was missed on all five seeds (per-seed drift 0.0079–0.0130 against ≤ 0.005). The confirmatory Welch test shows SEVER-DB's drift is lower than soft-delete IVF's (t = -9.57, p = 0.00015); TOST did not show equivalence (p = 0.997); a rebuilt IVF drifted less (0.0083 against 0.0109)." |
| D3 | DISCLOSE (now characterised by the code diff) | Use a three-tier evidence table. (a) **Final commit 94d0b24:** T-3 replay (L210), T-4 attacks (L206, L208), checks, coverage, spikes, P4 mutants (L220). (b) **Pre-final 7c445b5 / 9e11156 / 11f00f2 / 4810d8f:** T-1 crash campaigns, T-2 forensics, fuzzing, P3 mutants, EX-6, EX-7, P3-T13. (c) **Not run:** EX-8. Between (b) and (a), only refusal checks for damaged stores were added (BH-6/7/9, about 70 lines in 4 files). The write, key-rotation and erasure paths are unchanged (D3). Also cite the partial final-commit crash run: 14,784 points, 0 failures (D4) |
| D4 | SETTLED BY NEW EVIDENCE | "On the final commit, a partial crash campaign (window A, 94–98 of 300 operations per seed, 3 seeds) covered 14,784 crash points with 0 failures before it was stopped." No result file exists; the source is the raw per-point records (copied to results_collected) |
| D5 | DOC ERROR (DB-116 list and commit) | Use the commit list in D3. p4-mutants was rerun (L220 PASS) |
| D6 | DOC ERROR (README interim values) | Use the final ledger values: 938,129 crash points / 192,964 certificates (L144); 5 seeds (L148); 10^8 fuzzing (L162); prove 15.78 ms / verify 2.74 ms medians (L182); final coverage (L200) |
| D7 | DOC ERROR (README "HPC") | "All runs on one laptop (Intel Core Ultra 5 226V, 8 cores, 16 GB) in WSL2, Ubuntu 26.04." |
| D8 | SETTLED BY NEW EVIDENCE | "Parts 3 and 4 passed clean-room AI fair testing (180 and 101 tests, 0 failing). Part 2 was frozen 6 minutes before that rule was introduced and has no fair-testing PASS." (git: 23ac9be 12:41:42 against f4772a3 12:47:34) |
| D9 | DISCLOSE (a strength) | "The attack suite caught real problems: the verifier accepted forgeries in two early runs, one from a generator bug and one from a property of emptied-group proofs (documented as G-34). After the generator change, all 226,410 attacks were rejected on the final build." |
| D10 | DOC ERROR (CLAUDE.md §6.4) | Describe fair testing as: AI tester sessions, AI judge sessions, an oracle re-derivation sample, and planted bugs counted through the cargo-mutants gate (DB-75) |
| D11 | DOC ERROR (README "84 proofs") | Quote the proof reports with their dates (P2 211/211 on 10-08, P3 31/31 on 10-15, P4 79/79 on 10-19), or omit proofs. Do not claim that every proof holds on the final commit |
| D12 | DOC ERROR (README "68 / 68") | Use 69 of 69 (`TRACE_PART_4.md`) |
| D13 | SETTLED BY OWNER | Ubuntu 26.04. Every run was WSL2, not native Linux |
| D14 | DOC ERROR (PROGRESS) | `main` = `af8fed2`. This is not relevant to the paper |
| D15 | DOC ERROR (README "Python tests pass") | "271 Python tests pass (re-run 9 Nov 2026, CI invocation with clean-room suites run separately)." Rust tests were not re-run by the audit; the last recorded pass is inside L198 |
| D16 | DISCLOSE | "SEVER-DB's ground truth excludes records still in its holding area (179 of 10,000 at rung 0, seed 42); FAISS arms are scored over all live records." |
| D17 | DISCLOSE | "EX-2, EX-6 and the final-build replay ran at nq-10k instead of the pre-registered nq-100k because of time limits; P4-T3 crashed one 300-operation window per seed." |
| D18 | DISCLOSE (history only) | Cite L220 PASS. The accepted FAIL L189 is superseded |
| D19 | DISCLOSE (method note) | Ledger commits can name a later docs-only commit. This affects no headline number |
| D20 | SETTLED BY NEW EVIDENCE | The headline runs are clean-tree. One superseded run (P2-T5, L51) had an uncommitted engine file; cite the later replays instead |
| D21 | DISCLOSE | The ghost demo values (P1-T14) come from a demo output outside the ledger. Label them "demonstration" |

**Summary of the rulings (21):**
- **DOC ERROR (8):** D5, D6, D7, D10, D11, D12, D14, D15. The audit docs give the correct values.
- **SETTLED BY NEW EVIDENCE (3):** D4, D8, D20.
- **SETTLED BY OWNER (2):** D1, D13.
- **DISCLOSE (8):** D2, D3, D9, D16, D17, D18, D19, D21.

Every discrepancy is now ruled on, and none blocks the paper.

## 9. Fix log, item by item (9 Nov 2026)

What was done for each discrepancy, and what is now true.

| ID | Action taken | Evidence added | Result |
|---|---|---|---|
| D1 | Recorded the owner's answer. Reworded EX-8 everywhere in the audit as "not run to completion (device memory); no result" | Owner, 9 Nov | Settled |
| D2 | Recomputed T-5, Welch and TOST from per-rung recalls | `recompute/recompute_ex6.out` (all values MATCH) | Fact settled: target missed |
| D3 | Read the production diff 7c445b5..94d0b24 | `git diff` (about 70 production lines in 4 files, refusal checks only) | Settled: nature of the change known |
| D4 | Found and recomputed the stopped final-commit run's raw records | `recompute/recompute_p4crash_partial.py` / `.out`; files copied | Settled: 14,784 points, 0 failures (E3/E4) |
| D5 | Took the correct commit list from the ledger | `recompute/freshness.csv`, ledger L158, L161, L164, L192, L220 | Settled in the audit (03, 02 C46) |
| D6 | Replaced the README's interim values with final ledger values in the audit | 03 EX1, EX3, EX4, EX10; 02 C23–C27 | Settled in the audit |
| D7 | Platform from the ledger and the owner | ledger platform field; owner OS answer | Settled |
| D8 | Dated the freeze against the rule | git 23ac9be against f4772a3 | Settled |
| D9 | Checked the cited fix commits and G-34 | 2cd8b12, 9d1cb3d, 59e0a45 (all 2026-10-19); `docs/SPEC_GAPS.md:41` | Fact settled; to disclose |
| D10 | Fair-run files show `planted: []` and the DB-75 row | `results/fair-*.json` | Settled in the audit |
| D11 | Quoted the proof reports with their dates; no rerun (long, and it would rewrite tracked files) | `docs/PROOFS_P2..P4.md` headers | Settled as "reports dated 10-08 / 10-15 / 10-19; final-commit status unknown" |
| D12 | Used the generated trace file | `docs/TRACE_PART_4.md`: 69 of 69 | Settled in the audit |
| D13 | Recorded the owner's OS answer | `lsb_release` output | Settled |
| D14 | Read the branch state | `git branch -a` | Settled (not relevant to the paper) |
| D15 | Re-ran the Python suite with the CI invocation | `rerun_pytest.log`: 271 passed | Settled |
| D16 | Read the EX-6 code. The effect size needs a rerun with a shared truth set, which was not done (no reruns) | `ex6.py:14,193–206` | Disclose; size UNKNOWN |
| D17 | Scope cuts dated by DB-113 (29 Oct), after pre-registration (27 Sep) and before the results | git; ledger commands | Disclose |
| D18 | The final PASS is L220 | ledger | Settled |
| D19 | Noted where ledger commits name docs-only commits | DB-114; L218/L220 | Disclose (method note) |
| D20 | Read `dirty_paths` of every relevant dirty row | ledger | Settled |
| D21 | The ghost values come from a demo output outside the ledger | `artefacts/demo/idea-nq-10k-seed42.json` | Disclose as a demonstration |

**The only item that can no longer change without a rerun is D16** (the size of the EX-6 truth-set
effect). Every other item is settled or has fixed wording for the paper.

## 10. Repository documents corrected (9 Nov 2026)

At the owner's request, the 8 DOC ERROR items were fixed in the repository itself, together with
the stale OS, EX-8, T-5, final-commit-crash and authorship statements. The fix is on branch
`docs-audit-final`, commit `20f9747` ("docs: settle the documents against the evidence audit
(DB-120)"). It is not pushed and not merged.

Files changed:
- README.md
- docs/PROGRESS.md
- CLAUDE.md
- docs/SEVER-DB_PROJECT_OVERVIEW.md: header rows, the testing summary, and the new decision entry DB-120
- docs/02, docs/03 and docs/04
- project_report/11, /14 and /17
- tests/README.md, regenerated by `scripts/index.py`; `--check` OK

No code, test, result, ledger or frozen file was changed. All 864 freeze hashes still match. The
older decision entries (DB-113, DB-114, DB-116) are left as written; DB-120 records their
corrections.

| ID | Fixed where |
|---|---|
| D5 | DB-120 item 3; PROGRESS; project_report/14 |
| D6 | README Part 3 and Part 4 results |
| D7 | README Part 3 intro and evaluation section; CLAUDE.md §9; overview header |
| D10 | CLAUDE.md §6.4; README "How it is tested"; overview testing summary |
| D11 | README P4-T10 row (79 of 79, dated 19 Oct); DB-120 item 11 |
| D12 | README P4-T10 row (69 of 69) |
| D14 | PROGRESS |
| D15 | README test-suite row |
| D13 (OS) | DB-120 item 2; docs/03; project_report/11; PROGRESS; README |
| D1 (EX-8), D2 (T-5), D4 (final crash run) | README, PROGRESS, docs/03, project_report/11 and /14, DB-120 |

## 11. What is still not settled, why, and how to settle it

**Settled with no further work:** D1, D2, D4–D15, D17–D21. For D3, the type of change is settled from
the diff, but the results were not rerun (row U2).

| # | Item | Why it is not settled | How to settle it | Cost (laptop; from the ledger durations) |
|---|---|---|---|---|
| U1 | **D16**: how much the EX-6 ground-truth difference moves recall | The SEVER arm's truth leaves out its holding-area records, and the run did not store those IDs, so the effect cannot be recomputed | Add a shared-truth option to `python/sever_experiments/ex6.py` and rerun EX-6, all arms or just sever_db vs soft_delete_ivf. `ex6.py` and `ex2.py` are **frozen** (listed in `freeze/PART-4.sha256`), so this needs a new script outside the frozen files, or an erratum (F-6) | ~1 h per seed; ~5 h for 5 seeds (DB-114) |
| U2 | **D3**: T-1 and T-2 are on the pre-final build | The owner chose not to rerun. The diff argument ("only refusal checks added") is INFERRED, not measured | Rerun `p4-forensics` and both `p4-crash` windows on 94d0b24 | forensics 9 h 12 min (5 seeds) or ~2 h (1 seed); crash windows ~3× slower than before, about 2 days in all (DB-116) |
| U3 | **D11**: do all red proofs hold on the final commit? | The proof reports for Parts 3 and 4 date from 15 and 19 Oct | `PYTHONPATH=python uv run python -m sever_testkit_p3.proofs run` and `… sever_testkit_p4.proofs run` (they regenerate `docs/PROOFS_P3/P4.md`) | unknown; one build per patch (172 + 93 patches), likely hours |
| U4 | **C51**: traceability counts are E2 | The generated files were not regenerated by the audit | The fast-tier spec-trace steps (`python -m sever_testkit.spec_trace`, `_p2`, `_p3`, `_p4`) | minutes |
| U5 | **D22 (new)**: EX-2's live-record control fell to 0 of 20 at rungs 1–3 and rose to 4–16 at rungs 4–5 | The pass rule does not use it. The code says only that recovery "depends on what free space still holds" (`ex2.py:244`): a control counts only when a carved record key unwraps and its payload decrypts (`sever-scan/src/lib.rs:640–680`). There is no logged reason for the drop | Rerun one EX-2 seed with the scanner reporting which of the control's keys and payloads it found per rung; or reason from the key-rotation code which wrapped keys survive on disk after a rung | ~2 h (1 seed) plus analysis |
| U6 | **C47**: the Chroma comparison has no stored output | The spike result was never saved | Run the Studio Forget-me report once on the 3-note case and save its JSON | minutes (Studio env) |
| U7 | Rust tests not re-run by the audit | The owner chose the quick set | `cargo test --workspace` (+ `verifier/`, `audit/`) | ~10–30 min |
| U8 | **EX-8** | A fact, not a discrepancy: it needs more memory than this laptop has | Only on a machine with more RAM (> 16 GB). It cannot be settled on this laptop | — |
| U9 | **G-34 / D9** | A real property of the proof construction, documented, not removed | Independent cryptographic review, outside the project | — |

**Do any of these block the paper?** No, provided U1, U2, U3, U5 and U8 are stated as limitations
in the wording of §8. U4, U6 and U7 are quick and would move three claims from E2 or E1 to E3.

