"""Small building blocks shared by the screens."""

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme


def label(text: str = "", kind: str = "", wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if kind:
        lab.setObjectName(kind)
    lab.setWordWrap(wrap)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


def button(text: str, kind: str = "", on: Callable[[], None] | None = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on is not None:
        b.clicked.connect(lambda: on())
    return b


class Card(QFrame):
    """A rounded panel with an optional title and note; ``body`` takes the content."""

    def __init__(self, title: str = "", note: str = "", kind: str = "card") -> None:
        super().__init__()
        self.setObjectName(kind)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 14)
        self.lay.setSpacing(8)
        if title:
            self.lay.addWidget(label(title, "h3"))
        if note:
            self.lay.addWidget(label(note, "muted", wrap=True))
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        self.lay.addLayout(self.body)
        self.lay.addStretch(1)

    def add(self, w: QWidget) -> QWidget:
        self.body.addWidget(w)
        return w


def badge(text: str, colour: str = theme.ACCENT) -> QLabel:
    b = QLabel(text)
    b.setStyleSheet(
        f"background: {theme.rgba(colour, 34)}; color: {colour};"
        f" border: 1px solid {theme.rgba(colour, 110)};"
        " border-radius: 9px; padding: 2px 9px; font-size: 9.5pt; font-weight: 600;"
    )
    b.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return b


def tick(ok: bool | None) -> str:
    return "✓" if ok else ("✗" if ok is False else "○")


def tick_colour(ok: bool | None) -> str:
    return theme.OK if ok else (theme.BAD if ok is False else theme.MUTED)


class Tile(QFrame):
    """A big number with a caption."""

    def __init__(self, caption: str, value: str = "—", colour: str = theme.TEXT) -> None:
        super().__init__()
        self.setObjectName("card2")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        self.value = label(value, "big")
        self.value.setStyleSheet(f"color: {colour};")
        lay.addWidget(self.value)
        lay.addWidget(label(caption, "muted", wrap=True))

    def set(self, value: str, colour: str | None = None) -> None:
        self.value.setText(value)
        if colour:
            self.value.setStyleSheet(f"color: {colour};")


class Console(QPlainTextEdit):
    def __init__(self, height: int = 220) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setFont(theme.font(10, mono=True))
        self.setMinimumHeight(height)
        self.setMaximumBlockCount(5000)

    def say(self, text: str) -> None:
        self.appendPlainText(text)
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())


