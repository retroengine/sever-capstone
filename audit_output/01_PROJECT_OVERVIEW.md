# 01 · Project overview (audit)

| Field | Value | Label |
|---|---|---|
| Audit date | 2026-11-09 (UTC 20:29–21:xx) | OBSERVED |
| Git HEAD | `af8fed22f9be9cd8595f271d7b692e5664fdf0a6` on branch `p6-studio-company` (`main` points to the same commit) | OBSERVED (`git rev-parse HEAD`, `git branch -a`) |
| Release tag | `v1.0.0` = `part-4-frozen` = `7942c1d` (2026-11-01 19:53 UTC); 10 commits after it reach HEAD | OBSERVED (`git log v1.0.0..HEAD`) |
| Working tree at start | clean (`git status --porcelain` empty) | OBSERVED |
| Auditor | Claude (AI) in one session, read-only except `audit_output/` | — |

**ID conventions used in all five audit docs.** Audit IDs have **no hyphen**: `C1…` claims, `EX1…`
experiments, `T1…` tests and checks, `D1…` discrepancies. Project IDs keep their hyphens: `EX-1`
(overview experiment), `T-1` (pre-registered target), `P3-T4` (gate), `DB-116` (decision), `L-28`
(limit), `G-34` (spec gap). `EXn` is chosen to match `EX-n` where the project has one. `L<n>` in
the evidence columns means line *n* of `docs/RUN_LEDGER.jsonl`.

**Evidence grades.** E4 = recomputed by this audit from raw per-seed/per-run data. E3 = read from a
raw run output. E2 = from a generated summary. E1 = prose only. E0 = nothing found.

---

## 1. What the project is

- CLAIMED (CLAUDE.md §1, README.md:1–12): SEVER-DB is a vector database with **provable deletion**.
  Each group of vectors keeps an exact integer sum `S` and count `n` of Q24-quantised vectors, so a
  delete subtracts exactly. A Pedersen commitment per group, an RFC 9162 transparency log and a
  signed deletion certificate let anyone verify a deletion offline. Secrets are encrypted under a
  three-level key hierarchy, and each deletion destroys the old key (crypto-shredding).
- CLAIMED (CLAUDE.md §6.1): it was built in four parts, each adding one claim and then frozen:
  1. **The Idea**: exact deletion.
  2. **The Database**: crash safety and atomic multi-group delete.
  3. **The Receipt**: certificates.
  4. **The Erasure**: nothing recoverable from raw storage.
- OBSERVED: four freeze manifests exist (`freeze/PART-1..4.sha256`, with 81, 250, 342 and 191
  files). All 864 hashes match the working tree at HEAD (`results_collected/rerun_sha256_checks.log`,
  EXECUTED-NOW). The tags `part-1-frozen` (b1d4576, 2026-10-06), `part-2-frozen-e1` (7729302,
  2026-10-15), `part-2-frozen-e2` (a244264, 2026-10-15), `part-3-frozen` (a304014, 2026-11-01) and
  `part-4-frozen`/`v1.0.0` (7942c1d, 2026-11-01) exist.
- OBSERVED: no tag `part-2-frozen` exists, although CLAUDE.md §6.1's table names one. The memory
  notes say it was deleted as premature.
- OBSERVED: a desktop demo, "SEVER-DB Studio", lives in `studio/` with its own environment. It
  includes a Chroma comparison and a Groq LLM assistant (DB-119; commits b51404a…af8fed2, 6–9 Nov).

## 2. Architecture and code map (OBSERVED from Cargo.toml descriptions and file counts)

Line counts are `*.rs` files under each `src/`, including inline test modules. Test counts are
`grep -c '#[test]'` (Rust) or `def test_` (Python) and are approximate. Neither is a coverage figure.

### Rust workspace (`crates/*`, edition 2024, toolchain pinned 1.98.1 in `rust-toolchain.toml`, MSRV 1.85)

