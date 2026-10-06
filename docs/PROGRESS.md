# Progress

Updated at the end of every session (CLAUDE.md §3.3). Newest session first in the log.

> **Draft written by Claude on 6 Oct 2026, for you to confirm** (CLAUDE.md §3.3). Part 1 was built in
> write mode (your temporary rule: build everything first, study the code after). Read it before
> committing and change anything that is not how you see it.

## Now

- **Phase:** Part 1, The Idea: **every module built**; the gates are being recorded in the run ledger
  (`docs/RUN_LEDGER.jsonl`). Freeze (`part-1-frozen`) after the last gates pass and you commit.
- **Working copy:** `~/sever-db` on the WSL ext4 disk since 4 Oct (the `C:` copy is a backup).
- **Git:** you commit from now on; Claude only leaves changes in the working tree and hands you the
  commands. The work is on branch `p1-sever-quant` (32 commits ahead of `master`); `master` is the
  trunk (CLAUDE.md says `main`; the repo uses `master`).
- **Decisions (6 Oct):** DB-61 … DB-64 close the last Part 1 gaps G-9 … G-12 (the ULP sentence, spawn
  size as a runtime value, at most 10,000 frozen groups, `IntegrityViolation` for a bad artefact).
- **Next:** finish the Part 1 gates still open (below), then the freeze manifest and tag, then Part 2.

## Part 1 gates (Build §4.8) — status from the ledger

| Target | Status | Evidence |
|---|---|---|
| P1-T1 exactness (survivors check) | PASS | nq-10k 5 seeds: 43,562 checks; L4 synthetic: 275,114 checks; 0 failures |
| P1-T2 engine = model | nq-10k **PASS**; nq-100k **to run** | nq-10k: 10.6 M values, 0 mismatches |
| P1-T3 order independence | PASS (tests) | proptest, ≥ 256 orders per set |
| P1-T4 kernels bit-identical | PASS | 10^7 pairs (ignored test); nq-10k: 508 M pairs, 0 mismatches |
| P1-T5 no deleted record returned | nq-10k PASS; nq-100k with P1-T2 | |
| P1-T6 builder oracle | PASS | 5 seeds; slow test in `scripts/ci.sh full-checks` |
| P1-T7 quantisation recall (measure) | **1.000** at nq-100k (target ≥ 0.999) | ledger 5 Oct |
| P1-T8 sabotage SB-1 … SB-10 | PASS (run.sh); recorded with `full-checks` | |
| P1-T9 traceability | 70/70 | `docs/TRACE_PART_1.md` |
| P1-T10 coverage | measured 94.6 % lines / 85.1 % branches (Rust), 98 % (Python); **gate run to record** | `gates p1-coverage` |
| P1-T11 mutation | survivors triaged; **gate run to record** | exploratory 6 Oct: 22 survivors expected, ≈ 93.7 %; `docs/MUTANTS_P1.md` |
| P1-T12 fuzzing 10^8 per parser | PASS | ledger 6 Oct: 10^8 runs each, `artefact_parse` 1,777 s, `blob_parse` 619 s; the first run found a real bug (fixed) |
| P1-T13 contracts + proof spikes | PASS | spikes recorded 5 Oct, then deleted |
| P1-T14 ghost (measure) | recorded by the demo | nq-10k seed 42: IVF 5.0e-3, float mean 1.9e-8, SEVER 0 |

Definition of done (Build §2.9) still to tick: the gates above, the clean-clone demo check (after your
commit), the freeze manifest `freeze/PART-1.sha256` and the tag.

## Parts

| Part | Status | Tag | Notes |
|---|---|---|---|
| 1 The Idea | built; gates being recorded | | All Part 1 gaps closed (G-1, G-5 … G-12) |
| 2 The Database | not started | | Starts when Part 1 is frozen |
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
