"""The map's 3-D mode: the same records, colours and lit group as the 2-D map, laid out by t-SNE
with three axes (``Studio.layout3``). Drag to turn it; it turns slowly by itself until you do.

A third axis keeps a little more of the 384 dimensions than two, never all of them: distances are
still measured in 384-D, and the window says so. The 3-D mode needs OpenGL that can render into a
window. Where it cannot (no framebuffer: a headless screen, a broken driver), it says why and the
2-D map works as before.
"""

from typing import Any, cast

import numpy as np
import numpy.typing as npt
from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QHideEvent, QShowEvent
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..actions import Studio
from . import theme
from .map_view import MapView, paint
from .widgets import label

F64 = npt.NDArray[np.float64]
#: Qt platforms with no real display: no window to draw OpenGL into
HEADLESS = ("offscreen", "minimal")


def rgba_of(c: QColor) -> tuple[float, float, float, float]:
    return c.redF(), c.greenF(), c.blueF(), c.alphaF()


class Map3D(QWidget):
    def __init__(self, studio: Studio, map2d: MapView) -> None:
        super().__init__()
        self.studio, self.map2d = studio, map2d
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.ok = False
        self.reason = ""
        self.view: Any = None
        self.spinning = True
        self.note = label("", "small", wrap=True)
        self.note.hide()
        lay.addWidget(self.note)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._turn)
        self._checked = False

    def start(self) -> None:
        """Makes the OpenGL view the first time the 3-D mode opens, never before: on a screen
        without OpenGL support, creating it can take the whole window down."""
        if self.view is not None or self.reason:
            return
        platform = QGuiApplication.platformName()
        if platform in HEADLESS:
            self._fail(f"this screen is headless ({platform}): 3-D needs a real display.")
            return
        try:
            import pyqtgraph.opengl as gl

            view = gl.GLViewWidget()
            view.setBackgroundColor(QColor(theme.BG))
            view.setCameraPosition(distance=290, elevation=16, azimuth=35)
            # "translucent" blends over the light background; the default "additive" washes out
            self.dots = gl.GLScatterPlotItem(pxMode=True, glOptions="translucent")
            self.centres = gl.GLScatterPlotItem(pxMode=True, glOptions="translucent")
            self.mine = gl.GLScatterPlotItem(pxMode=True, glOptions="translucent")
            for item in (self.dots, self.centres, self.mine):
                view.addItem(item)
            view.installEventFilter(self)
        except Exception as e:  # PyOpenGL missing, or no OpenGL at all
            self._fail(f"OpenGL did not start here: {e}")
            return
        self.view = view
        cast(QVBoxLayout, self.layout()).insertWidget(0, view, 1)
        if self.isVisible():
            QTimer.singleShot(250, self._check)

    def _fail(self, why: str) -> None:
        self.reason = f"3-D is not available: {why} The 2-D map works as before."
        self.note.setText(self.reason)
        self.note.show()

    # -- OpenGL, checked once it is on screen -----------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt's name)
        super().showEvent(event)
        self.start()
        if not self._checked and self.view is not None:
            QTimer.singleShot(250, self._check)
        if self.ok:
            self.timer.start(50)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 (Qt's name)
        super().hideEvent(event)
        self.timer.stop()

    def _check(self) -> None:
        """A context is not enough: a headless screen has one but no framebuffer to draw into."""
        self._checked = True
        v = self.view
        if v is not None and v.isValid() and v.defaultFramebufferObject() != 0:
            self.ok = True
            self.refresh()
            if self.isVisible():
                self.timer.start(50)
            return
        if v is not None:
            v.hide()
        self._fail("OpenGL cannot draw into a window on this screen (no framebuffer).")

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt's name)
        if event.type() == QEvent.Type.MouseButtonPress:
            self.spinning = False  # the person turns it now
        return False

    def _turn(self) -> None:
        if self.spinning and self.view is not None:
            self.view.orbit(0.25, 0)

    # -- what is drawn ----------------------------------------------------------------------------

    def data(self) -> tuple[list[str], F64, F64]:
        """The 2-D map's records, each at its 3-D position, in the 2-D map's colour (``paint``)."""
        m = self.map2d
        recs = self.studio.backend.index.records
        rids = list(m.rids)
        pos = np.array([self.studio.xyz(r) for r in rids], np.float64).reshape(-1, 3)
        cache: dict[tuple[str, str], tuple[float, float, float, float]] = {}
        rgba = []
        for r in rids:
            g = recs[r].group
            key = (g, m._look(g))
            if key not in cache:
                cache[key] = rgba_of(paint(g, key[1], m.colour_all))
            rgba.append(cache[key])
        return rids, pos, np.array(rgba, np.float64).reshape(-1, 4)

    def refresh(self) -> None:
        """Draws the records; waits while the 3-D layout is still being made on the worker."""
        if not self.ok or self.studio.coords3 is None:
            return
        m = self.map2d
        rids, pos, rgba = self.data()
        recs = self.studio.backend.index.records
        lit = [m._look(recs[r].group) == "lit" for r in rids]
        self.dots.setData(pos=pos, color=rgba, size=np.where(lit, 8.0, 5.0))
        cs = self.studio.centres3()
        cpos = np.array([c[1:4] for c in cs], np.float64).reshape(-1, 3)
        ccol = np.array(
            [rgba_of(paint(c[0], m._look(c[0]), m.colour_all).darker(150)) for c in cs],
            np.float64,
        ).reshape(-1, 4)
        csize = np.array([22.0 if m._look(c[0]) == "lit" else 12.0 for c in cs])
        self.centres.setData(pos=cpos, color=ccol, size=csize)
        mine = [p for r, p in zip(rids, pos, strict=True) if recs[r].mine]
        self.mine.setData(
            pos=np.array(mine, np.float64).reshape(-1, 3),
            color=rgba_of(QColor(theme.YOURS)),
            size=13.0,
        )
