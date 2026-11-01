"""The application-backend SDK (§16.2), user keys (§3.3, §9.8), blinding values (§9.4) and the
ban on supplied randomness (§9.6, §16.2, §17)."""

import re

import pytest
import sever_db_p3 as sdk

import helpers as h
import sevlib


@pytest.mark.req("SR-3.3-2", "SR-16.2-1")
def test_user_key_is_ed25519_and_reloads_from_its_secret(user):
    """§3.3: "A user (an account) is identified by an Ed25519 key pair, the user key, which the
    application backend generates for the account and keeps in its key store." """
    secret = user.secret_bytes()
    # Ed25519 (RFC 8032): a 32-byte secret seed and a 32-byte public key.
    assert len(secret) == 32 and len(user.public_key) == 32
    again = sdk.UserKey.from_secret_bytes(secret)
    # The public key is a function of the secret: reloading gives the same account.
    assert again.public_key == user.public_key
    # §17 spirit and the SDK's own docstring: a key is never printed.
    assert secret.hex() not in repr(user)


@pytest.mark.req("SR-16.2-1", "SR-9.8-1", "SR-3.3-2")
def test_prepared_request_is_signed_over_dst_insert_collection_and_ct(db16, user, art16, rng):
    """§9.8: the user key signs "DST_INSERT ‖ collection_id ‖ C_t (65 bytes)"; §16.2:
    "prepare_insert quantises (§4.2), draws r_t (§9.4), computes C_t, signs." """
    req = sdk.prepare_insert(db16.cid, "doc-sig", sevlib.ood_vector(art16, rng), user)
    assert req.collection_id == db16.cid and req.record_id == "doc-sig"
    assert req.user_public_key == user.public_key
    cid_bytes = bytes.fromhex(db16.cid)  # §3.1: 16 bytes, shown as 32 hex characters
    msg = sevlib.DST_INSERT + cid_bytes + req.c_t
    assert len(msg) == 65  # 17 + 16 + 32 (§9.8, Appendix A)
    assert sevlib.ed25519_verify(user.public_key, msg, req.signature)
    # §9.9: C_t is a canonical ristretto255 point and never the identity.
    sevlib.r_decode(req.c_t)
    assert req.c_t != sevlib.IDENTITY_ENC


@pytest.mark.req("SR-9.4-1")
def test_each_request_draws_a_fresh_blinding_value(db16, user, art16, rng):
    """§9.4: the backend "generates `r_t` as 64 bytes from the OS CSPRNG" for every record; §16.2:
    "a new request would carry a new `r_t`, hence a new `C_t`." """
    vec = sevlib.ood_vector(art16, rng)
    a = sdk.prepare_insert(db16.cid, "doc-same", vec, user)
    b = sdk.prepare_insert(db16.cid, "doc-same", vec, user)
    # Same x̃, independent r_t: C_t = r_t·H + Σ scalar(x̃_i)·G_i differ unless r_t repeats
    # (probability 1/ℓ ≈ 2^−252).
    assert a.c_t != b.c_t


@pytest.mark.req("SR-16.2-1", "SR-9.4-2")
def test_request_exposes_no_blinding_value(db16, user, art16, rng):
    """§16.2: "`r_t` cannot be read from the request." """
    req = sdk.prepare_insert(db16.cid, "doc-hidden", sevlib.ood_vector(art16, rng), user)
    names = [n for n in dir(req) if not n.startswith("__")]
    assert not [n for n in names if re.search(r"(^|_)r_?t($|_)|blind", n, re.I)]


@pytest.mark.req("SR-16.2-2", "SR-15.1-5")
def test_placement_names_the_nearest_frozen_group(db16, user, art16, rng):
    """§16.2: "The SDK and the command-line tool report the placement as the §5.1 text form of
    the group the record is in after the transaction: `frozen-NNNN`, ..." """
    db, cid = db16.db, db16.cid
    for label in range(art16.k):
        # An in-distribution vector for this label (d_M ≤ 0.7τ, §7.2), so §7.3 returns frozen
        # group j* = label (§7.1); §5.1 writes it as frozen- + 4-digit zero-padded label.
        x = sevlib.in_dist_vector(art16, rng, label=label)
        _, rec = h.insert(db, cid, f"doc-frozen-{label}", x, user)
        assert rec.placement == f"frozen-{label:04d}"
        assert rec.database_lsn == label  # leaves 0, 1, 2, 3 in order (§10.2)


@pytest.mark.req("SR-16.2-2")
def test_placement_of_an_out_of_distribution_vector_is_holding(db16, user, art16, rng):
    """§7.3: an OOD vector with no spawned group that has room goes to the holding area; §16.2
    reports it as `holding`."""
    # d_M > 1.5τ: out of distribution (§7.2). A new collection has no spawned group, so R is
    # empty and route() returns the holding area.
    _, rec = h.insert(db16.db, db16.cid, "doc-ood", sevlib.ood_vector(art16, rng), user)
    assert rec.placement == "holding"
    # A holding-area insert gets a leaf like every insert (§10.2): leaf 0.
    assert rec.database_lsn == 0


