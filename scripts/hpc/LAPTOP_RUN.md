# The v1.0 run on the laptop (DB-113)

Every pre-registered gate and measure of Parts 3 and 4, once, on this laptop, at the sizes of
[`steps.sh`](steps.sh) (about 33 hours). It replaces the college-HPC run of DB-111;
[`HPC_GUIDE.md`](HPC_GUIDE.md) is kept for the machinery it describes.

## What runs

`run-all.sh` runs the 23 entries of `steps.sh` (DB-111's 22 steps; `p4-crash` is two windows) in 13
phases. Steps in one phase run at the same time. It runs as the systemd user unit `sever-hpc@real`,
with these safeguards:

- **Restarts:** after any kill (out of memory, a WSL restart), with a growing delay; finished steps
  are kept and an interrupted step continues.
- **A failed gate is never rerun** (Build §2.5). A failure caused by an out-of-memory kill is not a
  result: it is marked `rc=137` and reruns.
- **A verified backup after every step**, plus hourly, in `C:\Users\saiki\sever-backup\real`.
- **Watchdog** every 5 minutes: hang, disk, memory, late phase, and a heartbeat every 3 hours.
- **Waits, never fails:** on battery, and for the memory lock (below).
- **On Windows:**
  - a supervisor (`C:\Users\saiki\sever-run\supervisor.ps1`) keeps the PC awake and restarts WSL
    within 30 s if it stops;
  - no sleep on mains, and max CPU 99 % (turbo off, so it doesn't overheat).

## Your part

1. **Phone:** the ntfy app, subscribed to the topic in `~/longrun/ntfy-topic`. You get a heartbeat
   every 3 hours, and an alert for each wait, crash, hang or finish.
2. **Once, any time before the last phase** (about 28 hours in), in an Ubuntu terminal:
   ```bash
   sudo bash ~/sever-db/scripts/hpc/owner-sudo.sh
   ```
   It restarts nothing. If the run reaches `p4-forensics` and `p4-ex6` first, they wait and you
   get an alert.
3. **Keep it plugged in, keep the lid open, close VS Code** (it uses about 2.5 GB that the run
   needs). Watch from an Ubuntu window:
   `bash ~/sever-db/scripts/hpc/status.sh real`.

## Don't

- Sign out, shut down or restart Windows, or run `wsl --shutdown`. The run survives all of these,
  but loses the step in progress.
- Open heavy programs (browsers with many tabs, games, VS Code).
- Edit anything in `~/sever-db`: preflight refuses a changed tree.

## Stop, resume, results

| Want | Do |
|---|---|
| Pause the run on purpose | `bash scripts/hpc/launch.sh stop real` (resumable) |
| Resume | `bash scripts/hpc/launch.sh start real` |
| Stop WSL on purpose | create `C:\Users\saiki\sever-run\STOP`, then `wsl --shutdown` |
| See progress | `status.sh real`, `traces/hpc-summary.log` |
| Results | `docs/RUN_LEDGER.jsonl`, `results/`, `traces/hpc-*.log`; backups as above |
| Undo the laptop settings afterwards | `bash scripts/hpc/laptop-env.sh --undo` |

## If something goes wrong

| Alert or sign | Meaning | Do |
|---|---|---|
| `waiting` … battery | on battery: nothing runs | plug in |
| `waiting` … memory lock | the last phase is waiting for you | run `owner-sudo.sh` (above) |
| `crash` / `restart` | killed (memory, WSL); it continues by itself | nothing, unless it repeats |
| `stale` | no CPU progress for 30 min (fuzzing can be quiet) | `status.sh real`; if stuck: `launch.sh stop real`, then `start` |
| `late` | a phase is taking more than 1.2× its estimate | nothing; tell Claude |
| no `alive` for over 3 h | the laptop or WSL is down | sign in to Windows; the supervisor starts WSL and the run continues |
| `failed` | the unit gave up (8 starts) | `status.sh real`, then ask Claude |
| `done` | finished: every step passed, or a list of failed gates | tell Claude: a failed gate is fixed red-test-first, then rerun with `ONLY=… FORCE=1` |
