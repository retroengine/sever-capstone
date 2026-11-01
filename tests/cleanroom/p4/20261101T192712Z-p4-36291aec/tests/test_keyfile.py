"""§13 key hierarchy and erasure, §14.7 key file, §15.4 crash rows simulated on the key file."""

import os

import pytest

import helpers as h
from sever_db import IntegrityViolation

GROUPS_SMALL = {h.frozen_id(j) for j in range(4)} | {"holding"}


def _closed_db_with_records(dirs, user, per_group=2):
    """A closed d = 16 database: one collection, ``per_group`` in-distribution records in each of the
    4 frozen groups (destination frozen-j, derived with §7 in helpers.in_dist)."""
    data, keys = dirs
    db = h.open_db(data, keys)
    cid = db.create_collection(h.SMALL_SVP)
    for j in range(4):
        for s in range(per_group):
            r = h.insert(db, cid, f"r{j}-{s}", h.in_dist(j, s), user)
            assert r.placement == h.frozen_id(j)
    db.close()
    return cid


@pytest.mark.req("SR-14.7-1", "SR-14.7-2", "SR-14.7-5", "SR-13.1-1")
def test_key_file_layout_after_create(small_db):
    """§14.7: "Header, 4,096 bytes: b"SVDBKEYS" ‖ u16be version ‖ zero padding ‖ u32be crc32c" and
    "Size: 4 KB plus 1 KB per domain"; §13.1: one group key "per group, including the holding area"."""
    db, cid, data, keys = small_db
    b = open(h.keys_path(keys), "rb").read()
    assert b[:8] == b"SVDBKEYS"
    # The CRC covers every preceding byte of the header (§14.9 crc rule).
    assert h.crc32c(b[:4092]) == int.from_bytes(b[4092:4096], "big")
    # 4 frozen groups + the holding area = 5 domains → 4,096 + 5 · 1,024 = 9,216 bytes.
    assert len(b) == 4096 + 5 * 1024
    act = h.active_slots(keys)
    # Each domain's slot names this collection and one of its groups (§14.7 slot layout).
    assert {g for (c, g) in act} == GROUPS_SMALL
    assert {c for (c, g) in act} == {bytes.fromhex(cid)}
    # Pair indices are 0..4, each used once (§14.7: pair i at 4,096 + 1,024·i).
    assert sorted(i for i, _s, _p in act.values()) == [0, 1, 2, 3, 4]


@pytest.mark.req("SR-13.1-3")
def test_group_keys_distinct_and_32_bytes(small_db):
    """§13.1: "All keys are 32 bytes from the OS CSPRNG." Five independent 32-byte draws collide with
    probability ~2^-252, so five distinct, non-zero keys are expected."""
    _db, _cid, _data, keys = small_db
    ks = [p.key for _i, _s, p in h.active_slots(keys).values()]
    assert all(len(k) == 32 for k in ks)
    assert len(set(ks)) == 5 and bytes(32) not in ks


@pytest.mark.req("SR-13.1-1")
def test_group_keys_only_in_key_file(small_db, user):
    """§13.1: group key "Stored: Only in the key file (§14.7), plaintext, erasable"."""
    db, cid, data, keys = small_db
    h.insert(db, cid, "doc-a", h.in_dist(0, 0), user)
    db.checkpoint()
    for _i, _s, p in h.active_slots(keys).values():
        # No file other than KEYS (data dir or key dir) holds a group key's raw bytes.
        assert h.files_containing(p.key, data, keys, skip=("KEYS",)) == []


@pytest.mark.req("SR-13.3-3")
def test_insert_never_rotates(small_db, user):
    """§13.3: "Records joining a domain (insert, spillover, ...) never rotate anything; they are
    wrapped under the destination's current keys." So the key file is unchanged by inserts."""
    db, cid, data, keys = small_db
    before = open(h.keys_path(keys), "rb").read()
    h.insert(db, cid, "doc-a", h.in_dist(1, 0), user)  # → frozen-0001
    h.insert(db, cid, "doc-b", h.ood(0), user)  # → holding (§7.3, no spawned group)
    assert open(h.keys_path(keys), "rb").read() == before


