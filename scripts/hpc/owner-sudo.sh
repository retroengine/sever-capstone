#!/usr/bin/env bash
# scripts/hpc/owner-sudo.sh — the owner's one root step for the laptop run (DB-113), safe WHILE the
# run is going: nothing restarts, nothing stops. Claude cannot type a sudo password.
#
#     sudo bash ~/sever-db/scripts/hpc/owner-sudo.sh
#
# It does what root-setup.sh does, without the WSL restart, so the two locked-memory steps
# (p4-forensics, p4-ex6; spec §12.8 strict mode) can start:
#   1. memory lock unlimited for later starts (systemd user manager drop-in, limits.d)
#   2. memory lock unlimited NOW for every running process of the user (prlimit), so the run that is
#      already going inherits it; and in the run unit's drop-in, so a restarted run keeps it
#   3. swap off now (.wslconfig swap=0, written by laptop-env.sh, keeps it off after a restart)
#   4. Ubuntu's automatic updates off for the run (they could upgrade libraries mid-run)
# Re-running it is safe.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run it with sudo: sudo bash $0"; exit 1; }
U=${SUDO_USER:?run it with sudo from your own account, not as root}
UID_=$(id -u "$U"); H=$(getent passwd "$U" | cut -d: -f6)

echo "== 1. memory lock for later starts"
mkdir -p /etc/systemd/system/user@.service.d
printf '[Service]\nLimitMEMLOCK=infinity\n' >/etc/systemd/system/user@.service.d/sever-memlock.conf
printf '%s soft memlock unlimited\n%s hard memlock unlimited\n' "$U" "$U" >/etc/security/limits.d/99-sever.conf
systemctl daemon-reload

echo "== 2. memory lock now, for every running process of $U"
n=0; for p in $(pgrep -u "$U"); do prlimit --pid "$p" --memlock=unlimited:unlimited 2>/dev/null && n=$((n + 1)); done
echo "raised for $n processes"
d="$H/.config/systemd/user/sever-hpc@real.service.d"
if [ -f "$d/override.conf" ] && ! grep -q '^LimitMEMLOCK=infinity' "$d/override.conf"; then
  sed -i 's/^# LimitMEMLOCK=infinity.*$/LimitMEMLOCK=infinity/' "$d/override.conf"
  grep -q '^LimitMEMLOCK=infinity' "$d/override.conf" || echo "LimitMEMLOCK=infinity" >>"$d/override.conf"
  chown "$U:" "$d/override.conf"
  sudo -u "$U" XDG_RUNTIME_DIR="/run/user/$UID_" systemctl --user daemon-reload || true
fi

echo "== 3. swap off"
swapoff -a || true

echo "== 4. automatic updates off"
systemctl disable --now unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true

echo
echo "owner-sudo: done. Nothing else to do: the run's locked-memory steps start by themselves."
