# Running SEVER-DB's final test run on the campus ThinkStation

A step-by-step guide for the owner. It is also written so it can be pasted into a Claude chat on the
ThinkStation as background, when help is needed there.

---

## Part A — The scenario (paste this part into Claude chat first)

**Who I am and what this is.** I'm the owner of SEVER-DB, a vector database with provable
deletion, built in Rust and Python as a capstone project. The code is on GitHub (private
repository `retroengine/sever-capstone`, branch `main`). Parts 1 and 2 of the project are finished
and frozen. Parts 3 and 4 are built and pass every check on my laptop. What's left is **one long
run of every pre-registered test gate and measure** on a strong machine, about 1–2 days. The
results decide whether Parts 3 and 4 can be frozen and v1.0 released.

**The machine.** A Lenovo ThinkStation on campus. It's new to me, and my laptop is not with me.
- It has a strong GPU. **The run doesn't use the GPU.** The work is CPU-only, and the floating-point
  results must be bit-for-bit reproducible.
- **I have a normal account, not admin.** There's an Admin account on the machine that I don't
  control. I can install things into my own home folder (Rust, `uv`, Python packages), but not
  system packages.
- I can leave it running for 2 days. I put a paper note on it saying not to turn it off.

**The two scripts that do the work** (both in the repository, under `scripts/vm/`):
- `check.sh` checks the machine and changes nothing. It prints `[ ok ]`, `[WARN]` or `[FAIL]` lines,
  and at the end says whether all 22 steps can run here or only 20.
- `setup.sh` installs everything once, in about 20–40 minutes. Without admin it runs as
  `NO_SUDO=1 bash scripts/vm/setup.sh`.
- `run-all.sh` runs the 22 steps one after another (`p3-crash`, `p3-replay`, …, `p4-ex8`). Each step's
  output goes to `traces/vm-<step>.log`, which ends with `rc=N` (0 = passed). There's one line per step
  in `traces/vm-summary.log`. If restarted, it skips the steps that already passed.

**Two steps need admin help.** `p4-forensics` and `p4-ex6` run the database in its strict "keys
never touch the disk" mode (spec §12.8). That needs:
- `ulimit -l` = `unlimited` (the memory-lock limit),
- swap off or encrypted,
- hibernation off,
- a working `/dev/fuse` with `fusermount3`.

Without admin, run the other 20 with `SKIP="p4-forensics p4-ex6"`.

