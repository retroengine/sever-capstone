#!/usr/bin/env bash
# scripts/hpc/watchdog.sh [INSTANCE…] — every 5 minutes (sever-hpc-watchdog.timer), or by hand.
# For each instance with an env file (default: real and drill) it alerts on:
#   stale    the unit is running but its processes used no CPU for STALE_MIN minutes (a hang).
#            It does not kill: fuzzing and mutation steps are honestly quiet for long stretches.
#            With KILL_STALE=1 in the env file it kills the run, and systemd restarts it.
#   failed   the unit gave up (start limit reached).
#   disk     less than DISK_MIN_GB free on the Linux disk.
#   memory   less than 2 GB of memory available.
#   backup   the last backup (real only) is more than 3 hours old.
#   late     the phase running has taken over 1.2 × its DB-113 estimate (run-all's phase.state).
#   alive    every 3 hours (real only) a heartbeat with the steps done so far: when it stops
#            coming, the laptop or WSL is down (DB-113).
# A step that waits on purpose (run-all's "waiting" marker: battery, the owner's sudo step) is
# not reported as a hang.
set -u
. "$(dirname "$0")/lib.sh"
insts=("$@"); [ ${#insts[@]} -gt 0 ] || insts=(real drill)

cpu_usec() { # cumulative CPU time of the unit's control group, in microseconds
  local cg; cg=$(systemctl --user show -p ControlGroup --value "$UNIT" 2>/dev/null)
  [ -n "$cg" ] && awk '/^usage_usec/ {print $2}' "/sys/fs/cgroup$cg/cpu.stat" 2>/dev/null
}

for inst in "${insts[@]}"; do
  [ -f "$LONGRUN/$inst.env" ] || continue
  ( load_instance "$inst" || exit 0
    state=$(systemctl --user is-active "$UNIT" 2>/dev/null)
    if [ "$state" = failed ]; then
      alert_once failed failed "the run unit has failed and will not restart by itself (status.sh $INSTANCE)"
    else clear_alert failed; fi

    if [ "$state" = active ]; then
      now=$(date +%s); use=$(cpu_usec)
      if [ -n "$use" ]; then
        read -r last_use last_t 2>/dev/null <"$STATE/watchdog.cpu" || { last_use=-1; last_t=$now; }
        if [ "$use" != "$last_use" ] || [ -f "$STATE/waiting" ]; then
          echo "$use $now" >"$STATE/watchdog.cpu"; clear_alert stale
        elif [ $(( (now - last_t) / 60 )) -ge "$STALE_MIN" ]; then
          step=$(tail -n 1 "$REPO/traces/$PREFIX-run.out" 2>/dev/null | cut -c1-120)
          alert_once stale stale "no CPU progress for $(( (now - last_t) / 60 )) min (last: $step)"
          if [ "${KILL_STALE:-0}" = 1 ]; then
            systemctl --user kill -s KILL "$UNIT"; notify stale "killed the hung run; systemd restarts it"
          fi
        fi
      fi
    else rm -f "$STATE/watchdog.cpu"; fi

    f=$(free_gb "$REPO")
    if [ "$f" -lt "$DISK_MIN_GB" ]; then alert_once disk disk "only ${f} GB free on the Linux disk"; else clear_alert disk; fi
    m=$(mem_available_gb)
    if [ "$m" -lt 2 ]; then alert_once memory memory "only ${m} GB of memory available"; else clear_alert memory; fi

    if [ "$INSTANCE" = real ] && [ "$state" = active ]; then
      last=$(stat -c %Y "$STATE/backup.last" 2>/dev/null || echo 0)
      if [ $(( $(date +%s) - last )) -gt 10800 ]; then alert_once backup backup "no backup for over 3 hours (backup.sh real)"
      else clear_alert backup; fi
    fi

    if [ "$state" = active ] && read -r ph p_start p_est 2>/dev/null <"$REPO/traces/$PREFIX-phase.state" \
       && [ "${p_est:-0}" -gt 0 ] && [ ! -f "$STATE/waiting" ]; then
      took=$(( ($(date +%s) - p_start) / 60 ))
      if [ "$took" -gt $(( p_est * 12 / 10 )) ]; then
        alert_once "late$ph" late "phase $ph has run ${took} min against an estimate of ${p_est} min"
      fi
    fi

    if [ "$INSTANCE" = real ] && [ "$state" = active ]; then
      hb=$(stat -c %Y "$STATE/heartbeat" 2>/dev/null || echo 0)
      if [ $(( $(date +%s) - hb )) -ge 10800 ]; then
        touch "$STATE/heartbeat"
        sum="$REPO/traces/$PREFIX-summary.log"
        done_n=$(grep -cE ' rc=[0-9]+ duration=' "$sum" 2>/dev/null)
        bad=$(grep -E ' rc=[0-9]+ duration=' "$sum" 2>/dev/null \
          | awk '{split($3, a, "="); if (a[2] + 0 > 0 && a[2] + 0 < 128) print $2}' | sort -u | tr '\n' ' ')
        notify alive "running; $done_n step ends so far${bad:+; failed: $bad}; mem ${m} GB free"
      fi
    fi
  )
done
exit 0
