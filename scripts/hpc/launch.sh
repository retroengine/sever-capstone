#!/usr/bin/env bash
# scripts/hpc/launch.sh start|stop|reset INSTANCE — controls sever-hpc@INSTANCE.
#
#   start real   pins the approved commit (EXPECTED_COMMIT = HEAD), checks it like the unit will,
#                enables autostart (after a reboot it continues once you sign in to Windows),
#                starts the hourly backup and the run. Refused until the drills have passed on
#                this commit (drills.sh); FORCE=1 overrides.
#   start drill  starts the drill instance (no autostart).
#   stop  X      stops the run cleanly and disables autostart; finished steps are kept, and
#                start continues where it stopped.
#   reset drill  forgets the drill's state and logs. (There is no reset for real: its logs are
#                the result. Rerunning a finished real step needs FORCE=1 ONLY=step by hand.)
set -u
. "$(dirname "$0")/lib.sh"
cmd=${1:?usage: launch.sh start|stop|reset real|drill}
load_instance "${2:?usage: launch.sh start|stop|reset real|drill}" || exit 2
cd "$REPO" || exit 1

case "$cmd" in
  start)
    if [ "$INSTANCE" = real ]; then
      head=$(git rev-parse HEAD)
      if [ "${FORCE:-0}" != 1 ] && [ "$(cat "$LONGRUN/drill/PASSED" 2>/dev/null)" != "$head" ]; then
        echo "refused: the drills have not passed on this commit (bash scripts/hpc/drills.sh)"; exit 1
      fi
      sed -i "s/^EXPECTED_COMMIT=.*/EXPECTED_COMMIT=$head/" "$LONGRUN/real.env"
      # The same check the unit runs, in the unit's own limits (memory lock), without starting.
      systemd-run --user --wait --pipe --collect --quiet -p LimitMEMLOCK=infinity \
        -p EnvironmentFile="$LONGRUN/real.env" -p WorkingDirectory="$REPO" \
        "$REPO/scripts/hpc/preflight.sh" real --check || { echo "refused by preflight (above)"; exit 1; }
      systemctl --user enable --now sever-hpc-backup.timer >/dev/null
      systemctl --user enable sever-hpc@real.service >/dev/null 2>&1
    fi
    systemctl --user reset-failed "$UNIT" 2>/dev/null
    systemctl --user start --no-block "$UNIT"
    sleep 3
    echo "started $UNIT: $(systemctl --user is-active "$UNIT")"
    echo "watch it: bash scripts/hpc/status.sh $INSTANCE" ;;
  stop)
    systemctl --user disable "$UNIT" >/dev/null 2>&1
    systemctl --user stop "$UNIT"
    echo "stopped $UNIT; start it again with: bash scripts/hpc/launch.sh start $INSTANCE" ;;
  reset)
    [ "$INSTANCE" = drill ] || { echo "refused: the real run's logs are its result; no reset"; exit 1; }
    systemctl --user stop "$UNIT" 2>/dev/null; systemctl --user reset-failed "$UNIT" 2>/dev/null
    rm -rf "${STATE:?}"/* traces/hpc-drill-*
    echo "drill state and logs cleared" ;;
  *) echo "usage: launch.sh start|stop|reset real|drill"; exit 2 ;;
esac
