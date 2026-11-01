"""Crashes at random moments (§15.1, §15.3, §15.4, §15.7, §15.8): a process is SIGKILLed while it
works; after reopening, the state must be one the spec allows."""

import json
import os
import random
import signal
import time

import pytest

import helpers as h
import sevlib

# Seconds between "go" and SIGKILL (jittered per test): from at once to well into the work.
DELAYS = [0.0, 0.005, 0.02, 0.05, 0.12, 0.3, 0.7]

CHILD_HEAD = """
import json, sys
import sever_db_p3 as s
db = s.Database.open({data!r}, {keys!r}, d=16)
print("ready", flush=True)
sys.stdin.readline()
"""


def run_and_kill(env, body, delay, **fmt):
    """Starts the child, waits until it has opened the database, lets it work for `delay` seconds,
    then SIGKILLs it. Returns its stdout lines (acknowledgements printed before the kill)."""
    import subprocess
    import sys

    code = CHILD_HEAD.format(data=env.data, keys=env.keys) + body.format(**fmt)
    p = subprocess.Popen([sys.executable, "-u", "-c", code], cwd=env.root, text=True,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    first = p.stdout.readline()
    assert first.strip() == "ready", p.stderr.read()[-2000:]
    p.stdin.write("go\n")
    p.stdin.flush()
    time.sleep(delay)
    p.send_signal(signal.SIGKILL)
    out, _ = p.communicate(timeout=60)
    return [ln for ln in out.splitlines() if ln.strip()]


def setup_frozen(env, user, art, rng, n, prefix="k"):
    """A closed database with n records spread over the four frozen groups (leaves 0…n−1)."""
    db = h.open_db(env)
    cid = db.create_collection(h.SMALL)
    reqs = {}
    for i in range(n):
        rid = f"{prefix}-{i}"
        reqs[rid] = h.insert(db, cid, rid, sevlib.in_dist_vector(art, rng, i % 4), user)[0]
    db.close()
    return cid, reqs


INSERT_LOOP = """
user = s.UserKey.from_secret_bytes(bytes.fromhex({secret!r}))
for rid, vec in json.loads({items!r}):
    rec = db.insert({cid!r}, s.prepare_insert({cid!r}, rid, vec, user))
    print("ack", rid, rec.database_lsn, flush=True)
print("done", flush=True)
"""


@pytest.mark.req("SR-15.1-2", "SR-15.8-1", "SR-10.2-3")
@pytest.mark.parametrize("seed", range(len(DELAYS)))
def test_killed_insert_stream_keeps_exactly_a_prefix(user, art16, seed):
    """§15.1: "A crash before the `COMMIT` is durable leaves the database unchanged ... A crash
    after it leaves the insert done." §15.8: an acknowledged insert is durable. So after a kill the
    live records are the acknowledged ones plus at most the one in flight, and the log holds one
    leaf per live record (no orphaned leaf, P3-T4)."""
    rng = __import__("numpy").random.default_rng(1000 + seed)
    env = h.Env()
    db = h.open_db(env)
    cid = db.create_collection(h.SMALL)
    db.close()
    items = [(f"s-{i:03d}", sevlib.in_dist_vector(art16, rng, i % 4)) for i in range(300)]
    delay = DELAYS[seed] * random.Random(seed).uniform(0.8, 1.25)
    lines = run_and_kill(env, INSERT_LOOP, delay, secret=user.secret_bytes().hex(),
                         items=json.dumps(items), cid=cid)
    acked = [ln.split() for ln in lines if ln.startswith("ack")]
    # Each acknowledged insert got the next leaf: 0, 1, 2, … (§10.2).
    assert [int(a[2]) for a in acked] == list(range(len(acked)))
    db = h.open_db(env)
    try:
        live = h.total_group_n(db, cid)  # every record went to a frozen group (§7.3)
        assert len(acked) <= live <= min(len(acked) + 1, len(items))
        # The live records are exactly the first `live` of the stream, and the log holds
        # exactly `live` leaves, so their deletions take leaves live, live + 1, … (§10.2).
        for j, (rid, _) in enumerate(items[:live]):
            out = db.delete(cid, rid)
            assert out.outcome == "deleted" and out.database_lsn == live + j
            if j == 0:
                ok, step = sevlib.verify_certificate(out.certificate, h.anchors(db))
                assert ok, step
        if live < len(items):
            assert db.delete(cid, items[live][0]).outcome == "absent"
        if live == 0:
            assert h.next_lsn(db, cid, user, art16, rng) == 0
    finally:
        h.quiet_close(db)


DELETE_USER = """
outs = db.delete_user({cid!r}, json.loads({ids!r}))
print("done", json.dumps([o.database_lsn for o in outs]), flush=True)
"""


@pytest.mark.req("SR-15.3-5", "SR-15.4-1", "SR-15.8-1")
@pytest.mark.parametrize("seed", range(len(DELAYS)))
def test_killed_delete_user_is_all_or_nothing(user, art16, seed):
    """§15.3: `delete_user` commits "one transaction"; §16.1: "one transaction". A kill leaves
    either every record of the cohort deleted, with every certificate retrievable, or none deleted,
    with no certificate and no leaf (DB-24: "no certificate for a rolled-back deletion, no orphaned
    leaf")."""
    rng = __import__("numpy").random.default_rng(2000 + seed)
    env = h.Env()
    total = 90
    cid, reqs = setup_frozen(env, user, art16, rng, total)  # leaves 0–89
    cohort = [f"k-{i}" for i in range(total) if i % 3 != 1]  # 60 records over all four groups
    delay = DELAYS[seed] * random.Random(seed).uniform(0.8, 1.25)
    lines = run_and_kill(env, DELETE_USER, delay, cid=cid, ids=json.dumps(cohort))
    done = any(ln.startswith("done") for ln in lines)
    db = h.open_db(env)
    try:
        live = h.total_group_n(db, cid)
        assert live in (total, total - len(cohort))  # all or nothing
        if done:
            assert live == total - len(cohort)  # acknowledged, so durable (§15.8)
        anchors = h.anchors(db)
        if live == total:
            # Rolled back: no certificate at the leaves the cohort would have taken, and the
            # next deletion takes leaf 90 (no orphaned leaf).
            assert all(db.certificate(total + i) is None for i in range(len(cohort)))
            out = db.delete(cid, cohort[0])
            assert out.outcome == "deleted" and out.database_lsn == total
        else:
            # Committed: one certificate per record at leaves 90, 91, … in list order.
            for i, rid in enumerate(cohort):
                raw = db.certificate(total + i)
                assert raw is not None
                c = h.cert(raw)
                assert c.c_t == reqs[rid].c_t and c.database_lsn == total + i
                ok, step = sevlib.verify_certificate(raw, anchors)
                assert ok, step
            assert db.delete(cid, cohort[0]).outcome == "absent"
    finally:
        h.quiet_close(db)


@pytest.mark.req("SR-15.1-2", "SR-15.4-1", "SR-15.3-5")
@pytest.mark.parametrize("seed", range(5))
def test_killed_cli_insert_then_delete(user, art16, seed):
    """§15.1 crash rule for the CLI playing the backend (§16.3 / API doc), then §15.4 for a
    killed CLI delete: "Before ... COMMIT is durable: Unchanged ... retrying is safe"; "After
    COMMIT: Deleted ... a retry returns `AlreadyAbsent`; the certificate is retrievable by
    `database_lsn`"."""
    rng = __import__("numpy").random.default_rng(3000 + seed)
    r = random.Random(seed)
    env = h.Env()
    db = h.open_db(env)
    cid = db.create_collection(h.SMALL)
    db.close()
    key = h.user_key_file()
    vec = h.vec_arg(sevlib.in_dist_vector(art16, rng, 2))

    def killed(*args):
        import subprocess

        cmd = [h.CLI, args[0], "--data", env.data, "--keys", env.keys, "--d", "16", *args[1:]]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(r.uniform(0.0, 0.5))
        p.send_signal(signal.SIGKILL)
        p.communicate(timeout=60)

    killed("insert", "--cid", cid, "--id", "cli-1", "--vector", vec, "--user-key", key)
    db = h.open_db(env)
    live = h.total_group_n(db, cid)
    assert live in (0, 1)
    if live == 0:
        assert db.delete(cid, "cli-1").outcome == "absent"
        db.close()
        assert h.cli(env, "insert", "--cid", cid, "--id", "cli-1", "--vector", vec,
                     "--user-key", key).returncode == 0  # retry is a normal insert (§15.1)
    else:
        db.close()
    # Now cli-1 is live at leaf 0. Kill a CLI delete.
    killed("delete", "--cid", cid, "--id", "cli-1")
    db = h.open_db(env)
    try:
        live = h.total_group_n(db, cid)
        assert live in (0, 1)
        if live == 1:
            assert db.certificate(1) is None  # no certificate for a rolled-back deletion
            out = db.delete(cid, "cli-1")
            assert out.outcome == "deleted" and out.database_lsn == 1  # no orphaned leaf
            raw = out.certificate
        else:
            assert db.delete(cid, "cli-1").outcome == "absent"
            raw = db.certificate(1)
            assert raw is not None
        c = h.cert(raw)
        assert c.leaf_index == 0 and c.database_lsn == 1
        ok, step = sevlib.verify_certificate(raw, h.anchors(db))
        assert ok, step
    finally:
        h.quiet_close(db)


DELETE_LOOP = """
for rid in json.loads({ids!r}):
    out = db.delete({cid!r}, rid)
    print("del", rid, out.database_lsn, flush=True)
"""


@pytest.mark.req("SR-15.3-5", "SR-15.8-1", "SR-5.3-2")
@pytest.mark.parametrize("seed", range(len(DELAYS)))
def test_killed_delete_stream_keeps_commitments_exact(user, art16, seed):
    """§5.3: all four fields "MUST change together in one transaction (INV-2)"; §15.8: an
    acknowledged deletion is durable. After a kill during a stream of deletions, the next
    certificate of each group starts from C_S = Σ C_t of exactly its live members."""
    rng = __import__("numpy").random.default_rng(4000 + seed)
    env = h.Env()
    total = 80
    cid, reqs = setup_frozen(env, user, art16, rng, total)  # twenty records per group
    order = [f"k-{i}" for i in range(total)]
    lines = run_and_kill(env, DELETE_LOOP, DELAYS[seed] * random.Random(seed).uniform(0.8, 1.25),
                         cid=cid, ids=json.dumps(order))
    acked = [ln.split()[1] for ln in lines if ln.startswith("del")]
    db = h.open_db(env)
    try:
        live_n = h.total_group_n(db, cid)
        assert total - len(acked) - 1 <= live_n <= total - len(acked)
        gone = set(order[: total - live_n])  # deletions happen in order
        assert set(acked) <= gone
        for rid in order:
            out = db.delete(cid, rid)
            if rid in gone:
                assert out.outcome == "absent"
                continue
            c = h.cert(out.certificate)
            label = int(rid.split("-")[1]) % 4
            members = [r for r in order if int(r.split("-")[1]) % 4 == label and r not in gone]
            assert c.cs_pre == sevlib.r_sum_enc([reqs[m].c_t for m in members])
            gone.add(rid)
    finally:
        h.quiet_close(db)
