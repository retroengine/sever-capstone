"""§15.4 crash table and §15.1 insert crashes, driven through the command-line tool (Part 4 API:
``sever-db insert|delete-user --data D --keys K ...``), killed with SIGKILL at random moments, then
reopened through the SDK. The CLI's default dimension is v1's d = 384 (§2.2), so these tests use the
384-dimensional artefact."""

import json
import os
import random
import signal
import subprocess
import time

import pytest

import helpers as h
from sever_db import Deletion

BIG = h.art(h.BIG_SVP)
COHORT = ["ck-a1", "ck-a2", "ck-b1"]  # a* → frozen-0005, b* → frozen-0040
GROUP_OF = {"ck-a1": 5, "ck-a2": 5, "ck-b1": 40, "ck-keep": 5}
VEC = {rid: h.in_dist(GROUP_OF[rid], s, BIG) for s, rid in enumerate(GROUP_OF)}


def _setup(root, user):
    """A closed d = 384 database with the cohort plus one survivor, created through the SDK."""
    data, keys = h.new_dirs(root)
    db = h.open_db(data, keys, d=384)
    cid = db.create_collection(h.BIG_SVP)
    for rid, x in VEC.items():
        assert h.insert(db, cid, rid, x, user).placement == h.frozen_id(GROUP_OF[rid])
    db.close()
    return data, keys, cid


def _kill_after(args, delay):
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(delay)
    p.send_signal(signal.SIGKILL)
    p.wait()
    return p.returncode


def _full_run_seconds(root, user, args_for):
    """Duration of one complete, unkilled run on a twin database (the kill window)."""
    data, keys, cid = _setup(os.path.join(root, "twin"), user)
    t = time.monotonic()
    r = h.run_cli(args_for(data, keys, cid))
    dt = time.monotonic() - t
    assert r.returncode == 0, r.stderr[-2000:]
    return data, keys, cid, dt


@pytest.mark.req("SR-15.4-2", "SR-15.4-3", "SR-15.4-4", "SR-15.4-5", "SR-15.4-6", "SR-12.5-2",
                 "SR-15.3-11", "SR-13.4-3")
@pytest.mark.parametrize("seed", range(6))
def test_sigkill_delete_user_all_or_nothing(root, user, seed):
    """§15.4: every crash point leaves either "Unchanged" or "Deleted"; §12.5: delete_user is "one
    transaction: all or nothing"; §13.4: recovery leaves only the active slot of every domain."""
    os.mkdir(os.path.join(root, "twin"))
    os.mkdir(os.path.join(root, "run"))

    def args_for(data, keys, cid):
        return h.cli_args("delete-user", data, keys, "--cid", cid, "--ids", json.dumps(COHORT))

    tdata, tkeys, tcid, full = _full_run_seconds(root, user, args_for)
    # The completed twin: every cohort record gone, the survivor kept.
    db = h.open_db(tdata, tkeys, d=384)
    assert h.sizes(db, tcid)[h.frozen_id(5)] == 1 and h.sizes(db, tcid)[h.frozen_id(40)] == 0
    db.close()

    data, keys, cid = _setup(os.path.join(root, "run"), user)
    c = bytes.fromhex(cid)
    before = h.active_slots(keys)
    delay = random.Random(seed).uniform(0.0, full * 1.1)
    _kill_after(args_for(data, keys, cid), delay)

    db = h.open_db(data, keys, d=384)  # recovery (§15.7)
    try:
        h.assert_keys_well_formed(keys)  # §13.4: orphans and old slots erased
        after = h.active_slots(keys)
        s = h.sizes(db, cid)
        if s[h.frozen_id(40)] == 1:  # unchanged (crash before COMMIT was durable)
            assert s[h.frozen_id(5)] == 3  # ...for every record of the cohort
            for g in (5, 40):
                # §15.4 rows 1–2: "Old group key: Present" and still active (same version, key).
                assert after[(c, h.frozen_id(g))][2] == before[(c, h.frozen_id(g))][2]
            # Retrying is safe: one transaction deletes all three.
            assert [o.outcome for o in db.delete_user(cid, COHORT)] == ["deleted"] * 3
        else:  # deleted (crash after COMMIT)
            assert s[h.frozen_id(40)] == 0 and s[h.frozen_id(5)] == 1
            blob = open(h.keys_path(keys), "rb").read()
            for g in (5, 40):
                old = before[(c, h.frozen_id(g))][2]
                new = after[(c, h.frozen_id(g))][2]
                assert new.version == old.version + 1  # one rotation per affected domain
                assert old.key not in blob  # recovery erased the old key (§15.4 rows 3–5)
            # "a retry returns AlreadyAbsent" (§15.4).
            assert db.delete_user(cid, COHORT) == [Deletion("absent")] * 3
        # Untouched domains never rotate.
        for (cc, g), v in before.items():
            if g not in (h.frozen_id(5), h.frozen_id(40)):
                assert after[(cc, g)] == v
        assert "ck-keep" in h.ids_in(db.search(cid, [float(v) for v in VEC["ck-keep"]], k=5))
    finally:
        db.close()
    # §15.7 step 3 (G-43): a clean close (storage checkpoint) after recovery and a second reopen work.
    db = h.open_db(data, keys, d=384)
    try:
        assert h.sizes(db, cid)[h.frozen_id(40)] == 0
        assert h.sizes(db, cid)[h.frozen_id(5)] == 1
    finally:
        db.close()
    h.assert_keys_well_formed(keys)


