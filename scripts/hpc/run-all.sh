#!/usr/bin/env bash
# scripts/hpc/run-all.sh — runs every pre-registered Part 3 and Part 4 gate and measure once
# (Build 3-4 §1.9 P3-T1…T13, §2.10 P4-T1…T15), on the laptop at the sizes of DB-113 (which amends
# DB-111: the college HPC is no longer available). Normally started by the systemd user unit
# sever-hpc@real.service (scripts/hpc/launch.sh); the runbook is scripts/hpc/LAPTOP_RUN.md.
#
# Output:
#   traces/$PREFIX-<step>.log   the step's full output, ending with a line "rc=N"
#   traces/$PREFIX-summary.log  one line per step: time, step, rc, duration (appended)
#   traces/$PREFIX-run.out      this script's own output
#   traces/$PREFIX-phase.state  "PHASE START_EPOCH ESTIMATE_MIN" of the phase running (watchdog ETA)
#   PREFIX is "hpc" (real run) or "hpc-drill" (MOCK=1). The gates write the run ledger and
#   results/ themselves (never edit those by hand, CLAUDE.md §6.4). A verified backup
#   (backup.sh) is written after every step, so a result is off the Linux disk as soon as it exists.
#
# Phases: steps with the same phase number run at the same time (their memory budgets add up to
# at most the unit's MemoryMax, DB-113); the next phase starts when all of them have ended. Timing
# measures (p3-measures, p4-ex7, p4-ex8) run in phases of their own, so nothing else shares the CPU.
#
# Restart rule (Build §2.5: a failed gate is a result, never rerun until it passes):
#   - a step whose log ends "rc=0" passed: skipped;
#   - a step whose log ends "rc=1" … "rc=127" finished and failed: skipped, still reported failed;
#   - a step whose log has no rc line, or rc ≥ 128 (killed by a signal, out of memory): it was
#     interrupted and runs again; p3-crash continues its campaign (--resume), p4-crash continues
#     from its per-seed progress files by itself.
#   - DB-113: a step that ends with rc 1 … 127 while an out-of-memory kill happened (the kernel's
#     oom_kill count in /proc/vmstat rose, or oomguard stopped a process) did not produce a result:
#     the machine killed part of it. It is recorded as rc=137 with a "# oom:" line and runs again.
#   FORCE=1 with ONLY="step" reruns a finished step on purpose (only after a recorded reason).
#
# Waits (never failures): on battery power the next step waits for the mains (alert); a
# locked-memory step (p4-forensics, p4-ex6: spec §12.8 strict mode) waits until the memory lock is
# unlimited and swap is off (the owner's one sudo step, scripts/hpc/owner-sudo.sh; alert).
#
# Exit code: 0 every step passed; 1 at least one step finished and failed; 3 at least one step
# was interrupted (the unit restarts the run, which then continues). A failing step never stops
# the rest.
#
# Environment:
#   ONLY="a b"   run only these steps;  SKIP="a b"  skip these steps
#   FORCE=1      rerun a finished step (with ONLY)
#   MOCK=1       the drill: short fake steps (scripts/hpc/mock-step.sh) instead of the gates
#   OOMGUARD_LOG the memory guard's log (default traces/oomguard.log)
set -u
cd "$(dirname "$0")/../.."
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"   # a unit or setsid may not carry a login PATH
export PYTHONHASHSEED=0 PYTHONPATH=python
# DB-113: every crate is fetched and the gates' binaries prebuilt by laptop-env.sh before the run,
# so no step needs the network; builds that still happen are capped to fit beside another step.
export CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS:-6}
G3="uv run --no-sync python -m sever_testkit_p3.gates"
G4="uv run --no-sync python -m sever_testkit_p4.gates"
NPROC=$(nproc)
mkdir -p traces
if [ "${MOCK:-0}" = 1 ]; then PREFIX=${PREFIX:-hpc-drill}; INST=drill; else PREFIX=${PREFIX:-hpc}; INST=real; fi
SUMMARY=traces/$PREFIX-summary.log
PHASEF=traces/$PREFIX-phase.state
export OOMGUARD_LOG=${OOMGUARD_LOG:-traces/oomguard.log}
STATE_DIR=${LONGRUN:-$HOME/longrun}/$INST
mkdir -p "$STATE_DIR"
[ "${LOG_TO_FILE:-0}" = 1 ] && exec >>"traces/$PREFIX-run.out" 2>&1

