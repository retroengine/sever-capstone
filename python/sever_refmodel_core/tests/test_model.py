"""Tests for the Part 1 reference model (spec §3–§8), on the small fixture (Build §2.7): the
committed golden artefact (d = 16, 4 frozen groups) and spawn target 8 (gap G-10)."""

import contextlib
import itertools
import json
import struct
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sever_partition import artefact
from sever_refmodel_core import model as m
from sever_testkit import synthetic

ROOT = Path(__file__).resolve().parents[3]
ART = artefact.decode((ROOT / "golden/p1_partition_small.svp").read_bytes())
D = 16
REF = synthetic.clustered(600, D, 4, seed=42)  # the artefact's own reference rows
LIVE = synthetic.clustered(400, D, 3, seed=7, shift=3.0)  # far from the reference: OOD


def fresh(spawn_target: int = 8, spawning: bool = True) -> m.RefIndex:
    return m.RefIndex(ART, spawning_enabled=spawning, spawn_target=spawn_target)


def survivors_snapshot(idx: m.RefIndex, gid: str) -> m.GroupSnapshot:
    """The group rebuilt from its surviving members alone (Build §4.7 L6, the survivors check)."""
    g = idx.groups[gid]
    rebuilt = m.Group(gid, g.kind, g.centroid, D)
    for rid in sorted(g.members, key=m.id_bytes):
        rebuilt.add(rid, g.members[rid])
    return m.snapshot(rebuilt)


# --- §3.2 record IDs -----------------------------------------------------------------------------


@pytest.mark.spec("SR-3.2-1", "SR-3.2-2")
@pytest.mark.parametrize(
    ("rid", "ok"),
    [
        ("doc0", True),
        ("nq-1234", True),
        ("3a", True),
        ("٣", True),
        ("1", False),
        ("007", False),
        ("-3", False),
        ("+3", False),
        ("", False),
        ("a" * 256, True),
        ("a" * 257, False),
        ("é" * 128, True),
        ("é" * 129, False),
    ],
)
def test_p1_model_record_id_rules(rid: str, ok: bool) -> None:
    if ok:
        m.check_record_id(rid)
    else:
        with pytest.raises(m.InvalidRecordIdError):
            m.check_record_id(rid)


@pytest.mark.spec("SR-3.2-3", "SR-3.2-4")
def test_p1_model_duplicate_live_id_and_reinsert_after_delete() -> None:
    idx = fresh()
    idx.insert("doc0", REF[0])
    with pytest.raises(m.DuplicateRecordError) as same:
        idx.insert("doc0", REF[0])
    assert same.value.same_commitment
    with pytest.raises(m.DuplicateRecordError) as other:
        idx.insert("doc0", REF[1])
    assert not other.value.same_commitment
    assert idx.delete("doc0") != m.AlreadyAbsent()
    idx.insert("doc0", REF[1])  # §3.2: may be inserted again after deletion
    idx.check_invariants()


# --- §5 exact deletion ---------------------------------------------------------------------------


@pytest.mark.spec("SR-5.3-1", "SR-5.4-1", "SR-5.5-3")
def test_p1_model_delete_restores_survivors_state() -> None:
    idx = fresh(spawning=False)
    for i in range(60):
        idx.insert(f"doc{i}", REF[i])
    before = {gid: m.snapshot(g) for gid, g in idx.groups.items()}
    victim = "doc17"
    gid = idx.where[victim]
    assert idx.delete(victim) == m.Deleted(gid)
    m.assert_state_equivalent(m.snapshot(idx.groups[gid]), survivors_snapshot(idx, gid))
    for other, snap in before.items():
        if other != gid:
            m.assert_state_equivalent(m.snapshot(idx.groups[other]), snap)  # untouched
    assert victim not in idx.groups[gid].members  # physical excision, no marker
    assert idx.big_n == 59


