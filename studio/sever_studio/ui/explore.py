"""Explore: the map fills the screen; everything else floats on it.

Search at the top, the legend at the top left, the holding area as a gauge on the right, "Add
yourself" at the bottom left, and a small sheet at the bottom when a dot is selected.
"""

import json
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from .. import explain, layout
from ..actions import Added, Deleted
from ..backend import HOLDING, Inserted
from . import copy, theme
from .host import Host
from .map3d import Map3D
from .map_view import Bucket, GroupCard, HoverCard, MapView
from .widgets import Flow, Heatmap, Verdict, button, chip, info, label, lift

#: a search's question, its hits, where it is drawn, and how the engine searched (§8.1)
Found = tuple[str, list[tuple[str, float, bool]], tuple[float, float], dict[str, Any]]


def floating(vertical: bool = True, margin: int = 12) -> tuple[QFrame, QVBoxLayout | QHBoxLayout]:
    f = QFrame()
    f.setObjectName("float")
    lift(f)
    lay: QVBoxLayout | QHBoxLayout = QVBoxLayout(f) if vertical else QHBoxLayout(f)
    lay.setContentsMargins(margin, margin - 2, margin, margin - 2)
    lay.setSpacing(8)
    return f, lay


def route_key(placement: str, flushed: bool) -> str:
    if flushed:
        return "route.flush"
    if placement.startswith("frozen-"):
        return "route.frozen"
    if placement.startswith("spawn-"):
        return "route.spawn"
    return "route.holding"


