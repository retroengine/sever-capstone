#!/usr/bin/env bash
# scripts/hpc/windows.sh [--dry-run] — the Windows-side settings, made from inside WSL with no
# Windows admin (the files are your own; powercfg changes only your active power plan):
#
#   1. %USERPROFILE%\.wslconfig: processors = all but 2, memory = all but 8 GB, swap=0
#      (2 cores and room for Windows and other users; swap off for spec §12.8). An existing file is
#      kept as .wslconfig.before-sever. Takes effect after `wsl --shutdown`.
#   2. A hidden keep-alive in your Startup folder (sever-wsl-keepalive.vbs): at every sign-in it
#      starts this Ubuntu and keeps it running with no window open, so the run continues (and
#      resumes after a reboot once you sign in). Delete the file to undo.
#   3. Sleep and hibernate on mains power: never (powercfg). If the college's policy forbids it,
#      it says so and you set it in Settings or ask IT.
set -u
. "$(dirname "$0")/lib.sh"
dry=0; [ "${1:-}" = --dry-run ] && dry=1
grep -qi microsoft /proc/version || { echo "not WSL: nothing to do"; exit 1; }
winuser=$(windows_user); [ -n "$winuser" ] || { echo "cannot reach Windows (cmd.exe): is WSL interop on?"; exit 1; }
WINHOME="/mnt/c/Users/$winuser"
distro=${WSL_DISTRO_NAME:-Ubuntu}
cores=$(cmd.exe /c "echo %NUMBER_OF_PROCESSORS%" 2>/dev/null | tr -d '\r')
ram=$(powershell.exe -NoProfile -Command "[math]::Floor((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB)" 2>/dev/null | tr -d '\r')
[[ "$cores" =~ ^[0-9]+$ && "$ram" =~ ^[0-9]+$ ]] || { echo "could not read cores ($cores) or RAM ($ram) from Windows"; exit 1; }
procs=$(( cores > 4 ? cores - 2 : cores )); mem=$(( ram > 16 ? ram - 8 : ram / 2 ))

cfg="[wsl2]
memory=${mem}GB
processors=${procs}
swap=0"
echo "== Windows: user $winuser, $cores logical processors, $ram GB RAM; distro $distro"
echo "== 1. $WINHOME/.wslconfig"; echo "$cfg"
vbs="' SEVER-DB: keeps WSL ($distro) running with no window open, so the HPC run continues.
' Written by scripts/hpc/windows.sh. Delete this file to undo.
CreateObject(\"WScript.Shell\").Run \"wsl.exe -d $distro --exec /bin/sleep infinity\", 0, False"
startup="$WINHOME/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
echo "== 2. $startup/sever-wsl-keepalive.vbs"
echo "== 3. powercfg: standby and hibernate after 0 minutes on mains power"
[ "$dry" = 1 ] && { echo "(dry run: nothing written)"; exit 0; }

if [ -f "$WINHOME/.wslconfig" ] && [ "$(tr -d '\r' <"$WINHOME/.wslconfig")" != "$cfg" ]; then
  cp "$WINHOME/.wslconfig" "$WINHOME/.wslconfig.before-sever"; echo "kept the old file as .wslconfig.before-sever"
fi
printf '%s\n' "$cfg" | sed 's/$/\r/' >"$WINHOME/.wslconfig"
mkdir -p "$startup" && printf '%s\n' "$vbs" | sed 's/$/\r/' >"$startup/sever-wsl-keepalive.vbs"
ok=1
for s in "standby-timeout-ac 0" "hibernate-timeout-ac 0"; do
  # shellcheck disable=SC2086
  powercfg.exe /change $s >/dev/null 2>&1 || ok=0
done
[ "$ok" = 1 ] && echo "power: sleep and hibernate off on mains power" \
  || echo "power: NOT changed (policy?). Set Settings > System > Power > Sleep: Never, or ask IT."
echo
echo "windows.sh: done. To apply .wslconfig: in PowerShell run  wsl --shutdown  then reopen Ubuntu."
