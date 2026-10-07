# Progress

Updated at the end of every session (CLAUDE.md §3.3). Newest session first in the log.

> **Draft written by Claude on 7 Oct 2026, for you to confirm** (CLAUDE.md §3.3). Parts 1 and 2 are
> built in write mode (your temporary rule: build everything first, study the code after). Read it
> before committing and change anything that is not how you see it.

## Now

- **Phase:** **Part 2, The Database** (Build §5), started 7 Oct 2026. Part 1 is frozen
  (`freeze/PART-1.sha256`, tag `part-1-frozen`); the freeze guard passes.
- **Working copy:** `~/sever-db` on the WSL ext4 disk since 4 Oct (the `C:` copy is a backup).
- **Git:** you commit from now on; Claude only leaves changes in the working tree and hands you the
  commands. The trunk is `main`. Part 2 work goes on short branches, one per module
  (`p2-sever-vfs`, `p2-sever-format`, …).
- **Decisions (7 Oct, Part 2 design review):** DB-46 (slot payload `id ‖ x̃ ‖ extension secret`;
  header `seal_version`) and DB-48 (`sealer_id` in every file; plaintext database, no
  confidentiality claim before Part 4) accepted; DB-65 (`create_dir`/`remove_dir` in the `Vfs`)
  closes G-13. DB-51 … DB-54 wait for Parts 3 and 4.
- **Machine:** WSL now has 10 GB (`C:\Users\saiki\.wslconfig`, `memory=10GB`), so the nq-100k
  gate runs three seeds at once (`--jobs 3`, 80 min).
- **Next:** `sever-format` (spec §14: pages, group header, slot, WAL records, `MANIFEST`,
  checkpoint files, append-store records; strict parsers). It must first define the byte layouts
  §14 leaves open (file headers with `sealer_id`, `MANIFEST`, `meta.bin`, `collections.bin`,
  `locator.bin`, WAL segment header): expect gap entries. Part 2 adds its own gate runners and tools
  in new modules; the Part 1 packages (including `sever_testkit`) are frozen (F-3).

## Part 2 modules (Build §5.5)

| Module | Status | Notes |
|---|---|---|
| `sever-vfs` | built | EP-5 `Vfs`; `PosixVfs`; `SimVfs` (current/durable views, crash at op N, tear, `DropAll`/`KeepAll`/`Random(seed)`, failed `fsync` loses the data like Linux, `fork`); EP-5 contract suite (functional + crash), 3 wrong backends fail it; 7 hand mutants all killed; MSRV-clean |
| `sever-format` | built | §14 codecs: file header, `MANIFEST`, segment header, `SECRETS`, group header, slot + payload (DB-46), WAL framing + typed records, paged checkpoint files, store records, the storage image (`DbImage::apply`, checkpoint streams); SB-11 red; gaps G-14…G-16 → DB-66…DB-68 |
| `sever-wal` | built | segments, one-append transactions, rollover, recovery that cuts the torn tail, covered-segment removal; crash at every op × 3 policies, every 512-byte tear, crash during recovery, proptest; SB-13 red. Durability helpers (`sever_vfs::durable`): SB-12, SB-14 red |
| `sever-appendstore` | built | EP-8 `AppendStore` + `FileStore` (segments, torn-tail cut at open, rollover); EP-8 contract suite, a wrong store fails it; crash at every op × 3 policies keeps every synced record |
| `sever-checkpoint` | built | §15.6 steps 1–4 (tmp dir, rename, MANIFEST via tmp+rename), strict load (paged files, WAL position, artefact names), cleanup of leftovers; crash at every op × 3 policies loads old or new; SB-12 red through it |
| `sever-txn` | built | EP-6 `Sealer` + `PlaintextSealer`, EP-7 `TxnParticipant`, EP-9 `Clock` (`SystemClock`, `SimClock`), each with a contract suite that wrong implementations fail; `StoredExtension` (codec beside the frozen EP-1); ChangeSet → after-images (put, move-last, drain/re-wrap, headers incl. holding count, counters, passage refs); decode + synthetic ChangeSet rebuild; the §5.4 protocol with step hooks; SB-15 red |
| (next) | | `sever-engine` |
| `sever-wal` | | §12.3; SB-11, SB-13 |
| `sever-appendstore` | | EP-8, §14.8 |
| `sever-checkpoint` | | §12.4, §15.6; SB-12 |
| `sever-txn` | | EP-6, EP-7, EP-9, §12.5; SB-14, SB-15 |
| `sever-engine` | | §12.7, §12.9, §15.7, §16.1 |
| `sever-crashkit`, `sever_refmodel_durable` | | EX-1 campaign, durable oracle |
| `sever-p2`, `sever-py-p2` / `sever_db_p2` | | composition root, CLI, SDK |
| Part 2 `spec_trace` | | the frozen tool knows only Part 1's sections; Part 2 needs a new module that reuses it |

