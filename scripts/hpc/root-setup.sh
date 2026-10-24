#!/usr/bin/env bash
# scripts/hpc/root-setup.sh — the ONE step that needs root, run by the owner (Claude cannot type a
# sudo password):   sudo bash ~/sever-db/scripts/hpc/root-setup.sh
# Root here is root of your own WSL Ubuntu only: it needs no Windows admin and changes nothing on
# Windows. Re-running it is safe. Afterwards: PowerShell, wsl --shutdown, reopen Ubuntu.
#
#   1. system packages: compiler, git, FUSE and fuse2fs (p4-forensics), e2fsprogs, unzip, ...
#   2. memory lock unlimited for your user's services and logins (spec §12.8; p4-forensics, p4-ex6)
#   3. linger: your systemd user services keep running with no Ubuntu window open
#   4. systemd on in /etc/wsl.conf (Ubuntu's WSL default; checked)
#   5. swap off now (.wslconfig swap=0 keeps it off after a restart)
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run it with sudo: sudo bash $0"; exit 1; }
U=${SUDO_USER:?run it with sudo from your own account, not as root}

echo "== 1. packages"
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  build-essential pkg-config git e2fsprogs fuse3 fuse2fs curl ca-certificates python3 python3-venv \
  rsync xz-utils unzip

echo "== 2. memory lock for $U"
mkdir -p /etc/systemd/system/user@.service.d
printf '[Service]\nLimitMEMLOCK=infinity\n' >/etc/systemd/system/user@.service.d/sever-memlock.conf
printf '%s soft memlock unlimited\n%s hard memlock unlimited\n' "$U" "$U" >/etc/security/limits.d/99-sever.conf

echo "== 3. linger for $U"
loginctl enable-linger "$U"

echo "== 4. systemd in WSL"
if ! grep -qE '^[[:space:]]*systemd[[:space:]]*=[[:space:]]*true' /etc/wsl.conf 2>/dev/null; then
  printf '\n[boot]\nsystemd=true\n' >>/etc/wsl.conf; echo "added [boot] systemd=true to /etc/wsl.conf"
else echo "already on"; fi

echo "== 5. swap off"
swapoff -a || true
systemctl daemon-reload

echo
echo "root-setup: done. Now, in Windows PowerShell:  wsl --shutdown"
echo "then reopen Ubuntu (and Claude), and tell Claude: root-setup done."
