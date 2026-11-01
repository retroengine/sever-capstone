"""Deletion (§15.3), exactness (§5.3, §5.4), certificates (§11) and the commitment arithmetic
(§4.5, §9.3, §9.5) checked offline with a clean-room verifier (sevlib)."""

import struct

import numpy as np
import pytest
import sever_db_p3 as sdk

import helpers as h
import sevlib


def frozen_records(db, cid, user, art, rng, label, n, prefix="m"):
    """n records in frozen group `label` (in-distribution, §7.3); returns their requests."""
    reqs = []
    for i in range(n):
        req, rec = h.insert(db, cid, f"{prefix}-{label}-{i}", sevlib.in_dist_vector(art, rng, label), user)
        assert rec.placement == f"frozen-{label:04d}"
        reqs.append(req)
    return reqs


@pytest.mark.req("SR-10.2-3", "SR-15.3-4", "SR-15.3-6", "SR-11.1-3")
def test_delete_returns_a_certificate_at_the_next_leaf(db16, user, art16, rng):
    """§15.3 step 4: "Build the certificate with `database_lsn` = the next leaf index"; step 9:
    "Acknowledge with the certificate." """
    db, cid = db16.db, db16.cid
    reqs = frozen_records(db, cid, user, art16, rng, 0, 3)  # leaves 0, 1, 2
    out = db.delete(cid, "m-0-1")
    # Three insert leaves exist, so the delete leaf is index 3 (on-demand log checkpoints are not
    # leaves, §10.3).
    assert out.outcome == "deleted" and out.database_lsn == 3
    c = h.cert(out.certificate)
    assert c.database_lsn == 3  # tag 10 = this deletion's own leaf index
    assert c.c_t == reqs[1].c_t  # tag 1 = C_t of the deleted record
    assert c.user_sig == reqs[1].signature  # tag 5 = the insert signature
    assert c.collection_id == bytes.fromhex(cid)  # tag 13
    assert c.kind == 0  # tag 12: 0 = from a group
    assert c.leaf_index == 1  # tag 6: the record's insert leaf


@pytest.mark.req("SR-5.4-2", "SR-10.2-2")
def test_second_delete_is_absent_and_appends_nothing(db16, user, art16, rng):
    """§5.4: "If it is absent, the deletion returns `AlreadyAbsent`, changes nothing, and issues no
    certificate." §10.2: a delete leaf is appended for "Every deletion that removes a record"."""
    db, cid = db16.db, db16.cid
    frozen_records(db, cid, user, art16, rng, 1, 1)  # leaf 0
    assert db.delete(cid, "m-1-0").database_lsn == 1  # leaf 1
    again = db.delete(cid, "m-1-0")
    assert (again.outcome, again.database_lsn, again.certificate) == ("absent", None, None)
    # No leaf for the absent retry: the next insert is leaf 2.
    assert h.next_lsn(db, cid, user, art16, rng) == 2


@pytest.mark.req("SR-5.4-2", "SR-15.3-1")
def test_delete_of_a_never_inserted_id_is_absent(db16, user, art16, rng):
    """§15.3 step 1: "Look up `scrambled_id`. If absent, return `AlreadyAbsent` and touch
    nothing." """
    db, cid = db16.db, db16.cid
    out = db.delete(cid, "never-was")
    assert (out.outcome, out.database_lsn, out.certificate) == ("absent", None, None)
    assert h.next_lsn(db, cid, user, art16, rng) == 0  # the log is still empty


@pytest.mark.req("SR-11.3-1", "SR-11.3-2", "SR-11.3-3", "SR-11.3-4", "SR-11.3-5", "SR-11.3-6",
                 "SR-11.3-8", "SR-11.3-11", "SR-9.5-6", "SR-9.8-4")
def test_group_deletion_certificate_passes_the_section_11_3_verifier(db16, user, art16, rng):
    """§11.3: "Accept only if every step passes." An honest group deletion must pass steps 1–6,
    checked with only the certificate and the published anchors."""
    db, cid = db16.db, db16.cid
    frozen_records(db, cid, user, art16, rng, 2, 3)
    out = db.delete(cid, "m-2-0")
    ok, step = sevlib.verify_certificate(out.certificate, h.anchors(db))
    assert ok, f"rejected at §11.3 step {step}"


