#!/usr/bin/env bash
# Clean-clone check (DEMO_PLAN Day 3): does the COMMITTED demo run on a fresh machine-like copy?
#
#   scripts/clean_clone_check.sh            # clone HEAD, fresh env from demo/uv.lock, tests, smoke demo
#
# Data files are never committed (CLAUDE.md §5), so the clone links this checkout's
# datasets/processed/<set>/ folders in read-only use; the demo's manifest check then proves the
# linked bytes are the committed ones. The clone, its environment and its ledger live in a temp
# folder and are deleted at the end; nothing here touches this checkout.
set -euo pipefail
DEMO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$(cd "$DEMO/.." && pwd)"
WORK="$(mktemp -d /tmp/sever-clean-clone.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

echo "== clone $(git -C "$SRC" rev-parse --short HEAD) into $WORK"
git clone --quiet "$SRC" "$WORK/repo"
if [ -n "$(git -C "$SRC" status --porcelain)" ]; then
  echo "   note: the source checkout has uncommitted changes; they are NOT in this clone"
fi

echo "== link the data (not in git)"
for set in sciq_reference nq_1m nq_queries; do
  ln -s "$SRC/datasets/processed/$set" "$WORK/repo/datasets/processed/$set"
done

echo "== fresh environment from demo/uv.lock only"
cd "$WORK/repo/demo"
export UV_PROJECT_ENVIRONMENT="$WORK/venv" PYTHONHASHSEED=0 PYTHONPATH=python
uv sync --frozen --quiet

echo "== tests"
uv run --frozen pytest -q

echo "== smoke demo (50,000 rows, 100 stress ops)"
uv run --frozen python -m sever_demo.demo --rows 50000 --stress 100 --ledger "$WORK/ledger.jsonl"

echo "== CLEAN CLONE OK"
