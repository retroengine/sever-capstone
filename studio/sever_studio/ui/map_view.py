"""The map: every live record as a dot where its meaning puts it, and the holding area as a gauge.

A dot's colour is its group's own, its shape the group's kind (● frozen, ■ spawned); each centre μ,
as the engine has it, is a ✕ among the passages nearest it. Selecting a group lights up its members
wherever they lie: a frozen group's are near its centre, a spawned group's are a scattered batch
(§7.4). Stars are your own records. Records in the holding area are not on the map: no search
reaches them until the area flushes, so they sit in the gauge at the map's edge.
"""

from collections.abc import Callable
from typing import Any

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..actions import Studio
from ..backend import HOLDING
from . import copy, theme
from .widgets import Heatmap, label, lift

pg.setConfigOptions(antialias=True, background=theme.BG, foreground=theme.MUTED)
EMPTY = np.zeros((0, 2))


class HoverCard(QFrame):
    """What a dot is: its ID, group, three lines of its text, and its numbers as a strip."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("float")
        lift(self)
        self.setFixedWidth(380)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = self.box = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.rid = label("", "strong")
        top.addWidget(self.rid, 1)
        self.rid.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.group = QLabel()
        self.group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        top.addWidget(self.group)
        lay.addLayout(top)
        self.account = label("", "small")
        lay.addWidget(self.account)
        self.text = label("", wrap=True)
        lay.addWidget(self.text)
        self.heat = Heatmap(cols=48)
        lay.addWidget(self.heat)
        self.source = label(copy.short("hover.source"), "small")
        lay.addWidget(self.source)
        self.hide()

    def show_for(self, info: dict[str, object], colour: QColor) -> None:
        c = colour.name()
        self.group.setText(str(info["group"]))
        self.group.setStyleSheet(
            f"background: {theme.rgba(c, 51)}; color: {c}; border-radius: 8px; padding: 1px 7px;"
            f" font-size: {theme.pt(theme.SMALL)}pt;"
        )
        # the group's name always shows whole; a long record ID gives way, with an ellipsis
        room = self.width() - 24 - self.group.sizeHint().width() - 8
        rid = str(info["rid"]) + ("  ★" if info["mine"] else "")
        self.rid.setText(
            self.rid.fontMetrics().elidedText(rid, Qt.TextElideMode.ElideMiddle, max(40, room))
        )
        self.source.setText(copy.short("hover.source.mine" if info["mine"] else "hover.source"))
        self.account.setText(str(info["account"]))
        t = " ".join(str(info["text"]).split())
        self.text.setText(t if len(t) <= 170 else t[:169] + "…")
        self.heat.set(np.asarray(info["vector"], np.float64))
        # the wrapped text's real height for this width: adjustSize alone left the strip over
        # the last line when the text wrapped
        self.box.activate()
        self.setFixedHeight(self.box.totalHeightForWidth(self.width()))
        self.show()
        self.raise_()


def _nums(values: npt.NDArray[np.generic], fmt: str, shown: int = 3) -> str:
    return "[" + ", ".join(format(v, fmt) for v in values[:shown]) + f", … {len(values)} numbers]"


class GroupCard(QFrame):
    """A group when its centre is hovered: what the engine says about it (DB-109)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("float")
        lift(self)
        self.setFixedWidth(400)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = self.box = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(5)
        self.title = label("", "strong")
        lay.addWidget(self.title)
        self.kind = label("", "small", wrap=True)
        lay.addWidget(self.kind)
        self.n = label("", "mono")
        self.cs = label("", "mono", wrap=True)
        self.cs_note = label("", "small", wrap=True)
        self.mu = label("", "mono", wrap=True)
        self.mu_note = label("", "small", wrap=True)
        for w in (self.n, self.cs, self.cs_note, self.mu, self.mu_note):
            lay.addWidget(w)
        self.heat = Heatmap(cols=48)
        lay.addWidget(self.heat)
        lay.addWidget(label(copy.short("group.note"), "small", wrap=True))
        self.hide()

    def show_for(self, card: dict[str, Any], colour: QColor) -> None:
        group = str(card["group"])
        c = colour.name()
        self.title.setText(f"<span style='color:{c}'>✕</span> {group}")
        self.kind.setText(
            copy.short("group.frozen" if group.startswith("frozen-") else "group.spawned")
        )
        self.n.setText(f"n   = {card['n']:,} records  (the engine's count)")
        cs = card["commitment"]
        self.cs.setText(f"C_S = {cs[:24]}…" if cs else "C_S = not published yet")
        self.cs_note.setText(
            f"the group's commitment, from the engine's receipt #{card['commitment_lsn']}"
            " (after that deletion)"
            if cs
            else "the engine publishes a group's commitment in each deletion's receipt"
        )
        mu = card["mu"]
        self.mu.setText("μ   = " + (_nums(mu, ".4f") if mu is not None else "unknown"))
        self.mu_note.setText(f"fixed centre, from {card['mu_source']}")
        if mu is not None:
            self.heat.set(np.asarray(mu, np.float64))
        self.box.activate()
        self.setFixedHeight(self.box.totalHeightForWidth(self.width()))
        self.show()
        self.raise_()


