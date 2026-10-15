"""The model's group state (§5.3–5.5, §9.3–9.4, INV-3) against the spec and Part 1's frozen
core-form golden blob."""

import json
import random
from pathlib import Path

import pytest

from sever_refmodel_certs import spec
from sever_refmodel_certs.group import BlobError, CertGroup, parse_full_blob
from sever_refmodel_certs.ristretto import L, decode, encode

ROOT = Path(__file__).resolve().parents[3]
CORE = json.loads((ROOT / "golden/p1_core_blob.json").read_text(encoding="utf-8"))


def _core_group() -> CertGroup:
    g = CertGroup(CORE["d"])
    for k, (rid, x) in enumerate(CORE["members"].items()):
        g.insert(rid, tuple(x), 1000 + k)
    return g


def test_p3_model_full_blob_is_the_core_blob_with_the_commitment_region() -> None:
    # §5.5, DB-47: the full form is the core form with magic SEVERG and C_S ‖ r_agg after S.
    g = _core_group()
    full = g.full_blob()
    d = CORE["d"]
    region = 18 + 8 * d
    assert full[:6] == b"SEVERG"
    assert full[region : region + 32] == encode(g.c_s)
    assert int.from_bytes(full[region + 32 : region + 64], "little") == g.r_agg
    as_core = b"SEVERC" + full[6:region] + full[region + 64 :]
    assert as_core.hex() == CORE["blob_hex"]


def test_p3_model_insert_then_delete_restores_every_field() -> None:
    # §5.3: after the deletion every field equals its value had t never been inserted.
    g = _core_group()
    before = (list(g.s), g.n, g.r_agg, encode(g.c_s), g.full_blob())
    g.insert("doc-z", tuple(range(-4, 4)), 777)
    rem = g.delete("doc-z")
    assert rem is not None
    assert not rem.group_emptied
    assert (list(g.s), g.n, g.r_agg, encode(g.c_s), g.full_blob()) == before
    assert (decode(rem.c_s_post) + decode(rem.c_t)).equals(decode(rem.c_s_pre))
    assert g.delete("doc-z") is None  # §5.4: absent → AlreadyAbsent, nothing changes
    assert g.full_blob() == before[4]


def test_p3_model_emptying_a_group_gives_the_identity() -> None:
    # §5.4: n = 0 → S = 0, r_agg = 0, C_S = identity; tag 11 is 1 only for the last member.
    g = _core_group()
    flags = [g.delete(rid).group_emptied for rid in list(g.members)]  # type: ignore[union-attr]
    assert flags == [False, False, True]
    assert (g.s, g.n, g.r_agg, encode(g.c_s)) == ([0] * CORE["d"], 0, 0, bytes(32))


def test_p3_model_c_s_always_commits_to_s_and_r_agg() -> None:
    # INV-3: C_S = r_agg·H + Σ scalar(S_i)·G_i after any stream of inserts and deletes.
    rng = random.Random(42)
    g = CertGroup(8)
    live: list[str] = []
    for step in range(40):
        if live and rng.random() < 0.4:
            g.delete(live.pop(rng.randrange(len(live))))
        else:
            rid = f"r{step}"
            g.insert(rid, tuple(rng.randint(-(2**24), 2**24) for _ in range(8)), rng.randrange(L))
            live.append(rid)
        assert g.c_s.equals(spec.commit(g.s, g.r_agg))


def test_p3_model_blob_is_independent_of_insertion_order() -> None:
    # §5.5: the same records in any order give the same canonical blob.
    rows = list(CORE["members"].items())
    blobs = set()
    for order in ([0, 1, 2], [2, 0, 1], [1, 2, 0]):
        g = CertGroup(CORE["d"])
        for k in order:
            g.insert(rows[k][0], tuple(rows[k][1]), 1000 + k)
        blobs.add(g.full_blob())
    assert len(blobs) == 1


def test_p3_model_full_blob_parser_rejects_what_section_5_5_rejects() -> None:
    g = _core_group()
    blob = g.full_blob()
    n, s, c_s, r_agg, members = parse_full_blob(blob)
    assert int.from_bytes(r_agg, "little") == g.r_agg
    assert (n, s, c_s, members) == (
        3,
        g.s,
        encode(g.c_s),
        {k: tuple(v[0]) for k, v in g.members.items()},
    )
    d = CORE["d"]
    count_at = 18 + 8 * d + 64
    bad = {
        "core magic": b"SEVERC" + blob[6:],
        "member_count": blob[:count_at] + (4).to_bytes(8, "big") + blob[count_at + 8 :],
        "trailing": blob + b"\x00",
        "r_agg ≥ ℓ": blob[: 18 + 8 * d + 32] + L.to_bytes(32, "little") + blob[18 + 8 * d + 64 :],
    }
    for name, b in bad.items():
        with pytest.raises(BlobError):
            parse_full_blob(b)
        assert name
    # Unsorted IDs: swap the first two member records.
    first = count_at + 8
    ln1 = int.from_bytes(blob[first : first + 2], "big")
    rec1 = blob[first : first + 2 + ln1 + 8 * d]
    rest = blob[first + len(rec1) :]
    ln2 = int.from_bytes(rest[:2], "big")
    rec2 = rest[: 2 + ln2 + 8 * d]
    with pytest.raises(BlobError):
        parse_full_blob(blob[:first] + rec2 + rec1 + rest[len(rec2) :])
