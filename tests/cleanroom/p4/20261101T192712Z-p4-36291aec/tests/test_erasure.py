"""§13.2 what is plaintext on disk, §13.5 erasure, §15.9 drop collection."""

import struct

import pytest

import helpers as h
from sever_db import UnknownCollection

RID = "zq-record-identifier-5d1e"
PASSAGE = b"PASSAGE-MARKER-the-quick-brown-fox-91c2e"


def _needles(x):
    """The byte forms a vector could take on disk: x̃ as i32be (the slot payload layout, §14.4),
    i32le, i64be (canonical blob widening, §5.5), and the float32 input LE/BE."""
    q = h.quantise(x)
    return {
        "x̃ i32be": b"".join(struct.pack(">i", int(v)) for v in q),
        "x̃ i32le": b"".join(struct.pack("<i", int(v)) for v in q),
        "x̃ i64be": b"".join(struct.pack(">q", int(v)) for v in q),
        "x f32le": x.astype("<f4").tobytes(),
        "x f32be": x.astype(">f4").tobytes(),
    }


def _assert_no_plaintext(x, data, keys):
    for name, needle in {"record id": RID.encode(), "passage": PASSAGE, **_needles(x)}.items():
        assert h.files_containing(needle, data, keys) == [], name


@pytest.mark.req("SR-13.2-8", "SR-13.2-2", "SR-13.2-3", "SR-21-11")
def test_no_plaintext_secrets_on_disk(dirs, user):
    """§13.2: "Plaintext on disk, on purpose: n and group sizes; C_S; centroids; scrambled_ids; log
    leaves and certificates; group IDs; key versions" — the record ID, the vector and the passage are
    not in that list, so no file may hold them in the clear (§12.1: "only ever receives ciphertext for
    anything secret")."""
    data, keys = dirs
    db = h.open_db(data, keys)
    cid = db.create_collection(h.SMALL_SVP)
    x = h.in_dist(1, 0)
    h.insert(db, cid, RID, x, user, passage=PASSAGE)
    _assert_no_plaintext(x, data, keys)  # while open: WAL, append stores
    db.checkpoint()
    _assert_no_plaintext(x, data, keys)  # after a storage checkpoint
    db.close()
    _assert_no_plaintext(x, data, keys)


@pytest.mark.req("SR-13.2-8")
def test_no_plaintext_for_holding_record(dirs, user):
    """§7.4: a holding record "is stored encrypted, with its r_t like every record"."""
    data, keys = dirs
    db = h.open_db(data, keys)
    cid = db.create_collection(h.SMALL_SVP)
    x = h.ood(42)
    assert h.insert(db, cid, RID, x, user, passage=PASSAGE).placement == "holding"
    db.close()
    _assert_no_plaintext(x, data, keys)


@pytest.mark.req("SR-15.8-2", "SR-13.4-1", "SR-21-13")
def test_old_group_key_gone_everywhere_after_delete(dirs, user):
    """§15.8: a deletion returns success only when "the old key's slot has been overwritten and
    fsynced"; §13.1: group keys are stored only in the key file, so after the deletion the old key's
    32 bytes exist in no file at all (§13.5 step 3)."""
    data, keys = dirs
    db = h.open_db(data, keys)
    cid = db.create_collection(h.SMALL_SVP)
    h.insert(db, cid, RID, h.in_dist(3, 0), user, passage=PASSAGE)
    h.insert(db, cid, "other-one", h.in_dist(3, 1), user)
    old = h.active_slots(keys)[(bytes.fromhex(cid), h.frozen_id(3))][2].key
    assert db.delete(cid, RID).outcome == "deleted"
    assert h.files_containing(old, data, keys) == []
    db.close()
    assert h.files_containing(old, data, keys) == []