@pytest.mark.req("SR-11.3-7", "SR-11.1-3", "SR-11.3-8")
def test_holding_area_deletion_certificate(db16, user, art16, rng):
    """§11.1: tags 2, 3, 4 are "empty for a holding-area deletion"; §11.3 step 7: "tags 2, 3 and 4
    are empty and tag 11 is 0. Only steps 1–5 apply." """
    db, cid = db16.db, db16.cid
    req, rec = h.insert(db, cid, "doc-hold", sevlib.ood_vector(art16, rng), user)
    assert rec.placement == "holding"
    out = db.delete(cid, "doc-hold")
    c = h.cert(out.certificate)
    assert c.kind == 1  # deletion_kind 1 = from the holding area
    assert (c.cs_pre, c.cs_post, c.proof, c.emptied) == (b"", b"", b"", 0)
    assert c.c_t == req.c_t and c.leaf_index == 0 and c.database_lsn == 1
    ok, step = sevlib.verify_certificate(out.certificate, h.anchors(db))
    assert ok, f"rejected at §11.3 step {step}"


@pytest.mark.req("SR-11.1-1", "SR-11.1-3", "SR-9.5-5", "SR-11.2-1", "SR-10.2-1")
def test_certificate_layout_field_by_field(db16, user, art16, rng):
    """§11.1: "repeat for tag = 1 … 13, in ascending order, each exactly once: u8 tag ‖ u32be
    length ‖ value; then: u8 0xFF ‖ u32be 64 ‖ operator_signature"."""
    db, cid = db16.db, db16.cid
    req = frozen_records(db, cid, user, art16, rng, 3, 2)[0]
    raw = db.delete(cid, "m-3-0").certificate
    c = h.cert(raw)  # the strict parser rejects any other tag order, length or trailing byte
    lengths = {t: len(v) for t, v in c.tags.items()}
    # Fixed sizes from the §11.1 table; tag 4 is 32 + 32 + 32·d = 576 at d = 16 (§9.5).
    assert lengths[1] == lengths[2] == lengths[3] == 32
    assert lengths[4] == 64 + 32 * 16
    assert lengths[5] == 64 and lengths[8] == 4 and lengths[9] == 64 and lengths[10] == 8
    assert lengths[11] == 1 and lengths[12] == 1 and lengths[13] == 16
    # Tag 7: u8 count ‖ count × 69 bytes; at least four cosignatures make it witnessed (§10.4).
    assert lengths[7] == 1 + 69 * len(c.cosigs) and len(c.cosigs) >= 4
    # Tag 6 (§11.2): version 1, the 209-byte insert leaf (§10.2) built from this request.
    assert c.version == 1
    leaf = c.insert_leaf
    assert leaf[0] == 0x01 and leaf[1:17] == bytes.fromhex(cid)
    assert leaf[17:81] == c.scrambled_id and leaf[81:113] == req.c_t
    assert leaf[113:145] == user.public_key and leaf[145:209] == req.signature
    # The whole certificate: TLV body, then 0xFF ‖ u32be 64 ‖ 64-byte signature, nothing more.
    assert raw[len(c.body):len(c.body) + 5] == b"\xff" + struct.pack(">I", 64)
    assert len(raw) == len(c.body) + 69
    assert c.key_period == 0  # a new database is in operator epoch 0 (§9.8)


@pytest.mark.req("SR-9.3-2", "SR-5.3-2", "SR-5.4-4", "SR-11.3-6")
def test_commitments_chain_and_empty_the_group_exactly(db16, user, art16, rng):
    """§5.3: "after the deletion every field equals the value it would have had if `t` had never
    been inserted"; §5.4: "When `n` reaches 0, ... `C_S = identity` exactly."; §9.3:
    `C_S_post + C_t = C_S_pre`."""
    db, cid = db16.db, db16.cid
    reqs = frozen_records(db, cid, user, art16, rng, 0, 3)
    cts = [r.c_t for r in reqs]
    live = list(range(3))
    prev_post = None
    for i in (1, 0, 2):
        c = h.cert(db.delete(cid, f"m-0-{i}").certificate)
        # C_S is the sum of the members' C_t (§5.3 adds C_t on insert, nothing else touches it).
        assert c.cs_pre == sevlib.r_sum_enc([cts[j] for j in live])
        live.remove(i)
        assert c.cs_post == sevlib.r_sum_enc([cts[j] for j in live])
        if prev_post is not None:
            assert c.cs_pre == prev_post  # consecutive certificates of one group chain (§11.3)
        prev_post = c.cs_post
        # Tag 11 is 1 exactly when this deletion emptied the group (§11.1, §11.3 step 6).
        assert c.emptied == (0 if live else 1)
    assert prev_post == sevlib.IDENTITY_ENC  # the all-zero encoding (§5.2)


