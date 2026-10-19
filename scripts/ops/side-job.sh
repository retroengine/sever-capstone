#!/bin/bash
# Runs one job file from jobs/side/ beside the queue's worker (same log format); done/ or failed/.
# Holds jobs/side-lock/<id> while it runs, so the side-jobs service never starts a second copy.
cd "$(dirname "$0")/../.." || exit 1
id=$1; f=jobs/side/$id
mkdir -p jobs/side-lock
exec 9> "jobs/side-lock/$id"
flock -n 9 || exit 0
[ -f "$f" ] || exit 0
. "$f"
echo "$(date -u +%FT%TZ) start $id (side): $CMD" >> jobs/logs/$id.log
( export PYTHONHASHSEED=0 PYTHONPATH=python; bash -c "$CMD" ) 9>&- >> jobs/logs/$id.log 2>&1
rc=$?
echo "$(date -u +%FT%TZ) end $id rc=$rc" >> jobs/logs/$id.log
if [ $rc -eq 0 ]; then mv "$f" jobs/done/; else mv "$f" jobs/failed/; fi
