"""Studio takes its numbers from the engine's own events (DB-107, the inspect build).

Oracle A: §7.5 (a spawned group's centre is ``((f64)S_i / 2^24) / n`` over its founding cohort,
computed once at the flush; the cohort is the one whose IDs hash to the group's name). Oracle B: the
engine's log export (DB-86): the events, replayed by scrambled ID, must put every record where the
log does.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from sever_studio.actions import Studio
from sever_studio.backend import HOLDING, cert_field

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def studio(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Studio]:
    work = ROOT / "studio/work" / f"test-events-{tmp_path_factory.getbasetemp().name}"
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    yield s
    s.backend.close()
    s.backend.wipe()


def q24(x: np.ndarray) -> np.ndarray:
    return np.rint(x.astype(np.float64) * 2.0**24).astype(np.int64)


def test_studio_a_spawned_centre_is_the_engines_and_stays_after_spillover(studio: Studio) -> None:
    b = studio.backend
    out = studio.fill_bucket("flush")
    f = out[-1].flush
    assert f is not None
    assert f.id_matches
    founders = np.stack([b.vector_of(m) for m in f.members])
    want = (q24(founders).sum(axis=0).astype(np.float64) / 2.0**24) / len(f.members)
    mu = studio.centre(f.group)
    assert mu is not None
    assert np.array_equal(mu, want)
    # spillover into it (§7.3) must not move the centre Studio shows (it moved before: H1)
    spilled = 0
    for _ in range(600):
        i = b.index.loaded
        r = b.insert(studio.corpus.ids[i], studio.corpus.vectors[i], studio.corpus.accounts[i])
        b.index.loaded = i + 1
        spilled += r.placement == f.group
        if spilled >= 2:
            break
    assert spilled >= 2
    mu = studio.centre(f.group)
    assert mu is not None
    assert np.array_equal(mu, want)


def test_studio_events_replayed_put_every_record_where_the_log_does(studio: Studio) -> None:
    b = studio.backend
    studio.delete([next(r for r, v in b.index.records.items() if v.group != HOLDING)])
    where: dict[str, str] = {}
    for line in (studio.work / "events.jsonl").read_text("utf-8").splitlines():
        e = json.loads(line)
        for _, sid in e["departures"]:
            where.pop(sid, None)
        for g, sid in e["arrivals"]:
            where[sid] = g
    log = json.loads(b.live.export_log())
    truth: dict[str, str] = {}
    holding: list[str] = []
    for h, p in zip(log["leaves"], log["placements"], strict=True):
        leaf = bytes.fromhex(h)
        if leaf[0] == 1:
            sid = leaf[17:81].hex()
            if p["flush"]:
                for w in holding:
                    truth[w] = p["flush"]
                holding = []
            truth[sid] = p["group"]
            if p["group"] == HOLDING:
                holding.append(sid)
        else:
            truth.pop(cert_field(leaf[1:], 9).hex())
    assert where == truth
