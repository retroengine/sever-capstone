#!/bin/bash
# Interim Part 3 checks on the laptop (~5 h), while the full pre-registered gates wait for the VM
# run at the end (owner, 18 Oct 2026):  setsid nohup bash scripts/ops/p3-interim.sh > traces/interim.out 2>&1 &
# Crash points from op 17,000 (single deletions, every multi-group deletion, the inserts after),
# the nq-100k replay of seed 42, then the shorter gates. Progress: traces/gate-interim.log
cd "$(dirname "$0")/../.." || exit 1
export PYTHONHASHSEED=0 PYTHONPATH=python
G="uv run python -m sever_testkit_p3.gates"
log() { echo "$(date -u +%FT%TZ) $*" >> traces/gate-interim.log; }
log "start"
(
  $G p3-crash --data nq-10k --all-seeds --jobs 5 --crash-from 17000 > traces/gate-p3-crash-interim.log 2>&1
  rc=$?; echo "rc=$rc" >> traces/gate-p3-crash-interim.log; log "p3-crash (from op 17000) rc=$rc"
  step() { name=$1; shift; log "start $name"; nice -n 10 $G "$@" > "traces/gate-$name.log" 2>&1; rc=$?
    echo "rc=$rc" >> "traces/gate-$name.log"; log "$name rc=$rc"; }
  step p3-attacks  p3-attacks --data nq-10k --all-seeds --jobs 2
  step p3-checks   p3-checks
  step p3-coverage p3-coverage
  step p3-measures p3-measures
  step p3-spikes   p3-spikes
  step p3-fuzz     p3-fuzz --runs 10000000
) &
(
  sleep 120
  echo 800 > /proc/self/oom_score_adj
  $G p3-replay --data nq-100k --seed 42 --jobs 1 > traces/gate-p3-replay-interim.log 2>&1
  rc=$?; echo "rc=$rc" >> traces/gate-p3-replay-interim.log; log "p3-replay nq-100k seed 42 rc=$rc"
) &
wait
log "all done"
