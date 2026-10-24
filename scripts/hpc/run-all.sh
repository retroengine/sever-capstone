#!/usr/bin/env bash
# scripts/hpc/run-all.sh — runs every pre-registered Part 3 and Part 4 gate and measure once, in
# sequence, in WSL2 Ubuntu on the college HPC workstation prepared by scripts/hpc/setup.sh (DB-111;
# Build 3-4 §1.9 P3-T1…T13, §2.10 P4-T1…T15). The one guide is scripts/hpc/HPC_GUIDE.md.
#
# Detached; launch from the repo root (HPC_GUIDE.md step 9) and keep the Ubuntu window open:
#   mkdir -p traces && setsid nohup bash scripts/hpc/run-all.sh > traces/hpc-run.out 2>&1 &
#
# Output:
#   traces/hpc-<step>.log   the step's full output, ending with a line "rc=N"
#   traces/hpc-summary.log  one line per step: time, step, rc, duration (appended, never rewritten)
#   The gates themselves write the run ledger and results/ (never edit those by hand, CLAUDE.md §6.4).
# A failing step does not stop the rest; the script exits 1 if any step failed.
#
# Environment:
#   JOBS="N"           parallel jobs for the memory-heavy steps (default nproc/4, at least 2)
#   ONLY="a b"         run only these steps (names as in the STEPS list below)
#   SKIP="a b"         skip these steps
#   FORCE=1            re-run a step even if its log already ends with rc=0 (default: resume, skip it)
#
# Expected duration: roughly 1-2 days in total on 32 cores (the crash campaigns, the mutation runs
# and the two 10^8-run fuzz campaigns dominate). Gates versus measures (Build §2.5): a measure is
# recorded as found; never re-run one because of its value.
set -u
cd "$(dirname "$0")/../.."
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"   # setsid/nohup may not carry a login PATH
export PYTHONHASHSEED=0 PYTHONPATH=python
G3="uv run --no-sync python -m sever_testkit_p3.gates"
G4="uv run --no-sync python -m sever_testkit_p4.gates"
NPROC=$(nproc)
JOBS=${JOBS:-$(( NPROC / 4 ))}
[ "$JOBS" -ge 2 ] 2>/dev/null || JOBS=2
mkdir -p traces
SUMMARY=traces/hpc-summary.log

# name | command (word-split on purpose; no arguments contain spaces)
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

in_list() { # $1 = word, $2 = space-separated list
  case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

# Reject unknown names in ONLY / SKIP so a typo does not silently run nothing.
names=" "; for s in "${STEPS[@]}"; do names+="${s%%|*} "; done
for n in ${ONLY:-} ${SKIP:-}; do
  in_list "$n" "$names" || { echo "unknown step '$n'; steps are:$names"; exit 2; }
done

echo "run-all start $(date -Is) on $(hostname): nproc=$NPROC JOBS=$JOBS commit=$(git rev-parse --short HEAD 2>/dev/null)"
echo "ulimit -l = $(ulimit -l)"
[ "$(ulimit -l)" = "unlimited" ] || echo "WARNING: ulimit -l is not unlimited; the --locked-memory steps will fail (HPC_GUIDE.md step 9: sudo prlimit)"
echo "== $(date -Is) run-all start nproc=$NPROC JOBS=$JOBS commit=$(git rev-parse --short HEAD 2>/dev/null)" >>"$SUMMARY"

failed=0
for s in "${STEPS[@]}"; do
  name=${s%%|*}; cmd=${s#*|}
  log="traces/hpc-$name.log"
  if [ -n "${ONLY:-}" ] && ! in_list "$name" "$ONLY"; then continue; fi
  if in_list "$name" "${SKIP:-}"; then
    echo "$(date -Is) $name SKIPPED (SKIP)" | tee -a "$SUMMARY"; continue
  fi
  if [ "${FORCE:-0}" != 1 ] && [ -f "$log" ] && [ "$(tail -n 1 "$log")" = "rc=0" ]; then
    echo "$(date -Is) $name SKIPPED (already rc=0; FORCE=1 to re-run)" | tee -a "$SUMMARY"; continue
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
  [ "$rc" -eq 0 ] || failed=1
done

echo "== $(date -Is) run-all end failed=$failed" | tee -a "$SUMMARY"
exit $failed
