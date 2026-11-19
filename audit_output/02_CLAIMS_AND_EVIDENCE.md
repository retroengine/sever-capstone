# 02 · Claims and evidence (audit)

**How to read the table.**
- **Status:** VERIFIED (E3/E4 evidence agrees, in the stated scope), PARTIAL (true for part of what
  is claimed, or only on an earlier build), UNSUPPORTED (no raw evidence), CONTRADICTED (raw
  evidence disagrees), STALE (was true for an earlier run or state, but no longer matches the latest
  raw result or the repo).
- **Grade:** E0–E4, as in 01. **Only E3/E4 rows can be VERIFIED.**
- **Every claim quote is CLAIMED.** The evidence column is OBSERVED. The notes are INFERRED unless
  marked otherwise.
- L*n* = ledger line *n*. Result files are in `results_collected/` under the same name.

## A. Headline claims (the four parts)

| ID | Exact quoted claim | Where stated | Evidence (file, key, raw value) | Grade | Status | What would falsify it | Notes |
|---|---|---|---|---|---|---|---|
| C1 | "Deleting a vector returns its group, bit for bit, to the state it would have had if the vector had never arrived" | CLAUDE.md:158 (§6.1); README.md:8, :17 | `p1-differential-nq-100k-20261006T170158Z.json` (L38), summed `seeds[].replay.survivor_failures` = 0 of `survivor_groups_checked` 427,455, `mismatches` 0 of 12,389,642. nq-10k (L13): 0 of 43,562. Synthetic (L19): 0 of 275,114 | E4 | VERIFIED (d = 384, nq-10k and nq-100k, 5 seeds; synthetic d = 16) | Any survivor-group check that differs from the survivors-only rebuild | Part 1 source unchanged since the nq-100k run (freshness.csv: only lock and config files changed) |
| C2 | "Exactness survives a crash at any point; no acknowledged operation is lost; a multi-group deletion is all-or-nothing" | CLAUDE.md:159; README.md:18 | P2 (L56): 343,837 crash points, all failure counters 0. P3-T4 (L144): 938,129, 0. P4-T3: window A (L164) 45,635 and window B (L192) 16,965, 0 | E4 | PARTIAL | Any non-zero `not_oracle_state` / `lost_acknowledged` / `partial_delete_user` | (a) "Any point" means simulated VFS operations within one 20,000-op workload per seed, not physical power loss. (b) The P2 campaign predates erratum E-2. (c) On the final engine (Part 4) only 300-op windows were crashed, one window per seed. (d) On the final commit 94d0b24 there is only a stopped partial run: 14,784 crash points, 0 failures, 94–98 of 300 operations per seed (raw records, D4) |
| C3 | "Every deletion yields a certificate that anyone can verify offline, with no database access" | CLAUDE.md:160; README.md:19 | `p3-attacks-nq-10k-20261101T085746Z.json` (L206, final commit): honest 5,000/5,000 accepted, attacks 226,410/226,410 rejected. Crash campaign certificates checked 192,964, bad 0 (L144). Re-run today: `rerun_verifier.log` accepted:true and flipped→rejected step 2 | E4 / E3 | PARTIAL | Any honest certificate rejected, or any forged one accepted | Runs L103 and L119 had the verifier **accepting** 3 forgeries each (AT-14, then AT-2). The attack generator was changed (47,000 → 45,282 attacks/seed). The AT-2 weakness is documented as G-34, not removed (CLAIMED, docs/03:125–146). "Every deletion": only the generated deletions were checked |
| C4 | "After a deletion is acknowledged, nothing deleted can be recovered from raw storage" | CLAUDE.md:161; README.md:20 | `p4-forensics-nq-10k-20261030T141339Z.json` (L159): `n_findings` 0 in 30/30 scans of 17,179,869,184-byte images; `planted_found` all true; sensitivity SB-24…SB-30 (no SB-27 entry) each ≥ 924 findings | E4 | PARTIAL | Any finding in an honest-build scan | Run on 7c445b5. sever-erasure, -log and -cert sources changed on 1 Nov; **not rerun**. nq-10k instead of the pre-registered nq-100k. `allow_unsafe_fs` override on every seed. Live-record control fell to 0/20 at rungs 1–3 (03 EX2) |
| C5 | "v1.0.0, all four parts frozen" | docs/PROGRESS.md:7 | Tags part-1-frozen, part-2-frozen-e1/e2, part-3-frozen, part-4-frozen = v1.0.0 (7942c1d). `sha256sum -c freeze/PART-1..4` gives 81/250/342/191 OK (`rerun_sha256_checks.log`, EXECUTED-NOW) | E3 | VERIFIED | Any freeze hash mismatch | — |

