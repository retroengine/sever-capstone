"""Audit 2 (23 Oct 2026): each suspicion run, not argued. Run on a COPY of a synthetic work dir
(on ext4):  uv run --project studio --no-sync python studio/audit/audit2.py COPY
Prints one line per experiment: what Studio says, and what is actually true."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "python"), str(ROOT / "studio")]

from sever_studio import explain, proofs, tools, wow  # noqa: E402
from sever_studio.actions import Studio  # noqa: E402

s = Studio(ROOT, "synthetic", Path(sys.argv[1]), dev=True, rows=120)
s.open()
b = s.backend

# E1: on synthetic, "your own text, encoded by the pinned model" ticks with a hash stand-in
a = s.add_mine("Audit Person", "any words at all")
v = s.checklist.verdicts["freetext"]
print(f"E1 freetext ticked={v.ok} source={v.source!r}; encoder used: {s.corpus.encoder}")

# E2: on synthetic, "one encoder" ticks by comparing three name strings, no re-encoding
s.encoder_check()
v = s.checklist.verdicts["encoder"]
print(f"E2 encoder ticked={v.ok}: {v.detail}")

# E3: the witnesses live in the database's own key directory (simulated, §10.4, L-7)
keys = sorted(p.name for p in b.keys.iterdir())
anchors = json.loads(b.live.anchors())
print(f"E3 key dir holds {keys}; anchors list {len(anchors['witnesses'])} witnesses")

# E4: the climb counts cosignatures; it never checks one. Corrupt a cosignature's signature bytes
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
bad = wow.parse(bytes(cert))
steps, root, valid = wow.climb(bad.leaf, bad.leaf_index, bad.tree_size, bad.path)
folder = s.work / "audit2-climb"
folder.mkdir(exist_ok=True)
(folder / "certificate.bin").write_bytes(bytes(cert))
(folder / "anchors.json").write_text(b.live.anchors(), "utf-8")
code, out = tools.run(
    [tools.build(ROOT).verify, "certificate.bin", "--anchors", "anchors.json"], folder
)
print(
    f"E4 corrupted cosignature: Studio's climb says valid={valid and root == bad.root}, "
    f"{bad.witnesses} witnesses cosigned; sever-verify says: {out.splitlines()[-1]}"
)

# E5: Part 4's "every certificate verifies" passes on output that says the opposite
text = (
    "SEVER-DB Part 4: the erasure\n1. Positive control: the scanner RECOVERS x.\n"
    "2. delete_user: certificate 1: verify FAILED.\n3. Checkpoint: 0 findings.\n"
    "5. Crash during phase C: 0 findings."
)
print(f"E5 erase checks on a 'verify FAILED' output: {proofs._erase({}, text)[1]}")

# E6: the deletion diagram states key rotation and C_t without observing either
flow = dict(explain.delete_flow(s, d))
print(f"E6 delete_flow says: Keys -> {flow['Keys'][:60]}...; it reads no key file")
b.close()
