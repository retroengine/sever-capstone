"""Opens Studio on an emulated screen, walks every section and overlay, reports what does not fit.

Run by ``test_ui.py`` in its own process (a process has one screen):
``python tests/layout_probe.py WIDTH HEIGHT DPR OUTDIR``. Prints one JSON line:
the screen, the window's frame and minimum size, and every problem found in every state:

- the window larger than the screen (what WSLg's compositor kills);
- a single-line label or button whose text is wider than the widget (clipped);
- a visible widget outside its parent;
- a scroll area that scrolls sideways.

A screenshot of every state goes to OUTDIR.
"""

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "python"), str(ROOT / "studio")]

from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QLabel,
    QScrollArea,
    QWidget,
)

from sever_studio.actions import Studio  # noqa: E402
from sever_studio.ui import theme  # noqa: E402
from sever_studio.ui.app import fit  # noqa: E402
from sever_studio.ui.main_window import MainWindow  # noqa: E402


def inside_scroll(w: QWidget) -> bool:
    p = w.parentWidget()
    while p is not None:
        if isinstance(p, QAbstractScrollArea):
            return True
        p = p.parentWidget()
    return False


def problems(win: MainWindow, state: str) -> list[str]:
    out = []
    for w in win.findChildren(QWidget):
        if not w.isVisible() or w.width() <= 0:
            continue
        name = f"{state}: {type(w).__name__} {w.objectName() or ''}".strip()
        text = w.text() if isinstance(w, (QLabel, QAbstractButton)) else ""
        single = not (isinstance(w, QLabel) and (w.wordWrap() or w.pixmap()))
        if text and single and w.sizeHint().width() > w.width() + 2:
            out.append(f"{name} clipped ({w.sizeHint().width()} > {w.width()}): {text[:40]!r}")
        parent = w.parentWidget()
        plot = type(parent).__name__ in ("PlotWidget", "MapView", "GraphicsView")
        if parent is not None and not w.isWindow() and not inside_scroll(w) and not plot:
            g, r = w.geometry(), parent.rect()
            if (
                g.right() > r.right() + 1
                or g.bottom() > r.bottom() + 1
                or min(g.left(), g.top()) < -1
            ):
                out.append(
                    f"{name} outside {type(parent).__name__} ({g.getRect()} in {r.getRect()})"
                )
        if isinstance(w, QScrollArea) and w.horizontalScrollBar().maximum() > 0:
            out.append(f"{name} scrolls sideways by {w.horizontalScrollBar().maximum()} px")
    return out


def main() -> int:
    width, height, dpr, outdir = (
        int(sys.argv[1]),
        int(sys.argv[2]),
        float(sys.argv[3]),
        Path(sys.argv[4]),
    )
    outdir.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setFont(theme.font())
    app.setStyleSheet(theme.stylesheet())
    work = ROOT / "studio/work" / f"test-layout-{width}x{height}"
    shutil.rmtree(work, ignore_errors=True)
    studio = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    studio.open()
    studio.backend.insert_next(120)
    win = MainWindow(studio)
    fit(win, app)
    win.showMaximized()

    def settle(sec: float = 0.3) -> None:
        t = time.monotonic()
        while time.monotonic() - t < sec or win.worker.pending:
            app.processEvents()
            time.sleep(0.01)
        for _ in range(20):  # what the last result posted: new rows, their layout
            app.processEvents()
            time.sleep(0.01)

    found: list[str] = []
    shots = 0

    def check(state: str, wait: float = 0.3) -> None:
        nonlocal shots
        settle(wait)
        found.extend(problems(win, state))
        win.grab().save(str(outdir / f"{shots:02d}-{state}.png"))
        shots += 1

    for section, tab in [("home", None), ("explore", None), ("receipts", None)]:
        win.go(section, tab)
        check(section)
    for tab in ("log", "disk", "crash", "rules"):
        win.go("hood", tab)
        check(f"hood-{tab}")
    for tab in ("parts", "sabotage", "evidence"):
        win.go("proof", tab)
        check(f"proof-{tab}")
    win.go("live", "tree")
    check("live-empty")
    studio.forget("account-1")  # receipts for the live demonstrations
    live = win.sections["live"].tabs
    for tab, start in (
        ("tree", live["tree"].climb),
        ("attacks", live["attacks"].run),
        ("kill", live["kill"].run),
        ("race", live["race"].run),
    ):
        win.go("live", tab)
        start()
        check(f"live-{tab}", 4.0)  # the climb and the kills animate after the work is done
    e = win.sections["explore"]
    win.go("explore")
    e.dismiss_welcome()
    e.toggle_add()
    check("explore-add")
    e.toggle_add()
    rid = e.show_any()
    e.on_click(rid)
    check("explore-selected")
    e.query.setText("#0")
    e.ask()
    check("explore-search")
    win.toggle_drawer()
    check("drawer")
    win.toggle_drawer()
    win.start_tour()
    check("tour")
    win.set_scale(0.3)
    check("text-larger")
    geo = app.primaryScreen().availableGeometry()
    frame = win.frameGeometry()
    hint = win.minimumSizeHint()
    print(
        json.dumps(
            {
                "screen": [geo.width(), geo.height(), dpr],
                "frame": [frame.width(), frame.height()],
                "minimum": [hint.width(), hint.height()],
                "fits": frame.width() <= geo.width() and frame.height() <= geo.height(),
                "problems": found,
                "shots": shots,
                "errors": win.errors,
            }
        ),
        flush=True,
    )
    win.close()
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
