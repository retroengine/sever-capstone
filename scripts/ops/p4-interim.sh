#!/bin/bash
# Part 4 interim crash campaign (DB-94 style; the full P4-T3 runs on the VM): the final build
# through sever-crashkit-p4, crash points on both disks from op 17,000 (single deletions, every
# multi-group deletion, the inserts after), five seeds. A short smoke run goes first.
# Resumes from saved progress. Results: traces/p4-interim/p4i-*.
set -u
R=$(cd "$(dirname "$0")/../.." && pwd); W=$R; T=$R/traces/p4-interim; mkdir -p $T
cd $W || exit 1
C=$(git rev-parse --short=12 HEAD)
nice -n 10 cargo build -q --release -j 2 -p sever-crashkit-p4 --target-dir target/gate-p4-$C || exit 1
K=$W/target/gate-p4-$C/release/sever-crashkit-p4
run() { # seed out from limit
  local p=$2.progress; local res=(); [ -f "$p" ] && res=(--resume 1)
  "$K" campaign --oracle $R/traces/p2-oracle-nq-10k-seed$1.jsonl --root $R --out $2 --seed $1 \
    --method snapshot --compare-every 50 --crash-from $3 ${4:+--limit-ops $4} "${res[@]}"
}
if ! tail -n 1 $T/p4i-smoke.jsonl 2>/dev/null | grep -q '"t":"summary"'; then
  run 42 $T/p4i-smoke.jsonl 10000 10040 > $T/p4i-smoke.log 2>&1 || { echo "smoke failed"; exit 1; }
fi
for s in 42 123 777 2024 9999; do
  out=$T/p4i-crash-seed$s.jsonl
  tail -n 1 $out 2>/dev/null | grep -q '"t":"summary"' || run $s $out 17000 > $T/p4i-crash-seed$s.log 2>&1 &
done
wait
T=$T python3 - <<'PY'
import json, glob, os
T = os.environ["T"]
out = {}
for f in sorted(glob.glob(f"{T}/p4i-*.jsonl")):
    last = open(f).read().rstrip("\n").rsplit("\n", 1)[-1]
    try:
        s = json.loads(last)
    except ValueError:
        s = {"error": "no summary"}
    out[os.path.basename(f)] = s
bad = ("main_mismatches","not_oracle_state","refusals","bad_retries","double_mismatches","orphaned_leaves",
       "rolled_back_certificates","bad_certificates","method_mismatches","stale_key_slots","unreadable_records")
ok = all(s.get("t") == "summary" and all(s.get(k) == 0 for k in bad)
         and s.get("key_loss_refused") == s.get("key_loss_injected") for s in out.values())
json.dump({"pass": ok, "runs": out}, open(f"{T}/p4i-summary.json", "w"), indent=1)
print("PASS" if ok else "FAIL")
PY
