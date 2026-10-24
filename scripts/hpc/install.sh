#!/usr/bin/env bash
# scripts/hpc/install.sh [--uninstall] — installs the HPC run's safeguards as systemd user units
# (no sudo; root-setup.sh must have run first for the memory lock and linger). Starts nothing but
# the watchdog timer; the run itself starts with launch.sh. Re-running it is safe.
#
#   ~/.config/systemd/user/sever-hpc@.service       the run (instances real, drill)
#   ~/.config/systemd/user/sever-hpc-alert@.service  alert when the run unit gives up
#   ~/.config/systemd/user/sever-hpc-watchdog.*      every 5 min: hang, disk, memory, backup age
#   ~/.config/systemd/user/sever-hpc-backup.*        hourly backup of the real run's results
#   ~/longrun/real.env, ~/longrun/drill.env          settings (edit NTFY_TOPIC, BACKUP_REMOTE)
set -u
. "$(dirname "$0")/lib.sh"
UDIR="$HOME/.config/systemd/user"

if [ "${1:-}" = --uninstall ]; then
  systemctl --user disable --now sever-hpc@real.service sever-hpc@drill.service \
    sever-hpc-watchdog.timer sever-hpc-backup.timer 2>/dev/null
  rm -rf "$UDIR"/sever-hpc@.service "$UDIR"/sever-hpc-alert@.service "$UDIR"/sever-hpc-watchdog.* \
    "$UDIR"/sever-hpc-backup.* "$UDIR"/sever-hpc@real.service.d "$UDIR"/sever-hpc@drill.service.d
  systemctl --user daemon-reload
  echo "uninstalled the units; $LONGRUN (settings, alerts, backups) is kept"; exit 0
fi

problems=0
systemctl --user is-system-running >/dev/null 2>&1 || [ "$(systemctl --user is-system-running 2>/dev/null)" = degraded ] \
  || { echo "systemd user manager not running (is systemd=true in /etc/wsl.conf? root-setup.sh)"; problems=1; }
[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" = yes ] \
  || { echo "WARNING: linger is off: the run stops when the last Ubuntu window closes (root-setup.sh)"; problems=1; }
umgr=$(pgrep -u "$USER" -x systemd | head -1)
memlock_hard=$(awk '/Max locked memory/ {print $5}' "/proc/$umgr/limits" 2>/dev/null)

mkdir -p "$UDIR" "$LONGRUN/real" "$LONGRUN/drill"
for f in "$REPO"/scripts/hpc/units/*; do
  sed "s|@REPO@|$REPO|g" "$f" >"$UDIR/$(basename "$f")"
done

# The real run: memory cap (all but 4 GB of what WSL has), memory lock for p4-forensics/p4-ex6.
total=$(awk '/MemTotal/ {print int($2/1048576)}' /proc/meminfo)
cap=$(( total > 12 ? total - 4 : total ))
mkdir -p "$UDIR/sever-hpc@real.service.d"
{
  echo "[Service]"
  echo "MemoryMax=${cap}G"
  if [ "$memlock_hard" = unlimited ]; then echo "LimitMEMLOCK=infinity"
  else echo "# LimitMEMLOCK=infinity needs root-setup.sh (user manager hard limit: $memlock_hard); preflight refuses until then"; fi
} >"$UDIR/sever-hpc@real.service.d/override.conf"
[ "$memlock_hard" = unlimited ] || { echo "WARNING: the memory lock is limited to $memlock_hard bytes: run root-setup.sh, then wsl --shutdown"; problems=1; }

# The drill: the same unit, fast restarts and a low start limit so a crash loop stops in minutes.
mkdir -p "$UDIR/sever-hpc@drill.service.d"
cat >"$UDIR/sever-hpc@drill.service.d/override.conf" <<'EOF'
[Unit]
StartLimitIntervalSec=10min
StartLimitBurst=4
[Service]
MemoryMax=2G
RestartSec=3s
RestartSteps=2
RestartMaxDelaySec=8s
EOF

winuser=$(windows_user)
if [ ! -f "$LONGRUN/real.env" ]; then
  cat >"$LONGRUN/real.env" <<EOF
# SEVER-DB HPC run settings (scripts/hpc/HPC_GUIDE.md). Plain KEY=value lines, no spaces.
# ntfy topic for alerts on your phone (app "ntfy", subscribe to the same topic); empty = log only.
NTFY_TOPIC=
# Backups: a folder on the Windows side (outside the Linux disk), plus an optional off-machine copy
# (an rclone remote "name:path" or an ssh target "user@host:path").
BACKUP_DIR=/mnt/c/Users/${winuser:-$USER}/sever-backup/real
BACKUP_REMOTE=
# Set by launch.sh: the commit the run must test.
EXPECTED_COMMIT=
DISK_MIN_GB=40
MEM_MIN_GB=16
STALE_MIN=30
KILL_STALE=0
EOF
fi
if [ ! -f "$LONGRUN/drill.env" ]; then
  cat >"$LONGRUN/drill.env" <<EOF
# The failure drills (drills.sh): fake 20-second steps, local alerts only.
MOCK=1
PREFIX=hpc-drill
MOCK_SECONDS=10
NTFY_TOPIC=
BACKUP_DIR=$LONGRUN/drill/backups
DISK_MIN_GB=1
MEM_MIN_GB=1
STALE_MIN=1
EOF
fi

# The environment record (versions, commit, machine; the seeds are the project's fixed five).
{
  echo "written $(stamp) by install.sh"
  echo "commit $(git -C "$REPO" rev-parse HEAD)"
  . /etc/os-release; echo "os $PRETTY_NAME; kernel $(uname -r); WSL distro ${WSL_DISTRO_NAME:-?}"
  echo "cores $(nproc); memory $(awk '/MemTotal/ {print int($2/1048576)}' /proc/meminfo) GB; cpu $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)"
  echo "rustc $(rustc -V 2>/dev/null); cargo $(cargo -V 2>/dev/null)"
  echo "uv $(uv --version 2>/dev/null); python $(cd "$REPO" && uv run --no-sync python -V 2>/dev/null)"
  echo "seeds 42 123 777 2024 9999 (Overview §10.6; keys, r_t and nonces come from the OS)"
  echo "datasets/MANIFEST.sha256 $(sha256sum "$REPO/datasets/MANIFEST.sha256" | cut -c1-16)"
} >"$LONGRUN/env.txt"

systemctl --user daemon-reload
systemctl --user enable --now sever-hpc-watchdog.timer >/dev/null 2>&1
echo "installed: units in $UDIR, settings in $LONGRUN/real.env and drill.env, record in $LONGRUN/env.txt"
echo "memory cap for the real run: ${cap} GB of ${total} GB; memory lock: $memlock_hard"
[ "$problems" = 0 ] && echo "install: OK" || { echo "install: done with warnings (above)"; exit 1; }
