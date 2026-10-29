#!/usr/bin/env bash
# scripts/hpc/on-exit.sh INSTANCE — ExecStopPost of sever-hpc@INSTANCE. Reads why the run ended
# (systemd's EXIT_CODE / EXIT_STATUS / SERVICE_RESULT), marks a finished run DONE and alerts.
# run-all.sh exits 0 (all passed), 1 (finished, some step failed: never rerun), 3 (a step was
# interrupted: the unit restarts and the run continues). Anything else is a crash: the unit
# restarts it with backoff until its start limit, then sever-hpc-alert@ reports it.
set -u
. "$(dirname "$0")/lib.sh"
load_instance "${1:-real}" || exit 0
code=${EXIT_CODE:-}; status=${EXIT_STATUS:-}; result=${SERVICE_RESULT:-}
summary="$REPO/traces/$PREFIX-summary.log"
# Preflight refused this start (it already alerted): run-all never ran, nothing to classify.
[ -f "$STATE/running" ] || exit 0
rm -f "$STATE/running"
# The steps whose final result is a failure (rc 1 … 127 on the last line of their log); a step that
# was interrupted (rc ≥ 128, e.g. an out-of-memory kill, DB-113) and then passed is not one.
failed_steps() {
  local f r
  for f in "$REPO"/traces/"$PREFIX"-*.log; do
    [ -f "$f" ] && [ "$f" != "$summary" ] || continue
    r=$(tail -n 1 "$f" | sed -n 's/^rc=\([0-9][0-9]*\)$/\1/p')
    [ -n "$r" ] && [ "$r" -ge 1 ] && [ "$r" -lt 128 ] && basename "$f" .log | sed "s/^$PREFIX-//"
  done | tr '\n' ' '
}

case "$code/$status" in
  # The alert first, then DONE: whoever waits for DONE finds the alert already written.
  exited/0)
    notify done "finished: every step passed. Collect the results (HPC_GUIDE.md, Finish)."
    date -u +%FT%TZ >"$STATE/DONE" ;;
  exited/1)
    notify done "finished: steps failed and are not rerun (Build §2.5): $(failed_steps). Collect the logs (HPC_GUIDE.md, Finish)."
    date -u +%FT%TZ >"$STATE/DONE" ;;
  exited/3)
    notify restart "a step was interrupted (killed or out of memory); the run restarts and continues" ;;
  killed/TERM|killed/INT)
    notify stopped "run stopped ($status); start it again with launch.sh $INSTANCE" ;;
  *)
    notify crash "run ended abnormally (EXIT_CODE=$code EXIT_STATUS=$status RESULT=$result); systemd restarts it with backoff" ;;
esac
exit 0