## Part 1 gates (Build §4.8) — status from the ledger

| Target | Status | Evidence |
|---|---|---|
| P1-T1 exactness (survivors check) | PASS | nq-100k 5 seeds: 427,455 checks; nq-10k: 43,562; L4 synthetic: 275,114; 0 failures |
| P1-T2 engine = model | PASS | nq-10k 10.6 M values, nq-100k 12.4 M values (5 seeds each), 0 mismatches |
| P1-T3 order independence | PASS (tests) | proptest, ≥ 256 orders per set |
| P1-T4 kernels bit-identical | PASS | 10^7 pairs (ignored test); nq-10k 508 M and nq-100k 2.25 B pairs, 0 mismatches |
| P1-T5 no deleted record returned | PASS | 0 on nq-10k and nq-100k, five seeds each |
| P1-T6 builder oracle | PASS | 5 seeds; slow test in `scripts/ci.sh full-checks` |
| P1-T7 quantisation recall (measure) | **1.000** at nq-100k (target ≥ 0.999) | ledger 5 Oct |
| P1-T8 sabotage SB-1 … SB-10 | PASS | `gates p1-checks` (all 17 steps); a first run failed only because `run.sh` was not executable |
| P1-T9 traceability | 70/70 | `docs/TRACE_PART_1.md` |
| P1-T10 coverage | PASS | Rust 95.9 % lines, 87.0 % branches; Python 98.8 % |
| P1-T11 mutation | PASS | 325 / 347 = 93.7 %; 22 survivors, all triaged in `docs/MUTANTS_P1.md` |
| P1-T12 fuzzing 10^8 per parser | PASS | ledger 6 Oct: 10^8 runs each, `artefact_parse` 1,777 s, `blob_parse` 619 s; the first run found a real bug (fixed) |
| P1-T13 contracts + proof spikes | PASS | spikes recorded 5 Oct, then deleted |
| P1-T14 ghost (measure) | recorded by the demo | nq-10k seed 42: IVF 5.0e-3, float mean 1.9e-8, SEVER 0 |

Definition of done (Build §2.9): all gates above; the clean-clone demo check passed (6 Oct: the
report and the rebuilt artefact identical apart from timing); the freeze manifest and tag.

## Parts

| Part | Status | Tag | Notes |
|---|---|---|---|
| 1 The Idea | **frozen** 6 Oct 2026 | `part-1-frozen` | All Part 1 gaps closed (G-1, G-5 … G-12) |
| 2 The Database | next | | Build §5; follow-up from P1-T11: a test with two inserts into one group in one change set |
| 3 The Receipt | **preview** built in the demo | | Resolve G-3 (DB-51) and G-4 |
| 4 The Erasure | not started | | Apply G-2 |

## Part 1 modules (Build §4.4)

| Module | Status | Notes |
|---|---|---|
| `sever-types` | built | IDs, constants, every §17 error, `SecretBuf` + EP-4 |
| `sever-quant` | built | §4.1 steps 0–3 (DB-60), Q24 ties to even, dequantise; golden vector 5 |
| `sever-partition` (Rust) | built | §6.3 parser; length checked before any allocation (fuzz finding) |
| `sever_partition` (Python) | built | §6.2 builder, independent Ledoit–Wolf oracle; 5 artefacts in `artefacts/` |
| `sever_refmodel_core` (Python) | built | §3–§8 oracle; search made 4× faster on 5 Oct (same values, checked against the engine) |
| `sever-index` | built | §5, §7, §9.7; EP-1, EP-2, EP-3 with contract suites; `apply` fix (forged-change-set test) |
| `sever-search` | built | §8; scalar and AVX2 kernels bit-identical; MSRV-clean |
| `sever-tracekit`, `sever_testkit` | built | traces, replay with survivors and kernel checks, streams, ledger, gate runners, `spec_trace`, slices |
| `sever-spec` | built | `#[spec("SR-…")]` attribute (Build §2.2) |
| `sever-p1`, `sever-demo`, `sever_demo` | built | composition root (OS entropy), ghost baselines, CLI, HTML report; `scripts/p1-demo.sh` |
| Tests L1–L14 | built | L4 synthetic streams, L5 Hypothesis stateful, L9 E2E-1.1 … 1.7, L11 fuzz, L12 mutants + sabotage, L13 architecture |
| Proof spikes | passed, deleted | CommitmentExtension on ristretto255 (EP-1), rotation reader (EP-3) |
| CI | built | `scripts/ci.sh fast|full-checks`; `.github/workflows/ci.yml` (fast tier) |
| P0 pre-registration | written | `configs/experiments.yaml` (Overview §12 verbatim, pins filled from `PINS.json`) — yours to commit |