@pytest.mark.spec("SR-5.4-2")
def test_p1_model_delete_is_idempotent() -> None:
    idx = fresh()
    idx.insert("doc0", REF[0])
    idx.delete("doc0")
    state = {gid: m.snapshot(g) for gid, g in idx.groups.items()}
    assert idx.delete("doc0") == m.AlreadyAbsent()
    assert idx.delete("never-there") == m.AlreadyAbsent()
    assert {gid: m.snapshot(g) for gid, g in idx.groups.items()} == state


@pytest.mark.spec("SR-5.4-3")
def test_p1_model_empty_group_returns_to_initial_state_and_stays() -> None:
    idx = fresh(spawning=False)
    idx.insert("doc0", REF[0])
    gid = idx.where["doc0"]
    idx.delete("doc0")
    g = idx.groups[gid]
    assert (g.n, g.s) == (0, [0] * D)
    assert gid in idx.groups  # empty groups stay forever


@pytest.mark.spec("SR-5.5-1", "SR-5.5-2")
def test_p1_model_blob_layout_and_parser_rejections() -> None:
    members = {"b": (1,) * D, "a": (-2,) * D, "Z": (3,) * D}
    s = [2] * D
    blob = m.core_blob(D, s, members)
    assert blob[:6] == b"SEVERC"
    assert struct.unpack_from(">HHQ", blob, 6) == (1, D, 3)
    assert m.parse_core_blob(blob) == (3, s, members)
    first_id = 18 + 8 * D + 8
    assert blob[first_id : first_id + 3] == b"\x00\x01Z"  # 'Z' < 'a' < 'b' by bytes
    bad = {
        "count": blob[: 18 + 8 * D] + struct.pack(">Q", 2) + blob[18 + 8 * D + 8 :],
        "trailing": blob + b"\0",
        "magic": b"SEVERG" + blob[6:],
    }
    for name, b in bad.items():
        with pytest.raises(m.BlobError):
            m.parse_core_blob(b)
        assert name

    # Unsorted, duplicate and empty IDs, built by hand.
    def raw(ids: list[bytes]) -> bytes:
        out = b"SEVERC" + struct.pack(">HHQ", 1, D, len(ids)) + struct.pack(f">{D}q", *([0] * D))
        out += struct.pack(">Q", len(ids))
        for i in ids:
            out += struct.pack(">H", len(i)) + i + struct.pack(f">{D}q", *([0] * D))
        return out

    for ids in ([b"b", b"a"], [b"a", b"a"], [b""]):
        with pytest.raises(m.BlobError):
            m.parse_core_blob(raw(ids))


@pytest.mark.spec("SR-5.5-3")
@pytest.mark.parametrize("which", ["S", "n", "C_S", "blob", "member IDs"])
def test_p1_model_equivalence_helper_catches_each_field_alone(which: str) -> None:
    """Phase P1 must-fail: corrupting each of the five exactness fields is caught separately."""
    idx = fresh(spawning=False)
    for i in range(10):
        idx.insert(f"doc{i}", REF[i])
    snap = m.snapshot(idx.groups[idx.where["doc0"]])
    bad = {
        "S": m.GroupSnapshot(
            (snap.s[0] ^ 1, *snap.s[1:]), snap.n, snap.c_s, snap.blob, snap.member_ids
        ),
        "n": m.GroupSnapshot(snap.s, snap.n + 1, snap.c_s, snap.blob, snap.member_ids),
        "C_S": m.GroupSnapshot(snap.s, snap.n, b"\0" * 32, snap.blob, snap.member_ids),
        "blob": m.GroupSnapshot(
            snap.s, snap.n, snap.c_s, snap.blob[:-1] + b"\x01", snap.member_ids
        ),
        "member IDs": m.GroupSnapshot(snap.s, snap.n, snap.c_s, snap.blob, (*snap.member_ids, "x")),
    }[which]
    with pytest.raises(m.NotEquivalentError) as e:
        m.assert_state_equivalent(snap, bad)
    assert e.value.field == which


@pytest.mark.spec("SR-5.5-4")
def test_p1_model_insertion_order_independence() -> None:
    """P1-T3 in miniature: every permutation of a member set gives identical blobs."""
    ids = [f"doc{i}" for i in range(5)]
    blobs = set()
    for perm in itertools.permutations(range(5)):
        idx = fresh(spawning=False)
        for i in perm:
            idx.insert(ids[i], REF[i])
        blobs.add(tuple(idx.blob(gid) for gid in sorted(idx.groups)))
    assert len(blobs) == 1


