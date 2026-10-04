"""Group tests (spec §4.4, §5.2-5.6, §17; DEMO_PLAN T5-T10).

Expected values come from tests/spec_oracle.py (written from the spec text) or are written out by
hand. The code's own helpers (compare, snapshot, survivors_check) never judge the code; they are
tested separately against the spec rule they implement.

The T5-T10 functions take no fixtures on purpose: test_sabotage.py calls them directly with a
deliberate bug switched on and checks that they fail.
"""

import dataclasses
import struct

import numpy as np
import pytest

from sever_demo.errors import (
    DuplicateRecord,
    GroupCapacityExceeded,
    IntegrityViolation,
    Outcome,
)
from sever_demo.group import Group, compare, survivors_check, survivors_report
from spec_oracle import expected, field_diffs, group_blob, observed
from synthetic import SEED, D, quantised_rows, record_ids

N_ROWS = 60


def filled(n_rows: int = N_ROWS, extra: int = 0) -> tuple[Group, dict[str, int], list[list[int]]]:
    """A group holding doc0..doc{n_rows-1}; `extra` more vectors exist but are not inserted."""
    vectors = quantised_rows(n_rows + extra)
    g = Group(vectors)
    live = {}
    for row, rid in enumerate(record_ids(n_rows)):
        g.insert(rid, row)
        live[rid] = row
    return g, live, vectors.tolist()


def members_of(live: dict[str, int], vecs: list[list[int]]) -> dict[str, list[int]]:
    return {rid: vecs[row] for rid, row in live.items()}


def test_group_initial_state() -> None:
    # §5.2: S = 0, n = 0, no members. §4.4: S is i64.
    g = Group(quantised_rows(1))
    assert g.S.dtype == np.int64
    assert observed(g) == expected({}, D)


def test_blob_golden_bytes() -> None:
    # The layout written out byte by byte, by hand, for d = 2 and two members:
    # "b" -> (1, -1), "a" -> (2, 3). S = (3, 2), n = 2, members sorted: "a" then "b".
    golden = (
        b"SEVERC"
        + b"\x00\x01"  # version 1
        + b"\x00\x02"  # d = 2
        + b"\x00\x00\x00\x00\x00\x00\x00\x02"  # n = 2
        + b"\x00\x00\x00\x00\x00\x00\x00\x03"  # S_0 = 3
        + b"\x00\x00\x00\x00\x00\x00\x00\x02"  # S_1 = 2
        + b"\x00\x00\x00\x00\x00\x00\x00\x02"  # member_count = 2
        + b"\x00\x01a"  # id_len 1, "a"
        + b"\x00\x00\x00\x00\x00\x00\x00\x02"  # 2
        + b"\x00\x00\x00\x00\x00\x00\x00\x03"  # 3
        + b"\x00\x01b"  # id_len 1, "b"
        + b"\x00\x00\x00\x00\x00\x00\x00\x01"  # 1
        + b"\xff\xff\xff\xff\xff\xff\xff\xff"  # -1, two's complement
    )
    g = Group(np.array([[1, -1], [2, 3]], dtype=np.int32))
    g.insert("b", 0)
    g.insert("a", 1)
    assert g.blob() == golden
    assert group_blob({"b": [1, -1], "a": [2, 3]}, 2) == golden  # the oracle agrees too


def test_insert_then_delete_restores_state() -> None:
    # T5 (§5.3): insert one record, delete it: all four fields equal the state before.
    g, live, vecs = filled(extra=1)
    before = observed(g)
    g.insert("extra", N_ROWS)
    assert g.delete("extra", N_ROWS) is Outcome.DELETED
    assert observed(g) == before
    assert field_diffs(g, members_of(live, vecs), D) == []


def test_insert_then_delete_restores_empty_group() -> None:
    # T5 from empty: the very first insert, then its delete, gives back the §5.2 initial state.
    g = Group(quantised_rows(1))
    g.insert("doc0", 0)
    g.delete("doc0", 0)
    assert observed(g) == expected({}, D)


def test_delete_absent_is_idempotent() -> None:
    # T6 (§5.4): a second delete of the same ID returns AlreadyAbsent and changes nothing.
    g, live, vecs = filled()
    assert g.delete("doc7", 7) is Outcome.DELETED
    del live["doc7"]
    assert field_diffs(g, members_of(live, vecs), D) == []
    after_first = observed(g)

    assert g.delete("doc7", 7) is Outcome.ALREADY_ABSENT
    assert observed(g) == after_first


def test_delete_never_inserted_is_already_absent() -> None:
    # §5.4: absent is absent, whether deleted before or never inserted.
    g, _, _ = filled(extra=1)
    before = observed(g)
    assert g.delete("ghost", N_ROWS) is Outcome.ALREADY_ABSENT
    assert observed(g) == before


def test_duplicate_live_id_rejected() -> None:
    # T7 (§3.2 rule 3): a second insert of a live ID is rejected and changes nothing.
    g, _, _ = filled()
    before = observed(g)
    with pytest.raises(DuplicateRecord):
        g.insert("doc3", 3)
    assert observed(g) == before


def test_reinsert_after_delete_is_allowed() -> None:
    # §3.2: an ID may be inserted again after its record has been deleted.
    g, live, vecs = filled()
    g.delete("doc3", 3)
    g.insert("doc3", 3)
    assert field_diffs(g, members_of(live, vecs), D) == []


def test_delete_with_wrong_vector_is_refused() -> None:
    # The presented vector must be the member's own; nothing changes when it isn't.
    g, _, _ = filled()
    before = observed(g)
    with pytest.raises(IntegrityViolation):
        g.delete("doc3", 4)
    assert observed(g) == before


