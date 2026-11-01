"""§17 errors the interface can produce, §3.2 record-ID rules, §4.1 vector validation, §16.2 SDK."""

import hashlib
import os
import struct

import numpy as np
import pytest

import helpers as h
from sever_db import (
    BadUserSignature,
    Database,
    DuplicateRecord,
    IntegrityViolation,
    InvalidRecordId,
    NonFinite,
    NotNormalised,
    SeededNonceForbidden,
    SeverError,
    UnknownCollection,
    UserKey,
    WrongDimension,
    prepare_insert,
)


def _ins(db, cid, rid, x, user):
    """prepare_insert and insert together: §16.2 lets the SDK or the engine raise the §17 error."""
    return db.insert(cid, prepare_insert(cid, rid, [float(v) for v in x], user))


# ---------------------------------------------------------------- §3.2 record IDs

GOOD_IDS = [
    "doc0",  # §3.2 example
    "nq-1234",  # §3.2 example
    "123e4567-e89b-12d3-a456-426614174000",  # a UUID (§3.2 example)
    "a",  # 1 byte (lower bound)
    "x" * 256,  # 256 bytes (upper bound)
    "é" * 128,  # 2-byte characters: 256 bytes
    "3.0",  # not ^[+-]?[0-9]+$
    "+-3",  # two signs: not matched
    "١٢٣",  # Arabic-Indic digits are outside the ASCII class [0-9]
]

BAD_IDS = [
    "",  # 0 bytes (rule 1)
    "x" * 257,  # 257 bytes (rule 1)
    "é" * 129,  # 258 bytes, though only 129 characters: bytes count (rule 1)
    "1",  # §3.2 example
    "007",  # §3.2 example, leading zeros
    "-3",  # §3.2 example
    "+3",  # §3.2 example
    "0",
    "98765432109876543210987654321",  # longer than any integer type, still the counter shape
]


@pytest.mark.req("SR-3.2-1", "SR-3.2-2")
@pytest.mark.parametrize("rid", GOOD_IDS, ids=range(len(GOOD_IDS)))
def test_record_id_accepted(small_db, user, rid):
    """§3.2: "A UTF-8 string of 1 to 256 bytes" that does not match ^[+-]?[0-9]+$ is accepted."""
    db, cid, _d, _k = small_db
    r = _ins(db, cid, rid, h.in_dist(0, 0), user)
    assert r.placement == h.frozen_id(0)  # §7.3 destination, derived in helpers.in_dist
    assert db.delete(cid, rid).outcome == "deleted"


@pytest.mark.req("SR-3.2-1", "SR-3.2-2", "SR-17-2")
@pytest.mark.parametrize("rid", BAD_IDS, ids=range(len(BAD_IDS)))
def test_record_id_rejected(small_db, user, rid):
    """§3.2 rules 1–2 fail → §17 "InvalidRecordId"; "No error message may contain a record ID"."""
    db, cid, _d, _k = small_db
    with pytest.raises(InvalidRecordId) as e:
        _ins(db, cid, rid, h.in_dist(0, 0), user)
    if len(rid) >= 3:  # a 1–2 character ID could match unrelated text such as a § number
        assert rid not in str(e.value)
    assert h.total_n(db, cid) == 0  # nothing stored


@pytest.mark.req("SR-3.2-3", "SR-17-2")
def test_duplicate_live_id_with_new_request(small_db, user):
    """§3.2 rule 3: an ID "MUST NOT equal the ID of a record currently live"; §17: DuplicateRecord
    with same_commitment false (a new request carries a new r_t, hence a new C_t, §16.2)."""
    db, cid, _d, _k = small_db
    _ins(db, cid, "dup-id-xyz", h.in_dist(0, 0), user)
    with pytest.raises(DuplicateRecord) as e:
        _ins(db, cid, "dup-id-xyz", h.in_dist(0, 0), user)
    assert "dup-id-xyz" not in str(e.value)
    assert h.total_n(db, cid) == 1


@pytest.mark.req("SR-15.1-2", "SR-15.1-6")
def test_retry_same_request_is_success(small_db, user):
    """§15.1: "a retry fails with DuplicateRecord { same_commitment: true }, which the SDK treats as
    success"; API: it returns Receipt(None, None, retried=True)."""
    db, cid, _d, _k = small_db
    req = prepare_insert(cid, "retry-me", [float(v) for v in h.in_dist(1, 0)], user)
    first = db.insert(cid, req)
    assert first.retried is False and first.database_lsn == 0
    again = db.insert(cid, req)
    assert (again.database_lsn, again.placement, again.retried) == (None, None, True)
    assert h.total_n(db, cid) == 1  # nothing inserted twice