class Explore(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        s = host.studio
        self.map = MapView(s)
        self.map.setParent(self)
        self.map.hovered.connect(self.on_hover)
        self.map.clicked.connect(self.on_click)
        # the 3-D mode, beside the 2-D map (the owner, 23 Oct 2026); 2-D is the default
        self.mode = "2d"
        self.map3d = Map3D(s, self.map)
        self.map3d.setParent(self)
        self.map3d.hide()

        # the search, top centre
        self.search, sl = floating(vertical=False, margin=6)
        self.query = QLineEdit()
        self.query.setObjectName("search")
        self.query.setPlaceholderText(
            "Ask a question, or #12" if s.data == "nq" else "Pick a question: #0 … #11"
        )
        self.query.returnPressed.connect(self.ask)
        sl.addWidget(self.query, 1)
        sl.addWidget(button("", "primary", self.ask, "search", "Search"))
        sl.addWidget(button("", "ghost", self.clear_search, "x", "Clear"))

        # the legend, top left
        self.legend, ll = floating(vertical=False, margin=8)
        ll.addWidget(chip("● frozen group", theme.MUTED))
        ll.addWidget(chip("■ spawned group", theme.MUTED))
        ll.addWidget(chip("✕ centre μ", theme.TEXT))
        ll.addWidget(chip("★ yours", theme.WARN if theme.LIGHT else theme.YOURS_RING))
        self.b2d = button("2-D", "ghost", lambda: self.set_mode("2d"), tip="The flat map")
        self.b3d = button("3-D", "ghost", lambda: self.set_mode("3d"), tip="Turn it in 3-D")
        for b in (self.b2d, self.b3d):
            b.setCheckable(True)
            ll.addWidget(b)
        self.b2d.setChecked(True)
        self.colour_all = button("Colour every group", "ghost", self.toggle_colours, "layers")
        self.colour_all.setCheckable(True)
        ll.addWidget(self.colour_all)
        ll.addWidget(info("map.about"))

        # the search results, under the legend
        self.results, rl = floating()
        head = QHBoxLayout()
        self.res_q = label("", "strong", wrap=True)
        head.addWidget(self.res_q, 1)
        head.addWidget(button("", "ghost", self.clear_search, "x", "Close"))
        rl.addLayout(head)
        self.res_list = QListWidget()
        self.res_list.setMinimumHeight(150)
        self.res_list.itemClicked.connect(self._pick_result)
        rl.addWidget(self.res_list)
        self.res_quality = Verdict()
        rl.addWidget(self.res_quality)
        rl.addWidget(button("Check every question", "ghost", self.quality))
        self.results.hide()

        # the holding area, right
        self.gauge, gl = floating(margin=8)
        gl.addWidget(info("bucket"), alignment=Qt.AlignmentFlag.AlignRight)
        self.bucket = Bucket(s.corpus.spawn_target)
        gl.addWidget(self.bucket, 1)
        gl.addWidget(button("", "", lambda: self.fill("one"), "plus", "Put one record into it"))
        gl.addWidget(
            button("", "", lambda: self.fill("flush"), "layers", "Fill it until it flushes")
        )
        gl.addWidget(button("", "", self.search_waiting, "search", "Search for a waiting record"))

        # add yourself, bottom left
        self.fab = button(" " + copy.short("add"), "fab", self.toggle_add, "plus")
        self.add_panel, al = floating()
        ah = QHBoxLayout()
        ah.addWidget(label(copy.short("add"), "strong"), 1)
        ah.addWidget(info("add"))
        al.addLayout(ah)
        self.account = QLineEdit()
        self.account.setPlaceholderText("Your name")
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Something about you")
        self.text.setFixedHeight(64)
        al.addWidget(self.account)
        al.addWidget(self.text)
        al.addWidget(button("Add", "primary", self.add))
        self.add_result = Verdict()
        al.addWidget(self.add_result)
        self.add_panel.hide()

        # the selected record, a panel on the right: everything about it, then what to do
        self.sheet, shl = floating(vertical=True)
        self.sheet.setObjectName("card")  # opaque: the map must not show through the text
        head = QHBoxLayout()
        self.sel = label("", wrap=True)
        head.addWidget(self.sel, 1)
        head.addWidget(button("", "ghost", lambda: self.on_click(None), "x", "Close"))
        shl.addLayout(head)
        self.sel_text = QLabel()
        self.sel_text.setWordWrap(True)
        self.sel_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.sel_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        # the text, its numbers and how it got here (or what its deletion did), scrolled together
        inside = QWidget()
        il = QVBoxLayout(inside)
        il.setContentsMargins(0, 0, 6, 0)
        il.setSpacing(8)
        il.addWidget(self.sel_text)
        self.sel_heat = Heatmap(cols=48)
        il.addWidget(self.sel_heat)
        self.sel_nums = label("", "mono", wrap=True)
        il.addWidget(self.sel_nums)
        self.flow = Flow(vertical=True)
        il.addWidget(self.flow)
        il.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inside)
        shl.addWidget(scroll, 1)
        self.b_delete = button("Delete", "danger", self.delete_selected, "trash")
        self.b_forget = button("Forget", "danger", self.forget_selected, "forget")
        self.b_group = button("Group", "", self.toggle_group, "layers", "Show only its group")
        self.b_receipt = button("Receipt", "primary", self.open_receipt, "receipt")
        self.b_again = button("Delete again", "", self.delete_again, "refresh")
        acts = QHBoxLayout()
        for b in (self.b_delete, self.b_forget, self.b_group, self.b_receipt, self.b_again):
            acts.addWidget(b)
        acts.addStretch(1)
        shl.addLayout(acts)
        self.sheet.hide()

        # a group's numbers, when its centre is hovered
        self.gcard = GroupCard(self)
        self.map.group_hovered.connect(self.on_group_hover)
        self.map.group_clicked.connect(self.select_group)

        # the status, bottom right
        self.status = label("", "small")
        self.replay_btn = button("Replay", "ghost", self.replay, "play", "Replay the preparation")
        self.caption = label(copy.short("map.caption"), "small")

        # the welcome card
        self.welcome, wl = floating(margin=18)
        wl.addWidget(label(copy.short("welcome"), "heading"))
        for n, step in enumerate(
            ("Hover a dot to read it", "Add yourself with  +", "Click your ★, then Delete"), 1
        ):
            wl.addWidget(label(f"<b style='color:{theme.ACCENT}'>{n}</b>&nbsp;&nbsp;{step}"))
        wl.addWidget(button("Got it", "primary", self.dismiss_welcome))
        self.welcome.setVisible(not self._ui_state().get("welcomed", False))

        self.card = HoverCard(self)
        for w in (
            self.search,
            self.legend,
            self.results,
            self.gauge,
            self.fab,
            self.add_panel,
            self.sheet,
            self.status,
            self.caption,
            self.replay_btn,
            self.welcome,
        ):
            w.setParent(self)
        self.last_deleted: str | None = None
        self.last_lsn: int | None = None
        self.redraw()

    # -- layout -----------------------------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        self.place()

    def place(self) -> None:
        w, h = self.width(), self.height()
        self.map.setGeometry(0, 0, w, h)
        self.map3d.setGeometry(0, 0, w, h)
        sw = min(520, max(260, w - 420))
        sh = self.search.sizeHint().height()
        self.legend.adjustSize()
        # the search beside the legend when there is room, else the legend under it
        x0 = max((w - sw) // 2, 24 + self.legend.width())
        if w - 12 - x0 >= 260:
            self.search.setGeometry(x0, 12, min(sw, w - 12 - x0), sh)
            self.legend.move(12, 12)
            top = 70
        else:
            self.search.setGeometry((w - sw) // 2, 12, sw, sh)
            self.legend.move(12, 20 + sh)
            top = 28 + sh + self.legend.height()
        gw = 116
        gh = max(260, min(int(h * 0.62), h - 140))
        self.gauge.setGeometry(w - gw - 12, 70, gw, gh)
        self.results.setGeometry(12, top, min(320, w // 3), min(360, h - 140 - top))
        self.fab.adjustSize()
        self.fab.move(16, h - self.fab.height() - 16)
        pw = min(320, w - 32)
        self.add_panel.setFixedWidth(pw)
        self.add_panel.adjustSize()
        self.add_panel.move(16, h - self.fab.height() - self.add_panel.height() - 26)
        self.status.adjustSize()
        self.replay_btn.adjustSize()
        self.caption.adjustSize()
        right = w - self.replay_btn.width() - 12
        self.replay_btn.move(right, h - self.replay_btn.height() - 12)
        self.status.move(right - self.status.width() - 8, h - self.status.height() - 18)
        self.caption.move(right - self.caption.width() - 8, h - self.status.height() - 36)
        # the selected record's panel: on the right, over the gauge, above the bottom row
        pw = max(300, min(440, int(w * 0.36)))
        self.sheet.setGeometry(w - pw - 12, 70, pw, max(240, h - 70 - 60))
        self.gauge.setVisible(not self.sheet.isVisible())
        self.welcome.adjustSize()
        self.welcome.move((w - self.welcome.width()) // 2, (h - self.welcome.height()) // 2)
        for f in (
            self.search,
            self.legend,
            self.results,
            self.gauge,
            self.add_panel,
            self.sheet,
            self.welcome,
        ):
            f.raise_()
        self.card.raise_()

    def _ui_state(self) -> dict[str, Any]:
        path = self.host.studio.work / "ui.json"
        try:
            data = json.loads(path.read_text("utf-8")) if path.exists() else {}
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    def dismiss_welcome(self) -> None:
        state = self._ui_state()
        state["welcomed"] = True
        (self.host.studio.work / "ui.json").write_text(json.dumps(state), "utf-8")
        self.welcome.hide()

    # -- drawing ----------------------------------------------------------------------------------

    def redraw(self) -> None:
        b = self.host.studio.backend
        if isValid(self.card):
            self.card.hide()
        self.map.refresh()
        if self.mode == "3d":
            self.map3d.refresh()
        mine = {r for r, rec in b.index.records.items() if rec.mine}
        self.bucket.set(b.index.holding, mine)
        sizes = b.group_sizes()
        empty = sum(1 for _, n in sizes if n == 0)
        self.status.setText(
            f"{len(b.index.records):,} records · {len(sizes)} groups ({empty} empty) · "
            f"{self.host.studio.spares_left():,} spare passages"
        )
        self.place()

    def arrive(self, **kw: Any) -> None:
        self.redraw()

    def show_any(self) -> str | None:
        """Opens the card of the dot nearest the middle of the map (the tour's "Do it")."""
        if not len(self.map.rids):
            return None
        mid = self.map.xy.mean(axis=0)
        rid = self.map.rids[int(((self.map.xy - mid) ** 2).sum(axis=1).argmin())]
        self.on_hover(rid)
        return rid

    def focus_search(self) -> None:
        self.query.setFocus()
        self.query.selectAll()

    # -- hover and selection ----------------------------------------------------------------------

    def on_hover(self, rid: str | None) -> None:
        if rid is None or not isValid(self.card):
            if isValid(self.card):
                self.card.hide()
            return
        first = "hover" not in self.host.studio.checklist.verdicts
        info_ = self.host.studio.hover(rid)
        if not info_:
            return
        self.card.show_for(info_, self.map.colour(str(info_["group"])))
        p = self.map.to_widget(*self.host.studio.xy(rid))
        x = (
            p.x() + 16
            if p.x() + 16 + self.card.width() < self.width() - 130
            else p.x() - 16 - self.card.width()
        )
        y = min(max(64.0, p.y() - 30), self.height() - self.card.height() - 12)
        self.card.move(int(max(8, x)), int(y))
        if first:
            self.host.changed()

    def on_click(self, rid: str | None) -> None:
        self.map.select(rid)
        self.welcome.hide()
        b = self.host.studio.backend
        rec = b.index.records.get(rid) if rid else None
        if rec is None or rid is None:
            self.sheet.hide()
            self.place()
            return
        n = len(b.accounts().get(rec.account, []))
        c = self.map.colour(rec.group).name()
        self.sel.setText(
            f"<b>{rid}</b>{'  ★' if rec.mine else ''}<br>"
            f"<span style='color:{theme.MUTED}'>{rec.account} · </span>"
            f"<span style='color:{c}'>{rec.group}</span>"
        )
        self.sel_text.setText(b.text_of(rid))
        x = b.vector_of(rid).astype(np.float64)
        self.sel_heat.set(x)
        self.sel_heat.show()
        why = self.host.studio.why(rid)
        q = why["x_tilde"] if why is not None else np.rint(x * 2**24).astype(np.int64)
        lines = [
            f"x  = [{', '.join(f'{v:.5f}' for v in x[:3])}, … {len(x)} numbers]",
            f"x̃ = round(x · 2²⁴) = [{', '.join(f'{v:,}' for v in q[:3])}, …]"
            + ("" if why is not None else "  (Studio's §4.2 arithmetic)"),
        ]
        if why is not None:
            j, d = why["nearest"][0]
            inside = why["in_distribution"]
            lines.append(f"nearest frozen centre: frozen-{j:04d}, D = Σ(x̂ − μ)² = {d:.4f}")
            lines.append(
                f"d_M = {why['d_m']:.3f} {'≤' if inside else '>'} τ = {why['tau']:.3f}: "
                + ("in distribution (§7.2)" if inside else "out of distribution (§7.2–7.3)")
            )
            lines.append("computed by the engine's own routing code (DB-108)")
        if rec.group == HOLDING:
            lines.append("waiting in the bucket: in no group yet (§7.4)")
        self.sel_nums.setText("\n".join(lines))
        self.flow.set(explain.insert_flow(self.host.studio, rid), delay=220)
        self.b_forget.setText(f"Forget ({n})")
        self._sheet(mode="selected")

    def _sheet(self, mode: str) -> None:
        selected = mode == "selected"
        for b in (self.b_delete, self.b_forget, self.b_group):
            b.setVisible(selected)
        for b in (self.b_receipt, self.b_again):
            b.setVisible(not selected)
        self.sheet.show()
        self.place()

    def on_group_hover(self, group: str | None) -> None:
        self.map.hover(group)
        if group is None or not isValid(self.gcard):
            if isValid(self.gcard):
                self.gcard.hide()
            return
        s = self.host.studio
        self.gcard.show_for(s.group_card(group), self.map.colour(group))
        at = s.centre_xy(group)
        if at is None:
            return
        p = self.map.to_widget(*at)
        right = p.x() + 18 + self.gcard.width() < self.width() - 12
        gx = p.x() + 18 if right else p.x() - 18 - self.gcard.width()
        gy = min(max(64.0, p.y() - 40), self.height() - self.gcard.height() - 12)
        self.gcard.move(int(max(8, gx)), int(gy))

    def toggle_colours(self) -> None:
        """Spawned groups in their own colours too: each is a batch of records that waited together
        (§7.4), so its colour is scattered over the map."""
        self.map.set_colour_all(self.colour_all.isChecked())
        self.map3d.refresh()

    def set_mode(self, mode: str) -> None:
        """2-D or 3-D: the same records, colours and lit group. The 3-D layout is made on the worker
        the first time (t-SNE with three axes; minutes on NQ), then kept."""
        three = mode == "3d"
        self.mode = mode
        self.b2d.setChecked(not three)
        self.b3d.setChecked(three)
        self.map.setVisible(not three)
        self.map3d.setVisible(three)
        self.caption.setText(copy.short("map.caption3" if three else "map.caption"))
        s = self.host.studio
        if three and s.coords3 is None:
            if not self.map3d.reason:
                self.map3d.note.setText(copy.short("map.laying3"))
                self.map3d.note.show()
            self.host.worker.submit(s.layout3, lambda _: self._laid3(), self.host.error)
        elif three:
            self.map3d.refresh()
        self.place()

    def _laid3(self) -> None:
        if not self.map3d.reason:
            self.map3d.note.hide()
        self.map3d.refresh()

    def select_group(self, group: str) -> None:
        """A centre clicked: its members light up wherever they lie (a frozen group's around its
        centre, a spawned group's scattered: a batch, not a cluster, §7.4)."""
        self.map.focus(None if self.map.focus_group == group else group)
        self.map3d.refresh()
        if self.map.focus_group:
            n = dict(self.host.studio.backend.group_sizes())
            kind = "frozen" if group.startswith("frozen-") else "spawned"
            self.host.toast(f"{group}: its {n.get(group, 0):,} records lit ({kind} group)", None)

    def toggle_group(self) -> None:
        rid = self.map.selected
        rec = self.host.studio.backend.index.records.get(rid) if rid else None
        self.map.focus(None if self.map.focus_group or rec is None else rec.group)
        self.b_group.setText("All" if self.map.focus_group else "Group")

    # -- adding -----------------------------------------------------------------------------------

    def toggle_add(self) -> None:
        self.add_panel.setVisible(not self.add_panel.isVisible())
        self.welcome.hide()
        if self.add_panel.isVisible():
            self.place()
            self.account.setFocus()

    def add(self) -> None:
        account = self.account.text().strip()
        text = self.text.toPlainText().strip()
        if not account or not text:
            self.add_result.set(False, "Type a name and some text.")
            return
        self.add_result.set(None, "Adding…")
        self.host.worker.submit(
            lambda: self.host.studio.add_mine(account, text), self.added, self.host.error
        )

    def added(self, a: Added) -> None:
        r = a.result
        key = route_key(r.placement, r.flush is not None)
        p = r.predicted
        if p is None:
            self.add_result.set(True, copy.short(key))
        elif not p["in_distribution"] and p["unknown"]:
            self.add_result.set(
                None,
                f"{copy.short(key)}: the engine put it in {r.placement}; its routing code cannot "
                f"say where: the centre of {len(p['unknown'])} spawned group(s) was lost with a "
                "killed process (§7.3)",
            )
        else:
            want = p["destination"]
            agree = want == r.placement or (want == HOLDING and r.flush is not None)
            sign = "≤" if p["in_distribution"] else ">"
            self.add_result.set(
                agree,
                f"{copy.short(key)}: the engine put it in {r.placement}; its routing code said "
                f"{want} (d_M {p['d_m']:.1f} {sign} τ {p['tau']:.1f})",
            )
        self.add_result.setToolTip(copy.long(key))
        self.text.clear()
        self.add_panel.hide()
        if r.flush is not None:
            self._flushed(r)
        elif r.placement == HOLDING:
            self.redraw()
            self.bucket.flash()
        else:
            self.redraw()
            self.map.arrive(*a.xy, self.map.colour(r.placement), lambda: None)
            self.on_click(a.rid)
        self.host.toast(f"{a.rid}: {copy.short(key).lower()}", True)
        self.host.changed()

    def _flushed(self, r: Inserted) -> None:
        f = r.flush
        if f is None:
            return
        self.bucket.flash()
        mine = {m for m, rec in self.host.studio.backend.index.records.items() if rec.mine}
        self.bucket.set(f.members, mine)

        def landed() -> None:
            self.redraw()
            self.host.toast(
                f"{len(f.members)} records became group {f.group}"
                + (" · ID checked ✓" if f.id_matches else " · ID DIFFERS"),
                f.id_matches,
            )

        def go() -> None:
            self.bucket.set([], mine)
            self.map.fly(f.members, f.group, landed)

        QTimer.singleShot(450, go)

    def fill(self, until: str) -> None:
        s = self.host.studio
        mine = {m for m, rec in s.backend.index.records.items() if rec.mine}

        def progress(a: tuple[Any, ...]) -> None:
            self.bucket.set(s.backend.index.holding, mine)

        def done(out: list[Inserted]) -> None:
            if not out:
                self.host.toast("No passages left to insert.", False)
                return
            last = out[-1]
            if last.flush is not None:
                self._flushed(last)
            else:
                self.redraw()
                self.host.toast(
                    f"{len(out)} inserted · the bucket holds {len(s.backend.index.holding)}", None
                )
            self.host.changed()

        self.host.worker.submit(
            lambda report: s.fill_bucket(until, progress=lambda *a: report(*a)),
            done,
            self.host.error,
            progress,
        )

    def search_waiting(self) -> None:
        def done(out: tuple[str | None, bool, bool]) -> None:
            rid, found, stored = out
            if rid is None:
                self.host.toast(
                    "The bucket is empty: put one record in first.",
                    False,
                    "Put one in",
                    lambda: self.fill("one"),
                )
                return
            ok = stored and not found
            self.host.toast(
                f"{rid}: stored, but search can't find it"
                if ok
                else f"{rid}: found by search (unexpected)",
                ok,
            )
            self.host.changed()

        self.host.worker.submit(self.host.studio.unsearchable, done, self.host.error)

    # -- deleting ---------------------------------------------------------------------------------

    def _points(self, rids: list[str]) -> list[tuple[float, float, QColor]]:
        b = self.host.studio.backend
        out = []
        for r in rids:
            rec = b.index.records.get(r)
            if rec is not None and rec.group != HOLDING:
                out.append((*self.host.studio.xy(r), self.map.colour(rec.group)))
        return out

    def delete_selected(self) -> None:
        if self.map.selected:
            self.delete([self.map.selected], "delete")

    def forget_selected(self) -> None:
        rid = self.map.selected
        rec = self.host.studio.backend.index.records.get(rid) if rid else None
        if rec is not None:
            self.delete(self.host.studio.backend.accounts()[rec.account], "forget", rec.account)

    def delete(self, rids: list[str], kind: str, account: str = "") -> None:
        s = self.host.studio
        points = self._points(rids)

        def run() -> Deleted:
            return s.forget(account) if kind == "forget" else s.delete(rids)

        def done(d: Deleted) -> None:
            self.last_deleted = d.rids[0] if d.rids else None
            self.last_lsn = d.lsns[-1] if d.lsns else None
            self.map.select(None)
            n = len(d.rids)
            what = (
                f"Forgot {account}"
                if kind == "forget"
                else f"Deleted {d.rids[0] if d.rids else ''}"
            )
            plural = "s" if n != 1 else ""
            receipts = f"{len(d.lsns)} receipt{'s' if len(d.lsns) != 1 else ''}"
            self.sel.setText(
                f"<b>{what}</b><br><span style='color:{theme.MUTED}'>{n} record{plural} · "
                f"{receipts} · total {d.total_after:,}</span>"
            )
            self.b_again.setVisible(kind == "delete")

            def after() -> None:
                self.redraw()
                self.sel_text.setText("")
                self.sel_nums.setText("")
                self.sel_heat.hide()
                self.flow.set(explain.delete_flow(s, d), delay=220)
                self._sheet(mode="deleted")
                self.b_again.setVisible(kind == "delete")
                self.host.toast(
                    f"{n} deleted · {len(d.lsns)} receipt{'s' if len(d.lsns) != 1 else ''}", d.ok
                )
                self.host.changed()

            self.map.vanish(points, after)

        self.host.worker.submit(run, done, self.host.error)

    def open_receipt(self) -> None:
        self.host.go("receipts", lsn=self.last_lsn)

    def delete_again(self) -> None:
        rid = self.last_deleted
        if rid is None:
            return

        def done(ok: bool) -> None:
            self.host.toast(
                'Again: "absent". Nothing changed.' if ok else "Delete again did not say absent", ok
            )
            self.host.changed()

        self.host.worker.submit(lambda: self.host.studio.delete_again(rid), done, self.host.error)

    # -- search -----------------------------------------------------------------------------------

    def ask(self) -> None:
        s = self.host.studio
        q = self.query.text().strip()
        if not q:
            return
        question: int | str | None
        named = any(a.strip().lower() == q.lower() for a in s.backend.accounts())
        if q.lstrip("#").isdigit():
            question = int(q.lstrip("#")) % max(1, len(s.corpus.questions))
        elif named and s.data == "synthetic":
            question = None  # the account's records only: the fixture has no encoder
        elif s.data == "synthetic":
            self.host.toast("The offline fixture has no encoder: use #number.", False)
            return
        else:
            question = q

        def run() -> Found:
            if question is None:
                return q, [], (0.0, 0.0), {}
            text, hits = s.ask(question)
            vec = np.asarray(
                s.corpus.question_vectors[question]
                if isinstance(question, int)
                else s.encode(question),
                np.float32,
            )
            how = s.search_explained(vec)
            return text, hits, layout.place(vec, s.corpus.vectors, s.coords), how

        def done(out: Found) -> None:
            text, hits, origin, how = out
            if hits:
                self.map.show_beam(origin, hits)
            else:
                self.map.clear_beam()
            self.res_q.setText(text)
            self.res_list.clear()
            # a person's name is not in any vector: their records come from the backend's list
            owners = s.backend.accounts()
            for name in [a for a in owners if a.strip().lower() == q.strip().lower()]:
                head = QListWidgetItem(
                    f"👤 {name}: {len(owners[name])} records (by account, not by meaning)"
                )
                head.setForeground(QColor(theme.ACCENT))
                head.setToolTip(
                    "A search compares meanings: the account's name is not in any vector. "
                    "Studio's backend knows who owns which record."
                )
                self.res_list.addItem(head)
                for rid in owners[name]:
                    t = " ".join(s.backend.text_of(rid).split())
                    where = s.backend.index.records[rid].group
                    item = QListWidgetItem(f"   {rid} · {where} · {t[:40]}")
                    item.setData(Qt.ItemDataRole.UserRole, rid)
                    self.res_list.addItem(item)
            if how:
                opened = {g for g, _ in how["ranked"][: how["probed"]]}
                inside = all(
                    s.backend.index.records[r].group in opened
                    for r, _, _ in hits
                    if r in s.backend.index.records
                )
                head = QListWidgetItem(
                    f"The engine ranked {len(how['ranked'])} groups by their centre and opened the "
                    f"nearest {how['probed']} (§8.1)"
                    + ("; every hit is from one ✓" if inside else "")
                )
                head.setForeground(QColor(theme.MUTED))
                head.setToolTip(
                    "Groups are ranked by Σ(q − μ)² to their centre; a quarter of them, rounded up "
                    "and empty ones included, are opened and their records scored. The bucket is "
                    "never searched."
                )
                self.res_list.addItem(head)
            for rank, (rid, score, good) in enumerate(hits[:8], 1):
                t = " ".join(s.backend.text_of(rid).split())
                item = QListWidgetItem(
                    f"{rank}  {score:.3f}  {'✓ ' if good else ''}{t[:52]}"
                    + ("…" if len(t) > 52 else "")
                )
                item.setToolTip(
                    f"{rid}\nscore Σ(q − x̂)² = {score:.5f}, from the engine (§8.2)\n{t[:400]}"
                )
                item.setData(Qt.ItemDataRole.UserRole, rid)
                if good:
                    item.setForeground(QColor(theme.OK))
                self.res_list.addItem(item)
            if not hits and question is not None:
                self.res_list.addItem("Nothing found")
            waiting = [r for r in s.backend.index.holding if s.backend.index.records[r].mine]
            if waiting:  # §7.4: stored, deletable, but no search reaches the holding area
                note = QListWidgetItem(
                    f"⏳ {len(waiting)} of your records wait in the bucket: no search reaches "
                    "them until it flushes into a group"
                )
                note.setForeground(QColor(theme.WARN))
                note.setToolTip(copy.long("bucket"))
                self.res_list.addItem(note)
            self.results.show()
            self.welcome.hide()
            self.place()

        self.host.worker.submit(run, done, self.host.error)

    def _pick_result(self, item: QListWidgetItem) -> None:
        """A result clicked: its dot is selected, as if clicked on the map."""
        rid = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(rid, str) and rid in self.host.studio.backend.index.records:
            self.on_click(rid)

    def clear_search(self) -> None:
        self.map.clear_beam()
        self.results.hide()
        self.query.clear()

    def quality(self) -> None:
        def done(out: tuple[int, int, int, float]) -> None:
            n, at1, at10, _ = out
            self.res_quality.set(at10 > 0, f"{n:,} questions: first {at1:,}, top 10 {at10:,}")
            self.host.changed()

        self.res_quality.set(None, "Searching every question…")
        self.host.worker.submit(self.host.studio.search_quality, done, self.host.error)

    # -- replay -----------------------------------------------------------------------------------

    def replay(self) -> None:
        """The preparation again, fast: each record appears where its receipt said it landed; the
        bucket fills and flushes as it did (``prepare-events.jsonl``)."""
        path = self.host.studio.work / "prepare-events.jsonl"
        if not path.exists():
            self.host.toast("No preparation recorded here.", False)
            return
        events = [json.loads(ln) for ln in path.read_text("utf-8").splitlines()]
        corpus = self.host.studio.corpus.position
        holding: list[str] = []
        step = max(1, len(events) // 160)
        state = {"i": 0}
        view = self.map

        def tick() -> None:
            i = state["i"]
            placed: list[tuple[str, str]] = []
            for e in events[i : i + step]:
                if "flush" in e:
                    placed += [(m, e["placement"]) for m in holding]
                    holding.clear()
                    self.bucket.flash()
                if e["placement"] == HOLDING:
                    holding.append(e["rid"])
                else:
                    placed.append((e["rid"], e["placement"]))
            state["i"] = i + step
            placed = [(r, g) for r, g in placed if r in corpus]
            if placed:
                # only the new dots: redrawing all 10,000 each tick stalls the window; the map's
                # cached brushes and pens let pyqtgraph reuse each drawn dot
                styles = [view._style(g, "plain") for _, g in placed]
                xy = np.array([self.host.studio.xy(r) for r, _ in placed], np.float64)
                view.base.addPoints(
                    pos=xy, brush=[b for b, _ in styles], pen=[p for _, p in styles], size=4.6
                )
            self.bucket.set(holding, set())
            self.status.setText(f"replay {min(state['i'], len(events)):,} / {len(events):,}")
            self.status.adjustSize()
            if state["i"] >= len(events):
                timer.stop()
                QTimer.singleShot(900, self.redraw)

        timer = QTimer(self)
        timer.timeout.connect(tick)
        view.base.setData(pos=np.zeros((0, 2)))
        view.centres.setData(pos=np.zeros((0, 2)))
        timer.start(30)
        self._replay = timer

    def hideEvent(self, event: Any) -> None:  # noqa: N802 (Qt's name)
        if isValid(self.card):
            self.card.hide()
        super().hideEvent(event)
