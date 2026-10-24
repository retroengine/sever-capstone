# scripts/hpc/lib.sh — shared by the HPC scripts (DB-111; scripts/hpc/HPC_GUIDE.md). Source it.
#
# Each run is an *instance* of the systemd user unit sever-hpc@.service:
#   real   the v1.0 gate run (run-all.sh's 22 steps)
#   drill  the failure drills (run-all.sh MOCK=1: short fake steps)
# Instance settings live in $LONGRUN/<instance>.env; its state (alerts, markers, watchdog memory)
# in $LONGRUN/<instance>/. Nothing here reads or writes keys, r_t, passages or database folders.

REPO=${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
LONGRUN=${LONGRUN:-$HOME/longrun}
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

# load_instance NAME: reads $LONGRUN/NAME.env and sets INSTANCE, STATE, PREFIX and defaults.
load_instance() {
  INSTANCE=$1
  case "$INSTANCE" in real|drill) ;; *) echo "unknown instance '$INSTANCE' (real or drill)" >&2; return 2 ;; esac
  # shellcheck disable=SC1090
  [ -f "$LONGRUN/$INSTANCE.env" ] && . "$LONGRUN/$INSTANCE.env"
  STATE="$LONGRUN/$INSTANCE"
  mkdir -p "$STATE"
  if [ "$INSTANCE" = drill ]; then PREFIX=${PREFIX:-hpc-drill}; else PREFIX=${PREFIX:-hpc}; fi
  DISK_MIN_GB=${DISK_MIN_GB:-40}
  MEM_MIN_GB=${MEM_MIN_GB:-16}
  STALE_MIN=${STALE_MIN:-30}
  BACKUP_KEEP=${BACKUP_KEEP:-48}
  UNIT="sever-hpc@$INSTANCE.service"
  export INSTANCE STATE PREFIX
}

stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# notify LEVEL MESSAGE: always appended to $STATE/alerts.log; sent to ntfy when NTFY_TOPIC is set.
# Messages carry step names, counts and exit codes only, never data.
notify() {
  local level=$1; shift
  local msg="$*"
  echo "$(stamp) [$level] $msg" >>"$STATE/alerts.log"
  if [ -n "${NTFY_TOPIC:-}" ]; then
    local prio=default
    case "$level" in crash|failed|stale|disk|memory|refused) prio=high ;; done) prio=high ;; esac
    curl -fsS -m 15 -o /dev/null -H "Title: SEVER-DB $INSTANCE: $level" -H "Priority: $prio" \
      -d "$msg" "${NTFY_SERVER:-https://ntfy.sh}/$NTFY_TOPIC" 2>/dev/null \
      || echo "$(stamp) [notify] ntfy send failed" >>"$STATE/alerts.log"
  fi
}

# alert_once KEY LEVEL MESSAGE: like notify, but at most once per 6 hours for the same KEY.
alert_once() {
  local key=$1; shift
  local f="$STATE/alert.$key" now; now=$(date +%s)
  if [ -f "$f" ] && [ $((now - $(cat "$f"))) -lt 21600 ]; then return 0; fi
  echo "$now" >"$f"
  notify "$@"
}
clear_alert() { rm -f "$STATE/alert.$1"; }

free_gb() { df -Pk "$1" | awk 'NR==2 {print int($4/1048576)}'; }
mem_available_gb() { awk '/MemAvailable/ {print int($2/1048576)}' /proc/meminfo; }
windows_user() { cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r'; }