@pytest.mark.req("SR-15.9-2", "SR-15.9-1")
def test_drop_collection_erases_its_slots(dirs, user):
    """§15.9: "erase every key slot of the collection from the key file (overwrite with zeros and
    fsync) ... the drop is acknowledged only after the erase"."""
    data, keys = dirs
    db = h.open_db(data, keys)
    a = db.create_collection(h.SMALL_SVP)
    b = db.create_collection(h.SMALL_SVP)
    h.insert(db, a, "in-a", h.in_dist(0, 0), user)
    xb = h.in_dist(0, 1)
    h.insert(db, b, "in-b", xb, user)
    act0 = h.active_slots(keys)
    raw0 = h.read_pairs(keys)
    a_pairs = sorted(i for (c, _g), (i, _s, _p) in act0.items() if c == bytes.fromhex(a))
    assert len(a_pairs) == 5  # 4 frozen + holding (§13.1)
    a_keys = [p.key for (c, _g), (_i, _s, p) in act0.items() if c == bytes.fromhex(a)]
    db.drop_collection(a)
    raw1 = h.read_pairs(keys)
    for i in a_pairs:
        assert raw1[i] == (bytes(512), bytes(512))  # both slots zero
    for i in range(len(raw0)):
        if i not in a_pairs:
            assert raw1[i] == raw0[i]  # b untouched
    blob = open(h.keys_path(keys), "rb").read()
    assert all(k not in blob for k in a_keys)
    assert db.collections() == [b]
    with pytest.raises(UnknownCollection):
        h.insert(db, a, "late", h.in_dist(1, 0), user)
    assert h.ids_in(db.search(b, [float(v) for v in xb], k=5)) == ["in-b"]
    db.close()
    db = h.open_db(data, keys)
    try:
        assert db.collections() == [b]
        assert h.ids_in(db.search(b, [float(v) for v in xb], k=5)) == ["in-b"]
    finally:
        db.close()


@pytest.mark.req("SR-15.9-2", "SR-13.4-3")
def test_drop_crash_before_erase_finished_by_recovery(dirs, user):
    """§15.9: "A crash between the commit and the erase is finished by §13.4's recovery rule: the
    collection's slots now belong to no domain, so they are erased." Simulated by writing the dropped
    collection's old slots back after the drop, then reopening."""
    data, keys = dirs
    db = h.open_db(data, keys)
    a = db.create_collection(h.SMALL_SVP)
    b = db.create_collection(h.SMALL_SVP)
    h.insert(db, a, "in-a", h.in_dist(2, 0), user)
    act0 = h.active_slots(keys)
    raw0 = h.read_pairs(keys)
    a_pairs = [i for (c, _g), (i, _s, _p) in act0.items() if c == bytes.fromhex(a)]
    db.drop_collection(a)
    db.close()
    for i in a_pairs:  # the state a crash after COMMIT, before phase C, would leave
        h.write_at(h.keys_path(keys), h.HDR + h.PAIR * i, raw0[i][0] + raw0[i][1])
    db = h.open_db(data, keys)
    try:
        assert db.collections() == [b]
        raw1 = h.read_pairs(keys)
        for i in a_pairs:
            assert raw1[i] == (bytes(512), bytes(512))  # slots of no domain are erased
    finally:
        db.close()
    h.assert_keys_well_formed(keys)


@pytest.mark.req("SR-15.9-1")
def test_drop_unknown_collection(small_db):
    """§17: UnknownCollection when there is "No such collection"."""
    db, cid, _d, _k = small_db
    with pytest.raises(UnknownCollection):
        db.drop_collection("12" * 16)
    assert db.collections() == [cid]


@pytest.mark.req("SR-12.6-3", "SR-8.1-4")
def test_delete_of_many_never_shows_deleted(small_db, user):
    """§12.6: "Deleting a record overwrites its mirror entry ... before the deletion is acknowledged";
    §8.1 INV-9. Delete half of 16 records one by one; after each acknowledgement, a search over
    every group's vectors never returns a deleted ID."""
    db, cid, _d, _k = small_db
    xs = {f"mm-{j}-{s}": h.in_dist(j, s) for j in range(4) for s in range(4)}
    for rid, x in xs.items():
        h.insert(db, cid, rid, x, user)
    gone = set()
    for rid in list(xs)[::2]:
        assert db.delete(cid, rid).outcome == "deleted"
        gone.add(rid)
        for x in xs.values():
            assert not gone & set(h.ids_in(db.search(cid, [float(v) for v in x], k=16)))
    assert h.total_n(db, cid) == 8
