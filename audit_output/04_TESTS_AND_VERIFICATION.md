# 04 · Tests and verification (audit)

**How to read this.**
- Re-run column: **EXECUTED-NOW** means run by this audit on 2026-11-09 at HEAD `af8fed2`, with
  the output in `results_collected/rerun_*.log`. **READ-FROM-FILE** means taken from a recorded file.
  **NOT RE-RUN** means not run; the command is given.
- Counts of test functions are `grep` counts (`#[test]`, `def test_`). They are OBSERVED as counts
  of source occurrences, not executed cases.
- Gate thresholds are CLAIMED by each result's `gate` string. Values are OBSERVED in the file.

| ID | Test / check | What it covers (CLAIMED unless noted) | How to run | Last recorded result (READ-FROM-FILE) | Re-run now | Counts |
|---|---|---|---|---|---|---|
| T1 | Python unit, property and stateful suite | Reference models, partition builder, testkits, SDK wrappers, architecture rules (`tests/architecture`) | `PYTHONHASHSEED=0 uv run --no-sync pytest -q -m "not slow" --ignore=tests/cleanroom` (the CI form, `scripts/ci.sh:73`) | ci-fast-local.log: STEP python-tests PASS (undated). full-checks-635a8c9.log: python-tests **FAIL** (collection errors). 69a33f4: PASS | **EXECUTED-NOW: 271 passed, 2 deselected in 78.71 s, exit 0.** A plain `pytest -m "not slow"` from the root **fails**: 3 collection errors in `tests/cleanroom/p4/…` (`AttributeError: module 'helpers' has no attribute 'frozen_id'`) | `def test_` occurrences: 194 under `python/`, 33 under `tests/` (excluding cleanroom) = 227 source functions; 271 collected cases (parametrisation) |
| T2 | Rust workspace tests | Unit, proptest and integration tests of every crate | `cargo test --workspace` (also `verifier/`, `audit/` workspaces) | Inside full-checks: `rust-tests` PASS in `results/p4-checks-20261101T022137Z.json` (L198, 94d0b24) | NOT RE-RUN (owner chose the quick set) | `#[test]` occurrences: 565 in `crates/`, `verifier/`, `audit/` (`grep -r '#[test]'`); 10 `proptest!` blocks |
| T3 | Full-tier check suite (`scripts/ci.sh full-checks`) | fmt, clippy (also sabotage builds), rust and python tests, mypy, ruff, spec-trace, oracle and proof checks, registers, RFC vectors, freeze guard, fair-check, MSRV, cargo-deny, docs, sabotage | `PYTHONPATH=python uv run python -m sever_testkit_pN.gates pN-checks` | P1 L36 PASS (17 steps); P2 L82 PASS (29 steps); P3 L196 PASS and P4 L198 PASS (42 steps each, 94d0b24, CURRENT except sever-py). After v1.0: `traces/full-checks-635a8c9.log` 34 PASS / 4 FAIL (ruff, ruff-format, python-tests, python-slow); `full-checks-69a33f4.log` 42 PASS / 1 FAIL (cleanroom-kept) | NOT RE-RUN (≈ 30–60 min each; seconds field 1949–2041) | steps listed in each result's `steps` |
| T4 | Coverage gates | P1-T10, P2-T9, P3-T9, P4-T10 line/branch thresholds | `gates pN-coverage` | P1 0.9591/0.8701 (Rust), 0.9885 (Py). P2 0.9481/0.8670. P3 final L200: crypto 0.954233, commit 0.915842, log 0.930937, cert 0.958861, verifier 0.962707. P4 final L202: keys 0.981273, seal 0.961479, erasure 0.955752. Earlier FAILs: P3 L107 (verifier 0.777624), L115 (0.944751); P4 L179 (0.913858 / 0.933744 / 0.923077) | NOT RE-RUN. Ratios recomputed E4 (`recompute_gates.out`) | Raw: `traces/cov-p2-full.json`, `traces/coverage-python.json` |
| T5 | Mutation testing (cargo-mutants) | P1-T11, P2-T9, P3-T9, P4-T10; survivors triaged in `docs/MUTANTS_P*.md` | `gates pN-mutants --jobs N` | P1 325/347 = 0.9366 (L30). P2 652/713 = 0.9144 (L60). P3 final L158: cert 132/155 = 0.8516129032258064, crypto 114/122 = 0.9344, log 335/376 = 0.8910, verifier 219/225 = 0.9733. P4 final L220: erasure 123/136 = 0.9044, keys 84/86 = 0.9767, seal 139/145 = 0.9586. FAILs: P3 L147 (verifier 0 of 0 tested, cert 0.8013), L156 (setup fault, all 0.0); P4 L170 (erasure 0.7652, seal 0.7793, 71 untriaged), L189 (FAIL, 1 untriaged timeout; **owner accepted as pass**) | NOT RE-RUN (2.5–3.5 h each). Scores recomputed E4 as caught/(caught+missed+timeout) | total mutants P1 418, P2 868 (`counts.total_mutants`) |
| T6 | Fuzzing (cargo-fuzz / libFuzzer) | Every parser: P1 `artefact_parse`, `blob_parse`; P2 `wal_record`, `manifest`, `checkpoint_file`, `store_record`; P3 `certificate`, `log_record`, `witnessed`, `placement`, `verifier/fuzz:verify`, `audit/fuzz:export`; P4 `key_slot`, `wrapped_value`, `bucket_block`, `envelope`, `scan_targets` | `gates pN-fuzz --runs 100000000` | All final runs PASS at 10^8 runs/target, `crashed` false (P1 L28, P2 L50, P3 L162, P4 L153). P1 L18 FAIL: real OOM crash in `artefact_parse`, fixed. P2 L43/L45 FAIL: harness (no target built) | NOT RE-RUN (up to 40,084 s for `audit/fuzz:export`) | 17 targets |
| T7 | Sabotage builds (SB-1…SB-30) | Each `sabotage-SB-N` feature breaks one rule; a test must go red | inside `pN-checks` (`sabotage` step); P2 also `gates p2-sabotage` | `p2-sabotage-20261007T230807Z.json` PASS, e.g. "PASS SB-1 (sever-index): 9 failing test line(s)". P3/P4 via the checks step (PASS) | NOT RE-RUN | 30 SB items claimed |
| T8 | Proof spikes (extension points) | Contract suites pass for real impls and fail for wrong ones (Build §3.4) | `gates pN-spikes` | P1 L16, P2 L48, P3 L111/L167/L204 PASS | NOT RE-RUN | `tests` key: 7 / 7 / 4 |
| T9 | Requirement traceability | Every `SR-…` requirement has a labelled test | `spec-trace` (fast tier) | TRACE_PART_1..4: 70/70, 46/46, 108/108, 69/69 (E2) | NOT RE-RUN | — |
| T10 | Red proofs (`tests/proofs/`) | A patch that breaks one rule must turn the labelled tests red (CLAUDE.md §6.3) | `python -m sever_testkit_pN.proofs run` | PROOFS_P2: "211 of 211 proofs hold" (035d70b, 10-08). PROOFS_P3: "31 of 31" (219547f, 10-15). PROOFS_P4: "79 of 79" (52a099a, 10-19). **Not regenerated since; P3/P4 now have far more patch files** | NOT RE-RUN (long) | patch files: p2 141, p3 172, p4 93, inspect 9, scan 6 |
| T11 | Test-oracle check | Each SR-labelled test declares oracle A/B/B-shared/C/D | `python -m sever_testkit_p2.oracle_check check` (+ p3, p4) | fast tier steps `oracle-check-p2..p4` PASS (ci-fast-local.log, undated) | NOT RE-RUN | reports `docs/TEST_ORACLES_P2..P4.md` (E2) |
| T12 | Clean-room fair-testing suites | Fresh AI tester writes tests from the spec only, run against the sealed engine | `scripts/fair.sh run N` (costs API money) | Part 3 PASS 180/0; Part 4 PASS 101/0; Part 2 never PASS (03 EX12). Kept suites: `tests/cleanroom/` (171 `def test_`) | NOT RE-RUN. Note: kept suites cannot be collected together with the main suite (see T1) | — |
| T13 | Freeze guard | Frozen files unchanged | `sha256sum -c freeze/PART-N.sha256` | fast tier `freeze-guard` PASS | **EXECUTED-NOW: 81, 250, 342, 191 OK; 0 mismatches** (`rerun_sha256_checks.log`) | 864 files |
| T14 | Dataset manifest | P0 data unchanged | `(cd datasets && sha256sum -c MANIFEST.sha256)` | README: "9 files, all OK" | **EXECUTED-NOW: 9/9 OK** | — |
| T15 | Offline verifier on stored certificates | §11.3 verification without a database | `verifier/target/release/sever-verify CERT --anchors anchors.json` | `artefacts/demo/receipt-nq-10k-seed42.json`: verify accepted true; flipped "REJECT (step 2 …)" | **EXECUTED-NOW: accepted:true (exit 0); flipped → accepted:false, step 2 (exit 1)** | 2 certificates |
| T16 | Crash campaigns | T-1 | see 03 EX1 | 03 EX1 | NOT RE-RUN (hours–days) | 343,837 / 938,129 / 45,635 + 16,965 crash points |
| T17 | Differential and replay vs reference model | T-3 | see 03 EX3 | 03 EX3 | NOT RE-RUN | — |
| T18 | Attack suite AT-1…AT-20 | T-4 | see 03 EX4 | 03 EX4 | NOT RE-RUN (≈ 20 min each per `hpc-summary.log`), verifier spot-checked in T15 | 45,282 attacks/seed |
| T19 | Forensic scanner sensitivity | T-2 | see 03 EX2 | 03 EX2 | NOT RE-RUN (9 h 12 min) | 30 scans |
| T20 | E2E and errata tests | `tests/e2e`, `tests/e2e_p3`, `tests/errata` | in T1 or T3 (`python-slow`) | — | partly within T1's 271 | 9 + 5 + 1 `def test_` |
| T21 | Studio tests | Studio boundary and features (`studio/tests/test_boundary.py` etc.) | `studio/studio.sh test` | DB-119 claims tests; no recorded result read | NOT RE-RUN | — |
| T22 | Lint and types | rustfmt, clippy `-D warnings`, ruff, mypy `--strict` | `cargo fmt --check`, `cargo clippy …`, `uv run ruff check`, `uv run mypy python` | ci-fast-local.log PASS; full-checks-635a8c9 ruff FAIL (fixed in 69a33f4 per commit message) | NOT RE-RUN | — |

