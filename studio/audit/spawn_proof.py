"""Run: uv run --project studio --no-sync python studio/audit/spawn_proof.py COPY_OF_studio-nq (on ext4).
Is a spawned group the engine's? Every value below is read from the engine (receipt, export_log,
group_sizes, events) or worked out here from §7.5 and the dataset; nothing comes from Studio's math."""
import hashlib, json, sys
from pathlib import Path
import numpy as np
ROOT = Path.home() / "sever-db"
sys.path[:0] = [str(ROOT / "python"), str(ROOT / "studio")]
from sever_studio.actions import Studio
s = Studio(ROOT, "nq", Path(sys.argv[1]), dev=True, rows=10_000); s.open()
b, db, cid = s.backend, s.backend.live, s.backend.cid
seen = len(db.events(0))
out = s.fill_bucket("flush")
last = out[-1]
print(f"1. inserted {len(out)} passages; the engine's receipt for the last one says placement = {last.placement}")
g = last.placement
log = json.loads(db.export_log())
pl = log["placements"]
i = next(i for i in range(len(pl) - 1, -1, -1) if pl[i]["flush"])
print(f"2. the engine's public log, leaf #{i}: group={pl[i]['group']!r} flush={pl[i]['flush']!r}")
# founders from the engine's log: inserts placed in the holding area since the previous flush, not deleted
lsn_rid = {rec.lsn: rid for rid, rec in b.index.records.items() if rec.lsn is not None}
lsn_rid.update({r.lsn: r.rid for r in out})
prev = max((j for j in range(i) if pl[j]["flush"]), default=-1)
deleted = set()
for j, h in enumerate(log["leaves"]):
    leaf = bytes.fromhex(h)
    if leaf[0] == 2:  # a deletion leaf names the record by its scrambled ID (§11.1 tag 9)
        deleted.add(j)
held = [j for j in range(prev + 1, i) if pl[j]["group"] == "holding" and pl[j].get("flush") is None]
sid = {j: bytes.fromhex(log["leaves"][j])[17:81] for j in range(len(log["leaves"])) if bytes.fromhex(log["leaves"][j])[0] == 1}
gone = set()
for j in deleted:
    cert = bytes.fromhex(log["leaves"][j])[1:]
    at = 0
    while at + 5 <= len(cert):
        t, ln = cert[at], int.from_bytes(cert[at+1:at+5], "big")
        if t == 9: gone.add(cert[at+5:at+5+ln])
        at += 5 + ln
founders = [lsn_rid[j] for j in held if sid[j] not in gone] + [lsn_rid[i]]
print(f"3. founders read from the engine's log: {len(founders)} records")
h = hashlib.sha256()
for r in sorted(f.encode() for f in founders):
    h.update(len(r).to_bytes(2, "big") + r)
print(f"4. §7.5 ID worked out here: spawn-{h.hexdigest()[:16]}  engine: {g}  equal: {'spawn-' + h.hexdigest()[:16] == g}")
n = dict(db.group_sizes(cid))[g]
print(f"5. the engine's group_sizes: {g} n = {n}")
ev = [e for e in db.events(seen) if e["created"]]
mu_engine = np.array(ev[-1]["created"][0][1], np.float64)
print(f"6. the engine's own event (DB-107) created {ev[-1]['created'][0][0]} with its centroid")
X = np.stack([b.vector_of(r) for r in founders]).astype(np.float64)
xt = np.rint(X * 2.0**24).astype(np.int64)            # §4.2, ties to even
mu_spec = (xt.sum(axis=0).astype(np.float64) / 2.0**24) / len(founders)   # §7.5
print(f"7. §7.5 centroid worked out here from the dataset vectors equals the engine's, bit for bit: {np.array_equal(mu_spec, mu_engine)}")
print(f"   first 3: engine {mu_engine[:3]}  here {mu_spec[:3]}")
b.close()
