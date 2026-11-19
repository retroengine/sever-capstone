# 03 · Experiments and results (audit)

Every number is copied from the named file and key. "Recomputed" values come from the scripts in
`audit_output/recompute/`, which read only the raw result JSON:
- `recompute_gates.py` → `recompute_gates.out`
- `recompute_misc.py` → `recompute_misc.out`
- `recompute_ex6.py` → `recompute_ex6.out`
- `recompute_ex7.py` → `recompute_ex7.out`

Freshness comes from `recompute/freshness.py` → `freshness.csv`. **CURRENT** means that no file
owned by Parts 1..N (freeze manifests), and none of Cargo.lock, uv.lock, rust-toolchain.toml or
configs/, changed between the run's commit and HEAD. **STALE-POSSIBLE** lists what changed.
Status per file is in `results_collected/MANIFEST.csv`.

**Hardware for every experiment:** OBSERVED, one machine class per the ledger (x86_64, WSL2 kernel
6.6.114.1, 8 nproc). CLAIMED (DB-113): an Intel Core Ultra 5 226V laptop with 16 GB and 12 GB to
WSL. **Seeds:** `[42, 123, 777, 2024, 9999]` unless stated. All of them are labelled OBSERVED from
the result file `seeds` keys.

---

## EX1 — Crash campaigns (project EX-1; gates P2-T1…T3, P3-T4, P4-T3; target T-1)

- **Purpose** (CLAIMED, overview §3.4 T-1): "0 exactness violations and 0 lost acknowledged
  operations across the full crash campaign".
- **Method** (CLAIMED, result `gate` strings): crash at every simulated-VFS step (`step`), at
  512-byte WAL offsets (`offset`), at random points (`random`), and during recovery (`double`).
  Part 4 adds torn key-slot writes (`keytear`) and injected active-key losses. The VFS is simulated
  (`SimVfs`, crate sever-vfs). This is not physical power loss (INFERRED from the code map).
- **Dataset:** nq-10k, 20,000 operations per seed (Parts 2 and 3). **Baselines:** none (oracle-state check).

