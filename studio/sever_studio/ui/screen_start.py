"""The start screen (the data, the machine check, the encoder, the groups) and the rules screen
(what the database refuses, and the safe retry)."""

from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..backend import Inserted
from . import theme
from .host import Host
from .widgets import Card, Tile, button, label, tick, tick_colour

CLAIMS = [
    (
        "1 · The Idea",
        "Deleting a vector returns its group, bit for bit, to the state it would have had if the "
        "vector had never arrived.",
    ),
    (
        "2 · The Database",
        "Exactness survives a crash at any point; no acknowledged operation is lost; a deletion "
        "across groups is all or nothing.",
    ),
    (
        "3 · The Receipt",
        "Every deletion yields a certificate that anyone can verify offline, with no database "
        "access.",
    ),
    (
        "4 · The Erasure",
        "After a deletion is acknowledged, nothing deleted can be recovered from raw storage.",
    ),
]


class StartScreen(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        s = host.studio
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.addWidget(label("SEVER-DB", "h1"))
        lay.addWidget(
            label(
                "A vector database with provable deletion. Each group keeps an exact integer sum, "
                "so a deletion subtracts exactly; every deletion yields a signed receipt anyone "
                "can check; and the keys that could open deleted data are destroyed.",
                "muted",
                wrap=True,
            )
        )
        claims = QGridLayout()
        claims.setSpacing(10)
        for i, (head, claim) in enumerate(CLAIMS):
            card = Card(head, claim, "card2")
            claims.addWidget(card, 0, i)
        lay.addLayout(claims)

        grid = QGridLayout()
        grid.setSpacing(12)
        # 1. the data
        self.data = Card(
            "The data",
            (
                "Natural Questions: real Wikipedia passages, each owned by its article (the "
                "account), with real test questions and the passages judged to answer them. "
                "Every file is pinned by SHA-256 (P0)."
                if s.data == "nq"
                else "The offline fixture: 240 unit vectors in 16 dimensions (golden/, in git)."
            ),
        )
        self.data_bar = QProgressBar()
        self.data_bar.hide()
        self.data_res = label("", wrap=True)
        self.data.add(button("Re-hash the data", "", self.verify_data))
        self.data.add(self.data_bar)
        self.data.add(self.data_res)
        grid.addWidget(self.data, 0, 0)
        # 2. opening
        self.opening = Card(
            "Opening the database",
            "It refuses a machine where secrets could leak (§12.8–12.9): unencrypted swap, "
            "hibernation, memory that cannot be locked, a file system that does not overwrite in "
            "place.",
        )
        self.open_res = label("", wrap=True)
        self.opening.add(self.open_res)
        grid.addWidget(self.opening, 0, 1)
        # 3. the encoder
        self.enc = Card(
            "One encoder for everything",
            "Search only means something if the stored vectors, the questions and your own text "
            "come from the same model (§3.3). Three names, checked equal:",
        )
        self.enc_res = label("", wrap=True)
        self.enc.add(button("Check the encoder", "", self.encoder))
        self.enc.add(self.enc_res)
        grid.addWidget(self.enc, 0, 2)
        lay.addLayout(grid)

        groups = Card(
            "What is stored",
            "Records live in groups. Frozen groups come from a partition fitted once on separate "
            "data; spawned groups form when 200 out-of-distribution records have gathered in the "
            "holding area (§6–7). The counts are the database's own (stats, group sizes), checked "
            "against the application's index.",
        )
        tiles = QHBoxLayout()
        self.t_n = Tile("records in groups (N)")
        self.t_hold = Tile("in the holding area")
        self.t_frozen = Tile("frozen groups")
        self.t_spawned = Tile("spawned groups")
        self.t_agree = Tile("index agrees with the database")
        for t in (self.t_n, self.t_hold, self.t_frozen, self.t_spawned, self.t_agree):
            tiles.addWidget(t)
        groups.body.addLayout(tiles)
        row = QHBoxLayout()
        row.addWidget(button("Count again", "", self.clusters))
        row.addWidget(button("Open the map  →", "primary", lambda: host.go("map")))
        row.addStretch(1)
        groups.body.addLayout(row)
        lay.addWidget(groups)
        lay.addStretch(1)

    def arrive(self, **kw: Any) -> None:
        self.show_open()
        self.clusters()

    def show_open(self) -> None:
        s = self.host.studio
        v = s.checklist.verdicts.get("startup")
        overrides = s.numbers.get("startup_overrides", [])
        refused = s.backend.refused
        text = ""
        if refused:
            text += f"<span style='color:{theme.WARN}'>Refused this machine:</span> {refused}<br>"
            text += "Opened with the development override, which the database reports:<br>"
        text += "overrides in use: " + (
            ", ".join(f"<b>{o}</b>" for o in overrides) if overrides else "none"
        )
        if v:
            text += (
                f"<br><span style='color:{tick_colour(v.ok)}'>{tick(v.ok)} opened, and every"
                " override it used is listed</span>"
            )
        self.open_res.setText(text)

    def verify_data(self) -> None:
        s = self.host.studio
        self.data_bar.show()
        self.data_bar.setValue(0)

        def progress(a: tuple[Any, ...]) -> None:
            done, total = a
            self.data_bar.setMaximum(total)
            self.data_bar.setValue(done)

        def done(out: tuple[int, int]) -> None:
            ok, bad = out
            self.data_bar.hide()
            good = bad == 0 and ok > 0
            self.data_res.setText(
                f"<span style='color:{tick_colour(good)}'>{tick(good)}</span> "
                + (
                    f"{ok} files re-hashed against datasets/MANIFEST.sha256, {bad} mismatches"
                    if s.data == "nq"
                    else "the fixture matches the committed golden/ files"
                )
            )
            self.host.changed()

        self.data_res.setText("hashing…")
        self.host.worker.submit(
            lambda report: s.verify_data(lambda d, t: report(d, t)), done, self.host.error, progress
        )

    def encoder(self) -> None:
        def done(out: tuple[str, str, str]) -> None:
            art, data, mine = out
            ok = art == data == mine
            self.enc_res.setText(
                f"partition artefact: <b>{art}</b><br>stored vectors: <b>{data}</b><br>"
                f"your text and questions: <b>{mine}</b><br>"
                f"<span style='color:{tick_colour(ok)}'>{tick(ok)}"
                f" {'the same' if ok else 'DIFFERENT'}</span>"
            )
            self.host.changed()

        self.host.worker.submit(self.host.studio.encoder_check, done, self.host.error)

    def clusters(self) -> None:
        def done(st: dict[str, int]) -> None:
            self.t_n.set(f"{st['N']:,}")
            self.t_hold.set(f"{st['holding']:,}")
            self.t_frozen.set(str(st["frozen"]))
            self.t_spawned.set(str(st["spawned"]))
            v = self.host.studio.checklist.verdicts.get("clusters")
            self.t_agree.set(tick(v.ok if v else None), tick_colour(v.ok if v else None))
            self.host.changed()

        self.host.worker.submit(self.host.studio.clusters, done, self.host.error)


class RulesScreen(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.addWidget(label("What the database refuses", "h2"))
        lay.addWidget(
            label(
                "Inputs are validated, never repaired (§4). Errors are typed and never contain a "
                "record ID, a vector, a key or text (§17), so they can be logged as they are.",
                "muted",
                wrap=True,
            )
        )
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Input", "Expected error", "", "What it said"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setColumnWidth(0, 360)
        self.table.setColumnWidth(1, 190)
        self.table.setColumnWidth(2, 40)
        self.table.setMinimumHeight(220)
        lay.addWidget(button("Try the five invalid inputs", "primary", self.refusals))
        lay.addWidget(self.table)
        retry = Card(
            "The safe retry",
            "An insert whose answer was lost (a timeout, a dropped connection) is sent again with "
            "the same prepared request. The database recognises it, and nothing is stored twice "
            "(§15.1).",
        )
        self.retry_res = label("", wrap=True)
        retry.add(button("Insert, then send the same request again", "", self.retry))
        retry.add(self.retry_res)
        lay.addWidget(retry)
        lay.addStretch(1)

    def arrive(self, **kw: Any) -> None:
        pass

    def refusals(self) -> None:
        def done(rows: list[tuple[str, str, bool, str]]) -> None:
            self.table.setRowCount(len(rows))
            for i, (what, kind, ok, msg) in enumerate(rows):
                for j, v in enumerate([what, kind, tick(ok), msg]):
                    item = QTableWidgetItem(v)
                    if j == 2:
                        item.setForeground(QColor(tick_colour(ok)))
                    self.table.setItem(i, j, item)
            self.table.resizeRowsToContents()
            self.host.changed()

        self.host.worker.submit(self.host.studio.refusals, done, self.host.error)

    def retry(self) -> None:
        def done(out: tuple[Inserted, Inserted]) -> None:
            first, again = out
            ok = again.retried
            self.retry_res.setText(
                f"first answer: stored at log position <b>{first.lsn}</b>, in {first.placement}<br>"
                f"the same request again: <b>retried = {again.retried}</b>, nothing new stored<br>"
                f"<span style='color:{tick_colour(ok)}'>{tick(ok)} stored exactly once</span>"
            )
            self.host.changed()

        self.host.worker.submit(self.host.studio.retry, done, self.host.error)
