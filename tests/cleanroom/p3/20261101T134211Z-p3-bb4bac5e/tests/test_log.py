"""The transparency log, log checkpoints and witnesses (§10), and the anchors (§11.3)."""

import hashlib

import pytest

import helpers as h
import sevlib


def check_checkpoint_signatures(cp, anchors):
    """§9.8: operator over DST_STH ‖ …(66 bytes); witnesses over DST_COSIGN ‖ the same (83)."""
    msg = sevlib.Checkpoint(cp.tree_size, cp.root, cp.timestamp_ms, cp.epoch, cp.operator_signature)
    m = msg.message()
    assert len(m) == 66
    op = bytes.fromhex(anchors["operator"][str(cp.epoch)])
    assert sevlib.ed25519_verify(op, m, cp.operator_signature)
    good = set()
    for c in cp.cosignatures:
        if c.witness_index >= len(anchors["witnesses"]):
            continue
        hexkey = anchors["witnesses"][c.witness_index].get(str(c.witness_epoch))
        if hexkey and sevlib.ed25519_verify(bytes.fromhex(hexkey), sevlib.DST_COSIGN + m, c.signature):
            good.add(c.witness_index)
    return good


@pytest.mark.req("SR-10.3-4", "SR-9.8-2", "SR-10.3-1")
def test_genesis_log_checkpoint(db16):
    """§10.3: "The genesis log checkpoint is `(tree_size 0, root SHA-256(""), timestamp_ms =
    database creation time, epoch 0)`, signed by the operator when the database is created." """
    cp = db16.db.latest_log_checkpoint()
    assert cp.tree_size == 0
    assert cp.root == hashlib.sha256(b"").digest()
    assert cp.epoch == 0
    assert cp.timestamp_ms > 1_600_000_000_000  # a real creation time in ms (after 2020)
    check_checkpoint_signatures(cp, h.anchors(db16.db))  # the operator signature verifies


@pytest.mark.req("SR-11.3-11", "SR-9.6-1", "SR-10.4-2")
def test_anchors_of_a_new_database(db16):
    """§11.3: anchors are `{"d": N, "gdigest": hex, "operator": {"<epoch>": hex key},
    "witnesses": [{"<epoch>": hex key}, …]}`; "From the database's creation the anchors list the
    operator's and every witness's epoch-0 key"."""
    a = h.anchors(db16.db)
    assert a["d"] == 16
    # gdigest = SHA-512(H ‖ G_0 ‖ … ‖ G_15) with the §9.2 generators.
    assert bytes.fromhex(a["gdigest"]) == sevlib.gdigest(16)
    assert len(bytes.fromhex(a["operator"]["0"])) == 32
    assert len(a["witnesses"]) == 5  # five witnesses (§10.4)
    keys = [bytes.fromhex(w["0"]) for w in a["witnesses"]]
    assert all(len(k) == 32 for k in keys) and len(set(keys)) == 5


@pytest.mark.req("SR-10.2-3", "SR-10.2-1")
def test_every_insert_takes_the_next_leaf_whatever_its_placement(db16, user, art16, rng):
    """§10.2: the insert leaf is appended on "Every insert, including holding-area inserts";
    "`database_lsn` of an operation is the 0-based index of its leaf"."""
    db, cid = db16.db, db16.cid
    lsns = []
    for i in range(6):
        x = sevlib.ood_vector(art16, rng) if i % 2 else sevlib.in_dist_vector(art16, rng)
        lsns.append(h.insert(db, cid, f"seq-{i}", x, user)[1].database_lsn)
    assert lsns == [0, 1, 2, 3, 4, 5]


