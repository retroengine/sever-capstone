"""The map screen: the data, your own records, the holding area, deletion and search."""

import json
from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from .. import layout
from ..actions import Added, Deleted
from ..backend import HOLDING, Inserted
from . import theme
from .host import Host
from .map_view import Bucket, HoverCard, MapView
from .widgets import Card, badge, button, label


def routing_reason(placement: str, flushed: bool) -> str:
    if flushed:
        return (
            f"It was the record that filled the holding area: all of them flushed into the new "
            f"group {placement} (§7.4)."
        )
    if placement.startswith("frozen-"):
        return (
            f"In distribution: close enough to its nearest frozen group's centroid, so it joined "
            f"{placement} (§7.1–7.3)."
        )
    if placement.startswith("spawn-"):
        return (
            f"Out of distribution for every frozen group, so it spilled into the nearest spawned "
            f"group with room, {placement} (§7.3)."
        )
    return (
        "Out of distribution, and no spawned group had room: it waits in the holding area, stored "
        "and deletable but not searchable, until the area flushes (§7.3–7.4)."
    )


class MapScreen(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        s = host.studio
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # the bar: search and the legend
        bar = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText(
            "Ask a question: type it, or #number for one of the dataset's questions"
            if s.data == "nq"
            else "Ask: #number picks one of the fixture's questions"
        )
        self.query.returnPressed.connect(self.ask)
        bar.addWidget(self.query, 1)
        bar.addWidget(button("Search", "primary", self.ask))
        bar.addWidget(button("Clear", "", self.clear_search))
        bar.addSpacing(14)
        bar.addWidget(badge("● frozen group", theme.ACCENT))
        bar.addWidget(badge("○ spawned group", "#c9a2ff"))
        bar.addWidget(badge("★ yours", theme.YOURS_RING))
        bar.addWidget(badge("2D map: an approximation of 384-D distances", theme.MUTED))
        root.addLayout(bar)

        mid = QHBoxLayout()
        mid.setSpacing(10)
        self.map = MapView(s)
        self.map.hovered.connect(self.on_hover)
        self.map.clicked.connect(self.on_click)
        mid.addWidget(self.map, 1)
        self.bucket = Bucket(s.corpus.spawn_target)
        self.bucket.setFixedWidth(180)
        left_of_panel = QVBoxLayout()
        left_of_panel.addWidget(self.bucket, 1)
        left_of_panel.addWidget(button("One record into it", "", lambda: self.fill("one")))
        left_of_panel.addWidget(button("Fill until it flushes", "", lambda: self.fill("flush")))
        left_of_panel.addWidget(button("Search for one", "", self.search_waiting))
        bw = QWidget()
        bw.setLayout(left_of_panel)
        bw.setFixedWidth(186)
        mid.addWidget(bw)

        # the side panel
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 4, 0)
        sl.setSpacing(10)
        self.form = Card(
            "Add your details",
            "Type anything. It is encoded by the pinned model, signed with your account's key and "
            "stored encrypted.",
        )
        self.account = QLineEdit()
        self.account.setPlaceholderText("your name (the account)")
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("what to store, e.g. a note about yourself")
        self.text.setFixedHeight(84)
        self.form.add(self.account)
        self.form.add(self.text)
        self.form.add(button("Add to the database", "primary", self.add))
        self.callout = label("", wrap=True)
        self.form.add(self.callout)
        sl.addWidget(self.form)

        self.sel = Card("Selected", "Click a point on the map.")
        self.sel_title = label("", "h3", wrap=True)
        self.sel_info = label("", "muted", wrap=True)
        self.sel.add(self.sel_title)
        self.sel.add(self.sel_info)
        row = QHBoxLayout()
        self.b_delete = button("Delete this record", "danger", self.delete_selected)
        self.b_forget = button("Forget the account", "danger", self.forget_selected)
        row.addWidget(self.b_delete)
        row.addWidget(self.b_forget)
        self.sel.body.addLayout(row)
        row2 = QHBoxLayout()
        self.b_group = button("Show only its group", "", self.toggle_group)
        self.b_again = button("Delete it again", "", self.delete_again)
        row2.addWidget(self.b_group)
        row2.addWidget(self.b_again)
        self.sel.body.addLayout(row2)
        self.b_again.setEnabled(False)
        sl.addWidget(self.sel)

        self.results = Card("Search results", "")
        self.res_q = label("", "h3", wrap=True)
        self.res_list = QListWidget()
        self.res_list.setMinimumHeight(200)
        self.results.add(self.res_q)
        self.results.add(self.res_list)
        self.results.add(button("Search quality over every question", "", self.quality))
        sl.addWidget(self.results)
        sl.addStretch(1)
        scroll = QScrollArea()
        side.setFixedWidth(312)
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(330)
        mid.addWidget(scroll)
        root.addLayout(mid, 1)

        tools = QHBoxLayout()
        tools.addWidget(button("Replay the preparation", "", self.replay))
        tools.addStretch(1)
        self.status = label("", "muted")
        tools.addWidget(self.status)
        root.addLayout(tools)

        self.card = HoverCard(self.map)
        self.last_deleted: str | None = None
        self.update_select(None)
        self.redraw()

    # -- drawing ----------------------------------------------------------------------------------

    def redraw(self) -> None:
        b = self.host.studio.backend
        self.map.refresh()
        mine = {r for r, rec in b.index.records.items() if rec.mine}
        self.bucket.set(b.index.holding, mine)
        groups = {rec.group for rec in b.index.records.values() if rec.group != HOLDING}
        self.status.setText(
            f"{len(b.index.records):,} live records · {len(groups)} groups ·"
            f" {len(b.index.holding)} in the holding area · {len(b.index.receipts)} certificates"
        )

    def arrive(self, **kw: Any) -> None:
        self.redraw()

    # -- hover and selection ----------------------------------------------------------------------

    def on_hover(self, rid: str | None) -> None:
        if rid is None:
            self.card.hide()
            return
        first = "hover" not in self.host.studio.checklist.verdicts
        info = self.host.studio.hover(rid)
        if not info:
            return
        self.card.show_for(info, self.map.palette.colour(str(info["group"])))
        px, py = self.host.studio.xy(rid)
        pos = self.map.mapFromScene(self.map.vb.mapViewToScene(QPointF(px, py)))
        x = (
            pos.x() + 18
            if pos.x() + 18 + self.card.width() < self.map.width()
            else pos.x() - 18 - self.card.width()
        )
        y = min(max(8, pos.y() - 40), max(8, self.map.height() - self.card.height() - 8))
        self.card.move(max(8, x), y)
        if first:
            self.host.changed()

    def on_click(self, rid: str | None) -> None:
        self.map.select(rid)
        self.update_select(rid)

    def update_select(self, rid: str | None) -> None:
        b = self.host.studio.backend
        rec = b.index.records.get(rid) if rid else None
        self.b_delete.setEnabled(rec is not None)
        self.b_forget.setEnabled(rec is not None)
        self.b_group.setEnabled(rec is not None)
        if rec is None or rid is None:
            self.sel_title.setText("")
            self.sel_info.setText("Nothing selected.")
            return
        size = sum(1 for r in b.index.records.values() if r.group == rec.group)
        mine = len(b.accounts().get(rec.account, []))
        self.sel_title.setText(rid + ("  (yours)" if rec.mine else ""))
        self.sel_info.setText(
            f"account {rec.account} ({mine} live record{'s' if mine != 1 else ''})\n"
            f"group {rec.group}: {size} records"
        )
        self.b_forget.setText(f"Forget the account ({mine})")

    def toggle_group(self) -> None:
        rid = self.map.selected
        rec = self.host.studio.backend.index.records.get(rid) if rid else None
        self.map.focus(None if self.map.focus_group or rec is None else rec.group)
        self.b_group.setText("Show every group" if self.map.focus_group else "Show only its group")

    # -- adding -----------------------------------------------------------------------------------

    def add(self) -> None:
        account = self.account.text().strip()
        text = self.text.toPlainText().strip()
        if not account or not text:
            self.host.toast("Type a name and some text first.", theme.WARN)
            return
        self.callout.setText("encoding, signing, inserting…")
        self.host.worker.submit(
            lambda: self.host.studio.add_mine(account, text), self.added, self.host.error
        )

    def added(self, a: Added) -> None:
        r = a.result
        flushed = r.flush is not None
        self.callout.setText(
            f"<b>{a.rid}</b> stored at log position {r.lsn}.<br>"
            f"{routing_reason(r.placement, flushed)}<br><span style='color:{theme.MUTED}'>"
            f"Nearest passages: {', '.join(a.neighbours)}</span>"
        )
        self.text.clear()
        if r.placement == HOLDING:
            self.redraw()
            self.bucket.flash()
        elif r.flush is not None:
            self._flushed(r)
        else:
            x, y = a.xy
            c = self.map.palette.colour(r.placement)
            self.redraw()
            self.map.arrive(x, y, c, lambda: None)
            self.map.select(a.rid)
            self.update_select(a.rid)
        self.host.changed()

    def _flushed(self, r: Inserted) -> None:
        f = r.flush
        if f is None:
            return
        self.bucket.flash()
        b = self.host.studio.backend
        mine = {m for m, rec in b.index.records.items() if rec.mine}
        self.bucket.set(f.members, mine)

        def landed() -> None:
            self.redraw()
            self.host.toast(
                f"The holding area flushed: {len(f.members)} records became the new group "
                f"{f.group}. Its ID, recomputed from the members (§7.5): {f.expected} "
                + ("✓ matches." if f.id_matches else "✗ DIFFERS."),
                theme.OK if f.id_matches else theme.BAD,
            )

        def go() -> None:
            self.bucket.set([], mine)
            self.map.fly(f.members, f.group, landed)

        QTimer.singleShot(500, go)

    def fill(self, until: str) -> None:
        s = self.host.studio
        mine = {m for m, rec in s.backend.index.records.items() if rec.mine}

        def progress(a: tuple[Any, ...]) -> None:
            self.bucket.set(s.backend.index.holding, mine)

        def done(out: list[Inserted]) -> None:
            if not out:
                self.host.toast("No passages are left to insert.", theme.WARN)
                return
            last = out[-1]
            if last.flush is not None:
                self._flushed(last)
            else:
                self.redraw()
                self.host.toast(
                    f"{len(out)} passages inserted; the last went to {last.placement}.",
                    theme.ACCENT,
                )
            self.host.changed()

        self.host.worker.submit(
            lambda report: s.fill_bucket(until, progress=lambda *a: report(*a)),
            done,
            self.host.error,
            progress,
        )

    # -- deleting ---------------------------------------------------------------------------------

    def _points(self, rids: list[str]) -> list[tuple[float, float, QColor]]:
        b = self.host.studio.backend
        out = []
        for r in rids:
            rec = b.index.records.get(r)
            if rec is not None and rec.group != HOLDING:
                x, y = self.host.studio.xy(r)
                out.append((x, y, self.map.palette.colour(rec.group)))
        return out

    def delete_selected(self) -> None:
        rid = self.map.selected
        if rid:
            self.delete([rid], "delete")

    def forget_selected(self) -> None:
        rid = self.map.selected
        rec = self.host.studio.backend.index.records.get(rid) if rid else None
        if rec is not None:
            self.delete(self.host.studio.backend.accounts()[rec.account], "forget", rec.account)

    def delete(self, rids: list[str], kind: str, account: str = "") -> None:
        s = self.host.studio
        points = self._points(rids)
        accounts = {
            r: s.backend.index.records[r].account for r in rids if r in s.backend.index.records
        }

        def run() -> Deleted:
            return s.forget(account) if kind == "forget" else s.delete(rids)

        def done(d: Deleted) -> None:
            for rid, lsn in zip(d.rids, d.lsns, strict=False):
                self.host.receipts_of[lsn] = (rid, accounts.get(rid, ""))
            self.last_deleted = d.rids[0] if d.rids else None
            self.map.select(None)
            self.update_select(None)
            self.b_again.setEnabled(self.last_deleted is not None)
            groups = ", ".join(
                f"{g} {d.groups_before[g]} → {d.groups_after[g]}" for g in d.groups_before
            )

            def after() -> None:
                self.redraw()
                self.host.toast(
                    f"{'Forgot ' + account + ': ' if kind == 'forget' else ''}{len(d.rids)} deleted"
                    f" ({groups}); {len(d.lsns)} certificate{'s' if len(d.lsns) != 1 else ''}."
                    f" Total {d.total_before:,} → {d.total_after:,}.",
                    theme.OK if d.ok else theme.BAD,
                    "Check the receipt",
                    lambda: self.host.go("receipt", lsn=d.lsns[-1]) if d.lsns else None,
                )
                self.host.changed()

            self.map.vanish(points, after)

        self.host.worker.submit(run, done, self.host.error)

    def delete_again(self) -> None:
        rid = self.last_deleted
        if rid is None:
            return

        def done(ok: bool) -> None:
            self.host.toast(
                f'Deleting {rid} again: "absent". Nothing was subtracted and nothing changed'
                " (§5.4)."
                if ok
                else f"Deleting {rid} again did not behave as §5.4 says.",
                theme.OK if ok else theme.BAD,
            )
            self.host.changed()

        self.host.worker.submit(lambda: self.host.studio.delete_again(rid), done, self.host.error)

    # -- search -----------------------------------------------------------------------------------

    def ask(self) -> None:
        s = self.host.studio
        q = self.query.text().strip()
        if not q:
            return
        question: int | str
        if q.lstrip("#").isdigit():
            question = int(q.lstrip("#")) % max(1, len(s.corpus.questions))
        elif s.data == "synthetic":
            self.host.toast("The offline fixture has no encoder: use #number.", theme.WARN)
            return
        else:
            question = q

        def run() -> tuple[str, list[tuple[str, float, bool]], tuple[float, float]]:
            text, hits = s.ask(question)
            vec = (
                s.corpus.question_vectors[question]
                if isinstance(question, int)
                else s.encode(question)
            )
            return text, hits, layout.place(np.asarray(vec, np.float32), s.corpus.vectors, s.coords)

        def done(out: tuple[str, list[tuple[str, float, bool]], tuple[float, float]]) -> None:
            text, hits, origin = out
            self.map.show_beam(origin, hits)
            self.res_q.setText(f"“{text}”")
            self.res_list.clear()
            for rank, (rid, dist, good) in enumerate(hits, 1):
                t = s.backend.text_of(rid).replace("\n", " ")
                snip = t if len(t) <= 90 else t[:89] + "…"
                item = QListWidgetItem(
                    f"{rank}. {'✓ ' if good else ''}{rid}  ({dist:.3f})\n   {snip}"
                )
                if good:
                    item.setForeground(QColor(theme.OK))
                self.res_list.addItem(item)
            if not hits:
                self.res_list.addItem("nothing found")

        self.host.worker.submit(run, done, self.host.error)

    def clear_search(self) -> None:
        self.map.clear_beam()
        self.res_list.clear()
        self.res_q.setText("")

    def quality(self) -> None:
        def done(out: tuple[int, int, int, float]) -> None:
            n, at1, at10, ms = out
            self.host.toast(
                f"{n} questions have their judged answer stored: first for {at1}, in the top 10 for"
                f" {at10} ({ms:.2f} ms per search).",
                theme.OK,
            )
            self.host.changed()

        self.host.worker.submit(self.host.studio.search_quality, done, self.host.error)

    def search_waiting(self) -> None:
        def done(out: tuple[str | None, bool, bool]) -> None:
            rid, found, stored = out
            if rid is None:
                self.host.toast(
                    "The holding area is empty: put one record into it first.", theme.WARN
                )
                return
            self.host.toast(
                f"{rid} waits in the holding area. Stored: {'yes' if stored else 'no'}. Found by a"
                f" search with its own vector: {'yes' if found else 'no'} (§7.4: not searchable"
                " until it flushes).",
                theme.OK if stored and not found else theme.BAD,
            )
            self.host.changed()

        self.host.worker.submit(self.host.studio.unsearchable, done, self.host.error)

    # -- replay -----------------------------------------------------------------------------------

    def replay(self) -> None:
        """The preparation again, fast: each record appears where it landed, the bucket fills and
        flushes, exactly as the receipts of the real run recorded (``prepare-events.jsonl``)."""
        path = self.host.studio.work / "prepare-events.jsonl"
        if not path.exists():
            self.host.toast("No preparation was recorded in this work directory.", theme.WARN)
            return
        events = [json.loads(ln) for ln in path.read_text("utf-8").splitlines()]
        live = self.host.studio.backend.index.records
        where: dict[str, str] = {}
        holding: list[str] = []
        step = max(1, len(events) // 160)
        state = {"i": 0}
        view = self.map

        def tick() -> None:
            i = state["i"]
            for e in events[i : i + step]:
                rid, placement = e["rid"], e["placement"]
                if "flush" in e:
                    for m in holding:
                        where[m] = placement
                    holding.clear()
                    self.bucket.flash()
                if placement == HOLDING:
                    holding.append(rid)
                else:
                    where[rid] = placement
            state["i"] = i + step
            shown = [r for r in where if r in live or r in self.host.studio.corpus.position]
            xy = np.array([self.host.studio.xy(r) for r in shown], np.float64).reshape(-1, 2)
            brushes = [view.palette.colour(where[r]) for r in shown]
            view.base.setData(pos=xy, brush=brushes, pen=None, size=6)
            self.bucket.set(holding, set())
            self.status.setText(
                f"replay: {min(state['i'], len(events)):,} / {len(events):,} inserts"
            )
            if state["i"] >= len(events):
                timer.stop()
                QTimer.singleShot(900, self.redraw)

        timer = QTimer(self)
        timer.timeout.connect(tick)
        view.base.setData(pos=np.zeros((0, 2)))
        timer.start(30)
        self._replay = timer

    def hideEvent(self, event: Any) -> None:  # noqa: N802 (Qt's name)
        if isValid(self.card):  # at shutdown the card can go first
            self.card.hide()
        super().hideEvent(event)

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802 (Qt's name)
        if event.key() == Qt.Key.Key_Escape:
            self.on_click(None)
            self.clear_search()
        super().keyPressEvent(event)
