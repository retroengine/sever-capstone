"""Home: the four claims, a few checks before starting, and the way in."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from . import copy, theme
from .host import Host
from .icons import icon
from .widgets import Card, Verdict, button, info, label

CLAIMS = [
    ("claim.idea", "map"),
    ("claim.database", "zap"),
    ("claim.receipt", "receipt"),
    ("claim.erasure", "shield"),
]


class Home(QWidget):
    def __init__(self, host: Host, start_tour: Callable[[], None]) -> None:
        super().__init__()
        self.host = host
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 32, 40, 24)
        lay.setSpacing(20)
        lay.addWidget(label("SEVER-DB", "title"))
        tag = QHBoxLayout()
        tag.addWidget(label(copy.short("tagline"), "heading"))
        tag.addWidget(info("tagline"))
        tag.addStretch(1)
        lay.addLayout(tag)

        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (key, ico) in enumerate(CLAIMS):
            card = Card(copy.short(key), key, "card2")
            pic = QLabel()
            pic.setPixmap(icon(ico, theme.ACCENT, 28).pixmap(28, 28))
            card.body.insertWidget(0, pic)
            card.add(label(f"Part {i + 1}", "small"))
            grid.addWidget(card, 0, i)
        lay.addLayout(grid)

        go = QHBoxLayout()
        go.addWidget(button("  Start the guided tour", "primary", start_tour, "play"))
        go.addWidget(button("  Explore the map", "", lambda: host.go("explore"), "map"))
        go.addStretch(1)
        lay.addLayout(go)

        checks = Card("Before we start")
        self.v: dict[str, Verdict] = {}
        rows: list[tuple[str, str, Callable[[], None] | None]] = [
            ("data", "check.data", self.verify_data),
            ("startup", "check.startup", None),
            ("encoder", "check.encoder", self.encoder),
            ("clusters", "check.groups", self.clusters),
        ]
        for key, text, act in rows:
            row = QHBoxLayout()
            v = Verdict()
            v.set(None, copy.short(text))
            self.v[key] = v
            row.addWidget(v, 1)
            row.addWidget(info(text))
            if act is not None:
                row.addWidget(button("Check", "ghost", act, "refresh"))
            checks.body.addLayout(row)
        lay.addWidget(checks)
        reset = QHBoxLayout()
        reset.addWidget(button("Reset demo database", "ghost", self.reset, "refresh"))
        self.reset_state = Verdict()
        reset.addWidget(self.reset_state, 1)
        lay.addLayout(reset)
        lay.addStretch(1)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

    def reset(self) -> None:
        """Deletes the demo database and stores the first passages again (minutes on NQ)."""
        s = self.host.studio
        sure = QMessageBox.question(
            self,
            "Reset the demo database",
            f"Delete everything in {s.work.name} (records, keys, receipts) and store the first "
            f"{s.rows:,} passages again?",
        )
        if sure != QMessageBox.StandardButton.Yes:
            return

        def progress(a: tuple[Any, ...]) -> None:
            self.reset_state.set(None, f"storing {a[0]:,} / {a[1]:,}…")

        def done(_: object) -> None:
            self.reset_state.set(True, "a fresh demo database")
            self.host.go("home")
            self.host.changed()

        self.reset_state.set(None, "deleting…")
        self.host.worker.submit(
            lambda report: s.reset(lambda d, t: report(d, t)), done, self.host.error, progress
        )

    def arrive(self, **kw: Any) -> None:
        self.show_startup()
        self.clusters()

    def show_startup(self) -> None:
        s = self.host.studio
        overrides = s.numbers.get("startup_overrides", [])
        if s.backend.refused:
            self.v["startup"].warn(
                "Machine checked: refused here (" + ", ".join(overrides) + "), opened with the"
                " development override"
            )
            self.v["startup"].setToolTip(f"{s.backend.refused}\noverrides: {', '.join(overrides)}")
        else:
            self.v["startup"].set(True, "Machine checked: safe to open")

    def verify_data(self) -> None:
        s = self.host.studio
        self.v["data"].set(None, "Re-reading every data file…")

        def progress(a: tuple[Any, ...]) -> None:
            done, total = a
            self.v["data"].set(None, f"Re-reading the data… {done}/{total}")

        def done(out: tuple[int, int]) -> None:
            ok, bad = out
            self.v["data"].set(
                bad == 0 and ok > 0,
                f"Data pinned: {ok} files, {bad} changed"
                if s.data == "nq"
                else "Data pinned: the fixture matches git",
            )
            self.host.changed()

        self.host.worker.submit(
            lambda report: s.verify_data(lambda d, t: report(d, t)), done, self.host.error, progress
        )

    def encoder(self) -> None:
        def done(out: tuple[str, str, str]) -> None:
            art, data, mine = out
            ok = art == data == mine
            v = self.host.studio.checklist.verdicts.get("encoder")
            self.v["encoder"].set(ok and bool(v and v.ok), v.detail if v else "Encoders differ")
            self.v["encoder"].setToolTip(f"partition: {art}\nvectors: {data}\nyour text: {mine}")
            self.host.changed()

        self.host.worker.submit(self.host.studio.encoder_check, done, self.host.error)

    def clusters(self) -> None:
        def done(st: dict[str, int]) -> None:
            v = self.host.studio.checklist.verdicts.get("clusters")
            self.v["clusters"].set(
                v.ok if v else None,
                f"{st['N'] + st['holding']:,} records · {st['frozen']} frozen + {st['spawned']} "
                f"spawned groups · {st['holding']} waiting",
            )
            self.host.changed()

        self.host.worker.submit(self.host.studio.clusters, done, self.host.error)
