#!/bin/bash
# The interim crash campaign (DB-94): resume the run from op 17,000 if one was interrupted, else start it.
cd "$(dirname "$0")/../.." || exit 1
export PYTHONHASHSEED=0 PYTHONPATH=python
G="uv run python -m sever_testkit_p3.gates p3-crash --data nq-10k --all-seeds --jobs 5 --crash-from 17000"
$G --resume; rc=$?
if [ "$rc" = 3 ]; then $G; rc=$?; fi
exit $rc
