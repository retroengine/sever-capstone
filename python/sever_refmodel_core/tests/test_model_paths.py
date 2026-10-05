"""The reference model's rejection and integrity paths (spec §4.1, §5.5, §7.5, §8.1, §9.7, §21)."""

import json
from pathlib import Path

import numpy as np
import pytest

from sever_partition import artefact
from sever_refmodel_core import model as m

ROOT = Path(__file__).resolve().parents[3]


def rows(key: str) -> list[np.ndarray]:
    doc = json.loads((ROOT / "golden/p1_fixture_vectors.json").read_text(encoding="utf-8"))
    return [np.frombuffer(bytes.fromhex(h), dtype="<f4").copy() for h in doc[key]]


def fresh() -> m.RefIndex:
    art = artefact.decode((ROOT / "golden/p1_partition_small.svp").read_bytes())
    return m.RefIndex(art, spawn_target=8)


@pytest.mark.spec("SR-4.1-0", "SR-4.1-1", "SR-4.1-3")
def test_p1_model_rejects_bad_vectors_in_order() -> None:
    idx = fresh()
    x = rows("ref")[0]
    with pytest.raises(m.SeverError) as e:
        idx.insert("a", x[:8])
    assert e.value.kind == "WrongDimension"
    nan = x.copy()
    nan[2] = np.nan
    with pytest.raises(m.SeverError) as e:
        idx.insert("a", nan)
    assert e.value.kind == "NonFinite"
    with pytest.raises(m.SeverError) as e:
        idx.insert("a", x * np.float32(1.5))
    assert e.value.kind == "NotNormalised"
    with pytest.raises(m.SeverError):
        idx.search(x[:8], 10)


@pytest.mark.spec("SR-8.1-3")
def test_p1_model_search_on_an_empty_index_is_empty() -> None:
    assert fresh().search(rows("ref")[0], 10) == []
    idx = fresh()
    idx.insert("a", rows("ref")[0])
    assert idx.search(rows("ref")[0], 0) == []


@pytest.mark.spec("SR-9.7-1")
def test_p1_model_scrambled_id_matches_golden() -> None:
    g = json.loads((ROOT / "golden/p1_scramble.json").read_text(encoding="utf-8"))
    key, cid = bytes.fromhex(g["k_scramble_hex"]), bytes.fromhex(g["collection_id_hex"])
    for r in g["rows"]:
        got = m.scrambled_id(key, cid, r["record_id"]).hex()
        assert got == r["scrambled_id"]


@pytest.mark.spec("SR-5.5-2")
def test_p1_model_blob_parser_rejects_version_and_truncation() -> None:
    idx = fresh()
    idx.insert("a", rows("ref")[0])
    gid = next(g for g, grp in idx.groups.items() if grp.n)
    blob = idx.blob(gid)
    with pytest.raises(m.BlobError, match="version"):
        m.parse_core_blob(blob[:7] + b"\x02" + blob[8:])
    with pytest.raises(m.BlobError, match="truncated"):
        m.parse_core_blob(blob[:-3])
    with pytest.raises(m.BlobError):
        m.parse_core_blob(blob[:30])


@pytest.mark.spec("SR-7.5-1")
def test_p1_model_spawn_id_collision_fails_the_flush() -> None:
    idx = fresh()
    live = rows("live")
    ids = [f"live{i}" for i in range(8)]
    for i in range(7):
        idx.insert(ids[i], live[i])
    taken = m.spawn_id(ids)
    idx.groups[taken] = m.Group(taken, "spawned", np.zeros(16), 16)  # an existing group of that ID
    idx.groups[taken].members = {f"x{i}": (0,) * 16 for i in range(10_000)}  # no room
    with pytest.raises(m.SeverError) as e:
        idx.insert(ids[7], live[7])
    assert e.value.kind == "IntegrityViolation"


def test_p1_model_invariant_checks_fire() -> None:
    def built() -> m.RefIndex:
        idx = fresh()
        for i, v in enumerate(rows("ref")[:20]):
            idx.insert(f"doc{i}", v)
        idx.check_invariants()
        return idx

    idx = built()
    g = next(grp for grp in idx.groups.values() if grp.n)
    g.members = {**g.members, "ghost": g.members[next(iter(g.members))]}
    with pytest.raises(m.SeverError, match=r"INV-4|INV-6"):
        idx.check_invariants()
    idx = built()
    g = next(grp for grp in idx.groups.values() if grp.n)
    g.s = [g.s[0] + 1, *g.s[1:]]
    with pytest.raises(m.SeverError, match="INV-6"):
        idx.check_invariants()
    idx = built()
    idx.big_n += 1
    with pytest.raises(m.SeverError, match="INV-8"):
        idx.check_invariants()
    idx = built()
    idx.where.pop(next(iter(idx.where)))
    with pytest.raises(m.SeverError, match="INV-7"):
        idx.check_invariants()
