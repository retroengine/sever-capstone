#!/usr/bin/env bash
# Queue job: make sure gates p2-crash (nq-10k, five seeds) has a final ledger entry.
# Waits for a run already in progress; otherwise resumes an interrupted run (exit 3 from --resume
# means there is nothing to resume: start a fresh run). A finished run, PASS or FAIL, is never
# run again here: a gate is not rerun until it passes.
set -u
cd "$(dirname "$0")/../.."
export PYTHONHASHSEED=0 PYTHONPATH=python
while pgrep -f "sever_testkit_p2[.]gates p2-crash" > /dev/null; do sleep 60; done
last=$(grep -F '"command":"gates p2-crash --data nq-10k --seeds [42, 123, 777, 2024, 9999]' docs/RUN_LEDGER.jsonl | tail -1)
case "$last" in
  *'"outcome":"PASS"'*|*'"outcome":"FAIL"'*) echo "already finished"; exit 0 ;;
esac
uv run --no-sync python -m sever_testkit_p2.gates p2-crash --data nq-10k --all-seeds --jobs 3 --resume
rc=$?
if [ $rc -eq 3 ]; then
  uv run --no-sync python -m sever_testkit_p2.gates p2-crash --data nq-10k --all-seeds --jobs 3
  rc=$?
fi
exit $rc