@pytest.mark.req("SR-10.3-3", "SR-15.3-3", "SR-10.4-2", "SR-9.8-3")
def test_deletion_is_preceded_by_a_witnessed_checkpoint_at_the_current_size(db16, user, art16, rng):
    """§10.3: the engine issues a log checkpoint "on demand before a deletion, at the current size,
    if a witnessed log checkpoint does not cover every leaf"; §10.4: "A log checkpoint with at
    least four valid cosignatures is witnessed." """
    db, cid = db16.db, db16.cid
    for i in range(3):
        h.insert(db, cid, f"cp-{i}", sevlib.in_dist_vector(art16, rng), user)  # leaves 0–2
    out = db.delete(cid, "cp-1")  # leaf 3
    cp = db.latest_log_checkpoint()
    # Only genesis (size 0) existed, which does not cover leaves 0–2: an on-demand one at the
    # current size 3 is committed before the deletion. The deletion leaf (3) is not yet covered.
    assert cp.tree_size == 3
    assert len(check_checkpoint_signatures(cp, h.anchors(db))) >= 4
    c = h.cert(out.certificate)
    # The certificate's checkpoint covers the insert leaf (1) and only committed leaves (< 3+1).
    assert c.leaf_index < c.checkpoint.tree_size <= c.database_lsn


@pytest.mark.req("SR-10.1-1", "SR-10.2-2", "SR-10.2-1")
def test_log_root_recomputed_from_known_leaves(db16, user, art16, rng):
    """§10.1: "`leaf_hash = SHA-256(0x00 ‖ leaf)`, `node_hash = SHA-256(0x01 ‖ left ‖ right)`, the
    left-heavy tree"; §10.2: the delete leaf is `0x02 ‖` certificate bytes."""
    db, cid = db16.db, db16.cid
    h.insert(db, cid, "rt-a", sevlib.in_dist_vector(art16, rng, 0), user)  # leaf 0
    h.insert(db, cid, "rt-b", sevlib.in_dist_vector(art16, rng, 1), user)  # leaf 1
    da = db.delete(cid, "rt-a")  # leaf 2
    db_ = db.delete(cid, "rt-b")  # leaf 3; its checkpoint must cover leaves 0–2
    ca, cb = h.cert(da.certificate), h.cert(db_.certificate)
    leaves = [ca.insert_leaf, cb.insert_leaf, b"\x02" + da.certificate]
    # Before the second deletion the latest witnessed checkpoint (size 2) did not cover leaf 2, so
    # one at size 3 was issued; its root is MTH of the three known leaves.
    cp = db.latest_log_checkpoint()
    assert cp.tree_size == 3
    assert cp.root == sevlib.mth(leaves)
    # The first deletion's checkpoint is the only one covering leaf 0 (genesis is empty): size 2,
    # the two insert leaves.
    assert ca.checkpoint.tree_size == 2 and ca.checkpoint.root == sevlib.mth(leaves[:2])
    # The second may name size 2 or 3 (both cover leaf 1, NOTES.md #9); its root is MTH there.
    n = cb.checkpoint.tree_size
    assert n in (2, 3) and cb.checkpoint.root == sevlib.mth(leaves[:n])


@pytest.mark.req("SR-10.1-2", "SR-11.2-1")
def test_inclusion_proofs_are_rfc9162_paths(db16, user, art16, rng):
    """§10.1: "Inclusion and consistency proofs use RFC 9162's own algorithms." """
    db, cid = db16.db, db16.cid
    n = 7
    for i in range(n):
        h.insert(db, cid, f"inc-{i}", sevlib.ood_vector(art16, rng), user)
    certs = [h.cert(db.delete(cid, f"inc-{i}").certificate) for i in range(n)]
    leaf_hashes = [sevlib.leaf_hash(c.insert_leaf) for c in certs]  # leaves 0–6, in order
    for i, c in enumerate(certs):
        assert c.leaf_index == i
        # The certificate's path is PATH(i, D[tree_size]) and verifies against its root.
        assert sevlib.verify_inclusion(i, c.checkpoint.tree_size, leaf_hashes[i], c.path,
                                       c.checkpoint.root)
        assert db.inclusion_proof(i, c.checkpoint.tree_size) == c.path
    # Over the first seven leaves alone (the inserts), PATH(m, D[7]) for every m.
    for m in range(n):
        assert db.inclusion_proof(m, n) == sevlib.inclusion_path(leaf_hashes, m)


