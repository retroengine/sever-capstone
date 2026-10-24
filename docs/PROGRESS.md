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

- **Branch:** `main` = `3417b7f` (fast-forwarded from `studio-raw` on 24 Oct; GitHub's fast tier
  and `scripts/ci.sh full-checks` 42/42 green on it). **The HPC run tests `3417b7f`.**
- **Plan stage:** Stages 1 and 2 are done; next is Stage 3, the HPC run.
  - `Db::passage` with 3 tests (`5a655fc`); red proofs PRI-5 … 7 (`37bf88f`; PRI-1 … 7 all red).
  - The SDK's `Database.passage` and `sever_db.Explainer` (`2acd91d`).
  - The erase demo's step 4 (`dc29088`): on SB-24, `S_pre − S_post` is printed next to the
    original, identical for both deleted notes; the real build rebuilds 0. Red proofs PRS-1 … 4
    in `tests/proofs/scan/`, all red.

## Next

1. **Stage 1 (Claude): done** (above).
2. **Stage 2 (Claude): done**: `main` = `3417b7f`.
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
On `3417b7f`, `studio.sh test --full` gave 129 passed, 2 failed: the no-freeze test (677 ms
against 250 ms on a busy laptop; it passed on rerun) and the UI smoke, which timed out after
900 s, probably because the part demos' `cargo run --release` builds were cold after
`cargo clean`. The owner deferred this to Stage 6 (24 Oct); it does not affect the engine or
the HPC run.

## Working setup

- **Working copy:** `~/sever-db` on the laptop's WSL ext4 disk (the `C:` copy is a backup). Claude
  works here; the HPC only runs the gates.
- **Git:** Claude commits (conventional messages, no AI attribution) and pushes to `origin`. `main`
  is fast-forwarded only when GitHub's fast tier and `scripts/ci.sh full-checks` pass on the commit.
  No freeze tag without the owner's word.
- **Unattended laptop runs:** `scripts/jobq.sh` (service `sever-jobq`), side jobs
  `scripts/ops/sidejobs.sh`, memory guard `scripts/oomguard.sh`. The laptop has 16 GB (WSL 11 GB),
  8 cores, and overheats on long runs.

## Decided (24 Oct 2026)

- **Part 4's erase demo will show the leak** as Build 3-4 §2.11 step 4 says. On the SB-24 build,
  `sever-scan` decrypts the deleted record's group at both versions and `sever-demo-p4` prints
  `S_pre − S_post` beside the original `x̃`. Added to Stage 1, so the HPC run tests it. The spec
  (§16.3) says nothing about the scanner's report, so no gap is needed.
- **The frozen partition stays fitted on SciQ.** This is the design (DB-41): the groups must be
  fixed on data that holds no user data, and the drift test is meant to send most live data (about
  90 % expected; 88 % of NQ) to spawned groups. Refitting on NQ would break that thesis and Part 1's
  frozen artefacts and evidence.

## To explain later (learning pass)

- Why a failed `fsync` is never retried (`SimVfs` models Linux: pages marked clean, data gone).
- The current and durable views of `SimVfs`, and why a new file needs `fsync_dir` of its parent.
- Why the EP-5 crash contract must fail a backend that loses nothing.
- How `sever-engine` rebuilds the frozen index after a crash with one synthetic `ChangeSet`.
- Why a valid WAL record after a bad one means corruption, not a torn tail.

## Session log

- **24 Oct 2026 (end):** Stage 1 done (above); Stage 2: `main` fast-forwarded to `3417b7f`.
  Studio's full tier is deferred to Stage 6 (two failures noted under Studio).
- **24 Oct 2026 (later):** the HPC run rebuilt around the owner's long-run checklist
  (`scripts/hpc/HPC_GUIDE.md`, rewritten). The owner pastes one prompt (Part C), and Claude follows
  Part D:
  - discover;
  - Windows settings (`windows.sh`);
  - the owner's one sudo step (`root-setup.sh`);
  - data (`fetch-data.sh`, tested on the OneDrive zip: DATA OK) and `setup.sh`;
  - safeguards (`install.sh`: systemd user units with restarts after a kill but never after a
    failed gate, a memory cap, `nice 10`, a watchdog, hourly verified backups, ntfy alerts);
  - failure drills on a mock run (`drills.sh`);
  - a real reboot drill with the owner;
  - the real start only on the owner's word (`launch.sh`).

  The drills caught three bugs, all fixed:
  - `SuccessExitStatus=1` also accepted a refused preflight;
  - the DONE marker came before its alert;
  - `run-all.sh` would have rerun failed gates after a restart, and restarted `p3-crash` without
    `--resume`.

  Not possible under WSL without Windows admin: temperature alerts, and resuming before someone
  signs in after a reboot.
- **24 Oct 2026:** the gate-run machine settled: the college HPC in WSL2 Ubuntu, full sizes (G-47,
  DB-111; `scripts/vm/` became `scripts/hpc/` with one guide). Cleanup (DB-112): the post-v1.0
  plans dropped (E-3 … E-6, the release passage API); this file cut to the current state, history
  archived; `docs/HANDOFF.md` and Studio's finished `PLAN.md` and `PROMPT.md` removed; merged
  branches `demo-studio` and `p3-gates` deleted (`origin/p3-gates` too); about 47 GB of build
  output and stale traces removed from the laptop.
