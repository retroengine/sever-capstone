#!/usr/bin/env bash
# Part 1 demo in one command (Build §4.9, §2.9 "the demo runs from a clean clone with one command"):
#   scripts/p1-demo.sh                      # nq-10k, seed 42 (needs the P0 data in datasets/)
#   scripts/p1-demo.sh --data nq-100k --seed 123
#   scripts/p1-demo.sh --data synthetic     # offline: golden fixture only, no data needed
# Builds what is missing first (the partition artefact for the seed, the ID export), runs
# `sever-demo idea`, then renders the HTML report next to the JSON.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONHASHSEED=0 PYTHONPATH=python
data=nq-10k seed=42
while [ $# -gt 0 ]; do
  case "$1" in
    --data) data=$2; shift 2 ;;
    --seed) seed=$2; shift 2 ;;
    *) echo "usage: scripts/p1-demo.sh [--data nq-10k|nq-100k|synthetic] [--seed N]"; exit 2 ;;
  esac
done
uv sync --locked -q
if [ "$data" != synthetic ]; then
  (cd datasets && sha256sum --quiet -c MANIFEST.sha256) || { echo "P0 data missing or changed"; exit 1; }
  [ -f "artefacts/partition-seed$seed.svp" ] || uv run --no-sync python -m sever_partition.build --seed "$seed"
  [ -f artefacts/nq_1m.ids.jsonl ] || uv run --no-sync python -m sever_testkit.slices
fi
cargo build -q --release -p sever-p1 --bin sever-demo
if [ "$data" = synthetic ]; then report=artefacts/demo/idea-synthetic-seed42.json
else report="artefacts/demo/idea-$data-seed$seed.json"; fi
status=0
./target/release/sever-demo idea --data "$data" --seed "$seed" --json "$report" || status=$?
uv run --no-sync python -m sever_demo.render "$report"
exit $status
