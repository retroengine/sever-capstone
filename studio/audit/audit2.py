"""Audit 2 (23 Oct 2026), re-run after Stage 6 (6 Nov 2026, DB-119): each suspicion run, not argued.
Run on a COPY of a synthetic work dir (on ext4), through studio.sh's environment:

    PYTHONPATH=studio/vendor/site:studio uv run --project studio --no-sync \\
        python studio/audit/audit2.py COPY

Prints one line per experiment: what Studio says now, and what is actually true."""

import json
import sys
from pathlib import Path

from sever_studio import config, explain, tools, wow
from sever_studio.actions import Studio

cfg = config.load()
s = Studio(cfg, "synthetic", Path(sys.argv[1]), dev=True, rows=120)
s.open()
b = s.backend

# E1: on synthetic, "your own text, encoded by the pinned model" ticked with a hash stand-in
s.add_mine("Audit Person", "any words at all")
v = s.checklist.verdicts.get("freetext")
print(f"E1 freetext verdict on synthetic: {v} (fixed when None: never ticks offline, H1)")

# E2: on synthetic, "one encoder" ticked by comparing three name strings
s.encoder_check()
v = s.checklist.verdicts.get("encoder")
print(f"E2 encoder verdict on synthetic: {v} (fixed when None, H1)")

# E3: the witnesses live in the database's own key directory (simulated, §10.4, L-7)
keys = sorted(p.name for p in b.keys.iterdir())
anchors = json.loads(b.live.anchors())
from sever_studio.ui import copy  # noqa: E402

said = "simulated" in copy.long("log.about")
print(
    f"E3 key dir holds {keys}; anchors list {len(anchors['witnesses'])} witnesses; "
    f"the log screen says simulated: {said}"
)

# E4: the climb counted cosignatures without checking one; is any climb left?
s.fill_bucket("one")
rid = next(r for r, rec in b.index.records.items() if rec.group != "holding" and not rec.mine)
d = s.delete([rid])
cert = bytearray((b.receipts / f"{d.lsns[0]}.cert").read_bytes())
at, t7 = 0, None
while cert[at] != 0xFF:
    tag, ln = cert[at], int.from_bytes(cert[at + 1 : at + 5], "big")
    if tag == 7:
        t7 = (at + 5, ln)
    at += 5 + ln
assert t7 is not None
cert[t7[0] + t7[1] - 1] ^= 0x01  # the last byte of the last cosignature's signature
folder = s.work / "audit2-climb"
folder.mkdir(exist_ok=True)
(folder / "certificate.bin").write_bytes(bytes(cert))
(folder / "anchors.json").write_text(b.live.anchors(), "utf-8")
code, out = tools.run([tools.of(cfg).verify, "certificate.bin", "--anchors", "anchors.json"], folder)
print(
    f"E4 Studio has a climb: {hasattr(wow, 'climb')} (removed, H2); "
    f"sever-verify on a corrupted cosignature says: {out.splitlines()[-1]}"
)

# E5: Part 4's "every certificate verifies" passed on output that said the opposite
import importlib.util  # noqa: E402

print(
    "E5 the part-program parser exists: "
    f"{importlib.util.find_spec('sever_studio.proofs') is not None} (removed, H3)"
)

# E6: the deletion diagram stated key rotation and C_t without observing either
line = explain.deleted_line(d)
print(f"E6 Studio says after a deletion: {line!r}; unobserved words in it: "
      f"{[w for w in ('key', 'overwritten', 'C_S', 'witness') if w in line]}")
b.close()
