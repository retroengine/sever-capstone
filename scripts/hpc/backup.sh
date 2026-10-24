#!/usr/bin/env bash
# scripts/hpc/backup.sh INSTANCE            hourly (sever-hpc-backup.timer) or by hand
# scripts/hpc/backup.sh INSTANCE restore F  unpack backup F into ~/restored-<time>/ (never over the repo)
#
# Copies only what the run reports: traces/$PREFIX-*.log / -summary.log / -run.out, the run ledger
# docs/RUN_LEDGER.jsonl, results/, and the commit. Never database folders, keys, certificates or
# the trace data files (CLAUDE.md §5). Each backup is a .tar.gz with a .sha256, verified after
# writing, in BACKUP_DIR (the Windows side, outside the Linux disk); the newest BACKUP_KEEP are
# kept. With BACKUP_REMOTE (an rclone remote "name:path" or an ssh target "user@host:path") each
# backup is also copied there.
set -u
. "$(dirname "$0")/lib.sh"
load_instance "${1:-real}" || exit 2
cd "$REPO" || exit 1
DEST=${BACKUP_DIR:-$STATE/backups}

if [ "${2:-}" = restore ]; then
  f=${3:?usage: backup.sh INSTANCE restore FILE.tar.gz}
  (cd "$(dirname "$f")" && sha256sum -c "$(basename "$f").sha256") || { echo "checksum FAILED: not restoring"; exit 1; }
  out="$HOME/restored-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$out" && tar xzf "$f" -C "$out"
  echo "restored into $out (compare, then copy what you need; the repo is untouched)"; exit 0
fi

mkdir -p "$DEST" || { notify backup "backup folder $DEST is not writable"; exit 1; }
name="$PREFIX-$(date +%Y%m%d-%H%M%S).tar.gz"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git rev-parse HEAD >"$tmp/COMMIT" 2>/dev/null
files=()
for p in traces/"$PREFIX"-*.log traces/"$PREFIX"-summary.log traces/"$PREFIX"-run.out docs/RUN_LEDGER.jsonl results; do
  [ -e "$p" ] && files+=("$p")
done
tar czf "$tmp/$name" -C "$tmp" COMMIT -C "$REPO" "${files[@]}" 2>/dev/null \
  || { notify backup "backup could not be written"; exit 1; }
(cd "$tmp" && sha256sum "$name" >"$name.sha256")
cp "$tmp/$name" "$tmp/$name.sha256" "$DEST/" || { notify backup "copy to $DEST failed"; exit 1; }
(cd "$DEST" && sha256sum --quiet -c "$name.sha256") || { notify backup "backup $name failed its checksum"; exit 1; }
if [ -n "${BACKUP_REMOTE:-}" ]; then
  if command -v rclone >/dev/null && [[ "$BACKUP_REMOTE" != *@* ]]; then
    rclone copy "$DEST/$name" "$BACKUP_REMOTE" && rclone copy "$DEST/$name.sha256" "$BACKUP_REMOTE" \
      || notify backup "off-machine copy to $BACKUP_REMOTE failed"
  else
    scp -q -o BatchMode=yes "$DEST/$name" "$DEST/$name.sha256" "$BACKUP_REMOTE" \
      || notify backup "off-machine copy to $BACKUP_REMOTE failed"
  fi
fi
# Keep the newest BACKUP_KEEP.
ls -1t "$DEST/$PREFIX"-*.tar.gz 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" | while read -r old; do
  rm -f "$old" "$old.sha256"
done
touch "$STATE/backup.last"
echo "backup: $DEST/$name (${#files[@]} items, verified)"