@pytest.mark.req("SR-4.5-1", "SR-9.5-6", "SR-9.3-1", "SR-9.5-1", "SR-9.5-3")
def test_proof_verifies_for_a_state_with_negative_sums(db16, user, art16, rng):
    """§4.5: `scalar(v) = ℓ − (|v| mod ℓ)` for `v < 0`; §9.5: the operator proves knowledge of
    `s_i = scalar(S_post_i)` with `C_S_post = r_post·H + Σ s_i·G_i`."""
    db, cid = db16.db, db16.cid
    xs = [sevlib.in_dist_vector(art16, rng, 1) for _ in range(3)]
    reqs = []
    for i, x in enumerate(xs):
        req, rec = h.insert(db, cid, f"neg-{i}", x, user)
        assert rec.placement == "frozen-0001"
        reqs.append(req)
    s_post = sevlib.quantise(xs[1]) + sevlib.quantise(xs[2])
    assert (s_post < 0).any()  # the post-state S has negative components (centroids do)
    c = h.cert(db.delete(cid, "neg-0").certificate)
    # The proof only verifies if the engine committed and proved with §4.5's mapping, since the
    # SDK built every C_t with it and C_S_post is their sum (checked here first).
    assert c.cs_post == sevlib.r_add_enc(reqs[1].c_t, reqs[2].c_t)
    assert sevlib.verify_proof(c, 16)


@pytest.mark.req("SR-5.3-1", "SR-5.4-1")
def test_deletion_matches_a_twin_that_never_saw_the_record(user, art16, rng):
    """§5.3: "after the deletion every field equals the value it would have had if `t` had never
    been inserted"; §5.4 physical excision: "A deleted record is removed from the member list."
    Compared with a twin database through the public interface."""
    xs = {f"tw-{i}": sevlib.in_dist_vector(art16, rng, i % 4) for i in range(8)}
    extra = {"tw-gone-a": sevlib.in_dist_vector(art16, rng, 2),
             "tw-gone-b": sevlib.ood_vector(art16, rng)}
    a_env, b_env = h.Env(), h.Env()
    a, b = h.open_db(a_env), h.open_db(b_env)
    try:
        ca, cb = a.create_collection(h.SMALL), b.create_collection(h.SMALL)
        order = list(xs)
        for i, rid in enumerate(order):
            h.insert(a, ca, rid, xs[rid], user)
            if i == 3:  # the extra records arrive in the middle of A's stream only
                for e, v in extra.items():
                    h.insert(a, ca, e, v, user)
            h.insert(b, cb, rid, xs[rid], user)
        for e in extra:
            assert a.delete(ca, e).outcome == "deleted"
        # Group sizes (n per group) equal the twin's.
        assert a.group_sizes(ca) == b.group_sizes(cb)
        # Search over every group returns the same IDs with bit-identical scores (§8.1 depends
        # only on the members' x̂ and the centroids, both equal).
        for q in [sevlib.in_dist_vector(art16, rng, j) for j in range(4)] + [extra["tw-gone-a"]]:
            ra, rb = a.search(ca, q, k=20), b.search(cb, q, k=20)
            assert ra == rb
            assert "tw-gone-a" not in [r for r, _ in ra]
    finally:
        h.quiet_close(a)
        h.quiet_close(b)


@pytest.mark.req("SR-5.4-1")
def test_deleted_record_disappears_from_search(db16, user, art16, rng):
    """§8.1: "A deleted record MUST NOT appear in any result produced after its deletion is
    acknowledged (INV-9)." """
    db, cid = db16.db, db16.cid
    x = sevlib.in_dist_vector(art16, rng, 0)
    h.insert(db, cid, "doc-find", x, user)
    # The query equals the record's vector: score 0 in its own (probed, nearest) group.
    assert db.search(cid, x, k=1)[0][0] == "doc-find"
    db.delete(cid, "doc-find")
    assert "doc-find" not in [r for r, _ in db.search(cid, x, k=50)]


