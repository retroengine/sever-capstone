#!/usr/bin/env bash
# scripts/hpc/fetch-data.sh [FILE] — puts the data bundle into the repository and verifies it.
# The bundle is sever-hpc.zip (from OneDrive or a USB stick; it holds sever-data.tar and its
# .sha256) or sever-data.tar with sever-data.tar.sha256 beside it. Without FILE it looks in the
# Windows Downloads, Desktop and OneDrive Desktop folders and on USB drives (/mnt/d … /mnt/z).
# It unpacks datasets/processed/, artefacts/ and the 10 trace files, then checks
# datasets/MANIFEST.sha256. The repository's own files are never overwritten.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
cd "$REPO"
f=${1:-}
if [ -z "$f" ]; then
  w=$(windows_user || true)
  for d in "/mnt/c/Users/$w/Downloads" "/mnt/c/Users/$w/Desktop" "/mnt/c/Users/$w/OneDrive/Desktop" \
           "/mnt/c/Users/$w/Downloads/sever-hpc" /mnt/[d-z] /mnt/[d-z]/sever-hpc; do
    for n in sever-hpc.zip sever-data.tar; do [ -f "$d/$n" ] && { f="$d/$n"; break 2; }; done
  done
fi
[ -n "$f" ] && [ -f "$f" ] || { echo "no bundle found: download sever-hpc.zip into Windows Downloads, or give its path"; exit 1; }
echo "bundle: $f ($(du -h "$f" | cut -f1))"

work="$REPO/.bundle-tmp"; rm -rf "$work"; mkdir -p "$work"; trap 'rm -rf "$work"' EXIT
case "$f" in
  *.zip)
    python3 - "$f" "$work" <<'PY'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
want = [n for n in z.namelist() if n.endswith(("sever-data.tar", "sever-data.tar.sha256"))]
if len(want) != 2: sys.exit("the zip does not hold sever-data.tar and its .sha256")
for n in want:
    with z.open(n) as src, open(f"{sys.argv[2]}/{n.rsplit('/', 1)[-1]}", "wb") as dst:
        while chunk := src.read(1 << 22): dst.write(chunk)
PY
    ;;
  *.tar) cp "$f" "$work/"; cp "$f.sha256" "$work/" ;;
  *) echo "expected sever-hpc.zip or sever-data.tar"; exit 1 ;;
esac
(cd "$work" && sha256sum -c sever-data.tar.sha256) || { echo "the bundle is damaged: download it again"; exit 1; }
# Only data paths are unpacked, and nothing tracked by git is replaced.
tar tf "$work/sever-data.tar" | grep -vE '^(datasets/processed|artefacts|traces)(/|$)' && { echo "unexpected paths in the bundle"; exit 1; }
tar xf "$work/sever-data.tar" --skip-old-files
(cd datasets && sha256sum --quiet -c MANIFEST.sha256) && echo "fetch-data: DATA OK"