| Run | Ledger / file | Commit | Seeds | Ops/seed | Crash points (recomputed sum of per-seed `verdict.crash_points`) | By kind (recomputed) | Failures (sum) | Extra | Freshness |
|---|---|---|---|---|---|---|---|---|---|
| P2 smoke | L40 `p2-crash-…20261007T192621Z` | f7d6362 dirty | 42 | 40 | 1,584 | — | 0 | — | STALE-POSSIBLE |
| **P2-T1…T3** | L56 `p2-crash-nq-10k-20261008T012927Z.json` | 682bface | 5 | 20,000 | **343,837** (68,927; 68,149; 68,821; 69,871; 68,069) | step 321,689; offset 17,148; random 5,000; double 6,874; generic points 28,707 | 0 (all verdict counters 0) | — | STALE-POSSIBLE: engine changes after the run include erratum E-2 (a244264, sever-engine) and test-audit commits |
| P3-T4 interim | L97 `p3-crash-…20261019T014621Z` | 30e4497d | 5 | from op 17,000 (`--crash-from 17000`) | 145,919 | step 141,959; offset 3,218; random 742 | 0 | certificates checked 76,852 | STALE-POSSIBLE |
| **P3-T4** | L144 `p3-crash-nq-10k-20261029T225309Z.json` | 4dcfbe0 (resumed run, `stderr_tail` "resuming after operation 1814") | 5 | 20,000 | **938,129** (187,795; 187,014; 187,691; 188,696; 186,933) | step 914,464; offset 18,665; random 5,000; double 18,759 | 0 | certificates checked 192,964, bad 0, orphaned leaves 0, rolled-back certs 0 | **STALE-POSSIBLE**: sever-cert, sever-log src changed on 1 Nov (BH-6/7/9); not rerun on final commit |
| **P4-T3 window A** | L164 `p4-crash-nq-10k-20261030T175146Z.json` | 7c445b5 | 42, 123, 777 | ops 17,694–17,993 (`--limit-ops 17994`) | **45,635** (15,240; 15,170; 15,225) | step 37,739; keytear 7,632; offset 218; random 46; double 911 | 0 | key-loss injected 300, refused 300; stale key slots 0; unreadable 0 | **STALE-POSSIBLE** (6 crates' src changed incl. sever-erasure, sever-log, sever-cert) |
| P4-T3 window B (first) | L168 `…20261030T184348Z` | 7c445b5 | 2024, 9999 | ops 18,700–18,999 | 16,966 | — | 0 engine-side; outcome **FAIL** (harness method check, DB-114 item 5) | — | superseded |
| **P4-T3 window B** | L192 `p4-crash-nq-10k-20261031T124815Z.json` | 9e11156 | 2024, 9999 | ops 18,700–18,999 | **16,965** (7,915; 9,050) | step 14,517; keytear 2,312; offset 94; random 42; double 339 | 0 | key-loss 200/200 refused | **STALE-POSSIBLE** |
| **P4-T3 final-commit rerun (partial)** | L211 (started only); `traces/final-p4-crash-a.log`: `rc=stopped (owner decision 1 Nov, partial)`. Raw per-point records `traces/p4-crash-nq-10k-seed{42,123,777}.jsonl` and `.progress` | 94d0b24 | 42, 123, 777 | window A, stopped after 94 / 98 / 95 of 300 ops | **14,784** (4,910; 4,961; 4,913), recomputed from the raw records | step 12,136; keytear 2,552; offset 81; random 15; double 295 (progress) | 0 (every `.progress` failure counter) | certificates checked 4,129 (1,461 + 1,260 + 1,408); key-loss injection not reached | CURRENT (only sever-py changed since). No result file; E3/E4 from the raw records (D4) |

- **Fairness:** no comparison arms. **N:** 5 seeds (Part 4: 3 + 2 seeds in two 300-operation
  windows, so each seed was crashed in **one** window only).
- **Falsification:** any non-zero `not_oracle_state`, `lost_acknowledged`, `partial_delete_user`,
  `bad_certificates` or `unreadable_records`. The data could show this; every recorded value is 0.
- **Scope gap** (OBSERVED from the commands): on the final engine (Part 4), T-1 covers 600 of
  20,000 operations per seed pair. On the final commit 94d0b24 there is only the partial run above: 14,784 crash points, 0 failures, and no key-loss injection reached.

## EX2 — Forensic erasure scan (project EX-2; P4-T1, P4-T2; target T-2)

- File: L159 `results/p4-forensics-nq-10k-20261030T141339Z.json`, commit 7c445b5, outcome PASS.
  **STALE-POSSIBLE**: sever-erasure, sever-log and sever-cert sources changed on 1 Nov. **Not rerun
  on the final commit, and not named in DB-116's not-rerun list** (see D5).
- Command (ledger): `gates p4-forensics --data nq-10k --seeds [42, 123, 777, 2024, 9999] --image-gib 16`.
  Pre-registered size: nq-100k (overview EX-table). This run used nq-10k (DB-113 scope cut).
- Per seed (E4, `recompute_misc.out`):
  - 6 scans of a 17,179,869,184-byte image (after ingest and after each of 5 rungs).
  - `n_findings` 0 in all 30 scans.
  - `planted_found` all true in all 30 scans.
  - `overrides: ["allow_unsafe_fs"]` on every seed.
- **Sensitivity** (seed 42, `sensitivity.items`): SB-24 2,374; SB-25 1,178; SB-26 924; SB-28 4,246;
  SB-29 65,738; SB-30 65,229 findings; `ok` true. SB-27 has no entry (OBSERVED; reason UNKNOWN).
- **Live-record control** (`live_records_recovered`, 20 targets):

| Seed | ingest | rung 1 | rung 2 | rung 3 | rung 4 | rung 5 |
|---|---|---|---|---|---|---|
| 42 | 20 | 0 | 0 | 0 | 6 | 16 |
| 123 | 20 | 0 | 0 | 0 | 4 | 12 |
| 777 | 19 | 0 | 0 | 0 | 9 | 12 |
| 2024 | 20 | 0 | 0 | 0 | 5 | 12 |
| 9999 | 20 | 0 | 0 | 0 | 4 | 16 |

  INFERRED: in rungs 1–3 the scanner could not even recover live records it holds keys for. So
  "0 findings" at those rungs is weaker evidence of erasure than at ingest. This is not part of
  the pass rule.
- **Baselines:** sabotage builds only. No other database was scanned in this gate. A Chroma spike is
  claimed in DB-119, but no data was found (EX13).
- **Falsification:** any finding in a scan of the honest build, or any sabotage build with 0 findings.
  The data could show either; neither occurred.

## EX3 — Engine against the reference model (project EX-3; P1-T1/T2/T4/T5, L4 synthetic, P2-T5, P3-T5, P4-T9 T-3)

| Run | File | Commit | Data, seeds | Recomputed totals (E4) | Outcome | Freshness |
|---|---|---|---|---|---|---|
| P1 differential | L13 `p1-differential-nq-10k-20261005T133904Z.json` | 0b697f7 (dirty) | nq-10k ×5 | ops 89,245; compared 10,648,947; mismatches 0; deleted_returned 0; survivor groups 43,562, failures 0; kernel pairs 508,183,412, mismatches 0 | PASS | STALE-POSSIBLE (Part 1 src changed before freeze) |
| **P1 differential** | L38 `p1-differential-nq-100k-20261006T170158Z.json` | 22d1dce | nq-100k ×5 | ops 731,105; compared 12,389,642; mismatches 0; survivor groups 427,455, failures 0; kernel pairs 2,252,810,672, mismatches 0 | PASS | src unchanged since (only lock/config files) |
| L4 synthetic | L19 `p1-synthetic-20261005T134647Z.json` | c4d0081 (dirty) | 1,000 streams × 1,000 ops, 5 seeds | ops 1,001,000; compared 13,155,903; mismatches 0; survivor groups 275,114 | PASS | STALE-POSSIBLE |
| P1-T6 builder vs oracle | `artefacts/partition-seed*.json` (not in ledger) | UNKNOWN | 5 seeds | max `oracle_shrinkage_diff` 2.0816681711721685e-17 (seed 42); max `oracle_tau_diff` 1.4210854715202004e-14 (seed 777) | thresholds 1e-12 / 1e-9 (CLAIMED README:125) | UNKNOWN (file mtime 2026-10-04) |
| P2-T5 replay | L51 `p2-replay-nq-10k-20261007T220349Z.json` | 22012b6 (dirty) | 5 seeds × plain/close/crash | per-run `summary.mismatches` 0 (seed 42 plain: checks 2,129,788) | PASS | STALE-POSSIBLE |
| P3-T5 interim | L99 `p3-replay-nq-100k-20261019T033241Z` | 30e4497 | nq-100k seed 42 | certificates 90,040; checks 2,576,072; mismatches 0 | PASS | superseded |
| **P3-T5** | L148 `p3-replay-nq-100k-20261030T050118Z.json` | 7c445b5 | nq-100k ×5, mode plain | certificates 450,056; checks 12,880,102; five-field checked 9,510, failed 0; commitment mismatches 0 | PASS | STALE-POSSIBLE (sever-cert/log) |
| **P4-T9 (T-3), final** | L210 `p4-replay-nq-10k-20261101T093555Z.json` | 94d0b24 | nq-10k ×5 | certificates 44,959; checks 10,693,787; five-field checked 5,130, failed 0; mismatches 0 | PASS | only `crates/sever-py/src/lib.rs` (DB-118) changed since |

- **Oracle:** `python/sever_refmodel_*`. CLAIMED: it was written from the spec only (CLAUDE.md §7).
  The audit did not verify this independence.
- **Falsification:** any mismatch or survivor failure. None was recorded.

## EX4 — Certificate verification and attacks (project EX-4; P3-T1/T2, P4-T9 T-4; target T-4)

| Run | File | Commit | Honest accepted / total (recomputed) | Attacks rejected / total (recomputed) | Wrongly judged | Outcome |
|---|---|---|---|---|---|---|
| 1 | L103 `p3-attacks-…20261019T043502Z` | 30e4497 | 5,000 / 5,000 | 234,997 / 235,000 | 3 | FAIL |
| 2 | L113 `…20261019T145551Z` | eb7ca7c | 0 / 0 (generator stopped) | 0 / 0 | 0 | FAIL |
| 3 | L119 `…20261019T174528Z` | 9d1cb3d | 5,000 / 5,000 | 226,407 / 226,410 | 3 | FAIL |
| 4 | L123 `…20261019T191140Z` | a2484e0 | 5,000 / 5,000 | 226,410 / 226,410 | 0 | PASS |
| 5 | L141 `…20261029T114936Z` | 4dcfbe0 (dirty) | 5,000 / 5,000 | 226,410 / 226,410 | 0 | PASS |
| **6, final** | L206 `p3-attacks-nq-10k-20261101T085746Z.json` | 94d0b24 | **5,000 / 5,000** | **226,410 / 226,410** | 0 | PASS (CURRENT) |
| P4-T9 T-4 | L142 `p4-attacks-…20261029T114951Z` | 7c445b5 | 5,000 / 5,000 | 226,410 / 226,410 | 0 | PASS |
| **P4-T9 T-4, final** | L208 `p4-attacks-nq-10k-20261101T090800Z.json` | 94d0b24 | **5,000 / 5,000** | **226,410 / 226,410** | 0 | PASS (sever-py changed since) |

- Per seed (final): 1,000 honest and 45,282 attacks across AT-1…AT-20 (`generator` string
  "1000 honest certificates, 45282 attacks").
- **Important (OBSERVED):** the attack set changed between failing and passing runs: 47,000 →
  45,282 per seed. CLAIMED (docs/03_experiments_and_results.md:125–146, G-34, DB-95): run 1's
  accepted forgeries came from a generator bug (AT-14). Run 3's accepted AT-2 forgeries came from a
  real construction property of an emptied group's proof. The response was to document it in §9.5
  and change the generator's donors, not the verifier. See D9.
- **Re-run (EXECUTED-NOW, `results_collected/rerun_verifier.log`):**
  - `sever-verify certificate.bin --anchors anchors.json` → `{"accepted":true,…,"leaf_index":3459}`, exit 0.
  - `flipped.bin` → `{"accepted":false,"reason":"the operator signature does not verify","step":2}`, exit 1.
  - The binary dates from 2026-10-24. Later verifier commit 8f6cbc1 (10-30) is described as tests only.
- **Falsification:** any honest certificate rejected, or any attack accepted. This was observed in
  runs 1 and 3, before the generator changes.

## EX5 — Quantisation recall (project EX-5; P1-T7 / P4-T13; target T-6 ≥ 0.999)

| Data | File | Commit | queries | k | recall_at_10 | target | met | seconds | Freshness |
|---|---|---|---|---|---|---|---|---|---|
| nq-100k | L9 `p1-quant-recall-nq-100k-20261005T131137Z.json` | eac1ecf (dirty) | 3452 | 10 | **1.0** | 0.999 | true | 86.3 | STALE-POSSIBLE (sever-quant src changed later on 10-05/06) |
| nq-1m | L180 `p1-quant-recall-nq-1m-20261030T232039Z.json` | 7c445b5 | 3452 | 10 | **1.0** | 0.999 | true | 917.4 | CURRENT |

- Method (`method` key): "float64 brute force, |q|^2 - 2 q.x + |x|^2; ties by row index;
  dequantised = round_half_even(x*2^24)/2^24".
- E3 only: no per-query data is stored, so the recall cannot be recomputed.
- **Note:** the nq-1m slice *was* used here and the measurement completed. This is distinct from
  EX8, which never produced a result.

## EX6 — Search stability under deletion (project EX-6; P4-T12; target T-5)

- File: L161 `results/p4-ex6-nq-10k-20261030T154119Z.json`, commit 4810d8f, outcome RECORDED.
  STALE-POSSIBLE: sever-cert, -log, -erasure, -crashkit-p4 and -py changed since.
- Data: nq-10k (pre-registered: nq-100k, overview EX-6 row; cut by DB-113). 3,452 queries.
  Rungs 0–5.
- Arms:
  - `sever_db`, the final engine through the SDK
  - `frozen_only`
  - `soft_delete_ivf`, FAISS IVFFlat with deletions filtered at query time
  - `rebuild_ivf`
- FAISS parameters (code `ex6.py:9–10,258`): `nlist` = SEVER's group count at rung 0 (171 for
  seed 42), `nprobe` = ⌈0.25·nlist⌉.
