"""The window: screens on the left, the checklist on the right, story mode across the top."""

from collections.abc import Callable
from functools import partial
from typing import Any

from PySide6.QtGui import QCloseEvent, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..actions import Studio
from ..checklist import BY_KEY, ROWS
from . import theme
from .screen_disk import CrashScreen, DiskScreen
from .screen_map import MapScreen
from .screen_proofs import EvidenceScreen, ProofsScreen, SabotageScreen
from .screen_receipt import LogScreen, ReceiptScreen
from .screen_start import RulesScreen, StartScreen
from .story import CHAPTERS
from .widgets import Toast, badge, button, label, tick, tick_colour
from .worker import Worker

SCREENS = [
    ("start", "Start"),
    ("map", "Map"),
    ("rules", "Refusals"),
    ("receipt", "Receipt"),
    ("log", "Log"),
    ("disk", "Disk"),
    ("crash", "Crash"),
    ("proofs", "Proofs"),
    ("sabotage", "Sabotage lab"),
    ("evidence", "Evidence"),
]
#: checklist screen names -> the window's screen keys
SCREEN_OF = {
    "Start": "start",
    "Map": "map",
    "Bucket": "map",
    "Search": "map",
    "Your details": "map",
    "Refusals": "rules",
    "Receipt": "receipt",
    "Log": "log",
    "Disk": "disk",
    "Crash": "crash",
    "Proofs": "proofs",
    "Sabotage": "sabotage",
    "Evidence": "evidence",
}


class ChecklistPanel(QFrame):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.setObjectName("card")
        self.w = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        self.head = label("", "h3")
        lay.addWidget(self.head)
        lay.addWidget(label("Ticked only by a live check in this session.", "muted", wrap=True))
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(2)
        self.marks: dict[str, QLabel] = {}
        for r in ROWS:
            row = QHBoxLayout()
            m = QLabel("○")
            m.setFixedWidth(18)
            self.marks[r.key] = m
            row.addWidget(m)
            t = QLabel(f"{r.n}. {r.title}")
            t.setWordWrap(True)
            t.setToolTip(f"{r.spec} · screen: {r.screen}")
            t.setStyleSheet("font-size: 9.5pt;")
            row.addWidget(t, 1)
            row.addWidget(button("show", "show", partial(self.w.show_row, r.key)))
            box = QWidget()
            box.setLayout(row)
            il.addWidget(box)
        il.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        lay.addWidget(scroll, 1)
        lay.addWidget(button("Save the session report", "", self.w.save_report))
        self.setFixedWidth(300)
        self.refresh()

    def refresh(self) -> None:
        c = self.w.studio.checklist
        for key, m in self.marks.items():
            v = c.verdicts.get(key)
            ok = v.ok if v else None
            m.setText(tick(ok))
            m.setStyleSheet(f"color: {tick_colour(ok)}; font-weight: 700;")
            if v:
                m.setToolTip(v.detail)
        self.head.setText(f"Checklist · {c.passed()} of {len(ROWS)} shown")


class StoryBar(QFrame):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.setObjectName("story")
        self.w = window
        self.i = 0
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 12, 10)
        text = QVBoxLayout()
        self.title = label("", "h3")
        self.say = label("", wrap=True)
        self.look = label("", "muted", wrap=True)
        text.addWidget(self.title)
        text.addWidget(self.say)
        text.addWidget(self.look)
        lay.addLayout(text, 1)
        lay.addWidget(button("◀", "", lambda: self.step(-1)))
        lay.addWidget(button("Do it", "primary", self.do))
        lay.addWidget(button("Next ▶", "", lambda: self.step(1)))
        self.hide()

    def show_chapter(self) -> None:
        ch = CHAPTERS[self.i]
        self.title.setText(f"{self.i + 1} / {len(CHAPTERS)} · {ch.title}")
        self.say.setText(ch.say)
        self.look.setText("Look for: " + ch.look)
        self.w.go(ch.screen)

    def step(self, d: int) -> None:
        self.i = max(0, min(len(CHAPTERS) - 1, self.i + d))
        self.show_chapter()

    def do(self) -> None:
        for key in CHAPTERS[self.i].rows:
            self.w.show_row(key, story=True)


