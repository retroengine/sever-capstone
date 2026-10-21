"""Edge inputs through the final SDK (bug hunt, workstream 6). Synthetic vectors only.

PYTHONHASHSEED=0 PYTHONPATH=python .venv/bin/python scripts/bughunt/edges.py $PWD $PWD/target/bh/e
"""

import math
import shutil
import sys
from pathlib import Path

import numpy as np

from sever_db import Database, UserKey, prepare_insert

REPO, ROOT = Path(sys.argv[1]), Path(sys.argv[2])
shutil.rmtree(ROOT, ignore_errors=True)
db = Database.open(ROOT / "data", ROOT / "keys", d=16, allow_unsafe_memory=True)
cid = db.create_collection(REPO / "golden/p1_partition_small.svp", spawn_target=8)
u = UserKey.generate()


def unit(i):
    v = np.random.default_rng(i).standard_normal(16)
    return (v / np.linalg.norm(v)).tolist()


def tryit(label, f, expect):
    try:
        f()
        got = "ok"
    except Exception as e:
        got = type(e).__name__
    flag = "" if got == expect else "   <-- UNEXPECTED"
    print(f"{label:<44} expect {expect:<16} got {got:<16}{flag}")


def ins(rid: str, v: list[float] | None = None) -> object:
    return db.insert(cid, prepare_insert(cid, rid, v or unit(len(rid)), u))


tryit("1-byte id", lambda: ins("a"), "ok")
tryit("256-byte id", lambda: ins("x" * 256), "ok")
tryit("257-byte id", lambda: ins("y" * 257), "InvalidRecordId")
tryit("256 bytes as 128 two-byte chars", lambda: ins("é" * 128), "ok")
tryit("257 bytes (128 é + 1)", lambda: ins("é" * 128 + "z"), "InvalidRecordId")
tryit("empty id", lambda: ins(""), "InvalidRecordId")
for rid in ["123", "+5", "-0", "007", "12a", " 12", "12\n", "1.5", "١٢٣"]:
    exp = "InvalidRecordId" if rid in ("123", "+5", "-0", "007") else "ok"
    tryit(f"id {rid!r}", lambda rid=rid: ins(rid), exp)
tryit("lone surrogate id", lambda: ins("\udc80"), "InvalidRecordId")
tryit("NaN component", lambda: ins("nan1", [math.nan] + [0.0] * 15), "NonFinite")
tryit("inf component", lambda: ins("inf1", [math.inf] + [0.0] * 15), "NonFinite")
tryit("not unit (0.9)", lambda: ins("n09", [0.9] + [0.0] * 15), "NotNormalised")
tryit("zero vector", lambda: ins("z0", [0.0] * 16), "NotNormalised")
tryit("wrong d (17)", lambda: ins("d17", [1.0] + [0.0] * 16), "WrongDimension")
tryit(
    "unknown collection",
    lambda: db.insert("0" * 32, prepare_insert("0" * 32, "q", unit(1), u)),
    "UnknownCollection",
)
tryit("bad cid text", lambda: db.stats("xyz"), "UnknownCollection")
st = db.stats(cid)
print("stats", st)
for rid in ["a", "x" * 256, "é" * 128, "12a", " 12", "12\n", "1.5", "١٢٣"]:
    tryit(f"delete {rid[:10]!r}", lambda rid=rid: db.delete(cid, rid).outcome, "ok")
tryit("delete absent", lambda: db.delete(cid, "never"), "ok")
print("after deleting every record", db.stats(cid))
db.close()
tryit("use after close", lambda: db.stats(cid), "SeverError")
db2 = Database.open(ROOT / "data", ROOT / "keys", d=16, allow_unsafe_memory=True)
print("reopen stats", db2.stats(cid))
db2.close()