- Statistic (`ex6.py:119–121`): std of Recall@10 over rungs 1–5. Both ddof 0 and ddof 1 are stored.
  The target uses **ddof 0 (population)**.

**Per-seed drift, ddof 0 (stated = recomputed; all 20 MATCH in `recompute_ex6.out`)**

| Seed | sever_db | frozen_only | soft_delete_ivf | rebuild_ivf |
|---|---|---|---|---|
| 42 | 0.012954464183038068 | 0.023138306744769552 | 0.020969582512359048 | 0.009365222716070667 |
| 123 | 0.01046320748377855 | 0.01861598700253601 | 0.02013593103098343 | 0.00810255701460924 |
| 777 | 0.012791206346796629 | 0.025693965592170492 | 0.01918919088864533 | 0.007606493637896423 |
| 2024 | 0.007905761024394675 | 0.021007558382339756 | 0.020893560259573982 | 0.010163063765244468 |
| 9999 | 0.010368996522385845 | 0.01879711600014802 | 0.02133219262476454 | 0.0064806735708229125 |
| Mean (recomputed, n=5) | 0.010896727112078754 | 0.021450586744392767 | 0.02050409146326527 | 0.008343602140928741 |
| Sample SD of the 5 drifts (recomputed, ddof 1) | 0.0020757920419127262 | 0.00300527867518637 | 0.0008541991891231843 | 0.0014513858685229458 |
| Bootstrap 95 % of mean (stated = recomputed, PCG64(0), 10,000 resamples) | [0.009383702323189377, 0.012404719083659334] | [0.019166752877541566, 0.02380346390428581] | [0.01975723497404819, 0.021092940306008317] | [0.007255378286409582, 0.009431825995447903] |

