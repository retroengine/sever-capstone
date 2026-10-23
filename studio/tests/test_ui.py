"""The window, driven like a person drives it: real clicks, real key presses, a real mouse over
the map, on the owner's screen size (1280 × 800 at device pixel ratio 2; conftest.py).

The layout is checked in separate processes, one per screen size: the window must fit the screen
(a Wayland compositor kills a window that does not), nothing may be clipped or stick out of its
parent, and nothing may scroll sideways (``layout_probe.py``).
"""

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import WORK, screen_config
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from sever_studio.actions import Studio
from sever_studio.checklist import ROWS
from sever_studio.ui.app import fit
from sever_studio.ui.main_window import MainWindow
from sever_studio.ui.tour import CHAPTERS

ROOT = Path(__file__).resolve().parents[2]
SIZES = [(1280, 800, 2.0), (1024, 640, 1.0), (1366, 768, 1.0), (1920, 1080, 1.0)]


@pytest.mark.parametrize(
    "size",
    [pytest.param(s, marks=[] if s[0] == 1280 else [pytest.mark.full]) for s in SIZES],
    ids=lambda s: f"{s[0]}x{s[1]}@{s[2]:g}",
)
def test_ui_layout_fits_the_screen(size: tuple[int, int, float], report: dict[str, Any]) -> None:
    w, h, dpr = size
    shots = WORK / "screens" / f"{w}x{h}"
    shutil.rmtree(shots, ignore_errors=True)
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": screen_config(WORK / f".screen-{w}x{h}.json", w, h, dpr),
    }
    p = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parent / "layout_probe.py"),
            str(w),
            str(h),
            str(dpr),
            str(shots),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
        check=False,
    )
    assert p.returncode == 0, p.stderr[-2000:]
    doc = json.loads(p.stdout.strip().splitlines()[-1])
    report.update(frame=doc["frame"], minimum=doc["minimum"], shots=doc["shots"])
    assert doc["fits"], doc
    assert doc["problems"] == []
    assert doc["errors"] == []


# -- one window, driven by clicks ---------------------------------------------------------------


@pytest.fixture(scope="module")
def win(qapp: QApplication) -> Iterator[MainWindow]:
    work = WORK / "test-ui"
    shutil.rmtree(work, ignore_errors=True)
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    w = MainWindow(s)
    fit(w, qapp)
    w.showMaximized()
    settle(w)
    yield w
    w.close()
    shutil.rmtree(work, ignore_errors=True)


def settle(w: MainWindow, at_least: float = 0.15, timeout: float = 180) -> None:
    """Lets the window run until the worker, the map's animations and the step dots are done."""
    app = QApplication.instance()
    assert app is not None
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        app.processEvents()
        busy = w.worker.pending or w.sections["explore"].map._anims
        if time.monotonic() - t0 >= at_least and not busy:
            break
        time.sleep(0.01)
    for _ in range(40):  # timers that start when the work ends (dots, toasts)
        app.processEvents()
        time.sleep(0.01)


def press(b: QWidget) -> None:
    QTest.mouseClick(b, Qt.MouseButton.LeftButton)


def find(parent: QWidget, text: str) -> QPushButton:
    for b in parent.findChildren(QPushButton):
        if b.text().strip() == text and b.isVisible():
            return b
    raise AssertionError(f"no visible button {text!r}")


def test_ui_the_rail_switches_sections(win: MainWindow) -> None:
    for key, button in win.nav.items():
        press(button)
        settle(win)
        assert win.stack.currentWidget() is win.sections[key]


def test_ui_slash_opens_the_search(win: MainWindow) -> None:
    win.go("home")
    win.activateWindow()
    QTest.keyClick(win, Qt.Key.Key_Slash)
    settle(win)
    assert win.current == "explore"
    assert QApplication.focusWidget() is win.sections["explore"].query