class MainWindow(QMainWindow):
    def __init__(self, studio: Studio) -> None:
        super().__init__()
        self.studio = studio
        self.worker = Worker()
        self.receipts_of: dict[int, tuple[str, str]] = {}
        self.setWindowTitle("SEVER-DB Studio")
        self.resize(1680, 1000)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        top = QHBoxLayout()
        title = label("SEVER-DB Studio", "h2")
        top.addWidget(title)
        c = studio.corpus
        top.addWidget(
            badge(
                f"{'Natural Questions' if studio.data == 'nq' else 'offline fixture'} · d = {c.d} ·"
                f" {len(studio.backend.index.records):,} records",
                theme.ACCENT,
            )
        )
        if studio.backend.refused:
            top.addWidget(badge("development override in use", theme.WARN))
        top.addStretch(1)
        self.busy = badge("working…", theme.WARN)
        self.busy.hide()
        top.addWidget(self.busy)
        self.list_btn = button("Checklist", "", self.toggle_list)
        self.list_btn.setCheckable(True)
        self.list_btn.setChecked(True)
        top.addWidget(self.list_btn)
        self.story_btn = button("Story mode", "", self.toggle_story)
        self.story_btn.setCheckable(True)
        top.addWidget(self.story_btn)
        outer.addLayout(top)

        self.story = StoryBar(self)
        outer.addWidget(self.story)

        body = QHBoxLayout()
        body.setSpacing(12)
        nav = QVBoxLayout()
        nav.setSpacing(2)
        self.nav_group = QButtonGroup(self)
        self.nav: dict[str, QPushButton] = {}
        for key, name in SCREENS:
            b = button(name, "nav", partial(self.go, key))
            b.setCheckable(True)
            self.nav_group.addButton(b)
            self.nav[key] = b
            nav.addWidget(b)
        nav.addStretch(1)
        nav.addWidget(label("F11: full screen", "muted"))
        navw = QWidget()
        navw.setLayout(nav)
        navw.setFixedWidth(140)
        body.addWidget(navw)

        self.stack = QStackedWidget()
        self.screens: dict[str, Any] = {
            "start": StartScreen(self),
            "map": MapScreen(self),
            "rules": RulesScreen(self),
            "receipt": ReceiptScreen(self),
            "log": LogScreen(self),
            "disk": DiskScreen(self),
            "crash": CrashScreen(self),
            "proofs": ProofsScreen(self),
            "sabotage": SabotageScreen(self),
            "evidence": EvidenceScreen(self),
        }
        for key, _ in SCREENS:
            w = self.screens[key]
            if key in ("start", "rules", "log", "disk", "crash", "proofs", "evidence"):
                sc = QScrollArea()
                sc.setWidget(w)
                sc.setWidgetResizable(True)
                self.stack.addWidget(sc)
                self._wrapped = getattr(self, "_wrapped", {})
                self._wrapped[key] = sc
            else:
                self.stack.addWidget(w)
        body.addWidget(self.stack, 1)
        self.panel = ChecklistPanel(self)
        body.addWidget(self.panel)
        outer.addLayout(body, 1)

        self.toaster = Toast(root)
        self.worker.busy_changed.connect(self.busy.setVisible)
        QShortcut(QKeySequence("F11"), self, self.toggle_full)
        self.current = ""
        self.go("start")

    # -- the Host protocol ------------------------------------------------------------------------

    def toast(
        self,
        text: str,
        colour: str = theme.ACCENT,
        action: str = "",
        on: Callable[[], None] | None = None,
    ) -> None:
        self.toaster.pop(text, colour, action, on)

    def error(self, message: str) -> None:
        self.toast(f"Error: {message}", theme.BAD)
        self.changed()

    def changed(self) -> None:
        self.panel.refresh()

    def go(self, screen: str, **kw: Any) -> None:
        w = self.screens[screen]
        holder = getattr(self, "_wrapped", {}).get(screen, w)
        self.stack.setCurrentWidget(holder)
        self.nav[screen].setChecked(True)
        if screen != self.current or kw:
            w.arrive(**kw)
        self.current = screen

    # -- the checklist ----------------------------------------------------------------------------

    def show_row(self, key: str, story: bool = False) -> None:
        """Goes to the row's screen and runs its live check (or says what to do there)."""
        row = BY_KEY[key]
        screen = SCREEN_OF[row.screen]
        s = self.screens
        m: MapScreen = s["map"]
        self.go(screen)
        actions: dict[str, Callable[[], None]] = {
            "data": s["start"].verify_data,
            "startup": s["start"].show_open,
            "encoder": s["start"].encoder,
            "clusters": s["start"].clusters if screen == "start" else m.redraw,
            "insert": lambda: self._focus_form(m),
            "freetext": lambda: self._focus_form(m),
            "routing": lambda: self._focus_form(m),
            "flush": lambda: m.fill("flush"),
            "unsearchable": lambda: self._waiting(m),
            "search": lambda: self._search(m),
            "hover": lambda: self.toast(
                "Hover any point on the map: its card opens.", theme.ACCENT
            ),
            "delete": lambda: self._delete(m),
            "absent": m.delete_again,
            "forget": lambda: self._forget(m),
            "retry": s["rules"].retry,
            "refusals": s["rules"].refusals,
            "verify": s["receipt"].verify,
            "tamper": s["receipt"].tamper,
            "limits": lambda: s["receipt"].arrive(),
            "log": s["log"].read,
            "audit": s["log"].audit,
            "disk": s["disk"].scan,
            "restart": s["crash"].restart,
            "crash": s["crash"].crash,
            "exact": lambda: s["proofs"].arrive(run="idea", live=None),
            "ghost": lambda: s["proofs"].arrive(run="idea", live=None),
            "durable": lambda: s["proofs"].arrive(run="durable", live=None),
            "chain": lambda: s["proofs"].arrive(run="receipt", live=None),
            "shred": lambda: s["proofs"].arrive(run="erase", live="synthetic"),
            "leak": lambda: s["proofs"].arrive(run="erase", live="synthetic"),
            "phasec": lambda: s["proofs"].arrive(run="erase", live="synthetic"),
            "sabotage": s["sabotage"].run,
            "evidence": lambda: s["evidence"].arrive(),
        }
        if story and key in ("ghost", "leak", "phasec"):
            return  # the chapter's other rows already ran the same program
        actions[key]()

    def _focus_form(self, m: MapScreen) -> None:
        m.account.setFocus()
        self.toast("Type your name and a sentence, then Add to the database.", theme.ACCENT)

    def _waiting(self, m: MapScreen) -> None:
        if not self.studio.backend.index.holding:
            m.fill("one")
        m.search_waiting()

    def _search(self, m: MapScreen) -> None:
        if not m.query.text().strip():
            m.query.setText("#12")
        m.ask()
        m.quality()

    def _delete(self, m: MapScreen) -> None:
        mine = [r for r, rec in self.studio.backend.index.records.items() if rec.mine]
        rid = m.map.selected or (mine[-1] if mine else None)
        if rid is None:
            self.toast("Click a point on the map, then Delete this record.", theme.ACCENT)
            return
        m.delete([rid], "delete")

    def _forget(self, m: MapScreen) -> None:
        if m.map.selected:
            m.forget_selected()
            return
        accounts = self.studio.backend.accounts()
        several = [a for a, ids in accounts.items() if len(ids) >= 3]
        if not several:
            self.toast("Click a point on the map, then Forget the account.", theme.ACCENT)
            return
        a = sorted(several, key=lambda a: -len(accounts[a]))[0]
        m.delete(accounts[a], "forget", a)

    # -- the rest ---------------------------------------------------------------------------------

    def toggle_story(self) -> None:
        on = self.story_btn.isChecked()
        self.story.setVisible(on)
        if on:
            self.story.show_chapter()

    def toggle_list(self) -> None:
        self.panel.setVisible(self.list_btn.isChecked())

    def toggle_full(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def save_report(self) -> None:
        path = self.studio.report()
        self.toast(f"Session report saved: {path.name} (numbers and verdicts only)", theme.OK)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        if self.toaster.isVisible():
            self.toaster.move(
                self.width() - self.toaster.width() - 24, self.height() - self.toaster.height() - 24
            )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt's name)
        self.worker.wait()
        if self.studio.checklist.verdicts:
            self.studio.report()
        self.studio.backend.close()
        event.accept()