@pytest.mark.req("SR-15.3-6", "SR-10.2-3")
def test_certificate_is_retrievable_by_database_lsn(db16, user, art16, rng):
    """§15.4: "the certificate is retrievable by `database_lsn`"; `certificate(database_lsn)` is
    "The certificate of the deletion at `database_lsn` (§15.4), or `None`." """
    db, cid = db16.db, db16.cid
    frozen_records(db, cid, user, art16, rng, 0, 2)  # leaves 0, 1
    out = db.delete(cid, "m-0-0")  # leaf 2
    assert db.certificate(2) == out.certificate
    assert db.certificate(0) is None  # leaf 0 is an insert, not a deletion
    assert db.certificate(3) is None  # no leaf 3 yet


@pytest.mark.req("SR-9.7-1")
def test_scrambled_id_depends_on_collection_and_record_id(db16, user, art16, rng):
    """§9.7: `scrambled_id = HMAC-SHA-512( k_scramble, collection_id ‖ record_id_bytes )` — 64
    bytes, with one `k_scramble` per database, never rotated."""
    db, cid = db16.db, db16.cid
    cid2 = db.create_collection(h.SMALL)

    def scr(c, rid):
        h.insert(db, c, rid, sevlib.ood_vector(art16, rng), user)
        return h.cert(db.delete(c, rid).certificate).scrambled_id

    first = scr(cid, "doc-s")
    again = scr(cid, "doc-s")  # same collection and ID: same HMAC input, same key
    other_id = scr(cid, "doc-t")
    other_col = scr(cid2, "doc-s")  # different collection_id in the HMAC input
    assert len(first) == 64 and first == again
    assert first != other_id and first != other_col
    assert b"doc-s" not in first


@pytest.mark.req("SR-15.3-5", "SR-5.4-2")
def test_delete_user_deletes_in_list_order_with_chained_certificates(db16, user, art16, rng):
    """§15.3: "`delete_user(list)` does steps 1–4 for every record in list order. Each certificate
    is built on the state left by the previous one, so consecutive certificates chain." """
    db, cid = db16.db, db16.cid
    reqs = frozen_records(db, cid, user, art16, rng, 0, 3)  # leaves 0–2
    other = frozen_records(db, cid, user, art16, rng, 1, 1)  # leaf 3
    outs = db.delete_user(cid, ["m-0-2", "m-1-0", "m-0-0", "never-there", "m-0-2"])
    assert [o.outcome for o in outs] == ["deleted", "deleted", "deleted", "absent", "absent"]
    # Deletion leaves follow the four inserts in list order: 4, 5, 6.
    assert [o.database_lsn for o in outs[:3]] == [4, 5, 6]
    c0, c1, c2 = (h.cert(o.certificate) for o in outs[:3])
    assert c0.cs_pre == sevlib.r_sum_enc([r.c_t for r in reqs])
    assert c2.cs_pre == c0.cs_post  # same group, built on the state the previous one left
    assert c1.cs_pre == other[0].c_t and c1.emptied == 1  # group 1 held only this record
    assert c2.cs_post == reqs[1].c_t  # only m-0-1 remains in group 0
    anchors = h.anchors(db)
    for o in outs[:3]:
        ok, step = sevlib.verify_certificate(o.certificate, anchors)
        assert ok, step


@pytest.mark.req("SR-15.3-5")
def test_delete_user_of_an_empty_list_changes_nothing(db16, user, art16, rng):
    """§15.3: delete_user does steps 1–4 "for every record in list order": none for an empty
    list, so no leaf."""
    assert db16.db.delete_user(db16.cid, []) == []
    assert h.next_lsn(db16.db, db16.cid, user, art16, rng) == 0