| Crate | Part | Responsibility (from its Cargo.toml) | src lines | #[test] |
|---|---|---|---|---|
| sever-types | 1 | IDs, constants, core errors, secret buffers | 1159 | 25 |
| sever-quant | 1 | Normalisation check, Q24 quantise/dequantise (§4.1–4.3) | 386 | 14 |
| sever-index | 1 | Groups, exact accumulators, routing, holding area, flush, plan/apply (§5, §7) | 3161 | 44 |
| sever-search | 1 | IVF-flat search, pinned 8-lane kernel, scalar and AVX2 (§8) | 485 | 10 |
| sever-partition | 1 | Parse/validate partition artefact `.svp` (§6.3) | 337 | 5 |
| sever-tracekit | 1 | Replay traces: engine vs reference model | 487 | 0 |
| sever-spec | 1 | `#[spec("SR-…")]` test-label macro | 40 | 0 |
| sever-p1 | 1 | Part 1 composition root, ghost baselines, `sever-demo` | 1470 | 11 |
| sever-vfs | 2 | EP-5 Vfs: PosixVfs and crash-simulating SimVfs (§12.2) | 2567 | 36 |
| sever-wal | 2 | Write-ahead log, torn tails, replay (§12.3) | 1205 | 27 |
| sever-format | 2 | Byte-exact checksummed storage formats (§14) | 3245 | 61 |
| sever-txn | 2 | EP-6 Sealer, EP-7 TxnParticipant, commit protocol | 2824 | 22 |
| sever-checkpoint | 2 | Storage checkpoints, MANIFEST install (§12.4) | 535 | 6 |
| sever-appendstore | 2 | EP-8 append-only stores, passage payloads | 509 | 9 |
| sever-engine | 2 | Collections, API, recovery with full invariant check | 1255 | 31 |
| sever-crashkit | 2 | Crash-campaign driver on SimVfs | 1948 | 3 |
| sever-p2, sever-py-p2 | 2 | Part 2 root and CLI; PyO3 SDK | 950, 322 | 3, 0 |
| sever-crypto | 3 | Generators, commitments, proofs of knowledge, nonces, signatures | 2006 | 35 |
| sever-commit | 3 | EP-1 CommitmentExtension: `C_S`, `r_agg`, `C_t`, `r_t` | 908 | 11 |
| sever-log | 3 | RFC 9162 transparency log, proofs, checkpoints, witnesses (§10) | 2805 | 24 |
| sever-cert | 3 | Deletion certificates: TLV encoding, parser, builder, signing | 1962 | 26 |
| sever-crashkit-p3, sever-p3, sever-py-p3 | 3 | Gate kit, Part 3 root and CLI, SDK | 2477, 2070, 628 | 0, 16, 0 |
| sever-keys | 4 | Key types in secret memory, two-slot key file | 1087 | 22 |
| sever-seal | 4 | AES-256-GCM-SIV sealing (EP-6 AeadSealer) | 1629 | 17 |
| sever-erasure | 4 | Key-rotation participant, crypto-shredding | 2699 | 36 |
| sever-platform | 4 | Startup refusals (swap, mlock, filesystem), memory hygiene | 978 | 17 |
| sever-scan | 4 | Forensic scanner of raw images (EX-2, §16.3) | 2085 | 6 |
| sever-eval | 4 | Measuring harness `sever-bench` (EX-7, EX-8) | 623 | 2 |
| sever-crashkit-p4 | 4 | Part 4 crash campaign incl. key disk | 2944 | 1 |
| sever-db, sever-py | 4 | Final composition root + `sever-db` CLI; final SDK `sever_db` | 2137, 775 | 20, 0 |
| sever-explain | Studio | Explains routing/search in engine arithmetic (added 2026-10-23) | 271 | 4 |
| `verifier/` (separate workspace) | 3 | Offline certificate verifier `sever-verify` (§11.3) | 1572 | 19 |
| `audit/` (separate workspace) | 3 | Log-export auditor `sever-audit` | 1602 | 2 |

### Python (`python/`, Python 3.13, `uv.lock`)

