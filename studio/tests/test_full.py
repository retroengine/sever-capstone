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
from pathlib import Path
from typing import Any

import pytest
from conftest import WORK
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from sever_studio.actions import Studio
from sever_studio.checklist import ROWS

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.full


def exact(s: Studio) -> None:
    assert s.backend.mismatches() == []
    assert s.backend.total() == len(s.backend.index.records)


def test_full_soak_500_random_operations(report: dict[str, Any]) -> None:
    work = WORK / "test-soak"
    shutil.rmtree(work, ignore_errors=True)
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    rng = random.Random(42)  # the order of the operations only
    done: dict[str, int] = {}
    t0 = time.monotonic()
    for k in range(500):
        b = s.backend
        op = rng.choices(
            ["add", "fill", "delete", "forget", "search", "restart", "crash"],
            weights=[30, 15, 25, 6, 20, 2, 2],
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
        elif op == "restart":
            s.restart()
        elif op == "crash":
            assert s.crash(count=20).missing == 0
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
    s = Studio(ROOT, "nq", work, dev=True, rows=10_000)
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
    timed("climb", s.climb, d.lsns[0])
    timed("attack_lab", s.attack_lab, d.lsns[0])
    timed("log", s.log)
    timed("audit", s.audit)
    timed("disk", s.disk)
    timed("restart", s.restart)
    timed("crash", s.crash, 200)
    for _ in range(3):
        account, _ = s.crash_test_person()
        timed("crash_delete", s.crash_delete, account, random.uniform(0.2, 1.3))
    timed("race", s.race, 20_000)
    for name in ("idea", "durable", "receipt"):
        timed(f"proof_{name}", s.proof, name, None)
    timed("proof_erase", s.proof, "erase", "synthetic")
    timed("evidence", s.evidence)
    exact(s)
    v = s.checklist.verdicts
    report.update(timings=timings, numbers={k: x for k, x in s.numbers.items() if k != "data"})
    failed = {k: x.detail for k, x in v.items() if not x.ok}
    assert failed == {}
    assert {r.key for r in ROWS} - set(v) <= {"sabotage"}


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


@pytest.mark.parametrize("sb", ["SB-1", "SB-16", "SB-24"])
def test_full_a_planted_bug_turns_a_test_red(sb: str, report: dict[str, Any]) -> None:
    from sever_studio import sabotage

    out = sabotage.run(ROOT, sb)
    report.update(summary=out.summary)
    assert out.compiled
    assert out.caught, out.output[-3000:]
