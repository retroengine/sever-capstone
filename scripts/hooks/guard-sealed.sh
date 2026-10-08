#!/usr/bin/env bash
# PreToolUse hook (FT-3, FT-9, FT-10): Claude's edit tools may not touch sealed or generated files.
# The CI checks (fair-check, freeze-guard) catch any other route; this stops the obvious one early.
path=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("file_path",""))')
case "$path" in
  */tests/cleanroom/*|*/docs/audit/*|*/freeze/*|*/results/*|*/docs/RUN_LEDGER.jsonl)
    echo "blocked: $path is sealed or generated (docs/FAIR_TESTING.md FT-3/FT-10)" >&2; exit 2 ;;
esac
exit 0
