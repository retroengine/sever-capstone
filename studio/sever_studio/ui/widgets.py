"""Small building blocks shared by every section."""

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import copy, theme
from .icons import icon


def lift(w: QWidget, blur: int = 28) -> None:
    """A soft shadow under a floating panel (light theme only: on dark it would not show)."""
    if theme.LIGHT:
        shadow = QGraphicsDropShadowEffect(w)
        shadow.setBlurRadius(blur)
        shadow.setOffset(0, 4)
        c = QColor(theme.SHADOW)
        c.setAlpha(38)
        shadow.setColor(c)
        w.setGraphicsEffect(shadow)


def label(text: str = "", kind: str = "", wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if kind:
        lab.setObjectName(kind)
    lab.setWordWrap(wrap)
    return lab


def button(
    text: str = "",
    kind: str = "",
    on: Callable[[], None] | None = None,
    ico: str | None = None,
    tip: str = "",
) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if ico:
        colour = theme.ON_ACCENT if kind in ("primary", "fab") else theme.TEXT
        b.setIcon(icon(ico, colour))
        b.setIconSize(QSize(16, 16))
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on is not None:
        b.clicked.connect(lambda: on())
    return b


def clear(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget() if item is not None else None
        if w is not None:
            w.deleteLater()


def chip(text: str, colour: str = theme.ACCENT) -> QLabel:
    c = QLabel(text)
    c.setStyleSheet(
        f"background: {theme.rgba(colour, 34)}; color: {colour}; border: 1px solid"
        f" {theme.rgba(colour, 110)}; border-radius: 9px; padding: 2px 9px;"
        f" font-size: {theme.pt(theme.SMALL)}pt; font-weight: 600;"
    )
    c.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return c


def mark(ok: bool | None) -> tuple[str, str]:
    """The sign and colour of a verdict: ✓ green, ✗ red, ○ grey (not yet shown)."""
    if ok is None:
        return "○", theme.MUTED
    return ("✓", theme.OK) if ok else ("✗", theme.BAD)


class Popover(QFrame):
    """A small panel of explanation that closes when you click anywhere else."""

    def __init__(self, title: str, text: str) -> None:
        super().__init__(None, Qt.WindowType.Popup)
        self.setObjectName("popover")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.addWidget(label(title, "strong"))
        body = label(text, wrap=True)
        body.setFixedWidth(340)
        lay.addWidget(body)

    def show_below(self, anchor: QWidget) -> None:
        self.adjustSize()
        p = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        screen = anchor.screen().availableGeometry()
        x = min(p.x(), screen.right() - self.width() - 8)
        y = (
            p.y()
            if p.y() + self.height() < screen.bottom()
            else p.y() - self.height() - anchor.height() - 12
        )
        self.move(max(screen.left() + 8, x), y)
        self.show()


def info(key: str) -> QPushButton:
    """ⓘ: the long explanation of ``key`` in a popover."""
    b = QPushButton()
    b.setObjectName("ghost")
    b.setIcon(icon("info", theme.MUTED, 16))
    b.setIconSize(QSize(16, 16))
    b.setToolTip("Why?")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFixedSize(26, 26)
    b.clicked.connect(lambda: Popover(copy.short(key), copy.long(key)).show_below(b))
    return b


class Card(QFrame):
    """A rounded panel: a title (with an optional ⓘ) and a body."""

    def __init__(self, title: str = "", why: str = "", kind: str = "card") -> None:
        super().__init__()
        self.setObjectName(kind)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 14)
        self.lay.setSpacing(8)
        if title or why:
            head = QHBoxLayout()
            head.setSpacing(4)
            self.title = label(title, "strong")
            head.addWidget(self.title, 1)
            if why:
                head.addWidget(info(why))
            self.lay.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        self.lay.addLayout(self.body)
        self.lay.addStretch(1)

    def add(self, w: QWidget) -> QWidget:
        self.body.addWidget(w)
        return w


class Tile(QFrame):
    """A big number and a caption."""

    def __init__(self, caption: str, value: str = "—") -> None:
        super().__init__()
        self.setObjectName("card2")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.value = label(value, "big")
        lay.addWidget(self.value)
        lay.addWidget(label(caption, "small", wrap=True))

    def set(self, value: str, colour: str = theme.TEXT) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color: {colour};")


class Verdict(QLabel):
    """A one-line result: sign, colour, a few words."""

    def __init__(self) -> None:
        super().__init__("")
        self.setWordWrap(True)

    def set(self, ok: bool | None, text: str) -> None:
        sign, colour = mark(ok)
        self.setText(f"<span style='color:{colour}; font-weight:700'>{sign}</span>&nbsp; {text}")

    def warn(self, text: str) -> None:
        """Neither passed nor failed: a check that held only with an override."""
        c = theme.WARN
        self.setText(f"<span style='color:{c}; font-weight:700'>⚠</span>&nbsp; {text}")


class Spinner(QWidget):
    """A turning arc while the worker is busy."""

    def __init__(self, size: int = 18) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._turn)
        self.hide()

    def run(self, on: bool) -> None:
        self.setVisible(on)
        if on:
            self.timer.start(30)
        else:
            self.timer.stop()

    def _turn(self) -> None:
        self.angle = (self.angle + 12) % 360
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt's name)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(theme.ACCENT), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        r = QRectF(2, 2, self.width() - 4, self.height() - 4)
        p.drawArc(r, -self.angle * 16, 270 * 16)
        p.end()