- **T-5 (≤ 0.005 per seed): NOT MET on 0 of 5 seeds.** `t5_met: false`, stated and recomputed (E4).
- **Welch two-sided t-test, sever_db vs soft_delete_ivf** on the ddof-0 drifts, n = 5 per arm,
  α = 0.005: t = -9.570522849699275, p = 0.00015000062306656675 (stated = recomputed, scipy
  `ttest_ind(equal_var=False)`). Significant: SEVER-DB's drift is lower than soft-delete IVF's.
- **TOST, δ = 0.005:** p = 0.9974696929884848 (stated = recomputed). Equivalence is not shown.
  CLAIMED (overview §3.4): this outcome was expected beforehand.
- Recall@10 by rung, seed 42 (`recompute_ex6.out`):
  - sever_db 0.9541 → 0.9171
  - soft_delete_ivf 0.9601 → 0.9014
  - rebuild_ivf 0.9601 → 0.9354
  - frozen_only 0.9253 → 0.859
- **Fairness check:**

  | Item | Outcome |
  |---|---|
  | Data and queries | Same for all arms |
  | Seeds | Same 5 for all arms |
  | Hardware | Same machine |
  | Tuning budget | FAISS `nlist`/`nprobe` derived from SEVER's group count. Not tuned independently. SEVER's probe count is fixed by the spec (UNKNOWN whether equal to 25 %) |
  | Ground truth | **Differs by arm** (OBSERVED in code `ex6.py:14,193–206`): the SEVER arm's truth and nDCG exclude SEVER's own holding-area records (seed 42 rung 0: 179 of 10,000; `records` 9,821 vs 10,000 for the FAISS arms). This favours the SEVER arm's recall (INFERRED) |
  | Wall-clock | Not comparable: EX-6 was paused while other steps ran (DB-114, CLAIMED) |
  | Test-set leakage | None found: the partition was fitted on SciQ, and `meta.json` reports 0 text overlap |

