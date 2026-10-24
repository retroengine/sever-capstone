# SEVER-DB on the college HPC: the one guide

The v1.0 gate run (DB-111): every pre-registered gate and measure of Parts 3 and 4, once, at full
size, in WSL2 Ubuntu on the college HPC (Windows). This file is the only document for it.

- **Parts A–B** are for the owner: what to prepare, and the few things only a person can do.
- **Part C** is the one prompt to paste into Claude Code on the HPC.
- **Part D** is Claude's instructions there, phase by phase, with the points where it stops for the
  owner.
- **Parts E–F** are the runbook (monitor, stop, resume, restore, alerts) and troubleshooting.

**What runs.** `scripts/hpc/run-all.sh` runs 22 steps one after another (`p3-crash` … `p4-ex8`),
about 1.5–3 days on 22 cores. It runs as a systemd user unit, `sever-hpc@real`, with these
safeguards:
- **Restarts:** after a kill or an out-of-memory kill, with a growing delay (60 s up to 15 min),
  at most 8 times.
- **Never reruns a failed gate** (Build §2.5).
- **Memory cap**, and `nice 10`.
- **Watchdog:** every 5 minutes, it alerts on a hang, low disk or low memory, or a late backup.
- **Hourly backup** of the logs, the ledger and the results.
- **Alerts on your phone** through ntfy.
- **Resumes after a Windows restart** once you sign in.

All of it is in `scripts/hpc/`; its state lives in `~/longrun/`.

---

## Part A — Before you go (at home)

1. **The commit.** Claude on the laptop finishes the engine work and merges it into `main`, then
   tells you the commit to test. Don't go before that.
2. **The data** is `sever-hpc.zip` (3.4 GB) in your **OneDrive Desktop**: it is already online. On
   the laptop, check that OneDrive shows it as synced (a green tick). A USB stick (exFAT, 8 GB or
   more) with the same zip is a good spare.
3. **Alerts:** install the **ntfy** app on your phone and subscribe to a topic with a long, unguessable
   name (for example `sever-` and 12 random letters). Anyone who knows the name can read the alerts.
   The alerts never contain data: only step names, counts and exit codes.
4. **Your phone**, for GitHub's and Microsoft's 2-factor codes.

## Part B — On the HPC, by hand (about 30 minutes)

Windows PowerShell: press the Windows key, type `PowerShell`, Enter. Ubuntu: Start menu, Ubuntu.

1. **WSL and Ubuntu.** In PowerShell:
   ```powershell
   wsl --status
   wsl --install -d Ubuntu-24.04
   ```
   - If `wsl --status` fails, WSL is not enabled. Enabling it needs a Windows administrator once:
     ask IT to run `wsl --install --no-distribution`.
   - Installing Ubuntu needs no admin. It asks for a **new Ubuntu user name and password**: write
     the password down, because `sudo` will ask for it.
2. **The code and Claude Code.** In the Ubuntu window:
   ```bash
   ssh-keygen -t ed25519 -C "college-hpc" -f ~/.ssh/id_ed25519 -N "" && cat ~/.ssh/id_ed25519.pub
   ```
   1. Add the printed line on github.com: **Settings → SSH and GPG keys → New SSH key**.
   2. Then run:
      ```bash
      git clone git@github.com:retroengine/sever-capstone.git ~/sever-db
      cd ~/sever-db && git checkout <the commit Claude gave you>
      curl -fsSL https://claude.ai/install.sh | bash
      ```
   3. Close the Ubuntu window and open a new one.
3. **The data.** In the browser, open **onedrive.live.com** and go to **Desktop**. Download
   `sever-hpc.zip` into **Downloads**. Don't unzip it; Claude finds it there.
4. **Start Claude.** In Ubuntu:
   ```bash
   cd ~/sever-db && claude
   ```
   Log in, then paste Part C.

## Part C — The prompt (paste this into Claude Code on the HPC)

```text
I am on the college HPC, in WSL2 Ubuntu, in ~/sever-db. We are doing SEVER-DB's v1.0 gate run.
Read CLAUDE.md, then scripts/hpc/HPC_GUIDE.md (Part D is your instructions), then the "Now"
section of docs/PROGRESS.md. Then carry out Part D phase by phase. Report after each phase in a
few lines. Stop and wait for me at every STOP. Do not start the real run until I say exactly
"start the real run".
```

---

## Part D — Claude's instructions on the HPC

### Rules (binding; they come from CLAUDE.md)

- **Change no code, test, config or spec.** The run tests the commit exactly as checked out
  (`preflight.sh` refuses otherwise). If something needs a code change, stop and tell the owner;
  the fix happens on the laptop.
