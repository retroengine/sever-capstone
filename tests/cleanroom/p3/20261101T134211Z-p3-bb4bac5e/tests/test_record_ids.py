"""Record-ID rules (§3.2), checked by insert step 1 (§15.1), and their errors (§17)."""

import pytest
import sever_db_p3 as sdk

import helpers as h
import sevlib


@pytest.mark.req("SR-3.2-1", "SR-15.1-5")
@pytest.mark.parametrize("rid", ["a", "x" * 256, "é" * 128, "€" * 85 + "a"])
def test_record_id_of_1_to_256_bytes_is_accepted(db16, user, art16, rng, rid):
    """§3.2 rule 1: "A UTF-8 string of 1 to 256 bytes." Lengths count bytes, not characters."""
    # "é" is 2 UTF-8 bytes (128 × 2 = 256); "€" is 3 bytes (85 × 3 + 1 = 256): both at the limit.
    assert 1 <= len(rid.encode()) <= 256
    _, rec = h.insert(db16.db, db16.cid, rid, sevlib.ood_vector(art16, rng), user)
    # First leaf of a new database: database_lsn is the 0-based leaf index (§10.2), so 0.
    assert rec.database_lsn == 0


@pytest.mark.req("SR-3.2-1", "SR-17-1")
@pytest.mark.parametrize("rid", ["", "x" * 257, "é" * 128 + "x", "€" * 86])
def test_record_id_outside_1_to_256_bytes_is_rejected(db16, user, art16, rng, rid):
    """§3.2 rule 1: "A UTF-8 string of 1 to 256 bytes." §17: InvalidRecordId when §3.2 rules 1–2
    fail."""
    # 0, 257, 257 (128·2 + 1) and 258 (86·3) bytes: each outside 1…256.
    with pytest.raises(sdk.InvalidRecordId):
        h.prepare_and_insert(db16.db, db16.cid, rid, sevlib.ood_vector(art16, rng), user)
    # A rejected insert appends no leaf (§10.2 appends on an insert, which did not happen), so the
    # next insert is still leaf 0.
    assert h.next_lsn(db16.db, db16.cid, user, art16, rng) == 0


@pytest.mark.req("SR-3.2-1")
def test_record_id_with_lone_surrogate_is_rejected(db16, user, art16, rng):
    """§3.2 rule 1: a record ID is "A UTF-8 string". A lone surrogate has no UTF-8 encoding."""
    # "\ud800" cannot be encoded in UTF-8, so rule 1 fails: InvalidRecordId (§17).
    with pytest.raises(sdk.InvalidRecordId):
        h.prepare_and_insert(db16.db, db16.cid, "doc-\ud800", sevlib.ood_vector(art16, rng), user)


@pytest.mark.req("SR-3.2-2")
@pytest.mark.parametrize("rid", ["1", "007", "-3", "+3", "0", "-0", "+0000",
                                 "123456789012345678901234567890123456789012345678901234567890"])
def test_bare_decimal_integer_id_is_rejected(db16, user, art16, rng, rid):
    """§3.2 rule 2: "It MUST NOT match ^[+-]?[0-9]+$ (a bare decimal integer, with or without sign
    or leading zeros). ... `1`, `007`, `-3` and `+3` are rejected." """
    # Each matches ^[+-]?[0-9]+$ in full, so InvalidRecordId (§17).
    with pytest.raises(sdk.InvalidRecordId):
        h.prepare_and_insert(db16.db, db16.cid, rid, sevlib.ood_vector(art16, rng), user)


@pytest.mark.req("SR-3.2-2")
@pytest.mark.parametrize("rid", ["doc0", "nq-1234", "0b8f9a3e-5c1d-4e8a-9f2b-7d6c5e4a3b21",
                                 "1.5", "1e3", "0x1F", "+-3", "--3", "3-", " 7", "7 ", "٣٤",
                                 "１２"])
def test_id_that_is_not_a_bare_decimal_integer_is_accepted(db16, user, art16, rng, rid):
    """§3.2 rule 2: "`doc0`, `nq-1234` and UUIDs are accepted". The pattern is ^[+-]?[0-9]+$,
    with [0-9] the ASCII digits only."""
    # None of these matches the whole pattern: a dot, an 'e', an 'x', two signs, a trailing sign,
    # a space, or non-ASCII digits (Arabic-Indic, full-width). So the insert succeeds.
    _, rec = h.insert(db16.db, db16.cid, rid, sevlib.ood_vector(art16, rng), user)
    assert rec.database_lsn == 0  # the first leaf (§10.2)