- **Falsification of the T-5 claim:** any seed with drift > 0.005. All 5 seeds were above it, so
  the target is falsified.

## EX7 — Cost of provable erasure (project EX-7; P4-T14; measure)

- Files:
  - L184 `p4-ex7-nq-10k-20261031T021052Z.json` (5 seeds)
  - L186 `p4-ex7-nq-100k-20261031T073714Z.json` (seed 42 only)
  - Both at commit 7c445b5, STALE-POSSIBLE (6 crates changed).
- Arms: `sever` (final engine), `noerase` (encryption without rotation or erase), `softdelete`
  (Part 2 engine with tombstones).
- nq-10k means were recomputed from the per-seed values. 18/18 MATCH the file's
  `summary.<arm>.<key>.mean` (`recompute_ex7.out`).

| Metric (nq-10k, mean of 5 seeds) | sever | noerase | softdelete | Source key |
|---|---|---|---|---|
| delete p50 per call (µs), stated ci95 in [ ] | 75332.9668 [74539.3858, 76380.9178] | 65528.4424 [64885.41799999999, 66323.79719999999] | 1416.5218 [1327.8256, 1522.3957999999998] | `summary.*.delete_call_p50_us` |
| delete bytes per record | 38874.36633625893 | 27122.137467741366 | 9.954381363514395 | `delete_bytes_per_record` |
| delete fsyncs per record | 15.941008878577318 | 13.08427156638902 | 0.8722402860595243 | `delete_fsyncs_per_record` |
| insert p50 (µs) | 18644.284 | 17802.0162 | 1881.3142 | `insert_p50_us` |
| insert fsyncs per op (stated) | 3.0175 | 3.0089 | 1.0003 | `insert_fsyncs_per_op` |