- **A failed gate is a result.** Never rerun it, never loosen it, never touch its log. A measure is
  recorded as found (Build §2.5). Never run the strict steps with `allow_unsafe_memory`, and never
  shrink a step.
- **Never edit by hand** `docs/RUN_LEDGER.jsonl`, `results/`, `docs/audit/`, `tests/cleanroom/`.
- **Never print, copy or commit** database folders, key files, certificates, `r_t` or passage text
  written by the run.
- **Root and Windows are the owner's.** Claude cannot type a sudo password and must not try. The
  only Windows-side change is `windows.sh` (the owner's own files, no admin). Respect the college's
  policy; if something would break it, say so.
- **Keep 2 cores and 8 GB for other users** (`windows.sh` does this); the run uses `nice 10`.
- **If a script fails,** report its output and the likely cause. Fix only the environment (packages,
  settings, data). Never fix the repository's code.

### Phase 1 — Discover (read-only)

```bash
bash scripts/hpc/discover.sh
```
Show the table. Summarise what blocks the run and which later phase fixes each item:
- swap, `.wslconfig` and sleep → phase 2;
- packages, memory lock and linger → phase 3;
- tools → phase 5.

Real blockers mean stop and tell the owner:
- not WSL2;
- not x86-64;
- the repository not on ext4;
- C: with under 150 GB free;
- no internet.

### Phase 2 — Windows-side settings (no admin)

```bash
bash scripts/hpc/windows.sh --dry-run
bash scripts/hpc/windows.sh
```
It does three things:
- writes `.wslconfig`: all cores but 2, all memory but 8 GB, `swap=0`;
- puts the keep-alive in the Startup folder;
- turns sleep off on mains power. If `powercfg` was refused, tell the owner to set
  **Settings → System → Power → Sleep: Never** (or ask IT).

Also tell the owner: **Settings → Windows Update → Pause updates** for 1 week.

### Phase 3 — The root step. **STOP** for the owner

Tell the owner, word for word:
> In a **new Ubuntu window**, run: `sudo bash ~/sever-db/scripts/hpc/root-setup.sh` (it asks for
> your Ubuntu password). When it says done, run `wsl --shutdown` in **PowerShell**. This closes
> Claude too. Then open Ubuntu, run `cd ~/sever-db && claude --continue`, and say "root-setup done".

`root-setup.sh` does five things:
- installs the system packages;
- makes the memory lock unlimited for the user's services;
- enables linger;
- checks systemd;
- turns swap off.

`wsl --shutdown` applies `.wslconfig`.

### Phase 4 — Verify the configuration

```bash
bash scripts/hpc/discover.sh
```
Expect:
- **cores and memory:** the Windows totals minus 2 cores and 8 GB;
- **swap:** off;
- **linger:** yes;
- **memory lock:** services `unlimited`;
- **sleep (mains):** never;
- **keep-alive:** installed;
- **tools missing:** only `cargo`, `uv` (phase 5 installs them).

Anything else: fix it through the scripts (rerun `windows.sh`, or ask the owner to rerun
`root-setup.sh`), or stop and ask.

### Phase 5 — Data and environment (about 30–60 min)

```bash
bash scripts/hpc/fetch-data.sh                    # finds sever-hpc.zip in Downloads; must end DATA OK
bash scripts/hpc/setup.sh 2>&1 | tee ~/longrun-setup.log
bash scripts/hpc/check.sh                         # must end: All 22 run-all.sh steps can run here.
```
- **If `fetch-data.sh` finds no bundle,** ask the owner where it is and pass the path.
- **`setup.sh` installs** Rust (pinned 1.98.1, nightly, 1.85), the cargo tools, `uv`, Python and the
  packages, and builds the SDK modules. It checks the data and writes any missing artefacts and
  traces.
- **If `check.sh` lists a `[FAIL]`,** fix it before going on.

### Phase 6 — Safeguards

```bash
bash scripts/hpc/install.sh                       # must end: install: OK
```
It installs the units and writes `~/longrun/real.env`, `~/longrun/drill.env` and `~/longrun/env.txt`
(versions, commit, machine). Then:
1. Ask the owner for their **ntfy topic**. Set `NTFY_TOPIC=` in `~/longrun/real.env` (and in
   `drill.env` if they want the drills' alerts too).
2. Ask about an optional off-machine backup target: `BACKUP_REMOTE=`, an rclone remote or
   `user@host:path`.
3. Send a test alert, and have the owner confirm it reached the phone:
   ```bash
   bash -c '. scripts/hpc/lib.sh; load_instance real; notify test "SEVER-DB alerts work"'
   ```

### Phase 7 — Mock run and failure drills (about 15 min)

```bash
bash scripts/hpc/drills.sh
```
This runs the real unit, scripts and restart rules on three fake steps. Every drill must PASS:

| Drill | What it proves |
|---|---|
| session | the run doesn't belong to a terminal, so closing windows can't stop it |
| kill9 | `kill -9`: systemd restarts it; passed steps are kept; the killed step reruns |
| torn | a log cut mid-write: that step reruns, the others are kept |
| reboot | every process killed at once, then the boot path continues the run |
| disk | low disk: the start is refused, alerted, and capped; after the fix it runs |
| hang | a hung step: an alert after the stale time, no kill; when it resumes, the run finishes |
| loop | a job that always crashes: it stops at the start limit, with an alert |
| failed | a failed step: the run finishes, is marked DONE, and that step is never rerun |
| backup | a backup is written and verified; restore checks it; a damaged copy is refused |

Show the table. Any FAIL: stop and report. Then do the **real reboot drill** with the owner
(**STOP**):
```bash
sed -i 's/^MOCK_SECONDS=.*/MOCK_SECONDS=90/' ~/longrun/drill.env
systemctl --user enable sever-hpc@drill.service && systemctl --user start --no-block sever-hpc@drill.service
```
Tell the owner:
> In PowerShell run `wsl --shutdown`, then **sign out of Windows and sign back in**. Don't open
> Ubuntu. Wait 2 minutes, then open Ubuntu, run `cd ~/sever-db && claude --continue`, and say
> "back".

Then check that the run continued after the reboot with no help:
```bash
bash scripts/hpc/status.sh drill
```
It should be active or finished, with the steps finished before the reboot kept. Afterwards:
```bash
systemctl --user disable --now sever-hpc@drill.service
sed -i 's/^MOCK_SECONDS=.*/MOCK_SECONDS=10/' ~/longrun/drill.env
```

### Phase 8 — Report and approval. **STOP**

Give the owner, in a few lines:
- the commit;
- cores, memory cap, `nice`;
- the alert topic and backup folder;
- the phase 4 table's key rows;
- the drills table and the reboot drill's result;
- the expected duration (1.5–3 days);
- what they must not do: sign out, shut down, or run `wsl --shutdown`. Locking the screen with
  Windows+L is fine.

Then ask: **"Start the real run?"** Start only on "start the real run".

### Phase 9 — Launch

```bash
bash scripts/hpc/launch.sh start real
sleep 120 && bash scripts/hpc/status.sh real
```
`launch.sh` does four things:
- refuses unless the drills passed on this commit;
- pins the commit (`EXPECTED_COMMIT`);
- runs the unit's own preflight;
- enables autostart and the hourly backup, then starts the run.

Confirm `p3-crash` started, the owner got the "run started" alert, and the backup timer is listed:
```bash
systemctl --user list-timers 'sever-hpc*'
```
Tell the owner to lock the screen (Windows+L) and leave. Claude can be closed: the run doesn't need
it.

### Phase 10 — When the owner asks how it is going

```bash
bash scripts/hpc/status.sh real
```
Explain any alert with Part E's table. Never rerun or change anything because of a result.

### Phase 11 — Finish (after the "finished" alert)

```bash
bash scripts/hpc/status.sh real
bash scripts/hpc/backup.sh real                   # the final backup
git status --short
```
1. Only files under `docs/` and `results/` may have changed: the run ledger and the generated
   reports. If **anything else** shows up (above all a name with `key`, `cert`, `db`, `secrets` or
   `wal`), stop and show the owner. Otherwise:
   ```bash
   git switch -c hpc-run-$(date +%Y%m%d)
   git add docs/ results/
   git commit -m "test(hpc): full run of the Part 3 and Part 4 gates and measures on the college HPC (WSL2)"
   git push -u origin HEAD
   ```
   The commit has no AI attribution line (the owner's rule).
2. Copy the logs to the Windows Desktop:
   ```bash
   W=$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r')
   tar czf "/mnt/c/Users/$W/Desktop/hpc-logs-$(date +%Y%m%d).tar.gz" traces/hpc-*.log traces/hpc-summary.log traces/hpc-run.out
   ```
3. Report:
   - steps passed and failed;
   - the branch pushed;
   - where the logs are.

   Failed steps go back to the laptop (Part E, "A gate failed").

---

## Part E — Runbook (the owner)

| I want to… | Do this (in Ubuntu, `cd ~/sever-db`) |
|---|---|
| See how it's going | `bash scripts/hpc/status.sh` (or just watch the phone) |
| Stop it | `bash scripts/hpc/launch.sh stop real`. Finished steps are kept |
| Continue after a stop | `bash scripts/hpc/launch.sh start real`. It continues where it stopped |
| Continue after Windows restarted | Sign in to Windows. The keep-alive starts Ubuntu and the run continues by itself; check with `status.sh` |
| See the alerts | `tail ~/longrun/real/alerts.log` |
| Restore a backup | `bash scripts/hpc/backup.sh real restore <file.tar.gz>`. It unpacks into `~/restored-<time>/` after checking the checksum, and never touches the repository |
| Remove everything afterwards | `bash scripts/hpc/install.sh --uninstall`; delete `sever-wsl-keepalive.vbs` from the Startup folder; restore `.wslconfig` from `.wslconfig.before-sever` (or delete it); after the results are pushed and copied, PowerShell `wsl --unregister Ubuntu-24.04` (deletes the run's databases and keys too); remove the HPC's SSH key on GitHub |

**What each alert means:**

| Alert | Meaning | What to do |
|---|---|---|
| start | the run began | nothing |
| restart | it restarted after an interruption; finished steps are kept | nothing; several in a row: look at `status.sh` |
| crash | the job was killed (out of memory, or killed by hand); systemd restarts it with a delay | nothing, unless it repeats |
| stopped | someone stopped it (`launch.sh stop`) | `launch.sh start real` to continue |
| refused | the start check failed (disk, memory, swap, memory lock, commit); the reason is in the alert | fix the reason; it retries by itself until the cap |
| failed | it gave up: 8 starts in 7 days, or refused at the cap | `status.sh`, fix, then `launch.sh start real` |
| stale | no CPU progress for 30 min (a hang); it is **not** killed | `status.sh`; if really stuck: `launch.sh stop real`, then `start real` |
| disk / memory | little disk (under 40 GB) or memory (under 2 GB) left | free space on C: / close other programs |
| backup | no backup for 3 hours, or a copy failed | `bash scripts/hpc/backup.sh real` and read its message |
| done | finished: every step passed, or a list of failed steps | Part D phase 11 (Claude), or Part E below |

**A gate failed.** That's a result, not a crash, and it is never rerun here.
1. On the laptop, Claude reads the logs.
2. It fixes the bug with a red test first.
3. The fix is merged into `main` and gets a new commit.
4. Back on the HPC, with the new commit checked out:
   - Claude removes `~/longrun/real/DONE`;
   - it deletes the stale outputs of the steps to rerun (`traces/p3-crash-*`, `traces/p4-crash-*`
     when those rerun);
   - it sets `ONLY="<that gate and every later step>"` and `FORCE=1` in `~/longrun/real.env`;
   - it runs `drills.sh` and then `launch.sh start real`.

The decision to rerun is recorded on the laptop with its reason.

## Part F — Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Permission denied (publickey)` on clone | the SSH key isn't on GitHub | Part B step 2; `ssh -T git@github.com` must greet you |
| `wsl --install` needs administrator rights | WSL isn't enabled on the machine | IT runs `wsl --install --no-distribution` once |
| `setup.sh` fails downloading | a campus proxy | ask IT for it; `export https_proxy=http://HOST:PORT http_proxy=…`, rerun (safe) |
| `preflight refused: ulimit -l …` | `root-setup.sh` not run, or WSL not restarted after it | Phase 3 again |
| `preflight refused: swap is on` | `.wslconfig` not applied | `windows.sh`, then `wsl --shutdown` |
| `preflight refused: HEAD is …` | a different commit is checked out | `git checkout <approved commit>` |
| `preflight refused: tracked files differ` | something changed a tracked file | `git status`; show Claude on the laptop; never commit it here |
| A step's log says `PlatformUnsafe` / `§12.8` | memory lock or swap | `status.sh`; Phase 3/4 checks |
| A step's log says `§12.9` and `filesystem` | the repository is on a Windows drive | it must be `~/sever-db` |
| Out of memory (`dmesg` mentions oom; a crash alert) | too many parallel jobs for the memory WSL has | set `JOBS=4` in `~/longrun/real.env`; it continues |
| C: runs out of space | Ubuntu's virtual disk grows on C: | free space on C: |
| Nothing happens after a Windows restart | not signed in yet, or the keep-alive was deleted | sign in; check the Startup folder for `sever-wsl-keepalive.vbs` |