class MapView(pg.PlotWidget):  # type: ignore[misc]  # pyqtgraph has no type hints
    hovered = Signal(object)
    clicked = Signal(object)
    group_hovered = Signal(object)
    group_clicked = Signal(object)

    def __init__(self, studio: Studio) -> None:
        super().__init__()
        self.studio = studio
        self.setMenuEnabled(False)
        self.hideAxis("left")
        self.hideAxis("bottom")
        self.setAspectLocked(True)
        self.getPlotItem().setContentsMargins(0, 0, 0, 0)
        self.vb = self.getPlotItem().getViewBox()
        self.vb.setDefaultPadding(0.1)  # room for the floating search, legend and gauge
        self.base = pg.ScatterPlotItem(pxMode=True)
        self.centres = pg.ScatterPlotItem(pxMode=True)
        self.centre_at: list[tuple[str, float, float]] = []
        self.halo = pg.ScatterPlotItem(pxMode=True)
        self.mine = pg.ScatterPlotItem(pxMode=True)
        self.anim = pg.ScatterPlotItem(pxMode=True)
        self.ring = pg.ScatterPlotItem(pxMode=True)
        self.beam = pg.PlotDataItem(pen=pg.mkPen(theme.ACCENT + "aa", width=1.4), connect="pairs")
        self.star = pg.ScatterPlotItem(pxMode=True)
        for item in (
            self.base,
            self.centres,
            self.halo,
            self.mine,
            self.beam,
            self.anim,
            self.ring,
            self.star,
        ):
            self.addItem(item)
        self.labels: list[pg.TextItem] = []
        self.rids: list[str] = []
        self.dot = 7.0
        self.xy: npt.NDArray[np.float64] = EMPTY
        self.focus_group: str | None = None
        self.selected: str | None = None
        self._brush: dict[tuple[str, str], object] = {}
        self.scene().sigMouseMoved.connect(self._moved)
        self.scene().sigMouseClicked.connect(self._click)
        self._anims: list[QVariantAnimation] = []

    # -- drawing ----------------------------------------------------------------------------------

    def colour(self, group: str) -> QColor:
        return theme.group_colour(group)

    def _style(self, group: str, look: str) -> tuple[object, object]:
        """``look``: "plain", "dim" (another group is selected) or "lit" (the selected group)."""
        key = (group, look)
        if key not in self._brush:
            c = self.colour(group)
            if look == "dim":
                c = QColor(c.red(), c.green(), c.blue(), 30)
            brush = pg.mkBrush(c)
            pen = (
                pg.mkPen(QColor(theme.TEXT), width=1.4)
                if look == "lit"
                else pg.mkPen(QColor(0, 0, 0, 25 if look == "dim" else 70), width=0.5)
            )
            self._brush[key] = (brush, pen)
        return self._brush[key]  # type: ignore[return-value]

    def _look(self, group: str) -> str:
        if self.focus_group is None:
            return "plain"
        return "lit" if group == self.focus_group else "dim"

    def refresh(self) -> None:
        recs = self.studio.backend.index.records
        rids = [r for r, rec in recs.items() if rec.group != HOLDING]
        self.rids = rids
        self.xy = np.array([self.studio.xy(r) for r in rids], np.float64).reshape(-1, 2)
        self.dot = 4.6 if len(rids) > 2000 else 7.0
        brushes, pens, sizes, symbols = [], [], [], []
        mine_xy = []
        for r in rids:
            rec = recs[r]
            look = self._look(rec.group)
            b, p = self._style(rec.group, look)
            brushes.append(b)
            pens.append(p)
            sizes.append(self.dot * (1.6 if look == "lit" else 1.0))
            symbols.append("o" if rec.group.startswith("frozen-") else "s")
            if rec.mine:
                mine_xy.append(self.studio.xy(r))
        self.base.setData(
            pos=self.xy if len(rids) else EMPTY,
            brush=brushes,
            pen=pens,
            size=sizes or self.dot,
            symbol=symbols or "o",
        )
        self._centres()
        mx = np.array(mine_xy, np.float64).reshape(-1, 2)
        self.halo.setData(
            pos=mx, size=28, brush=pg.mkBrush(QColor(255, 209, 102, 60)), pen=pg.mkPen(None)
        )
        self.mine.setData(
            pos=mx,
            size=13,
            symbol="star",
            brush=pg.mkBrush(theme.YOURS),
            pen=pg.mkPen(theme.YOURS_RING, width=1.5),
        )
        self._ring()

    def _centres(self) -> None:
        """Each group's centre μ as the engine has it (✕), drawn among the passages nearest it."""
        spots, at = [], []
        for g, cx, cy, n in self.studio.centres():
            c = self.colour(g)
            look = self._look(g)
            if look == "dim":
                c = QColor(c.red(), c.green(), c.blue(), 50)
            at.append((g, cx, cy))
            spots.append(
                {
                    "pos": (cx, cy),
                    "symbol": "x",
                    "size": (self.dot + (9 if n >= 20 else 4)) * (1.5 if look == "lit" else 1.0),
                    "brush": pg.mkBrush(c.darker(150)),
                    "pen": pg.mkPen(theme.SURFACE, width=0.8),
                }
            )
        self.centres.setData(spots=spots)
        self.centre_at = at

    def _click(self, ev: object) -> None:
        pos = ev.scenePos()  # type: ignore[attr-defined]
        g = self.nearest_centre(pos)
        if g is not None:
            self.group_clicked.emit(g)
        else:
            self.clicked.emit(self.nearest(pos))

    def _moved(self, pos: QPointF) -> None:
        """Over a centre: the group's card; anywhere else: the nearest dot's."""
        g = self.nearest_centre(pos)
        if g is not None:
            self.hovered.emit(None)
            self.group_hovered.emit(g)
            return
        self.group_hovered.emit(None)
        self.hovered.emit(self.nearest(pos))

    def nearest_centre(self, scene_pos: QPointF, radius: float = 11.0) -> str | None:
        if not self.centre_at:
            return None
        p = self.vb.mapSceneToView(scene_pos)
        px, py = self.vb.viewPixelSize()
        best, d2 = None, radius * radius
        for g, x, y in self.centre_at:
            dd = ((x - p.x()) / max(px, 1e-12)) ** 2 + ((y - p.y()) / max(py, 1e-12)) ** 2
            if dd <= d2:
                best, d2 = g, dd
        return best

    def _ring(self) -> None:
        if self.selected and self.selected in self.studio.backend.index.records:
            x, y = self.studio.xy(self.selected)
            self.ring.setData(
                pos=[(x, y)], size=24, brush=pg.mkBrush(None), pen=pg.mkPen(theme.ACCENT, width=2.5)
            )
        else:
            self.ring.setData(pos=EMPTY)

    def focus(self, group: str | None) -> None:
        self.focus_group = group
        self.refresh()

    def select(self, rid: str | None) -> None:
        self.selected = rid
        self._ring()

    def to_widget(self, x: float, y: float) -> QPointF:
        return QPointF(self.mapFromScene(self.vb.mapViewToScene(QPointF(x, y))))

    # -- the search beam --------------------------------------------------------------------------

    def show_beam(self, origin: tuple[float, float], hits: list[tuple[str, float, bool]]) -> None:
        self.clear_beam()
        pts = []
        for rank, (rid, _, good) in enumerate(hits, 1):
            if rid not in self.studio.backend.index.records:
                continue
            x, y = self.studio.xy(rid)
            pts += [origin, (x, y)]
            if rank <= 5 or good:
                t = pg.TextItem(
                    ("✓" if good else "") + str(rank),
                    color=theme.OK if good else theme.TEXT,
                    anchor=(0.5, 1.4),
                )
                t.setPos(x, y)
                self.addItem(t)
                self.labels.append(t)
        arr = np.array(pts, np.float64).reshape(-1, 2)
        if len(arr):
            self.beam.setData(arr[:, 0], arr[:, 1])
        self.star.setData(
            pos=[origin],
            size=22,
            symbol="star",
            brush=pg.mkBrush(theme.ACCENT),
            pen=pg.mkPen(theme.SURFACE, width=1.2),
        )

    def clear_beam(self) -> None:
        self.beam.setData([], [])
        self.star.setData(pos=EMPTY)
        for t in self.labels:
            self.removeItem(t)
        self.labels = []

    # -- animations -------------------------------------------------------------------------------

    def _animate(self, ms: int, step: Callable[[float], None], done: Callable[[], None]) -> None:
        a = QVariantAnimation(self)
        a.setDuration(ms)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.valueChanged.connect(lambda v: step(float(v)))

        def fin() -> None:
            self.anim.setData(pos=EMPTY)
            self._anims.remove(a)
            done()

        a.finished.connect(fin)
        self._anims.append(a)
        a.start()

    def vanish(self, points: list[tuple[float, float, QColor]], then: Callable[[], None]) -> None:
        """Deleted dots flash, grow and fade away."""
        if not points:
            then()
            return
        xy = np.array([(x, y) for x, y, _ in points], np.float64)
        colours = [c for *_, c in points]
        tint = QColor(theme.ACCENT)

        def step(t: float) -> None:
            alpha = int(255 * (1 - t))
            self.anim.setData(
                pos=xy,
                size=8 + 34 * t,
                brush=pg.mkBrush(tint.red(), tint.green(), tint.blue(), int(alpha * 0.2)),
                pen=[
                    pg.mkPen(QColor(c.red(), c.green(), c.blue(), alpha), width=2.5)
                    for c in colours
                ],
            )

        self._animate(900, step, then)

    def arrive(self, x: float, y: float, colour: QColor, then: Callable[[], None]) -> None:
        """A new dot drops in with a ripple."""

        def step(t: float) -> None:
            a = int(255 * (1 - t) + 60)
            self.anim.setData(
                pos=[(x, y)],
                size=60 * (1 - t) + 12,
                brush=pg.mkBrush(None),
                pen=pg.mkPen(QColor(colour.red(), colour.green(), colour.blue(), a), width=2),
            )

        self._animate(800, step, then)

    def fly(self, members: list[str], group: str, then: Callable[[], None]) -> None:
        """A flush: the waiting records fly from the gauge's side to their places."""
        r = self.vb.viewRect()
        start = np.array([r.right(), (r.top() + r.bottom()) / 2])
        ends = np.array([self.studio.xy(m) for m in members], np.float64)
        brush = pg.mkBrush(self.colour(group))
        pen = pg.mkPen(QColor(theme.SURFACE))

        def step(t: float) -> None:
            self.anim.setData(pos=start + (ends - start) * t, size=6, brush=brush, pen=pen)

        self._animate(1400, step, then)

    # -- the pointer ------------------------------------------------------------------------------

    def nearest(self, scene_pos: QPointF, radius: float = 9.0) -> str | None:
        if not len(self.rids):
            return None
        p = self.vb.mapSceneToView(scene_pos)
        px, py = self.vb.viewPixelSize()
        dx = (self.xy[:, 0] - p.x()) / max(px, 1e-12)
        dy = (self.xy[:, 1] - p.y()) / max(py, 1e-12)
        d2 = dx * dx + dy * dy
        i = int(np.argmin(d2))
        return self.rids[i] if d2[i] <= radius * radius else None