def test_survivors_check_after_random_deletes() -> None:
    # T8 (§5.3, §5.5): after random deletes, all four fields equal those of a group holding the
    # survivors only. The survivors are tracked by this test, the expected fields by the oracle.
    g, live, vecs = filled()
    rng = np.random.default_rng(SEED)
    for row in rng.choice(N_ROWS, size=N_ROWS // 3, replace=False):
        rid = f"doc{row}"
        assert g.delete(rid, int(row)) is Outcome.DELETED
        del live[rid]
    assert len(live) == N_ROWS - N_ROWS // 3
    assert field_diffs(g, members_of(live, vecs), D) == []


def test_blob_order_independent() -> None:
    # T9 (§5.5): the same member set inserted in 100 different orders gives the same blob,
    # and that blob is the one the spec layout says.
    vectors = quantised_rows(N_ROWS)
    vecs = vectors.tolist()
    want = group_blob({f"doc{r}": vecs[r] for r in range(N_ROWS)}, D)
    rng = np.random.default_rng(SEED)
    for _ in range(100):
        g = Group(vectors)
        for row in rng.permutation(N_ROWS):
            g.insert(f"doc{row}", int(row))
        assert g.blob() == want


def test_empty_group_persists() -> None:
    # T10 (§5.4): delete every member: S = 0 and n = 0 exactly, and the group still works.
    g, live, vecs = filled()
    for rid, row in list(live.items()):
        g.delete(rid, row)
    assert observed(g) == expected({}, D)
    g.insert("doc0", 0)
    assert field_diffs(g, {"doc0": vecs[0]}, D) == []


def test_blob_members_sorted_by_utf8_bytes() -> None:
    # §3.2: IDs compare by UTF-8 bytes. Read the IDs back out of the blob, in order.
    ids = ["b", "é", "ab", "Z", "a"]
    g = Group(quantised_rows(len(ids)))
    for row, rid in enumerate(ids):
        g.insert(rid, row)
    blob = g.blob()
    pos, seen = 6 + 2 + 2 + 8 + 8 * D + 8, []
    for _ in ids:
        (length,) = struct.unpack(">H", blob[pos : pos + 2])
        seen.append(blob[pos + 2 : pos + 2 + length])
        pos += 2 + length + 8 * D
    assert seen == [b"Z", b"a", b"ab", b"b", b"\xc3\xa9"]
    assert pos == len(blob)  # nothing after the last member


def test_capacity_cap_is_one_million() -> None:
    # §5.6: an insert that would make n > 1,000,000 is rejected. n is set directly so the test
    # doesn't need a million inserts; the limit itself is written here, not imported.
    g = Group(quantised_rows(2))
    g.n = 999_999
    g.insert("doc0", 0)  # n becomes exactly 1,000,000: allowed
    assert g.n == 1_000_000
    with pytest.raises(GroupCapacityExceeded):
        g.insert("doc1", 1)
    assert g.n == 1_000_000
    assert "doc1" not in g.members


def test_errors_never_contain_the_record_id() -> None:
    # §17: no error message may contain a record ID.
    rid = "secret-record-4815"
    g = Group(quantised_rows(2))
    g.insert(rid, 0)
    with pytest.raises(DuplicateRecord) as dup:
        g.insert(rid, 0)
    with pytest.raises(IntegrityViolation) as bad:
        g.delete(rid, 1)
    assert rid not in str(dup.value)
    assert rid not in str(bad.value)


def test_compare_catches_each_field_on_its_own() -> None:
    # §5.5: "A corruption of any one field MUST be caught." Corrupt one field at a time.
    g, _, _ = filled()
    snap = g.snapshot()
    corruptions = {
        "S": dataclasses.replace(snap, S=bytes([snap.S[0] ^ 1]) + snap.S[1:]),
        "n": dataclasses.replace(snap, n=snap.n + 1),
        "members": dataclasses.replace(snap, member_ids=snap.member_ids[1:]),
        "blob": dataclasses.replace(snap, blob_sha256="0" * 64),
    }
    for field, bad in corruptions.items():
        result = compare(snap, bad)
        assert result[field] is False, field
        assert all(ok for f, ok in result.items() if f != field), field


def test_survivors_check_flags_a_corrupted_sum() -> None:
    # The demo's survivors_check must agree with the oracle when the group is right,
    # and must report S when one component of S is off by one.
    g, live, vecs = filled()
    rng = np.random.default_rng(SEED)
    assert survivors_check(g, rng) == {"S": True, "n": True, "members": True, "blob": True}
    assert field_diffs(g, members_of(live, vecs), D) == []
    g.S[5] += 1
    assert survivors_check(g, rng)["S"] is False


def test_survivors_report_matches_survivors_check() -> None:
    # The shell's verify table uses survivors_report. It must give the same verdict and use the
    # random generator exactly as survivors_check does, or the rehearsed numbers would change.
    g, live, _ = filled()
    for rid in ["doc3", "doc7", "doc11"]:
        g.delete(rid, live.pop(rid))
    one, two = np.random.default_rng(SEED), np.random.default_rng(SEED)
    snap_live, snap_rebuilt, result = survivors_report(g, one)
    assert result == survivors_check(g, two)
    assert one.integers(1 << 62) == two.integers(1 << 62)  # both generators at the same point
    assert snap_live == g.snapshot()
    assert snap_rebuilt.member_ids == snap_live.member_ids