@pytest.mark.req("SR-3.2-3", "SR-17-1")
def test_insert_of_a_live_id_with_a_new_request_is_duplicate(db16, user, art16, rng):
    """§3.2 rule 3: "It MUST NOT equal the ID of a record currently live in the same collection."
    §17: DuplicateRecord { same_commitment } — false here, so the SDK re-raises it."""
    h.insert(db16.db, db16.cid, "doc-a", sevlib.ood_vector(art16, rng), user)
    # A new request carries a fresh r_t, hence a different C_t (§16.2): same_commitment is false,
    # and the SDK only turns a same_commitment = true duplicate into success.
    with pytest.raises(sdk.DuplicateRecord) as ei:
        h.prepare_and_insert(db16.db, db16.cid, "doc-a", sevlib.ood_vector(art16, rng), user)
    assert ei.value.args[:1] != (True,)
    # The failed insert appended nothing: leaves are only the first insert (leaf 0), so the next
    # insert is leaf 1.
    assert h.next_lsn(db16.db, db16.cid, user, art16, rng) == 1


@pytest.mark.req("SR-3.2-4", "SR-10.2-1")
def test_id_may_be_inserted_again_after_deletion(db16, user, art16, rng):
    """§3.2: "A record ID MAY be inserted again after its record has been deleted. The new record
    is a new insert, with a new log leaf." """
    db, cid = db16.db, db16.cid
    h.insert(db, cid, "doc-r", sevlib.ood_vector(art16, rng), user)  # leaf 0
    first = db.delete(cid, "doc-r")  # leaf 1
    assert first.outcome == "deleted" and first.database_lsn == 1
    req, rec = h.insert(db, cid, "doc-r", sevlib.ood_vector(art16, rng), user)
    assert rec.database_lsn == 2  # a new leaf, after the insert (0) and the deletion (1)
    second = db.delete(cid, "doc-r")
    assert second.outcome == "deleted" and second.database_lsn == 3
    c = h.cert(second.certificate)
    # The second certificate is for the second insert: its insert leaf is leaf 2 and its C_t is
    # the new request's (§11.1 tag 1, §11.2 leaf_index).
    assert c.leaf_index == 2 and c.c_t == req.c_t


@pytest.mark.req("SR-3.2-3")
def test_same_id_in_two_collections_is_allowed(db16, user, art16, rng):
    """§3.2 rule 3 forbids a live duplicate "in the same collection" only; §3.1: "A collection is
    an independent index"."""
    db = db16.db
    cid2 = db.create_collection(h.SMALL)
    assert cid2 != db16.cid  # 16 random bytes each (§3.1)
    _, a = h.insert(db, db16.cid, "shared-id", sevlib.ood_vector(art16, rng), user)
    _, b = h.insert(db, cid2, "shared-id", sevlib.ood_vector(art16, rng), user)
    # One log for the whole database (§3.1): leaves 0 and 1.
    assert (a.database_lsn, b.database_lsn) == (0, 1)


@pytest.mark.req("SR-17-2", "SR-3.2-2")
def test_invalid_record_id_error_does_not_contain_the_id(db16, user, art16, rng):
    """§17: "No error message may contain a record ID, a vector value, a key, `r_t` or passage
    text." """
    rid = "73519468207"  # a bare integer: InvalidRecordId by §3.2 rule 2
    with pytest.raises(sdk.InvalidRecordId) as ei:
        h.prepare_and_insert(db16.db, db16.cid, rid, sevlib.ood_vector(art16, rng), user)
    assert rid not in str(ei.value) and rid not in repr(ei.value)


@pytest.mark.req("SR-17-2", "SR-3.2-3")
def test_duplicate_record_error_does_not_contain_the_id(db16, user, art16, rng):
    """§17: "No error message may contain a record ID ..." — DuplicateRecord included."""
    rid = "patient-ZQX-delicate-9931"
    h.insert(db16.db, db16.cid, rid, sevlib.ood_vector(art16, rng), user)
    with pytest.raises(sdk.DuplicateRecord) as ei:
        h.prepare_and_insert(db16.db, db16.cid, rid, sevlib.ood_vector(art16, rng), user)
    text = str(ei.value) + repr(ei.value) + repr(ei.value.args)
    assert "ZQX-delicate" not in text