class Bucket(QWidget):
    """The holding area as a tall, narrow gauge: it fills dot by dot and empties all at once."""

    def __init__(self, target: int) -> None:
        super().__init__()
        self.target = target
        self.ids: list[str] = []
        self.mine: set[str] = set()
        self.pulse = 0.0
        self.cols = 5 if target >= 50 else 2
        self.setMinimumSize(92, 180)
        self.setMouseTracking(True)
        self._a: QVariantAnimation | None = None

    def set(self, ids: list[str], mine: set[str]) -> None:
        self.ids = list(ids)
        self.mine = mine
        self.update()

    def flash(self) -> None:
        a = QVariantAnimation(self)
        a.setDuration(900)
        a.setStartValue(1.0)
        a.setEndValue(0.0)
        a.valueChanged.connect(self._pulse)
        a.start()
        self._a = a

    def _pulse(self, v: object) -> None:
        self.pulse = float(v)  # type: ignore[arg-type]
        self.update()

    def _body(self) -> tuple[QRectF, float]:
        body = QRectF(14, 8, self.width() - 28, self.height() - 52)
        rows = -(-self.target // self.cols)
        cell = min((body.width() - 12) / self.cols, (body.height() - 10) / rows)
        return body, cell

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt's name)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body, cell = self._body()
        path = QPainterPath()
        inset = 6.0
        path.moveTo(body.left(), body.top())
        path.lineTo(body.left() + inset, body.bottom())
        path.lineTo(body.right() - inset, body.bottom())
        path.lineTo(body.right(), body.top())
        glow = int(140 * self.pulse)
        a = QColor(theme.ACCENT)
        p.setPen(QPen(QColor(a.red(), a.green(), a.blue(), 110 + glow), 2))
        p.setBrush(QBrush(QColor(a.red(), a.green(), a.blue(), 16 + glow // 3)))
        p.drawPath(path)
        x0 = body.left() + (body.width() - cell * self.cols) / 2
        for i, rid in enumerate(self.ids[: self.target]):
            r, c = divmod(i, self.cols)
            centre = QPointF(x0 + (c + 0.5) * cell, body.bottom() - 5 - (r + 0.5) * cell)
            mine = rid in self.mine
            p.setPen(QPen(QColor(theme.YOURS_RING), 1.2) if mine else Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.YOURS if mine else theme.HOLDING))
            rad = cell * (0.46 if mine else 0.34)
            p.drawEllipse(centre, rad, rad)
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(theme.HEADING, QFont.Weight.Bold))
        p.drawText(
            QRectF(0, self.height() - 42, self.width(), 24),
            Qt.AlignmentFlag.AlignHCenter,
            f"{len(self.ids)}/{self.target}",
        )
        p.setFont(theme.font(theme.SMALL))
        p.setPen(QColor(theme.MUTED))
        p.drawText(
            QRectF(0, self.height() - 20, self.width(), 18),
            Qt.AlignmentFlag.AlignHCenter,
            copy.short("bucket"),
        )
        p.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt's name)
        body, cell = self._body()
        x0 = body.left() + (body.width() - cell * self.cols) / 2
        pos = event.position()
        c = int((pos.x() - x0) // cell) if cell else -1
        r = int((body.bottom() - 5 - pos.y()) // cell) if cell else -1
        i = r * self.cols + c
        rid = self.ids[i] if 0 <= c < self.cols and r >= 0 and 0 <= i < len(self.ids) else None
        self.setToolTip(f"{rid}{'  ★ yours' if rid in self.mine else ''}" if rid else "")
