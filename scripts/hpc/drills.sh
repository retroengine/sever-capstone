#!/usr/bin/env bash
# scripts/hpc/drills.sh [DRILL…] — the failure drills (step 4 of the guide), on the drill instance
# sever-hpc@drill: the same unit, scripts and restart rules as the real run, with three fake
# 10-second steps (MOCK=1, mock-step.sh). About 10 minutes. Prints a pass/fail table and, when every
# drill passes, writes $LONGRUN/drill/PASSED with the commit (launch.sh start real requires it).
#
#   session   the run does not belong to the terminal: closing it cannot stop the run
#   kill9     kill -9 of the job: systemd restarts it, passed steps are kept, the killed one reruns
#   torn      a step log cut mid-write (no valid rc line): that step reruns, the others are kept
#   reboot    every process killed at once, then the boot path (default.target) starts it again
#   disk      too little disk: preflight refuses, retries stop at the cap with an alert; fixed: runs
#   hang      a hung step: the watchdog alerts (no kill); resumed: the run finishes
#   loop      a job that always crashes: restarts stop at the start limit, with an alert
#   failed    a step that fails: the run finishes, is marked DONE and never reruns that step
#   backup    a backup is written and verified; restore checks it; a damaged copy is refused
set -u
. "$(dirname "$0")/lib.sh"
cd "$REPO" || exit 1
ENVF="$LONGRUN/drill.env"
[ -f "$ENVF" ] || { echo "run scripts/hpc/install.sh first"; exit 1; }
load_instance drill
D="$STATE"; ALERTS="$D/alerts.log"; SUM="traces/hpc-drill-summary.log"
results=()

