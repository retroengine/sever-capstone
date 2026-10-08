#!/usr/bin/env bash
# Queue job: P2-T11, once, after the crash gate (so nothing else competes for the CPU while it
# times operations). A measure is recorded as found and never rerun: if a ledger entry for it
# already exists (RECORDED or ERROR), this does nothing.
set -u
cd "$(dirname "$0")/../.."
export PYTHONHASHSEED=0 PYTHONPATH=python
while pgrep -f "sever_testkit_p2[.]gates p2-crash" > /dev/null; do sleep 60; done
if grep -F '"command":"gates p2-measures --data nq-100k --seed 42"' docs/RUN_LEDGER.jsonl | grep -qE '"outcome":"(RECORDED|ERROR)"'; then
  echo "already recorded"; exit 0
fi
exec uv run --no-sync python -m sever_testkit_p2.gates p2-measures --data nq-100k --seed 42