# phase | name | estimate in minutes | lock (1 = needs the memory lock) | command (word-split on
# purpose; no argument contains spaces). Sizes and estimates: DB-113.
if [ "${MOCK:-0}" = 1 ]; then
  M="bash scripts/hpc/mock-step.sh"
  S=${MOCK_SECONDS:-20}
  STEPS=(
    "1|mock-a|1|0|$M mock-a $S"
    "2|mock-b|1|0|$M mock-b $S"
    "3|mock-c|1|0|$M mock-c $S"
    "4|mock-d|1|0|$M mock-d $S"
    "4|mock-e|1|0|$M mock-e $S"
    "5|mock-l|1|1|$M mock-l $S"
  )
else
  # shellcheck source=scripts/hpc/steps.sh
  . scripts/hpc/steps.sh
fi

in_list() { # $1 = word, $2 = space-separated list
  case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}
# last_rc LOG: the N of a final "rc=N" line, or nothing when the step never finished.
last_rc() { [ -f "$1" ] && tail -n 1 "$1" | sed -n 's/^rc=\([0-9][0-9]*\)$/\1/p'; }
# oom_events: out-of-memory kills so far, the kernel's (every cgroup) plus oomguard's stops.
oom_events() {
  local k g
  k=$(awk '$1 == "oom_kill" {print $2}' /proc/vmstat 2>/dev/null)
  g=$(grep -c "stopped lone process" "$OOMGUARD_LOG" 2>/dev/null)
  echo $(( ${k:-0} + ${g:-0} ))
}
alert() { # LEVEL MESSAGE: through on-exit.sh's library, when it can be loaded (never fatal)
  ( . scripts/hpc/lib.sh && load_instance "$INST" >/dev/null 2>&1 && notify "$@" ) 2>/dev/null || true
}
on_mains() { # true unless Windows says the laptop runs on battery (BatteryStatus 1)
  [ "${MOCK:-0}" = 1 ] && [ ! -f "$STATE_DIR/battery" ] && return 0
  [ "${MOCK:-0}" = 1 ] && return 1
  command -v powershell.exe >/dev/null || return 0
  local s
  s=$(timeout 30 powershell.exe -NoProfile -Command "(Get-CimInstance Win32_Battery).BatteryStatus" 2>/dev/null | tr -d '\r\n ')
  [ "$s" != 1 ]
}
lock_ready() { # the strict mode of spec §12.8 can start: memory lock unlimited, no swap
  if [ "${MOCK:-0}" = 1 ]; then [ ! -f "$STATE_DIR/nolock" ]; return; fi
  [ "$(ulimit -l)" = unlimited ] && [ -z "$(swapon --noheadings 2>/dev/null)" ]
}
# wait_for CHECK KEY MESSAGE: polls CHECK every 60 s (5 s in the drill); one alert, then quiet.
wait_for() {
  local check=$1 key=$2 msg=$3 said=0
  until $check; do
    if [ "$said" = 0 ]; then
      echo "$(date -Is) WAIT: $msg" | tee -a "$SUMMARY"; alert waiting "$msg"; said=1
      : >"$STATE_DIR/waiting"
    fi
    if [ "${MOCK:-0}" = 1 ]; then sleep 5; else sleep 60; fi
  done
  rm -f "$STATE_DIR/waiting"
  [ "$said" = 1 ] && echo "$(date -Is) WAIT over: $key" | tee -a "$SUMMARY"
  return 0
}
backup_now() { # a verified backup of what exists so far; serialised, never fatal
  ( flock -w 600 9 && bash scripts/hpc/backup.sh "$INST" >/dev/null 2>&1 ) 9>"$STATE_DIR/backup.lock" || true
}

# Reject unknown names in ONLY / SKIP so a typo does not silently run nothing.
names=" "; for s in "${STEPS[@]}"; do IFS='|' read -r _ n _ _ _ <<<"$s"; names+="$n "; done
for n in ${ONLY:-} ${SKIP:-}; do
  in_list "$n" "$names" || { echo "unknown step '$n'; steps are:$names"; exit 2; }
done

