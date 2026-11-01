"""§15.3 delete, §15.8 acknowledgement, §5.4 idempotency, §12.6 zeroing (observable part), §12.5
all-or-nothing delete_user, exactness against a twin database."""

import pytest

import helpers as h
from sever_db import Deletion, InvalidRecordId, UnknownCollection


@pytest.mark.req("SR-15.3-1", "SR-5.4-2", "SR-15.4-4")
def test_retry_after_delete_is_absent(small_db, user):
    """§5.4: "If it is absent, the deletion returns AlreadyAbsent, changes nothing, and issues no
    certificate"; §15.4: "a retry returns AlreadyAbsent"."""
    db, cid, _d, _k = small_db
    h.insert(db, cid, "doc-1", h.in_dist(0, 0), user)
    first = db.delete(cid, "doc-1")
    assert first.outcome == "deleted"
    # The SDK maps AlreadyAbsent to Deletion("absent") with no lsn and no certificate (API).
    assert db.delete(cid, "doc-1") == Deletion("absent")


@pytest.mark.req("SR-5.4-2")
def test_delete_never_inserted_is_absent(small_db):
    """§15.3 step 1: "Look up scrambled_id. If absent, return AlreadyAbsent and touch nothing."."""
    db, cid, _d, _k = small_db
    assert db.delete(cid, "never-there") == Deletion("absent")


@pytest.mark.req("SR-15.3-4", "SR-15.3-6")
def test_lsn_arithmetic_and_absent_adds_no_leaf(small_db, user):
    """§10.2: "database_lsn of an operation is the 0-based index of its leaf"; a delete leaf is
    appended for "Every deletion that removes a record"; §15.3 step 4: database_lsn = "the next leaf
    index". An AlreadyAbsent deletion appends nothing (§5.4 "changes nothing")."""
    db, cid, _d, _k = small_db
    assert h.insert(db, cid, "a-1", h.in_dist(0, 0), user).database_lsn == 0  # first leaf
    assert h.insert(db, cid, "b-1", h.in_dist(1, 0), user).database_lsn == 1
    d = db.delete(cid, "a-1")
    assert d.database_lsn == 2  # the next leaf index
    assert db.delete(cid, "a-1").outcome == "absent"  # no leaf
    assert h.insert(db, cid, "c-1", h.in_dist(2, 0), user).database_lsn == 3  # not 4


@pytest.mark.req("SR-15.3-6", "SR-15.4-6")
def test_certificate_retrievable_by_lsn(small_db, user):
    """§15.4: "the certificate is retrievable by database_lsn"; §15.3 step 9: "Acknowledge with the
    certificate"."""
    db, cid, _d, _k = small_db
    h.insert(db, cid, "a-1", h.in_dist(0, 0), user)
    d = db.delete(cid, "a-1")
    assert d.certificate and db.certificate(d.database_lsn) == d.certificate
    # Leaf 0 is an insert leaf, not a deletion → no certificate (API: "or None").
    assert db.certificate(0) is None


@pytest.mark.req("SR-15.3-4")
def test_certificate_fields_group_deletion(small_db, user):
    """§15.3 step 4: "Build the certificate with database_lsn = the next leaf index"; §11.1 tags."""
    db, cid, _d, _k = small_db
    req = h.prepare_insert(cid, "a-1", [float(v) for v in h.in_dist(1, 0)], user)
    db.insert(cid, req)
    h.insert(db, cid, "a-2", h.in_dist(1, 1), user)
    d = db.delete(cid, "a-1")
    t = h.parse_cert(d.certificate)
    assert t[1] == req.c_t  # tag 1: C_t of the deleted record
    assert t[5] == req.signature  # tag 5: the user's insert signature
    assert int.from_bytes(t[10], "big") == d.database_lsn == 2  # tag 10, u64be
    assert t[11] == b"\x00"  # a-2 remains → not emptied
    assert t[12] == b"\x00"  # deletion_kind 0 = from a group
    assert t[13] == bytes.fromhex(cid)
    assert len(t[2]) == len(t[3]) == 32
    assert len(t[4]) == 32 + 32 + 16 * 32  # A ‖ z_r ‖ z_0..z_{d−1} at d = 16
    assert len(t[9]) == 64  # scrambled_id


@pytest.mark.req("SR-15.3-4", "SR-5.4-4")
def test_certificate_emptied_group(small_db, user):
    """§5.4: "When n reaches 0, ... C_S = identity exactly" (the 32-byte all-zero encoding, §5.2);
    §11.1 tag 11 group_emptied_by_this_deletion."""
    db, cid, _d, _k = small_db
    h.insert(db, cid, "solo", h.in_dist(3, 0), user)
    t = h.parse_cert(db.delete(cid, "solo").certificate)
    assert t[3] == bytes(32)  # C_S_post = identity
    assert t[11] == b"\x01"
    assert h.sizes(db, cid)[h.frozen_id(3)] == 0  # the group stays, with n = 0


