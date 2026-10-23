"""Receipts: pick one, verify it offline, flip a byte and watch it fail."""

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..actions import Verified
from . import copy, theme
from .host import Host
from .widgets import Card, Empty, StepDots, button, info, label


class Receipts(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        self.lsn: int | None = None
        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(20)

        left = QVBoxLayout()
        left.addWidget(label("Receipts", "heading"))
        self.list = QListWidget()
        self.list.setMinimumWidth(200)
        self.list.setMaximumWidth(280)
        self.list.currentItemChanged.connect(lambda *_: self.pick())
        left.addWidget(self.list, 1)
        outer.addLayout(left)

        self.stack = QStackedWidget()
        self.empty = Empty("receipt", "No receipts yet.\nDelete something on the map.")
        self.stack.addWidget(self.empty)
        page = QWidget()
        right = QVBoxLayout(page)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(16)
        head = QHBoxLayout()
        self.picked = label("", "heading")
        head.addWidget(self.picked, 1)
        head.addWidget(info("receipt.about"))
        right.addLayout(head)
        self.who = label("", "muted")
        right.addWidget(self.who)
        row = QHBoxLayout()
        row.addWidget(button("Verify", "primary", self.verify, "check"))
        row.addWidget(button("Flip one byte", "danger", self.tamper, "zap"))
        row.addStretch(1)
        right.addLayout(row)
        self.dots = StepDots()
        right.addWidget(self.dots)
        self.verdict = label("", "title")
        right.addWidget(self.verdict)
        self.reason = label("", "muted", wrap=True)
        right.addWidget(self.reason)
        self.hex = QLabel()
        self.hex.setTextFormat(Qt.TextFormat.RichText)
        right.addWidget(self.hex)
        limits = Card(copy.short("receipt.limits"), "receipt.limits", "card2")
        limits.add(label("No copy kept · who asked · log consistency", "small"))
        right.addWidget(limits)
        right.addStretch(1)
        self.stack.addWidget(page)
        outer.addWidget(self.stack, 1)

    def arrive(self, **kw: Any) -> None:
        self.list.clear()
        b = self.host.studio.backend
        target = kw.get("lsn")
        for lsn in reversed(b.index.receipts):
            rid, _ = self.host.studio.backend.receipt_owner(lsn) or ("", "")
            item = QListWidgetItem(f"#{lsn}" + (f"   {rid}" if rid else ""))
            item.setData(Qt.ItemDataRole.UserRole, lsn)
            self.list.addItem(item)
            if lsn == target:
                self.list.setCurrentItem(item)
        if target is None and self.list.count():
            self.list.setCurrentRow(0)
        self.stack.setCurrentIndex(1 if self.list.count() else 0)
        if self.list.count():
            self.host.studio.limits()
            self.host.changed()

    def pick(self) -> None:
        item = self.list.currentItem()
        self.lsn = int(item.data(Qt.ItemDataRole.UserRole)) if item else None
        if self.lsn is None:
            return
        rid, acc = self.host.studio.backend.receipt_owner(self.lsn) or ("", "")
        self.picked.setText(f"Receipt #{self.lsn}")
        self.who.setText(
            f"the deletion of {rid} · {acc}" if rid else "a deletion made outside this application"
        )
        self.dots.show_steps([])
        self.verdict.setText("")
        self.reason.setText("")
        self.hex.setText("")

    def _show(self, v: Verified) -> None:
        self.dots.show_steps([(s.number, s.checks, s.verdict) for s in v.steps])
        good = v.verdict == "ACCEPT"
        colour = theme.OK if good else theme.BAD
        self.verdict.setText(
            f"<span style='color:{colour}'>{'ACCEPT' if good else 'REJECT'}</span>"
        )
        self.reason.setText(
            "Checked by sever-verify with only the receipt and the public anchors."
            if good
            else v.verdict.removeprefix("REJECT").strip(" ()")
        )
        self.host.changed()

    def verify(self) -> None:
        if self.lsn is None:
            return
        lsn = self.lsn
        self.hex.setText("")
        self.host.worker.submit(lambda: self.host.studio.verify(lsn), self._show, self.host.error)

    def tamper(self) -> None:
        if self.lsn is None:
            return
        lsn = self.lsn
        from .widgets import hex_view

        def done(v: Verified) -> None:
            if v.flipped:
                at, old, _ = v.flipped
                self.hex.setText(hex_view(v.certificate, at, old))
            self._show(v)

        self.host.worker.submit(lambda: self.host.studio.tamper(lsn), done, self.host.error)