## B. Pre-registered targets (overview §3.4, fixed 2026-09-27)

| ID | Exact quoted claim | Where | Evidence | Grade | Status | Falsifier | Notes |
|---|---|---|---|---|---|---|---|
| C6 | "Pre-registered targets (fixed 27 September 2026, before any code exists)" | overview:272 | `git log -S` on the T-5 and T-6 lines: only commit 84161ca (2026-09-27). The first crate commit is 2026-10-04 | E3 | VERIFIED | A later commit editing a target line | Scope cuts after pre-registration (EX-6 and EX-2 run at nq-10k instead of nq-100k, P4-T3 windows) came by DB-113, not by edits to the targets |
| C7 | T-1: "0 exactness violations and 0 lost acknowledged operations across the full crash campaign" | overview:276 | As C2 | E4 | PARTIAL | As C2 | Full campaign on Parts 2 and 3 only. The final build has windows |
| C8 | T-2: "0 findings in the forensic erasure scan, and every erasure sabotage produces ≥ 1 finding" | overview:277 | As C4 | E4 | PARTIAL | As C4 | Stale-possible and nq-10k only |
| C9 | T-3: "100 % byte-identical canonical group blobs and identical search results, engine vs reference model" | overview:278 | L210 `p4-replay-nq-10k-20261101T093555Z.json`: mismatches 0, five_field_failed 0 of 5,130, checks 10,693,787 (final commit). L148 nq-100k: 0 of 12,880,102 | E4 | VERIFIED (final build at nq-10k; nq-100k on 7c445b5) | Any mismatch | — |
| C10 | T-4: "100 % of honest certificates accepted; 100 % of attack certificates rejected" | overview:279 | L206, L208: 5,000/5,000 and 226,410/226,410 | E4 | VERIFIED on the final attack set | Any wrong judgement | See C3 on how the attack set changed after failures |
| C11 | T-5: "Per-seed standard deviation (ddof = 0) of Recall@10 across the five deletion rungs ≤ 0.005, on each of the five seeds" | overview:280 | `p4-ex6-…json` `t5_per_seed.*.ddof0`: 0.012954…, 0.010463…, 0.012791…, 0.007905…, 0.010368… Recomputed identical; 0 of 5 ≤ 0.005 | E4 | **CONTRADICTED (target missed)** | Already falsified | Reported as missed in docs/03:189–212 and project_report/11. **README omits it** (D7) |
| C12 | T-6: "Recall@10 … ≥ 0.999 at both corpus sizes (10^5 and 10^6)" | overview:281 | `recall_at_10` 1.0 (nq-100k, L9) and 1.0 (nq-1m, L180), 3452 queries | E3 | VERIFIED | recall < 0.999 | No per-query data, so it cannot be recomputed |
| C13 | "One confirmatory statistical test … Welch's two-sided t-test … α = 0.005" | overview:283 | Recomputed t = -9.570522849699275, p = 0.00015000062306656675 | E4 | VERIFIED (significant: SEVER drift < soft-delete IVF) | p ≥ 0.005 | rebuild_ivf has a lower mean drift (0.00834) than SEVER (0.01090). The Welch test does not involve it |
| C14 | "a TOST equivalence test at margin Δ = 0.005 is reported, with the expectation … that five seeds are too few" | overview:284–286 | TOST p = 0.9974696929884848 (recomputed) | E4 | VERIFIED | — | — |

