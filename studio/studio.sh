#!/usr/bin/env bash
# studio/studio.sh: SEVER-DB Studio, the desktop demo of the whole project (DB-106).
#
#   studio/studio.sh setup                 once: Studio's environment, the SDK wheel, the programs,
#                                          the data links and config.toml (DB-119)
#   studio/studio.sh prepare [--data nq|synthetic] [--rows N]   build the demo database (~10 min on NQ)
#   studio/studio.sh run     [--data nq|synthetic] [--x11]      open the window
#   studio/studio.sh smoke   [--data nq|synthetic]              open it on this screen, walk everything, quit
#   studio/studio.sh test    [--full]      Studio's tests: offline and fast; --full adds this screen,
#                                          the NQ data, a soak and live sabotage (~15 min)
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
export PYTHONHASHSEED=0 PYTHONPATH="$here/vendor/site:$here"
dev=(--dev)
[ "${SEVER_STRICT:-0}" = 1 ] && dev=()
py() { (cd "$here" && uv run --no-sync python "$@"); }

need_env() {
  py -c "import sever_db, sever_db_native, PySide6" 2>/dev/null && [ -f "$here/config.toml" ] \
    && return
  echo "Studio's environment is not built: run studio/studio.sh setup first." >&2
  exit 2
}

cmd=${1:-help}
shift || true
case "$cmd" in
  setup)
    # The one bridge between the repository and Studio (DB-119): everything Studio uses is built or
    # linked into studio/vendor/ (git-ignored) and named in studio/config.toml. Studio's own code
    # never runs cargo and never reads a repository path (tests/test_boundary.py).
    (cd "$here" && uv sync --locked)
    v="$here/vendor"
    rm -rf "$v"
    mkdir -p "$v/bin" "$v/wheels" "$v/site" "$v/data" "$v/evidence"
    # The SDK: Part 4's native module as a wheel, with inspect (DB-107, DB-108: the engine's own
    # events, explanations and passage reads), and its Python package beside it.
    "$here/.venv/bin/maturin" build -q --release -m crates/sever-py/Cargo.toml --features inspect \
      --interpreter "$here/.venv/bin/python" --out "$v/wheels"
    uv pip install -q --python "$here/.venv/bin/python" --reinstall "$v"/wheels/*.whl
    rsync -a --exclude tests --exclude __pycache__ python/sever_db "$v/site/"
    cp python/sever_db_native.pyi "$v/site/"
    # The released programs: the offline checker, the auditor, Part 3's attack generator.
    for ws in verifier audit; do
      (cd "$ws" && CARGO_TARGET_DIR="$root/$ws/target" cargo build -q --release --locked)
    done
    cp verifier/target/release/sever-verify audit/target/release/sever-audit "$v/bin/"
    cargo build -q --release --locked -p sever-crashkit-p3
    cp target/release/sever-crashkit-p3 "$v/bin/"
    # The data, linked: the pinned datasets, the partition artefacts, the golden fixture; and the
    # committed golden files hashed from git, so Studio can check the fixture without git.
    ln -s "$root/datasets" "$root/artefacts" "$root/golden" "$v/data/"
    for f in golden/p1_partition_small.svp golden/p1_partition_small.json \
             golden/p1_fixture_vectors.json; do
      echo "$(git show "HEAD:$f" | sha256sum | cut -d' ' -f1)  $f"
    done > "$v/data/golden.sha256"
    cp spec/registers_p3.yaml "$v/data/"
    # The evidence: the generated reports, the run ledger, the fairness runs, the freeze tags.
    for f in docs/TRACE_PART_*.md docs/PROOFS_P*.md docs/TEST_ORACLES_P*.md docs/RUN_LEDGER.jsonl \
             results/fair-*.json; do
      [ -e "$f" ] && ln -s "$root/$f" "$v/evidence/"
    done
    git for-each-ref refs/tags --format='%(refname:short) %(creatordate:short)' > "$v/evidence/TAGS"
    cat > "$here/config.toml" <<TOML
# Written by studio/studio.sh setup on $(date -u +%Y-%m-%dT%H:%MZ) from $(git rev-parse --short HEAD).
[paths]
data = "$v/data"
verify = "$v/bin/sever-verify"
audit = "$v/bin/sever-audit"
attacks = "$v/bin/sever-crashkit-p3"
register = "$v/data/registers_p3.yaml"
evidence = "$v/evidence"
TOML
    py -c "from pathlib import Path; from sever_studio.encoder import fetch; \
print('encoder:', fetch(Path('$here/work/models')))"
    if [ -z "$(fc-list :lang=hi family)" ]; then
      echo "note: no Devanagari or Bengali font, so a few NQ passages show boxes:"
      echo "      sudo apt install fonts-noto-core"
    fi
    if (cd datasets && sha256sum --quiet -c MANIFEST.sha256) 2>/dev/null; then
      [ -f artefacts/partition-seed42.svp ] \
        || PYTHONPATH="$root/python" uv run --no-sync python -m sever_partition.build --seed 42
      echo "ready: the real data is there (studio/studio.sh prepare, then run)"
    else
      echo "ready, offline only: the NQ data is not in datasets/ (see the top-level README);"
      echo "use studio/studio.sh prepare --data synthetic, then run --data synthetic"
    fi
    ;;
  prepare) need_env; py -m sever_studio prepare "${dev[@]}" "$@" ;;
  run|smoke)
    need_env
    args=()
    for a in "$@"; do
      if [ "$a" = --x11 ]; then
        if ldconfig -p | grep -q libxcb-cursor.so; then export QT_QPA_PLATFORM=xcb
        else echo "--x11 needs libxcb-cursor0:  sudo apt install libxcb-cursor0" >&2; exit 2; fi
      else args+=("$a"); fi
    done
    [ "$cmd" = smoke ] && args+=(--smoke)
    py -m sever_studio run "${dev[@]}" "${args[@]}"
    ;;
  test)
    need_env
    (cd "$here" && uv run --no-sync ruff check . && uv run --no-sync ruff format --check .)
    (cd "$here" && uv run --no-sync mypy sever_studio tests)
    if [ "${1:-}" = --full ]; then
      shift
      (cd "$here" && SEVER_STUDIO_FULL=1 uv run --no-sync pytest -q -p no:cacheprovider tests "$@")
    else
      (cd "$here" && uv run --no-sync pytest -q -p no:cacheprovider tests "$@")
    fi
    ;;
  clean) rm -rf "$here/work" ;;
  *) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
