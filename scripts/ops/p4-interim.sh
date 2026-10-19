#!/bin/bash
# Part 4 interim crash campaign (DB-94; the full P4-T3 runs on the VM): the final build through
# sever-crashkit-p4, crash points on both disks in three windows of each seed's trace, so every
# kind of operation is crashed: single deletions (from op 17,000), multi-group deletions (from op
# 17,844) and the inserts after them (from op 18,860), WINDOW operations each, five seeds.
# A Part 4 run holds both disks' snapshots (2-3.5 GB), so at most JOBS run at once (five at once
# ran out of memory on 19 Oct). A short smoke run goes first. Each run resumes from its saved
# progress. Results: traces/p4-interim/p4i-*; verdict: traces/p4-interim/p4i-summary.json.
set -u
R=$(cd "$(dirname "$0")/../.." && pwd); T=$R/traces/p4-interim; mkdir -p "$T"
cd "$R" || exit 1
WINDOW=${WINDOW:-80}; JOBS=${JOBS:-2}
C=$(git rev-parse --short=12 HEAD)
nice -n 10 cargo build -q --release -j 2 -p sever-crashkit-p4 --target-dir target/gate-p4-$C || exit 1
K=$R/target/gate-p4-$C/release/sever-crashkit-p4
run() { # seed out from limit
  local p=$2.progress; local res=(); [ -f "$p" ] && res=(--resume 1)
  nice -n 10 "$K" campaign --oracle "$R/traces/p2-oracle-nq-10k-seed$1.jsonl" --root "$R" --out "$2" \
    --seed "$1" --method snapshot --compare-every 50 --crash-from "$3" --limit-ops "$4" "${res[@]}"
}
finished() { tail -n 1 "$1" 2>/dev/null | grep -q '"t":"summary"'; }
if ! finished "$T/p4i-smoke.jsonl"; then
  run 42 "$T/p4i-smoke.jsonl" 10000 10040 > "$T/p4i-smoke.log" 2>&1 || { echo "smoke failed"; exit 1; }
fi
for s in 42 123 777 2024 9999; do
  for w in d:17000 x:17844 i:18860; do
    out=$T/p4i-crash-seed$s-${w%%:*}.jsonl; from=${w#*:}
    finished "$out" && continue
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n; done
    run "$s" "$out" "$from" $((from + WINDOW)) > "${out%.jsonl}.log" 2>&1 &
  done
done
wait
T=$T python3 - <<'PY'
import glob
import json
import os

T = os.environ["T"]
out = {}
for f in sorted(glob.glob(f"{T}/p4i-smoke.jsonl") + glob.glob(f"{T}/p4i-crash-seed*-?.jsonl")):
    last = open(f).read().rstrip("\n").rsplit("\n", 1)[-1]
    try:
        s = json.loads(last)
    except ValueError:
        s = {"error": "no summary"}
    out[os.path.basename(f)] = s
bad = ("main_mismatches", "not_oracle_state", "refusals", "bad_retries", "double_mismatches",
       "orphaned_leaves", "rolled_back_certificates", "bad_certificates", "method_mismatches",
       "stale_key_slots", "unreadable_records")
ok = len(out) == 16 and all(
    s.get("t") == "summary" and all(s.get(k) == 0 for k in bad)
    and s.get("key_loss_refused") == s.get("key_loss_injected")
    for s in out.values()
)
json.dump({"pass": ok, "runs": out}, open(f"{T}/p4i-summary.json", "w"), indent=1)
print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
PY