@pytest.mark.req("SR-13.3-1", "SR-13.3-2", "SR-13.4-2", "SR-15.8-2", "SR-15.3-10")
def test_group_delete_rotates_exactly_its_domain(small_db, user):
    """§13.3: "Any committed transaction in which at least one record leaves a key domain rotates that
    domain"; §13.4: "Rotation writes the new key into the inactive slot ... and overwrites the old slot
    with zeros ... (phase C)"; §15.8: success only when "the old key's slot has been overwritten"."""
    db, cid, data, keys = small_db
    h.insert(db, cid, "doc-a", h.in_dist(2, 0), user)
    h.insert(db, cid, "doc-b", h.in_dist(2, 1), user)
    raw_before = h.read_pairs(keys)
    act0 = h.active_slots(keys)
    i, s, old = act0[(bytes.fromhex(cid), h.frozen_id(2))]
    assert db.delete(cid, "doc-a").outcome == "deleted"
    act1 = h.active_slots(keys)  # also asserts the old slot is 512 zero bytes (phase C done)
    i1, s1, new = act1[(bytes.fromhex(cid), h.frozen_id(2))]
    assert i1 == i  # same pair: domains are never re-indexed (§14.7)
    assert s1 == 1 - s  # the new key went to the previously inactive slot (§13.4)
    assert new.version == old.version + 1  # §13.3 step 1: version + 1
    assert new.key != old.key
    # The old key's bytes are gone from the key file once delete returned (§15.8).
    assert old.key not in open(h.keys_path(keys), "rb").read()
    # Every other domain's pair is byte-identical: only the domain that lost a record rotates.
    raw_after = h.read_pairs(keys)
    for k, (pi, _ps, _pp) in act0.items():
        if k[1] != h.frozen_id(2):
            assert raw_after[pi] == raw_before[pi]


@pytest.mark.req("SR-13.3-1", "SR-15.8-2")
def test_holding_delete_rotates_holding_domain(small_db, user):
    """§13.3: a record leaves a domain when it is "deleted from the holding area"; §13.1: the holding
    area has its own group key."""
    db, cid, data, keys = small_db
    r = h.insert(db, cid, "ood-1", h.ood(1), user)
    assert r.placement == "holding"  # §7.3: OOD and no spawned group → holding; §16.2 text form
    act0 = h.active_slots(keys)
    _i, _s, old = act0[(bytes.fromhex(cid), "holding")]
    assert db.delete(cid, "ood-1").outcome == "deleted"
    act1 = h.active_slots(keys)
    _i, _s, new = act1[(bytes.fromhex(cid), "holding")]
    assert new.version == old.version + 1
    assert old.key not in open(h.keys_path(keys), "rb").read()
    # Frozen domains lost nothing → same version and key.
    for g in (h.frozen_id(j) for j in range(4)):
        assert act1[(bytes.fromhex(cid), g)][2] == act0[(bytes.fromhex(cid), g)][2]


@pytest.mark.req("SR-15.3-11", "SR-13.3-1")
def test_delete_user_one_rotation_per_domain(small_db, user):
    """§15.3: for delete_user "Phase A writes one new key per affected domain, phase B commits one
    transaction, and phase C erases one old key per affected domain"."""
    db, cid, data, keys = small_db
    for s in range(3):
        h.insert(db, cid, f"a{s}", h.in_dist(0, s), user)
    h.insert(db, cid, "b0", h.in_dist(3, 0), user)
    act0 = h.active_slots(keys)
    out = db.delete_user(cid, ["a0", "a1", "b0"])
    assert [o.outcome for o in out] == ["deleted"] * 3
    act1 = h.active_slots(keys)
    c = bytes.fromhex(cid)
    # frozen-0000 lost two records in ONE transaction → exactly one rotation: version + 1, not + 2.
    assert act1[(c, h.frozen_id(0))][2].version == act0[(c, h.frozen_id(0))][2].version + 1
    assert act1[(c, h.frozen_id(3))][2].version == act0[(c, h.frozen_id(3))][2].version + 1
    # Unaffected domains keep their slot unchanged.
    for g in (h.frozen_id(1), h.frozen_id(2), "holding"):
        assert act1[(c, g)] == act0[(c, g)]


@pytest.mark.req("SR-13.4-3", "SR-14.7-2")
def test_reopen_leaves_one_valid_slot_per_domain(dirs, user):
    """§13.4: "for every domain with active version v: the slot holding v MUST exist with a valid CRC
    ...; every other slot for that domain is erased"."""
    data, keys = dirs
    cid = _closed_db_with_records(dirs, user)
    db = h.open_db(data, keys)
    db.delete(cid, "r1-0")
    db.close()
    db = h.open_db(data, keys)
    db.close()
    h.assert_keys_well_formed(keys)
    assert len(h.active_slots(keys)) == 5


