"""The Assistant: Acme Notes, a company app on SEVER-DB, used as a customer would use it.

Left: you store your notes, ask the assistant, and ask to be forgotten. Right: the map (your notes
★, the hits lit) and, below it, every real call the app made to the database and the engine's state
after each action. "Forget me" opens a report that checks, row by row, what is left of you in
SEVER-DB and in an ordinary vector store (Chroma) running the same app.
"""

import shutil
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import layout
from ..actions import Verified
from ..assistant import Answer
from ..company import Company, Gone, Note, Retrieved
from . import copy, theme
from .host import Host
from .map3d import Map3D
from .map_view import MapView
from .widgets import Card, StepList, button, clear, label, mark

EXAMPLE_NAME = "Dana"
EXAMPLE_NOTES = [
    "I am allergic to penicillin; my doctor is Dr. Mehta at the Elm Street clinic.",
    "My daughter's school pickup is at 3:15 on Tuesdays and Thursdays.",
    "Remember to renew my passport before the trip to Lisbon in June.",
]
EXAMPLE_QUESTION = "When is my daughter's school pickup?"


def note_line(n: Note, spawn: int) -> str:
    if n.waiting:
        return (
            f"⏳ <b>{n.rid}</b> · log #{n.lsn} · waiting in the holding area: searchable once "
            f"{spawn} notes gather (§7.4)"
        )
    agreed = "" if n.agreed else " (routing not checked)"
    return f"✓ <b>{n.rid}</b> · log #{n.lsn} · group {n.placement}{agreed}"


def snippet(text: str, n: int = 140) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[: n - 1].rstrip() + "…"


