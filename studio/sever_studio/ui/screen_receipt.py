"""The receipt screen (offline verification, tampering, the limits) and the log screen (the
signed public log, its witnesses, the auditor)."""

import json
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..actions import Verified
from . import theme
from .host import Host
from .widgets import (
    Card,
    Console,
    StepList,
    Tile,
    badge,
    button,
    hex_view,
    label,
    tick,
    tick_colour,
)


class ReceiptScreen(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        lay = QHBoxLayout(self)
        lay.setSpacing(14)
        left = QVBoxLayout()
        left.addWidget(label("Receipts", "h2"))
        left.addWidget(
            label(
                "Every deletion's certificate, kept for the person it belongs to.",
                "muted",
                wrap=True,
            )
        )
        self.list = QListWidget()
        self.list.setFixedWidth(300)
        self.list.currentItemChanged.connect(lambda *_: self.pick())
        left.addWidget(self.list, 1)
        lay.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(12)
        head = Card(
            "Check it offline",
            "The person gets two files: the certificate and the public trust anchors. sever-verify "
            "is a separate program that shares no code with the database; it runs in a folder "
            "holding only those two files, with no database access (§11.3).",
        )
        self.picked = label(
            "Pick a receipt on the left, or delete something on the map.", "h3", wrap=True
        )
        head.add(self.picked)
        row = QHBoxLayout()
        self.b_verify = button("Verify", "primary", self.verify)
        self.b_tamper = button("Flip one byte and verify the copy", "danger", self.tamper)
        row.addWidget(self.b_verify)
        row.addWidget(self.b_tamper)
        row.addStretch(1)
        head.body.addLayout(row)
        self.folder = label("", "muted", wrap=True)
        head.add(self.folder)
        right.addWidget(head)
        self.steps = StepList()
        right.addWidget(self.steps)
        self.hex = QLabel()
        self.hex.setTextFormat(Qt.TextFormat.RichText)
        right.addWidget(self.hex)
        limits = Card("What a certificate does not prove", "")
        self.limits = label("", wrap=True)
        limits.add(self.limits)
        right.addWidget(limits)
        right.addStretch(1)
        lay.addLayout(right, 1)
        self.lsn: int | None = None

    def arrive(self, **kw: Any) -> None:
        self.list.clear()
        b = self.host.studio.backend
        target = kw.get("lsn")
        for lsn in reversed(b.index.receipts):
            rid, acc = self.host.receipts_of.get(lsn, ("", ""))
            item = QListWidgetItem(f"{lsn}.cert" + (f"   {rid}" if rid else ""))
            item.setData(Qt.ItemDataRole.UserRole, lsn)
            if acc:
                item.setToolTip(f"account {acc}")
            self.list.addItem(item)
            if lsn == target:
                self.list.setCurrentItem(item)
        if target is None and self.list.count():
            self.list.setCurrentRow(0)
        self.limits.setText("<br>".join(f"• {t}" for t in self.host.studio.limits()))
        self.host.changed()

    def pick(self) -> None:
        item = self.list.currentItem()
        self.lsn = int(item.data(Qt.ItemDataRole.UserRole)) if item else None
        if self.lsn is not None:
            rid, acc = self.host.receipts_of.get(self.lsn, ("", ""))
            self.picked.setText(
                f"Certificate at log position {self.lsn}"
                + (f": the deletion of {rid} ({acc})" if rid else "")
            )
            self.hex.setText("")

    def _show(self, v: Verified) -> None:
        self.steps.show_steps([(str(s.number), s.checks, s.verdict) for s in v.steps], v.verdict)
        self.folder.setText(
            f"in {v.folder.relative_to(self.host.studio.work.parent.parent)}: "
            + ", ".join(sorted(p.name for p in v.folder.iterdir()))
            + f" · exit code {v.code}"
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

        def done(v: Verified) -> None:
            if v.flipped:
                at, old, _ = v.flipped
                self.hex.setText(hex_view(v.certificate, at, old))
            self._show(v)

        self.host.worker.submit(lambda: self.host.studio.tamper(lsn), done, self.host.error)


class LogScreen(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.addWidget(label("The public log", "h2"))
        lay.addWidget(
            label(
                "Every insert and every deletion is a leaf of an append-only Merkle tree (RFC "
                "9162). The operator signs each checkpoint of it, and independent witnesses cosign "
                "it, so the operator cannot show one history to one person and another to someone "
                "else "
                "(§10).",
                "muted",
                wrap=True,
            )
        )
        tiles = QHBoxLayout()
        self.t_size = Tile("leaves in the log")
        self.t_epoch = Tile("key epoch")
        self.t_wit = Tile("witnesses cosigned (at least 4 needed)")
        self.t_path = Tile("hashes in the newest leaf's inclusion proof")
        for t in (self.t_size, self.t_epoch, self.t_wit, self.t_path):
            tiles.addWidget(t)
        lay.addLayout(tiles)
        self.root = label("", "mono", wrap=True)
        lay.addWidget(self.root)
        self.wit = QHBoxLayout()
        lay.addLayout(self.wit)
        lay.addWidget(button("Read the latest checkpoint", "", self.read))
        audit = Card(
            "The auditor",
            "sever-audit, another separate program, gets the exported log, the anchors and every "
            "certificate. It replays the whole tree, checks every checkpoint and cosignature, that "
            "each certificate's deletion is in the log, and that each group's certificates chain "
            "(§11.3, §15.4).",
        )
        audit.add(button("Export the log and audit it", "primary", self.audit))
        self.audit_res = label("", "h3", wrap=True)
        audit.add(self.audit_res)
        self.console = Console(110)
        audit.add(self.console)
        lay.addWidget(audit)
        lay.addStretch(1)

    def arrive(self, **kw: Any) -> None:
        self.read()

    def read(self) -> None:
        def done(log: dict[str, Any]) -> None:
            self.t_size.set(f"{log['tree_size']:,}")
            self.t_epoch.set(str(log["epoch"]))
            ok = log["witnesses"] >= 4
            self.t_wit.set(str(log["witnesses"]), theme.OK if ok else theme.BAD)
            self.t_path.set(str(log["inclusion_path"]))
            self.root.setText(f"root hash {log['root']}")
            while self.wit.count():
                item = self.wit.takeAt(0)
                w = item.widget() if item is not None else None
                if w is not None:
                    w.deleteLater()
            for idx, ep in log["cosignatures"]:
                self.wit.addWidget(badge(f"✓ witness {idx} · epoch {ep}", theme.OK))
            self.wit.addStretch(1)
            self.host.changed()

        self.host.worker.submit(self.host.studio.log, done, self.host.error)

    def audit(self) -> None:
        def done(out: tuple[int, str]) -> None:
            code, text = out
            ok = code == 0
            try:
                d = json.loads(text)
                summary = (
                    f"{d['leaves']:,} leaves, {d['checkpoints']} checkpoints,"
                    f" {len(d['findings'])} findings"
                )
            except (ValueError, KeyError, TypeError):
                summary = text[:120]
            self.audit_res.setText(
                f"<span style='color:{tick_colour(ok)}'>{tick(ok)}</span> sever-audit: {summary}"
            )
            self.console.say(text)
            self.host.changed()

        self.host.worker.submit(self.host.studio.audit, done, self.host.error)