@pytest.mark.req("SR-13.4-3", "SR-14.7-3", "SR-17-8")
def test_corrupt_active_slot_refuses_start(dirs, user):
    """§13.4: "the slot holding v MUST exist with a valid CRC (otherwise refuse to start: that data can
    no longer be decrypted)"; §14.7: "a torn slot fails its CRC and is treated as absent"."""
    data, keys = dirs
    cid = _closed_db_with_records(dirs, user)
    i, s, _p = h.active_slots(keys)[(bytes.fromhex(cid), h.frozen_id(1))]
    off = h.HDR + h.PAIR * i + h.SLOT * s + 30  # a byte inside the 32-byte key field (bytes 20..51)
    b = open(h.keys_path(keys), "rb").read()
    h.write_at(h.keys_path(keys), off, bytes([b[off] ^ 0x01]))
    # The active version's slot now fails its CRC → absent → invariant INV-14 fails → §17 says any
    # invariant failure is IntegrityViolation.
    with pytest.raises(IntegrityViolation):
        h.open_db(data, keys)


@pytest.mark.req("SR-13.4-3")
def test_erased_active_slot_refuses_start(dirs, user):
    """§13.4: the active version's slot "MUST exist ... (otherwise refuse to start)"."""
    data, keys = dirs
    cid = _closed_db_with_records(dirs, user)
    i, s, _p = h.active_slots(keys)[(bytes.fromhex(cid), "holding")]
    h.write_at(h.keys_path(keys), h.HDR + h.PAIR * i + h.SLOT * s, bytes(h.SLOT))
    with pytest.raises(IntegrityViolation):  # INV-14 violation → IntegrityViolation (§17)
        h.open_db(data, keys)


@pytest.mark.req("SR-13.4-3", "SR-14.7-6")
def test_truncated_whole_pair_refuses_start(dirs, user):
    """§14.7: "The pair count is (file length − 4,096) / 1,024"; cutting the last pair removes a live
    domain's only slot, so §13.4's "MUST exist" fails."""
    data, keys = dirs
    _closed_db_with_records(dirs, user)
    p = h.keys_path(keys)
    os.truncate(p, os.path.getsize(p) - h.PAIR)
    with pytest.raises(IntegrityViolation):
        h.open_db(data, keys)


@pytest.mark.req("SR-14.7-6")
def test_trailing_partial_pair_truncated_at_recovery(dirs, user):
    """§14.7: "a trailing partial pair (a crash while the file grew) is truncated at recovery"."""
    data, keys = dirs
    cid = _closed_db_with_records(dirs, user)
    p = h.keys_path(keys)
    size = os.path.getsize(p)
    with open(p, "ab") as f:
        f.write(b"\xa5" * 700)  # 700 < 1,024: a partial pair
        f.flush()
        os.fsync(f.fileno())
    db = h.open_db(data, keys)
    try:
        # Recovery truncated back to 4,096 + 1,024 · 5 and the database serves its records.
        assert os.path.getsize(p) == size == 4096 + 5 * 1024
        assert h.total_n(db, cid) == 8
    finally:
        db.close()
    h.assert_keys_well_formed(keys)


def _plant_inactive(dirs, user, version_delta: int | None, rotate_first: bool = False):
    """Writes into the inactive slot of frozen-0002's pair either a valid slot with version
    active + version_delta, or (None) torn garbage. Returns (cid, pair, active slot)."""
    data, keys = dirs
    cid = _closed_db_with_records(dirs, user)
    if rotate_first:  # one deletion from frozen-0002 → its version is ≥ 1, so v − 1 exists
        db = h.open_db(data, keys)
        assert db.delete(cid, "r2-1").outcome == "deleted"
        db.close()
    c = bytes.fromhex(cid)
    i, s, p = h.active_slots(keys)[(c, h.frozen_id(2))]
    if version_delta is None:
        blob = os.urandom(h.SLOT)
    else:
        blob = h.make_slot(i, p.version + version_delta, os.urandom(32), c, h.frozen_id(2))
    h.write_at(h.keys_path(keys), h.HDR + h.PAIR * i + h.SLOT * (1 - s), blob)
    return cid, i, s, p


