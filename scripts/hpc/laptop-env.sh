#!/usr/bin/env bash
# scripts/hpc/laptop-env.sh [--dry-run | --undo | --check] — makes the owner's laptop a clean,
# dedicated machine for the v1.0 run (DB-113). No sudo and no Windows admin; re-running it is safe.
#
#   Windows  .wslconfig (all 8 cores, 12 GB, swap=0 for the next WSL start; the old file is kept);
#            power on mains: no sleep, no hibernate, lid does nothing, max CPU 99 % (turbo off:
#            the laptop overheats at full turbo); the keep-alive becomes a supervisor that holds
#            the "system required" state (no idle sleep) and restarts WSL within 30 s whenever it
#            stops (a crash, vmmem killed, wsl --shutdown); extra programs closed (browsers,
#            OneDrive, Teams, Dell helpers, ...; never VS Code, Office or security software).
#   WSL      the editor's background helpers stopped (rust-analyzer, Copilot); the idle job queues
#            (sever-jobq, sever-sidejobs) stopped for the run; the memory guard kept.
#   Data     the dataset manifest verified; artefacts, Part 1 traces and Part 2 oracles present.
#   Tools    every crate fetched (no step needs the network); the Python environment loads.
#
# --undo puts back what it changed (power, keep-alive, job queues). --check only reports.
# To stop WSL on purpose while the supervisor runs: create  C:\Users\<you>\sever-run\STOP  first.
set -u
. "$(dirname "$0")/lib.sh"
cd "$REPO" || exit 1
mode=apply
case "${1:-}" in --dry-run) mode=dry ;; --undo) mode=undo ;; --check) mode=check ;; "") ;; *) echo "usage: $0 [--dry-run|--undo|--check]"; exit 2 ;; esac
ok=0; bad=0
say() { echo "$*"; }
okk() { echo "  ok    $*"; ok=$((ok + 1)); }
fail() { echo "  FAIL  $*"; bad=$((bad + 1)); }
run() { if [ "$mode" = dry ]; then echo "  (dry) $*"; else "$@"; fi; }

winuser=$(windows_user)
[ -n "$winuser" ] || { echo "cannot reach Windows (cmd.exe): is WSL interop on?"; exit 1; }
W="/mnt/c/Users/$winuser"; WW="C:\\Users\\$winuser"
RUN="$W/sever-run"; RUNW="$WW\\sever-run"
STARTUP="$W/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
distro=${WSL_DISTRO_NAME:-Ubuntu}
ps() { timeout 60 powershell.exe -NoProfile -NonInteractive -Command "$1" 2>/dev/null | tr -d '\r'; }

# ---------------------------------------------------------------------------------------------
if [ "$mode" = undo ]; then
  say "== undo"
  for s in "standby-timeout-ac 30" "hibernate-timeout-ac 180"; do powercfg.exe /change $s >/dev/null 2>&1; done
  powercfg.exe /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX 100 >/dev/null 2>&1
  powercfg.exe /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 1 >/dev/null 2>&1
  powercfg.exe /setactive SCHEME_CURRENT >/dev/null 2>&1
  : >"$RUN/STOP" 2>/dev/null
  [ -f "$RUN/keepalive.vbs.before" ] && cp "$RUN/keepalive.vbs.before" "$STARTUP/sever-wsl-keepalive.vbs"
  systemctl --user enable --now sever-jobq.service sever-sidejobs.service >/dev/null 2>&1
  say "power back to sleep 30 min / hibernate 3 h / CPU 100 % / lid sleeps; supervisor told to stop;"
  say "old keep-alive back; job queues on. .wslconfig: the old file is $W/.wslconfig.before-laptop-run"
  exit 0
fi

# ---------------------------------------------------------------------------------------------
say "== 1. Windows: WSL settings ($W/.wslconfig)"
cfg="[wsl2]
memory=12GB
processors=8
swap=0"
cur=$(tr -d '\r' <"$W/.wslconfig" 2>/dev/null)
if [ "$cur" = "$cfg" ]; then okk ".wslconfig already: memory=12GB processors=8 swap=0"
elif [ "$mode" = check ]; then fail ".wslconfig differs (memory=12GB processors=8 swap=0 expected)"
else
  [ -f "$W/.wslconfig" ] && [ ! -f "$W/.wslconfig.before-laptop-run" ] && run cp "$W/.wslconfig" "$W/.wslconfig.before-laptop-run"
  [ "$mode" = dry ] || printf '%s\n' "$cfg" | sed 's/$/\r/' >"$W/.wslconfig"
  okk ".wslconfig written (applies at the next WSL start; nothing restarts now)"
