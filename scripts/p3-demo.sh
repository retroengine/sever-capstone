#!/usr/bin/env bash
# Part 3 demo in one command (Build 3-4 §1.10):
#   scripts/p3-demo.sh                      # nq-10k, seed 42 (needs the P0 data in datasets/)
#   scripts/p3-demo.sh --data synthetic     # offline: golden fixture only, no data needed
# Builds the SDK's native module, the verifier and the auditor, then runs `sever-demo-p3 receipt`:
# inserts through the SDK, one deletion verified by sever-verify in a separate directory, a flipped
# byte rejected, a delete_user whose certificates chain, and sever-audit over the log export.
# Writes artefacts/demo/receipt-<data>-seed<seed>.json; exits non-zero if any step fails.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONHASHSEED=0 PYTHONPATH=python
data=nq-10k seed=42
while [ $# -gt 0 ]; do
  case "$1" in
    --data) data=$2; shift 2 ;;
    --seed) seed=$2; shift 2 ;;
    *) echo "usage: scripts/p3-demo.sh [--data nq-10k|synthetic] [--seed N]"; exit 2 ;;
  esac
done
uv sync --locked -q
uv run --no-sync maturin develop -q --release --uv -m crates/sever-py-p3/Cargo.toml
if [ "$data" != synthetic ]; then
  (cd datasets && sha256sum --quiet -c MANIFEST.sha256) || { echo "P0 data missing or changed"; exit 1; }
  [ -f "artefacts/partition-seed$seed.svp" ] || uv run --no-sync python -m sever_partition.build --seed "$seed"
fi
uv run --no-sync python -m sever_demo_p3.receipt receipt --data "$data" --seed "$seed" --root . --work artefacts/demo