@pytest.mark.spec("SR-5.6-1")
def test_p1_model_room_test_boundaries() -> None:
    """Build §2.2 boundary values: 2kn = 3N − 1, 3N, 3N + 1 (k = 3, N = 10: n·6 vs 30)."""
    assert m.has_room(n=4, k=3, big_n=10)  # 24 < 30
    assert not m.has_room(n=5, k=3, big_n=10)  # 30 = 30
    assert m.has_room(n=1, k=2, big_n=1) is False  # 4 = 3 + 1 > 3
    assert m.has_room(n=1, k=1, big_n=1)  # 2 = 3 − 1 < 3


# --- §7 routing, holding area, flush -------------------------------------------------------------


@pytest.mark.spec("SR-7.3-1", "SR-7.4-1", "SR-7.4-2", "SR-7.5-1", "SR-7.5-2")
def test_p1_model_holding_flushes_exactly_at_target() -> None:
    idx = fresh(spawn_target=8)
    for i in range(7):
        assert idx.insert(f"live{i}", LIVE[i]) == ("holding", m.HOLDING)
    assert idx.stats() == {"frozen": 4, "spawned": 0, "N": 0, "k": 4, "holding": 7}
    placement = idx.insert("live7", LIVE[7])
    gid = m.spawn_id([f"live{i}" for i in range(8)])
    assert placement == ("spawned", gid)
    g = idx.groups[gid]
    assert g.n == 8
    assert idx.stats() == {"frozen": 4, "spawned": 1, "N": 8, "k": 5, "holding": 0}
    expected = np.array([(float(v) / 2**24) / 8 for v in g.s])
    assert np.array_equal(g.centroid, expected)  # μ_i = ((f64)S_i / 2^24) / n
    idx.check_invariants()


@pytest.mark.spec("SR-7.3-2")
def test_p1_model_spillover_is_checked_before_holding() -> None:
    """SB-8 in the model: once a spawned group has room, an OOD vector joins it."""
    idx = fresh(spawn_target=8)
    for i in range(8):
        idx.insert(f"live{i}", LIVE[i])
    for i in range(20):  # in-distribution data grows N so the spawned group has room
        idx.insert(f"doc{i}", REF[i])
    gid = next(g for g in idx.groups if g.startswith("spawn-"))
    assert m.has_room(idx.groups[gid].n, idx.k, idx.big_n)
    assert idx.insert("live8", LIVE[8]) == ("spawned", gid)


@pytest.mark.spec("SR-7.4-3")
def test_p1_model_holding_record_is_deletable_and_never_searched() -> None:
    idx = fresh(spawn_target=8)
    idx.insert("live0", LIVE[0])
    hits = idx.search(LIVE[0], 10)
    assert "live0" not in [h for h, _ in hits]
    assert idx.delete("live0") == m.Deleted(m.HOLDING)
    assert idx.stats()["holding"] == 0


@pytest.mark.spec("SR-7.7-1", "SR-7.7-2", "INV-16")
def test_p1_model_routing_is_pure_and_ignores_creation_order() -> None:
    """§7.7 tests 1–2: same (x̃, state) → same destination; two states that differ only in the
    order their spawned groups were created route identically."""
    cohort_a, cohort_b = range(0, 8), range(8, 16)
    a, b = fresh(), fresh()
    for i in itertools.chain(cohort_a, cohort_b):
        a.insert(f"live{i}", LIVE[i])
    for i in itertools.chain(cohort_b, cohort_a):
        b.insert(f"live{i}", LIVE[i])
    assert sorted(a.groups) == sorted(b.groups)  # same spawned groups, created in opposite order
    for i in range(16, 60):
        xq = m.quantise(LIVE[i])
        assert a.route(xq) == a.route(xq)
        assert a.route(xq) == b.route(xq)


