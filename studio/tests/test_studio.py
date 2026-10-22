"""Studio's own tests, offline on the golden fixture (``d = 16``, spawn size 8), the window drawn
offscreen. They check that each demonstration really shows what its checklist row claims, and that
no screen ever shows a secret. Expected values come from the spec (§ named in each test) or from an
independent computation in the test, never from the code under test.
"""

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sever_studio import evidence, proofs, sabotage
from sever_studio.actions import Studio
from sever_studio.checklist import ROWS

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def studio(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Studio]:
    # The work directory must be on a file system that overwrites in place (§12.9): /tmp is often
    # tmpfs, so it goes under studio/work/.
    work = ROOT / "studio/work" / f"test-{tmp_path_factory.getbasetemp().name}"
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    yield s
    s.backend.close()
    s.backend.wipe()


def spawn_id_by_hand(members: list[str]) -> str:
    """§7.5, written out again: SHA-256 over the IDs ascending by bytes, each u16be(len) ‖ id."""
    data = b""
    for m in sorted(x.encode("utf-8") for x in members):
        data += len(m).to_bytes(2, "big") + m
    return "spawn-" + hashlib.sha256(data).hexdigest()[:16]


def test_studio_index_agrees_with_the_database_after_preparing(studio: Studio) -> None:
    # oracle: the database's own counts (stats, group sizes), §5, §7.6
    assert studio.backend.mismatches() == []
    st = studio.backend.live.stats(studio.backend.cid)
    assert st["N"] + st["holding"] == len(studio.backend.index.records) == 120


def test_studio_your_record_lands_where_its_receipt_says(studio: Studio) -> None:
    a = studio.add_mine("Ada Lovelace", "notes on the analytical engine")
    assert a.result.lsn is not None
    assert studio.backend.index.records[a.rid].group == a.result.placement
    assert studio.backend.index.records[a.rid].mine
    assert studio.backend.mismatches() == []
    for key in ("insert", "freetext", "routing"):
        assert studio.checklist.verdicts[key].ok, key


def test_studio_a_waiting_record_is_stored_but_never_found(studio: Studio) -> None:
    # §7.4: a holding-area record is stored and not searchable
    studio.fill_bucket(until="one")
    rid, found, stored = studio.unsearchable()
    assert rid is not None
    assert stored
    assert not found
    assert studio.checklist.verdicts["unsearchable"].ok


def test_studio_the_flush_moves_exactly_the_spawn_size_into_the_hashed_group(
    studio: Studio,
) -> None:
    before = list(studio.backend.index.holding)
    out = studio.fill_bucket(until="flush")
    flush = out[-1].flush
    assert flush is not None
    # §7.4: exactly the spawn size, all of them the waiting records plus the one that filled it
    assert len(flush.members) == studio.corpus.spawn_target == 8
    assert set(before) <= set(flush.members)
    # §7.5, computed independently
    assert flush.group == spawn_id_by_hand(flush.members)
    assert dict(studio.backend.live.group_sizes(studio.backend.cid))[flush.group] == 8
    assert studio.backend.index.holding == []
    assert studio.checklist.verdicts["flush"].ok


def test_studio_delete_then_again_is_absent_and_the_counts_stay_exact(studio: Studio) -> None:
    rid = next(r for r, rec in studio.backend.index.records.items() if rec.group != "holding")
    total = studio.backend.total()
    d = studio.delete([rid])
    assert d.ok
    assert len(d.lsns) == 1
    assert studio.backend.total() == total - 1
    assert rid not in studio.backend.index.records
    # §5.4: deleting again changes nothing
    assert studio.delete_again(rid)
    assert studio.backend.total() == total - 1


def test_studio_forgetting_an_account_removes_all_of_it(studio: Studio) -> None:
    account = "account-3"
    ids = studio.backend.accounts()[account]
    d = studio.forget(account)
    assert d.ok
    assert len(d.lsns) == len(ids)
    assert account not in studio.backend.accounts()
    assert all(studio.backend.absent(r) for r in ids)


def test_studio_receipt_verifies_and_a_flipped_byte_is_rejected(studio: Studio) -> None:
    lsn = studio.backend.index.receipts[-1]
    v = studio.verify(lsn)
    assert v.code == 0
    assert v.verdict == "ACCEPT"
    # the person's folder holds only the certificate and the anchors (§11.3)
    assert sorted(p.name for p in v.folder.iterdir()) == ["anchors.json", "certificate.bin"]
    t = studio.tamper(lsn)
    assert t.code == 1
    assert t.verdict.startswith("REJECT (step")
    assert t.flipped is not None
    assert t.flipped[1] ^ t.flipped[2] == 1


def test_studio_refusals_are_typed_and_hold_no_record_id(studio: Studio) -> None:
    rows = studio.refusals()
    assert [r[1] for r in rows] == [
        "NotNormalised",
        "WrongDimension",
        "InvalidRecordId",
        "DuplicateRecord",
        "SeededNonceForbidden",
    ]
    assert all(r[2] for r in rows), rows


def test_studio_retried_insert_is_stored_once(studio: Studio) -> None:
    total = studio.backend.total()
    first, again = studio.retry()
    assert first.lsn is not None
    assert again.retried
    assert studio.backend.total() == total + 1