@pytest.mark.req("SR-10.1-2")
def test_inclusion_proof_out_of_range_is_none(db16, user, art16, rng):
    """`inclusion_proof`: "RFC 9162 inclusion proof (§10.1), or `None` if the sizes are out of
    range" — a leaf must lie inside a tree no larger than the log."""
    db, cid = db16.db, db16.cid
    for i in range(3):
        h.insert(db, cid, f"oor-{i}", sevlib.ood_vector(art16, rng), user)  # 3 leaves
    assert db.inclusion_proof(3, 3) is None  # leaf index = tree size
    assert db.inclusion_proof(0, 4) is None  # tree larger than the log
    assert db.inclusion_proof(0, 0) is None  # empty tree
    assert db.inclusion_proof(0, 1) == []  # a one-leaf tree: the empty path (RFC 9162)


@pytest.mark.req("SR-10.1-2", "SR-10.4-1")
def test_consistency_proof_between_two_checkpoints(db16, user, art16, rng):
    """§10.1: consistency proofs use RFC 9162; "A consistency proof exists only for `0 < old_size <
    new_size ≤ tree_size` ... `consistency_proof` returns none for any other pair, `old_size =
    new_size` included (G-50)." """
    db, cid = db16.db, db16.cid
    for i in range(3):
        h.insert(db, cid, f"cs-{i}", sevlib.in_dist_vector(art16, rng), user)
    db.delete(cid, "cs-0")  # checkpoint at 3, leaf 3
    old = db.latest_log_checkpoint()
    for i in range(3, 6):
        h.insert(db, cid, f"cs-{i}", sevlib.in_dist_vector(art16, rng), user)  # leaves 4–6
    db.delete(cid, "cs-4")  # checkpoint at 7, leaf 7
    new = db.latest_log_checkpoint()
    assert (old.tree_size, new.tree_size) == (3, 7)
    proof = db.consistency_proof(3, 7)
    assert sevlib.verify_consistency(3, 7, old.root, new.root, proof)
    assert db.consistency_proof(3, 3) is None  # old_size = new_size
    assert db.consistency_proof(0, 7) is None  # old_size = 0
    assert db.consistency_proof(7, 3) is None  # old > new
    assert db.consistency_proof(3, 9) is None  # new_size beyond the 8 leaves


@pytest.mark.req("SR-10.3-3", "SR-10.4-1", "SR-10.4-2")
def test_witnessed_checkpoint_is_not_reissued_when_it_covers_every_leaf(db16, user, art16, rng):
    """§10.3: the on-demand checkpoint is issued "if a witnessed log checkpoint does not cover
    every leaf"; when one does, none is needed. Each deletion leaf is a new leaf, though."""
    db, cid = db16.db, db16.cid
    for i in range(2):
        h.insert(db, cid, f"rw-{i}", sevlib.in_dist_vector(art16, rng), user)
    db.delete(cid, "rw-0")  # checkpoint at 2; leaf 2 = the deletion
    a = db.latest_log_checkpoint()
    out = db.delete(cid, "rw-1")  # leaf 2 is not covered: a checkpoint at size 3 first
    b = db.latest_log_checkpoint()
    assert (a.tree_size, b.tree_size) == (2, 3)
    # Either witnessed checkpoint covers rw-1's leaf (NOTES.md #9); it must be one of them.
    used = h.cert(out.certificate).checkpoint
    assert (used.tree_size, used.root) in ((a.tree_size, a.root), (b.tree_size, b.root))
    assert len(check_checkpoint_signatures(b, h.anchors(db))) >= 4
    assert sevlib.verify_consistency(2, 3, a.root, b.root, db.consistency_proof(2, 3))
