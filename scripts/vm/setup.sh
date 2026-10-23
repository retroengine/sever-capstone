#!/usr/bin/env bash
# scripts/vm/setup.sh — one-time, idempotent setup of a fresh cloud Linux VM for SEVER-DB's
# pre-registered Full-tier gates and measures (Build §2.8; Build 3-4 §1.9, §2.10).
#
# Target: Ubuntu 24.04, root or a user with sudo, e.g. 32 cores / 64-128 GB RAM.
#
# What it does (each step is skipped when already done, so re-running is safe):
#   1. apt packages: build-essential, pkg-config, git, e2fsprogs, fuse3, fuse2fs, curl, python3, ...
#   2. memlock: writes /etc/security/limits.d/99-sever.conf (memlock unlimited for the run user),
#      needed by the --locked-memory gates (mlockall). Takes effect only after a RE-LOGIN.
#   3. rustup: the toolchain pinned in rust-toolchain.toml (spec §20.1), nightly (cargo-fuzz),
#      1.85 (the MSRV step of scripts/ci.sh), llvm-tools-preview (cargo-llvm-cov).
#   4. cargo tools, only if missing: cargo-mutants, cargo-llvm-cov, cargo-fuzz, cargo-deny.
#   5. uv (astral installer), `uv sync`, then the three SDK native modules exactly as scripts/ci.sh
#      builds them (sever-py-p2, sever-py-p3, sever-py). `uv sync` removes them, so they are always
#      rebuilt after it.
#   6. datasets: checks datasets/MANIFEST.sha256. The data are not in git; when they are missing it
#      prints the rsync command to copy datasets/processed/ over from the workstation.
#   7. artefacts: builds the partition (C-15) and the nq-1m ID export if artefacts/ lacks them
#      (skip with SKIP_ARTEFACTS=1).
#
# How to run (from anywhere; the script cds to the repo root):
#   bash scripts/vm/setup.sh
#   then log out and back in (memlock), check `ulimit -l` prints "unlimited", and start the run:
#   setsid nohup bash scripts/vm/run-all.sh > traces/vm-run.out 2>&1 &
#
# Duration: about 20-40 min (cargo installs and the release builds dominate), plus the partition
# build when artefacts/ is empty. The full gate run that follows takes roughly 1-2 days.
#
# Without admin rights (no sudo): NO_SUDO=1 bash scripts/vm/setup.sh. Steps 1-2 then install
# nothing system-wide: missing commands are listed for the admin (a C compiler, git and curl are
# required), fuse2fs is unpacked from its .deb into ~/.local without root when it is missing, and
# the memlock limit is left as it is (the two --locked-memory steps then need the admin, see
# scripts/vm/HPC_GUIDE.md). Steps 3-8 install into the home directory and need no admin.
#
# Never prints or logs keys, r_t or passage text: it only installs tools and checks hashes.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)

say() { printf '\n== %s\n' "$*"; }
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
RUN_USER=${SUDO_USER:-$(id -un)}