class AssistantSection(QWidget):
    def __init__(self, host: Host, company: Company) -> None:
        super().__init__()
        self.host, self.company = host, company
        self.name_asked: str = ""
        self.last_gone: Gone | None = None
        self.report: ForgetReport | None = None
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(split)

        # -- left: you --------------------------------------------------------------------------
        inside = QWidget()
        left = QVBoxLayout(inside)
        left.setContentsMargins(20, 16, 12, 16)
        left.setSpacing(14)
        left.addWidget(label(copy.short("assistant.about"), "heading", wrap=True))
        left.addWidget(label(copy.long("assistant.about"), "small", wrap=True))

        you = Card("1  Store your notes", "assistant.you")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Your name")
        you.add(self.name)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Your notes, one per line")
        self.notes.setFixedHeight(110)
        you.add(self.notes)
        row = QHBoxLayout()
        row.addWidget(button("Fill example", "ghost", self.fill_example))
        self.b_store = button("Store my notes", "primary", self.store, "plus")
        row.addWidget(self.b_store)
        row.addStretch(1)
        you.body.addLayout(row)
        self.stored = label("", "small", wrap=True)
        self.stored.setTextFormat(Qt.TextFormat.RichText)
        you.add(self.stored)
        # only needed while a note waits in the holding area (§7.4)
        self.b_others = button(
            "Let other users write",
            "primary",
            self.others,
            "users",
            "Other customers' notes (the dataset's passages) until the holding area flushes",
        )
        self.b_others.hide()
        row2 = QHBoxLayout()
        row2.addWidget(self.b_others)
        row2.addStretch(1)
        you.body.addLayout(row2)
        self.holding = label("", "small", wrap=True)
        you.add(self.holding)
        left.addWidget(you)

        ask = Card("2  Ask about them", "assistant.ask")
        qrow = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText("Ask about your notes")
        self.question.returnPressed.connect(self.ask)
        qrow.addWidget(self.question, 1)
        qrow.addWidget(button("Ask", "primary", self.ask, "search"))
        ask.body.addLayout(qrow)
        self.answer = label("", "", wrap=True)
        self.answer.setTextFormat(Qt.TextFormat.RichText)
        self.answer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ask.add(self.answer)
        self.ai_note = label("", "small", wrap=True)
        ask.add(self.ai_note)
        self.cites = label("", "small", wrap=True)
        self.cites.setTextFormat(Qt.TextFormat.RichText)
        ask.add(self.cites)
        left.addWidget(ask)

        forget = Card("3  Forget me", "assistant.forget")
        frow = QHBoxLayout()
        self.b_forget = button("Forget me", "danger", self.forget, "forget")
        frow.addWidget(self.b_forget)
        self.b_report = button("Open the report", "ghost", self.open_report, "list")
        self.b_report.hide()
        frow.addWidget(self.b_report)
        frow.addStretch(1)
        forget.body.addLayout(frow)
        self.forgot = label("", "small", wrap=True)
        forget.add(self.forgot)
        left.addWidget(forget)
        self.cards = [you, ask, forget]
        for c in self.cards:  # as tall as what they hold; the room left stays below them
            c.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        left.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inside)
        scroll.setMinimumWidth(400)
        split.addWidget(scroll)
        self.left_scroll = scroll

        # -- right: the map, the calls, the engine ----------------------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 12, 16, 12)
        rl.setSpacing(8)
        mrow = QHBoxLayout()
        self.b2d = button("2-D", "ghost", lambda: self.set_mode("2d"), tip="The flat map")
        self.b3d = button("3-D", "ghost", lambda: self.set_mode("3d"), tip="Turn it in 3-D")
        for b in (self.b2d, self.b3d):
            b.setCheckable(True)
            mrow.addWidget(b)
        self.caption = label(copy.short("assistant.map"), "small", wrap=True)
        mrow.addWidget(self.caption, 1)
        rl.addLayout(mrow)
        self.stack = QStackedWidget()
        self.map = MapView(host.studio)
        self.map.setMouseEnabled(x=False, y=False)  # a picture here: a stray scroll never zooms it
        self.map.hideButtons()
        self.map3d = Map3D(host.studio, self.map)
        self.stack.addWidget(self.map)
        self.stack.addWidget(self.map3d)
        rl.addWidget(self.stack, 3)
        self.tabs = QTabWidget()
        self.calls = QTableWidget(0, 4)
        self.calls.setHorizontalHeaderLabels(["call", "arguments", "result", "ms"])
        self.calls.verticalHeader().hide()
        hh = self.calls.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.calls.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.calls, "SEVER-DB calls")
        state = QWidget()
        self.state_grid = QGridLayout(state)
        self.state_grid.setContentsMargins(12, 12, 12, 12)
        self.tabs.addTab(state, "Engine state")
        rl.addWidget(self.tabs, 2)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        self.mode = "2d"
        self.b2d.setChecked(True)
        self.step = 0
        self.next_step(1)
        self.tidy()

    # -- the Host's section protocol ------------------------------------------------------------

    def arrive(self, **_: Any) -> None:
        self.map.refresh()
        self.refresh_side()

    def next_step(self, n: int) -> None:
        """Outline the card of the step to do next (0: none)."""
        self.step = n
        for i, c in enumerate(self.cards, 1):
            c.setObjectName("cardNext" if i == n else "card")
            c.style().unpolish(c)
            c.style().polish(c)
        if n:  # bring it into view once the layout has settled
            card = self.cards[n - 1]
            QTimer.singleShot(0, lambda: self.left_scroll.ensureWidgetVisible(card, 0, 16))

    # -- actions --------------------------------------------------------------------------------

    def fill_example(self) -> None:
        if not self.name.text().strip():
            self.name.setText(EXAMPLE_NAME)
        if not self.notes.toPlainText().strip():
            self.notes.setPlainText("\n".join(EXAMPLE_NOTES))
        if not self.question.text().strip():
            self.question.setText(EXAMPLE_QUESTION)

    def store(self) -> None:
        name = self.name.text().strip()
        notes = [t for t in self.notes.toPlainText().splitlines() if t.strip()]
        if not name or not notes:
            self.host.toast("Type your name and at least one note (or Fill example).", None)
            return
        spawn = self.host.studio.corpus.spawn_target

        def done(out: list[Note]) -> None:
            self.notes.clear()
            lines = [note_line(n, spawn) for n in out]
            self.stored.setText("<br>".join(lines))
            waiting = sum(n.waiting for n in out)
            self.b_others.setVisible(bool(waiting))
            self.holding.setText(
                f"{waiting} of your notes wait: fill the holding area to make them searchable."
                if waiting
                else ""
            )
            self.host.toast(
                f"{len(out)} notes stored"
                + (f"; {waiting} waiting in the holding area" if waiting else ""),
                True,
            )
            self.next_step(1 if waiting else 2)
            self.after_action()

        self.host.worker.submit(
            lambda: self.company.store_notes(name, notes), done, self.host.error
        )

    def others(self) -> None:
        def done(n: int) -> None:
            self.holding.setText(
                f"✓ {n:,} other notes filled the holding area; it became a new group, so your "
                "notes are searchable now (§7.4–7.5)."
            )
            self.b_others.hide()
            mine = self.company.notes_of(self.name.text().strip())
            recs = self.host.studio.backend.index.records
            self.stored.setText(
                "<br>".join(f"✓ <b>{r}</b> · group {recs[r].group}" for r in mine if r in recs)
                or self.stored.text()
            )
            self.next_step(2)
            self.after_action()

        self.holding.setText("writing other users' notes…")
        self.tidy()
        self.host.worker.submit(self.company.let_others_write, done, self.host.error)

    def ask(self) -> None:
        q = self.question.text().strip()
        if not q:
            self.host.toast("Type a question (or Fill example).", None)
            return
        name = self.name.text().strip()
        s = self.host.studio

        def done(out: tuple[Retrieved, Answer]) -> None:
            got, ans = out
            # with AI off the answer is the passages themselves: shown once, in the list below
            self.answer.setText(escape(ans.text).replace("\n", "<br>") if ans.ai else "")
            self.ai_note.setText(ans.note)
            rows = []
            for h in got.hits:
                star = "★ " if h.mine and h.account == name else ""
                who = "your note" if star else (h.account or "another user")
                text = "passage absent" if h.text is None else snippet(h.text)
                rows.append(
                    f"<b>[{h.n}]</b> {star}{escape(text)}<br>"
                    f"<span style='color:{theme.MUTED}'>{who} · distance {h.distance:.3f}</span>"
                )
            rows.append(
                f"<span style='color:{theme.MUTED}'>searched {len(got.opened)} groups (§8.1); "
                "each text read from the database with passage() (§16.1)</span>"
            )
            self.cites.setText("<br>".join(rows))
            origin = layout.place(s.encode(q), s.corpus.vectors, s.coords)
            self.map.show_beam(origin, [(h.rid, h.distance, h.mine) for h in got.hits])
            self.next_step(3)
            self.after_action(redraw=False)

        self.answer.setText("asking…")
        self.tidy()
        self.host.worker.submit(lambda: self.company.ask(q), done, self.host.error)

    def forget(self) -> None:
        name = self.name.text().strip()
        if not name or not self.company.notes_of(name):
            self.host.toast("Store a note first: there is nothing of yours to forget.", None)
            return

        def done(g: Gone) -> None:
            self.last_gone = g
            self.map.clear_beam()
            self.answer.setText("")
            self.ai_note.setText("")
            self.cites.setText("")
            ok = sum(a for _, _, a in g.receipts)
            sign = "✓" if ok == len(g.receipts) else "✗"
            self.forgot.setText(
                f"{sign} {len(g.deleted.rids)} notes deleted; {ok} of {len(g.receipts)} "
                "receipts check out."
            )
            self.b_report.show()
            self.next_step(0)
            QTimer.singleShot(0, lambda: self.left_scroll.ensureWidgetVisible(self.cards[2], 0, 16))
            self.after_action()
            self.open_report()

        self.forgot.setText("forgetting…")
        self.tidy()
        self.host.worker.submit(lambda: self.company.forget(name), done, self.host.error)

    def open_report(self) -> None:
        if self.last_gone is None:
            self.host.toast("Forget me first: the report is about what is left.", None)
            return
        if self.report is None or self.report.g is not self.last_gone:
            self.report = ForgetReport(self.host, self.company, self.last_gone, self)
        self.report.show()
        self.report.raise_()

    def report_verify(self) -> None:
        self.open_report()
        if self.report is not None:
            self.report.verify()

    def report_flip(self) -> None:
        self.open_report()
        if self.report is not None:
            self.report.flip()

    # -- the right side -------------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        three = mode == "3d"
        self.mode = mode
        self.b2d.setChecked(not three)
        self.b3d.setChecked(three)
        self.stack.setCurrentWidget(self.map3d if three else self.map)
        s = self.host.studio
        if three and s.coords3 is None:
            if not self.map3d.reason:
                self.map3d.note.setText(copy.short("map.laying3"))
                self.map3d.note.show()
            self.host.worker.submit(s.layout3, lambda _: self.map3d.refresh(), self.host.error)
        elif three:
            self.map3d.refresh()

    def tidy(self) -> None:
        """An empty line takes no room."""
        for w in (self.stored, self.holding, self.answer, self.ai_note, self.cites, self.forgot):
            w.setVisible(bool(w.text()))

    def after_action(self, redraw: bool = True) -> None:
        self.tidy()
        if redraw:
            self.map.refresh()
            if self.mode == "3d":
                self.map3d.refresh()
        self.refresh_side()
        self.host.changed()

    def refresh_side(self) -> None:
        calls = self.company.calls[-300:]
        self.calls.setRowCount(len(calls))
        for i, c in enumerate(reversed(calls)):
            for j, v in enumerate((c.what, c.args, c.result, f"{c.ms:.1f}")):
                self.calls.setItem(i, j, QTableWidgetItem(v))

        def done(st: dict[str, Any]) -> None:
            clear(self.state_grid)
            for i, (k, v) in enumerate(st.items()):
                self.state_grid.addWidget(label(k, "small"), i, 0)
                self.state_grid.addWidget(
                    label(f"{v:,}" if isinstance(v, int) else str(v), "mono"), i, 1
                )
            self.state_grid.setRowStretch(len(st), 1)

        self.host.worker.submit(self.company.state, done, self.host.error)


