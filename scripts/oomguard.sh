#!/bin/bash
# SEVER-DB memory guard (systemd user service sever-oomguard; starts with WSL).
# Every 5 s:
#  - marks every heavy process (sever-*, cargo, rustc, maturin, python gates) oom_score_adj 900, so
#    if memory runs out the kernel kills a gate process, never WSL's own processes;
#  - below LOW MB available with two or more heavy processes running, pauses (SIGSTOP) the newest
#    one, so the oldest keeps its progress; resumes paused ones above HIGH MB;
#  - below CRIT MB with only one heavy process, stops it cleanly (SIGTERM), so the job queue
#    records a failure and moves on instead of WSL crashing.
# Log: ~/sever-db/traces/oomguard.log
LOW=900; HIGH=2500; CRIT=300
LOG=$HOME/sever-db/traces/oomguard.log
heavy() {
  for p in $(pgrep -u "$USER" -f 'sever-crashkit|sever-scan|sever-demo|sever-db|cargo|rustc|maturin|sever_testkit|pytest' 2>/dev/null); do
    [ "$p" = "$$" ] && continue
    c=$(tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null) || continue
    case "$c" in *oomguard*|*claude*|*jobq.sh*|"") continue;; esac
    rss=$(awk '/VmRSS/{print $2}' /proc/$p/status 2>/dev/null)
    [ -n "$rss" ] && [ "$rss" -gt 200000 ] && echo "$p"
  done
}
while true; do
  avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  hs=$(heavy)
  for p in $hs; do echo 900 > /proc/$p/oom_score_adj 2>/dev/null; done
  running=$(for p in $hs; do s=$(ps -o stat= -p $p 2>/dev/null | cut -c1); [ "$s" != "T" ] && echo $p; done)
  n=$(echo "$running" | grep -c .)
  if [ "$avail" -lt "$CRIT" ] && [ "$n" -le 1 ] && [ -n "$running" ]; then
    kill -TERM $running && echo "$(date -u +%FT%TZ) avail=${avail}MB: stopped lone process $running ($(tr '\0' ' ' < /proc/$running/cmdline 2>/dev/null | cut -c1-120))" >> "$LOG"
  elif [ "$avail" -lt "$LOW" ] && [ "$n" -ge 2 ]; then
    newest=$(for p in $running; do echo "$(stat -c %Y /proc/$p) $p"; done | sort -n | tail -1 | cut -d' ' -f2)
    kill -STOP "$newest" && echo "$(date -u +%FT%TZ) avail=${avail}MB: paused $newest" >> "$LOG"
  elif [ "$avail" -gt "$HIGH" ]; then
    for p in $hs; do
      if [ "$(ps -o stat= -p $p 2>/dev/null | cut -c1)" = "T" ]; then
        kill -CONT "$p" && echo "$(date -u +%FT%TZ) avail=${avail}MB: resumed $p" >> "$LOG"; break
      fi
    done
  fi
  sleep 5
done