# run_step NAME LOCK CMD: runs one step unless it already finished; its log ends "rc=N".
run_step() {
  local name=$1 lock=$2 cmd=$3 log="traces/$PREFIX-$1.log" prev rc t0 dt o0 o1 line
  prev=$(last_rc "$log")
  if [ "${FORCE:-0}" != 1 ] && [ -n "$prev" ] && [ "$prev" -lt 128 ]; then
    if [ "$prev" = 0 ]; then
      echo "$(date -Is) $name SKIPPED (passed earlier)" | tee -a "$SUMMARY"
    else
      echo "$(date -Is) $name SKIPPED (finished earlier with rc=$prev; never rerun, Build §2.5)" | tee -a "$SUMMARY"
    fi
    return 0
  fi
  [ "$lock" = 1 ] && wait_for lock_ready "memory lock for $name" \
    "$name waits for the memory lock and swap off: run  sudo bash ~/sever-db/scripts/hpc/owner-sudo.sh"
  # An interrupted p3-crash continues its campaign when its run-state file is there.
  if [ "$name" = p3-crash ] && [ -f "$log" ] && [ "${FORCE:-0}" != 1 ] \
     && [ -f traces/p3-crash-nq-10k-run.json ]; then
    cmd="$cmd --resume"
  fi
  [ -f "$log" ] && mv "$log" "$log.prev"
  echo "$(date -Is) $name START: $cmd"
  t0=$(date +%s); o0=$(oom_events)
  {
    echo "# step $name, $(date -Is), commit $(git rev-parse HEAD 2>/dev/null)"
    echo "# cmd: $cmd"
  } >"$log"
  # shellcheck disable=SC2086  # the command is a word list by design
  $cmd >>"$log" 2>&1 </dev/null
  rc=$?
  o1=$(oom_events)
  if [ "$rc" -ge 1 ] && [ "$rc" -lt 128 ] && [ "$o1" -gt "$o0" ]; then
    echo "# oom: $((o1 - o0)) out-of-memory kill(s) during this step (exit was $rc): interrupted, not a result (DB-113)" >>"$log"
    rc=137
  fi
  echo "rc=$rc" >>"$log"
  dt=$(( $(date +%s) - t0 ))
  line="$(date -Is) $name rc=$rc duration=$(printf '%dh%02dm%02ds' $((dt/3600)) $((dt%3600/60)) $((dt%60))) log=$log"
  echo "$line" | tee -a "$SUMMARY"
  backup_now
  return 0
}

total_est=0; for s in "${STEPS[@]}"; do IFS='|' read -r _ _ e _ _ <<<"$s"; total_est=$(( total_est + e )); done
echo "run-all start $(date -Is) on $(hostname): nproc=$NPROC commit=$(git rev-parse --short HEAD 2>/dev/null) mock=${MOCK:-0} estimate=${total_est}min"
echo "ulimit -l = $(ulimit -l); swap: $(swapon --noheadings 2>/dev/null | wc -l) device(s)"
echo "== $(date -Is) run-all start nproc=$NPROC commit=$(git rev-parse --short HEAD 2>/dev/null) estimate=${total_est}min" >>"$SUMMARY"

phases=$(for s in "${STEPS[@]}"; do echo "${s%%|*}"; done | sort -n | uniq)
for ph in $phases; do
  todo=(); est=0
  for s in "${STEPS[@]}"; do
    IFS='|' read -r p name e lock cmd <<<"$s"
    [ "$p" = "$ph" ] || continue
    if [ -n "${ONLY:-}" ] && ! in_list "$name" "$ONLY"; then continue; fi
    if in_list "$name" "${SKIP:-}"; then
      echo "$(date -Is) $name SKIPPED (SKIP)" | tee -a "$SUMMARY"; continue
    fi
    todo+=("$name|$lock|$cmd"); [ "$e" -gt "$est" ] && est=$e
  done
  [ ${#todo[@]} -gt 0 ] || continue
  wait_for on_mains "mains power" "the laptop runs on battery: plug it in (the run waits)"
  echo "$ph $(date +%s) $est" >"$PHASEF"
  if [ ${#todo[@]} = 1 ]; then
    IFS='|' read -r name lock cmd <<<"${todo[0]}"; run_step "$name" "$lock" "$cmd"
  else
    pids=()
    for t in "${todo[@]}"; do
      IFS='|' read -r name lock cmd <<<"$t"; run_step "$name" "$lock" "$cmd" & pids+=($!)
    done
    for p in "${pids[@]}"; do wait "$p"; done
  fi
done
rm -f "$PHASEF"

# The verdict comes from the logs, so a step that ended in an earlier start counts too.
failed=0; interrupted=0
for s in "${STEPS[@]}"; do
  IFS='|' read -r _ name _ _ _ <<<"$s"
  if [ -n "${ONLY:-}" ] && ! in_list "$name" "$ONLY"; then continue; fi
  in_list "$name" "${SKIP:-}" && continue
  rc=$(last_rc "traces/$PREFIX-$name.log")
  if [ -z "$rc" ] || [ "$rc" -ge 128 ]; then interrupted=1
  elif [ "$rc" -ne 0 ]; then failed=1; fi
done
if [ "$interrupted" = 1 ]; then code=3; elif [ "$failed" = 1 ]; then code=1; else code=0; fi
echo "== $(date -Is) run-all end failed=$failed interrupted=$interrupted" | tee -a "$SUMMARY"
exit $code
