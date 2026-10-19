#!/bin/bash
# SEVER-DB side jobs (systemd user service sever-sidejobs; starts with WSL): every job file in
# jobs/side/ runs beside the main queue's worker. scripts/ops/side-job.sh locks each job,
# so at most one copy runs; a job that was running when WSL stopped runs again on the next start.
cd "$(dirname "$0")/../.." || exit 1
mkdir -p jobs/side
while true; do
  for f in jobs/side/*; do
    [ -f "$f" ] && setsid "$PWD/scripts/ops/side-job.sh" "$(basename "$f")" > /dev/null 2>&1 < /dev/null &
  done
  sleep 30
done