# ---- 1. apt packages --------------------------------------------------------------------------
say "apt packages"
if [ "${NO_SUDO:-0}" = 1 ]; then
  # Commands, not packages: the machine may have gcc without the build-essential metapackage.
  need_missing=(); want_missing=()
  for c in cc git curl; do command -v "$c" >/dev/null 2>&1 || need_missing+=("$c"); done
  for c in make pkg-config python3 rsync xz sha256sum mkfs.ext4 debugfs fusermount3; do
    command -v "$c" >/dev/null 2>&1 || want_missing+=("$c")
  done
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v fuse2fs >/dev/null 2>&1; then
    # apt-get download and dpkg -x need no root: unpack the package into ~/.local/opt.
    opt="$HOME/.local/opt/fuse2fs"
    mkdir -p "$opt" "$HOME/.local/bin"
    if (cd "$opt" && apt-get download fuse2fs >/dev/null 2>&1 && dpkg -x fuse2fs_*.deb "$opt/root"); then
      bin=$(find "$opt/root" -type f -name fuse2fs | head -1)
      [ -n "$bin" ] && ln -sf "$bin" "$HOME/.local/bin/fuse2fs"
    fi
    if command -v fuse2fs >/dev/null 2>&1; then echo "fuse2fs: unpacked into $opt (no root)"
    else want_missing+=("fuse2fs"); fi
  fi
  [ ${#want_missing[@]} -eq 0 ] || echo "ASK THE ADMIN to install (NO_SUDO=1): ${want_missing[*]}"
  if [ ${#need_missing[@]} -gt 0 ]; then
    echo "MISSING and required to build anything: ${need_missing[*]}"
    echo "Ask the admin: sudo apt-get install -y build-essential pkg-config git curl"
    exit 1
  fi
  [ ${#want_missing[@]} -gt 0 ] || echo "all present"
else
PKGS=(build-essential pkg-config git e2fsprogs fuse3 fuse2fs curl ca-certificates python3 \
      python3-venv rsync xz-utils)
missing=()
for p in "${PKGS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
if [ ${#missing[@]} -gt 0 ]; then
  $SUDO apt-get update -y
  DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y --no-install-recommends "${missing[@]}"
else
  echo "all present"
fi
fi
# fuse2fs mounts the forensic disk image (P4-T1/T2) as an unprivileged user: /dev/fuse must be usable.
[ -e /dev/fuse ] || echo "WARNING: /dev/fuse is missing; the forensics gate needs FUSE (modprobe fuse)"

# ---- 2. memlock -------------------------------------------------------------------------------
say "memlock limit for $RUN_USER"
LIMITS=/etc/security/limits.d/99-sever.conf
WANT="$RUN_USER soft memlock unlimited
$RUN_USER hard memlock unlimited"
if [ "${NO_SUDO:-0}" = 1 ]; then
  echo "skipped (NO_SUDO=1); only the admin can write $LIMITS"
elif [ "$(cat "$LIMITS" 2>/dev/null || true)" != "$WANT" ]; then
  printf '%s\n' "$WANT" | $SUDO tee "$LIMITS" >/dev/null
  echo "wrote $LIMITS"
fi
echo "current shell: ulimit -l = $(ulimit -l)"
[ "$(ulimit -l)" = "unlimited" ] || echo "NOTE: log out and back in (new SSH session) before run-all.sh;" \
  "the --locked-memory gates need ulimit -l = unlimited"

# ---- 3. rustup and toolchains -----------------------------------------------------------------
say "rust toolchains"
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
if ! command -v rustup >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal \
    --default-toolchain none
fi
PINNED=""
if [ -f rust-toolchain.toml ]; then
  PINNED=$(sed -n 's/^[[:space:]]*channel[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' rust-toolchain.toml | head -1)
fi
PINNED=${PINNED:-stable}
echo "pinned toolchain: $PINNED"
rustup toolchain install "$PINNED" --profile minimal -c rustfmt -c clippy -c llvm-tools-preview
rustup default "$PINNED"
rustup toolchain install nightly --profile minimal -c llvm-tools-preview
rustup toolchain install 1.85 --profile minimal
# Run from the repo root, rust-toolchain.toml selects $PINNED; make sure its components are there.
rustup component add --toolchain "$PINNED" llvm-tools-preview rustfmt clippy

# ---- 4. cargo tools ---------------------------------------------------------------------------
say "cargo tools"
for t in cargo-mutants cargo-llvm-cov cargo-fuzz cargo-deny; do
  if command -v "$t" >/dev/null 2>&1; then echo "$t: present"
  else (cd "$HOME" && cargo +"$PINNED" install --locked "$t"); fi
done

# ---- 5. uv, Python env, SDK native modules ----------------------------------------------------
say "uv and the Python environment"
command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv sync
# Same lines as scripts/ci.sh (fast tier): uv sync removes these modules, so rebuild all three.
uv run --no-sync maturin develop -q --release --uv -m crates/sever-py-p2/Cargo.toml
uv run --no-sync maturin develop -q --release --uv -m crates/sever-py-p3/Cargo.toml
uv run --no-sync maturin develop -q --release --uv -m crates/sever-py/Cargo.toml

# ---- 6. datasets ------------------------------------------------------------------------------
say "datasets"
DATA_OK=0
if [ -f datasets/MANIFEST.sha256 ] && [ -d datasets/processed ] \
   && (cd datasets && sha256sum --quiet -c MANIFEST.sha256); then
  DATA_OK=1; echo "datasets/MANIFEST.sha256: OK"
else
  cat <<MSG
DATASETS MISSING OR NOT MATCHING datasets/MANIFEST.sha256.
They are not in git. Copy them from the workstation (run this ON THE WORKSTATION, in ~/sever-db):
  rsync -av --progress datasets/processed/ ${RUN_USER}@<VM-IP>:${ROOT}/datasets/processed/
(and, if the VM clone lacks them, datasets/PINS.json and datasets/MANIFEST.sha256).
Then check on the VM:  (cd datasets && sha256sum -c MANIFEST.sha256)
and re-run this script.
MSG
fi

# ---- 7. partition artefacts -------------------------------------------------------------------
say "artefacts"
if [ "${SKIP_ARTEFACTS:-0}" = 1 ]; then echo "skipped (SKIP_ARTEFACTS=1)"
elif [ "$DATA_OK" != 1 ]; then echo "skipped: datasets missing"
else
  export PYTHONHASHSEED=0 PYTHONPATH=python
  if ls artefacts/partition-seed*.svp >/dev/null 2>&1; then echo "partition artefacts: present"
  else uv run --no-sync python -m sever_partition.build --all-seeds; fi
  if [ -f artefacts/nq_1m.ids.jsonl ]; then echo "artefacts/nq_1m.ids.jsonl: present"
  else uv run --no-sync python -m sever_testkit.slices; fi
fi

# ---- 8. traces --------------------------------------------------------------------------------
# The replay gates read Part 1's nq-100k traces and the crash gates Part 2's nq-10k oracle streams;
# both live in traces/ (not in git). Each is written by its reference model when missing (or copy
# them from the workstation: rsync -av traces/p1-nq-100k-seed*.jsonl traces/p2-oracle-*.jsonl).
say "traces"
if [ "$DATA_OK" != 1 ]; then echo "skipped: datasets missing"
else
  export PYTHONHASHSEED=0 PYTHONPATH=python
  mkdir -p traces
  for s in 42 123 777 2024 9999; do
    [ -s "traces/p1-nq-100k-seed$s.jsonl" ] \
      || uv run --no-sync python -m sever_testkit.traces --data nq-100k --seed "$s"
    [ -s "traces/p2-oracle-nq-10k-seed$s.jsonl" ] \
      || uv run --no-sync python -m sever_refmodel_durable.oracle write --data nq-10k --seed "$s" --root .
  done
  ls -la traces/p1-nq-100k-seed*.jsonl traces/p2-oracle-nq-10k-seed*.jsonl
fi

say "done"
echo "Next: re-login if ulimit -l is not unlimited, then from $ROOT:"
echo "  mkdir -p traces && setsid nohup bash scripts/vm/run-all.sh > traces/vm-run.out 2>&1 &"
