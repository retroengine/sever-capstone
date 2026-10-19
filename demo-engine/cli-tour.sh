#!/usr/bin/env bash
# demo-engine/cli-tour.sh: the same story through the sever-db command-line tool, offline, on the
# golden fixture (d = 16, 4 frozen groups, spawn size 8). Every command opens the database (recovery
# and the invariant check run first), does one thing, prints one JSON line and closes.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
cd "$root"
work="$here/work/cli"
rm -rf "$work"
mkdir -p "$work/handed-to-the-person"
for ws in verifier audit; do
  [ -x "$ws/target/release/sever-$([ $ws = verifier ] && echo verify || echo audit)" ] \
    || (cd "$ws" && CARGO_TARGET_DIR="$root/$ws/target" cargo build -q --release --locked)
done
[ -x target/release/sever-db ] || cargo build -q --release --locked -p sever-db

dev=(--allow-unsafe-memory)
[ "${SEVER_STRICT:-0}" = 1 ] && dev=()
DB=(target/release/sever-db)
D=(--data "$work/data" --keys "$work/keys" --d 16 "${dev[@]}")
show() {
  printf '\n$ %s\n' "$*" | sed -E "s|$root/||g; s|$work|work/cli|g; s/\[[-0-9., e]{20,}\]/'[16 floats]'/g"
  "$@"
}
field() { python3 -c "import json,sys; print(json.loads(sys.stdin.read())$1)"; }
# The i-th unit vector of the fixture, as a JSON list.
vector() {
  python3 - "$1" <<'PY'
import json, struct, sys
doc = json.load(open("golden/p1_fixture_vectors.json"))
raw = bytes.fromhex(doc["ref"][int(sys.argv[1])])
print(json.dumps([round(x, 9) for x in struct.unpack("<16f", raw)]))
PY
}

echo "== 1. An account key for the application's user (kept by the backend, mode 0600)"
show "${DB[@]}" user-key --out "$work/alice.key"

echo; echo "== 2. A database and a collection over the partition artefact"
cid=$("${DB[@]}" create "${D[@]}" --artefact golden/p1_partition_small.svp --spawn-target 8 | field '["cid"]')
echo "cid = $cid"
show "${DB[@]}" verify "${D[@]}"

echo; echo "== 3. Insert six records with their passages"
for i in 0 1 2 3 4 5; do
  show "${DB[@]}" insert "${D[@]}" --cid "$cid" --id "note-$i" --vector "$(vector $i)" \
    --user-key "$work/alice.key" --passage "alice's note number $i"
done

echo; echo "== 4. Search with note-2's own vector, and the counts"
show "${DB[@]}" search "${D[@]}" --cid "$cid" --vector "$(vector 2)" --k 3
show "${DB[@]}" stats "${D[@]}" --cid "$cid"

echo; echo "== 5. Alice asks to be forgotten: delete her records in one transaction"
out=$("${DB[@]}" delete-user "${D[@]}" --cid "$cid" --ids '["note-0","note-1","note-2","note-3","note-4","note-5"]')
echo "$out" | python3 -c "
import json, sys
for o in json.loads(sys.stdin.read())['outcomes']:
    print(o['outcome'], 'at log position', o.get('database_lsn'), '| certificate', len(o.get('certificate', ''))//2, 'bytes')
    open(f\"$work/handed-to-the-person/{o['database_lsn']}.cert\", 'wb').write(bytes.fromhex(o['certificate']))
"
show "${DB[@]}" anchors "${D[@]}" --out "$work/handed-to-the-person/anchors.json" >/dev/null
show "${DB[@]}" search "${D[@]}" --cid "$cid" --vector "$(vector 2)" --k 3
show "${DB[@]}" delete "${D[@]}" --cid "$cid" --id note-2

echo; echo "== 6. Alice checks her receipts offline, with no database access"
cd "$work/handed-to-the-person"
for c in *.cert; do
  printf '%s: ' "$c"; "$root/verifier/target/release/sever-verify" "$c" --anchors anchors.json
done
cp "$(ls *.cert | head -1)" tampered.bin
python3 -c "b=bytearray(open('tampered.bin','rb').read()); b[len(b)//2]^=1; open('tampered.bin','wb').write(b)"
printf 'one flipped byte: '; "$root/verifier/target/release/sever-verify" tampered.bin --anchors anchors.json || echo "(exit $?: rejected)"
rm tampered.bin
cd "$root"

echo; echo "== 7. An auditor checks the public log and the receipts"
show "${DB[@]}" latest-checkpoint "${D[@]}"
"${DB[@]}" export-log "${D[@]}" --out "$work/log.json" >/dev/null
show audit/target/release/sever-audit "$work/log.json" --anchors "$work/handed-to-the-person/anchors.json" \
  $(for c in "$work"/handed-to-the-person/*.cert; do printf -- '--certificate %s ' "$c"; done)

echo; echo "Done. The database is in demo-engine/work/cli/ (data/, keys/); the receipts in"
echo "demo-engine/work/cli/handed-to-the-person/."