## C. Gate and measure numbers stated in docs

| ID | Exact quoted claim | Where | Evidence | Grade | Status | Falsifier | Notes |
|---|---|---|---|---|---|---|---|
| C15 | "Rust 95.9 % lines, 87.0 % branches; Python 98.8 %" | README.md:129 | `p1-coverage-…json` rust.lines [1127, 1175] → 0.9591489361702128; branches [134, 154] → 0.8701298701298701; python [515, 521] → 0.9884836852207294 | E4 | VERIFIED | — | — |
| C16 | "325 / 347 caught (93.7 %); 22 survivors" | README.md:130 | `p1-mutants-…json` caught 325, missed 22, timeout 0 → 0.9365994236311239 | E4 | VERIFIED | — | Score = caught/(caught+missed+timeout); unviable excluded |
| C17 | "lines 94.8 %, branches 86.7 %" (P2-T9) | README.md:209 | [3689, 3891] → 0.9480853251092264; [339, 391] → 0.8670076726342711 | E4 | VERIFIED | — | STALE-POSSIBLE (Part 2 source changed after 10-07) |
| C18 | "652 / 713 = 91.4 %, all 60 survivors triaged" | README.md:209 | caught 652, missed 60, timeout 1 → 0.9144460028050491; `untriaged` [] | E4 | VERIFIED | — | — |
| C19 | "343,837 crash points (every VFS operation 321,689, every 512-byte …)" | README.md:203 | Recomputed step 321,689, offset 17,148, random 5,000 = 343,837 | E4 | VERIFIED | — | STALE-POSSIBLE (pre E-2) |
| C20 | P2-T11: "insert 8.1 KB, single delete 14.2 KB, multi-record delete_user 24.6 KB …; recovery 0.05 s … 0.85 s …; peak resident memory 1.09 GB" | README.md:211 | `found.per_kind`: 8062.09474, 14156.824960594915, 24608.149310730252; recovery 0.051788124 / 0.847202078; VmHWM 1093044 kB | E3 | VERIFIED (rounded) | — | — |
| C21 | P1-T6: "largest differences 2e-17 and 1.4e-14" | README.md:125 | max over `artefacts/partition-seed*.json`: 2.0816681711721685e-17, 1.4210854715202004e-14 | E4 | VERIFIED | — | Artefacts are not in the ledger; producing commit UNKNOWN |
| C22 | P1-T14: "soft-delete IVF 5.0e-3, float mean 1.9e-8, SEVER 0" | README.md:133 | `idea-nq-10k-seed42.json` `ghost.per_group`: 0.005035506396513171; 1.862645149230957e-08 (group 2); 0 | E3 | VERIFIED | — | File regenerated 2026-11-09 19:51 outside the ledger |
| C23 | P3-T4: "PASS: 145,919 crash points, 76,852 certificates checked" | README.md:301 | L97 interim (crash-from 17000) has those values. The full gate L144: 938,129 and 192,964 | E4 | STALE | — | README shows the interim run, not the gate |
| C24 | P3-T5: "Part 1's nq-100k trace, seed 42 … PASS" | README.md:302 | L148: 5 seeds, PASS | E3 | STALE | — | — |
| C25 | P3-T9 coverage: "crypto 95.4 %, verifier 95.2 %, commit 91.6 %, log 92.9 %, cert 96.2 %" | README.md:304 | L121 (19 Oct) matches. Final L200: crypto 0.954233, commit 0.915842, log 0.930937, cert 0.958861, verifier 0.962707 | E4 | STALE | — | — |
| C26 | P3-T10: "fuzzing, 10^7 executions per parser … 6 parsers, 0 crashes" | README.md:305 | L162: 10^8 per target, 6 targets, 0 crashed | E3 | STALE (superseded by a stronger run) | — | — |
| C27 | P3-T13: "prove 12.2 ms, verify 2.2 ms (medians); certificate 1.2–13.6 KB" | README.md:307 | L109: 12.171319 / 2.2043179999999998. Final L182: 15.783409000000002 / 2.744998; bytes 1197–13645 | E3 | STALE | — | — |
| C28 | Part 3/4 gates "run once, in full, on the college HPC in WSL2 Ubuntu" | README.md:294–295, :355–356 | DB-113: HPC unavailable, laptop run. Ledger: same WSL2 kernel in all 224 rows | E3 | CONTRADICTED | — | README last committed 10-31 |
| C29 | P4-T3: "three windows of 80 operations per seed …, five seeds, plus a smoke run — PASS: 16 / 16 runs" | README.md:360 | No ledger row or result file. The gate runs (L164, L192) are 300-op windows, 3 + 2 seeds | E1 | STALE / UNSUPPORTED | — | Possibly `traces/p4-interim/` (56 files, not analysed) |
| C30 | P4-T10: "68 / 68 requirements traced, 84 proofs" | README.md:361 | `docs/TRACE_PART_4.md`: "69 of 69". `docs/PROOFS_P4.md`: "79 of 79 proofs hold" (run 10-19). `tests/proofs/p4/` holds 93 files | E2 | CONTRADICTED (three different numbers) | — | D12 |
| C31 | "Test suite: cargo test --workspace, Python tests: pass" | README.md:362 | Re-run today: Python 271 passed (with `--ignore=tests/cleanroom`). A plain `pytest` fails at collection with 3 errors. Cargo not run | E3 | PARTIAL | — | `traces/full-checks-635a8c9.log` shows 4 FAIL steps; 69a33f4 shows 1 FAIL (cleanroom-kept) |
| C32 | P4-T10 mutation PASS: "p4-mutants PASS (P4-T10)" | PROGRESS.md:14 | L220 `p4-mutants-20261101T175053Z.json`: erasure 123/136 = 0.9044117647058824, keys 84/86 = 0.9767441860465116, seal 139/145 = 0.9586206896551724, untriaged [] | E4 | VERIFIED | — | The earlier L189 FAIL was "accepted as a pass by the owner" (DB-114); L220 is a real PASS |
| C33 | P4-T10 coverage ≥ 95 % | README / PROGRESS | L202: keys 0.9812734082397003, seal 0.9614791987673343, erasure 0.9557522123893806 | E4 | VERIFIED | — | — |
| C34 | P3-T9 mutation PASS: "sever-cert 0.8516, sever-crypto 0.9344, sever-log 0.891, verifier 0.9733" | overview DB-114 | L158: 132/155, 114/122, 335/376, 219/225 recomputed equal | E4 | VERIFIED | — | sever-cert clears its 0.85 minimum by 0.0016. STALE-POSSIBLE (not rerun after BH fixes) |
| C35 | "16 of the 17 gates pass as recorded; P4-T10 records FAIL …; 5 of the 6 measures are recorded; EX-8 was killed by the out-of-memory killer at 10.39 GB after 6 h 11 min" | PROGRESS.md:18–21 | Ledger rows L141–L192 support the gate and measure counts (with the reruns). For EX-8 there is no ledger row or result; only header lines in `hpc-p4-ex8.log` | E3 (gates) / E1 (EX-8 OOM figures) | PARTIAL | — | Owner (9 Nov): EX-8 never ran because of device limits. See C36 |
| C36 | EX-8 / P4-T15 memory and recovery at 10^6 vectors | overview EX-8 row; Appendix A ≈ 3.8 GB prediction | No result exists (03 EX8) | E0 | UNSUPPORTED (**not run to completion because of device limits; not a failed result**) | — | Any 10^6 memory number in the paper would have no source |
| C37 | EX-7 nq-100k: "Deletes per second … 7.63 (sever), 12.70 (noerase), 741.37 (softdelete)" | docs/03_experiments_and_results.md:236 | `per_second` 7.626844206739731, 12.698753413030902, 741.3707917259521 | E3 | VERIFIED | — | One seed, no interval |
| C38 | EX-7 nq-10k sever delete p50 "75,333 [74,539, 76,381]" | docs/03:232 | Recomputed mean 75332.9668; ci95 [74539.3858, 76380.9178] | E4 (mean) / E3 (CI) | VERIFIED | — | — |
| C39 | Fair PASS Part 3 "180 clean-room tests, 0 failing" and Part 4 "101 … 0 failing" | docs/03:112, :166; PROGRESS.md:13–14 | `fair-20261101T134211Z-p3-bb4bac5e.json` tests 180, failing 0, PASS. `fair-20261101T192712Z-p4-36291aec.json` tests 101, failing 0, PASS | E3 | VERIFIED | — | Ledger rows L215 and L224 are `git_dirty: true`. The oracle judge could not derive 5/10 (P3) and 2/10 (P4) sampled values |
| C40 | Errata re-runs: "256 tests, 255 passed, 0 failed, 1 skipped" | docs/03:90 | `cleanroom-p2-after-e1.json` and `-e2.json`: tests 256, passed 255, failed 0 | E3 | VERIFIED | — | — |
| C41 | "Every ledger line records the same platform: x86_64, kernel 6.6.114.1-microsoft-standard-WSL2, CPU flags avx2 fma aes sha_ni" | docs/03:25 | 224/224 rows (recompute/ledger.py) | E4 | VERIFIED | — | `swap_on` varies (172 true, 52 false) |
| C42 | Hardware "… native Linux" | overview:12 | Ledger: `wsl: true` in every row | E3 | CONTRADICTED | — | Overview table predates DB-113 |
| C43 | "WSL2 Ubuntu 24.04 with 12 GB" | overview DB-113:1154 | Today `/etc/os-release` shows Ubuntu 26.04 LTS. The ledger has no OS field | E3 (today's `/etc/os-release` and the owner's `lsb_release` output, 9 Nov: "Ubuntu 26.04 LTS … resolute") | CONTRADICTED | — | Owner confirmed (9 Nov 2026) that the OS is Ubuntu 26.04. DB-113's "24.04" is wrong |

