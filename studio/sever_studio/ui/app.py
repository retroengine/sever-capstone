"""Starts the window on a prepared database, sized to the screen it opens on.

``smoke=True`` walks every section, every tab and the whole tour with "Do it" (the slow sabotage
build left out), then quits: exit 1 if Qt reported a warning or an error, the window did not fit
the screen, or a step failed.
"""

import sys
import time
from collections.abc import Callable, Iterator
from functools import partial
from pathlib import Path

from PySide6.QtCore import QMessageLogContext, QTimer, QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QMessageBox

from ..actions import Studio
from ..checklist import ROWS
from . import theme
from .main_window import MainWindow
from .tour import CHAPTERS

#: Qt messages that say nothing about Studio: WSLg's compositor reports the first two on every
#: start; the third comes from passages in a script no installed font covers (setup says which
#: package adds the fonts).
BENIGN = (
    "Wayland does not support QWindow::requestActivate",
    "propagateSizeHints",
    "OpenType support missing for",
)


def fit(win: MainWindow, app: QApplication) -> None:
    """Never larger than the screen: a Wayland compositor kills a window that is (WSLg)."""
    geo = app.primaryScreen().availableGeometry()
    win.setMinimumSize(min(960, geo.width()), min(600, geo.height()))
    win.resize(min(int(geo.width() * 0.94), 1680), min(int(geo.height() * 0.94), 1050))


def smoke_steps(win: MainWindow) -> Iterator[Callable[[], None]]:
    for section in ("home", "explore", "receipts", "hood", "proof"):
        yield partial(win.go, section)
    for tab in ("log", "disk", "crash", "rules"):
        yield partial(win.go, "hood", tab)
    for tab in ("parts", "sabotage", "evidence"):
        yield partial(win.go, "proof", tab)
    yield win.start_tour
    for i, ch in enumerate(CHAPTERS):
        if i:
            yield partial(win.tour.step, 1)
        if "sabotage" not in ch.rows:
            yield partial(win._tour_do, ch)
    yield win.toggle_drawer
    yield partial(win.set_scale, 0.2)
    yield partial(win.set_scale, -0.2)


def run(root: Path, data: str, rows: int, work: Path, dev: bool, smoke: bool = False) -> int:
    issues: list[str] = []

    def handler(mode: QtMsgType, ctx: QMessageLogContext, msg: str) -> None:
        if (
            mode != QtMsgType.QtDebugMsg
            and mode != QtMsgType.QtInfoMsg
            and not any(b in msg for b in BENIGN)
        ):
            issues.append(msg)
        if not any(b in msg for b in BENIGN):
            print(msg, file=sys.stderr)

    qInstallMessageHandler(handler)
    app = QApplication.instance() or QApplication(sys.argv)
    assert isinstance(app, QApplication)
    app.setApplicationName("SEVER-DB Studio")
    app.setFont(theme.font())
    app.setStyleSheet(theme.stylesheet())
    if not (work / "index.json").exists():
        hint = f"Nothing is prepared in {work.name} yet. Run once:  studio/studio.sh prepare" + (
            " --data synthetic" if data == "synthetic" else ""
        )
        print(hint, file=sys.stderr)
        if not smoke:
            QMessageBox.information(None, "SEVER-DB Studio", hint)
        return 2
    studio = Studio(root, data, work, dev, rows)
    studio.open()
    win = MainWindow(studio)
    fit(win, app)
    if smoke:
        steps = smoke_steps(win)
        errors = win.errors
        t0 = time.monotonic()

        def tick() -> None:
            if win.worker.pending or win.sections["explore"].map._anims:
                return
            try:
                next(steps)()
            except StopIteration:
                timer.stop()
                geo = app.primaryScreen().availableGeometry()
                frame = win.frameGeometry()
                fits = frame.width() <= geo.width() and frame.height() <= geo.height()
                failed_rows = [k for k, v in studio.checklist.verdicts.items() if not v.ok]
                ok = not issues and not errors and fits and not failed_rows
                print(
                    f"smoke: {'PASS' if ok else 'FAIL'} in {time.monotonic() - t0:.0f} s; screen "
                    f"{geo.width()}x{geo.height()}, window {frame.width()}x{frame.height()}; "
                    f"checklist {studio.checklist.passed()}/{len(ROWS)}; "
                    f"{len(issues)} Qt messages; {len(errors)} errors",
                    flush=True,
                )
                missing = [r.key for r in ROWS if not studio.checklist.verdicts.get(r.key)]
                failed = [k for k, v in studio.checklist.verdicts.items() if not v.ok]
                print(f"  not shown: {missing or 'none'}; failed: {failed or 'none'}", flush=True)
                for m in issues + errors:
                    print(f"  {m}", flush=True)
                win.close()
                app.exit(0 if ok else 1)

        timer = QTimer()
        timer.timeout.connect(tick)
        timer.start(350)
    win.showMaximized()
    return app.exec()