@pytest.mark.req("SR-15.1-2", "SR-13.4-3")
@pytest.mark.parametrize("seed", range(4))
def test_sigkill_insert_is_atomic(root, user, seed):
    """§15.1: "A crash before the COMMIT is durable leaves the database unchanged ... A crash after it
    leaves the insert done"."""
    os.mkdir(os.path.join(root, "twin"))
    os.mkdir(os.path.join(root, "run"))
    ukey = os.path.join(root, "user.key")
    r = h.run_cli([h.CLI, "user-key", "--out", ukey])
    assert r.returncode == 0, r.stderr[-2000:]
    x = h.in_dist(77, 3, BIG)

    def args_for(data, keys, cid):
        return h.cli_args(
            "insert", data, keys, "--cid", cid, "--id", "cli-new",
            "--vector", json.dumps([float(v) for v in x]), "--user-key", ukey, "--passage", "text",
        )

    tdata, tkeys, tcid, full = _full_run_seconds(root, user, args_for)
    db = h.open_db(tdata, tkeys, d=384)
    assert h.sizes(db, tcid)[h.frozen_id(77)] == 1  # the completed run inserted into frozen-0077
    db.close()

    data, keys, cid = _setup(os.path.join(root, "run"), user)
    before_keys = open(h.keys_path(keys), "rb").read()
    _kill_after(args_for(data, keys, cid), random.Random(100 + seed).uniform(0.0, full * 1.1))

    db = h.open_db(data, keys, d=384)
    try:
        n77 = h.sizes(db, cid)[h.frozen_id(77)]
        assert n77 in (0, 1)
        found = "cli-new" in h.ids_in(db.search(cid, [float(v) for v in x], k=5))
        assert found == (n77 == 1)  # all four fields and the mirror agree (INV-2)
        assert h.total_n(db, cid) == 4 + n77
        # An insert never rotates (§13.3), and recovery found nothing to erase.
        assert open(h.keys_path(keys), "rb").read() == before_keys
        outcome = db.delete(cid, "cli-new").outcome
        assert outcome == ("deleted" if n77 else "absent")
    finally:
        db.close()
    h.assert_keys_well_formed(keys)


@pytest.mark.req("SR-15.4-6", "SR-15.3-6")
def test_cli_delete_user_then_sdk_certificate(root, user):
    """§15.4: after a completed deletion "the certificate is retrievable by database_lsn". The CLI's
    deletion is leaf 4 (four insert leaves 0–3 precede it, §10.2), the next ones 5 and 6."""
    data, keys, cid = _setup(root, user)
    r = h.run_cli(h.cli_args("delete-user", data, keys, "--cid", cid, "--ids", json.dumps(COHORT)))
    assert r.returncode == 0, r.stderr[-2000:]
    db = h.open_db(data, keys, d=384)
    try:
        certs = [db.certificate(lsn) for lsn in (4, 5, 6)]
        assert all(certs)
        assert [int.from_bytes(h.parse_cert(c)[10], "big") for c in certs] == [4, 5, 6]
        assert db.certificate(7) is None
    finally:
        db.close()


@pytest.mark.req("SR-12.8-4", "SR-12.8-6")
def test_cli_refuses_without_memory_override(root, user):
    """§12.8: without allow_unsafe_memory the engine refuses to start on this machine (unencrypted
    swap, no memory lock: PROMPT), so the CLI deletes nothing."""
    data, keys, cid = _setup(root, user)
    args = [h.CLI, "delete-user", "--data", data, "--keys", keys, "--cid", cid, "--ids",
            json.dumps(COHORT)]
    assert h.run_cli(args).returncode != 0
    db = h.open_db(data, keys, d=384)
    try:
        assert h.total_n(db, cid) == 4
    finally:
        db.close()