@pytest.mark.req("SR-15.4-3", "SR-13.4-3")
def test_orphan_new_slot_erased_by_recovery(dirs, user):
    """§15.4 row "After phase A, before COMMIT is durable": "Unchanged; the new slot is an orphan
    (version ≠ active)" and "Recovery erases the orphan; retrying is safe"."""
    data, keys = dirs
    cid, i, s, p = _plant_inactive(dirs, user, +1)  # what phase A leaves: version v+1, valid CRC
    db = h.open_db(data, keys)
    try:
        act = h.active_slots(keys)  # asserts the orphan slot is now 512 zero bytes
        assert act[(bytes.fromhex(cid), h.frozen_id(2))] == (i, s, p)  # the active key is kept
        assert h.sizes(db, cid)[h.frozen_id(2)] == 2  # state unchanged
        # Retrying the deletion is safe: it deletes normally.
        assert db.delete(cid, "r2-0").outcome == "deleted"
    finally:
        db.close()


@pytest.mark.req("SR-15.4-4", "SR-13.4-3")
def test_stale_old_slot_erased_by_recovery(dirs, user):
    """§15.4 row "After COMMIT, before phase C": old key "Present in its slot" and "Recovery erases it
    (version ≠ active)". Simulated by a valid slot of version v − 1 beside the active one."""
    data, keys = dirs
    cid, i, s, p = _plant_inactive(dirs, user, -1, rotate_first=True)
    db = h.open_db(data, keys)
    try:
        act = h.active_slots(keys)
        assert act[(bytes.fromhex(cid), h.frozen_id(2))] == (i, s, p)
        # 8 inserted, r2-1 deleted before the plant → N = 7; the stale slot changes nothing.
        assert h.total_n(db, cid) == 7
        assert db.delete(cid, "r2-1").outcome == "absent"
    finally:
        db.close()


@pytest.mark.req("SR-15.4-5", "SR-14.7-3")
def test_torn_inactive_slot_erased_by_recovery(dirs, user):
    """§15.4 row "During phase C (torn slot)": "CRC fails, so treated as absent and erased again"."""
    data, keys = dirs
    cid, i, s, p = _plant_inactive(dirs, user, None)
    db = h.open_db(data, keys)
    try:
        assert h.active_slots(keys)[(bytes.fromhex(cid), h.frozen_id(2))] == (i, s, p)
        assert h.total_n(db, cid) == 8
    finally:
        db.close()


@pytest.mark.req("SR-13.4-3")
def test_missing_key_file_refuses_start(dirs, user):
    """§13.4: the active slot of every domain "MUST exist ... (otherwise refuse to start)"."""
    data, keys = dirs
    _closed_db_with_records(dirs, user)
    os.remove(h.keys_path(keys))
    # Collections exist in the data directory, their domains' slots do not → INV-14 → refuse.
    with pytest.raises(IntegrityViolation):
        h.open_db(data, keys)


@pytest.mark.req("SR-14.7-4", "SR-14.7-5", "SR-13.3-1", "SR-15.2-3", "SR-7.5-1")
def test_flush_adds_domain_and_rotates_holding(small_db, user):
    """§15.2: a flush creates the group with "fresh group key" (a new domain, appended: §14.7 "Pairs
    are appended in creation order") and "Rotate[s] the holding area (§13.3)"."""
    db, cid, data, keys = small_db
    c = bytes.fromhex(cid)
    act0 = h.active_slots(keys)
    ids = [f"o-{s:03d}" for s in range(200)]
    last = None
    for s, rid in enumerate(ids):
        last = h.insert(db, cid, rid, h.ood(s), user)
    # §7.4: the 200th holding record triggers the flush; §7.5 gives the ID; §16.2 reports the group
    # the record is in after the transaction.
    sid = h.spawn_id(ids)
    assert last.placement == sid
    assert h.sizes(db, cid)[sid] == 200
    assert os.path.getsize(h.keys_path(keys)) == 4096 + 6 * 1024  # one domain more
    act1 = h.active_slots(keys)
    assert act1[(c, sid)][0] == 5  # appended as pair 5
    assert act1[(c, "holding")][2].version == act0[(c, "holding")][2].version + 1
    for j in range(4):
        assert act1[(c, h.frozen_id(j))] == act0[(c, h.frozen_id(j))]