class Heatmap(QWidget):
    """A vector's numbers as a grid of cells: blue below zero, red above, white near zero."""

    def __init__(self, cols: int = 32) -> None:
        super().__init__()
        self.cols = cols
        self.values: npt.NDArray[np.float64] = np.zeros(0)
        self.setMinimumHeight(60)

    def set(self, vector: Sequence[float] | npt.NDArray[np.floating[Any]]) -> None:
        self.values = np.asarray(vector, np.float64)
        rows = max(1, -(-len(self.values) // self.cols))
        self.setFixedHeight(rows * 9 + 2)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt's name)
        if not len(self.values):
            return
        p = QPainter(self)
        w = (self.width() - 2) / self.cols
        scale = max(float(np.abs(self.values).max()), 1e-9)
        for i, v in enumerate(self.values):
            t = max(-1.0, min(1.0, v / scale))
            if t >= 0:
                c = QColor(255, int(255 * (1 - t * 0.8)), int(255 * (1 - t * 0.85)))
            else:
                c = QColor(int(255 * (1 + t * 0.85)), int(255 * (1 + t * 0.6)), 255)
            r, col = divmod(i, self.cols)
            p.fillRect(QRectF(1 + col * w, 1 + r * 9, w - 1, 8), c)
        p.end()


class StepList(QWidget):
    """The verifier's steps, revealed one after another with their verdicts."""

    def __init__(self) -> None:
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(4)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._next)
        self.queue: list[QWidget] = []

    def show_steps(
        self, steps: Sequence[tuple[str, str, str]], verdict: str, delay: int = 220
    ) -> None:
        """``steps``: (number, what it checks, verdict) rows; ``verdict``: the final line."""
        while self.lay.count():
            item = self.lay.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        self.queue = []
        for n, checks, v in steps:
            state = "ok" if v == "ok" else ("fail" if v.startswith("FAILED") else "skip")
            colour = {"ok": theme.OK, "fail": theme.BAD, "skip": theme.MUTED}[state]
            mark = {"ok": "✓", "fail": "✗", "skip": "–"}[state]
            row = QFrame()
            row.setObjectName("card2")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 6, 10, 6)
            m = label(mark)
            m.setStyleSheet(f"color: {colour}; font-size: 14pt; font-weight: 700;")
            m.setFixedWidth(22)
            h.addWidget(m)
            h.addWidget(label(f"step {n}", "muted"))
            body = label(checks, wrap=True)
            body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            h.addWidget(body, 1)
            vl = label(v)
            vl.setStyleSheet(f"color: {colour}; font-weight: 600;")
            h.addWidget(vl)
            self.queue.append(row)
        final = label(verdict, "h2")
        good = verdict.startswith("ACCEPT")
        final.setStyleSheet(
            f"color: {theme.OK if good else theme.BAD}; padding: 8px 4px;"
            f" border-top: 2px solid {theme.OK if good else theme.BAD};"
        )
        self.queue.append(final)
        self.timer.start(delay)

    def _next(self) -> None:
        if not self.queue:
            self.timer.stop()
            return
        w = self.queue.pop(0)
        effect = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(effect)
        self.lay.addWidget(w)
        anim = QPropertyAnimation(effect, b"opacity", w)
        anim.setDuration(260)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()


class Toast(QFrame):
    """A message that slides in at the bottom right and leaves by itself."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(14, 10, 10, 10)
        self.text = label("", wrap=True)
        self.text.setMaximumWidth(460)
        self.lay.addWidget(self.text, 1)
        self.action = button("", "show")
        self.lay.addWidget(self.action)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()
        self._cb: Callable[[], None] | None = None
        self.action.clicked.connect(self._act)

    def _act(self) -> None:
        if self._cb:
            self._cb()
        self.hide()

    def pop(
        self,
        text: str,
        colour: str = theme.ACCENT,
        action: str = "",
        on: Callable[[], None] | None = None,
    ) -> None:
        self.text.setText(text)
        self.setStyleSheet(
            f"QFrame#toast {{ background: {theme.PANEL_2}; border: 1px solid {colour};"
            " border-radius: 12px; }"
        )
        self.action.setVisible(bool(action))
        self.action.setText(action)
        self._cb = on
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self.move(parent.width() - self.width() - 24, parent.height() - self.height() - 24)
        self.show()
        self.raise_()
        self.timer.start(7000)


def hex_view(data: bytes, at: int, before: int, width: int = 16, rows: int = 4) -> str:
    """Rich text: the bytes around ``at``, the flipped one highlighted with its old value."""
    start = max(0, (at // width - rows // 2) * width)
    lines = []
    for r in range(rows):
        off = start + r * width
        if off >= len(data):
            break
        cells = []
        for i in range(off, min(off + width, len(data))):
            if i == at:
                cells.append(
                    f'<span style="background:{theme.BAD}; color:#000; font-weight:700;">'
                    f"{data[i]:02x}</span>"
                )
            else:
                cells.append(f"{data[i]:02x}")
        lines.append(f'<span style="color:{theme.MUTED}">{off:06x}</span>  ' + " ".join(cells))
    note = f"byte {at}: {before:02x} → {data[at]:02x} (one bit flipped)"
    return (
        f'<pre style="font-family:{theme.MONO}; font-size:10.5pt">'
        + "<br>".join(lines)
        + f'</pre><span style="color:{theme.BAD}">{note}</span>'
    )