class Console(QPlainTextEdit):
    def __init__(self, height: int = 180) -> None:
        super().__init__()
        self.setObjectName("console")
        self.setReadOnly(True)
        self.setMinimumHeight(height)
        self.setMaximumBlockCount(4000)

    def say(self, text: str) -> None:
        self.appendPlainText(text)
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())


class Heatmap(QWidget):
    """A vector's numbers as a strip of cells: blue below zero, red above, white near zero."""

    def __init__(self, cols: int = 48) -> None:
        super().__init__()
        self.cols = cols
        self.values: npt.NDArray[np.float64] = np.zeros(0)
        self.setMinimumHeight(24)

    def set(self, vector: Sequence[float] | npt.NDArray[np.floating[Any]]) -> None:
        self.values = np.asarray(vector, np.float64)
        rows = max(1, -(-len(self.values) // self.cols))
        self.setFixedHeight(rows * 6 + 2)
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
            p.fillRect(QRectF(1 + col * w, 1 + r * 6, w - 0.5, 5), c)
        p.end()


class StepDots(QWidget):
    """The verifier's steps as numbered dots, lit one after another: green passed, red failed,
    grey not reached or not applicable. Each dot's tooltip says what the step checks."""

    def __init__(self) -> None:
        super().__init__()
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(10)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._next)
        self.queue: list[tuple[QLabel, str]] = []

    def show_steps(self, steps: Sequence[tuple[int, str, str]], delay: int = 180) -> None:
        clear(self.lay)
        self.queue = []
        for n, checks, verdict in steps:
            state = (
                "ok" if verdict == "ok" else ("fail" if verdict.startswith("FAILED") else "skip")
            )
            colour = {"ok": theme.OK, "fail": theme.BAD, "skip": theme.LINE}[state]
            dot = QLabel(str(n))
            dot.setFixedSize(34, 34)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setToolTip(f"step {n}: {checks}\n→ {verdict}")
            dot.setStyleSheet(
                f"border-radius: 17px; border: 2px solid {theme.LINE}; color: {theme.MUTED};"
                " font-weight: 700;"
            )
            self.lay.addWidget(dot)
            self.queue.append((dot, colour))
        self.lay.addStretch(1)
        self.timer.start(delay)

    def _next(self) -> None:
        if not self.queue:
            self.timer.stop()
            return
        dot, colour = self.queue.pop(0)
        dot.setStyleSheet(
            f"border-radius: 17px; background: {theme.rgba(colour, 60)}; border: 2px solid "
            f"{colour};"
            f" color: {theme.TEXT}; font-weight: 700;"
        )


class Flow(QWidget):
    """A diagram as boxes joined by arrows, each a step's title and its real numbers, lit one
    after another (``explain`` builds the steps)."""

    def __init__(self, vertical: bool = True) -> None:
        super().__init__()
        self.vertical = vertical
        self.lay: QVBoxLayout | QHBoxLayout = QVBoxLayout(self) if vertical else QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(2)
        self.boxes: list[QFrame] = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._next)
        self.lit = 0

    def set(self, steps: Sequence[tuple[str, str]], delay: int = 0) -> None:
        clear(self.lay)
        self.boxes = []
        for i, (title, body) in enumerate(steps):
            if i:
                arrow = label("↓" if self.vertical else "→", "muted")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.lay.addWidget(arrow)
            box = QFrame()
            box.setObjectName("card2")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(10, 6, 10, 6)
            bl.setSpacing(1)
            bl.addWidget(label(title, "strong", wrap=True))
            bl.addWidget(label(body, "small", wrap=True))
            self.lay.addWidget(box, 1)
            self.boxes.append(box)
        self.lit = 0
        if delay:
            for b in self.boxes:
                b.setStyleSheet(f"QFrame#card2 {{ border: 1px solid {theme.LINE}; }}")
            self.timer.start(delay)
        else:
            self.lit = len(self.boxes)
            self._paint()

    def _next(self) -> None:
        self.lit += 1
        self._paint()
        if self.lit >= len(self.boxes):
            self.timer.stop()

    def _paint(self) -> None:
        for i, b in enumerate(self.boxes):
            c = theme.ACCENT if i < self.lit else theme.LINE
            b.setStyleSheet(f"QFrame#card2 {{ border: 1px solid {c}; }}")


