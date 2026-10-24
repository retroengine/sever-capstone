#!/usr/bin/env bash
# scripts/hpc/discover.sh — read-only report of the machine for the HPC run (step 1 of the guide).
# Changes nothing. Prints a table: what was found, and what it means for the run.
set -u
. "$(dirname "$0")/lib.sh"
rows=()
row() { rows+=("| $1 | $2 | $3 |"); }
yes_no() { "$@" >/dev/null 2>&1 && echo yes || echo no; }

. /etc/os-release 2>/dev/null
row "Linux" "${PRETTY_NAME:-?}, $(uname -m), kernel $(uname -r)" "must be x86-64 (spec §12.9)"
if grep -qi 'microsoft-standard-WSL2' /proc/version; then row "WSL" "WSL2, distro ${WSL_DISTRO_NAME:-?}" "the run's platform (DB-111)"
else row "WSL" "not WSL2" "the guide assumes WSL2: stop and ask"; fi
winuser=$(windows_user)
wcores=$(cmd.exe /c "echo %NUMBER_OF_PROCESSORS%" 2>/dev/null | tr -d '\r')
wram=$(powershell.exe -NoProfile -Command "[math]::Floor((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB)" 2>/dev/null | tr -d '\r')
row "Windows" "user ${winuser:-?}, ${wcores:-?} logical processors, ${wram:-?} GB RAM" "windows.sh gives WSL all but 2 cores and 8 GB"
row "WSL gets" "$(nproc) cores, $(awk '/MemTotal/ {print int($2/1048576)}' /proc/meminfo) GB" "after windows.sh + wsl --shutdown: ${wcores:-?}−2 cores, ${wram:-?}−8 GB"
swap=$(awk 'NR>1' /proc/swaps | wc -l)
row "swap" "$([ "$swap" -eq 0 ] && echo off || echo "on ($swap device)")" "must be off for p4-forensics, p4-ex6 (.wslconfig swap=0)"
wslcfg="/mnt/c/Users/$winuser/.wslconfig"
row ".wslconfig" "$([ -f "$wslcfg" ] && tr -d '\r' <"$wslcfg" | grep -E '^(memory|processors|swap)=' | tr '\n' ' ' || echo none)" "windows.sh writes it"
row "repo disk" "$(stat -f -c %T "$REPO") at $REPO, $(free_gb "$REPO") GB free" "ext4 required; about 150 GB wanted"
row "Windows C:" "$(free_gb /mnt/c 2>/dev/null || echo ?) GB free" "the Linux disk grows on C:; keep 150 GB or more free"
row "systemd" "system $(systemctl is-system-running 2>/dev/null), user $(systemctl --user is-system-running 2>/dev/null)" "needed for the run's unit, watchdog and backup"
row "linger" "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" "yes = runs without an open window (root-setup.sh)"
umgr=$(pgrep -u "$USER" -x systemd | head -1)
row "memory lock" "shell $(ulimit -l), services $(awk '/Max locked memory/ {print $5}' "/proc/$umgr/limits" 2>/dev/null)" "services need unlimited (root-setup.sh)"
row "cgroup" "$(cat "/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers" 2>/dev/null)" "memory = the run's memory cap works"
row "sudo" "$(sudo -n true 2>/dev/null && echo 'yes, no password' || echo 'needs your password (root-setup.sh by you)')" "Claude never types passwords"
row "/dev/fuse" "$([ -w /dev/fuse ] && echo usable || echo 'not usable')" "p4-forensics mounts an ext4 image with fuse2fs"
for c in cc git curl unzip fuse2fs fusermount3 mkfs.ext4 cargo uv; do miss+=" $(command -v $c >/dev/null || echo $c)"; done
row "tools missing" "$(echo ${miss:-} | xargs)" "root-setup.sh (packages), setup.sh (cargo, uv)"
net=""; for u in https://github.com https://static.rust-lang.org https://index.crates.io/config.json https://pypi.org/simple/pip/ https://ntfy.sh; do
  curl -fsS -o /dev/null -m 10 "$u" 2>/dev/null || net+=" ${u#https://}"; done
row "internet" "$([ -z "$net" ] && echo "all reachable" || echo "unreachable:$net")" "setup downloads Rust, crates, Python packages; alerts use ntfy.sh"
row "other users" "$(who | awk '{print $1}' | sort -u | tr '\n' ' ') (Linux); Windows: $(query.exe user 2>/dev/null | tr -d '\r' | awk 'NR>1 {print $1}' | tr '\n' ' ')" "keep 2 cores and 8 GB free for them; the run uses nice 10"
row "load" "$(cut -d' ' -f1-3 /proc/loadavg)" "should be near 0 before the run"
row "sleep (mains)" "$(powercfg.exe /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 2>/dev/null | tr -d '\r' | awk -F': ' '/Current AC Power Setting Index/ {print ($2=="0x00000000" ? "never" : "after " strtonum($2)/60 " min")}')" "must be never (windows.sh)"
row "keep-alive" "$([ -f "/mnt/c/Users/$winuser/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/sever-wsl-keepalive.vbs" ] && echo installed || echo missing)" "keeps Ubuntu running with no window; restarts it at sign-in"
row "temperature" "not visible from WSL" "no temperature alert is possible without Windows admin tools"
row "uptime" "$(uptime -p)" ""

echo "| Item | Found | What it means |"
echo "|---|---|---|"
printf '%s\n' "${rows[@]}"
