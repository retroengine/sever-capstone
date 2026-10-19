#!/usr/bin/env bash
# demo-engine/demo.sh: SEVER-DB's final database, used the way an application uses it.
#
#   demo-engine/demo.sh setup              once: Python env, the SDK, sever-verify, sever-audit, sever-db
#   demo-engine/demo.sh tour  [--data nq|synthetic] [--rows N]   the guided tour (12 chapters, ~5 min)
#   demo-engine/demo.sh shell [--data nq|synthetic]              use it yourself (help inside)
#   demo-engine/demo.sh cli                the same story through the sever-db command-line tool
#   demo-engine/demo.sh erase              the forensic proof on simulated disks (Part 4's demo)
#   demo-engine/demo.sh examples           run the example programs in examples/
#   demo-engine/demo.sh test               the demo's own tests (offline, ~1 min)
#   demo-engine/demo.sh clean              delete demo-engine/work/ (databases, keys, receipts)
#
# --data nq (the default) needs the pinned NQ data in datasets/ (not in git); --data synthetic
# runs offline on the golden fixture. The databases live in demo-engine/work/ (ext4: the database
# refuses filesystems that do not overwrite in place, §12.9). On a development machine (WSL, a
# laptop with plain swap) the database refuses to start (§12.8); this script passes --dev, which
# opens it with the development override and reports it. SEVER_STRICT=1 leaves the override out.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
cd "$root"
export PYTHONHASHSEED=0 PYTHONPATH="$root/python:$here"
dev=(--dev)
[ "${SEVER_STRICT:-0}" = 1 ] && dev=()
py() { uv run --no-sync python "$@"; }

need_sdk() {
  py -c "import sever_db_native" 2>/dev/null && return
  echo "The SDK's native module is not built: run demo-engine/demo.sh setup first." >&2
  exit 2
}

cmd=${1:-help}
shift || true
case "$cmd" in
  setup)
    uv sync --locked
    # uv sync removes the native module; build it again (release) into .venv.
    uv run --no-sync maturin develop -q --release --uv -m crates/sever-py/Cargo.toml
    for ws in verifier audit; do
      (cd "$ws" && CARGO_TARGET_DIR="$root/$ws/target" cargo build -q --release --locked)
    done
    cargo build -q --release --locked -p sever-db
    if (cd datasets && sha256sum --quiet -c MANIFEST.sha256) 2>/dev/null; then
      [ -f artefacts/partition-seed42.svp ] \
        || py -m sever_partition.build --seed 42
      echo "ready: the real data is there (demo-engine/demo.sh tour)"
    else
      echo "ready, offline only: the NQ data is not in datasets/ (see demo-engine/README.md);"
      echo "use demo-engine/demo.sh tour --data synthetic"
    fi
    ;;
  tour) need_sdk; py -m sever_tour tour "${dev[@]}" "$@" ;;
  shell) need_sdk; py -m sever_tour shell "${dev[@]}" "$@" ;;
  cli) bash "$here/cli-tour.sh" ;;
  erase) bash scripts/demo-p4.sh ;;
  examples)
    need_sdk
    py "$here/examples/quickstart.py"
    py "$here/examples/backend.py"
    ;;
  test)
    need_sdk
    uv run --no-sync ruff check "$here"
    uv run --no-sync ruff format --check "$here"
    uv run --no-sync mypy --strict "$here/sever_tour" "$here/examples" "$here/tests"
    uv run --no-sync pytest -q -p no:cacheprovider "$here/tests" "$@"
    ;;
  clean) rm -rf "$here/work" ;;
  *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
