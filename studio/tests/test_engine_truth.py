"""Each record's group is the engine's: its own log, replayed, decides (DB-109).

Oracle B: the engine's log export (DB-86). The replay here is written again from the spec, not
taken from Studio: an insert leaf is ``0x01 ‖ collection_id 16 ‖ scrambled_id 64 ‖ …`` and its
index is the insert's ``database_lsn`` (§10.2); a deletion leaf is ``0x02 ‖ certificate`` whose
tag 9 is the scrambled ID (§11.1); a flush moves every record then in the holding area (§7.4).
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sever_studio.actions import Studio
from sever_studio.backend import HOLDING

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def studio(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Studio]:
    work = ROOT / "studio/work" / f"test-truth-{tmp_path_factory.getbasetemp().name}"
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    s.fill_bucket("flush")
    yield s
    s.backend.close()
    s.backend.wipe()


def tag(cert: bytes, want: int) -> bytes:
    at = 0
    while at < len(cert):
        t, n = cert[at], int.from_bytes(cert[at + 1 : at + 5], "big")
        if t == want:
            return cert[at + 5 : at + 5 + n]
        at += 5 + n
    raise ValueError(want)


def replay_by_hand(log: dict[str, Any]) -> dict[int, str]:
    """Insert leaf index -> the group its record is in now; deleted records are absent."""
    group: dict[bytes, str] = {}
    lsn_of: dict[bytes, int] = {}
    holding: list[bytes] = []
    for i, (h, p) in enumerate(zip(log["leaves"], log["placements"], strict=True)):
        leaf = bytes.fromhex(h)
        if leaf[0] == 1:
            sid = leaf[17:81]
            lsn_of[sid] = i
            if p["flush"]:
                for w in holding:
                    group[w] = p["flush"]
                holding = []
            group[sid] = p["group"]
            if p["group"] == HOLDING:
                holding.append(sid)
        else:
            sid = tag(leaf[1:], 9)
            if group.pop(sid) == HOLDING:
                holding.remove(sid)
    return {lsn_of[s]: g for s, g in group.items()}


def test_studio_each_record_is_in_the_group_the_engine_log_says(studio: Studio) -> None:
    b = studio.backend
    studio.delete([next(iter(b.index.records))])
    truth = replay_by_hand(json.loads(b.live.export_log()))
    mine = {rec.lsn: rec.group for rec in b.index.records.values()}
    assert mine == truth
    assert b.mismatches() == []


def test_studio_a_swap_that_keeps_every_count_is_still_caught(studio: Studio) -> None:
    # Red for the old check, which compared counts only: one record of group A and one of group B
    # trade places, so every group's size stays the same.
    b = studio.backend
    recs = b.index.records
    a = next(r for r, v in recs.items() if v.group != HOLDING)
    c = next(r for r, v in recs.items() if v.group not in (HOLDING, recs[a].group))
    ga, gc = recs[a].group, recs[c].group
    recs[a].group, recs[c].group = gc, ga
    try:
        problems = b.mismatches()
        assert any(a in p for p in problems), problems
        assert any(c in p for p in problems), problems
    finally:
        recs[a].group, recs[c].group = ga, gc
    assert b.mismatches() == []
