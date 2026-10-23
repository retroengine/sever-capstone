"""A checklist row is ticked only by an engine check or a part program run live (DB-109).

Oracle A: Build §2.5 (a result is evidence only from a run, with its commit) and DB-109. A recording
is shown as a recording (◐), never ticked; a row that only shows something (a hover, the stated
limits, the evidence files) is not a check at all.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from sever_studio import proofs
from sever_studio.actions import Studio
from sever_studio.checklist import ROWS

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def studio(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Studio]:
    work = ROOT / "studio/work" / f"test-checklist-{tmp_path_factory.getbasetemp().name}"
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    yield s
    s.backend.close()
    s.backend.wipe()


def test_studio_checklist_shown_rows_are_not_checks() -> None:
    shown = {r.key for r in ROWS if not r.check}
    assert shown == {"hover", "limits", "evidence"}
    assert len(ROWS) == 37


def test_studio_a_recorded_run_is_shown_never_ticked(studio: Studio) -> None:
    if proofs.recorded(ROOT, "idea") is None:
        pytest.skip("no recorded nq-10k run in artefacts/demo/")
    before = studio.checklist.passed()
    studio.proof("idea", None)
    for key in ("exact", "ghost"):
        v = studio.checklist.verdicts[key]
        assert v.source == "recorded"
        assert not studio.checklist.ticked(key)
    assert studio.checklist.passed() == before


def test_studio_a_recording_names_its_file_date_and_unknown_commit() -> None:
    p = proofs.load_recorded(ROOT, "durable")
    if p is None:
        pytest.skip("no recorded nq-10k run in artefacts/demo/")
    assert "artefacts/demo/durable-nq-10k-seed42.json" in p.source
    assert "written 20" in p.source
    assert "commit unknown" in p.source


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


def test_studio_the_race_model_ticks_nothing(studio: Studio) -> None:
    # C3: the race is Studio's numpy model of §4–5; only the engine's own proof may tick its row
    before = studio.checklist.verdicts.get("race")
    studio.race(200)
    assert studio.checklist.verdicts.get("race") is before


def test_studio_part_1_run_live_ticks_the_race_row(studio: Studio) -> None:
    p = studio.proof("idea", "synthetic")
    assert p is not None
    assert p.ok, p.checks
    v = studio.checklist.verdicts["race"]
    assert v.source == "live"
    assert studio.checklist.ticked("race")
    assert "sever-demo idea" in v.detail
