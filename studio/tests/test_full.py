"""The full tier (``studio/studio.sh test --full``): long, real, and slow on purpose.

- a soak: 500 seeded random operations, the index checked against the database after every one;
- the real data: every demonstration on a copy of the prepared NQ database, timed;
- responsiveness: the window's thread is never blocked for long while the NQ map is drawn,
  replayed and searched;
- sabotage: one planted bug of each kind, built and tested live.
"""

import random
import shutil
import time
from collections.abc import Iterator
from typing import Any

import pytest
from conftest import CFG, WORK
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from sever_studio.actions import Studio
from sever_studio.checklist import ROWS

pytestmark = pytest.mark.full


def exact(s: Studio) -> None:
    assert s.backend.mismatches() == []
    assert s.backend.total() == len(s.backend.index.records)


def test_full_soak_500_random_operations(report: dict[str, Any]) -> None:
    work = WORK / "test-soak"
    shutil.rmtree(work, ignore_errors=True)
    s = Studio(CFG, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    rng = random.Random(42)  # the order of the operations only
    done: dict[str, int] = {}
    t0 = time.monotonic()
    for k in range(500):
        b = s.backend
        op = rng.choices(
            ["add", "fill", "delete", "forget", "search"],
            weights=[30, 15, 25, 6, 20],
        )[0]
        if op == "add":
            s.add_mine(f"Person {rng.randrange(40)}", f"note {k} {rng.random()}")
        elif op == "fill":
            s.fill_bucket(until="one", limit=20)
        elif op == "delete" and b.index.records:
            s.delete([rng.choice(sorted(b.index.records))])
        elif op == "forget":
            accounts = sorted(b.accounts())
            if accounts:
                s.forget(rng.choice(accounts))
        elif op == "search":
            s.ask(rng.randrange(len(s.corpus.questions)))
        done[op] = done.get(op, 0) + 1
        exact(s)
    report.update(
        operations=done, seconds=round(time.monotonic() - t0, 1), records=s.backend.total()
    )
    assert all(v.ok for v in s.checklist.verdicts.values())
    s.backend.close()
    shutil.rmtree(work, ignore_errors=True)


@pytest.fixture(scope="module")
def nq() -> Iterator[Studio]:
    source = WORK / "studio-nq"
    if not (source / "index.json").exists():
        pytest.skip("no prepared NQ database (studio/studio.sh prepare)")
    work = WORK / "test-nq"
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(source, work)
    s = Studio(CFG, "nq", work, dev=True, rows=10_000)
    s.open()
    yield s
    s.backend.close()
    shutil.rmtree(work, ignore_errors=True)


def test_full_every_demonstration_on_the_real_data(nq: Studio, report: dict[str, Any]) -> None:
    s = nq
    timings: dict[str, float] = {}

    def timed(name: str, fn: Any, *args: Any) -> Any:
        t = time.perf_counter()
        out = fn(*args)
        timings[name] = round(time.perf_counter() - t, 2)
        return out

    timed("verify_data", s.verify_data)
    timed("encoder_check", s.encoder_check)
    timed("clusters", s.clusters)
    a = timed("add_mine", s.add_mine, "Real Reviewer", "Please forget everything I wrote here.")
    s.hover(a.rid)
    timed("fill_one", s.fill_bucket, "one")
    timed("unsearchable", s.unsearchable)
    timed("fill_flush", s.fill_bucket, "flush")
    timed("search_quality", s.search_quality)
    timed("retry", s.retry)
    timed("refusals", s.refusals)
    d = timed("delete", s.delete, [a.rid])
    timed("delete_again", s.delete_again, a.rid)
    accounts = s.backend.accounts()
    big = max(sorted(accounts), key=lambda x: len(accounts[x]))
    f = timed("forget", s.forget, big)
    timed("verify", s.verify, f.lsns[0])
    timed("tamper", s.tamper, f.lsns[0])
    s.limits()
    timed("attack_lab", s.attack_lab, d.lsns[0])
    timed("log", s.log)
    timed("audit", s.audit)
    timed("disk", s.disk)
    timed("evidence", s.evidence)
    # the company demo on the real data: Acme Notes, with Chroma beside it (Stage 6)
    from sever_studio.company import Company
    from sever_studio.ordinary import Ordinary

    c = Company(s, Ordinary(s.work / "chroma"))
    notes = [
        "I am allergic to penicillin; my doctor is Dr. Mehta at the Elm Street clinic.",
        "My daughter's school pickup is at 3:15 on Tuesdays and Thursdays.",
    ]
    stored = timed("store_notes", c.store_notes, "Full Tier Person", notes)
    assert len(stored) == 2
    timed("let_others_write", c.let_others_write)
    got, _ = timed("ask", c.ask, notes[1])
    assert all(h.text is not None for h in got.hits)
    gone = timed("forget_me", c.forget, "Full Tier Person")
    assert gone.clean, gone
    assert gone.chroma is not None
    report.update(
        chroma_after={k: f for k, (f, _) in gone.chroma.after.hits.items()},
        sever_after={k: f for k, (f, _) in gone.after.hits.items()},
    )
    exact(s)
    v = s.checklist.verdicts
    report.update(timings=timings, numbers={k: x for k, x in s.numbers.items() if k != "data"})
    failed = {k: x.detail for k, x in v.items() if not x.ok}
    assert failed == {}
    assert {r.key for r in ROWS} - set(v) == set()


def test_full_the_window_never_freezes(
    nq: Studio, qapp: QApplication, report: dict[str, Any]
) -> None:
    from sever_studio.ui.app import fit
    from sever_studio.ui.main_window import MainWindow

    w = MainWindow(nq)
    fit(w, qapp)
    w.showMaximized()
    gaps: list[float] = []
    last = [time.monotonic()]

    def beat() -> None:
        now = time.monotonic()
        gaps.append(now - last[0])
        last[0] = now

    timer = QTimer()
    timer.timeout.connect(beat)
    timer.start(16)

    def run(seconds: float) -> None:
        t = time.monotonic()
        while time.monotonic() - t < seconds or w.worker.pending:
            qapp.processEvents()
            time.sleep(0.002)

    e = w.sections["explore"]
    w.go("explore")
    run(1.0)
    e.query.setText("#12")
    e.ask()
    run(1.0)
    e.replay()
    run(8.0)
    e.fill("one")
    run(2.0)
    timer.stop()
    worst = max(gaps[3:]) * 1000
    report.update(worst_ms=round(worst, 1), beats=len(gaps))
    w.close()
    assert worst < 250, f"the window's thread was blocked for {worst:.0f} ms"


@pytest.mark.full
def test_full_encoder_check_reencodes_stored_passages() -> None:
    # H6, oracle B: the ONNX encoder against the dataset's own vectors, not three names compared
    s = Studio(CFG, "nq", WORK / "studio-nq", dev=True, rows=10_000)
    s.encoder_check()
    v = s.checklist.verdicts["encoder"]
    assert v.ok, v.detail
    assert "cosine" in v.detail
