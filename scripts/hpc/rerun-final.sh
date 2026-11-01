#!/usr/bin/env bash
# DB-116: after the November bug hunt changed sever-log, sever-cert and sever-erasure, the gates that
# reach those crates run once more on the final commit, one at a time, at the DB-113 sizes and with
# the commands of scripts/hpc/steps.sh. Logs: traces/final-<step>.log, each ending "rc=N".
#   scripts/hpc/rerun-final.sh            run every step whose log has no rc= line yet (resumable)
set -u
cd "$(dirname "$0")/../.."
export PYTHONHASHSEED=0 PYTHONPATH=python CARGO_NET_OFFLINE=true
G3="uv run --no-sync python -m sever_testkit_p3.gates"
G4="uv run --no-sync python -m sever_testkit_p4.gates"
topic=$(cat ~/longrun/ntfy-topic 2>/dev/null || true)
note() { [ -n "$topic" ] && curl -s -m 10 -d "$1" "https://ntfy.sh/$topic" >/dev/null || true; }
steps=(
  "p3-checks|$G3 p3-checks"
  "p4-checks|$G4 p4-checks"
  "p3-coverage|$G3 p3-coverage"
  "p4-coverage|$G4 p4-coverage"
  "p3-spikes|$G3 p3-spikes"
  "p3-attacks|$G3 p3-attacks --data nq-10k --all-seeds --jobs 2"
  "p4-attacks|$G4 p4-attacks --data nq-10k --all-seeds --jobs 2"
  "p4-replay|$G4 p4-replay --data nq-10k --all-seeds --jobs 3"
  "p4-crash-a|$G4 p4-crash --data nq-10k --seed 42 --seed 123 --seed 777 --jobs 3 --crash-from 17694 --limit-ops 17994"
  "p4-crash-b|$G4 p4-crash --data nq-10k --seed 2024 --seed 9999 --jobs 2 --crash-from 18700 --limit-ops 19000"
  "p3-mutants|env CARGO_BUILD_JOBS=2 $G3 p3-mutants --jobs 3"
  "p4-mutants|env CARGO_BUILD_JOBS=2 $G4 p4-mutants --jobs 4"
  "p3-replay|$G3 p3-replay --data nq-100k --all-seeds --jobs 2"
  "p3-crash|$G3 p3-crash --data nq-10k --all-seeds --jobs 5"
)
for s in "${steps[@]}"; do
  name=${s%%|*}; cmd=${s#*|}; log=traces/final-$name.log
  if [ -f "$log" ] && grep -q '^rc=' "$log"; then continue; fi
  { echo "# step $name, $(date -u +%FT%TZ), commit $(git rev-parse HEAD)"; echo "# cmd: $cmd"; } > "$log"
  $cmd >> "$log" 2>&1
  rc=$?
  echo "rc=$rc" >> "$log"
  note "SEVER-DB final rerun: $name rc=$rc"
done
note "SEVER-DB final rerun: all steps finished"
echo DONE > traces/final-DONE