@pytest.mark.req("SR-15.3-4", "SR-13.3-1")
def test_certificate_holding_deletion(small_db, user):
    """§11.1: tags 2, 3, 4 are "empty for a holding-area deletion"; tag 12 "1 = from the holding
    area"; §7.4: holding records are "always deletable immediately"."""
    db, cid, _d, _k = small_db
    assert h.insert(db, cid, "ood-1", h.ood(3), user).placement == "holding"
    d = db.delete(cid, "ood-1")
    t = h.parse_cert(d.certificate)
    assert t[2] == t[3] == t[4] == b""
    assert t[12] == b"\x01"
    assert h.total_n(db, cid) == 0  # holding records never counted in N (§7.6)


@pytest.mark.req("SR-8.1-4", "SR-15.8-2", "SR-12.6-3")
def test_deleted_record_not_searchable(small_db, user):
    """§8.1: "A deleted record MUST NOT appear in any result produced after its deletion is
    acknowledged (INV-9)"; §12.6: the mirror entry is overwritten before acknowledgement."""
    db, cid, _d, _k = small_db
    x = h.in_dist(0, 0)
    h.insert(db, cid, "doc-1", x, user)
    h.insert(db, cid, "doc-2", h.in_dist(0, 1), user)
    assert "doc-1" in h.ids_in(db.search(cid, [float(v) for v in x], k=10))
    db.delete(cid, "doc-1")
    # Query is doc-1's own vector, so frozen-0000 is the one probed group (p = ⌈0.25·4⌉ = 1).
    assert h.ids_in(db.search(cid, [float(v) for v in x], k=10)) == ["doc-2"]


@pytest.mark.req("SR-5.3-1", "SR-5.4-1", "SR-15.3-9")
def test_exact_against_twin(root, user):
    """§5.3: "after the deletion every field equals the value it would have had if t had never been
    inserted". Twin A gets a, b, c then deletes b; twin B never sees b. Every public observable must
    match: group sizes, search IDs and scores bit for bit."""
    xs = {"a": h.in_dist(2, 0), "b": h.in_dist(2, 1), "c": h.in_dist(2, 2), "z": h.in_dist(1, 0)}
    dbs = []
    for name, ops in (("A", "abcz"), ("B", "acz")):
        data, keys = h.new_dirs(h.new_root())
        db = h.open_db(data, keys)
        cid = db.create_collection(h.SMALL_SVP)
        for r in ops:
            h.insert(db, cid, f"rec-{r}", xs[r], user)
        if name == "A":
            assert db.delete(cid, "rec-b").outcome == "deleted"
        dbs.append((db, cid))
    (da, ca), (dbb, cb) = dbs
    try:
        assert da.group_sizes(ca) == dbb.group_sizes(cb)
        for q in xs.values():
            ql = [float(v) for v in q]
            assert da.search(ca, ql, k=10) == dbb.search(cb, ql, k=10)
    finally:
        da.close()
        dbb.close()


@pytest.mark.req("SR-15.3-11", "SR-15.3-1")
def test_delete_user_chains_certificates(small_db, user):
    """§15.3: "delete_user(list) does steps 1–4 for every record in list order. Each certificate is
    built on the state left by the previous one, so consecutive certificates chain."""
    db, cid, _d, _k = small_db
    for s in range(3):
        h.insert(db, cid, f"p-{s}", h.in_dist(1, s), user)  # lsn 0, 1, 2
    out = db.delete_user(cid, ["p-0", "p-1"])
    assert [o.outcome for o in out] == ["deleted", "deleted"]
    assert [o.database_lsn for o in out] == [3, 4]  # next leaf indices, in list order
    c1, c2 = (h.parse_cert(o.certificate) for o in out)
    assert c2[2] == c1[3]  # C_S_pre of the second = C_S_post of the first
    assert h.sizes(db, cid)[h.frozen_id(1)] == 1


@pytest.mark.req("SR-15.3-1", "SR-5.4-2")
def test_delete_user_duplicates_and_missing(small_db, user):
    """§15.3: steps 1–4 for every record in list order on the state left by the previous one; step 1:
    an absent record returns AlreadyAbsent."""
    db, cid, _d, _k = small_db
    h.insert(db, cid, "q-1", h.in_dist(0, 0), user)
    out = db.delete_user(cid, ["q-1", "q-1", "nobody"])
    # The second q-1 sees the state after the first → absent; "nobody" never existed → absent.
    assert [o.outcome for o in out] == ["deleted", "absent", "absent"]
    assert out[1] == out[2] == Deletion("absent")