@pytest.mark.req("SR-15.1-6", "SR-15.1-2")
def test_retry_with_the_same_request_is_success_without_a_new_leaf(db16, user, art16, rng):
    """§15.1: "a retry fails with `DuplicateRecord { same_commitment: true }`, which the SDK treats
    as success." """
    db, cid = db16.db, db16.cid
    req = sdk.prepare_insert(cid, "doc-retry", sevlib.in_dist_vector(art16, rng), user)
    first = db.insert(cid, req)
    assert first.database_lsn == 0 and not first.retried
    again = db.insert(cid, req)  # the same request: same C_t as the live record
    assert again.retried
    # The retry committed nothing, so the log still has one leaf: the next insert is leaf 1.
    assert h.next_lsn(db, cid, user, art16, rng) == 1


@pytest.mark.req("SR-17-4", "SR-15.1-3")
def test_request_signed_for_another_collection_is_a_bad_signature(db16, user, art16, rng):
    """§16.2: "The engine verifies the signature over the collection inserted into (§15.1 step 2),
    whatever collection the request names". §17: BadUserSignature when the insert signature
    fails."""
    db = db16.db
    other = db.create_collection(h.SMALL)
    req = sdk.prepare_insert(other, "doc-x", sevlib.ood_vector(art16, rng), user)
    # The signature covers DST_INSERT ‖ other ‖ C_t; checked against db16.cid it fails.
    with pytest.raises(sdk.BadUserSignature):
        db.insert(db16.cid, req)
    # Nothing was inserted: the record is not live in db16.cid ...
    assert db.delete(db16.cid, "doc-x").outcome == "absent"
    # ... and the same request still works where it was signed for: leaf 0, the first leaf.
    assert db.insert(other, req).database_lsn == 0


@pytest.mark.req("SR-9.6-4", "SR-17-5")
@pytest.mark.parametrize("call", ["generate_pos", "generate_kw", "prepare_pos", "prepare_kw"])
def test_randomness_cannot_be_supplied_to_key_or_request_creation(db16, user, art16, rng, call):
    """§16.2: "every SDK function that draws randomness or leads to a proof raises it
    [SeededNonceForbidden] for any argument beyond its documented ones (DB-84)." """
    vec = sevlib.ood_vector(art16, rng)
    with pytest.raises(sdk.SeededNonceForbidden):
        if call == "generate_pos":
            sdk.UserKey.generate(42)
        elif call == "generate_kw":
            sdk.UserKey.generate(seed=42)
        elif call == "prepare_pos":
            sdk.prepare_insert(db16.cid, "doc-n", vec, user, b"\x00" * 32)
        else:
            sdk.prepare_insert(db16.cid, "doc-n", vec, user, rng=rng)


@pytest.mark.req("SR-9.6-4", "SR-17-5", "SR-3.3-3")
@pytest.mark.parametrize("how", ["delete_pos", "delete_kw", "delete_user_pos", "delete_user_kw"])
def test_randomness_cannot_be_supplied_to_a_deletion(db16, user, art16, rng, how):
    """§9.6: "The Python binding exposes no way to pass an RNG, a seed or a nonce; any attempt
    raises `SeededNonceForbidden`." A deletion leads to a proof (§9.5)."""
    db, cid = db16.db, db16.cid
    h.insert(db, cid, "doc-keep", sevlib.in_dist_vector(art16, rng), user)  # leaf 0
    with pytest.raises(sdk.SeededNonceForbidden):
        if how == "delete_pos":
            db.delete(cid, "doc-keep", 7)
        elif how == "delete_kw":
            db.delete(cid, "doc-keep", nonce=b"\x01" * 32)
        elif how == "delete_user_pos":
            db.delete_user(cid, ["doc-keep"], rng)
        else:
            db.delete_user(cid, ["doc-keep"], seed=7)
    # The refused call deleted nothing: the record is still live, and its deletion is leaf 1.
    out = db.delete(cid, "doc-keep")
    assert out.outcome == "deleted" and out.database_lsn == 1


@pytest.mark.req("SR-9.6-4", "SR-17-5")
def test_randomness_cannot_be_supplied_to_open_or_insert(env, user, art16, rng):
    """§16.2: any argument beyond the documented ones raises SeededNonceForbidden (DB-84)."""
    with pytest.raises(sdk.SeededNonceForbidden):
        sdk.Database.open(env.data, env.keys, 16, False, rng)
    with pytest.raises(sdk.SeededNonceForbidden):
        sdk.Database.open(env.data, env.keys, d=16, seed=1)
    db = h.open_db(env)
    try:
        cid = db.create_collection(h.SMALL)
        req = sdk.prepare_insert(cid, "doc-i", sevlib.ood_vector(art16, rng), user)
        with pytest.raises(sdk.SeededNonceForbidden):
            db.insert(cid, req, None, rng)
        with pytest.raises(sdk.SeededNonceForbidden):
            db.insert(cid, req, nonce=1)
        # Nothing was inserted by the refused calls: this insert is the first leaf.
        assert db.insert(cid, req).database_lsn == 0
    finally:
        h.quiet_close(db)


@pytest.mark.req("SR-3.3-3", "SR-16.2-1")
def test_delete_needs_no_signature_key_or_blinding_value(db16, art16, rng):
    """§3.3: "The engine performs no authorisation of its own." §16.2: `engine.delete(
    collection_id, record_id)  # no r_t argument`. Another account's backend call deletes it."""
    owner = sdk.UserKey.generate()
    h.insert(db16.db, db16.cid, "doc-owned", sevlib.in_dist_vector(art16, rng), owner)
    del owner  # the backend needs nothing of the account to delete
    out = db16.db.delete(db16.cid, "doc-owned")
    assert out.outcome == "deleted" and out.certificate
