"""Edge cases of the backend and the demonstrations, offline on the fixture. Each expected value is
named after the section that fixes it; none is taken from the code under test."""

import hashlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import WORK

from sever_studio import wow
from sever_studio.actions import Studio
from sever_studio.corpus import DataMissingError, fixture_encode, load

ROOT = Path(__file__).resolve().parents[2]


def spawn_id(members: list[str]) -> str:
    """§7.5, written out again."""
    data = b"".join(len(m).to_bytes(2, "big") + m for m in sorted(x.encode() for x in members))
    return "spawn-" + hashlib.sha256(data).hexdigest()[:16]


@pytest.fixture(scope="module")
def template() -> Iterator[Path]:
    """One prepared fixture database; each test gets a copy (the database is closed meanwhile)."""
    work = WORK / "test-edge-template"
    shutil.rmtree(work, ignore_errors=True)
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    s.backend.close()
    yield work
    shutil.rmtree(work, ignore_errors=True)


@pytest.fixture
def studio(request: pytest.FixtureRequest, template: Path) -> Iterator[Studio]:
    work = WORK / f"test-edge-{request.node.name[:40]}"
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(template, work)
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    yield s
    s.backend.close()
    shutil.rmtree(work, ignore_errors=True)


def exact(s: Studio) -> None:
    assert s.backend.mismatches() == []
    assert s.backend.total() == len(s.backend.index.records)


def test_edge_an_empty_bucket_has_nothing_to_search(studio: Studio) -> None:
    studio.delete(list(studio.backend.index.holding))
    assert studio.backend.index.holding == []
    assert studio.unsearchable() == (None, False, False)
    assert "unsearchable" not in studio.checklist.verdicts
    exact(studio)


def test_edge_a_waiting_record_is_deleted_with_a_holding_area_receipt(studio: Studio) -> None:
    rid = studio.add_mine("Waiting Wanda", "far from every group").rid
    assert studio.backend.index.records[rid].group == "holding"
    d = studio.delete([rid])
    assert d.ok
    cert = wow.parse((studio.backend.receipts / f"{d.lsns[0]}.cert").read_bytes())
    assert cert.from_holding  # §11.1 tag 12 = 1
    assert cert.tags[2] == cert.tags[3] == cert.tags[4] == b""  # §11.3 step 7
    v = studio.verify(d.lsns[0])
    assert v.verdict == "ACCEPT"
    step7 = next(st for st in v.steps if st.number == 7)
    assert step7.verdict == "ok"
    exact(studio)


def test_edge_forgetting_waiting_and_grouped_records_together(studio: Studio) -> None:
    b = studio.backend
    account = "Mixed Max"
    studio.add_mine(account, "one far away note")
    studio.add_mine(account, "another far away note")
    grouped = next(r for r, rec in b.index.records.items() if rec.group.startswith("frozen-"))
    near = b.vector_of(grouped)  # a stored record's own vector routes to that record's group
    b.insert("mixed-in-group", near, account, text="close to a group", mine=True)
    groups = {b.index.records[r].group for r in b.accounts()[account]}
    assert "holding" in groups
    assert len(groups) >= 2
    d = studio.forget(account)
    assert d.ok
    assert len(d.lsns) == 3
    assert account not in b.accounts()
    exact(studio)


