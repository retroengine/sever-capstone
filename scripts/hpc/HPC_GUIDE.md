# Running SEVER-DB's final test run on the college HPC (WSL2 Ubuntu)

The one guide for the v1.0 gate run (DB-111). It is written for the owner, step by step, and so that
it can be pasted into a Claude chat on the HPC as background when help is needed there. Nothing else
in the repository describes this run; other files point here.

---

## Part A — The scenario (paste this part into Claude chat first)

**Who I am and what this is.** I'm the owner of SEVER-DB, a vector database with provable
deletion, built in Rust and Python as a capstone project. The code is on GitHub (private
repository `retroengine/sever-capstone`, branch `main`). Parts 1 and 2 of the project are finished
and frozen. Parts 3 and 4 are built and pass every check on my laptop. What's left is **one long
run of every pre-registered test gate and measure**, at full size, about 1–2 days. The results
decide whether Parts 3 and 4 can be frozen and v1.0 released.

**The machine.** The college HPC workstation, running **Windows**. The run happens inside
**WSL2 Ubuntu 24.04** on it; there is no native Linux (decision DB-111).
- The run is CPU-only (the GPU is not used), and the floating-point results must be bit-for-bit
  reproducible.
- Inside Ubuntu I am the distribution's admin (`sudo` with my Ubuntu password), even if my Windows
  account is not an administrator.
- WSL2 must already be enabled on the machine (`wsl --status` works in PowerShell). Enabling it the
  first time needs a Windows administrator; installing Ubuntu into it does not.
- I can leave it running for 2 days. A paper note on it says not to turn it off.

**The scripts that do the work** (in the repository, under `scripts/hpc/`):
- `check.sh` checks the machine and changes nothing. It prints `[ ok ]`, `[WARN]` or `[FAIL]` lines,
  and at the end says whether all 22 steps can run or only 20.
- `setup.sh` installs everything once, in about 20–40 minutes (`sudo` inside Ubuntu).
- `run-all.sh` runs the 22 steps one after another (`p3-crash`, `p3-replay`, …, `p4-ex8`) at their
  full pre-registered sizes. Each step's output goes to `traces/hpc-<step>.log`, which ends with
  `rc=N` (0 = passed). There's one line per step in `traces/hpc-summary.log`. If restarted, it skips
  the steps that already passed.

**Two steps have extra needs.** `p4-forensics` and `p4-ex6` run the database in its strict "keys
never touch the disk" mode (spec §12.8). That needs, inside Ubuntu:
- `ulimit -l` = `unlimited` (the memory-lock limit; step 9 raises it with `sudo prlimit`),
- swap off (`swap=0` in the Windows file `.wslconfig`, step 3),
- hibernation off (WSL has none),
- a working `/dev/fuse` with `fusermount3` (`setup.sh` installs them).

**What the run claims, and what it does not (DB-111, overview L-8).** Locked memory and the forensic
scan cover the Ubuntu guest: its memory and the ext4 disk the engine writes to. What the Windows
host keeps (its pagefile, old blocks of the virtual disk file `ext4.vhdx`) is outside the claim and
is reported as a limit.

