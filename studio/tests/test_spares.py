"""The live demos never run out of passages (H2 of the Studio audit).

Oracle E: the engine's own answers (acknowledged inserts found in its log, a flush's placement). A
work directory whose spare passages are all used must still crash, fill and kill: Studio loads more.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from sever_studio.actions import Studio
from sever_studio.corpus import load

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def studio(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Studio]:
    work = ROOT / "studio/work" / f"test-spares-{tmp_path_factory.getbasetemp().name}"
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    s.backend.index.loaded = len(s.corpus.ids)  # every spare used, as in the audited copies
    s.backend.save()
    yield s
    s.backend.close()
    s.backend.wipe()


def test_studio_more_synthetic_passages_keep_the_first_ones() -> None:
    small, big = load(ROOT, "synthetic", 2_240), load(ROOT, "synthetic", 6_000)
    assert len(big.ids) >= 6_000
    assert big.ids[: len(small.ids)] == small.ids
    assert (big.vectors[: len(small.ids)] == small.vectors).all()


def test_studio_crash_demo_works_after_the_spares_ran_out(studio: Studio) -> None:
    c = studio.crash(40)
    assert c.killed
    assert c.acked > 0
    assert c.missing == 0
    assert studio.checklist.ticked("crash")
    assert studio.spares_left() > 0


def test_studio_a_reopened_studio_has_spares_again(studio: Studio) -> None:
    again = Studio(ROOT, "synthetic", studio.work, dev=True, rows=120)
    assert len(again.corpus.ids) - studio.backend.index.loaded >= 1_000


def test_studio_reset_gives_a_fresh_database_that_agrees_with_its_log(studio: Studio) -> None:
    studio.reset()
    b = studio.backend
    assert b.index.loaded == 120
    assert len((studio.work / "prepare-events.jsonl").read_text("utf-8").splitlines()) == 120
    assert b.mismatches() == []
    assert studio.spares_left() >= 2_000