@pytest.mark.req("SR-12.5-2", "SR-15.3-1")
def test_delete_user_all_or_nothing_on_bad_id(small_db, user):
    """§12.5: "delete_user removes many records, across many groups, in one transaction: all or
    nothing." A list with an invalid ID (a lone surrogate is not UTF-8, §3.2 rule 1) deletes nothing."""
    db, cid, _d, _k = small_db
    h.insert(db, cid, "v-1", h.in_dist(0, 0), user)
    h.insert(db, cid, "v-2", h.in_dist(1, 0), user)
    with pytest.raises(InvalidRecordId):
        db.delete_user(cid, ["v-1", "v-2", "bad-\ud800"])
    assert h.total_n(db, cid) == 2
    assert [o.outcome for o in db.delete_user(cid, ["v-1", "v-2"])] == ["deleted", "deleted"]


@pytest.mark.req("SR-15.3-1")
def test_delete_user_unknown_collection(small_db, user):
    """§17: UnknownCollection when there is "No such collection"; nothing in the real one changes."""
    db, cid, _d, _k = small_db
    h.insert(db, cid, "w-1", h.in_dist(0, 0), user)
    with pytest.raises(UnknownCollection):
        db.delete_user("00" * 16, ["w-1"])
    with pytest.raises(UnknownCollection):
        db.delete("ff" * 16, "w-1")
    assert h.total_n(db, cid) == 1


@pytest.mark.req("SR-3.2-4")
def test_reinsert_after_delete(small_db, user):
    """§3.2: "A record ID MAY be inserted again after its record has been deleted. The new record is a
    new insert, with a new log leaf."."""
    db, cid, _d, _k = small_db
    h.insert(db, cid, "again", h.in_dist(0, 0), user)  # leaf 0
    db.delete(cid, "again")  # leaf 1
    r = h.insert(db, cid, "again", h.in_dist(0, 1), user)
    assert r.database_lsn == 2 and r.retried is False
    assert h.sizes(db, cid)[h.frozen_id(0)] == 1


@pytest.mark.req("SR-15.8-1", "SR-15.4-6")
def test_delete_persists_across_reopen(dirs, user):
    """§15.8: success only when "its transaction is durable"; §15.4: the certificate stays
    retrievable by database_lsn."""
    data, keys = dirs
    db = h.open_db(data, keys)
    cid = db.create_collection(h.SMALL_SVP)
    x = h.in_dist(2, 0)
    h.insert(db, cid, "keep", h.in_dist(2, 1), user)
    h.insert(db, cid, "gone", x, user)
    d = db.delete(cid, "gone")
    db.close()
    db = h.open_db(data, keys)
    try:
        assert db.collections() == [cid]
        assert h.ids_in(db.search(cid, [float(v) for v in x], k=10)) == ["keep"]
        assert db.certificate(d.database_lsn) == d.certificate
        assert db.delete(cid, "gone") == Deletion("absent")
    finally:
        db.close()
    h.assert_keys_well_formed(keys)


@pytest.mark.req("SR-15.8-1")
def test_insert_persists_across_reopen_and_search_score(dirs, user):
    """§15.8: "An insert returns success when it is durable and applied"; the score after reopen is the
    §8.2 kernel on the dequantised vector (derived by hand in helpers.kernel_score)."""
    data, keys = dirs
    db = h.open_db(data, keys)
    cid = db.create_collection(h.SMALL_SVP)
    x, q = h.in_dist(3, 0), h.in_dist(3, 1)
    h.insert(db, cid, "doc-x", x, user)
    db.close()
    db = h.open_db(data, keys)
    try:
        hits = db.search(cid, [float(v) for v in q], k=5)
        assert hits == [("doc-x", h.kernel_score(q, x))]
    finally:
        db.close()


@pytest.mark.req("SR-15.8-2", "SR-13.3-2")
def test_delete_last_of_many_in_bucket_keeps_others_readable(dirs, user):
    """§13.3 step 4: "re-wraps the surviving record keys of every rotated bucket"; survivors stay
    readable after reopen (their records decrypt and the startup invariant check passes, §15.7)."""
    data, keys = dirs
    db = h.open_db(data, keys)
    cid = db.create_collection(h.SMALL_SVP)
    xs = [h.in_dist(0, s, eps=0.003) for s in range(12)]
    for s, x in enumerate(xs):
        h.insert(db, cid, f"m-{s:02d}", x, user)
    for s in range(0, 12, 3):
        assert db.delete(cid, f"m-{s:02d}").outcome == "deleted"
    db.close()
    db = h.open_db(data, keys)
    try:
        assert h.sizes(db, cid)[h.frozen_id(0)] == 8
        for s, x in enumerate(xs):
            hit = f"m-{s:02d}" in h.ids_in(db.search(cid, [float(v) for v in x], k=12))
            assert hit == (s % 3 != 0)
    finally:
        db.close()