Means are over n = 5 seeds. The CI is the file's bootstrap interval, which was not recomputed
because its resampling seed is not recorded for EX-7. Sample SDs are in `recompute_ex7.out`.

| Metric (nq-100k, seed 42, single run, no interval) | sever | noerase | softdelete |
|---|---|---|---|
| delete p50 / p99 per call (µs) | 109129.15 / 504919.806 | 59879.807 / 376340.546 | 906.747 / 18929.598 |
| deletes per second (`per_second`) | 7.626844206739731 | 12.698753413030902 | 741.3707917259521 |
| delete bytes per record | 39525.254797867616 | 27279.470812972013 | 10.524133718347402 |
| search p50 (µs) | 452.805 | 445.906 | 4710.848 |
| insert p50 (µs) | 15317.83 | 15307.098 | 1247.856 |
| peak memory (bytes) | 1225195520 | 1176211456 | 765685760 |
| reopen seconds | 8.065063195 | 21.058904848 | 0.749382822 |

- Fairness:
  - Same machine, data and seeds for all arms.
  - `softdelete` is a different (Part 2, unencrypted) engine.
  - CLAIMED (DB-113/114): timings overlapped other steps, so they are descriptive.
  - nq-100k has 1 seed and no interval.
- A single run cannot falsify anything, because EX-7 is descriptive.

## EX8 — Memory and recovery at one million vectors (project EX-8; P4-T15; measure) — **NOT RUN TO COMPLETION; NO RESULT EXISTS**

> **Read this as "not run because of device limits", not as "failed".** No measurement was produced.
> So there is no result that could pass or fail, and P4-T15 is a measure, not a gate.

