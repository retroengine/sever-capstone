#!/usr/bin/env bash
# Fair testing (docs/FAIR_TESTING.md). Every AI session runs fresh, in a bwrap clean room.
#   scripts/fair.sh doctor                 sandbox, canary and credential check (no session)
#   scripts/fair.sh run 2 [--module NAME]  one run: write, seal, measure, triage, plant, score, audit
#   scripts/fair.sh cycle 2                run → fix (FT-9) → run again, up to fix_rounds
#   scripts/fair.sh dry-run 2              every stage with offline stub agents (plumbing only)
#   scripts/fair.sh resume RUN_ID          continue an interrupted run
#   scripts/fair.sh fix RUN_ID             fix one run's findings in a new worktree and branch
#   scripts/fair.sh verify-freeze 2        FT-10, used by scripts/freeze.sh
#   scripts/fair.sh check                  CI: kept clean-room tests match their manifests
# Add --bg before the command to run it detached (log in ~/.sever-fair/logs/).
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONHASHSEED=0 PYTHONPATH=python
if [ "${1:-}" = "--bg" ]; then
  shift
  mkdir -p ~/.sever-fair/logs
  log=~/.sever-fair/logs/$(date -u +%Y%m%dT%H%M%SZ)-$1.log
  nohup uv run --no-sync python -m sever_fair "$@" >"$log" 2>&1 &
  echo "started in the background (pid $!); log: $log"
  exit 0
fi
exec uv run --no-sync python -m sever_fair "$@"