@pytest.mark.req("SR-9.4-2", "SR-11.3-6")
def test_flush_folds_founders_into_a_spawned_group_that_certifies(env, user, art16, rng):
    """§7.4: "When an insert brings the holding area to exactly [the spawn target] records, the
    same transaction performs a flush"; §9.4: the engine "adds `r_t` into `r_agg` when the record
    joins a group (at insert or at a flush)"."""
    db = h.open_db(env)
    try:
        cid = db.create_collection(h.SMALL, spawn_target=8)
        ids = [f"ood-{i:02d}" for i in range(8)]
        reqs = []
        for i, rid in enumerate(ids):
            req, rec = h.insert(db, cid, rid, sevlib.ood_vector(art16, rng), user)
            reqs.append(req)
            # Seven wait in the holding area; the eighth triggers the flush, and its placement
            # is the new group's §7.5 ID (the group it is in after the transaction, §16.2).
            assert rec.placement == ("holding" if i < 7 else sevlib.spawn_id(ids))
        assert (sevlib.spawn_id(ids), 8) in db.group_sizes(cid)
        c = h.cert(db.delete(cid, "ood-03").certificate)
        assert c.kind == 0  # now a group deletion
        # C_S of the new group = r_agg·H + Σ scalar(S_i)·G_i with r_agg and S the founders' sums,
        # which equals the sum of their C_t (§9.3 is linear).
        assert c.cs_pre == sevlib.r_sum_enc([r.c_t for r in reqs])
        ok, step = sevlib.verify_certificate(c.raw, h.anchors(db))
        assert ok, step
    finally:
        h.quiet_close(db)


@pytest.mark.req("SR-9.5-5", "SR-9.6-1", "SR-11.3-8")
def test_full_dimension_certificate(env, user, rng):
    """§9.5: "proof = A ‖ z_r ‖ z_0 ‖ … ‖ z_{d−1}  # 32 + 32 + 32·d = 12,352 bytes at d = 384";
    the published anchors' gdigest is `SHA-512(H ‖ G_0 ‖ … ‖ G_383)` (§9.6, §11.3)."""
    art = sevlib.parse_artefact(h.BIG)
    db = h.open_db(env, d=384)
    try:
        cid = db.create_collection(h.BIG)
        x1 = sevlib.in_dist_vector(art, rng, 5)
        x2 = sevlib.in_dist_vector(art, rng, 5)
        r1, a = h.insert(db, cid, "big-1", x1, user)
        r2, b = h.insert(db, cid, "big-2", x2, user)
        assert a.placement == b.placement == "frozen-0005"
        anchors = h.anchors(db)
        assert anchors["d"] == 384
        assert bytes.fromhex(anchors["gdigest"]) == sevlib.gdigest(384)
        c = h.cert(db.delete(cid, "big-1").certificate, d=384)
        assert len(c.proof) == 12352
        assert c.cs_pre == sevlib.r_add_enc(r1.c_t, r2.c_t) and c.cs_post == r2.c_t
        ok, step = sevlib.verify_certificate(c.raw, anchors)
        assert ok, step
    finally:
        h.quiet_close(db)


@pytest.mark.req("SR-3.2-3", "SR-9.7-1")
def test_deleting_in_one_collection_leaves_the_other_untouched(db16, user, art16, rng):
    """§3.1: "A collection is an independent index"; the scrambled ID includes the collection_id
    (§9.7), so the same record ID in two collections names two records."""
    db = db16.db
    cid2 = db.create_collection(h.SMALL)
    h.insert(db, db16.cid, "twin-id", sevlib.in_dist_vector(art16, rng, 0), user)
    req2, _ = h.insert(db, cid2, "twin-id", sevlib.in_dist_vector(art16, rng, 0), user)
    assert db.delete(db16.cid, "twin-id").outcome == "deleted"
    # Still live in cid2: retrying its own request is the committed record (§15.1) ...
    assert db.insert(cid2, req2).retried
    # ... and its group still holds it.
    assert ("frozen-0000", 1) in db.group_sizes(cid2)
    assert ("frozen-0000", 0) in db.group_sizes(db16.cid)


@pytest.mark.req("SR-10.2-1")
def test_holding_area_record_is_not_searchable(db16, user, art16, rng):
    """§7.4: a record in the holding area "is not added to any accumulator, is not counted in N,
    and is **not searchable**"; it still has its insert leaf (§10.2)."""
    db, cid = db16.db, db16.cid
    x = sevlib.ood_vector(art16, rng)
    _, rec = h.insert(db, cid, "hidden", x, user)
    assert rec.placement == "holding" and rec.database_lsn == 0
    assert db.search(cid, x, k=10) == []  # no frozen or spawned group has a member
    assert h.total_group_n(db, cid) == 0