class StepList(QWidget):
    """The verifier's steps (§11.3) as a labelled list: number, what it checks, its verdict."""

    def __init__(self) -> None:
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(3)

    def show_steps(self, steps: Sequence[tuple[int, str, str]]) -> None:
        clear(self.lay)
        for n, checks, verdict in steps:
            ok = None if not (verdict == "ok" or verdict.startswith("FAILED")) else verdict == "ok"
            sign, colour = mark(ok)
            why = "" if ok is not None else f" <span style='color:{theme.MUTED}'>({verdict})</span>"
            if ok is False:
                why = f" <span style='color:{theme.BAD}'>{verdict}</span>"
            self.lay.addWidget(
                label(
                    f"<span style='color:{colour}; font-weight:700'>{sign}</span>&nbsp; "
                    f"<b>{n}</b>&nbsp; {checks}{why}",
                    wrap=True,
                )
            )


class Timeline(QWidget):
    """Kill moments on one deletion's measured duration: each a mark at its share of the time,
    coloured by what recovery found."""

    def __init__(self) -> None:
        super().__init__()
        self.marks: list[tuple[float, str]] = []
        self.setMinimumHeight(54)

    def set(self, marks: list[tuple[float, str]]) -> None:
        self.marks = marks
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt's name)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right, y = 12.0, self.width() - 12.0, self.height() / 2
        p.setPen(QPen(QColor(theme.LINE), 3))
        p.drawLine(QPointF(left, y), QPointF(right, y))
        p.setPen(QColor(theme.MUTED))
        p.setFont(theme.font(theme.SMALL))
        p.drawText(QRectF(left, y + 8, 200, 18), Qt.AlignmentFlag.AlignLeft, "deletion starts")
        p.drawText(QRectF(right - 200, y + 8, 200, 18), Qt.AlignmentFlag.AlignRight, "it ends")
        colours = {"none": theme.FROZEN, "all": theme.OK, "partial": theme.BAD}
        for share, outcome in self.marks:
            x = left + (right - left) * min(1.0, max(0.0, share))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(colours.get(outcome, theme.MUTED)))
            p.drawEllipse(QPointF(x, y), 6, 6)
        p.end()


class Empty(QWidget):
    """What a section shows before there is anything in it."""

    def __init__(self, ico: str, text: str) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        pic = QLabel()
        pic.setPixmap(icon(ico, theme.MUTED, 40).pixmap(40, 40))
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(pic)
        t = label(text, "muted", wrap=True)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        lay.addStretch(1)


class Toast(QFrame):
    """One line at the bottom centre, with at most one action; leaves by itself."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("float")
        lift(self)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 8, 8)
        lay.setSpacing(10)
        self.sign = QLabel()
        lay.addWidget(self.sign)
        self.text = label("")
        lay.addWidget(self.text, 1)
        self.action = button("", "pill")
        lay.addWidget(self.action)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self._cb: Callable[[], None] | None = None
        self.action.clicked.connect(self._act)
        self.hide()

    def _act(self) -> None:
        if self._cb:
            self._cb()
        self.hide()

    def pop(
        self,
        text: str,
        ok: bool | None = True,
        action: str = "",
        on: Callable[[], None] | None = None,
    ) -> None:
        sign, colour = mark(ok) if ok is not None else ("•", theme.ACCENT)
        self.sign.setText(f"<span style='color:{colour}; font-weight:800'>{sign}</span>")
        self.text.setText(text)
        self.action.setVisible(bool(action))
        self.action.setText(action)
        self._cb = on
        self.place()
        self.show()
        self.raise_()
        self.timer.start(6000 if not action else 9000)

    def place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.text.setMaximumWidth(min(620, parent.width() - 180))
        self.adjustSize()
        self.move((parent.width() - self.width()) // 2, 68)


def hex_view(data: bytes, at: int, before: int, width: int = 16, rows: int = 3) -> str:
    """Rich text: the bytes around ``at``, the flipped one highlighted with its old value."""
    start = max(0, (at // width - rows // 2) * width)
    lines = []
    for r in range(rows):
        off = start + r * width
        if off >= len(data):
            break
        cells = []
        for i in range(off, min(off + width, len(data))):
            hot = f'<span style="background:{theme.BAD}; color:#000; font-weight:700;">'
            cells.append(f"{hot}{data[i]:02x}</span>" if i == at else f"{data[i]:02x}")
        lines.append(f'<span style="color:{theme.MUTED}">{off:06x}</span>  ' + " ".join(cells))
    return (
        f'<pre style="font-family:{theme.MONO}; font-size:{theme.pt(theme.SMALL)}pt">'
        + "<br>".join(lines)
        + f'</pre><span style="color:{theme.BAD}">byte {at}: {before:02x} → {data[at]:02x}</span>'
    )