@pytest.mark.spec("SR-7.7-3")
def test_p1_model_same_input_order_gives_identical_index() -> None:
    def run() -> list[bytes]:
        idx = fresh(spawn_target=8)
        for i in range(30):
            idx.insert(f"live{i}", LIVE[i])
            idx.insert(f"doc{i}", REF[i])
        return [idx.blob(g) for g in sorted(idx.groups)]

    assert run() == run()


# --- §8 search -----------------------------------------------------------------------------------


@pytest.mark.spec("SR-8.1-2")
@pytest.mark.parametrize(("k", "p"), [(4, 1), (5, 2), (6, 2), (7, 2), (8, 2), (128, 32), (263, 66)])
def test_p1_model_probe_count(k: int, p: int) -> None:
    assert m.probe_count(k) == p


@pytest.mark.spec("SR-8.2-1")
def test_p1_model_kernel_matches_explicit_lanes() -> None:
    rng = np.random.Generator(np.random.PCG64(3))
    q = rng.standard_normal(D).astype(np.float32)
    xs = rng.standard_normal((5, D)).astype(np.float32)
    got = m.kernel_scores(q, xs)
    for r in range(5):
        lanes = [np.float32(0.0)] * 8
        for i in range(D):
            t = np.float32(q[i] - xs[r, i])
            lanes[i % 8] = np.float32(lanes[i % 8] + np.float32(t * t))
        want = np.float32(
            np.float32(np.float32(lanes[0] + lanes[1]) + np.float32(lanes[2] + lanes[3]))
            + np.float32(np.float32(lanes[4] + lanes[5]) + np.float32(lanes[6] + lanes[7]))
        )
        assert got[r] == want  # bit-identical


@pytest.mark.spec("SR-8.1-4", "INV-9")
def test_p1_model_deleted_records_never_returned() -> None:
    idx = fresh(spawning=False)
    for i in range(100):
        idx.insert(f"doc{i}", REF[i])
    target = idx.search(REF[5], 1)[0][0]
    assert target == "doc5"
    idx.delete("doc5")
    for q in REF[:50]:
        assert "doc5" not in [h for h, _ in idx.search(q, 20)]


# --- golden vectors 7 and 8 (Appendix B), checked again by the Rust crates -----------------------


@pytest.mark.spec("SR-7.5-1")
def test_p1_model_golden_spawn_id() -> None:
    g = json.loads((ROOT / "golden/p1_spawn_id.json").read_text(encoding="utf-8"))
    assert m.spawn_id(g["cohort"]) == g["spawn_id"]


@pytest.mark.spec("SR-5.5-1")
def test_p1_model_golden_core_blob() -> None:
    g = json.loads((ROOT / "golden/p1_core_blob.json").read_text(encoding="utf-8"))
    members = {k: tuple(v) for k, v in g["members"].items()}
    s = [sum(c) for c in zip(*members.values(), strict=True)]
    assert m.core_blob(g["d"], s, members).hex() == g["blob_hex"]


# --- properties (L2) -----------------------------------------------------------------------------


ops = st.lists(
    st.tuples(st.sampled_from(["ins_ref", "ins_live", "del"]), st.integers(0, 39)), max_size=120
)


@settings(max_examples=60, deadline=None)
@given(ops)
@pytest.mark.spec("SR-5.3-1", "SR-5.5-3", "INV-6", "INV-8")
def test_p1_model_prop_survivors_check_after_any_sequence(seq: list[tuple[str, int]]) -> None:
    """P1-T1: after any sequence, every group equals the group built from its survivors alone."""
    idx = fresh(spawn_target=8)
    for op, i in seq:
        if op == "del":
            idx.delete(f"r{i}")
            idx.delete(f"l{i}")
            continue
        rid, x = (f"r{i}", REF[i]) if op == "ins_ref" else (f"l{i}", LIVE[i])
        with contextlib.suppress(m.DuplicateRecordError):
            idx.insert(rid, x)
    idx.check_invariants()
    for gid in idx.groups:
        m.assert_state_equivalent(m.snapshot(idx.groups[gid]), survivors_snapshot(idx, gid))
