#!/usr/bin/env bash
# Part 2 demo in one command (Build §5.9, §2.9 "the demo runs from a clean clone with one command"):
#   scripts/p2-demo.sh                      # nq-10k, seed 42 (needs the P0 data in datasets/)
#   scripts/p2-demo.sh --data synthetic     # offline: golden fixture only, no data needed
# Builds what is missing first (the partition artefact for the seed, the ID export), then runs
# `sever-demo-p2 durable`: a multi-group delete_user interrupted by a crash before and after its
# commit point, on a simulated disk and with a real SIGKILL. Writes
# artefacts/demo/durable-<data>-seed<seed>.json; exits non-zero if any deletion was partial.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONHASHSEED=0 PYTHONPATH=python
data=nq-10k seed=42
while [ $# -gt 0 ]; do
  case "$1" in
    --data) data=$2; shift 2 ;;
    --seed) seed=$2; shift 2 ;;
    *) echo "usage: scripts/p2-demo.sh [--data nq-10k|synthetic] [--seed N]"; exit 2 ;;
  esac
done
uv sync --locked -q
if [ "$data" != synthetic ]; then
  (cd datasets && sha256sum --quiet -c MANIFEST.sha256) || { echo "P0 data missing or changed"; exit 1; }
  [ -f "artefacts/partition-seed$seed.svp" ] || uv run --no-sync python -m sever_partition.build --seed "$seed"
  [ -f artefacts/nq_1m.ids.jsonl ] || uv run --no-sync python -m sever_testkit.slices
fi
cargo build -q --release -p sever-p2 --features demo --bin sever-demo-p2
./target/release/sever-demo-p2 durable --data "$data" --seed "$seed" --root . --work artefacts/demo