- OBSERVED:
  - There is **no `p4-ex8` row of any kind** in `docs/RUN_LEDGER.jsonl` (`grep ex8` finds none)
    and **no `results/*ex8*` file**.
  - `traces/hpc-p4-ex8.log` holds only its two header lines (step, commit 96f9370, cmd
    `gates p4-ex8 --seed 42`).
  - `traces/hpc-summary.log` shows the step was SKIPPED in the 03:38 run-all ("SKIP"). Starts were
    logged at 2026-10-30T23:20:50, 10-31T03:31:48, 10-31T11:38:13 and 10-31T12:48:19 (`hpc-run.out`
    lines 48, 76, 110, 113). None has an `rc=` line.
- CLAIMED (DB-114, PROGRESS.md):
  - The 12:48 attempt was stopped by the kernel OOM killer after 6 h 11 min at 10.39 GB
    resident, inside WSL's 12 GB with no swap.
  - An earlier attempt was killed at 6.8 GB while running beside other steps.
  - The owner chose not to rerun it.
  - E1: no raw memory log of these figures was found in `traces/`, and `oomguard.log` was not parsed
    for them.
- Owner statement (9 Nov 2026, this session): EX-8 "was not failed but more like never runned due
  to device constraints".
- **Ruling:** the claimed OOM kill and the owner's account agree. Neither supports a measured value.
  The memory figure at 10^6 vectors is **E0: no measurement**. The only 10^6 figure in the repo is
  Appendix A's **prediction** of about 3.8 GB, which is not a result.

## EX9 — Durability cost (P2-T11; measure)

- File: L58 `p2-measures-nq-100k-20261008T013402Z.json`, commit 4913bd9, seed 42, nq-100k.
  STALE-POSSIBLE: Part 2 sources changed later, including E-2.

| Kind | `found.per_kind` value |
|---|---|
| insert | 8062.09474 bytes/op, 1.00036 fsyncs/op, 1.501273944860034 ms/op, 100000 ops |
| delete_one | 14156.824960594915 bytes/op, 1.0008487248918887 fsyncs/op, 1.6106494235541307 ms/op, 24743 ops |
| delete_user_many | 24608.149310730252 bytes/op, 1.0012574515648287 fsyncs/op, 1.6696851796758612 ms/op, 21472 ops |

| Other measure | Value |
|---|---|
| Recovery, `checkpoint_only` | 0.051788124 s |
| Recovery, `wal_only` | 0.847202078 s |
| Memory at end | VmHWM 1093044 kB, VmRSS 765920 kB |
| `run_seconds` | 227.322400586 |
| Storage checkpoint | 23363807 bytes, 15 fsyncs, 0.135542294 s |

## EX10 — Proof and verification cost (P3-T13; measure)

| File | Commit | prove_ms median / max | verify_ms median / max | delete_ms_simvfs median / max | certificate_bytes min / max (predicted d384) |
|---|---|---|---|---|---|
| L109 `p3-measures-nq-10k-20261019T044654Z.json` | 30e4497 | 12.171319 / 34.373718 | 2.2043179999999998 / 12.462292 | 9.046386 / 29.856475 | 1197 / 13645 (14093) |
| **L182 `p3-measures-nq-10k-20261030T232049Z.json`** | 7c445b5 | **15.783409000000002 / 46.286774** | **2.744998 / 13.741111** | 13.377894 / 41.066043 | 1197 / 13645 (14093) |

20 deletions and 200 proofs, d = 384. Both runs are STALE-POSSIBLE.

## EX11 — "The ghost" demo (P1-T14; measure)

- File `artefacts/demo/idea-nq-10k-seed42.json` (git-ignored, **mtime 2026-11-09 19:51**, not in
  the ledger, producing commit UNKNOWN).
- `ghost.per_group`: 4 groups. Example group `spawn-5c926341a140d9ed`:
  - `soft_delete_distance` 0.005035506396513171
  - `float_mean_max_abs_diff` 9.313225746154785e-09
  - `sever_max_abs_diff` 0