def test_ui_hovering_a_dot_shows_its_card(win: MainWindow) -> None:
    win.go("explore")
    e = win.sections["explore"]
    e.dismiss_welcome()
    settle(win)
    rid = e.map.rids[len(e.map.rids) // 2]
    p = e.map.to_widget(*win.studio.xy(rid)).toPoint()
    QTest.mouseMove(e.map.viewport(), p)
    settle(win)
    assert e.card.isVisible()
    assert e.card.rid.text().startswith(rid)
    assert win.studio.checklist.verdicts["hover"].ok


def test_ui_click_delete_again_and_check_the_receipt(win: MainWindow) -> None:
    win.go("explore")
    e = win.sections["explore"]
    settle(win)
    rid = e.map.rids[3]
    p = e.map.to_widget(*win.studio.xy(rid)).toPoint()
    QTest.mouseClick(e.map.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    settle(win)
    assert e.sheet.isVisible()
    assert e.map.selected == rid
    press(e.b_delete)
    settle(win, 1.2)
    assert rid not in win.studio.backend.index.records
    assert e.b_again.isVisible()
    press(e.b_again)
    settle(win)
    assert "absent" in win.toaster.text.text()
    press(e.b_receipt)
    settle(win)
    assert win.current == "receipts"
    r = win.sections["receipts"]
    press(find(r, "Verify"))
    settle(win, 2.5)
    assert "ACCEPT" in r.verdict.text()
    press(find(r, "Flip one byte"))
    settle(win, 2.5)
    assert "REJECT" in r.verdict.text()
    assert "step 2" in r.reason.text()


def test_ui_add_yourself_with_the_form(win: MainWindow) -> None:
    win.go("explore")
    e = win.sections["explore"]
    press(e.fab)
    settle(win)
    assert e.add_panel.isVisible()
    QTest.keyClicks(e.account, "Grace Hopper")
    QTest.keyClicks(e.text, "Wrote the first compiler.")
    e.text.insertPlainText(" 🙂 Ünïcødé too.")  # pasted: QTest cannot type outside the BMP
    press(find(e.add_panel, "Add"))
    settle(win, 1.0)
    mine = [r for r, rec in win.studio.backend.index.records.items() if rec.mine]
    assert any(r.startswith("you-grace-hopper") for r in mine)
    assert win.studio.backend.mismatches() == []


@pytest.mark.full
def test_ui_the_whole_tour_by_its_buttons(win: MainWindow, report: dict[str, Any]) -> None:
    win.start_tour()
    settle(win)
    t0 = time.monotonic()
    for i, ch in enumerate(CHAPTERS):
        assert win.tour.title.text().startswith(f"{i + 1}.")
        if "sabotage" not in ch.rows:
            press(find(win.tour, "Do it"))
            settle(win, 0.5)
        if i < len(CHAPTERS) - 1:
            press(win.tour.findChildren(QPushButton)[-2])  # Next
            settle(win)
    report["tour_seconds"] = round(time.monotonic() - t0, 1)
    v = win.studio.checklist.verdicts
    missing = {r.key for r in ROWS} - set(v)
    failed = [k for k, x in v.items() if not x.ok]
    report.update(shown=len(v), failed=failed)
    assert missing <= {"sabotage"}, missing
    assert failed == []
    assert win.errors == []


def test_ui_bigger_text_still_fits(win: MainWindow, qapp: QApplication) -> None:
    geo = qapp.primaryScreen().availableGeometry()
    win.set_scale(0.4)
    for key in ("home", "explore", "receipts", "live", "hood", "proof"):
        win.go(key)
        settle(win)
        assert win.frameGeometry().width() <= geo.width()
        assert win.frameGeometry().height() <= geo.height()
    win.set_scale(-0.4)
    assert win.errors == []


def test_ui_a_second_studio_on_the_same_data_says_who_holds_it(win: MainWindow) -> None:
    from sever_studio.backend import WorkInUseError, lock

    work = WORK / "test-lock"
    held = lock(work, "prepare")
    try:
        code = (
            "import sys; sys.path[:0] = ['studio', 'python']\n"
            "from pathlib import Path\n"
            "from sever_studio.backend import lock, WorkInUseError\n"
            f"try:\n    lock(Path({str(work)!r}), 'run')\n"
            "except WorkInUseError as e:\n    print(e)\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
        )
        msg = out.stdout.strip()
        assert "busy" in msg
        assert "preparing the database" in msg
        assert str(os.getpid()) in msg
    finally:
        os.close(held)
    del WorkInUseError


@pytest.mark.full
def test_ui_smoke_on_the_real_display(report: dict[str, Any]) -> None:
    """The window on this machine's own display (WSLg Wayland): opens, walks everything, quits."""
    from conftest import REAL_DISPLAY

    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        pytest.skip("no display")
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    if REAL_DISPLAY:
        env["QT_QPA_PLATFORM"] = REAL_DISPLAY
    p = subprocess.run(
        ["bash", "studio/studio.sh", "smoke", "--data", "synthetic"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=900,
        check=False,
    )
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("smoke:")), p.stdout[-500:])
    report["smoke"] = line
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    assert "PASS" in line


def test_ui_a_search_says_when_your_records_wait_in_the_bucket(win: MainWindow) -> None:
    s = win.studio
    rid = s.add_mine("Waiting Wendy", "far from every group").rid
    assert s.backend.index.records[rid].group == "holding"  # §7.4: close to no group
    e = win.sections["explore"]
    win.go("explore")
    e.query.setText("#0")
    e.ask()
    settle(win)
    lines = [e.res_list.item(i).text() for i in range(e.res_list.count())]
    assert any("wait in the bucket" in t for t in lines), lines
    assert rid not in [r for r, _, _ in s.ask(0)[1]]  # and indeed no search reaches it


def test_ui_a_name_lists_that_persons_records(win: MainWindow) -> None:
    s = win.studio
    one = s.add_mine("Lin Lookup", "first note").rid
    two = s.add_mine("Lin Lookup", "second note").rid
    e = win.sections["explore"]
    win.go("explore")
    e.query.setText("lin lookup")  # any case: a name, not a meaning
    e.ask()
    settle(win)
    rows = [e.res_list.item(i) for i in range(e.res_list.count())]
    assert "Lin Lookup: 2 records" in rows[0].text()
    picked = [r.data(Qt.ItemDataRole.UserRole) for r in rows[1:3]]
    assert set(picked) == {one, two}
    e._pick_result(rows[1])  # a click on a result selects its dot
    settle(win)
    assert e.map.selected == picked[0]
    assert e.sheet.isVisible()
