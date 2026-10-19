#!/bin/bash
# Starts (or resumes) the long Part 3 gates, detached from any terminal or Claude session:
#   setsid nohup bash scripts/ops/p3-gates.sh > traces/gates.out 2>&1 &
# The crash gate resumes from its saved progress when it can (exit 3 from --resume means there
# is nothing to resume, so it starts fresh). The replay has no resume and starts fresh.
# Memory (WSL 10 GB): five crash processes take ~0.5 GB each and one replay up to ~3.5 GB, so the
# replay runs one seed at a time (two at once ran out of memory on 18 Oct 22:34 and restarted WSL).
# The replay is made the kernel's first choice if memory still runs out, so WSL itself survives.
cd "$(dirname "$0")/../.." || exit 1
export PYTHONHASHSEED=0 PYTHONPATH=python
G="uv run python -m sever_testkit_p3.gates"

(
  $G p3-crash --data nq-10k --all-seeds --jobs 5 --resume >> traces/gate-p3-crash.log 2>&1
  rc=$?
  if [ "$rc" = 3 ]; then
    $G p3-crash --data nq-10k --all-seeds --jobs 5 >> traces/gate-p3-crash.log 2>&1
    rc=$?
  fi
  echo "rc=$rc" >> traces/gate-p3-crash.log
) &

(
  sleep 120 # let the crash gate build the kit first
  echo 800 > /proc/self/oom_score_adj # inherited by the replay processes
  $G p3-replay --data nq-100k --all-seeds --jobs 1 > traces/gate-p3-replay.log 2>&1
  echo "rc=$?" >> traces/gate-p3-replay.log
) &

wait
