"""The window: an icon rail on the left, a slim top bar, one section at a time; the checklist slides
in from the right, the tour sits at the bottom, messages pop up as one-line toasts."""

from collections.abc import Callable
from functools import partial
from typing import Any

from PySide6.QtCore import QSize, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import explain
from ..actions import Studio
from ..checklist import CHECKS
from . import theme
from .drawer import Drawer
from .explore import Explore
from .home import Home
from .hood import Hood
from .icons import icon
from .live import Live
from .proof import ProofSection
from .receipts import Receipts
from .tour import Chapter, TourBar
from .widgets import Popover, Spinner, Toast, button, chip, label
from .worker import Worker

SECTIONS = [
    ("home", "home", "Home"),
    ("explore", "map", "Explore the map  ( / to search)"),
    ("receipts", "receipt", "Receipts"),
    ("live", "spark", "Live: log tree, attack lab, kill a delete, float vs exact"),
    ("hood", "engine", "Under the hood: log, disk, crash, bad input"),
    ("proof", "shield", "Proof: the four parts, sabotage, evidence"),
]
#: checklist row -> (section, tab)
WHERE = {
    **dict.fromkeys(("data", "startup", "encoder", "clusters"), ("home", None)),
    **dict.fromkeys(
        (
            "hover",
            "search",
            "insert",
            "freetext",
            "routing",
            "unsearchable",
            "flush",
            "delete",
            "absent",
            "forget",
        ),
        ("explore", None),
    ),
    **dict.fromkeys(("verify", "tamper", "limits"), ("receipts", None)),
    **dict.fromkeys(("log", "audit"), ("hood", "log")),
    "disk": ("hood", "disk"),
    **dict.fromkeys(("restart", "crash"), ("hood", "crash")),
    **dict.fromkeys(("refusals", "retry"), ("hood", "rules")),
    **dict.fromkeys(
        ("exact", "ghost", "durable", "chain", "shred", "leak", "phasec"), ("proof", "parts")
    ),
    "sabotage": ("proof", "sabotage"),
    "evidence": ("proof", "evidence"),
    "climb": ("live", "tree"),
    "attacks": ("live", "attacks"),
    "crashdelete": ("live", "kill"),
    "race": ("live", "race"),
}
SAMPLE = (
    "Tour visitor",
    "I am visiting the SEVER-DB demo and would like to be forgotten afterwards.",
)