set_env() { if grep -q "^$1=" "$ENVF"; then sed -i "s|^$1=.*|$1=$2|" "$ENVF"; else echo "$1=$2" >>"$ENVF"; fi; }
prop() { systemctl --user show -p "$1" --value "$UNIT"; }
wait_until() { # SECONDS CONDITION…  (polls every second)
  local t=$1; shift
  for ((i = 0; i < t; i++)); do eval "$*" && return 0; sleep 1; done; return 1
}
reset() {
  systemctl --user stop "$UNIT" 2>/dev/null; systemctl --user disable "$UNIT" 2>/dev/null
  systemctl --user reset-failed "$UNIT" 2>/dev/null
  rm -rf "${D:?}"/* traces/hpc-drill-*
  set_env MOCK_SECONDS 10; set_env DISK_MIN_GB 1; set_env STALE_MIN 1
}
start() { systemctl --user reset-failed "$UNIT" 2>/dev/null; systemctl --user start --no-block "$UNIT"; }
done_ok() { [ -f "$D/DONE" ] && grep -q "run-all end failed=0 interrupted=0" "$SUM" 2>/dev/null; }
step_passed() { grep -q " $1 rc=0 " "$SUM" 2>/dev/null; }
record() { results+=("| $1 | $2 | $3 |"); echo "-- $1: $2 ($3)"; }

drill_session() {
  reset; start
  wait_until 20 '[ "$(prop ActiveState)" = active ]'
  cg=$(prop ControlGroup); linger=$(loginctl show-user "$USER" -p Linger --value)
  if [[ "$cg" == */user@$(id -u).service/* ]] && [ "$linger" = yes ] && wait_until 90 done_ok; then
    record session PASS "unit in $cg, linger on: no terminal owns it; finished"
  else record session FAIL "cgroup=$cg linger=$linger done=$(cat "$D/DONE" 2>/dev/null)"; fi
}

drill_kill9() {
  reset; start
  wait_until 60 'step_passed mock-a && grep -q "mock-b START" traces/hpc-drill-run.out 2>/dev/null'
  sleep 3; kill -9 "$(prop MainPID)"
  if wait_until 120 done_ok && grep -q "mock-a SKIPPED (passed earlier)" "$SUM" && step_passed mock-b \
     && [ "$(cat "$D/starts")" -ge 2 ] && grep -q "\[crash\]" "$ALERTS" && grep -q "\[restart\]" "$ALERTS"; then
    record kill9 PASS "restarted by systemd ($(cat "$D/starts") starts), mock-a kept, mock-b rerun, crash and restart alerts"
  else record kill9 FAIL "starts=$(cat "$D/starts" 2>/dev/null) done=$([ -f "$D/DONE" ] && echo y || echo n)"; fi
}

drill_torn() {
  reset; start; wait_until 120 done_ok
  # mock-c's log loses its final "rc=0" mid-write: truncate the line to "rc="
  sed -i '$ s/^rc=0$/rc=/' traces/hpc-drill-mock-c.log; rm -f "$D/DONE"; : >"$SUM.new"; mv "$SUM.new" "$SUM"
  start
  if wait_until 90 done_ok && grep -q "mock-a SKIPPED" "$SUM" && grep -q "mock-b SKIPPED" "$SUM" && step_passed mock-c; then
    record torn PASS "the torn step reran; the two finished steps were kept"
  else record torn FAIL "see $SUM"; fi
}

drill_reboot() {
  reset; systemctl --user enable "$UNIT" >/dev/null 2>&1; start
  wait_until 60 'step_passed mock-a'; sleep 2
  # A reboot: every process dies at once, nothing runs on-exit, systemd must not restart it itself.
  systemctl --user kill -s KILL "$UNIT"; systemctl --user stop "$UNIT" 2>/dev/null
  systemctl --user reset-failed "$UNIT" 2>/dev/null; rm -f "$D/running"
  wait_until 10 '[ "$(prop ActiveState)" != active ]'
  systemctl --user start default.target   # what the user manager does at boot (linger)
  if wait_until 120 done_ok && grep -q "mock-a SKIPPED (passed earlier)" "$SUM"; then
    record reboot PASS "the boot path started it (enabled), it continued; the real reboot drill is HPC_GUIDE.md Part D phase 7"
  else record reboot FAIL "enabled=$(prop UnitFileState) state=$(prop ActiveState)"; fi
  systemctl --user disable "$UNIT" >/dev/null 2>&1
}

drill_disk() {
  reset; set_env DISK_MIN_GB 999999; start
  ok1=0; wait_until 120 '[ "$(prop ActiveState)" = failed ]' && grep -q "\[refused\]" "$ALERTS" && grep -q "\[failed\]" "$ALERTS" && ok1=1
  set_env DISK_MIN_GB 1; start
  if [ "$ok1" = 1 ] && wait_until 90 done_ok; then
    record disk PASS "refused with an alert, gave up at the cap with an alert; after the fix it ran"
  else record disk FAIL "refused/failed alerts=$ok1 state=$(prop ActiveState)"; fi
}

drill_hang() {
  reset; touch "$D/hang.mock-b"; start
  wait_until 60 'pgrep -f "mock-step.sh mock-b" >/dev/null && [ "$(ps -o stat= -p "$(pgrep -f "mock-step.sh mock-b" | head -1)" | cut -c1)" = T ]'
  bash scripts/hpc/watchdog.sh drill; sleep 65; bash scripts/hpc/watchdog.sh drill
  alerted=0; grep -q "\[stale\]" "$ALERTS" && alerted=1
  still=$(prop ActiveState)
  pkill -CONT -f "mock-step.sh mock-b"
  if [ "$alerted" = 1 ] && [ "$still" = active ] && wait_until 90 done_ok; then
    record hang PASS "stale alert after 1 min, not killed; resumed and finished"
  else record hang FAIL "alert=$alerted state=$still"; fi
}

drill_loop() {
  reset; touch "$D/killrun-always"; start
  if wait_until 240 '[ "$(prop ActiveState)" = failed ]'; then
    sleep 15; s2=$(prop ActiveState)
    if [ "$s2" = failed ] && grep -q "\[failed\]" "$ALERTS"; then
      record loop PASS "stopped after $(cat "$D/starts") starts (cap 4), stays stopped, alert sent"
    else record loop FAIL "state after the cap: $s2"; fi
  else record loop FAIL "never reached the cap (state $(prop ActiveState), restarts $(prop NRestarts))"; fi
  rm -f "$D/killrun-always"
}

drill_failed() {
  reset; touch "$D/fail.mock-b"; start
  wait_until 120 '[ -f "$D/DONE" ]'
  ok=0; why=""
  grep -q " mock-b rc=1 " "$SUM" || why+=" no-rc1"
  grep -q "\[done\].*mock-b" "$ALERTS" || why+=" no-done-alert"
  [ "$(cat "$D/starts")" = 1 ] || why+=" starts=$(cat "$D/starts")"
  [ -z "$why" ] && ok=1
  start; sleep 5; s=$(prop ActiveState)               # DONE: the unit must not run again
  MOCK=1 PREFIX=hpc-drill bash scripts/hpc/run-all.sh >/dev/null 2>&1   # and run-all skips the failed step
  if [ "$ok" = 1 ] && [ "$s" != active ] && grep -q "mock-b SKIPPED (finished earlier with rc=1" "$SUM"; then
    record failed PASS "finished, DONE, no restart; the failed step is never rerun"
  else record failed FAIL "ok=$ok state=$s$why"; fi
}

drill_backup() {
  reset; start; wait_until 120 done_ok
  bash scripts/hpc/backup.sh drill >/dev/null
  b=$(ls -1t "$BACKUP_DIR"/hpc-drill-*.tar.gz 2>/dev/null | head -1)
  r=$(bash scripts/hpc/backup.sh drill restore "$b" 2>&1 | sed -n 's/^restored into \([^ ]*\).*/\1/p')
  good=0; [ -n "$r" ] && [ -f "$r/traces/hpc-drill-summary.log" ] && [ -f "$r/COMMIT" ] && good=1
  cp "$b" "$D/bad.tar.gz"; cp "$b.sha256" "$D/bad.tar.gz.sha256"; sed -i "s|$(basename "$b")|bad.tar.gz|" "$D/bad.tar.gz.sha256"
  printf 'x' | dd of="$D/bad.tar.gz" bs=1 seek=100 conv=notrunc 2>/dev/null
  refused=0; bash scripts/hpc/backup.sh drill restore "$D/bad.tar.gz" >/dev/null 2>&1 || refused=1
  [ -n "$r" ] && rm -rf "$r"
  if [ "$good" = 1 ] && [ "$refused" = 1 ]; then record backup PASS "written, verified, restored; a damaged copy refused"
  else record backup FAIL "restored=$good refused_damaged=$refused"; fi
}

all=(session kill9 torn reboot disk hang loop failed backup)
want=("$@"); [ ${#want[@]} -gt 0 ] || want=("${all[@]}")
for d in "${want[@]}"; do echo "== drill $d"; "drill_$d"; done
reset

echo
echo "| Drill | Result | Detail |"
echo "|---|---|---|"
printf '%s\n' "${results[@]}"
if [ ${#want[@]} -eq ${#all[@]} ] && ! printf '%s\n' "${results[@]}" | grep -q FAIL; then
  git rev-parse HEAD >"$D/PASSED"; echo "ALL DRILLS PASS on $(git rev-parse --short HEAD)"; exit 0
fi
printf '%s\n' "${results[@]}" | grep -q FAIL && { echo "SOME DRILLS FAILED"; exit 1; }
echo "partial run: PASSED is written only when every drill runs and passes"