def test_edge_emptying_a_whole_group(studio: Studio) -> None:
    b = studio.backend
    group = "frozen-0000"
    members = [r for r, rec in b.index.records.items() if rec.group == group]
    assert members
    d = studio.delete(members)
    assert d.ok
    sizes = dict(b.live.group_sizes(b.cid))
    assert sizes[group] == 0
    certs = [wow.parse((b.receipts / f"{n}.cert").read_bytes()) for n in d.lsns]
    emptied = [x for x in certs if x.tags[11] == b"\x01"]
    assert len(emptied) == 1  # §11.1 tag 11: only the deletion that emptied it
    assert studio.verify(emptied[0].database_lsn).verdict == "ACCEPT"
    exact(studio)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("Zoë 🙂 Ünïcødé", "emoji and accents 🙂 ñ ü"),
        ("x" * 300, "a very long name"),
        ("", "no name at all"),
        ("12345", "a name that is a bare number"),
        ("Long Text", "y" * 10_000),
    ],
)
def test_edge_unusual_names_and_texts(studio: Studio, name: str, text: str) -> None:
    a = studio.add_mine(name, text)
    assert 1 <= len(a.rid.encode()) <= 256  # §3.2
    assert not a.rid.lstrip("+-").isdigit()
    assert studio.backend.text_of(a.rid) == text
    assert studio.delete([a.rid]).ok
    exact(studio)


def test_edge_names_that_slug_alike_stay_apart(studio: Studio) -> None:
    one = studio.add_mine("Ada Lovelace", "first")
    two = studio.add_mine("ada  lovelace!", "second")
    assert one.rid != two.rid
    assert one.rid in studio.backend.index.records
    assert two.rid in studio.backend.index.records
    exact(studio)


def test_edge_only_your_own_records_fill_the_bucket(studio: Studio) -> None:
    studio.delete(list(studio.backend.index.holding))
    flush = None
    for k in range(20):
        a = studio.add_mine("Bucket Filler", f"far away thought {k}")
        if a.result.flush is not None:
            flush = a.result.flush
            break
    assert flush is not None
    assert len(flush.members) == studio.corpus.spawn_target  # §7.4
    assert all(studio.backend.index.records[m].mine for m in flush.members)
    assert flush.group == spawn_id(flush.members)  # §7.5
    exact(studio)


def test_edge_a_committed_insert_whose_answer_was_lost(studio: Studio) -> None:
    b, c = studio.backend, studio.corpus
    rid = c.ids[b.index.loaded]
    i = c.position[rid]
    b.live.insert(b.cid, b.request(rid, c.vectors[i], c.accounts[i]))  # committed, never tracked
    assert b.mismatches() != []
    assert b.reconcile([], rid) is True  # the database says it committed
    exact(studio)


@pytest.mark.full
def test_edge_five_crashes_in_a_row(studio: Studio) -> None:
    for _ in range(5):
        c = studio.crash(count=30)
        assert c.killed
        assert c.missing == 0
        exact(studio)


def test_edge_restart_then_carry_on(studio: Studio) -> None:
    studio.add_mine("Before Restart", "one")
    studio.restart()
    studio.add_mine("After Restart", "two")
    studio.fill_bucket(until="one")
    exact(studio)
    assert studio.checklist.verdicts["restart"].ok


def test_edge_missing_data_and_model_say_what_to_do(tmp_path: Path) -> None:
    from sever_studio.encoder import Encoder, EncoderError

    with pytest.raises(DataMissingError, match="missing"):
        load(tmp_path, "nq", 10)
    with pytest.raises(EncoderError, match=r"studio\.sh setup"):
        Encoder(tmp_path)


def test_edge_an_unprepared_work_directory_is_refused_kindly(tmp_path: Path) -> None:
    from sever_studio.ui.app import run

    assert run(ROOT, "synthetic", 120, WORK / "test-not-prepared", True, smoke=True) == 2


def test_edge_the_report_holds_no_secret_and_no_text(studio: Studio) -> None:
    studio.add_mine("Secret Sam", "my private note 9f3c")
    studio.forget("account-1")
    path = studio.report()
    report = path.read_text("utf-8")
    for secret in studio.backend.secrets():
        assert secret not in report
    assert "my private note" not in report
    for rid in list(studio.backend.index.records)[:50]:
        assert studio.backend.text_of(rid) not in report
    json.loads(report)


def test_edge_fixture_encoder_is_unit_length() -> None:
    v = fixture_encode("anything", 16)[0].astype("float64")
    assert abs((v * v).sum() - 1) < 1e-6  # §4.1: the database validates, never normalises