class MainWindow(QMainWindow):
    def __init__(self, studio: Studio) -> None:
        super().__init__()
        self.studio = studio
        self.worker = Worker()
        self.errors: list[str] = []
        self.setWindowTitle("SEVER-DB Studio")
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(60)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(8, 12, 8, 12)
        rl.setSpacing(6)
        self.nav: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        for key, ico, tip in SECTIONS:
            b = QPushButton()
            b.setObjectName("rail")
            b.setIcon(icon(ico, theme.TEXT, 22))
            b.setIconSize(QSize(22, 22))
            b.setToolTip(tip)
            b.setCheckable(True)
            b.clicked.connect(partial(self.go, key))
            group.addButton(b)
            rl.addWidget(b)
            self.nav[key] = b
        rl.addStretch(1)
        rl.addWidget(button("A−", "ghost", lambda: self.set_scale(-0.1), tip="Smaller text"))
        rl.addWidget(button("A+", "ghost", lambda: self.set_scale(0.1), tip="Larger text"))
        outer.addWidget(rail)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        top = QFrame()
        top.setObjectName("topbar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(16, 8, 12, 8)
        tl.setSpacing(10)
        tl.addWidget(label("SEVER-DB Studio", "strong"))
        tl.addWidget(
            chip(
                f"{'Natural Questions' if studio.data == 'nq' else 'offline fixture'} · "
                f"{len(studio.backend.index.records):,} records",
                theme.ACCENT,
            )
        )
        if studio.backend.refused:
            dev = chip("development override", theme.WARN)
            dev.setToolTip(studio.backend.refused)
            tl.addWidget(dev)
        tl.addStretch(1)
        self.spinner = Spinner()
        tl.addWidget(self.spinner)
        self.progress = button("", "pill", self.toggle_drawer, "list", "The checklist")
        tl.addWidget(self.progress)
        tl.addWidget(button("Words", "ghost", self.glossary, "list", "What the terms mean"))
        tl.addWidget(button("Tour", "", self.start_tour, "play", "The guided tour"))
        column.addWidget(top)

        self.stage = QWidget()
        sl = QVBoxLayout(self.stage)
        sl.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        sl.addWidget(self.stack)
        column.addWidget(self.stage, 1)
        outer.addLayout(column, 1)

        self.sections: dict[str, Any] = {
            "home": Home(self, self.start_tour),
            "explore": Explore(self),
            "receipts": Receipts(self),
            "live": Live(self),
            "hood": Hood(self),
            "proof": ProofSection(self),
        }
        for key, _, _ in SECTIONS:
            self.stack.addWidget(self.sections[key])

        self.toaster = Toast(self.stage)
        self.tour = TourBar(self.stage, self._tour_go, self._tour_do)
        self.drawer = Drawer(self.stage, studio.checklist, self.show_row, self.save_report)
        self.worker.busy_changed.connect(self.spinner.run)

        QShortcut(QKeySequence("F11"), self, self.toggle_full)
        QShortcut(QKeySequence("/"), self, self._slash)
        QShortcut(QKeySequence("N"), self, self._next_chapter)
        QShortcut(QKeySequence("Esc"), self, self._escape)
        self.current = ""
        self.changed()
        self.go("home")

    # -- the Host protocol ------------------------------------------------------------------------

    def toast(
        self,
        text: str,
        ok: bool | None = True,
        action: str = "",
        on: Callable[[], None] | None = None,
    ) -> None:
        self.toaster.pop(text, ok, action, on)

    def error(self, message: str) -> None:
        self.errors.append(message)
        self.toast(message.split("\n")[0][:160], False)
        self.changed()

    def changed(self) -> None:
        self.drawer.refresh()
        self.progress.setText(f" {self.studio.checklist.passed()}/{len(CHECKS)}")

    def go(self, section: str, tab: str | None = None, **kw: Any) -> None:
        w = self.sections[section]
        self.stack.setCurrentWidget(w)
        self.nav[section].setChecked(True)
        if section != self.current or tab or kw:
            w.arrive(tab=tab, **kw) if section in ("hood", "proof", "live") else w.arrive(**kw)
        self.current = section

    # -- the checklist ----------------------------------------------------------------------------

    def show_row(self, key: str, tour: bool = False) -> None:
        """Goes to the row's place and runs its live check (or says what to do there)."""
        section, tab = WHERE[key]
        self.go(section, tab)
        s = self.sections
        e: Explore = s["explore"]
        hood, proof = s["hood"].tabs, s["proof"].tabs
        actions: dict[str, Callable[[], None]] = {
            "data": s["home"].verify_data,
            "startup": s["home"].show_startup,
            "encoder": s["home"].encoder,
            "clusters": s["home"].clusters,
            "hover": self._show_any,
            "search": lambda: self._search(e),
            "insert": lambda: self._add(e, tour),
            "freetext": lambda: self._add(e, tour),
            "routing": lambda: self._add(e, tour),
            "unsearchable": lambda: self._waiting(e),
            "flush": lambda: e.fill("flush"),
            "delete": lambda: self._delete(e),
            "absent": lambda: self.when_idle(e.delete_again),
            "forget": lambda: self._forget(e),
            "verify": s["receipts"].verify,
            "tamper": s["receipts"].tamper,
            "limits": lambda: None,
            "log": hood["log"].arrive,
            "audit": hood["log"].audit,
            "disk": hood["disk"].scan,
            "restart": hood["crash"].restart,
            "crash": hood["crash"].crash,
            "refusals": hood["rules"].refusals,
            "retry": hood["rules"].retry,
            "exact": lambda: proof["parts"].arrive("idea", "synthetic"),
            "ghost": lambda: proof["parts"].arrive("idea", "synthetic"),
            "durable": lambda: proof["parts"].arrive("durable", "synthetic"),
            "chain": lambda: proof["parts"].arrive("receipt", "synthetic"),
            "shred": lambda: proof["parts"].arrive("erase", "synthetic"),
            "leak": lambda: proof["parts"].arrive("erase", "synthetic"),
            "phasec": lambda: proof["parts"].arrive("erase", "synthetic"),
            "sabotage": proof["sabotage"].run,
            "evidence": lambda: None,
            "climb": s["live"].tabs["tree"].climb,
            "attacks": s["live"].tabs["attacks"].run,
            "crashdelete": s["live"].tabs["kill"].run,
            "race": s["live"].tabs["race"].engine_proof,
        }
        actions[key]()

    def _show_any(self) -> None:
        self.sections["explore"].show_any()

    def _add(self, e: Explore, tour: bool) -> None:
        if tour:
            if not e.account.text():
                e.account.setText(SAMPLE[0])
                e.text.setPlainText(SAMPLE[1])
            e.add_panel.show()
            e.place()
            e.add()
        else:
            e.add_panel.show()
            e.place()
            e.account.setFocus()

    def _waiting(self, e: Explore) -> None:
        if not self.studio.backend.index.holding:
            e.fill("one")
        e.search_waiting()

    def _search(self, e: Explore) -> None:
        if not e.query.text().strip():
            e.query.setText("#12")
        e.ask()
        e.quality()

    def _delete(self, e: Explore) -> None:
        mine = [r for r, rec in self.studio.backend.index.records.items() if rec.mine]
        rid = e.map.selected or (mine[-1] if mine else None)
        if rid is None:
            self.toast("Click a dot first, then Delete.", None)
            return
        e.delete([rid], "delete")

    def _forget(self, e: Explore) -> None:
        if e.map.selected:
            e.forget_selected()
            return
        accounts = self.studio.backend.accounts()
        several = sorted(
            (a for a, ids in accounts.items() if len(ids) >= 3), key=lambda a: -len(accounts[a])
        )
        if not several:
            self.toast("Click a dot first, then Forget.", None)
            return
        e.delete(accounts[several[0]], "forget", several[0])

    def when_idle(self, fn: Callable[[], None]) -> None:
        """Runs ``fn`` once the worker and the map's animations are done (a step that needs the
        result of the one before it)."""
        e: Explore = self.sections["explore"]
        if self.worker.pending or e.map._anims:
            QTimer.singleShot(100, lambda: self.when_idle(fn))
        else:
            fn()

    # -- the tour ---------------------------------------------------------------------------------

    def start_tour(self) -> None:
        self.drawer.close_drawer()
        self.tour.start()

    def _tour_go(self, ch: Chapter) -> None:
        self.go(ch.section, ch.tab)

    def _tour_do(self, ch: Chapter) -> None:
        done = set()
        for key in ch.rows:
            run = {
                "ghost": "exact",
                "leak": "shred",
                "phasec": "shred",
                "freetext": "insert",
                "routing": "insert",
            }.get(key, key)
            if run not in done:
                done.add(run)
                self.show_row(run, tour=True)

    # -- the rest ---------------------------------------------------------------------------------

    def _next_chapter(self) -> None:
        if self.tour.isVisible():
            self.tour.step(1)

    def toggle_drawer(self) -> None:
        self.drawer.toggle()

    def _slash(self) -> None:
        self.go("explore")
        self.sections["explore"].focus_search()

    def _escape(self) -> None:
        self.drawer.close_drawer()
        if self.current == "explore":
            e: Explore = self.sections["explore"]
            e.on_click(None)
            e.clear_search()
            e.add_panel.hide()

    def set_scale(self, d: float) -> None:
        theme.scale = round(max(0.8, min(1.6, theme.scale + d)), 1)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setFont(theme.font())
            app.setStyleSheet(theme.stylesheet())
        self.sections["explore"].place()

    def glossary(self) -> None:
        text = "<br>".join(f"<b>{term}</b>: {meaning}" for term, meaning in explain.GLOSSARY)
        Popover("Words used here", text).show_below(self.progress)

    def toggle_full(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def save_report(self) -> None:
        path = self.studio.report()
        self.toast(f"Report saved: {path.name}", True)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        self.drawer.place()
        if self.tour.isVisible():
            self.tour.place()
        if self.toaster.isVisible():
            self.toaster.place()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt's name)
        self.worker.wait()
        if self.studio.checklist.verdicts:
            self.studio.report()
        self.studio.backend.close()
        event.accept()