fi

say "== 2. Windows: power on mains (no sleep, no hibernate, lid does nothing, turbo off)"
if [ "$mode" != check ]; then
  for s in "standby-timeout-ac 0" "hibernate-timeout-ac 0" "disk-timeout-ac 0"; do run powercfg.exe /change $s >/dev/null 2>&1; done
  run powercfg.exe /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX 99 >/dev/null 2>&1
  run powercfg.exe /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0 >/dev/null 2>&1
  run powercfg.exe /setactive SCHEME_CURRENT >/dev/null 2>&1
fi
q() { powercfg.exe /q SCHEME_CURRENT "$1" "$2" 2>/dev/null | tr -d '\r' | awk '/Current AC Power Setting Index/ {print $NF}'; }
[ "$(q SUB_SLEEP STANDBYIDLE)" = 0x00000000 ] && okk "sleep on mains: never" || fail "sleep on mains is not 'never' (Settings > System > Power)"
[ "$(q SUB_SLEEP HIBERNATEIDLE)" = 0x00000000 ] && okk "hibernate on mains: never" || fail "hibernate on mains is not 'never'"
[ "$(q SUB_PROCESSOR PROCTHROTTLEMAX)" = 0x00000063 ] && okk "max CPU on mains: 99 % (turbo off)" || fail "max CPU on mains is not 99 %"
lid=$(q SUB_BUTTONS LIDACTION)
if [ "$lid" = 0x00000000 ]; then okk "closing the lid on mains: do nothing"
elif [ -z "$lid" ]; then echo "  note  this laptop does not expose the lid setting: keep the lid open"
else fail "closing the lid would sleep: keep the lid open, or Control Panel > Power Options > lid"; fi