| Package | Role | non-test lines | def test_ |
|---|---|---|---|
| sever_partition | C-15 partition builder | 406 | 16 |
| sever_refmodel_core / _durable / _certs | C-18 reference models (oracles), Parts 1 / 2 / 3 | 547 / 284 / 2184 | 27 / 6 / 31 |
| sever_testkit, _p2, _p3, _p4 | Gate runners (`python -m … gates <step>`), which write `results/` and the ledger | 1373 / 1425 / 1960 / 1250 | 4 / 21 / 22 / 15 |
| sever_experiments | EX-2, EX-6, EX-7 code (for example `ex6.py`) | 851 | 2 |
| sever_fair | Clean-room AI fair-testing harness (`scripts/fair.sh`) | 2488 | 14 |
| sever_db, sever_db_p2, sever_db_p3 | SDK wrappers | 368 / 156 / 324 | 16 / 2 / 13 |
| sever_demo, sever_demo_p3 | Demo report renderers | 265 / 274 | 3 / 2 |

### Dependencies (pinned)

OBSERVED in `pyproject.toml`: numpy 2.5.*, scikit-learn 1.9.*, pyarrow 25.0.*, faiss-cpu ≥ 1.15.1,
maturin 1.15.*. Dev tools: pytest, hypothesis, ruff, mypy, mutmut, import-linter. Exact versions
are in `uv.lock`. The Rust crate versions are in `Cargo.lock`, which this audit did not enumerate.
The Studio's own environment (`studio/pyproject.toml`, `studio/uv.lock`) was not enumerated.

### Data (OBSERVED, `datasets/PINS.json`, `datasets/processed/meta.json`; manifest verified EXECUTED-NOW)

| Item | Value |
|---|---|
| Encoder | `sentence-transformers/all-MiniLM-L6-v2` rev `1110a243…`, d = 384, float32 |
| Corpus | BeIR/nq rev `b7253e6c…`: `size_big` 1,000,000, `size_small` 100,000 (prefix of big), 3,452 queries, 4,201 judgements (BeIR/nq-qrels rev `519acd4e…`) |
| Partition fit data | allenai/sciq rev `2c94ad3e…`: 13,679 passages |
| Encoder truncation | `truncation_rate` 0.049148 (49,148 of 1,000,000 NQ passages truncated) |
| Overlap checks | `non_overlap`: ids 0, queries_vs_nq_text 0, sciq_vs_nq_text 0 |
| Slices used by gates | `nq-10k`, `nq-100k`, `nq-1m` (sub-slices of the 1 M set) |

## 3. Environment and hardware

- OBSERVED (ledger): all 224 rows record `machine x86_64`, kernel `6.6.114.1-microsoft-standard-WSL2`,
  `wsl true`, cpu_flags `avx2 fma aes sha_ni` and python 3.13.14. `swap_on` is true in 172 rows and
  false in 52 (`recompute/ledger.py`). The ledger records no CPU model, core count, RAM or OS release.
- OBSERVED (`traces/hpc-summary.log`): `nproc=8` on every run-all start.
- OBSERVED today: `lscpu` shows Intel Core Ultra 5 226V with 8 CPUs; `free` shows 11 GiB visible
  to WSL; `/etc/os-release` shows Ubuntu 26.04 LTS.
- CLAIMED (DB-113): the v1.0 run was on the laptop (Core Ultra 5 226V, 8 cores, 16 GB, WSL2 Ubuntu
  24.04 with 12 GB) because "the college HPC is no longer available".
- INFERRED: every recorded run used the same machine class (same kernel string throughout). The
  `hpc-*` log names are historical. The scripts are named after the HPC plan (DB-111), but the runs
  were on the laptop. The OS is Ubuntu 26.04 LTS, confirmed by the owner on 9 Nov 2026 (`lsb_release`: 26.04,
  codename resolute). DB-113's "24.04" is wrong.

## 4. How to build, run and reproduce (CLAIMED in CLAUDE.md §9 and README; spot-checked where marked)

