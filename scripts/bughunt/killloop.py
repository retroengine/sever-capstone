"""SIGKILL loop against the final SDK (bug hunt BH-5, workstream 2). Synthetic vectors only.

Run from the repo root (ROOT on ext4, absolute, not existing yet):
  REPO=$PWD PYTHONHASHSEED=0 PYTHONPATH=python .venv/bin/python scripts/bughunt/killloop.py \
    $PWD/target/bh/kill-42 30 42
parent: python killloop.py ROOT ROUNDS SEED
child:  python killloop.py --child ROOT SEED
Journal lines: "B <op> <ids>" before the call, "A <op> <ids> <result>" after it returned.
"""

import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from sever_db import Database, DuplicateRecord, UserKey, prepare_insert

REPO = Path(os.environ["REPO"])
ART = REPO / "golden/p1_partition_small.svp"
D = 16


def vec(rid: str) -> list[float]:
    g = np.random.default_rng(abs(hash(rid)) % (2**32))
    v = g.standard_normal(D)
    return (v / np.linalg.norm(v)).tolist()


def opendb(root: Path) -> Database:
    return Database.open(root / "data", root / "keys", d=D, allow_unsafe_memory=True)


def journal_append(root: Path, line: str) -> None:
    with open(root / "journal", "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def child(root: Path, seed: int) -> None:
    rng = random.Random(seed)
    meta = json.loads((root / "meta.json").read_text())
    cid, user = meta["cid"], UserKey.from_secret_bytes(bytes.fromhex(meta["user"]))
    live = set(replay(root)[0])
    nxt = int(meta.get("next", 0)) + seed * 100000
    db = opendb(root)
    while True:
        r = rng.random()
        if r < 0.6 or len(live) < 5:
            rid = f"r{nxt}"
            nxt += 1
            journal_append(root, f"B I {rid}")
            rec = db.insert(cid, prepare_insert(cid, rid, vec(rid), user), passage=rid.encode())
            journal_append(root, f"A I {rid} {rec.retried}")
            live.add(rid)
        elif r < 0.85:
            rid = rng.choice(sorted(live))
            journal_append(root, f"B D {rid}")
            out = db.delete(cid, rid)
            journal_append(root, f"A D {rid} {out.outcome}")
            live.discard(rid)
        elif r < 0.97:
            ids = rng.sample(sorted(live), min(len(live), rng.randint(2, 6)))
            journal_append(root, f"B U {','.join(ids)}")
            outs = db.delete_user(cid, ids)
            journal_append(root, f"A U {','.join(ids)} {len(outs)}")
            live.difference_update(ids)
        else:
            journal_append(root, "B C -")
            db.checkpoint()
            journal_append(root, "A C -")


def replay(root: Path) -> tuple[list[str], str | None]:
    """The live set from acknowledged ops, and the op in flight (a B without its A), if any."""
    live: set[str] = set()
    pending = None
    p = root / "journal"
    lines = p.read_text().splitlines() if p.exists() else []
    for line in lines:
        kind, op, ids = line.split()[:3]
        if kind == "B":
            pending = f"{op} {ids}"
            continue
        pending = None
        if op == "I":
            live.add(ids)
        elif op == "D":
            live.discard(ids)
        elif op == "U":
            live.difference_update(ids.split(","))
    return sorted(live), pending


def resolve(root: Path, db: Database, cid: str, user: UserKey) -> str:
    """Retries the op in flight (§15.8: a lost answer is retried); journals it as acknowledged."""
    _, pending = replay(root)
    if pending is None:
        return "none"
    op, ids = pending.split()
    if op == "I":
        try:
            rec = db.insert(cid, prepare_insert(cid, ids, vec(ids), user), passage=ids.encode())
            res = f"I inserted-now lsn={rec.database_lsn}"
        except DuplicateRecord:
            res = "I was-committed"
        journal_append(root, f"A I {ids} resolved")
    elif op == "D":
        res = f"D {db.delete(cid, ids).outcome}"
        journal_append(root, f"A D {ids} resolved")
    elif op == "U":
        res = f"U {len(db.delete_user(cid, ids.split(',')))}"
        journal_append(root, f"A U {ids} resolved")
    else:
        journal_append(root, "A C -")
        res = "C"
    return res


def check(root: Path, db: Database, cid: str) -> tuple[int, int]:
    live, _ = replay(root)
    st = db.stats(cid)
    total = st["N"] + st["holding"]
    return total, len(live)


def parent(root: Path, rounds: int, seed: int) -> int:
    rng = random.Random(seed)
    root.mkdir(parents=True, exist_ok=False)
    user = UserKey.generate()
    with opendb(root) as db:
        cid = db.create_collection(ART, spawn_target=8)
    (root / "meta.json").write_text(json.dumps({"cid": cid, "user": user.secret_bytes().hex()}))
    bad = 0
    for i in range(rounds):
        p = subprocess.Popen([sys.executable, __file__, "--child", str(root), str(seed * 1000 + i)])
        time.sleep(rng.uniform(0.05, 2.5))
        p.send_signal(signal.SIGKILL)
        p.wait()
        try:
            with opendb(root) as db:
                res = resolve(root, db, cid, user)
                total, want = check(root, db, cid)
        except Exception as e:
            print(f"round {i}: OPEN/CHECK FAILED {type(e).__name__}: {e}", flush=True)
            return 1
        ok = total == want
        bad += not ok
        print(
            f"round {i}: resolved={res} stored={total} journal={want} {'ok' if ok else 'MISMATCH'}",
            flush=True,
        )
        if not ok:
            return 1
    # Final: every live record deletes, every other one is absent.
    live, _ = replay(root)
    with opendb(root) as db:
        outs = [db.delete(cid, r).outcome for r in live]
        st = db.stats(cid)
    print(
        f"final: deleted {outs.count('deleted')}/{len(live)}, other outcomes "
        f"{sorted(set(outs) - {'deleted'})}, stats after {st}",
        flush=True,
    )
    return 0 if outs.count("deleted") == len(live) and st["N"] + st["holding"] == 0 else 1


if __name__ == "__main__":
    if sys.argv[1] == "--child":
        child(Path(sys.argv[2]), int(sys.argv[3]))
    else:
        raise SystemExit(parent(Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])))
