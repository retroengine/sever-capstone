#!/usr/bin/env bash
# scripts/hpc/run-all.sh — runs every pre-registered Part 3 and Part 4 gate and measure once, in
# sequence, in WSL2 Ubuntu on the college HPC workstation (DB-111; Build 3-4 §1.9 P3-T1…T13,
# §2.10 P4-T1…T15). Normally started by the systemd user unit sever-hpc@real.service
# (scripts/hpc/launch.sh); the one guide is scripts/hpc/HPC_GUIDE.md.
#
# Output:
#   traces/$PREFIX-<step>.log   the step's full output, ending with a line "rc=N"
#   traces/$PREFIX-summary.log  one line per step: time, step, rc, duration (appended)
#   traces/$PREFIX-run.out      this script's own output
#   PREFIX is "hpc" (real run) or "hpc-drill" (MOCK=1). The gates write the run ledger and
#   results/ themselves (never edit those by hand, CLAUDE.md §6.4).
#
# Restart rule (Build §2.5: a failed gate is a result, never rerun until it passes):
#   - a step whose log ends "rc=0" passed: skipped;
#   - a step whose log ends "rc=1" … "rc=127" finished and failed: skipped, still reported failed;
#   - a step whose log has no rc line, or rc ≥ 128 (killed by a signal, out of memory): it was
#     interrupted and runs again; p3-crash continues its campaign (--resume), p4-crash continues
#     from its per-seed progress files by itself.
#   FORCE=1 with ONLY="step" reruns a finished step on purpose (only after a recorded reason).
#
# Exit code: 0 every step passed; 1 at least one step finished and failed; 3 at least one step
# was interrupted (the unit restarts the run, which then continues). A failing step never stops
# the rest.
#
# Environment:
#   JOBS="N"     parallel jobs for the memory-heavy steps (default nproc/4, at least 2)
#   ONLY="a b"   run only these steps;  SKIP="a b"  skip these steps
#   FORCE=1      rerun a finished step (with ONLY)
#   MOCK=1       the drill: short fake steps (scripts/hpc/mock-step.sh) instead of the gates
set -u
cd "$(dirname "$0")/../.."
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"   # a unit or setsid may not carry a login PATH
export PYTHONHASHSEED=0 PYTHONPATH=python
G3="uv run --no-sync python -m sever_testkit_p3.gates"
G4="uv run --no-sync python -m sever_testkit_p4.gates"
NPROC=$(nproc)
JOBS=${JOBS:-$(( NPROC / 4 ))}
[ "$JOBS" -ge 2 ] 2>/dev/null || JOBS=2
mkdir -p traces
if [ "${MOCK:-0}" = 1 ]; then PREFIX=${PREFIX:-hpc-drill}; else PREFIX=${PREFIX:-hpc}; fi
SUMMARY=traces/$PREFIX-summary.log
[ "${LOG_TO_FILE:-0}" = 1 ] && exec >>"traces/$PREFIX-run.out" 2>&1

# name | command (word-split on purpose; no arguments contain spaces)
if [ "${MOCK:-0}" = 1 ]; then
  M="bash scripts/hpc/mock-step.sh"
  STEPS=(
    "mock-a|$M mock-a ${MOCK_SECONDS:-20}"
    "mock-b|$M mock-b ${MOCK_SECONDS:-20}"
    "mock-c|$M mock-c ${MOCK_SECONDS:-20}"
  )
else
STEPS=(
  # ---- Part 3, The Receipt: gates
  "p3-crash|$G3 p3-crash --data nq-10k --all-seeds --jobs 5"
  "p3-replay|$G3 p3-replay --data nq-100k --all-seeds --jobs 2"
  "p3-attacks|$G3 p3-attacks --data nq-10k --all-seeds --jobs 5"
  "p3-checks|$G3 p3-checks"
  "p3-coverage|$G3 p3-coverage"
  "p3-measures|$G3 p3-measures"
  "p3-spikes|$G3 p3-spikes"
  "p3-mutants|$G3 p3-mutants --jobs $JOBS"
  "p3-fuzz|$G3 p3-fuzz --runs 100000000"
  # ---- Part 4, The Erasure: gates
  "p4-crash|$G4 p4-crash --data nq-10k --all-seeds --jobs $JOBS"
  "p4-replay|$G4 p4-replay --data nq-100k --all-seeds --jobs 2"
  "p4-attacks|$G4 p4-attacks --data nq-10k --all-seeds --jobs 5"
  "p4-forensics|$G4 p4-forensics --data nq-100k --all-seeds --locked-memory"
  "p4-checks|$G4 p4-checks"
  "p4-coverage|$G4 p4-coverage"
  "p4-mutants|$G4 p4-mutants --jobs $JOBS"
  "p4-fuzz|$G4 p4-fuzz --runs 100000000"
  # ---- Part 4: measures
  "p4-ex6|$G4 p4-ex6 --data nq-100k --all-seeds --locked-memory"
  "p4-quant-recall|$G4 p4-quant-recall"
  "p4-ex7-nq-100k|$G4 p4-ex7 --data nq-100k --all-seeds"
  "p4-ex7-nq-1m|$G4 p4-ex7 --data nq-1m --all-seeds"
  "p4-ex8|$G4 p4-ex8 --seed 42"
)
fi

