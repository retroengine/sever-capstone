"""The map: every live record as a point, coloured by its group, and the holding area as a bucket.

Points in frozen groups are filled dots, points in spawned groups are rings; your own records are
white with a gold halo. Records in the holding area are not on the map: they sit in the bucket,
because no search can reach them until the bucket flushes into a new group (§7.4). Hovering a point
shows what it is; clicking selects it and its group.
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
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..actions import Studio
from ..backend import HOLDING
from . import theme
from .widgets import Heatmap, label

pg.setConfigOptions(antialias=True, background=theme.BG, foreground=theme.MUTED)


class Palette:
    """A stable colour per group: frozen groups by their number, spawned groups by arrival."""

    def __init__(self) -> None:
        self.spawned: dict[str, int] = {}

    def colour(self, group: str) -> QColor:
        if group.startswith("frozen-"):
            return theme.group_colour(int(group.split("-")[1]), spawned=False)
        if group == HOLDING:
            return QColor(theme.HOLDING)
        if group not in self.spawned:
            self.spawned[group] = 128 + len(self.spawned)
        return theme.group_colour(self.spawned[group], spawned=True)


class HoverCard(QFrame):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("hover")
        self.setFixedWidth(400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.rid = label("", "h3")
        top.addWidget(self.rid, 1)
        self.group = QLabel()
        top.addWidget(self.group)
        lay.addLayout(top)
        self.account = label("", "muted", wrap=True)
        lay.addWidget(self.account)
        self.text = label("", wrap=True)
        self.text.setStyleSheet("font-size: 10.5pt;")
        lay.addWidget(self.text)
        self.source = label("", "muted", wrap=True)
        self.source.setStyleSheet("font-size: 9pt;")
        lay.addWidget(self.source)
        lay.addWidget(label("its encoding", "muted"))
        self.heat = Heatmap(cols=32)
        lay.addWidget(self.heat)
        self.numbers = label("", "mono", wrap=True)
        self.numbers.setStyleSheet("font-size: 8.5pt; color: #8c92a6;")
        lay.addWidget(self.numbers)
        self.hide()

    def show_for(self, info: dict[str, object], colour: QColor) -> None:
        self.rid.setText(str(info["rid"]) + ("  (yours)" if info["mine"] else ""))
        g = str(info["group"])
        self.group.setText(g)
        self.group.setStyleSheet(
            f"background: {theme.rgba(colour.name(), 51)}; color: {colour.name()};"
            f" border: 1px solid {theme.rgba(colour.name(), 136)}; border-radius: 9px;"
            " padding: 2px 8px; font-size: 9pt;"
        )
        self.account.setText(f"account: {info['account']}")
        t = str(info["text"])
        self.text.setText(t if len(t) < 420 else t[:419] + "…")
        self.source.setText(
            f"Text shown from {info['source']}. The database stores it encrypted and never "
            "hands it back (§13.2)."
        )
        v = np.asarray(info["vector"], np.float64)
        self.heat.set(v)
        head = ", ".join(f"{x:+.4f}" for x in v[:6])
        self.numbers.setText(f"{len(v)} float32 numbers, unit length: [{head}, …]")
        self.adjustSize()
        self.show()
        self.raise_()


class MapView(pg.PlotWidget):  # type: ignore[misc]  # pyqtgraph has no type hints
    hovered = Signal(object)
    clicked = Signal(object)

    def __init__(self, studio: Studio) -> None:
        super().__init__()
        self.studio = studio
        self.palette = Palette()
        self.setMenuEnabled(False)
        self.hideAxis("left")
        self.hideAxis("bottom")
        self.setAspectLocked(True)
        self.getPlotItem().setContentsMargins(4, 4, 4, 4)
        self.vb = self.getPlotItem().getViewBox()
        self.vb.setMouseEnabled(True, True)
        self.base = pg.ScatterPlotItem(pxMode=True, hoverable=False)
        self.halo = pg.ScatterPlotItem(pxMode=True)
        self.mine = pg.ScatterPlotItem(pxMode=True)
        self.anim = pg.ScatterPlotItem(pxMode=True)
        self.ring = pg.ScatterPlotItem(pxMode=True)
        self.beam = pg.PlotDataItem(pen=pg.mkPen(theme.ACCENT + "aa", width=1.4), connect="pairs")
        self.star = pg.ScatterPlotItem(pxMode=True)
        for item in (self.base, self.halo, self.mine, self.beam, self.anim, self.ring, self.star):
            self.addItem(item)
        self.labels: list[pg.TextItem] = []
        self.rids: list[str] = []
        self.xy: npt.NDArray[np.float64] = np.zeros((0, 2))
        self.focus_group: str | None = None
        self.selected: str | None = None
        self.scene().sigMouseMoved.connect(self._moved)
        self.scene().sigMouseClicked.connect(self._clicked)
        self._anims: list[QVariantAnimation] = []

    # -- drawing ----------------------------------------------------------------------------------

    def refresh(self) -> None:
        recs = self.studio.backend.index.records
        rids = [r for r, rec in recs.items() if rec.group != HOLDING]
        self.rids = rids
        self.xy = np.array([self.studio.xy(r) for r in rids], np.float64).reshape(-1, 2)
        brushes, pens, sizes = [], [], []
        small = len(rids) > 2000
        mine_xy, mine_b = [], []
        for r in rids:
            rec = recs[r]
            c = self.palette.colour(rec.group)
            dim = self.focus_group is not None and rec.group != self.focus_group
            if dim:
                c = QColor(c.red(), c.green(), c.blue(), 40)
            spawned = rec.group.startswith("spawn-")
            if rec.mine:
                mine_xy.append(self.studio.xy(r))
                mine_b.append(c)
            brushes.append(pg.mkBrush(theme.BG if spawned else c))
            pens.append(
                pg.mkPen(c, width=1.6) if spawned else pg.mkPen(QColor(0, 0, 0, 90), width=0.6)
            )
            sizes.append((5.0 if spawned else 4.6) if small else (7.5 if spawned else 7.0))
        self.base.setData(
            pos=self.xy if len(rids) else np.zeros((0, 2)), brush=brushes, pen=pens, size=sizes
        )
        mx = np.array(mine_xy, np.float64).reshape(-1, 2)
        self.halo.setData(
            pos=mx, size=30, brush=pg.mkBrush(QColor(255, 209, 102, 60)), pen=pg.mkPen(None)
        )
        self.mine.setData(
            pos=mx,
            size=13,
            symbol="star",
            brush=pg.mkBrush(theme.YOURS),
            pen=pg.mkPen(theme.YOURS_RING, width=1.5),
        )
        self._ring()

    def _ring(self) -> None:
        if self.selected and self.selected in self.studio.backend.index.records:
            x, y = self.studio.xy(self.selected)
            self.ring.setData(
                pos=[(x, y)], size=24, brush=pg.mkBrush(None), pen=pg.mkPen(theme.ACCENT, width=2.5)
            )
        else:
            self.ring.setData(pos=np.zeros((0, 2)))

    def focus(self, group: str | None) -> None:
        self.focus_group = group
        self.refresh()

    def select(self, rid: str | None) -> None:
        self.selected = rid
        self._ring()

    # -- the search beam --------------------------------------------------------------------------

    def show_beam(self, origin: tuple[float, float], hits: list[tuple[str, float, bool]]) -> None:
        self.clear_beam()
        pts = []
        for rank, (rid, _, good) in enumerate(hits, 1):
            if rid not in self.studio.backend.index.records:
                continue
            x, y = self.studio.xy(rid)
            pts += [origin, (x, y)]
            t = pg.TextItem(
                ("✓ " if good else "") + str(rank),
                color=theme.OK if good else theme.TEXT,
                anchor=(0.5, 1.4),
            )
            t.setPos(x, y)
            self.addItem(t)
            self.labels.append(t)
        arr = np.array(pts, np.float64).reshape(-1, 2)
        self.beam.setData(arr[:, 0], arr[:, 1]) if len(arr) else self.beam.setData([], [])
        self.star.setData(
            pos=[origin],
            size=22,
            symbol="star",
            brush=pg.mkBrush(theme.ACCENT),
            pen=pg.mkPen("#ffffff", width=1.2),
        )

    def clear_beam(self) -> None:
        self.beam.setData([], [])
        self.star.setData(pos=np.zeros((0, 2)))
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
            done()
            self._anims.remove(a)

        a.finished.connect(fin)
        self._anims.append(a)
        a.start()

    def vanish(self, points: list[tuple[float, float, QColor]], then: Callable[[], None]) -> None:
        """Deleted points flash, grow and fade away."""
        if not points:
            then()
            return
        xy = np.array([(x, y) for x, y, _ in points], np.float64)

        def step(t: float) -> None:
            alpha = int(255 * (1 - t))
            self.anim.setData(
                pos=xy,
                size=8 + 34 * t,
                brush=[pg.mkBrush(QColor(255, 255, 255, int(alpha * 0.25))) for _ in points],
                pen=[
                    pg.mkPen(QColor(c.red(), c.green(), c.blue(), alpha), width=2.5)
                    for *_, c in points
                ],
            )

        def done() -> None:
            self.anim.setData(pos=np.zeros((0, 2)))
            then()

        self._animate(900, step, done)

    def arrive(self, x: float, y: float, colour: QColor, then: Callable[[], None]) -> None:
        """A new point drops in with a ripple."""

        def step(t: float) -> None:
            self.anim.setData(
                pos=[(x, y)],
                size=60 * (1 - t) + 12,
                brush=pg.mkBrush(None),
                pen=pg.mkPen(
                    QColor(colour.red(), colour.green(), colour.blue(), int(255 * (1 - t) + 60)),
                    width=2,
                ),
            )

        def done() -> None:
            self.anim.setData(pos=np.zeros((0, 2)))
            then()

        self._animate(800, step, done)

    def fly(self, members: list[str], group: str, then: Callable[[], None]) -> None:
        """A flush: the bucket's records fly from the bucket's side of the map to their places."""
        r = self.vb.viewRect()
        start = np.array([r.right(), (r.top() + r.bottom()) / 2])
        ends = np.array([self.studio.xy(m) for m in members], np.float64)
        c = self.palette.colour(group)

        def step(t: float) -> None:
            pos = start + (ends - start) * t
            self.anim.setData(
                pos=pos, size=7, brush=pg.mkBrush(c), pen=pg.mkPen(QColor(255, 255, 255, 120))
            )

        def done() -> None:
            self.anim.setData(pos=np.zeros((0, 2)))
            then()

        self._animate(1400, step, done)

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

    def _moved(self, pos: QPointF) -> None:
        self.hovered.emit(self.nearest(pos))

    def _clicked(self, ev: object) -> None:
        pos = ev.scenePos()  # type: ignore[attr-defined]
        self.clicked.emit(self.nearest(pos))


class Bucket(QWidget):
    """The holding area: records stored but not yet in any group, so not searchable (§7.4).
    It fills dot by dot and empties all at once when it reaches the spawn size."""

    def __init__(self, target: int) -> None:
        super().__init__()
        self.target = target
        self.ids: list[str] = []
        self.mine: set[str] = set()
        self.pulse = 0.0
        self.setMinimumWidth(190)
        self.setMouseTracking(True)
        self.cols = 10 if target >= 50 else 4

    def set(self, ids: list[str], mine: set[str]) -> None:
        self.ids = list(ids)
        self.mine = mine
        self.update()

    def flash(self) -> None:
        a = QVariantAnimation(self)
        a.setDuration(900)
        a.setStartValue(1.0)
        a.setEndValue(0.0)
        a.valueChanged.connect(lambda v: self._pulse(float(v)))
        a.start()
        self._a = a

    def _pulse(self, v: float) -> None:
        self.pulse = v
        self.update()

    def _geometry(self) -> tuple[QRectF, float]:
        w, h = self.width(), self.height()
        top, bottom = 70.0, h - 70.0
        body = QRectF(18, top, w - 36, max(60.0, bottom - top))
        rows = -(-self.target // self.cols)
        cell = min((body.width() - 24) / self.cols, (body.height() - 16) / rows)
        return body, cell

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt's name)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body, cell = self._geometry()
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(12, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, 8, self.width(), 24), Qt.AlignmentFlag.AlignHCenter, "Holding area")
        p.setFont(theme.font(9))
        p.setPen(QColor(theme.MUTED))
        p.drawText(
            QRectF(0, 32, self.width(), 34),
            Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap,
            "stored · deletable at once\nnot searchable until it flushes",
        )
        # the bucket: a tapered outline
        path = QPainterPath()
        inset = 14.0
        path.moveTo(body.left(), body.top())
        path.lineTo(body.left() + inset, body.bottom())
        path.lineTo(body.right() - inset, body.bottom())
        path.lineTo(body.right(), body.top())
        glow = int(140 * self.pulse)
        p.setPen(QPen(QColor(124, 156, 255, 110 + glow), 2.2))
        p.setBrush(QBrush(QColor(124, 156, 255, 18 + glow // 3)))
        p.drawPath(path)
        p.setPen(QPen(QColor(124, 156, 255, 170), 3))
        p.drawLine(QPointF(body.left() - 6, body.top()), QPointF(body.right() + 6, body.top()))
        # the records, stacked from the bottom
        x0 = body.left() + (body.width() - cell * self.cols) / 2
        for i, rid in enumerate(self.ids[: self.target]):
            r, c = divmod(i, self.cols)
            cx = x0 + (c + 0.5) * cell
            cy = body.bottom() - 8 - (r + 0.5) * cell
            mine = rid in self.mine
            p.setPen(QPen(QColor(theme.YOURS_RING), 1.4) if mine else Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.YOURS if mine else theme.HOLDING))
            rad = cell * (0.42 if mine else 0.34)
            p.drawEllipse(QPointF(cx, cy), rad, rad)
        # the gauge
        n = len(self.ids)
        p.setFont(theme.font(20))
        p.setPen(QColor(theme.TEXT))
        p.drawText(
            QRectF(0, self.height() - 64, self.width(), 34),
            Qt.AlignmentFlag.AlignHCenter,
            f"{n} / {self.target}",
        )
        p.setFont(theme.font(9))
        p.setPen(QColor(theme.MUTED))
        p.drawText(
            QRectF(0, self.height() - 32, self.width(), 20),
            Qt.AlignmentFlag.AlignHCenter,
            f"flushes into a new group at {self.target}",
        )
        p.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt's name)
        body, cell = self._geometry()
        x0 = body.left() + (body.width() - cell * self.cols) / 2
        pos = event.position()
        c = int((pos.x() - x0) // cell) if cell else -1
        r = int((body.bottom() - 8 - pos.y()) // cell) if cell else -1
        i = r * self.cols + c
        if 0 <= c < self.cols and r >= 0 and 0 <= i < len(self.ids):
            rid = self.ids[i]
            self.setToolTip(f"{rid}{'  (yours)' if rid in self.mine else ''}: in the holding area")
        else:
            self.setToolTip("")
