"""The disk screen (what a thief with a copy of the disk would find) and the crash screen (a clean
restart, then a writer killed in the middle of its inserts)."""

from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QSpinBox, QVBoxLayout, QWidget

from ..actions import Crashed, Disk
from . import theme
from .host import Host
from .widgets import Card, Tile, button, label, tick, tick_colour


class DiskScreen(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.addWidget(label("What is on the disk", "h2"))
        lay.addWidget(
            label(
                "A raw byte search of every file under data/ and keys/, as someone holding a copy "
                "of the disk would run it, for 40 live records: each one's ID, two windows of its "
                "text and its vector. First over an ordinary store of the same records, to show "
                "the search can see. Only public values are stored in the clear (§13.2): group "
                "sizes, commitments, centroids, scrambled IDs, the log and the certificates.",
                "muted",
                wrap=True,
            )
        )
        lay.addWidget(button("Search both disks", "primary", self.scan))
        grid = QGridLayout()
        grid.setSpacing(12)
        self.naive = Card("An ordinary store", "the same records, as most stores keep them")
        self.sever = Card("SEVER-DB", "data/ and keys/ of the database in use")
        self.tiles: dict[str, dict[str, Tile]] = {"naive": {}, "sever": {}}
        for side, card in (("naive", self.naive), ("sever", self.sever)):
            row = QHBoxLayout()
            for kind in ("record IDs", "passage text", "vectors"):
                t = Tile(f"{kind} found")
                self.tiles[side][kind] = t
                row.addWidget(t)
            card.body.addLayout(row)
        grid.addWidget(self.naive, 0, 0)
        grid.addWidget(self.sever, 0, 1)
        lay.addLayout(grid)
        self.files = label("", "mono", wrap=True)
        files = Card("The largest files", "")
        files.add(self.files)
        lay.addWidget(files)
        lay.addWidget(
            label(
                "The stronger claim, that nothing deleted can be recovered even with the key file, "
                "is on the Proofs screen (Part 4: the forensic scanner).",
                "muted",
                wrap=True,
            )
        )
        lay.addStretch(1)

    def arrive(self, **kw: Any) -> None:
        pass

    def scan(self) -> None:
        def done(d: Disk) -> None:
            for side, hits in (("naive", d.naive), ("sever", d.sever)):
                for kind, (found, n) in hits.items():
                    good = found == n if side == "naive" else found == 0
                    colour = (theme.BAD if found else theme.OK) if side == "sever" else theme.WARN
                    self.tiles[side][kind].set(f"{found} / {n}", colour if good else theme.BAD)
            self.files.setText(
                f"{d.files} files, {d.size / 1e6:.1f} MB<br>"
                + "<br>".join(f"{size / 1e3:>9,.0f} kB  {name}" for name, size in d.biggest)
            )
            self.host.changed()

        self.host.worker.submit(self.host.studio.disk, done, self.host.error)


class CrashScreen(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.addWidget(label("Restart, and pull the plug", "h2"))
        restart = Card(
            "A clean restart",
            "Close the database and open it again: recovery and the full invariant check run "
            "first. Every record must still be there, and every deleted one still gone.",
        )
        self.r_res = label("", wrap=True)
        restart.add(button("Restart the database", "", self.restart))
        restart.add(self.r_res)
        lay.addWidget(restart)
        crash = Card(
            "A writer killed with SIGKILL",
            "A second process inserts the next passages, writing down each one the database "
            "acknowledged. Half-way it is killed, as a power cut would stop it: no clean shutdown, "
            "no flush. After recovery, every insert it was told was stored must be there (§12, "
            "§15.1). The insert in flight may have committed or not; the database decides, and "
            "the application asks it.",
        )
        row = QHBoxLayout()
        row.addWidget(label("inserts to attempt"))
        self.count = QSpinBox()
        self.count.setRange(20, 2000)
        self.count.setValue(200 if host.studio.data == "nq" else 40)
        row.addWidget(self.count)
        row.addWidget(button("Pull the plug", "danger", self.crash))
        row.addStretch(1)
        crash.body.addLayout(row)
        self.phase = label("", "h3", wrap=True)
        crash.add(self.phase)
        tiles = QHBoxLayout()
        self.t_acked = Tile("acknowledged before the kill")
        self.t_missing = Tile("acknowledged but missing after recovery")
        self.t_flight = Tile("the insert in flight had committed")
        for t in (self.t_acked, self.t_missing, self.t_flight):
            tiles.addWidget(t)
        crash.body.addLayout(tiles)
        lay.addWidget(crash)
        lay.addStretch(1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)

    def arrive(self, **kw: Any) -> None:
        pass

    def restart(self) -> None:
        def done(out: tuple[int, int, bool]) -> None:
            before, after, gone = out
            ok = before == after and gone
            self.r_res.setText(
                f"{before:,} records before, {after:,} after; this session's deleted records still"
                f" absent: {'yes' if gone else 'NO'}<br>"
                f"<span style='color:{tick_colour(ok)}'>{tick(ok)}"
                " nothing lost, nothing back</span>"
            )
            self.host.changed()

        self.r_res.setText("closing, reopening (recovery, invariant check)…")
        self.host.worker.submit(self.host.studio.restart, done, self.host.error)

    def _poll(self) -> None:
        acks = self.host.studio.work / "acks.txt"
        n = len(acks.read_text("utf-8").splitlines()) if acks.exists() else 0
        self.t_acked.set(str(n), theme.ACCENT)
        if n >= self.count.value() // 2:
            self.phase.setText(
                "killed (SIGKILL) · recovering · checking every acknowledged insert…"
            )

    def crash(self) -> None:
        count = self.count.value()
        self.phase.setText("the writer is inserting…")
        self.t_missing.set("—")
        self.t_flight.set("—")
        (self.host.studio.work / "acks.txt").unlink(missing_ok=True)
        self.timer.start(60)

        def done(c: Crashed) -> None:
            self.timer.stop()
            ok = c.killed and c.missing == 0 and c.acked > 0
            self.t_acked.set(str(c.acked))
            self.t_missing.set(str(c.missing), theme.OK if c.missing == 0 else theme.BAD)
            self.t_flight.set(
                "—" if c.committed is None else ("yes" if c.committed else "no"), theme.TEXT
            )
            self.phase.setText(
                f"<span style='color:{tick_colour(ok)}'>{tick(ok)}</span> "
                + ("killed" if c.killed else "finished before the kill")
                + f" after {c.acked} acknowledged inserts; after recovery every one is there"
                + ("" if c.missing == 0 else f" except {c.missing}")
            )
            self.host.changed()

        self.host.worker.submit(lambda: self.host.studio.crash(count), done, self.host.error)
