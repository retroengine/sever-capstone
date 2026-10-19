#!/bin/bash
# Runs the rest of the Part 3 gate list once scripts/ops/p3-gates.sh (crash + replay) has finished,
# without any Claude session:  setsid nohup bash scripts/ops/p3-gates-after.sh > traces/gates-after.out 2>&1 &
# Each step logs to traces/gate-<step>.log and ends with "rc=N". A failing step does not stop the rest.
cd "$(dirname "$0")/../.." || exit 1
export PYTHONHASHSEED=0 PYTHONPATH=python
G="uv run python -m sever_testkit_p3.gates"
while pgrep -f "bash .*p3-gates\.sh" > /dev/null || pgrep -x sever-crashkit- > /dev/null; do sleep 60; done
echo "$(date -u +%FT%TZ) crash+replay finished; starting the rest" >> traces/gate-after.log
step() { name=$1; shift; echo "$(date -u +%FT%TZ) start $name" >> traces/gate-after.log
  nice -n 10 $G "$@" > "traces/gate-$name.log" 2>&1; rc=$?
  echo "rc=$rc" >> "traces/gate-$name.log"; echo "$(date -u +%FT%TZ) $name rc=$rc" >> traces/gate-after.log; }
step p3-attacks  p3-attacks --data nq-10k --all-seeds --jobs 2
step p3-checks   p3-checks
step p3-coverage p3-coverage
step p3-measures p3-measures
step p3-spikes   p3-spikes
step p3-mutants  p3-mutants --jobs 4
step p3-fuzz     p3-fuzz --runs 100000000
echo "$(date -u +%FT%TZ) all done" >> traces/gate-after.log
