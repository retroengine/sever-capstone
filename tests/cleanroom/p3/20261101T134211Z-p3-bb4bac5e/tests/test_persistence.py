"""Persistence across close and reopen (§12.4 clean shutdown, §15.7 recovery, §15.8)."""

import pytest

import helpers as h
import sevlib


@pytest.mark.req("SR-15.8-1", "SR-15.1-2", "SR-15.1-6")
def test_state_survives_close_and_reopen(env, user, art16, rng):
    """§15.8: "An insert returns success when it is durable and applied"; a deletion likewise.
    After a clean close and reopen every acknowledged operation is still there."""
    db = h.open_db(env)
    cid = db.create_collection(h.SMALL)
    reqs = []
    for i in range(4):
        req, _ = h.insert(db, cid, f"p-{i}", sevlib.in_dist_vector(art16, rng, 0), user)  # 0–3
        reqs.append(req)
    out = db.delete(cid, "p-1")  # leaf 4
    q = sevlib.in_dist_vector(art16, rng, 0)
    before = dict(sizes=db.group_sizes(cid), cp=db.latest_log_checkpoint(), anchors=db.anchors(),
                  search=db.search(cid, q, k=10))
    db.close()

    db = h.open_db(env)
    try:
        assert db.collections() == [cid]
        assert db.group_sizes(cid) == before["sizes"]
        assert db.search(cid, q, k=10) == before["search"]
        assert db.latest_log_checkpoint() == before["cp"]
        assert db.anchors() == before["anchors"]  # the same operator and witness keys
        assert db.certificate(4) == out.certificate
        # A retried insert of a record committed before the restart is still recognised as the
        # same commitment (§15.1): success, no new leaf.
        assert db.insert(cid, reqs[0]).retried
        assert db.delete(cid, "p-1").outcome == "absent"  # still deleted
        nxt = db.delete(cid, "p-2")
        assert nxt.database_lsn == 5  # leaves 0–4 survived; nothing appended by the retries
        c_prev, c = h.cert(out.certificate), h.cert(nxt.certificate)
        # The group's commitment chain continues across the restart (§11.3, §9.3).
        assert c.cs_pre == c_prev.cs_post
        assert c.cs_post == sevlib.r_add_enc(reqs[0].c_t, reqs[3].c_t)
        ok, step = sevlib.verify_certificate(nxt.certificate, h.anchors(db))
        assert ok, step
    finally:
        h.quiet_close(db)


@pytest.mark.req("SR-11.3-8", "SR-9.8-6")
def test_certificate_still_verifies_after_restart(env, user, art16, rng):
    """§9.8: "Old public keys stay resolvable forever, so old certificates keep verifying." A
    certificate issued before a restart verifies against the anchors published after it."""
    db = h.open_db(env)
    cid = db.create_collection(h.SMALL)
    h.insert(db, cid, "v-0", sevlib.in_dist_vector(art16, rng, 3), user)
    h.insert(db, cid, "v-1", sevlib.in_dist_vector(art16, rng, 3), user)
    raw = db.delete(cid, "v-0").certificate
    db.close()
    db = h.open_db(env)
    try:
        assert db.certificate(2) == raw
        ok, step = sevlib.verify_certificate(raw, h.anchors(db))
        assert ok, step
    finally:
        h.quiet_close(db)


@pytest.mark.req("SR-10.3-4", "SR-10.5-1")
def test_log_continues_after_restart(env, user, art16, rng):
    """§10.2: `database_lsn` is the 0-based leaf index of an append-only log; a restart neither
    loses nor repeats a leaf."""
    db = h.open_db(env)
    cid = db.create_collection(h.SMALL)
    for i in range(3):
        h.insert(db, cid, f"lc-{i}", sevlib.ood_vector(art16, rng), user)
    db.close()
    db = h.open_db(env)
    try:
        assert h.insert(db, cid, "lc-3", sevlib.ood_vector(art16, rng), user)[1].database_lsn == 3
        assert db.delete(cid, "lc-0").database_lsn == 4
    finally:
        h.quiet_close(db)
