#!/usr/bin/env bash
# scripts/hpc/check.sh — read-only check of the college HPC workstation's WSL2 Ubuntu before
# scripts/hpc/setup.sh and run-all.sh (DB-111; the one guide is scripts/hpc/HPC_GUIDE.md).
# Changes nothing. One line per requirement: [ ok ], [WARN] (a step may be slow or skipped) or
# [FAIL] (something the run needs). Ends with which run-all.sh steps this machine can run.
#
#   bash scripts/hpc/check.sh            (from anywhere; it cds to the repo root)
#
# The swap, hibernation, memlock and filesystem rules are the engine's own (spec §12.8, §12.9;
# crates/sever-platform/src/rules.rs), so a [FAIL] here is a refusal there.
set -u
cd "$(dirname "$0")/../.."
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
fails=0; locked_ok=1
ok()   { printf '[ ok ] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; }
fail() { printf '[FAIL] %s\n' "$*"; fails=$((fails + 1)); }

echo "== machine"
[ "$(uname -s)-$(uname -m)" = "Linux-x86_64" ] && ok "Linux x86-64 ($(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}"))" \
  || fail "not Linux x86-64: $(uname -s) $(uname -m) (spec §12.9)"
if grep -qi 'microsoft-standard-WSL2' /proc/version 2>/dev/null; then ok "WSL2"
elif grep -qi microsoft /proc/version 2>/dev/null; then fail "WSL1: convert it in PowerShell with 'wsl --set-version Ubuntu-24.04 2'"
else warn "not WSL2: the guide assumes WSL2 Ubuntu on Windows (DB-111)"; fi
n=$(nproc); [ "$n" -ge 16 ] && ok "$n cores" || warn "$n cores (the run takes longer; set processors= in .wslconfig to all cores)"
mem=$(awk '/MemTotal/ {print int($2/1048576)}' /proc/meminfo)
if [ "$mem" -ge 60 ]; then ok "${mem} GiB RAM"
elif [ "$mem" -ge 30 ]; then warn "${mem} GiB RAM: start run-all.sh with JOBS=4 (or raise memory= in .wslconfig)"
else fail "${mem} GiB RAM: too little for the nq-100k steps (raise memory= in .wslconfig, then wsl --shutdown)"; fi
free_gb=$(df -Pk . | awk 'NR==2 {print int($4/1048576)}')
[ "$free_gb" -ge 150 ] && ok "${free_gb} GiB free here" || warn "${free_gb} GiB free here (about 150 GiB wanted)"
fs=$(stat -f -c %T . 2>/dev/null)
case "$fs" in
  ext2/ext3|ext4|xfs) ok "this folder is on the ext4 family or XFS ($fs; spec §12.9)" ;;
  *) fail "this folder is on '$fs'; the engine refuses a Windows drive (/mnt/c ...) (spec §12.9): clone into ~/sever-db" ;;
esac

echo "== commands"
for c in cc git curl; do command -v "$c" >/dev/null 2>&1 && ok "$c" || fail "$c missing (setup.sh installs build-essential git curl)"; done
for c in make pkg-config python3 rsync xz sha256sum; do command -v "$c" >/dev/null 2>&1 && ok "$c" || warn "$c missing (setup.sh installs it)"; done
for c in mkfs.ext4 debugfs fuse2fs fusermount3; do command -v "$c" >/dev/null 2>&1 && ok "$c" || warn "$c missing (setup.sh installs e2fsprogs, fuse3, fuse2fs)"; done
[ -r /dev/fuse ] && [ -w /dev/fuse ] && ok "/dev/fuse usable" || warn "/dev/fuse not usable (p4-forensics needs it; update WSL in PowerShell: wsl --update)"
for c in rustup cargo uv; do command -v "$c" >/dev/null 2>&1 && ok "$c (already installed)" || ok "$c not yet installed (setup.sh installs it)"; done
warn "Windows must not sleep, restart or sign out during the run (HPC_GUIDE.md step 2); this script cannot see that"

echo "== memory rules for --locked-memory (p4-forensics, p4-ex6; spec §12.8)"
l=$(ulimit -l)
[ "$l" = "unlimited" ] && ok "ulimit -l unlimited" \
  || { warn "ulimit -l = $l KiB, not unlimited (before the run: sudo prlimit --pid \$\$ --memlock=unlimited:unlimited)"; locked_ok=0; }
swap_bad=0
while read -r name kind _; do
  [ "$name" = "Filename" ] && continue
  base=${name##*/}
  if [ "$kind" = "partition" ] && [[ "$base" =~ ^zram[0-9]+$ ]]; then continue; fi
  if [[ "$base" =~ ^dm-[0-9]+$ ]] && grep -q '^CRYPT-' "/sys/block/$base/dm/uuid" 2>/dev/null; then continue; fi
  real=$(readlink -f "$name" 2>/dev/null); rb=${real##*/}
  if [[ "$rb" =~ ^dm-[0-9]+$ ]] && grep -q '^CRYPT-' "/sys/block/$rb/dm/uuid" 2>/dev/null; then continue; fi
  swap_bad=1; warn "swap $name ($kind) is on and not encrypted (swap=0 in .wslconfig, then wsl --shutdown)"
done < /proc/swaps
[ "$swap_bad" = 0 ] && ok "swap off or encrypted" || locked_ok=0
state=$(cat /sys/power/state 2>/dev/null || true); resume=$(cat /sys/power/resume 2>/dev/null || echo 0:0)
if [[ " $state " == *" disk "* ]] && [ "$(echo "$resume" | tr -d '[:space:]')" != "0:0" ]; then
  warn "hibernation enabled (/sys/power/resume = $resume)"; locked_ok=0
else ok "hibernation off"; fi
[ -r /dev/fuse ] && [ -w /dev/fuse ] && command -v fusermount3 >/dev/null 2>&1 || locked_ok=0

echo "== network (setup.sh downloads Rust, crates and Python packages)"
for u in https://static.rust-lang.org https://index.crates.io/config.json https://pypi.org/simple/pip/ https://github.com; do
  curl -fsS -o /dev/null -m 10 "$u" 2>/dev/null && ok "$u" || fail "cannot reach $u (campus proxy? set https_proxy)"
done

echo "== project files"
[ -f datasets/MANIFEST.sha256 ] && ok "datasets/MANIFEST.sha256 (from git)" || fail "datasets/MANIFEST.sha256 missing: is this the repo root?"
if [ -d datasets/processed/nq_1m ]; then ok "datasets/processed present (setup.sh checks every hash)"
else fail "datasets/processed missing: unpack sever-data.tar here (HPC_GUIDE.md step 6)"; fi
for s in 42 123 777 2024 9999; do
  [ -s "traces/p1-nq-100k-seed$s.jsonl" ] && [ -s "traces/p2-oracle-nq-10k-seed$s.jsonl" ] \
    || { warn "traces for seed $s missing (setup.sh writes them, slowly)"; }
done
ls artefacts/partition-seed*.svp >/dev/null 2>&1 && ok "artefacts present" || warn "artefacts missing (setup.sh builds them)"

echo "== result"
if [ "$fails" -gt 0 ]; then echo "$fails FAIL line(s): fix those first."; fi
if [ "$locked_ok" = 1 ]; then echo "All 22 run-all.sh steps can run here."
else
  echo "20 of 22 steps can run here until the memory rules above are met (HPC_GUIDE.md steps 3 and 9):"
  echo "p4-forensics and p4-ex6 need swap off, ulimit -l unlimited and a usable /dev/fuse."
fi
[ "$fails" -eq 0 ]