## D. Process claims (how the evidence was produced)

| ID | Exact quoted claim | Where | Evidence | Grade | Status | Falsifier | Notes |
|---|---|---|---|---|---|---|---|
| C44 | "Freeze needs it (FT-10): `scripts/freeze.sh N` (N ≥ 2) refuses without a PASS fairness run" | CLAUDE.md:272; docs/FAIR_TESTING.md:52 | Part 2: only FAIL (L72) and DRY (L68) fair outcomes; run 42fc06df has no outcome (L74 started only). Part 2 is tagged frozen (e1, e2) | E3 | CONTRADICTED for Part 2 | — | PROGRESS.md:13 says frozen 8 Oct |
| C45 | "a separate session plants blind bugs that the script scores" | CLAUDE.md:263 (§6.4) | All non-dry fair results have `planted: []`. The check row reads "planted bugs: cargo-mutants gate PASS in the ledger (DB-75)" | E3 | STALE (replaced by DB-75) | — | — |
| C46 | "Not rerun on the final commit: the rest of p4-crash-a, p4-crash-b, p3-mutants, p4-mutants, p3-replay and p3-crash; their last results are on 7c3c313" | overview:1061 (DB-116) | p4-mutants **was** rerun (L220 PASS, 77ca977/e00e31d). The last results are on 7c445b5, 11f00f2, 9e11156, 96f9370, **not 7c3c313** (a docs commit). Also not rerun and not listed: p4-forensics, p3-fuzz, p4-fuzz, p3-measures, p4-ex6, p4-ex7, p4-quant-recall | E3 | CONTRADICTED (incomplete and miscited) | — | D5 |
| C47 | Chroma spike: "after delete(), get and query return nothing, and the scan still finds 3/3 IDs, 6/6 text windows and 3/3 vectors" | overview:1087 (DB-119) | No result file or log found | E1 | UNSUPPORTED | Re-running the spike | — |
| C48 | "Stage 6 … pushed and not merged into main" | PROGRESS.md:35 | `main` = `af8fed2` = HEAD of p6-studio-company (`git branch -a`) | E3 | STALE | — | — |
| C49 | Part 3 "Built … it freezes after a fair-testing pass" | README.md:19 | Tag part-3-frozen exists (2026-11-01) | E3 | STALE | — | — |
| C50 | Proof reports: "211 of 211 proofs hold" (P2), "31 of 31" (P3), "79 of 79" (P4) | docs/PROOFS_P2/3/4.md:3 | Patch counts now: p2 141, p3 172, p4 93 files in `tests/proofs/` (files, not necessarily proofs) | E2 | STALE (P3/P4 reports dated 10-15 and 10-19, before most patches) | Running `proofs run` | Not re-run (long) |
| C51 | Traceability "70 of 70", "46 of 46", "108 of 108", "69 of 69" requirements | docs/TRACE_PART_1..4.md | Generated files, read as is | E2 | UNCONFIRMED (not regenerated) | `spec-trace` run | — |
| C52 | Dataset: 1,000,000 NQ passages, 3,452 queries, SciQ 13,679, 0 text overlap | meta.json | `build.nq.size_big` 1000000, `queries` 3452, `sciq.passages` 13679, `non_overlap` zeros. Manifest OK today | E3 | VERIFIED | — | `truncation_rate` 0.049148 is a limitation |
| C53 | DB-116: "p4-crash-a ran 1.9 h, about a third of its range (seeds 42, 123, 777; about 4,900 crash points each; 0 mismatches, 0 bad certificates)" | overview:1061 | `traces/p4-crash-nq-10k-seed{42,123,777}.jsonl` (raw, recounted): 4,910 / 4,961 / 4,913 crash points. `.progress` `sum`: main_mismatches 0, bad_certificates 0, not_oracle_state 0, refusals 0. Ops reached 17,787 / 17,791 / 17,788 of 17,993. `seconds` 6064 / 6092 / 6052 | E4 | VERIFIED | Any non-zero failure counter | "1.9 h": the progress `seconds` are about 1.7 h per seed. "About a third": 94–98 of 300 ops, which agrees |