in_list() { # $1 = word, $2 = space-separated list
  case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}
# last_rc LOG: the N of a final "rc=N" line, or nothing when the step never finished.
last_rc() { [ -f "$1" ] && tail -n 1 "$1" | sed -n 's/^rc=\([0-9][0-9]*\)$/\1/p'; }

# Reject unknown names in ONLY / SKIP so a typo does not silently run nothing.
names=" "; for s in "${STEPS[@]}"; do names+="${s%%|*} "; done
for n in ${ONLY:-} ${SKIP:-}; do
  in_list "$n" "$names" || { echo "unknown step '$n'; steps are:$names"; exit 2; }
done

echo "run-all start $(date -Is) on $(hostname): nproc=$NPROC JOBS=$JOBS commit=$(git rev-parse --short HEAD 2>/dev/null) mock=${MOCK:-0}"
echo "ulimit -l = $(ulimit -l)"
[ "${MOCK:-0}" = 1 ] || [ "$(ulimit -l)" = "unlimited" ] \
  || echo "WARNING: ulimit -l is not unlimited; the --locked-memory steps will fail (HPC_GUIDE.md: root-setup.sh)"
echo "== $(date -Is) run-all start nproc=$NPROC JOBS=$JOBS commit=$(git rev-parse --short HEAD 2>/dev/null)" >>"$SUMMARY"

failed=0; interrupted=0
for s in "${STEPS[@]}"; do
  name=${s%%|*}; cmd=${s#*|}
  log="traces/$PREFIX-$name.log"
  if [ -n "${ONLY:-}" ] && ! in_list "$name" "$ONLY"; then continue; fi
  if in_list "$name" "${SKIP:-}"; then
    echo "$(date -Is) $name SKIPPED (SKIP)" | tee -a "$SUMMARY"; continue
  fi
  prev=$(last_rc "$log")
  if [ "${FORCE:-0}" != 1 ] && [ -n "$prev" ] && [ "$prev" -lt 128 ]; then
    if [ "$prev" = 0 ]; then
      echo "$(date -Is) $name SKIPPED (passed earlier)" | tee -a "$SUMMARY"
    else
      echo "$(date -Is) $name SKIPPED (finished earlier with rc=$prev; never rerun, Build §2.5)" | tee -a "$SUMMARY"
      failed=1
    fi
    continue
  fi
  # An interrupted p3-crash continues its campaign when its run-state file is there.
  if [ "$name" = p3-crash ] && [ -f "$log" ] && [ "${FORCE:-0}" != 1 ] \
     && [ -f traces/p3-crash-nq-10k-run.json ]; then
    cmd="$cmd --resume"
  fi
  [ -f "$log" ] && mv "$log" "$log.prev"
  echo "$(date -Is) $name START: $cmd"
  t0=$(date +%s)
  {
    echo "# step $name, $(date -Is), commit $(git rev-parse HEAD 2>/dev/null)"
    echo "# cmd: $cmd"
  } >"$log"
  # shellcheck disable=SC2086  # the command is a word list by design
  $cmd >>"$log" 2>&1 </dev/null
  rc=$?
  echo "rc=$rc" >>"$log"
  dt=$(( $(date +%s) - t0 ))
  line="$(date -Is) $name rc=$rc duration=$(printf '%dh%02dm%02ds' $((dt/3600)) $((dt%3600/60)) $((dt%60))) log=$log"
  echo "$line" | tee -a "$SUMMARY"
  if [ "$rc" -ge 128 ]; then interrupted=1
  elif [ "$rc" -ne 0 ]; then failed=1; fi
done

if [ "$interrupted" = 1 ]; then code=3; elif [ "$failed" = 1 ]; then code=1; else code=0; fi
echo "== $(date -Is) run-all end failed=$failed interrupted=$interrupted" | tee -a "$SUMMARY"
exit $code
