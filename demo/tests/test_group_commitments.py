"""Groups with commitments: the full five-field exactness relation (spec §5.2-5.5, §9.3).

Expected values come from tests/spec_oracle.py, whose C_S is computed by the independent verifier.
The test functions take no fixtures, so test_sabotage.py can call them with a bug switched on.
"""

import struct

import numpy as np
import pytest

from sever_demo.crypto import random_scalars
from sever_demo.errors import Outcome
from sever_demo.group import Group, compare, survivors_check
from sever_verify.ristretto import IDENTITY, add, commitment
from spec_oracle import committed_field_diffs
from synthetic import SEED, D, quantised_rows, record_ids

N_ROWS = 40


def committed_group(n_rows: int = N_ROWS, extra: int = 0):
    """doc0..doc{n_rows-1} inserted, then commitments switched on (the load path)."""
    vectors = quantised_rows(n_rows + extra)
    blinding = random_scalars(n_rows + extra)  # r_t from the OS (§9.4); the test reads them back
    g = Group(vectors, blinding)
    for row, rid in enumerate(record_ids(n_rows)):
        g.insert(rid, row)
    g.start_commitments()
    vecs = vectors.tolist()
    live = {f"doc{r}": r for r in range(n_rows)}
    return g, live, vecs, blinding


def oracle_diffs(g: Group, live: dict[str, int], vecs, blinding) -> list[str]:
    members = {rid: vecs[row] for rid, row in live.items()}
    return committed_field_diffs(g, members, {rid: blinding[row] for rid, row in live.items()}, D)


def test_start_commitments_matches_the_spec() -> None:
    # §5.2: C_S = r_agg·H + Σ S_i·G_i with r_agg = Σ r_t; the blob is §5.5's layout.
    g, live, vecs, blinding = committed_group()
    assert oracle_diffs(g, live, vecs, blinding) == []
    assert g.blob().startswith(b"SEVERG")


def test_committed_insert_then_delete_restores_state() -> None:
    # T5 with commitments (§5.3): all five fields, including C_S and r_agg, come back exactly.
    g, live, vecs, blinding = committed_group(extra=1)
    before = (g.blob(), g.C_S, g.r_agg)
    g.insert("extra", N_ROWS)  # record by record: C_S += C_t
    assert g.delete("extra", N_ROWS) is Outcome.DELETED  # C_S -= C_t
    assert (g.blob(), g.C_S, g.r_agg) == before
    assert oracle_diffs(g, live, vecs, blinding) == []


def test_committed_random_deletes_match_survivors() -> None:
    # T8 with commitments: after random deletes the five fields equal the survivors-only group, and
    # every deletion satisfies the public check C_S_post + C_t = C_S_pre (§9.3).
    g, live, vecs, blinding = committed_group()
    rng = np.random.default_rng(SEED)
    for row in rng.choice(N_ROWS, size=N_ROWS // 3, replace=False):
        rid = f"doc{row}"
        assert g.delete(rid, int(row)) is Outcome.DELETED
        del live[rid]
        t = g.last_transition
        assert t is not None
        assert add(t.c_s_post, t.c_t) == t.c_s_pre
        assert t.c_t == commitment(vecs[row], blinding[row])  # C_t from the verifier's code
    assert oracle_diffs(g, live, vecs, blinding) == []


def test_committed_delete_absent_changes_nothing() -> None:
    # T6 with commitments (§5.4).
    g, _, _, _ = committed_group()
    g.delete("doc3", 3)
    before = (g.blob(), g.C_S, g.r_agg)
    assert g.delete("doc3", 3) is Outcome.ALREADY_ABSENT
    assert (g.blob(), g.C_S, g.r_agg) == before


def test_committed_empty_group_is_identity() -> None:
    # §5.4: when n reaches 0, S = 0, r_agg = 0 and C_S = identity exactly.
    g, live, vecs, blinding = committed_group()
    for rid, row in list(live.items()):
        g.delete(rid, row)
        del live[rid]
    assert g.C_S == IDENTITY
    assert g.r_agg == 0
    assert g.last_transition is not None
    assert g.last_transition.emptied
    assert oracle_diffs(g, live, vecs, blinding) == []


def test_committed_blob_layout_golden() -> None:
    # §5.5 written out by hand for d = 2, members "b" -> (1, -1) with r_t = 5, "a" -> (2, 3) with
    # r_t = 7. The scalars are fixed test inputs, not seeded randomness. C_S is the verifier's.
    vectors = np.array([[1, -1], [2, 3]], dtype=np.int32)
    g = Group(vectors, [5, 7])
    g.insert("b", 0)
    g.insert("a", 1)
    g.start_commitments()
    c_s = commitment([3, 2], 12)
    golden = (
        b"SEVERG"
        + struct.pack(">HHQ", 1, 2, 2)
        + struct.pack(">qq", 3, 2)  # S
        + c_s
        + (12).to_bytes(32, "little")  # r_agg = 5 + 7, scalar little-endian (§0.2)
        + struct.pack(">Q", 2)
        + b"\x00\x01a"
        + struct.pack(">qq", 2, 3)
        + b"\x00\x01b"
        + struct.pack(">qq", 1, -1)
    )
    assert g.blob() == golden


def test_compare_flags_a_corrupted_commitment() -> None:
    # §5.5: corrupting C_S alone must be caught, as its own field.
    g, _, _, _ = committed_group()
    snap = g.snapshot()
    bad = Group(g.vectors, g.blinding)
    bad.__dict__.update(g.__dict__)
    bad.C_S = add(g.C_S, commitment([1] + [0] * (D - 1), 0))
    result = compare(snap, bad.snapshot())
    assert result["C_S"] is False
    assert result["S"]
    assert result["n"]
    assert result["members"]


def test_survivors_check_has_five_fields() -> None:
    g, _, _, _ = committed_group()
    rng = np.random.default_rng(SEED)
    g.delete("doc1", 1)
    assert survivors_check(g, rng) == {
        "S": True,
        "n": True,
        "members": True,
        "blob": True,
        "C_S": True,
    }


def test_uncommitted_group_cannot_start_without_blinding() -> None:
    g = Group(quantised_rows(2))
    with pytest.raises(ValueError, match="no blinding"):
        g.start_commitments()