def test_studio_log_has_four_witnesses_and_the_audit_is_clean(studio: Studio) -> None:
    log = studio.log()
    assert log["witnesses"] >= 4  # §10.4
    code, out = studio.audit()
    assert code == 0
    assert json.loads(out)["findings"] == []


def test_studio_disk_holds_no_id_text_or_vector_in_the_clear(studio: Studio) -> None:
    d = studio.disk()
    assert all(found == n and n > 0 for found, n in d.naive.values())
    assert all(found == 0 for found, _ in d.sever.values())


def test_studio_restart_and_a_killed_writer_lose_nothing(studio: Studio) -> None:
    before, after, gone = studio.restart()
    assert before == after
    assert gone
    assert studio.backend.mismatches() == []
    c = studio.crash(count=40)
    assert c.killed
    assert c.acked > 0
    assert c.missing == 0
    assert studio.backend.mismatches() == []


def test_studio_search_finds_each_fixture_answer(studio: Studio) -> None:
    n, _, at10, _ = studio.search_quality()
    assert n > 0
    assert at10 == n


def test_studio_every_row_can_be_ticked(studio: Studio) -> None:
    studio.verify_data()
    studio.encoder_check()
    studio.clusters()
    studio.hover(next(iter(studio.backend.index.records)))
    studio.limits()
    studio.evidence()
    for name in ("idea", "durable", "receipt"):
        if proofs.recorded(ROOT, name):
            studio.proof(name, None)
        else:
            studio.proof(name, "synthetic")
    shown = {k for k, v in studio.checklist.verdicts.items() if v.ok}
    missing = {r.key for r in ROWS} - shown
    # the erase proof and the sabotage lab build release binaries: covered by their own tests
    assert missing <= {"shred", "leak", "phasec", "sabotage"}, missing
    report = studio.report()
    doc = json.loads(report.read_text("utf-8"))
    assert doc["of"] == len(ROWS) == 33


def test_studio_no_screen_shows_a_secret(studio: Studio) -> None:
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget

    from sever_studio.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    secrets = [json.loads(ln)[1] for ln in studio.backend.keystore.read_text("utf-8").splitlines()]
    assert secrets
    w = MainWindow(studio)
    w.show()
    for key in w.screens:
        w.go(key)
        w.worker.wait()
        app.processEvents()
    texts = []
    for widget in w.findChildren(QWidget):
        if isinstance(widget, (QLabel, QAbstractButton)):
            texts.append(widget.text())
        texts.append(widget.toolTip())
    blob = "\n".join(texts)
    assert not any(s in blob for s in secrets)
    w.worker.wait()
    w.close()


def test_studio_reads_the_recorded_proofs() -> None:
    for name in ("idea", "durable", "receipt"):
        p = proofs.load_recorded(ROOT, name)
        if p is None:
            pytest.skip("no recorded nq-10k runs in artefacts/demo/")
        assert p.ok, (name, p.checks)


def test_studio_reads_the_erase_output() -> None:
    text = (Path(__file__).parent / "data/demo-p4.out").read_text("utf-8")
    p = proofs.read("erase", {}, text, "captured")
    assert p.ok, p.checks
    r = p.report
    assert "RECOVERS" in r["normal"]["1"]
    assert "0 findings" in r["normal"]["3"]
    assert "7 findings" in r["sb24"]["3"]


def test_studio_erase_parser_catches_a_leak_in_the_real_build() -> None:
    text = (Path(__file__).parent / "data/demo-p4.out").read_text("utf-8")
    broken = text.replace(
        "scan the image for the deleted records: 0 findings", "scan: 3 findings", 1
    )
    assert not proofs.read("erase", {}, broken, "captured").ok


def test_studio_sabotage_commands_match_the_runner() -> None:
    run_sh = (ROOT / "tests/sabotage/run.sh").read_text("utf-8")
    for item in sabotage.ITEMS:
        assert item.id in run_sh, item.id
        cmd, env = sabotage.command(item)
        if item.kind == "python":
            assert env["SEVER_SABOTAGE"] == item.id
        else:
            assert any(f"sabotage-{item.id}" in a for a in cmd)
    assert len(sabotage.ITEMS) == 30


def test_studio_evidence_is_read_from_the_generated_reports() -> None:
    lines = evidence.headlines(ROOT)
    assert {ln.source for ln in lines} >= {"TRACE_PART_1.md", "PROOFS_P2.md"}
    assert all(any(ch.isdigit() for ch in ln.claim) for ln in lines)


def test_studio_encoder_matches_the_dataset_vectors() -> None:
    from sever_studio.encoder import Encoder, EncoderError

    models = ROOT / "studio/work/models"
    emb = ROOT / "datasets/processed/nq_1m/embeddings.npy"
    try:
        enc = Encoder(models)
    except EncoderError:
        pytest.skip("the encoder is not fetched (studio/studio.sh setup)")
    if not emb.exists():
        pytest.skip("no NQ data")
    import pyarrow.parquet as pq

    batch = next(
        pq.ParquetFile(ROOT / "datasets/processed/nq_1m/passages.parquet").iter_batches(
            batch_size=20, columns=["text"]
        )
    )
    texts = [str(t) for t in batch.to_pydict()["text"]]
    ours = enc.encode(texts).astype(np.float64)
    theirs = np.load(emb, mmap_mode="r")[:20].astype(np.float64)
    assert float((ours * theirs).sum(axis=1).min()) > 0.9999
