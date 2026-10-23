"""The map: every live record as a dot coloured by its group, and the holding area as a gauge.

Each group has a colour of its own; by group, its records form a disc around its centre (◆ frozen,
■ spawned). Stars are your own records. Records in the holding area are not on the map: no search
reaches them until the area flushes (§7.4), so they sit in the gauge at the map's edge.
"""

from collections.abc import Callable

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


class Palette:
    """Each group's own colour, as the group map gave it (``layout.GroupMap``)."""

    def __init__(self, studio: Studio) -> None:
        self.studio = studio

    def colour(self, group: str) -> QColor:
        if group == HOLDING:
            return QColor(theme.HOLDING)
        colours = self.studio.groups.colours
        if group not in colours:
            self.studio.place_groups()
        return theme.group_colour(colours.get(group, 0))


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


class MapView(pg.PlotWidget):  # type: ignore[misc]  # pyqtgraph has no type hints
    hovered = Signal(object)
    clicked = Signal(object)

    def __init__(self, studio: Studio) -> None:
        super().__init__()
        self.studio = studio
        self.palette = Palette(studio)
        self.setMenuEnabled(False)
        self.hideAxis("left")
        self.hideAxis("bottom")
        self.setAspectLocked(True)
        self.getPlotItem().setContentsMargins(0, 0, 0, 0)
        self.vb = self.getPlotItem().getViewBox()
        self.vb.setDefaultPadding(0.1)  # room for the floating search, legend and gauge
        self.base = pg.ScatterPlotItem(pxMode=True)
        self.centres = pg.ScatterPlotItem(pxMode=True)
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
        self._brush: dict[tuple[str, bool], object] = {}
        self.scene().sigMouseMoved.connect(lambda pos: self.hovered.emit(self.nearest(pos)))
        self.scene().sigMouseClicked.connect(
            lambda ev: self.clicked.emit(self.nearest(ev.scenePos()))
        )
        self._anims: list[QVariantAnimation] = []

    # -- drawing ----------------------------------------------------------------------------------

    def _style(self, group: str, dim: bool) -> tuple[object, object]:
        key = (group, dim)
        if key not in self._brush:
            c = self.palette.colour(group)
            if dim:
                c = QColor(c.red(), c.green(), c.blue(), 35)
            brush = pg.mkBrush(c)
            pen = pg.mkPen(QColor(0, 0, 0, 30 if dim else 70), width=0.5)
            self._brush[key] = (brush, pen)
        return self._brush[key]  # type: ignore[return-value]

    def refresh(self) -> None:
        recs = self.studio.backend.index.records
        rids = [r for r, rec in recs.items() if rec.group != HOLDING]
        self.rids = rids
        self.xy = np.array([self.studio.xy(r) for r in rids], np.float64).reshape(-1, 2)
        size = self.dot = 4.6 if len(rids) > 2000 else 7.0
        brushes, pens = [], []
        mine_xy = []
        for r in rids:
            rec = recs[r]
            b, p = self._style(
                rec.group, self.focus_group is not None and rec.group != self.focus_group
            )
            brushes.append(b)
            pens.append(p)
            if rec.mine:
                mine_xy.append(self.studio.xy(r))
        self.base.setData(pos=self.xy if len(rids) else EMPTY, brush=brushes, pen=pens, size=size)
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
        """Each group's centre, in its colour: ◆ frozen, ■ spawned (by group only)."""
        if not self.studio.by_group:
            self.centres.setData(pos=EMPTY)
            return
        spots = []
        for g, x, y, _ in self.studio.centres():
            c = self.palette.colour(g)
            if self.focus_group is not None and g != self.focus_group:
                c = QColor(c.red(), c.green(), c.blue(), 50)
            spots.append(
                {
                    "pos": (x, y),
                    "symbol": "d" if g.startswith("frozen-") else "s",
                    "size": self.dot + (4 if g.startswith("frozen-") else 6),
                    "brush": pg.mkBrush(c),
                    "pen": pg.mkPen(theme.SURFACE, width=1.5),
                    "data": g,
                }
            )
        self.centres.setData(spots=spots)

    def recolour(self) -> None:
        """After the palette changes (the colour-blind-safe switch)."""
        self._brush.clear()
        self.palette = Palette(self.studio)
        self.refresh()

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
        brush = pg.mkBrush(self.palette.colour(group))
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
