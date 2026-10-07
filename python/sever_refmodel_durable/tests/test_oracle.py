"""Tests of the durable oracle (Build §5.5): the digest, the stream and the verdict."""

import json
from pathlib import Path

import numpy as np

from sever_partition import artefact
from sever_refmodel_core import model as m
from sever_refmodel_durable import oracle as o

ART = Path("golden/p1_partition_small.svp")


def fresh() -> m.RefIndex:
    return m.RefIndex(artefact.decode(ART.read_bytes()), spawn_target=8)


def test_p2_oracle_digest_tracks_every_change() -> None:
    rows = o.fixture_rows()
    idx = fresh()
    seen = {o.state_digest(idx)}
    for i in range(30):
        idx.insert(f"r{i}", rows[i * 7 % 240])
        d = o.state_digest(idx)
        assert d not in seen, "every insert changes the state"
        seen.add(d)
    # Equal states give equal digests, whatever the history.
    a, b = fresh(), fresh()
    a.insert("x", rows[0])
    a.insert("y", rows[1])
    b.insert("y", rows[1])
    b.insert("x", rows[0])
    assert o.state_digest(a) == o.state_digest(b)
    a.delete("x")
    b.delete("x")
    assert o.state_digest(a) == o.state_digest(b)


def test_p2_oracle_holding_records_are_in_the_digest() -> None:
    rows = o.fixture_rows()
    a, b = fresh(), fresh()
    a.insert("h1", rows[200])
    b.insert("h2", rows[200])
    assert a.holding, "out-of-distribution rows land in the holding area"
    assert b.holding
    assert o.state_digest(a) != o.state_digest(b)


def test_p2_oracle_stream_shape() -> None:
    ids = [f"r{i}" for i in range(10)]
    ops = o.crash_stream(ids, list(range(10)), [[["r0", "r1"]], [["r2"]]], total=25)
    kinds = [k for k, _, _ in ops]
    assert kinds[:10] == ["i"] * 10
    assert kinds[10:12] == ["d", "d"]
    assert kinds[12:19] == ["x"] * 7, "every remaining record deleted singly"
    assert kinds[19:] == ["i"] * 6, "then re-inserts up to the total"
    assert len(ops) == 25
    singles = [a for k, a, _ in ops if k == "x"]
    assert singles == sorted(singles, key=m.id_bytes)


def test_p2_oracle_small_golden_is_current(tmp_path: Path) -> None:
    out = tmp_path / "small.jsonl"
    o.write_small(out)
    golden = Path("golden/p2_oracle_small.jsonl")
    assert golden.read_bytes() == out.read_bytes(), "regenerate with `oracle small` (and say why)"


def _results(tmp_path: Path, lines: list[dict[str, object]]) -> Path:
    p = tmp_path / "r.jsonl"
    p.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return p


def test_p2_oracle_check_counts_each_failure(tmp_path: Path) -> None:
    golden = Path("golden/p2_oracle_small.jsonl")
    lines = [json.loads(x) for x in golden.read_text(encoding="utf-8").splitlines()]
    s = [lines[0]["s0"], *(x["s"] for x in lines[1:])]
    i_del = next(i for i, x in enumerate(lines[1:]) if x["t"] == "d")

    def crash(acked: int, state: str | None, **kw: object) -> dict[str, object]:
        return {"t": "crash", "kind": "step", "op": acked, "acked": acked, "state": state, **kw}

    good = [crash(5, s[5]), crash(5, s[6]), crash(i_del, s[i_del + 1], retry="ok")]
    v = o.check(golden, _results(tmp_path, good))
    assert v.crash_points == 3
    assert v.failures() == 0
    bad = [
        crash(5, s[4]),  # lost an acknowledged operation
        crash(i_del, "00" * 32),  # a partial delete_user
        crash(7, None),  # refused to start
        crash(7, s[7], retry="bad"),
        crash(7, s[7], double=s[8]),
    ]
    v = o.check(golden, _results(tmp_path, bad))
    assert (v.lost_acknowledged, v.partial_delete_user, v.startup_refusals) == (1, 1, 1)
    assert (v.bad_retries, v.double_crash_mismatch, v.not_oracle_state) == (1, 1, 2)


def test_p2_oracle_small_stream_is_valid_for_the_model() -> None:
    idx = fresh()
    rows = o.fixture_rows()
    for op in o.small_stream():
        o.apply(idx, op, rows)
    idx.check_invariants()
    assert len(o.small_stream()) == 400
    kinds = {k for k, _, _ in o.small_stream()}
    assert kinds == {"i", "d", "x"}, "the stream has inserts, delete_user and single deletes"
    assert np.isfinite(rows).all()