class ForgetReport(QDialog):
    """What is left of the person, row by row, in SEVER-DB and in the ordinary store."""

    def __init__(self, host: Host, company: Company, g: Gone, parent: QWidget) -> None:
        super().__init__(parent)
        self.host, self.company, self.g = host, company, g
        self.setWindowTitle(f"Forget me: {g.name}")
        # never larger than the screen (WSLg); what does not fit scrolls
        geo = self.screen().availableGeometry()
        self.resize(min(1000, int(geo.width() * 0.9)), min(720, int(geo.height() * 0.85)))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inside = QWidget()
        scroll.setWidget(inside)
        outer.addWidget(scroll)
        lay = QVBoxLayout(inside)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)
        lay.addWidget(label(f"What is left of {g.name}", "heading"))
        self.summary = QGridLayout()
        self.summary.setHorizontalSpacing(24)
        self.summary.setVerticalSpacing(10)
        self.answers = self.summarise()
        for col, head in enumerate(("", "SEVER-DB", "Chroma, the same app")):
            if head:
                self.summary.addWidget(label(head, "strong"), 0, col)
        for r, (question, sever, chroma) in enumerate(self.answers, 1):
            self.summary.addWidget(label(question, "", wrap=True), r, 0)
            for col, (good, text) in enumerate((sever, chroma), 1):
                sign, colour = mark(good)
                cell = label(f"<span style='color:{colour}'><b>{sign}</b> {text}</span>", "")
                cell.setTextFormat(Qt.TextFormat.RichText)
                self.summary.addWidget(cell, r, col)
        self.summary.setColumnStretch(0, 3)
        self.summary.setColumnStretch(1, 2)
        self.summary.setColumnStretch(2, 2)
        box = Card()
        box.body.addLayout(self.summary)
        lay.addWidget(box)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["", "SEVER-DB", "Chroma, the same app"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        for row in self.rows():
            r = self.table.rowCount()
            self.table.insertRow(r)
            for col, text in enumerate(row):
                self.table.setItem(r, col, QTableWidgetItem(text))
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hh.sectionResized.connect(lambda *_: self._fit_table())
        self._fit_table()
        brow = QHBoxLayout()
        brow.addWidget(button("Verify receipts (offline)", "primary", self.verify, "shield"))
        brow.addWidget(button("Flip a byte", "danger", self.flip, "zap"))
        brow.addWidget(button("Save receipts…", "", self.save, "receipt"))
        brow.addStretch(1)
        self.b_details = button("Details", "ghost", self.toggle_details, "list")
        self.b_details.setCheckable(True)
        brow.addWidget(self.b_details)
        lay.addLayout(brow)
        self.verdict = label("", "strong", wrap=True)
        self.verdict.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.verdict)
        self.steps = StepList()
        lay.addWidget(self.steps)
        self.saved = label("", "mono", wrap=True)
        self.saved.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.saved)
        # the full table and what it does not show, behind Details
        self.details = QWidget()
        dl = QVBoxLayout(self.details)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(10)
        dl.addWidget(self.table)
        dl.addWidget(label(copy.long("forget.notes"), "small", wrap=True))
        self.details.hide()
        lay.addWidget(self.details)
        lay.addWidget(button("Close", "ghost", self.accept), 0, Qt.AlignmentFlag.AlignRight)
        lay.addStretch(1)

    def toggle_details(self) -> None:
        self.details.setVisible(self.b_details.isChecked())
        self._fit_table()

    def summarise(self) -> list[tuple[str, tuple[bool, str], tuple[bool | None, str]]]:
        """Three questions, each answered for both stores from the same measurements as the table:
        ✓ is the answer a person who asked to be forgotten wants."""
        g, c = self.g, self.g.chroma
        kinds = ("passage text", "vectors", "x̃ (stored integers)")

        def left(after: Any) -> tuple[int, int]:
            return self._found(after.hits, kinds)

        s_find = bool(g.found_by_search or g.readable)
        s_left, s_of = left(g.after)
        n = len(g.receipts)
        sever = [
            (not s_find, "no" if not s_find else "yes"),
            (s_left == 0, "nothing" if s_left == 0 else f"{s_left} of {s_of} found"),
            (n > 0, f"{n} receipt{'s' if n != 1 else ''}"),
        ]
        chroma: list[tuple[bool | None, str]]
        if c is None:
            chroma = [(None, "not set up")] * 3
        else:
            c_find = bool(c.found_by_query or c.readable)
            c_left, c_of = left(c.after)
            chroma = [
                (not c_find, "no" if not c_find else "yes"),
                (c_left == 0, "nothing" if c_left == 0 else f"still there: {c_left} of {c_of}"),
                (False, "none"),
            ]
        questions = [
            "Can the app still find or read your notes?",
            "Is your text or vector still in its files?",
            "Do you get proof it was deleted?",
        ]
        return [(q, a, b) for q, a, b in zip(questions, sever, chroma, strict=True)]

    def _fit_table(self) -> None:
        """The table as tall as its rows at the width it has now, so nothing hides under it."""
        self.table.resizeRowsToContents()
        rows_h = sum(self.table.rowHeight(i) for i in range(self.table.rowCount()))
        head = self.table.horizontalHeader().sizeHint().height()
        self.table.setFixedHeight(head + rows_h + 2 * self.table.frameWidth() + 4)

    def resizeEvent(self, e: QResizeEvent) -> None:  # noqa: N802 (Qt)
        super().resizeEvent(e)
        self._fit_table()

    @staticmethod
    def _found(hits: dict[str, tuple[int, int]], kinds: tuple[str, ...]) -> tuple[int, int]:
        return sum(hits[k][0] for k in kinds if k in hits), sum(
            hits[k][1] for k in kinds if k in hits
        )

    def rows(self) -> list[tuple[str, str, str]]:
        g, c = self.g, self.g.chroma
        d = g.deleted
        sizes = "; ".join(
            f"{grp} n {d.groups_before.get(grp, 0)} → {d.groups_after.get(grp, 0)}"
            for grp in sorted(d.groups_before)
        )
        text_k, vec_k = ("passage text",), ("vectors", "x̃ (stored integers)")

        def before_after(kinds: tuple[str, ...], before: Any, after: Any) -> str:
            b, n = self._found(before.hits, kinds)
            a, _ = self._found(after.hits, kinds)
            return f"{b} → {a} of {n} searched for"

        sever = [
            f"{len(d.rids)} records; {sizes}",
            "not found" if not g.found_by_search else f"FOUND: {', '.join(g.found_by_search)}",
            "passage() → absent" if not g.readable else f"passage() still reads {len(g.readable)}",
            before_after(text_k, g.before, g.after) + " (encrypted, §13.2)",
            before_after(vec_k, g.before, g.after),
            f"{len(g.receipts)} receipts",
        ]
        if c is None:
            chroma = ["not set up"] * 6
        else:
            chroma = [
                f"{c.deleted} deleted",
                "not found" if not c.found_by_query else f"FOUND: {', '.join(c.found_by_query)}",
                "get() → none" if not c.readable else f"get() still reads {len(c.readable)}",
                before_after(text_k, c.before, c.after),
                before_after(vec_k, c.before, c.after),
                "none",
            ]
        names = [
            "Deleted",
            "Search with her own words",
            "The app can still read her text",
            "Her text in the files, before → after",
            "Her vectors in the files (float32 or x̃), before → after",
            "Proof she can keep",
        ]
        return list(zip(names, sever, chroma, strict=True))

    def verify(self) -> None:
        s = self.host.studio

        def run() -> list[Verified]:
            return [s.verify(lsn) for lsn in self.g.deleted.lsns]

        def done(vs: list[Verified]) -> None:
            ok = sum(v.verdict == "ACCEPT" for v in vs)
            sign, colour = mark(ok == len(vs) and bool(vs))
            self.verdict.setText(
                f"<span style='color:{colour}'>{sign} ACCEPT × {ok} of {len(vs)}</span>: checked "
                "by sever-verify with only each receipt and the public anchors (§11.3)"
            )
            if vs:
                self.steps.show_steps([(x.number, x.checks, x.verdict) for x in vs[-1].steps])
            self.host.changed()

        self.verdict.setText("verifying…")
        self.host.worker.submit(run, done, self.host.error)

    def flip(self) -> None:
        if not self.g.deleted.lsns:
            return
        lsn = self.g.deleted.lsns[0]

        def done(v: Verified) -> None:
            bad = v.verdict.startswith("REJECT")
            sign, colour = mark(bad)
            at = v.flipped[0] if v.flipped else "?"
            self.verdict.setText(
                f"<span style='color:{colour}'>{sign} {v.verdict}</span>: receipt #{lsn} with "
                f"byte {at} flipped is rejected, at the step named"
            )
            self.steps.show_steps([(x.number, x.checks, x.verdict) for x in v.steps])
            self.host.changed()

        self.host.worker.submit(lambda: self.host.studio.tamper(lsn), done, self.host.error)

    def save(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save the receipts to")
        if folder:
            self.save_to(Path(folder))

    def save_to(self, folder: Path) -> list[str]:
        """Each receipt and the public anchors, and the exact command that checks each one."""
        b, cfg = self.host.studio.backend, self.host.studio.cfg
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy(b.receipts / "anchors.json", folder / "anchors.json")
        commands = []
        for lsn in self.g.deleted.lsns:
            shutil.copy(b.receipts / f"{lsn}.cert", folder / f"certificate-{lsn}.bin")
            commands.append(f"{cfg.verify} certificate-{lsn}.bin --anchors anchors.json --explain")
        (folder / "VERIFY.txt").write_text(f"cd {folder}\n" + "\n".join(commands) + "\n", "utf-8")
        self.saved.setText(f"saved in {folder}; check each with:\n" + "\n".join(commands))
        return commands