## Determinism, security and attack testing (where the evidence lives)

| Kind | Present? | Evidence |
|---|---|---|
| Determinism or flakiness | Yes, one documented flaky test | DB-114 (CLAIMED, E1): `p4_erasure_startup_refuses_a_missing_or_torn_active_key_slot` failed about 1 in 200 runs. It was fixed, with 20,000 runs per build: old 98 failures, new 0. No raw log found |
| Crash or fault injection | Yes | T16 (SimVfs). Part 4 adds torn key slots and key loss |
| Mutation | Yes | T5 |
| Fuzz | Yes | T6 |
| Security / attack | Yes | T18 (AT-1…AT-20) and T19. CLAIMED threat model in overview §4. No external pentest |
| Concurrency | Limited | P2-T4 "a reader at every protocol step" (inside T3, CLAIMED README:204). No multi-client load test |
| Coverage | Yes | T4. Thresholds met on the final commit for Parts 3 and 4 |

## Not re-run (commands)

| What | Command | Reason |
|---|---|---|
| All Rust tests | `cargo test --workspace` (+ `cd verifier && cargo test`, `cd audit && cargo test`) | owner chose the quick set |
| Full-tier checks | `PYTHONPATH=python uv run python -m sever_testkit_p4.gates p4-checks` (also p1, p2, p3) | 30–60 min |
| Crash campaigns | `… sever_testkit_p3.gates p3-crash --data nq-10k --all-seeds`; `… sever_testkit_p4.gates p4-crash --data nq-10k --seed 42 --seed 123 --seed 777 --jobs 3 --crash-from 17694 --limit-ops 17994` | 10 h – days |
| Forensics | `… sever_testkit_p4.gates p4-forensics --data nq-10k --seeds 42 123 777 2024 9999 --image-gib 16` (ledger form) | 9 h, needs a 16 GiB image |
| Mutants | `… gates p3-mutants --jobs 3`, `… gates p4-mutants --jobs 4` | ~3 h each |
| Fuzz | `… gates pN-fuzz --runs 100000000` | up to 11 h |
| EX-6 / EX-7 / EX-8 | `… sever_testkit_p4.gates p4-ex6 --data nq-10k --seeds …`; `p4-ex7 …`; `p4-ex8 --seed 42` | hours; EX-8 does not fit this machine's memory (CLAIMED DB-114) |
| Proof runs | `… sever_testkit_p3.proofs run`, `… sever_testkit_p4.proofs run` | long; would regenerate tracked docs (not allowed) |
| Fair testing | `scripts/fair.sh run 3` | costs API money (owner rule) |
| Studio | `studio/studio.sh test` | separate environment |