## Counts (computed by `recompute/claim_counts.py` from the rows above → `recompute/claim_counts.out`)

53 claims.

| Status | Count | IDs |
|---|---|---|
| VERIFIED | 26 | C1, C5, C6, C9, C10, C12, C13, C14, C15, C16, C17, C18, C19, C20, C21, C22, C32, C33, C34, C37, C38, C39, C40, C41, C52, C53 |
| PARTIAL | 7 | C2, C3, C4, C7, C8, C31, C35 |
| CONTRADICTED | 7 | C11, C28, C30, C42, C43, C44, C46 (C11 = T-5 missed) |
| STALE | 10 | C23, C24, C25, C26, C27, C29, C45, C48, C49, C50 |
| UNSUPPORTED | 2 | C36, C47 (C36 = EX-8, never completed) |
| UNCONFIRMED (E2 only) | 1 | C51 |

| Strongest evidence grade | Count | IDs |
|---|---|---|
| E4 | 25 | C1, C2, C3, C4, C7, C8, C9, C10, C11, C13, C14, C15, C16, C17, C18, C19, C21, C23, C25, C32, C33, C34, C38, C41, C53 |
| E3 | 22 | C5, C6, C12, C20, C22, C24, C26, C27, C28, C31, C35, C37, C39, C40, C42, C43, C44, C45, C46, C48, C49, C52 |
| E2 | 3 | C30, C50, C51 |
| E1 | 2 | C29, C47 |
| E0 | 1 | C36 |

A grade describes the evidence for the *number*. A STALE or PARTIAL row can still have E4 evidence,
for example when the number is right but belongs to an older run or a narrower scope.
