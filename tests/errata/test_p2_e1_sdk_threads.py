"""Erratum E-1 (ERRATA.md): the Part 2 SDK deadlocked when one `Database` was used from several
threads. Found by the clean-room tester of fair-testing run 20261008T164154Z-p2-42fc06df
(docs/FAIR_TESTING.md), test `test_concurrent_reader_sees_all_or_nothing`.

The threads run in a child process with a time limit, so a deadlock fails this test instead of
hanging the suite.
"""

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SMALL = ROOT / "golden/p1_partition_small.svp"
N, BATCH = 40, 4

CHILD = r"""
import json, sys, threading
from sever_db_p2 import Database

data, keys, art = sys.argv[1:4]
n, batch = int(sys.argv[4]), int(sys.argv[5])


def unit(i):
    v = [0.0] * 16  # the small artefact has d = 16 (golden/p1_partition_small.json)
    v[i % 16] = 1.0
    return v


with Database.open(data, keys) as db:
    cid = db.create_collection(art, spawn_target=8)
    ids = [f"r{i:02d}" for i in range(n)]
    for i, r in enumerate(ids):
        db.insert(cid, r, unit(i))
    stop, seen, errors = threading.Event(), [], []

    def reader():
        try:
            while not stop.is_set():
                seen.append(sorted(r for r, _ in db.search(cid, unit(0), k=n)))
        except BaseException as e:  # noqa: BLE001
            errors.append(type(e).__name__)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for k in range(0, n, batch):
            db.delete_user(cid, ids[k : k + batch])
    finally:
        stop.set()
        for t in threads:
            t.join()
    print(json.dumps({"seen": seen, "errors": errors}))
"""


@pytest.mark.spec("SR-12.5-1", "SR-12.5-2")
# oracle: §12.5: searches take a shared lock while one writer runs; a reader sees the state before
# or after a deletion, never a mix. Expected states written by hand: the first 4·j records deleted.
@pytest.mark.oracle("A", "§12.5 concurrent readers and one writer; all-or-nothing deletion")
def test_p2_errata_e1_sdk_searches_from_threads_during_delete_user() -> None:
    base = ROOT / "target/errata" / uuid.uuid4().hex
    base.mkdir(parents=True)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "python"), PYTHONHASHSEED="0")
    try:
        r = subprocess.run(
            [sys.executable, "-c", CHILD, str(base / "data"), str(base / "keys"), str(SMALL),
             str(N), str(BATCH)],
            capture_output=True, text=True, timeout=60, env=env, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        pytest.fail("the SDK deadlocked: searches from threads during delete_user never returned")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["errors"] == []
    ids = [f"r{i:02d}" for i in range(N)]
    allowed = [ids[k:] for k in range(0, N + 1, BATCH)]  # §12.5: never a partial delete_user
    assert out["seen"], "no search completed"
    assert all(s in allowed for s in out["seen"])
