"""A deletion killed part-way: the verdict says only what the kills showed (H3, M5 of the audit).

Oracle A: §12.5 (a multi-record deletion is all or nothing) and §15.4 (crash table). A run that
finished before the kill shows nothing about a crash; only killed runs count, and "all deleted"
needs a kill after the commit point. Oracle E: each record's fate after recovery is the engine's
log, record by record.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from sever_studio.actions import Studio
from sever_studio.wow import kill_verdict

ROOT = Path(__file__).resolve().parents[2]


def test_studio_kill_verdict_needs_a_kill() -> None:
    ok, text = kill_verdict(["finished first"] * 5)
    assert ok is None
    assert "no kill" in text


def test_studio_kill_verdict_says_when_only_before_commit_kills_landed() -> None:
    ok, text = kill_verdict(["none", "none", "finished first"])
    assert ok is True
    assert "before the commit point" in text
    assert "2 kills" in text


def test_studio_kill_verdict_with_both_sides_of_the_commit_point() -> None:
    ok, text = kill_verdict(["none", "all", "none"])
    assert ok is True
    assert "after it all" in text


def test_studio_kill_verdict_a_half_deletion_is_red() -> None:
    ok, _ = kill_verdict(["none", "partial"])
    assert ok is False


@pytest.fixture(scope="module")
def studio(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Studio]:
    work = ROOT / "studio/work" / f"test-kill-{tmp_path_factory.getbasetemp().name}"
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    yield s
    s.backend.close()
    s.backend.wipe()


def test_studio_a_kill_at_once_deletes_none_record_by_record(studio: Studio) -> None:
    account, ids = studio.crash_test_person()
    studio.numbers["delete_user_ms_per_record"] = 1.0  # skip the timing run: kill at once
    r = studio.crash_delete(account, 0.0)
    assert r.outcome == "none"
    live = studio.backend.replay().groups
    lsns = [studio.backend.index.records[i].lsn for i in ids]
    assert all(n in live for n in lsns)
    assert studio.backend.mismatches() == []