# ---------------------------------------------------------------- §4.1 vectors

@pytest.mark.req("SR-4.1-0")
@pytest.mark.parametrize("n", [15, 17, 384, 0])
def test_wrong_dimension(small_db, user, n):
    """§4.1 step 0: "The input MUST have exactly d components. Otherwise reject with WrongDimension"."""
    db, cid, _d, _k = small_db
    x = np.zeros(n, dtype=np.float32)
    if n:
        x[0] = 1.0  # normalised, so only the dimension is wrong
    with pytest.raises(WrongDimension):
        _ins(db, cid, "dim-test", x, user)


@pytest.mark.req("SR-4.1-1")
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite(small_db, user, bad):
    """§4.1 step 1: "Every component MUST be finite. Otherwise reject with NonFinite"."""
    db, cid, _d, _k = small_db
    x = h.in_dist(0, 0).astype(np.float64)
    x[5] = bad
    with pytest.raises(NonFinite):
        _ins(db, cid, "nf-test", x, user)


@pytest.mark.req("SR-4.1-3", "SR-17-2")
def test_not_normalised_no_value_in_message(small_db, user):
    """§4.1 step 3 → NotNormalised; §17: "No error message may contain ... a vector value"."""
    db, cid, _d, _k = small_db
    x = np.zeros(16, dtype=np.float32)
    x[0] = np.float32(0.6171875)  # exact in binary, norm 0.6171875 ≫ tolerance away from 1
    with pytest.raises(NotNormalised) as e:
        _ins(db, cid, "nn-test", x, user)
    assert "0.6171875" not in str(e.value) and "0.617" not in str(e.value)


@pytest.mark.req("SR-4.1-3")
def test_normalisation_tolerance_boundary(small_db, user):
    """§4.1: "|norm − 1| ≤ 8 · 2^−23 MUST hold". e_0 · (1 + 8·2^−23) has norm exactly 1 + 8·2^−23
    (float32-exact, squared and rooted exactly in f64) → accepted; 1 + 9·2^−23 → rejected."""
    db, cid, _d, _k = small_db
    ok = np.zeros(16, dtype=np.float32)
    ok[0] = np.float32(1 + 8 * 2.0**-23)
    assert h.norm_ok(ok)
    r = _ins(db, cid, "tol-ok", ok, user)
    assert r.database_lsn == 0
    bad = np.zeros(16, dtype=np.float32)
    bad[0] = np.float32(1 + 9 * 2.0**-23)
    assert not h.norm_ok(bad)
    with pytest.raises(NotNormalised):
        _ins(db, cid, "tol-bad", bad, user)


# ---------------------------------------------------------------- §16.2, §17 other errors

@pytest.mark.req("SR-17-4")
def test_signature_bound_to_collection(small_db, user):
    """§16.2: "The engine verifies the signature over the collection inserted into (§15.1 step 2),
    whatever collection the request names" → a request prepared for A fails in B: BadUserSignature."""
    db, cid_a, _d, _k = small_db
    cid_b = db.create_collection(h.SMALL_SVP)
    req = prepare_insert(cid_a, "cross", [float(v) for v in h.in_dist(0, 0)], user)
    with pytest.raises(BadUserSignature):
        db.insert(cid_b, req)
    assert h.total_n(db, cid_b) == 0
    assert db.insert(cid_a, req).database_lsn == 0  # the same request is fine where it belongs


@pytest.mark.req("SR-17-5")
def test_seeded_nonce_forbidden(small_db, user):
    """§16.2: "every SDK function that draws randomness or leads to a proof raises it
    [SeededNonceForbidden] for any argument beyond its documented ones"."""
    db, cid, _d, _k = small_db
    _ins(db, cid, "s-1", h.in_dist(0, 0), user)
    with pytest.raises(SeededNonceForbidden):
        db.delete(cid, "s-1", 42)
    with pytest.raises(SeededNonceForbidden):
        db.delete_user(cid, ["s-1"], seed=7)
    with pytest.raises(SeededNonceForbidden):
        prepare_insert(cid, "s-2", [float(v) for v in h.in_dist(0, 1)], user, b"\x00" * 32)
    with pytest.raises(SeededNonceForbidden):
        UserKey.generate(rng=None)
    assert h.total_n(db, cid) == 1  # the refused delete changed nothing


@pytest.mark.req("SR-17-1")
def test_unknown_collection_insert_and_search(small_db, user):
    """§17: UnknownCollection when there is "No such collection"."""
    db, _cid, _d, _k = small_db
    other = "ab" * 16
    with pytest.raises(UnknownCollection):
        db.insert(other, prepare_insert(other, "u-1", [float(v) for v in h.in_dist(0, 0)], user))
    with pytest.raises(UnknownCollection):
        db.search(other, [float(v) for v in h.in_dist(0, 0)], k=3)


