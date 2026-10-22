"""Under the hood: the public log, the disk, crashes, and what the database refuses."""

import json
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QSpinBox, QTabWidget, QVBoxLayout, QWidget

from ..actions import Crashed, Disk
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
        self.t_wit = Tile("witnesses signed")
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
                self.witnesses.addWidget(chip(f"✓ witness {idx}", theme.OK))
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
        for col, kind in enumerate(("record IDs", "passage text", "vectors"), 1):
            for row, side in enumerate(("naive", "sever")):
                t = Tile(f"{kind} found")
                self.tiles[(side, kind)] = t
                grid.addWidget(t, row, col)
        lay.addLayout(grid)
        self.files = label("", "small")
        lay.addWidget(self.files)
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


class CrashTab(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        w, lay = page(copy.short("crash.about"), "crash.about")
        QVBoxLayout(self).addWidget(w)
        row = QHBoxLayout()
        row.addWidget(label("Writes to attempt"))
        self.count = QSpinBox()
        self.count.setRange(20, 2000)
        self.count.setValue(200 if host.studio.data == "nq" else 40)
        row.addWidget(self.count)
        row.addWidget(button("Pull the plug", "danger", self.crash, "zap"))
        row.addStretch(1)
        lay.addLayout(row)
        self.phase = Verdict()
        lay.addWidget(self.phase)
        tiles = QHBoxLayout()
        self.t_acked = Tile("confirmed before the kill")
        self.t_missing = Tile("missing after recovery")
        self.t_flight = Tile("the write in flight landed")
        for t in (self.t_acked, self.t_missing, self.t_flight):
            tiles.addWidget(t)
        lay.addLayout(tiles)
        restart = QHBoxLayout()
        restart.addWidget(button("Restart the database", "", self.restart, "refresh"))
        self.r_res = Verdict()
        restart.addWidget(self.r_res, 1)
        lay.addLayout(restart)
        lay.addStretch(1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)

    def arrive(self) -> None:
        pass

    def restart(self) -> None:
        def done(out: tuple[int, int, bool]) -> None:
            before, after, gone = out
            self.r_res.set(
                before == after and gone,
                f"{before:,} records before, {after:,} after; deleted stay deleted",
            )
            self.host.changed()

        self.r_res.set(None, "closing and reopening…")
        self.host.worker.submit(self.host.studio.restart, done, self.host.error)

    def _poll(self) -> None:
        acks = self.host.studio.work / "acks.txt"
        n = len(acks.read_text("utf-8").splitlines()) if acks.exists() else 0
        self.t_acked.set(str(n), theme.ACCENT)
        if n >= self.count.value() // 2:
            self.phase.set(None, "killed · recovering · checking…")

    def crash(self) -> None:
        count = self.count.value()
        self.phase.set(None, "writing…")
        self.t_missing.set("—")
        self.t_flight.set("—")
        (self.host.studio.work / "acks.txt").unlink(missing_ok=True)
        self.timer.start(60)

        def done(c: Crashed) -> None:
            self.timer.stop()
            ok = c.killed and c.missing == 0 and c.acked > 0
            self.t_acked.set(str(c.acked))
            self.t_missing.set(str(c.missing), theme.OK if c.missing == 0 else theme.BAD)
            self.t_flight.set("—" if c.committed is None else ("yes" if c.committed else "no"))
            self.phase.set(
                ok, "nothing confirmed was lost" if ok else "a confirmed write is missing"
            )
            self.host.changed()

        def failed(msg: str) -> None:
            self.timer.stop()
            self.host.error(msg)

        self.host.worker.submit(lambda: self.host.studio.crash(count), done, failed)


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
    TABS = ("log", "disk", "crash", "rules")

    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        self.tabs: dict[str, Any] = {
            "log": LogTab(host),
            "disk": DiskTab(host),
            "crash": CrashTab(host),
            "rules": RulesTab(host),
        }
        names = {"log": "Public log", "disk": "Disk", "crash": "Crash", "rules": "Bad input"}
        for k in self.TABS:
            self.addTab(self.tabs[k], names[k])
        self.currentChanged.connect(lambda i: self.tabs[self.TABS[i]].arrive())

    def arrive(self, tab: str | None = None, **kw: Any) -> None:
        if tab:
            self.setCurrentIndex(self.TABS.index(tab))
        self.tabs[self.TABS[self.currentIndex()]].arrive()