## Things to explain later (learning pass)

- Why a failed `fsync` is never retried: `SimVfs` models Linux's behaviour (pages marked clean,
  data silently gone, the retry "succeeds"), which is what SB-14 will exploit.
- The current/durable views of `SimVfs`, and why a new file needs `fsync_dir` of its parent.
- Why the EP-5 crash contract must fail a backend that loses nothing.

## Open questions

- What overwrote `sciq_reference/passages.parquet` at 19:35 UTC on 27 Sep? Not `build`; the
  writer was pyarrow 25.0.1.
- The build plan's Part 2–4 proposals (DB-46, DB-48, DB-51 … DB-54) are not yet in the decision
  register; decide them at the start of each part.
- 88 % of nq passages are out of distribution for the SciQ partition (by design: the drift case), so
  most of them live in spawned groups.
- Two files in `demo/` were renamed outside these sessions (`1 data.py`, `2 quant.py`); left as is.
- Long runs need the laptop awake: three runs were lost on 5 Oct to a WSL restart and once to the
  out-of-memory killer (all recorded in the ledger as aborted).

## Session log

- **7 Oct 2026**: Part 2 started. Design review: DB-46, DB-48 accepted; G-13 found and closed by
  DB-65. `sever-vfs` built (30 tests, contract suite, posix on ext4 and tmpfs); a hand mutation
  pass found a weak reorder check in the contract, fixed.

- **6 Oct 2026 (afternoon)**: every Part 1 gate recorded on clean commits: P1-T11 mutants 93.7 %
  (tests added for the survivors that were real gaps: the change set's `k` after a flush,
  `QVec::dim`, INV-5 on a larger index), P1-T10 coverage, full checks (sabotage runner made
  executable; it now restores proptest files a sabotage build writes), P1-T12 fuzz, P1-T2/T5 on
  nq-100k (five seeds, 12.4 M values, 0 mismatches). Clean-clone demo check passed. Git history
  rewritten by you to drop co-author trailers (`docs/COMMIT_MAP.txt` maps the old hashes in the
  ledger). WSL given 10 GB. Part 1 frozen.
- **5–6 Oct 2026**: moved to `~/sever-db`. Built `sever-p1` (composition root, ghost baselines,
  `sever-demo idea`), `sever_demo` report, `spec_trace` and `#[spec]`, L4/L5/L13 suites, fuzz targets,
  proof spikes (passed, deleted), coverage tests, CI script, one-command demo, `experiments.yaml`.
  Ledger: P1-T7 = 1.000; nq-10k differential PASS (five seeds, with survivors and kernel checks); L4
  synthetic PASS. Bugs found by tests: artefact parser allocation (fuzz), `apply` on a malformed
  flush. Dependency pins for §20.3 (proptest 1.6 without fork; no Rust Parquet reader). Closed
  G-9 … G-12 (DB-61 … DB-64).
- **4 Oct 2026**: `sever-types`, `sever-quant`, partition builder and importer, reference model,
  `sever-index`, `sever-search`, tracekit and test kit built in write mode; G-8 closed (DB-60);
  P1-T6 and P1-T8 pass; demo moved to `demo/` and made self-contained (DB-56).
- **3 Oct 2026**: demo shell made guided; Part 3 preview (commitments, proofs, certificates, offline
  verifier).
- **1–2 Oct 2026**: the review demo (data checks, quantiser, index, baselines, full run on 1M).
- **27 Sep 2026**: specification, overview, build plan and CLAUDE.md written; P0 data encoded and
  verified.