| Purpose | Command | Checked by audit |
|---|---|---|
| Environment | `uv sync --locked`. `uv sync` removes the native SDK modules; rebuild them with `uv run --no-sync maturin develop --release --uv -m crates/sever-py/Cargo.toml` | not run (it would modify `.venv`) |
| Python tests (fast) | `PYTHONHASHSEED=0 uv run --no-sync pytest -q -m "not slow" --ignore=tests/cleanroom` | **EXECUTED-NOW: 271 passed, 2 deselected, 78.71 s.** Plain `pytest` without `--ignore` fails at collection (3 errors) |
| Rust tests | `cargo test --workspace` | not run (owner chose the quick set) |
| Fast CI tier | `scripts/ci.sh fast` | not run; `traces/ci-fast-local.log` shows 36 STEP PASS lines (undated, READ-FROM-FILE) |
| Offline verifier | `verifier/target/release/sever-verify CERT --anchors anchors.json` | **EXECUTED-NOW**: accepts the stored demo certificate and rejects the flipped one at step 2 |
| Gates (each writes the ledger and `results/`) | `PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_testkit_pN.gates <step> …` (exact commands are in each ledger row's `command`) | not run (hours) |
| Laptop gate run | `scripts/hpc/run-all.sh` / `steps.sh` (DB-113) | not run |
| Fair testing | `scripts/fair.sh run N` (costs API money) | not run |
| Studio | `studio/studio.sh setup`, `prepare`, `run` | not run |

## 5. Timeline from git history (OBSERVED; 439 commits; dates are author dates, UTC)

| Date | Event (commit) |
|---|---|
| 2026-09-27 | Project overview and spec committed (84161ca). Pre-registered targets T-1…T-6 enter in this commit and never change afterwards (`git log -S`). Data pinned 12:11 UTC, built 21:08 UTC (`PINS.json`, `meta.json`) |
| 2026-10-04 | First crates: sever-types, -quant, -index, -search, -partition, -tracekit. First ledger row (L1, 15:23 UTC) |
| 2026-10-05/06 | Part 1 gates (L9–L38). `part-1-frozen` b1d4576 on 10-06 17:45 |
| 2026-10-07/08 | Part 2 crates and gates (L40–L67). Test-oracle audit on 10-08. Fair runs for Part 2 on 10-08 (L68–L74). README says Part 2 "frozen 8 Oct" |
| 2026-10-15 | Errata E-1 (SDK deadlock found by a clean-room test) and E-2 (EP-7 pre_transaction): tags part-2-frozen-e1/-e2. Part 3 crates start (sever-crypto, -commit, -log, -cert) |
| 2026-10-16–19 | Verifier, auditor and Part 3 roots on 10-16. Part 4 crates on 10-18/19. Interim Part 3 gate runs on 10-19 (L97–L123) |
| 2026-10-20 | Fair runs for Parts 3 and 4: dry runs, then FAIL ×4 (L125–L137) |
| 2026-10-22–24 | Studio added (063642d); `sever-explain`; DB-111 (HPC plan) |
| 2026-10-29–31 | v1.0 laptop gate run (`hpc-summary.log`, commits 4dcfbe0 → 7c445b5 → 96f9370/9e11156). DB-113 and DB-114 record faults and reruns; EX-8 does not complete |
| 2026-11-01 | Bug hunt BH-6/7/9 fixes (a35c5c2, c629c6a, d5e41db, 09ecb78). Partial final rerun on 94d0b24 (L196–L211). Fair PASS P3 (L215) and P4 (L224). DB-118 SDK fix (36291ae). Tags part-3-frozen (a304014), part-4-frozen/v1.0.0 (7942c1d) |
| 2026-11-06 | `project_report/` (635a8c9, 52 files) and CI fixes (69a33f4, 0d6482b). Studio company demo (b51404a, 6010482) |
| 2026-11-09 | `docs/01–04_*.md` research-paper set (0d71615). Studio fixes (294f1e3, 9ca1756, af8fed2) |

Commits per day: 09-27 17, 10-01 6, 10-02 4, 10-04 14, 10-05 21, 10-06 19, 10-07 43, 10-08 47,
10-15 34, 10-16 10, 10-17 2, 10-18 15, 10-19 38, 10-20 20, 10-21 29, 10-22 7, 10-23 43, 10-24 9,
10-29 6, 10-30 16, 10-31 8, 11-01 22, 11-06 5, 11-09 4 (`recompute/git_log.txt`).

**Docs and results that predate major changes (INFERRED from the dates above):**
- `README.md`: last commit 1479019, 2026-10-31. It predates the 1 Nov fixes, the freezes and the tags.
- `docs/PROOFS_P3.md` (10-15) and `docs/PROOFS_P4.md` (10-19) predate most of their proof patches.
- `docs/TRACE_PART_4.md` (10-21).
- Every Part 3/4 result produced at 7c445b5 or earlier predates the BH-6/7/9 code changes of 1 Nov.
  Details are in 03 and 05.
- Since v1.0.0 the engine sources are unchanged: `git diff --stat v1.0.0 HEAD -- crates python
  verifier configs scripts` shows only `scripts/ci.sh`.

## 6. Where results, logs and reports live (OBSERVED)

| Location | Content | Size / count | Kind |
|---|---|---|---|
| `results/*.json` | One file per gate or measure run, written by the runners | 94 files, 900 K | raw (E3) |
| `docs/RUN_LEDGER.jsonl` | Append-only run ledger with commit, dirty flag, outcome, result_file and result_sha256 | 224 rows | raw index (E3) |
| `traces/*.log`, `hpc-summary.log`, `hpc-run.out`, `oomguard.log` | Step logs of the laptop run | ~80 small files | raw (E3) |
| `traces/*.jsonl` (+ `.xz`) | Per-operation traces (P1 traces, attack sets) | 20 files > 50 MB; 13 G total | raw, not copied |
| `traces/p4-crash-nq-10k-seed{42,123,777}.jsonl` (+ `.progress`) | Raw per-crash-point records of the stopped final-commit P4-T3 run (1 Nov) | 3 × ~0.94 MB | raw (E3), copied (D4) |
| `traces/archive-*`, `traces/p4-interim/`, `traces/mutants-*` | Archived or interim runs | dirs | stale / interim |
| `artefacts/` (git-ignored) | Partition artefacts and their JSON (P1-T6 diffs), demo outputs | 45 files | raw (E3); demo JSON not in the ledger |
| `freeze/` | Freeze hashes | 4 files | raw |
| `docs/audit/FAIRNESS_P*.md` | Generated fair-testing reports | 6 | E2 |
| `docs/PROOFS_P*.md`, `MUTANTS_P*.md`, `TEST_ORACLES_P*.md`, `TRACE_PART_*.md`, `RESULTS.md` | Generated summaries | — | E2 |
| `README.md`, `docs/PROGRESS.md`, overview DB-entries, `ERRATA.md`, `docs/SPEC_GAPS.md` | Prose | — | E1 |
| `docs/01–04_*.md` (2026-11-09) and `project_report/` (2026-11-06) | AI-written paper and report material | 4 + 52 files | E1 claims |
| `~/.sever-fair/runs/` (outside the repo) | Fair-run session logs | 20 run dirs | not read |
| `studio/work/` | Studio databases with keys | — | excluded (secrets) |

## 7. Audit self-verification (Phase 6, EXECUTED-NOW 2026-11-09)

| Check | Result | File |
|---|---|---|
| 29 numbers quoted in these docs re-read at their source JSON, trace or ledger keys | 29/29 match. 3 text-format mismatches (a Unicode minus sign, a rounded score, the wording of a boolean) were fixed first | `recompute/selfcheck.log` |
| Every file named in the docs is copied or listed in MANIFEST.csv | 98 references; 4 unresolved names, each explained (source code, filename pattern, quoted error text) | `recompute/linkcheck.log` |
| Original files unchanged | `git status --porcelain` shows only `?? audit_output/`. `git diff --stat` is empty | — |
| Secrets | No key directories, `SECRETS` files, `.env`, private keys or Groq keys were copied. The regex scan of `audit_output/` finds nothing. The only `r_t` string is the boolean `"planted_found": {"r_t": true}` in the forensics result. Compressed raw traces (`traces/*.xz`) and `studio/work/` were deliberately not copied | `results_collected/MANIFEST.csv` (rows "NOT COPIED") |
| Size | `audit_output/` 5.0 MB. 224 files copied; 63 rows list files or directories not copied (> 50 MB, compressed traces, archives, key dirs) | MANIFEST.csv |

Scripts (all read-only on repo files; run with `python3 -I <script> .` from the repo root, or
`.venv/bin/python -I` for `recompute_ex6.py`, which needs numpy and scipy): `ledger.py`,
`recompute_gates.py`, `recompute_misc.py`, `recompute_ex6.py`, `recompute_ex7.py`,
`freshness.py`, `collect.py`, `claim_counts.py`, `selfcheck.py`, `linkcheck.py`.