- The second group has `float_mean_max_abs_diff` 1.862645149230957e-08.
- `search.deleted_returned_after` 0 over 3,452 queries.
- Baselines: soft-delete IVF and a float running mean, implemented in `sever-p1`.

## EX12 — Clean-room AI fair testing (`scripts/fair.sh`; FT-1…FT-10)

| Run (results/fair-*.json) | Part | Commit | Outcome | Tests / failing | Oracle judge verdicts (of 10 sampled) | Session cost USD (sum of `sessions.cost_usd`) |
|---|---|---|---|---|---|---|
| 20261008T161930Z-p2-d76a93aa | 2 | d76a93a | FAIL ("valid planted bugs 0 of 0", oracle.json missing) | 65 / 0 | — | 2.98 |
| 20261008T164154Z-p2-42fc06df | 2 | 42fc06d | **no outcome row in the ledger** (L74 started only); its suite is used by `cleanroom-p2-after-e1/e2.json` | 256 / 0 after E-1 (255 passed, 1 skipped) | — | — |
| 20261020T091030Z-p3-4cccfae9 | 3 | 4cccfae | FAIL | 115 / 10 | AGREE 7, CANNOT_DERIVE 3 | 6.8 |
| 20261020T094639Z-p4-9189b50a | 4 | 9189b50 | FAIL | 146 / 1 | 7 / 3 | 4.78 |
| 20261020T141335Z-p3-3f2aef5b | 3 | 3f2aef5 | FAIL | 172 / 2 | 8 / 2 | 6.28 |
| 20261020T145844Z-p4-4ecbd6cf | 4 | 4ecbd6c | FAIL | 149 / 3 | 7 / 3 | 4.12 |
| 20261031T225306Z-p3-1479019b | 3 | 1479019 | FAIL (BH-7/BH-8 findings) | 140 / 2 | 9 / 1 | 7.31 |
| 20261101T130254Z-p3-5fee0df5 | 3 | 5fee0df | FAIL (2 spec gaps → G-52) | 178 / 2 | 5 / 5 | 5.93 |
| **20261101T134211Z-p3-bb4bac5e** | 3 | bb4bac5 (ledger dirty) | **PASS** | 180 / 0 | AGREE 5, CANNOT_DERIVE 5 | 6.38 |
| 20261101T142251Z-p4-a3040146 | 4 | a304014 | FAIL (no p4-mutants PASS yet) | 110 / 0 | 8 / 2 | 4.91 |
| 20261101T175539Z-p4-587aa09b | 4 | 587aa09 | FAIL (DB-118 empty-vector bug) | 148 / 1 | 7 / 3 | 5.45 |
| **20261101T192712Z-p4-36291aec** | 4 | 36291ae (ledger dirty) | **PASS** | 101 / 0 | AGREE 8, CANNOT_DERIVE 2 | 3.71 |

Four DRY runs use stub sessions. In every non-dry run `planted` is `[]`. The planted-bug check
became "cargo-mutants gate PASS in the ledger (DB-75)" (`rows`). Models: tester `opus`, judges
`sonnet` (`sessions`).

## EX13 — Studio: SEVER-DB vs Chroma deletion (DB-119) — **no raw data found**

CLAIMED (DB-119): "after `delete()`, `get` and `query` return nothing, and the scan still finds 3/3
IDs, 6/6 text windows and 3/3 vectors" (3 notes, 384-D). No result file, log or ledger row for
this was found (E1). Comparison fairness is UNKNOWN.

## Experiments a reader might assume exist but do not (detail in 05 §4)

- No comparison against production vector databases (Milvus, Qdrant, Weaviate, pgvector), except
  the unrecorded 3-note Chroma spike.
- No scalability curve beyond nq-1m recall, because EX-8 never produced a result.
- No concurrency or multi-client throughput experiment.
- No d ≠ 384 runs.
- No real-hardware power-loss test; crashes are simulated with SimVfs.
- No multiple-machine runs.
