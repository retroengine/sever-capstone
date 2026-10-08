#!/usr/bin/env bash
# A crash-safe job queue for long runs (gates, measures). One job at a time, oldest first.
#
#   scripts/jobq.sh add NAME 'command'  ['resume command']   queue a job
#   scripts/jobq.sh list                                      queued / running / done / failed
#   scripts/jobq.sh run                                       the worker (the systemd service runs it)
#
# Jobs live in jobs/ (not in git): queue/, running/, done/, failed/, logs/. A job that was running
# when WSL stopped (shutdown, reboot) is found in running/ when the worker starts again and is run
# again; if it has a resume command, that runs instead (e.g. `gates p2-crash … --resume`). Sleep
# needs nothing: the whole VM pauses and every process continues on wake.
#
# Install once (user service, starts with WSL; see docs/PROGRESS.md):
#   mkdir -p ~/.config/systemd/user && cp scripts/sever-jobq.service ~/.config/systemd/user/
#   systemctl --user daemon-reload && systemctl --user enable --now sever-jobq
set -u
cd "$(dirname "$0")/.."
J=jobs
mkdir -p $J/queue $J/running $J/done $J/failed $J/logs

add() { # NAME COMMAND [RESUME]
  local id; id="$(date -u +%Y%m%dT%H%M%S)-$1"
  { echo "CMD=$(printf %q "$2")"; echo "RESUME=$(printf %q "${3:-}")"; echo "ATTEMPTS=0"; } > "$J/queue/$id"
  echo "queued $id"
}

list() {
  local d; for d in running queue done failed; do
    echo "== $d"; ls "$J/$d" 2>/dev/null | sed 's/^/  /'
  done
}

run_one() { # a job file in running/
  local f=$1 id; id=$(basename "$f")
  # shellcheck disable=SC1090
  . "$f"
  ATTEMPTS=$((ATTEMPTS + 1))
  sed -i "s/^ATTEMPTS=.*/ATTEMPTS=$ATTEMPTS/" "$f"
  local cmd=$CMD
  if [ "$ATTEMPTS" -gt 1 ] && [ -n "$RESUME" ]; then cmd=$RESUME; fi
  echo "$(date -u +%FT%TZ) start $id attempt $ATTEMPTS: $cmd" >> "$J/logs/$id.log"
  ( export PYTHONHASHSEED=0 PYTHONPATH=python; bash -c "$cmd" ) >> "$J/logs/$id.log" 2>&1
  local rc=$?
  echo "$(date -u +%FT%TZ) end $id rc=$rc" >> "$J/logs/$id.log"
  if [ $rc -eq 0 ]; then mv "$f" "$J/done/"; else mv "$f" "$J/failed/"; fi
}

worker() {
  exec 9> "$J/.worker.lock"
  flock -n 9 || { echo "another worker is running"; exit 0; }
  while true; do
    # Interrupted jobs first (left in running/ by a stop), then the oldest queued one.
    local next; next=$(ls "$J/running" 2>/dev/null | sort | head -1)
    if [ -z "$next" ]; then
      next=$(ls "$J/queue" 2>/dev/null | sort | head -1)
      [ -n "$next" ] && mv "$J/queue/$next" "$J/running/"
    fi
    if [ -n "$next" ]; then run_one "$J/running/$next"; else sleep 30; fi
  done
}

case "${1:-}" in
  add) shift; add "$@" ;;
  list) list ;;
  run) worker ;;
  *) echo "usage: scripts/jobq.sh add NAME CMD [RESUME] | list | run"; exit 2 ;;
esac
