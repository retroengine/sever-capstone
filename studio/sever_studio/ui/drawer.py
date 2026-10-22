"""The checklist drawer: 33 features in five groups, each ticked only by a live check."""

from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..checklist import BY_KEY, Checklist
from . import copy, theme
from .widgets import button, label, lift, mark


class Drawer(QFrame):
    WIDTH = 320

    def __init__(
        self,
        parent: QWidget,
        checklist: Checklist,
        show_row: Callable[[str], None],
        save: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.setObjectName("drawer")
        lift(self)
        self.checklist = checklist
        self.setFixedWidth(self.WIDTH)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 12, 14)
        head = QHBoxLayout()
        self.head = label("", "heading")
        head.addWidget(self.head, 1)
        head.addWidget(button("", "ghost", self.close_drawer, "x", "Close"))
        lay.addLayout(head)
        lay.addWidget(label("Ticked only by a live check.", "small"))
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(2)
        self.rows: dict[str, QPushButton] = {}
        self.group_heads: list[tuple[str, list[str], QLabel]] = []
        for group, rows in copy.GROUPS:
            gh = label("", "strong")
            gh.setContentsMargins(0, 10, 0, 2)
            il.addWidget(gh)
            self.group_heads.append((group, [k for k, _ in rows], gh))
            for key, title in rows:
                b = QPushButton(title)
                b.setObjectName("ghost")
                b.setStyleSheet("text-align: left; padding: 5px 6px;")
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setToolTip(f"{BY_KEY[key].title} ({BY_KEY[key].spec}). Click to show it.")
                b.clicked.connect(partial(show_row, key))
                il.addWidget(b)
                self.rows[key] = b
        il.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        lay.addWidget(scroll, 1)
        lay.addWidget(button("Save the session report", "", save, "log"))
        self.anim = QPropertyAnimation(self, b"pos", self)
        self.anim.setDuration(220)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.hide()
        self.refresh()

    def refresh(self) -> None:
        v = self.checklist.verdicts
        for key, b in self.rows.items():
            verdict = v.get(key)
            sign, colour = mark(verdict.ok if verdict else None)
            b.setText(f"{sign}   {copy.CHECK_SHORT[key]}")
            b.setStyleSheet(
                f"text-align: left; padding: 5px 6px; color: {colour if verdict else theme.MUTED};"
            )
            if verdict:
                b.setToolTip(f"{BY_KEY[key].title} ({BY_KEY[key].spec})\n{verdict.detail}")
        for group, keys, gh in self.group_heads:
            done = sum(1 for k in keys if v.get(k) and v[k].ok)
            gh.setText(f"{group}  <span style='color:{theme.MUTED}'>{done}/{len(keys)}</span>")
        self.head.setText(f"Checklist {self.checklist.passed()}/{len(BY_KEY)}")

    def toggle(self) -> None:
        if self.isVisible():
            self.close_drawer()
        else:
            self.open_drawer()

    def open_drawer(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setFixedHeight(parent.height())
        self.move(parent.width(), 0)
        self.show()
        self.raise_()
        self.anim.setStartValue(QPoint(parent.width(), 0))
        self.anim.setEndValue(QPoint(parent.width() - self.WIDTH, 0))
        self.anim.start()

    def close_drawer(self) -> None:
        self.hide()

    def place(self) -> None:
        parent = self.parentWidget()
        if parent is not None and self.isVisible():
            self.setFixedHeight(parent.height())
            self.move(parent.width() - self.WIDTH, 0)
