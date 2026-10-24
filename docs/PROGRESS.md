# Progress

The current state only, updated at the end of every session (CLAUDE.md §3.3). The history up to
24 Oct 2026 is in [`archive/PROGRESS_HISTORY.md`](archive/PROGRESS_HISTORY.md). The one plan is
[`plans/2026-10-23-v1-then-demo.md`](plans/2026-10-23-v1-then-demo.md); nothing is planned after it
(DB-112).

## Now (24 Oct 2026)

| Part | Status | Tag |
|---|---|---|
| 1 The Idea | **frozen** 6 Oct 2026 | `part-1-frozen` |
| 2 The Database | **frozen** 8 Oct 2026; errata E-1, E-2; three known defects kept as limit L-28 | `part-2-frozen-e2` |
| 3 The Receipt | **built**; every interim laptop check passes; waits for the HPC run, a fair-testing PASS (FT-10), `scripts/freeze.sh 3` | |
| 4 The Erasure | **built**; interim checks pass, no gate in the ledger yet; waits for the same | |

- **Branch:** `studio-raw` (pushed), not yet merged into `main` (`f6be0d2`). It holds the Part 4
  `inspect` additions (DB-107, DB-108, DB-110), Studio's audit-1 fixes, and the HPC decision.
- **Plan stage:** Stage 1, the engine additions. Done: G-46, DB-110, `Db::passage` with 3 tests
  (`5a655fc`).

## Next

1. **Stage 1 (Claude):**
   - red proofs PRI-5 … 7 in `tests/proofs/inspect/`;
   - the SDK: `Engine.passage`, `Database.passage`, `Explainer` re-exported from `sever_db`, the
     `.pyi` stub;
   - the checks: with and without `--features inspect`, `cargo tree` unchanged, clippy, fmt,
     `tests/proofs/inspect/run.sh`, `scripts/ci.sh fast`, `studio/studio.sh test --full`.
2. **Stage 2 (Claude):** merge `studio-raw` into `main` once GitHub's fast tier and the laptop's
   `scripts/ci.sh full-checks` are green; tell the owner the commit.
3. **Stage 3 (the owner):** the one full run of every gate and measure, at full size, in WSL2 Ubuntu
   on the college HPC (DB-111): [`scripts/hpc/HPC_GUIDE.md`](../scripts/hpc/HPC_GUIDE.md). A failed
   gate is a bug: red test first, the smallest fix, then that gate and every later one rerun.
4. **Stage 4:** fair testing for Parts 3 and 4 until PASS, each run on the owner's go after its cost
   estimate.
5. **Stage 5:** `scripts/freeze.sh 3` and `4`; the tags `part-3-frozen`, `part-4-frozen`, `v1.0.0`,
   on the owner's word.
6. **Stage 6:** Studio's company demo on the frozen engine; its to-do list is
   `studio/audit/AUDIT2.md`.

## Evidence so far (interim, laptop; never reported as the gates, DB-94)

- **Part 3:** the crash campaign's insert phase (351,866 points, 0 failures) and crash points from
  operation 17,000 on every seed; the `nq-100k` replay of seed 42; attacks on five seeds; checks,
  coverage, measures, spikes; fuzzing at 10^7. Traceability 102/102.
- **Part 4:** the crash check in three windows of 80 operations per seed (16/16 runs, 0 refusals,
  0 stale key slots); P4-T3's reopen check sees BH-5 (`reopen_mismatches` 0 on the fixed build, 137
  with the fix switched off); SB-24 … SB-30 each red; traceability 68/68 with 84 proofs.
- **Whole tree:** `scripts/ci.sh full-checks` 42/42 on `c092727`; every demo exits 0; a fuzz smoke
  of all 17 targets (about 5·10^8 runs, 0 crashes).
- **Fair-testing bug hunts** (DB-98, DB-102): Part 3 170/172 and Part 4 146/149 on the second hunt;
  every finding fixed (G-37 … G-42, DB-99 … DB-104).

## Studio

`studio/` (DB-106 … DB-109) is the desktop demo of every feature: `studio/studio.sh setup |
prepare | run | test`. Audit 1 (`studio/audit/REPORT.md`) is fixed, each finding with a test that
fails without its fix; verified on `d3cdbc4` (`studio.sh test --full` 131 passed, NQ smoke PASS).
Audit 2 (`studio/audit/AUDIT2.md`) lists what is still overstated; it is fixed in Stage 6.

## Working setup

- **Working copy:** `~/sever-db` on the laptop's WSL ext4 disk (the `C:` copy is a backup). Claude
  works here; the HPC only runs the gates.
- **Git:** Claude commits (conventional messages, no AI attribution) and pushes to `origin`. `main`
  is fast-forwarded only when GitHub's fast tier and `scripts/ci.sh full-checks` pass on the commit.
  No freeze tag without the owner's word.
- **Unattended laptop runs:** `scripts/jobq.sh` (service `sever-jobq`), side jobs
  `scripts/ops/sidejobs.sh`, memory guard `scripts/oomguard.sh`. The laptop has 16 GB (WSL 11 GB),
  8 cores, and overheats on long runs.

## Open questions (decide before Stage 3: the HPC run tests the build as it then is)

- **Part 4's erase program** (`sever-demo-p4`, SB-24 build) counts what the scan decrypts but does
  not print the reconstructed vector beside the original, as Build 3-4 §2.11 step 4 says. A Part 4
  change; Part 4 is not frozen yet.
- **The frozen partition** is fitted on SciQ, so 88 % of NQ passages are out of distribution and
  live in spawned groups (by design: the drift case). Refitting on NQ would change the artefacts
  every gate uses.

## To explain later (learning pass)

- Why a failed `fsync` is never retried (`SimVfs` models Linux: pages marked clean, data gone).
- The current and durable views of `SimVfs`, and why a new file needs `fsync_dir` of its parent.
- Why the EP-5 crash contract must fail a backend that loses nothing.
- How `sever-engine` rebuilds the frozen index after a crash with one synthetic `ChangeSet`.
- Why a valid WAL record after a bad one means corruption, not a torn tail.

## Session log

- **24 Oct 2026:** the gate-run machine settled: the college HPC in WSL2 Ubuntu, full sizes (G-47,
  DB-111; `scripts/vm/` became `scripts/hpc/` with one guide). Cleanup (DB-112): the post-v1.0
  plans dropped (E-3 … E-6, the release passage API); this file cut to the current state, history
  archived; `docs/HANDOFF.md` and Studio's finished `PLAN.md` and `PROMPT.md` removed; merged
  branches `demo-studio` and `p3-gates` deleted (`origin/p3-gates` too); about 47 GB of build
  output and stale traces removed from the laptop.
