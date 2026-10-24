#!/usr/bin/env bash
# scripts/hpc/status.sh [INSTANCE] — one screen: unit state, steps done, restarts, current step,
# machine load, disk, last backup and alerts, and the last 20 lines of the run's output.
set -u
. "$(dirname "$0")/lib.sh"
load_instance "${1:-real}" || exit 2
cd "$REPO" || exit 1
sum="traces/$PREFIX-summary.log"; out="traces/$PREFIX-run.out"
age() { local t; t=$(stat -c %Y "$1" 2>/dev/null) || { echo never; return; }; local s=$(( $(date +%s) - t )); printf '%dh%02dm ago' $((s/3600)) $((s%3600/60)); }

echo "== SEVER-DB HPC run: $INSTANCE ($(date '+%F %T'))"
printf '%-18s %s\n' "unit" "$(systemctl --user is-active "$UNIT" 2>/dev/null) ($(systemctl --user is-enabled "$UNIT" 2>/dev/null); autostart after sign-in if enabled)"
printf '%-18s %s\n' "finished" "$( [ -f "$STATE/DONE" ] && echo "yes, $(cat "$STATE/DONE")" || echo no)"
printf '%-18s %s\n' "starts" "$(cat "$STATE/starts" 2>/dev/null || echo 0) (systemd restarts: $(systemctl --user show -p NRestarts --value "$UNIT" 2>/dev/null))"
if [ -f "$sum" ]; then
  printf '%-18s %s passed, %s failed, %s interrupted\n' "steps" \
    "$(grep -c ' rc=0 ' "$sum")" "$(grep -E ' rc=([1-9]|[1-9][0-9]|1[01][0-9]|12[0-7]) ' "$sum" | awk '{print $2}' | sort -u | wc -l)" \
    "$(grep -E ' rc=(12[89]|1[3-9][0-9]|2[0-9][0-9]) ' "$sum" | wc -l)"
  printf '%-18s %s\n' "failed steps" "$(grep -E ' rc=([1-9]|[1-9][0-9]|1[01][0-9]|12[0-7]) ' "$sum" | awk '{print $2}' | sort -u | tr '\n' ' ')"
fi
printf '%-18s %s\n' "now" "$(grep -E ' START: ' "$out" 2>/dev/null | tail -n 1 | awk '{print $1, $2}')"
printf '%-18s %s\n' "load (1/5/15 min)" "$(cut -d' ' -f1-3 /proc/loadavg) on $(nproc) cores"
printf '%-18s %s GB available of %s GB\n' "memory" "$(mem_available_gb)" "$(awk '/MemTotal/ {print int($2/1048576)}' /proc/meminfo)"
printf '%-18s %s GB free (Linux disk); C: %s GB free\n' "disk" "$(free_gb "$REPO")" "$(free_gb /mnt/c 2>/dev/null || echo '?')"
printf '%-18s %s\n' "last backup" "$(age "$STATE/backup.last")"
printf '%-18s %s\n' "temperature" "not visible from WSL"
echo "== last alerts"; tail -n 5 "$STATE/alerts.log" 2>/dev/null || echo "(none)"
echo "== last 20 lines of $out"; tail -n 20 "$out" 2>/dev/null || echo "(no output yet)"
