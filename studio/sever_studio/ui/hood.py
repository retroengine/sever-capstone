"""Under the hood: the public log, the disk, and what the database refuses."""

import json
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from ..actions import Disk
from ..backend import Inserted
from . import copy, theme
from .host import Host
from .widgets import Tile, Verdict, button, chip, clear, info, label

LEFT = Qt.AlignmentFlag.AlignLeft


def page(title: str, why: str) -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(24, 20, 24, 20)
    lay.setSpacing(16)
    head = QHBoxLayout()
    head.addWidget(label(title, "heading"))
    head.addWidget(info(why))
    head.addStretch(1)
    lay.addLayout(head)
    return w, lay


class LogTab(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        w, lay = page(copy.short("log.about"), "log.about")
        QVBoxLayout(self).addWidget(w)
        tiles = QHBoxLayout()
        self.t_size = Tile("leaves")
        self.t_wit = Tile("witnesses listed (simulated, L-7)")
        self.t_path = Tile("hashes in a proof")
        for t in (self.t_size, self.t_wit, self.t_path):
            tiles.addWidget(t)
        lay.addLayout(tiles)
        self.witnesses = QHBoxLayout()
        lay.addLayout(self.witnesses)
        audit = QHBoxLayout()
        audit.addWidget(button("Audit the whole log", "primary", self.audit, "shield"))
        self.audit_res = Verdict()
        audit.addWidget(self.audit_res, 1)
        lay.addLayout(audit)
        lay.addStretch(1)

    def arrive(self) -> None:
        def done(log: dict[str, Any]) -> None:
            self.t_size.set(f"{log['tree_size']:,}")
            self.t_wit.set(str(log["witnesses"]), theme.OK if log["witnesses"] >= 4 else theme.BAD)
            self.t_path.set(str(log["inclusion_path"]))
            clear(self.witnesses)
            for idx, _ in log["cosignatures"]:
                c = chip(f"witness {idx} listed", theme.OK)
                c.setToolTip(
                    "Listed in the checkpoint; the signature is checked by the auditor (Audit), "
                    "not here. In v1 the witnesses are simulated by the database (§10.4, L-7)."
                )
                self.witnesses.addWidget(c)
            self.witnesses.addStretch(1)
            self.host.changed()

        self.host.worker.submit(self.host.studio.log, done, self.host.error)

    def audit(self) -> None:
        def done(out: tuple[int, str]) -> None:
            code, text = out
            try:
                d = json.loads(text)
                summary = f"{d['leaves']:,} leaves, {len(d['findings'])} findings"
            except (ValueError, KeyError, TypeError):
                summary = text[:80]
            self.audit_res.set(code == 0, f"sever-audit: {summary}")
            self.audit_res.setToolTip(text)
            self.host.changed()

        self.audit_res.set(None, "auditing…")
        self.host.worker.submit(self.host.studio.audit, done, self.host.error)


class DiskTab(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        w, lay = page(copy.short("disk.about"), "disk.about")
        QVBoxLayout(self).addWidget(w)
        lay.addWidget(
            button("Search both disks", "primary", self.scan, "search"),
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        grid = QGridLayout()
        grid.setSpacing(12)
        self.tiles: dict[tuple[str, str], Tile] = {}
        grid.addWidget(label("An ordinary store", "strong"), 0, 0)
        grid.addWidget(label("SEVER-DB", "strong"), 1, 0)
        for col, kind in enumerate(
            ("record IDs", "passage text", "vectors", "x̃ (stored integers)"), 1
        ):
            for row, side in enumerate(("naive", "sever")):
                t = Tile(f"{kind} found")
                self.tiles[(side, kind)] = t
                grid.addWidget(t, row, col)
        lay.addLayout(grid)
        self.files = label("", "small")
        lay.addWidget(self.files)
        lay.addWidget(label(copy.long("disk.raw"), "small", wrap=True))
        lay.addStretch(1)

    def arrive(self) -> None:
        pass

    def scan(self) -> None:
        def done(d: Disk) -> None:
            for side, hits in (("naive", d.naive), ("sever", d.sever)):
                for kind, (found, n) in hits.items():
                    colour = (
                        theme.WARN if side == "naive" else (theme.OK if found == 0 else theme.BAD)
                    )
                    self.tiles[(side, kind)].set(f"{found}/{n}", colour)
            self.files.setText(f"{d.files} files · {d.size / 1e6:.1f} MB searched byte by byte")
            self.host.changed()

        self.host.worker.submit(self.host.studio.disk, done, self.host.error)


class RulesTab(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        w, lay = page(copy.short("rules.about"), "rules.about")
        QVBoxLayout(self).addWidget(w)
        lay.addWidget(
            button("Try five bad inputs", "primary", self.refusals, "x"),
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        self.rows = QVBoxLayout()
        lay.addLayout(self.rows)
        head = QHBoxLayout()
        head.addWidget(label(copy.short("retry.about"), "strong"))
        head.addWidget(info("retry.about"))
        head.addStretch(1)
        lay.addLayout(head)
        lay.addWidget(
            button("Send the same insert twice", "", self.retry, "refresh"),
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        self.retry_res = Verdict()
        lay.addWidget(self.retry_res)
        lay.addStretch(1)

    def arrive(self) -> None:
        pass

    def refusals(self) -> None:
        def done(rows: list[tuple[str, str, bool, str]]) -> None:
            clear(self.rows)
            for what, kind, ok, msg in rows:
                v = Verdict()
                v.set(ok, f"{what} → <b>{kind}</b>")
                v.setToolTip(msg)
                self.rows.addWidget(v)
            self.host.changed()

        self.host.worker.submit(self.host.studio.refusals, done, self.host.error)

    def retry(self) -> None:
        def done(out: tuple[Inserted, Inserted]) -> None:
            _, again = out
            self.retry_res.set(again.retried, "recognised as a retry; stored once")
            self.host.changed()

        self.host.worker.submit(self.host.studio.retry, done, self.host.error)


class Hood(QTabWidget):
    TABS = ("log", "disk", "rules")

    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        self.tabs: dict[str, Any] = {
            "log": LogTab(host),
            "disk": DiskTab(host),
            "rules": RulesTab(host),
        }
        names = {"log": "Public log", "disk": "Disk", "rules": "Bad input"}
        for k in self.TABS:
            self.addTab(self.tabs[k], names[k])
        self.currentChanged.connect(lambda i: self.tabs[self.TABS[i]].arrive())

    def arrive(self, tab: str | None = None, **kw: Any) -> None:
        if tab:
            self.setCurrentIndex(self.TABS.index(tab))
        self.tabs[self.TABS[self.currentIndex()]].arrive()
