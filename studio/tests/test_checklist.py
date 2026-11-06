"""A checklist row is ticked only by an engine check run live (DB-109).

Oracle A: Build §2.5 (a result is evidence only from a run, with its commit) and DB-109. A recording
is shown as a recording (◐), never ticked; a row that only shows something (a hover, the stated
limits, the evidence files) is not a check at all.
"""

from collections.abc import Iterator

import pytest
from conftest import CFG, WORK

from sever_studio.actions import Studio
from sever_studio.checklist import ROWS


@pytest.fixture(scope="module")
def studio(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Studio]:
    work = WORK / f"test-checklist-{tmp_path_factory.getbasetemp().name}"
    s = Studio(CFG, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    yield s
    s.backend.close()
    s.backend.wipe()


def test_studio_checklist_shown_rows_are_not_checks() -> None:
    shown = {r.key for r in ROWS if not r.check}
    assert shown == {"hover", "limits", "evidence"}
    assert len(ROWS) == 27


def test_studio_opening_receipts_or_evidence_ticks_nothing(studio: Studio) -> None:
    before = studio.checklist.passed()
    studio.limits()
    studio.evidence()
    studio.hover(next(iter(studio.backend.index.records)))
    assert studio.checklist.passed() == before


def test_studio_a_live_engine_check_ticks(studio: Studio) -> None:
    before = studio.checklist.passed()
    studio.clusters()
    assert studio.checklist.ticked("clusters")
    assert studio.checklist.passed() == before + 1
