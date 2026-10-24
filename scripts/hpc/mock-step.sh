#!/usr/bin/env bash
# scripts/hpc/mock-step.sh NAME SECONDS — a fake run-all step for the failure drills (MOCK=1).
# It burns one core for SECONDS, printing a progress line every second. Drill behaviour is set by
# files in $LONGRUN/drill/ (scripts/hpc/drills.sh writes them):
#   fail.NAME        exit 1 (a gate that finished and failed)
#   killrun.NAME     kill -9 run-all once, mid-step (the file is removed first)
#   killrun-always   kill -9 run-all every time (a crash loop)
#   hang.NAME        stop itself (SIGSTOP) mid-step once: a hung process
set -u
name=$1; secs=$2
D=${LONGRUN:-$HOME/longrun}/drill
half=$(( secs / 2 ))
for ((i = 1; i <= secs; i++)); do
  end=$(( $(date +%s) + 1 ))
  while [ "$(date +%s)" -lt "$end" ]; do :; done
  echo "$name: $i/$secs"
  if [ "$i" -eq "$half" ]; then
    if [ -f "$D/killrun-always" ] || { [ -f "$D/killrun.$name" ] && rm -f "$D/killrun.$name"; }; then
      echo "$name: drill: kill -9 run-all"; kill -9 "$PPID"
    fi
    if [ -f "$D/hang.$name" ]; then rm -f "$D/hang.$name"; echo "$name: drill: hang"; kill -STOP $$; fi
  fi
done
[ -f "$D/fail.$name" ] && { echo "$name: drill: FAIL"; exit 1; }
echo "$name: PASS"