**Rules the helper must respect** (from the project's CLAUDE.md):
- Don't change any code or test on this machine. The run must test the exact commit on GitHub.
- A failing **gate** is a bug to report, not something to fix or rerun here. Save its log.
- A **measure** is recorded as it comes out, never rerun because of its value.
- Never edit `docs/RUN_LEDGER.jsonl`, `results/` or `docs/audit/` by hand.
- Never print, copy or commit database folders, key files or certificates written by the run. They
  live under `target/` and `traces/`, which git ignores.
- Don't run the two strict steps in a weaker mode (`allow_unsafe_memory`) to make them pass.
  Changing a pre-registered gate is the owner's recorded decision, made before any result.

---

## Part B — Before you leave home (tonight)

1. **The data bundle** is on the Windows Desktop in the folder `sever-hpc`:
   - `sever-data.tar` (about 3.8 GB): `datasets/processed/`, `artefacts/`, and 10 trace files.
   - `sever-data.tar.sha256`: its fingerprint, to check that the copy is complete.
   - `HPC_GUIDE.md`: this file.
2. **Get the bundle to the ThinkStation.** Pick one way:
   - **USB stick** (8 GB or more, formatted **exFAT** or NTFS; FAT32 can't hold a file over 4 GB):
     copy the whole `sever-hpc` folder onto it.
   - **Google Drive:** upload the `sever-hpc` folder at drive.google.com. Tomorrow you download it in
     the ThinkStation's browser.
3. **Bring your phone.** On the ThinkStation you'll log in to GitHub (and maybe Google) in the
   browser, which may ask for a 2-factor code.

---

## Part C — On the ThinkStation, step by step

Open a terminal: press **Ctrl+Alt+T**, or search "Terminal" in the app menu. Type, or paste with
**Ctrl+Shift+V**, one block at a time.

### Step 1 — Quick look at the machine (1 min)

```bash
uname -m; . /etc/os-release; echo "$PRETTY_NAME"; nproc; free -g | head -2; df -hT ~
```
You want to see `x86_64`, Ubuntu or Debian, many cores, lots of memory, and a home folder of type
`ext4` or `xfs` with 150 GB or more free.

### Step 2 — Let the ThinkStation talk to GitHub (5 min)

```bash
ssh-keygen -t ed25519 -C "thinkstation" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```
1. Copy the printed line, which starts with `ssh-ed25519`.
2. In the browser, log in to github.com and go to **profile picture → Settings → SSH and GPG keys →
   New SSH key**.
3. Title it `ThinkStation`, paste the line, and click **Add SSH key**.

Then test it:
```bash
ssh -T -o StrictHostKeyChecking=accept-new git@github.com
```
It should say `Hi <your-name>! You've successfully authenticated`.

### Step 3 — Get the code (2 min)

```bash
git clone git@github.com:retroengine/sever-capstone.git ~/sever-db
cd ~/sever-db
git log --oneline -1
```
Write down the commit shown; it's the one being tested.

To open the project in VS Code, if it's installed: `code ~/sever-db`. You don't need VS Code for the
run; the terminal is enough.

### Step 4 — Put the data in place (5–10 min)

**From a USB stick:** plug it in. It appears under `/media/$USER/<name>`:
```bash
ls /media/$USER/
cp /media/$USER/*/sever-hpc/sever-data.tar* ~/sever-db/
```
**From Google Drive:** download the `sever-hpc` folder in the browser (it lands in `~/Downloads`,
maybe as a zip), then:
```bash
cd ~/Downloads && ls
# if it is a zip:  unzip sever-hpc*.zip
cp ~/Downloads/sever-hpc/sever-data.tar* ~/sever-db/ 2>/dev/null || cp ~/Downloads/sever-data.tar* ~/sever-db/
```
Then, for either way:
```bash
cd ~/sever-db
sha256sum -c sever-data.tar.sha256          # must say: sever-data.tar: OK
tar xf sever-data.tar && rm sever-data.tar sever-data.tar.sha256
(cd datasets && sha256sum --quiet -c MANIFEST.sha256) && echo "DATA OK"
```

### Step 5 — Check the machine (1 min)

```bash
cd ~/sever-db
bash scripts/vm/check.sh
```
Read the `[FAIL]` lines and fix them before going on:

| `[FAIL]` says | What to do |
|---|---|
| `cc`, `git` or `curl` missing | Only the admin can install them: `sudo apt-get install -y build-essential pkg-config git curl`. Without a C compiler nothing builds. |
| `this folder is on 'nfs'` (or another type) | The home folder is a network drive. Ask where a local disk is (often `/scratch` or `/data`), then clone there instead of `~/sever-db` and use that path everywhere below |
| `cannot reach https://…` | The campus may need a proxy. Ask IT for the proxy address, then `export https_proxy=http://PROXY:PORT http_proxy=http://PROXY:PORT` in the terminal before the next steps |
| `RAM: too little` | Tell Claude; the run needs a bigger machine |

`[WARN]` lines are fine for now. The last lines say whether **22** or **20** steps can run here.

### Step 6 — Install everything (20–40 min, no admin)

```bash
cd ~/sever-db
NO_SUDO=1 bash scripts/vm/setup.sh 2>&1 | tee ~/setup.log
```
It installs Rust (1.98.1, nightly and 1.85), the cargo tools, `uv`, Python 3.13 and the project's
packages. It builds the three Python modules, checks the data, and builds anything still missing.
If `fuse2fs` is missing, it unpacks it into your home folder.

- It ends with `== done`: good.
- It stops with `MISSING and required to build anything`: see Step 5, the admin row.
- Any other error: give `~/setup.log` (the last 50 lines: `tail -50 ~/setup.log`) to Claude chat.

Close the terminal and open a new one, so the new programs are on your `PATH`.

### Step 7 — Optional: the admin's 5-minute favour (for all 22 steps)

If an admin is around, show them this:

> Please run these on the ThinkStation for user `<my-username>`. They are for a 2-day test run of a
> database that keeps keys out of swap:
> ```bash
> sudo apt-get install -y fuse3 fuse2fs e2fsprogs
> printf '%s soft memlock unlimited\n%s hard memlock unlimited\n' <my-username> <my-username> | sudo tee /etc/security/limits.d/99-sever.conf
> sudo swapoff -a        # just before the run; undo afterwards with: sudo swapon -a
> sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
> ```

After the memlock line, **log out and back in**, then run `bash scripts/vm/check.sh` again. It
should now end with `All 22 run-all.sh steps can run here.`

No admin? That's fine. Go on with 20 steps.

### Step 8 — Keep the machine awake

1. **Settings → Power:** set Automatic suspend to **Off**, and Screen blank to **Never**, or whatever is
   allowed.
2. Leave the paper note on the machine.

### Step 9 — Start the run

```bash
cd ~/sever-db
mkdir -p traces
```
Then run **exactly one** of the following.

**If `check.sh` said all 22 steps can run:**
```bash
setsid nohup systemd-inhibit --what=sleep:idle --why="SEVER-DB test run" bash scripts/vm/run-all.sh > traces/vm-run.out 2>&1 &
```
**If it said 20 of 22** (no admin help):
```bash
SKIP="p4-forensics p4-ex6" setsid nohup systemd-inhibit --what=sleep:idle --why="SEVER-DB test run" bash scripts/vm/run-all.sh > traces/vm-run.out 2>&1 &
```
If `check.sh` said `systemd-inhibit not allowed`, drop the part
`systemd-inhibit --what=sleep:idle --why="SEVER-DB test run" ` from the command. Step 8 keeps the
machine awake instead.

If the machine has less than 60 GB of memory, put `JOBS=4 ` at the very front of the command.

**Check that it started**, about a minute later:
```bash
pgrep -af run-all.sh          # shows a line: it is running
tail -5 traces/vm-run.out     # shows "run-all start ..." and "p3-crash START"
```

### Step 10 — Leave it running

- **Lock the screen** with **Super+L** (the Windows key + L). **Don't log out and don't shut down.**
  Logging out may stop the run.
- Come back in 1–2 days. The run doesn't need you in between.

### Step 11 — Checking on it (any time)

```bash
cd ~/sever-db
cat traces/vm-summary.log     # one line per finished step: rc=0 = passed
tail -3 traces/vm-run.out     # which step is running now
pgrep -af run-all.sh          # still running? (no output = finished or stopped)
```

**If the machine was restarted or the run stopped:**
1. If the admin had turned swap off, they need to do it again (`sudo swapoff -a`).
2. Run the same Step 9 command again. Steps that already passed are skipped, and the interrupted
   step starts over.

### Step 12 — When it has finished

The last line of `traces/vm-run.out` reads `run-all end failed=0` (all passed) or `failed=1`.

**1. Collect the logs** (small, no secrets in them):
```bash
cd ~/sever-db
tar czf ~/vm-logs-$(date +%Y%m%d).tar.gz traces/vm-*.log traces/vm-summary.log traces/vm-run.out
```
Copy that file to the USB stick or upload it to Google Drive. Your laptop's Claude needs it.

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
git switch -c vm-run-$(date +%Y%m%d)
git add docs/
git -c user.name="SaiKiran Vanaparthi" -c user.email="himabindua321@gmail.com" commit -m "test(vm): full run of the Part 3 and Part 4 gates and measures on the ThinkStation"
git push -u origin HEAD
```

**3. A step failed (`rc=1`)?** Don't rerun it, and don't change anything. The logs from point 1 are
what's needed. Back home, give them to Claude on the laptop. Each failed gate is a bug to fix there,
with a failing test first. Then only that gate and the ones after it run again.

**4. Clean up** when everything is back home and safe:
- If the admin turned swap off: `sudo swapon -a`.
- Remove the ThinkStation's SSH key on github.com (Settings → SSH and GPG keys → Delete), unless
  you'll use the machine again.
- Optionally delete the project to free the disk: `rm -rf ~/sever-db`. Do this **only after** the
  push in point 2 worked and the logs are safely copied.

---

## Part D — If something goes wrong (for Claude chat)

| Symptom | Likely cause | Fix |
|---|---|---|
| `Permission denied (publickey)` on clone | The SSH key isn't on GitHub, or was added to another account | Redo Step 2; `ssh -T git@github.com` must greet you |
| `setup.sh` fails at `cargo install` with a linker error | No C compiler (`cc`) | Admin: `sudo apt-get install -y build-essential` |
| `setup.sh` fails downloading | A proxy is needed | `export https_proxy=…` (Step 5), then rerun Step 6 (it is safe to rerun) |
| `uv sync` fails on `faiss-cpu` or another package | Network, or no wheel for this Python | Show Claude the error; don't change `pyproject.toml` |
| A step's log says `PlatformUnsafe` | One of the §12.8 memory rules isn't met | Expected for `p4-forensics` and `p4-ex6` without admin; they should have been in `SKIP` |
| A step's log says `§12.9` and `filesystem` | The project is on a network or unsupported filesystem | Clone onto a local ext4 or XFS disk (Step 5 table) |
| The run stopped after a reboot | Power or updates | Step 11, "If the machine was restarted" |
| `traces/vm-summary.log` shows `rc=1` | A gate failed | Step 12, point 3: collect the logs, change nothing |
| Out of memory (the log ends abruptly; `dmesg` mentions oom) | Too many parallel jobs | Rerun the Step 9 command with `JOBS=4 ` in front (passed steps are skipped) |