say "== 3. Windows: the WSL supervisor (keep-alive that restarts WSL, no idle sleep)"
ps1='# SEVER-DB laptop run (DB-113): keeps WSL running and the PC awake. Written by laptop-env.sh.
# Stop on purpose: create the file STOP next to this script, then wsl --shutdown.
$ErrorActionPreference = "SilentlyContinue"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $dir "supervisor.log"
$m = New-Object System.Threading.Mutex($false, "Local\SeverWslSupervisor")
if (-not $m.WaitOne(0)) { exit 0 }
Add-Type -Namespace Sever -Name Power -MemberDefinition "[DllImport(\"kernel32.dll\")] public static extern uint SetThreadExecutionState(uint f);"
[Sever.Power]::SetThreadExecutionState([uint32]"0x80000001") | Out-Null   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
Remove-Item (Join-Path $dir "STOP") -ErrorAction SilentlyContinue
Add-Content $log "$(Get-Date -Format o) supervisor start"
while ($true) {
  if (Test-Path (Join-Path $dir "STOP")) { Add-Content $log "$(Get-Date -Format o) STOP file: exit"; break }
  $p = Start-Process -FilePath "wsl.exe" -ArgumentList "-d","@DISTRO@","--exec","/bin/sleep","infinity" -WindowStyle Hidden -PassThru
  $p.WaitForExit()
  Add-Content $log "$(Get-Date -Format o) WSL keep-alive ended (exit $($p.ExitCode)); restarting in 30 s"
  Start-Sleep -Seconds 30
}
[Sever.Power]::SetThreadExecutionState([uint32]"0x80000000") | Out-Null'
vbs="' SEVER-DB laptop run (DB-113): starts the WSL supervisor hidden at sign-in. Written by laptop-env.sh.
' To undo: bash ~/sever-db/scripts/hpc/laptop-env.sh --undo
CreateObject(\"WScript.Shell\").Run \"powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"\"$RUNW\\supervisor.ps1\"\"\", 0, False"
if [ "$mode" = apply ]; then
  mkdir -p "$RUN"
  [ -f "$STARTUP/sever-wsl-keepalive.vbs" ] && [ ! -f "$RUN/keepalive.vbs.before" ] \
    && cp "$STARTUP/sever-wsl-keepalive.vbs" "$RUN/keepalive.vbs.before"
  printf '%s\n' "${ps1//@DISTRO@/$distro}" | sed 's/$/\r/' >"$RUN/supervisor.ps1"
  printf '%s\n' "$vbs" | sed 's/$/\r/' >"$STARTUP/sever-wsl-keepalive.vbs"
  rm -f "$RUN/STOP"
  (cd /mnt/c && wscript.exe "$(wslpath -w "$STARTUP/sever-wsl-keepalive.vbs")" >/dev/null 2>&1 &)
  sleep 8
fi
if grep -q "supervisor.ps1" "$STARTUP/sever-wsl-keepalive.vbs" 2>/dev/null; then okk "Startup item runs the supervisor at sign-in"
else [ "$mode" = dry ] && echo "  (dry) would install the supervisor" || fail "Startup item is not the supervisor"; fi
sup=$(ps "(Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | Where-Object { \$_.ProcessId -ne \$PID -and \$_.CommandLine -like '*-File*supervisor.ps1*' } | Measure-Object).Count")
[ "${sup:-0}" -ge 1 ] 2>/dev/null && okk "supervisor running ($sup)" || { [ "$mode" = dry ] || fail "supervisor is not running"; }

say "== 4. Windows: close extra programs (never VS Code, Office or security software)"
apps="brave chrome msedge firefox opera OneDrive ms-teams Teams Spotify Discord Steam steamwebhelper WhatsApp Telegram Zoom PhoneExperienceHost Widgets WidgetService Copilot M365Copilot DellOptimizer.Systray DellOptimizer SupportAssistAgent Dell.TechHub Dell.TechHub.Instrumentation.SubAgent Dell.TechHub.Analytics.SubAgent Dell.TechHub.DataManager.SubAgent Dell.CoreServices.Client"
if [ "$mode" != check ]; then
  list=$(echo "$apps" | sed "s/[^ ]*/'&'/g; s/ /,/g")
  closed=$(ps "\$n=@($list); \$p=Get-Process -Name \$n -ErrorAction SilentlyContinue; if (\$p) { if ('$mode' -eq 'apply') { \$p | ForEach-Object { \$_.CloseMainWindow() | Out-Null }; Start-Sleep 8; Get-Process -Name \$n -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue }; (\$p.Name | Sort-Object -Unique) -join ' ' }")
  word=closed; [ "$mode" = dry ] && word="would close"
  [ -n "$closed" ] && okk "$word: $closed" || okk "none of the extra programs were running"
fi
left=$(ps "(Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 8 | ForEach-Object { \$_.Name + '=' + [int](\$_.WorkingSet64/1MB) + 'MB' }) -join ' '")
echo "  info  largest Windows processes now: $left"
echo "  info  close Excel and other Office files yourself (unsaved work); VS Code: close it when you are back"

say "== 5. WSL: editor helpers and idle services"
if [ "$mode" = apply ]; then
  pkill -f 'rust-analyzer' 2>/dev/null; pkill -f 'copilot-sdk|copilot-runtime' 2>/dev/null
  for u in sever-jobq sever-sidejobs; do
    if systemctl --user is-active --quiet "$u.service"; then
      if [ -z "$(ls -A jobs/queue jobs/running jobs/side 2>/dev/null | grep -v '^$')" ]; then
        systemctl --user disable --now "$u.service" >/dev/null 2>&1
      else echo "  note  $u has queued work: left running"; fi
    fi
  done
fi
for u in sever-jobq sever-sidejobs; do
  systemctl --user is-active --quiet "$u.service" && fail "$u still running (idle queues compete with the run)" || okk "$u stopped for the run"
done
systemctl --user is-active --quiet sever-oomguard.service && okk "memory guard (sever-oomguard) running" || fail "memory guard not running: systemctl --user start sever-oomguard"
pgrep -f rust-analyzer >/dev/null && echo "  note  rust-analyzer came back (VS Code is open): close VS Code when you are back" || okk "no rust-analyzer"

say "== 6. Data and inputs"; b0=$bad
if (cd datasets && sha256sum --quiet -c MANIFEST.sha256 >/dev/null 2>&1); then okk "datasets/MANIFEST.sha256 verifies"; else fail "datasets/MANIFEST.sha256 does not verify"; fi
for s in 42 123 777 2024 9999; do
  [ -f "artefacts/partition-seed$s.svp" ] || fail "artefacts/partition-seed$s.svp missing"
  for d in nq-10k nq-100k; do [ -s "traces/p1-$d-seed$s.jsonl" ] || fail "traces/p1-$d-seed$s.jsonl missing (Part 1 trace)"; done
  [ -s "traces/p2-oracle-nq-10k-seed$s.jsonl" ] || echo "  note  traces/p2-oracle-nq-10k-seed$s.jsonl missing: the crash gates write it first"
done
[ "$bad" = "$b0" ] && okk "artefacts and Part 1 traces for all five seeds"
f=$(free_gb .); [ "$f" -ge 100 ] && okk "$f GB free on the Linux disk" || fail "only $f GB free (100 wanted)"
for t in mkfs.ext4 fuse2fs fusermount3 debugfs; do command -v $t >/dev/null || fail "$t missing (p4-forensics)"; done
[ -r /dev/fuse ] && [ -w /dev/fuse ] && okk "/dev/fuse usable" || fail "/dev/fuse not usable"
# Earlier interim outputs of the Part 3 and Part 4 gates must not be picked up as this run's: a
# crash gate keeps a seed whose results file is complete ("already finished"). Inputs stay (the
# Part 1 traces p1-*, the Part 2 oracles p2-oracle-*). Only before the run, never during it.
old=$(cd traces && ls -d p3-crash-* p3-replay-* p3-attacks-* p3-measures-* p4-crash-* p4-replay-* \
  p4-attacks-* mutants-p3-gate mutants-p3-verifier mutants-p4-gate 2>/dev/null)
if [ -n "$old" ]; then
  if [ "$mode" = apply ] && [ ! -f traces/hpc-summary.log ]; then
    a="traces/archive-pre-laptop-run"; mkdir -p "$a"
    (cd traces && mv $old "archive-pre-laptop-run/") && okk "earlier gate outputs moved to $a ($(echo "$old" | wc -l) items)"
  elif [ -f traces/hpc-summary.log ]; then okk "the run has started: earlier outputs are left alone"
  else echo "  (dry) would move $(echo "$old" | wc -l) earlier gate outputs to traces/archive-pre-laptop-run/"; fi
else okk "no earlier gate outputs in traces/"; fi
for d in target/ex7-work-* target/ex2-work-*; do [ -e "$d" ] && { [ "$mode" = apply ] && rm -rf "$d"; }; done

say "== 7. Tools"; b0=$bad
if [ "$mode" = apply ]; then
  for m in Cargo.toml verifier/Cargo.toml audit/Cargo.toml spikes/p3-proof/Cargo.toml; do
    [ -f "$m" ] && { cargo fetch --locked --manifest-path "$m" >/dev/null 2>&1 || fail "cargo fetch $m"; }
  done
  for m in fuzz-p3/Cargo.toml fuzz-p4/Cargo.toml verifier/fuzz/Cargo.toml audit/fuzz/Cargo.toml; do
    [ -f "$m" ] && { cargo +nightly fetch --manifest-path "$m" >/dev/null 2>&1 || fail "cargo fetch $m"; }
  done
fi
[ "$bad" = "$b0" ] && okk "crates fetched for every workspace"
PYTHONPATH=python timeout 120 uv run --no-sync python -c "import sever_db, sever_testkit_p3.gates, sever_testkit_p4.gates, sever_experiments.ex7" >/dev/null 2>&1 \
  && okk "the Python environment loads (sever_db, both gate kits, experiments)" || fail "the Python environment does not load"
for t in cargo-mutants cargo-llvm-cov cargo-fuzz; do cargo ${t#cargo-} --version >/dev/null 2>&1 || cargo +nightly ${t#cargo-} --version >/dev/null 2>&1 || fail "$t missing"; done
okk "cargo-mutants, cargo-llvm-cov, cargo-fuzz present"

echo
echo "laptop-env ($mode): $ok ok, $bad failed"
[ "$bad" = 0 ]
