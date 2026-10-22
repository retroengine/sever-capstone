#!/usr/bin/env bash
# studio/studio.sh: SEVER-DB Studio, the desktop demo of the whole project (DB-106).
#
#   studio/studio.sh setup                 once: Studio's environment, the SDK, the encoder, the tools
#   studio/studio.sh prepare [--data nq|synthetic] [--rows N]   build the demo database (~10 min on NQ)
#   studio/studio.sh run     [--data nq|synthetic]              open the window
#   studio/studio.sh test                  Studio's own tests, offline (lint, types, tests)
#   studio/studio.sh clean                 delete studio/work/ (databases, keys, receipts, the model)
#
# --data nq (the default) needs the pinned NQ data in datasets/ (not in git); --data synthetic runs
# offline on the golden fixture. The databases live in studio/work/ (ext4: the database refuses
# file systems that do not overwrite in place, §12.9). On a development machine (WSL, a laptop with
# plain swap) the database refuses to start (§12.8); this script passes --dev, which opens it with
# the development override and shows that it did. SEVER_STRICT=1 leaves the override out.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
cd "$root"
export PYTHONHASHSEED=0 PYTHONPATH="$root/python:$here"
dev=(--dev)
[ "${SEVER_STRICT:-0}" = 1 ] && dev=()
py() { (cd "$here" && uv run --no-sync python "$@"); }

need_env() {
  py -c "import sever_db_native, PySide6" 2>/dev/null && return
  echo "Studio's environment is not built: run studio/studio.sh setup first." >&2
  exit 2
}

cmd=${1:-help}
shift || true
case "$cmd" in
  setup)
    (cd "$here" && uv sync --locked)
    # The SDK's native module, built into Studio's environment (uv sync removes it).
    VIRTUAL_ENV="$here/.venv" "$here/.venv/bin/maturin" develop -q --release --uv \
      -m crates/sever-py/Cargo.toml
    for ws in verifier audit; do
      (cd "$ws" && CARGO_TARGET_DIR="$root/$ws/target" cargo build -q --release --locked)
    done
    py -c "from pathlib import Path; from sever_studio.encoder import fetch; \
print('encoder:', fetch(Path('$here/work/models')))"
    if (cd datasets && sha256sum --quiet -c MANIFEST.sha256) 2>/dev/null; then
      [ -f artefacts/partition-seed42.svp ] \
        || uv run --no-sync python -m sever_partition.build --seed 42
      echo "ready: the real data is there (studio/studio.sh prepare, then run)"
    else
      echo "ready, offline only: the NQ data is not in datasets/ (see the top-level README);"
      echo "use studio/studio.sh prepare --data synthetic, then run --data synthetic"
    fi
    ;;
  prepare) need_env; py -m sever_studio prepare "${dev[@]}" "$@" ;;
  run) need_env; py -m sever_studio run "${dev[@]}" "$@" ;;
  test)
    need_env
    (cd "$here" && uv run --no-sync ruff check . && uv run --no-sync ruff format --check .)
    (cd "$here" && uv run --no-sync mypy sever_studio tests)
    (cd "$here" && QT_QPA_PLATFORM=offscreen uv run --no-sync pytest -q -p no:cacheprovider tests "$@")
    ;;
  clean) rm -rf "$here/work" ;;
  *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