**Rules the helper must respect** (from the project's CLAUDE.md):
- Don't change any code or test on this machine. The run must test the exact commit on GitHub.
- A failing **gate** is a bug to report, not something to fix or rerun here. Save its log.
- A **measure** is recorded as it comes out, never rerun because of its value.
- Never edit `docs/RUN_LEDGER.jsonl`, `results/` or `docs/audit/` by hand.
- Never print, copy or commit database folders, key files or certificates written by the run. They
  live under `target/` and `traces/`, which git ignores.
- Don't run the two strict steps in a weaker mode (`allow_unsafe_memory`) to make them pass, and
  don't shrink any step. Changing a pre-registered gate is the owner's recorded decision, made
  before any result.

---

## Part B — Before you leave home

1. **The data bundle** is on the laptop's Windows Desktop in the folder `sever-hpc`:
   - `sever-data.tar` (about 3.8 GB): `datasets/processed/`, `artefacts/`, and 10 trace files.
   - `sever-data.tar.sha256`: its fingerprint, to check that the copy is complete.
2. **Get the bundle to the HPC.** Pick one way:
   - **USB stick** (8 GB or more, formatted **exFAT** or NTFS; FAT32 can't hold a file over 4 GB):
     copy the whole `sever-hpc` folder onto it.
   - **Google Drive:** upload the `sever-hpc` folder at drive.google.com. On the HPC you download it in
     the browser.
3. **Bring your phone.** On the HPC you'll log in to GitHub (and maybe Google) in the browser, which
   may ask for a 2-factor code.

---

## Part C — On the HPC, step by step

Steps 1–3 happen in **Windows** (PowerShell: press the Windows key, type `PowerShell`, Enter).
From step 4 on, everything happens in the **Ubuntu** window. Paste into a terminal with right-click
or **Ctrl+Shift+V**.

### Step 1 — WSL and Ubuntu (5–15 min)

In PowerShell:
```powershell
wsl --status
wsl --list --verbose
```
- `wsl --status` fails or says WSL is not installed: WSL needs a Windows administrator once (IT:
  `wsl --install --no-distribution`). Ask, then continue.
- `Ubuntu-24.04` is not in the list: install it (no admin needed when WSL is enabled):
  ```powershell
  wsl --update
  wsl --install -d Ubuntu-24.04
  ```
  It opens an Ubuntu window and asks for a new **Ubuntu user name and password**. Write the password
  down: `sudo` asks for it.
- The list shows `VERSION 1` for Ubuntu-24.04: `wsl --set-version Ubuntu-24.04 2`.

### Step 2 — Keep Windows awake for 2 days (2 min)

1. **Settings → System → Power** (or **Power & battery**) **→ Screen and sleep:** set "When plugged
   in, put my device to sleep after" to **Never**. If the setting is locked, ask IT.
2. **Settings → Windows Update → Pause updates** for 1 week, so Windows doesn't restart itself.
3. Leave the paper note on the machine.

During the run: lock the screen with **Windows key + L**. **Never sign out or shut down**; signing
out stops Ubuntu and the run with it.

### Step 3 — Give Ubuntu the machine's cores and memory, and no swap (3 min)

In PowerShell, see what the machine has:
```powershell
$env:NUMBER_OF_PROCESSORS
[math]::Floor((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
```
Open the WSL settings file (Notepad creates it if it doesn't exist):
```powershell
notepad "$env:USERPROFILE\.wslconfig"
```
Put exactly this in it, with your numbers, and save:
```ini
[wsl2]
memory=56GB
processors=32
swap=0
```
- `memory`: the machine's RAM minus 8 GB (for Windows). 64 GB of RAM gives `56GB`.
- `processors`: the first number printed above (all of them).
- `swap=0`: required for the two strict steps (§12.8).

Then restart WSL so it reads the file:
```powershell
wsl --shutdown
```
Open Ubuntu again (Start menu → **Ubuntu 24.04**).

### Step 4 — Quick look at the machine (1 min)

In Ubuntu:
```bash
uname -m; nproc; free -g | head -3; df -hT ~
```
You want `x86_64`, all the cores, the memory you set, a **Swap** row of `0`, and a home folder of
type `ext4`.

`df` shows the virtual disk's maximum size, not real free space. Check the real space in Windows:
**File Explorer → This PC**. Drive **C:** needs **150 GB or more free**, because Ubuntu's disk
lives there.

### Step 5 — Let Ubuntu talk to GitHub (5 min)

```bash
ssh-keygen -t ed25519 -C "college-hpc" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```
1. Copy the printed line, which starts with `ssh-ed25519`.
2. In the browser, log in to github.com and go to **profile picture → Settings → SSH and GPG keys →
   New SSH key**.
3. Title it `College HPC`, paste the line, and click **Add SSH key**.

Then test it:
```bash
ssh -T -o StrictHostKeyChecking=accept-new git@github.com
```
It should say `Hi <your-name>! You've successfully authenticated`.

### Step 6 — Get the code and the data (10–15 min)

The project **must** live in the Ubuntu home folder (`~/sever-db`), never on a Windows drive
(`/mnt/c/...`): the engine refuses a Windows drive (spec §12.9).
```bash
git clone git@github.com:retroengine/sever-capstone.git ~/sever-db
cd ~/sever-db
git log --oneline -1
```
Write down the commit shown; it's the one being tested.

Find the bundle. Windows drives appear under `/mnt/` (C: is `/mnt/c`).

**From a USB stick** (say it is drive **E:** in File Explorer):
```bash
ls /mnt/e/sever-hpc/ 2>/dev/null || { sudo mkdir -p /mnt/e && sudo mount -t drvfs E: /mnt/e; }
cp /mnt/e/sever-hpc/sever-data.tar* ~/sever-db/
```
**From Google Drive:** download the `sever-hpc` folder in the browser (it lands in Downloads, maybe as
a zip, which you unzip in File Explorer), then:
```bash
WINUSER=$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r')
cp "/mnt/c/Users/$WINUSER/Downloads/sever-hpc/sever-data.tar"* ~/sever-db/
```
Then, for either way:
```bash
cd ~/sever-db
sha256sum -c sever-data.tar.sha256          # must say: sever-data.tar: OK
tar xf sever-data.tar && rm sever-data.tar sever-data.tar.sha256
(cd datasets && sha256sum --quiet -c MANIFEST.sha256) && echo "DATA OK"
```

### Step 7 — Check the machine (1 min)

```bash
cd ~/sever-db
bash scripts/hpc/check.sh
```
Fix every `[FAIL]` line before going on:

| `[FAIL]` says | What to do |
|---|---|
| `WSL1` | PowerShell: `wsl --set-version Ubuntu-24.04 2`, then reopen Ubuntu |
| `RAM: too little` | Raise `memory=` in `.wslconfig` (step 3), `wsl --shutdown`, reopen Ubuntu. If the machine itself has under 32 GB, tell Claude |
| `this folder is on '9p'` (or `drvfs`, `v9fs`) | The project is on a Windows drive. Clone it again into `~/sever-db` (step 6) |
| `cannot reach https://…` | The campus may need a proxy. Ask IT for the address, then `export https_proxy=http://PROXY:PORT http_proxy=http://PROXY:PORT` before the next steps |
| `datasets/processed missing` | Step 6, the data part |

`[WARN]` lines about missing tools are fine now; `setup.sh` installs them. The memory-rule warnings
are handled in steps 3 and 9.

### Step 8 — Install everything (20–40 min)

```bash
cd ~/sever-db
bash scripts/hpc/setup.sh 2>&1 | tee ~/setup.log
```
It asks for your Ubuntu password once (`sudo`). It installs the system packages, Rust (1.98.1,
nightly and 1.85), the cargo tools, `uv`, Python 3.13 and the project's packages, builds the three
Python modules, checks the data, and builds anything still missing.

- It ends with `== done`: good.
- Any error: give the last 50 lines (`tail -50 ~/setup.log`) to Claude chat.

Close the Ubuntu window and open a new one, so the new programs are on your `PATH`.

### Step 9 — Start the run

In the new Ubuntu window, **all in the same window**:
```bash
cd ~/sever-db
sudo prlimit --pid $$ --memlock=unlimited:unlimited
ulimit -l                                   # must print: unlimited
bash scripts/hpc/check.sh | tail -3         # must say: All 22 run-all.sh steps can run here.
mkdir -p traces
setsid nohup bash scripts/hpc/run-all.sh > traces/hpc-run.out 2>&1 &
```
- The `prlimit` line lifts the memory-lock limit for this window and everything started from it.
  It has to be repeated in any new window that starts the run.
- If `check.sh` still says **20 of 22**, read its `[WARN]` lines: swap (step 3) or `/dev/fuse`
  (`wsl --update` in PowerShell, then `wsl --shutdown`). Don't start without the two strict steps;
  ask Claude chat.
- If Ubuntu has less than 60 GB of memory, put `JOBS=4 ` at the very front of the `setsid` line.

**Check that it started**, about a minute later:
```bash
pgrep -af run-all.sh          # shows a line: it is running
tail -5 traces/hpc-run.out    # shows "run-all start ..." and "p3-crash START"
```

### Step 10 — Leave it running

1. In the same Ubuntu window: `tail -f traces/hpc-summary.log`. **Leave this window open**
   (minimising is fine). An open Ubuntu window keeps WSL running.
2. Lock the screen: **Windows key + L**. Don't sign out, don't shut down, don't run `wsl --shutdown`.
3. Come back in 1–2 days. The run doesn't need you in between.

### Step 11 — Checking on it (any time)

Open Ubuntu (or use the open window; Ctrl+C stops `tail -f`, not the run):
```bash
cd ~/sever-db
cat traces/hpc-summary.log    # one line per finished step: rc=0 = passed
tail -3 traces/hpc-run.out    # which step is running now
pgrep -af run-all.sh          # still running? (no output = finished or stopped)
```

**If Windows restarted or the run stopped:** open Ubuntu and repeat **step 9** exactly (the
`prlimit` line included; `.wslconfig` keeps swap off). Steps that already passed are skipped, and
the interrupted step starts over.

### Step 12 — When it has finished

The last line of `traces/hpc-run.out` reads `run-all end failed=0` (all passed) or `failed=1`.

**1. Collect the logs** (small, no secrets in them) and put a copy on the Windows Desktop:
```bash
cd ~/sever-db
tar czf ~/hpc-logs-$(date +%Y%m%d).tar.gz traces/hpc-*.log traces/hpc-summary.log traces/hpc-run.out
WINUSER=$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r')
cp ~/hpc-logs-*.tar.gz "/mnt/c/Users/$WINUSER/Desktop/"
```
Copy that file from the Desktop to the USB stick or Google Drive. The laptop's Claude needs it.

**2. Send the results to GitHub** (on a separate branch; the laptop merges it):
```bash
cd ~/sever-db
git status --short
```
You should see only files under `docs/`: the run ledger `docs/RUN_LEDGER.jsonl` and generated
reports such as `docs/MUTANTS_P3.md`, `docs/MUTANTS_P4.md`, `docs/PROOFS_P3.md`,
`docs/TEST_ORACLES_P4.md` or `docs/TRACE_PART_3.md`.

If **anything outside `docs/`** shows up, especially anything with `key`, `cert`, `db`, `secrets` or
`wal` in its name, **stop**. Don't commit; show the list to Claude chat. If only `docs/` files show:
```bash
git switch -c hpc-run-$(date +%Y%m%d)
git add docs/
git -c user.name="SaiKiran Vanaparthi" -c user.email="saikiran.vanaparthi72@gmail.com" commit -m "test(hpc): full run of the Part 3 and Part 4 gates and measures on the college HPC (WSL2)"
git push -u origin HEAD
```

**3. A step failed (`rc=1`)?** Don't rerun it, and don't change anything. The logs from point 1 are
what's needed. Back home, give them to Claude on the laptop. Each failed gate is a bug to fix there,
with a failing test first. Then only that gate and the ones after it run again, here, with the same
steps 9–12.

**4. Clean up** when everything is back home and safe:
- Remove the HPC's SSH key on github.com (Settings → SSH and GPG keys → Delete), unless you'll use
  the machine again.
- Delete the Ubuntu installation, which also removes every database, key and certificate the run
  wrote. In PowerShell, **only after** the push in point 2 worked and the logs are safely copied:
  `wsl --unregister Ubuntu-24.04`.
- Delete `.wslconfig` (`del "$env:USERPROFILE\.wslconfig"` in PowerShell) and undo the sleep and
  update settings of step 2.

---

## Part D — If something goes wrong (for Claude chat)

| Symptom | Likely cause | Fix |
|---|---|---|
| `Permission denied (publickey)` on clone | The SSH key isn't on GitHub, or was added to another account | Redo step 5; `ssh -T git@github.com` must greet you |
| `wsl --install` says it needs administrator rights | WSL isn't enabled on the machine | Ask IT to run `wsl --install --no-distribution` once (step 1) |
| `setup.sh` fails downloading | A proxy is needed | `export https_proxy=…` (step 7), then rerun step 8 (it is safe to rerun) |
| `uv sync` fails on `faiss-cpu` or another package | Network, or no wheel for this Python | Show Claude the error; don't change `pyproject.toml` |
| `ulimit -l` doesn't print `unlimited` after `prlimit` | `prlimit` ran in another window, or `sudo` failed | Run step 9 again, all lines in one window |
| A step's log says `PlatformUnsafe` and `§12.8` | Swap is on or the memory-lock limit is low | `free -g` must show swap 0 (step 3); start again from step 9 |
| A step's log says `§12.9` and `filesystem` | The project is on a Windows drive | Clone into `~/sever-db` (step 6) |
| The run stopped and Ubuntu was closed | Windows signed out, restarted, or `wsl --shutdown` | Step 11, "If Windows restarted" |
| `traces/hpc-summary.log` shows `rc=1` | A gate failed | Step 12, point 3: collect the logs, change nothing |
| Out of memory (the log ends abruptly; `dmesg` mentions oom) | Too many parallel jobs for the memory given to WSL | Raise `memory=` (step 3) or rerun step 9 with `JOBS=4 ` in front (passed steps are skipped) |
| C: runs out of space | Ubuntu's virtual disk grows on C: | Free space on C:, then step 11 |