def _corrupt_artefact(root, mutate) -> str:
    b = bytearray(open(h.SMALL_SVP, "rb").read())
    mutate(b)
    p = os.path.join(root, "bad.svp")
    open(p, "wb").write(bytes(b))
    return p


@pytest.mark.req("SR-6.3-2", "SR-17-8")
def test_bad_artefact_hash_stops_serving(small_db, root):
    """§6.3: "create_collection MUST verify sha256_artefact ... a failed check is rejected with
    IntegrityViolation"; §17: "every IntegrityViolation stops the engine serving: each later call,
    close() included, fails with IntegrityViolation"."""
    db, cid, _d, _k = small_db
    p = _corrupt_artefact(root, lambda b: b.__setitem__(200, b[200] ^ 0xFF))  # inside the centroids
    with pytest.raises(IntegrityViolation):
        db.create_collection(p)
    with pytest.raises(IntegrityViolation):
        db.collections()
    with pytest.raises(IntegrityViolation):
        db.close()


@pytest.mark.req("SR-6.3-2", "SR-6.3-3")
def test_artefact_non_finite_precision(small_db, root):
    """§6.3: create_collection MUST verify "that P has finite entries" → IntegrityViolation. The hash
    is recomputed so that only the finiteness check can fail."""
    db, _cid, _d, _k = small_db
    a = h.art()

    def mutate(b):
        p_off = a.body_len - 8 * a.d * a.d  # P[0][0]
        b[p_off : p_off + 8] = struct.pack(">d", float("nan"))
        b[a.body_len :] = hashlib.sha256(bytes(b[: a.body_len])).digest()

    with pytest.raises(IntegrityViolation) as e:
        db.create_collection(_corrupt_artefact(root, mutate))
    # DB-64 / SR-6.3-3: the error names the check, "never a value" → the NaN is not printed.
    assert "nan" not in str(e.value).lower()


@pytest.mark.req("SR-6.3-2")
def test_artefact_wrong_dimension(root):
    """§6.3: create_collection MUST verify "d": a d = 16 artefact in a d = 384 database fails."""
    data, keys = h.new_dirs(root)
    db = h.open_db(data, keys, d=384)
    with pytest.raises(IntegrityViolation):
        db.create_collection(h.SMALL_SVP)


@pytest.mark.req("SR-17-1")
def test_all_errors_are_sever_errors():
    """§17: "Every error is typed." Every §17 name is exported as a SeverError subclass."""
    import sever_db

    names = [
        "WrongDimension", "NonFinite", "NotNormalised", "InvalidRecordId", "DuplicateRecord",
        "CommitmentMismatch", "BadUserSignature", "GroupCapacityExceeded", "UnknownCollection",
        "SeededNonceForbidden", "PlatformUnsafe", "IntegrityViolation", "DurabilityFailure",
    ]  # the §17 table, in order
    for n in names:
        assert issubclass(getattr(sever_db, n), SeverError)


@pytest.mark.req("SR-16.2-2")
def test_placement_text_forms(small_db, user):
    """§16.2: placement is "the §5.1 text form of the group the record is in after the transaction:
    frozen-NNNN, spawn- followed by 16 lowercase hex characters, or holding"."""
    db, cid, _d, _k = small_db
    for j in range(4):
        assert _ins(db, cid, f"pl-{j}", h.in_dist(j, 0), user).placement == f"frozen-000{j}"
    assert _ins(db, cid, "pl-ood", h.ood(9), user).placement == "holding"


@pytest.mark.req("SR-16.2-1")
def test_user_key_round_trip(small_db):
    """§16.2 / §3.3: the backend keeps the user key and reloads it; a reloaded key signs the same
    account (same public key), so its requests insert normally."""
    db, cid, _d, _k = small_db
    u = UserKey.generate()
    u2 = UserKey.from_secret_bytes(u.secret_bytes())
    assert u2.public_key == u.public_key and len(u.public_key) == 32  # Ed25519 (§9.8)
    req = prepare_insert(cid, "uk-1", [float(v) for v in h.in_dist(2, 0)], u2)
    assert req.user_public_key == u.public_key
    assert db.insert(cid, req).placement == h.frozen_id(2)


@pytest.mark.req("SR-17-5")
def test_database_open_rejects_randomness(dirs):
    """§16.2: SDK functions refuse any argument beyond the documented ones (SeededNonceForbidden)."""
    data, keys = dirs
    with pytest.raises(SeededNonceForbidden):
        Database.open(data, keys, 16, False, True, 1234)
