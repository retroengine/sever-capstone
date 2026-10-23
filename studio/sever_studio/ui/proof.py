"""Proof: each part's own program, the sabotage lab, and the project's generated evidence."""

from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import sabotage
from ..proofs import Proof
from . import copy, theme
from .hood import page
from .host import Host
from .widgets import Card, Console, Tile, Verdict, button, clear, label, mark

PARTS = [("idea", "1"), ("durable", "2"), ("receipt", "3"), ("erase", "4")]


class PartCard(Card):
    def __init__(self, host: Host, name: str, part: str) -> None:
        super().__init__(f"Part {part} · {copy.short('proof.' + name)}", "proof." + name)
        self.host = host
        self.name = name
        row = QHBoxLayout()
        if name != "erase":
            row.addWidget(
                button(
                    "Recorded run",
                    "",
                    lambda: self.load(None),
                    tip="the nq-10k run in artefacts/demo/",
                )
            )
        row.addWidget(
            button(
                "Run now",
                "primary",
                lambda: self.load("synthetic"),
                "play",
                "on the offline fixture: seconds",
            )
        )
        row.addStretch(1)
        self.body.addLayout(row)
        self.verdict = Verdict()
        self.add(self.verdict)
        self.detail = label("", "small", wrap=True)
        self.add(self.detail)

    def load(self, live: str | None) -> None:
        self.verdict.set(None, "running…")
        self.detail.setText("")

        def done(p: Proof | None) -> None:
            if p is None:
                self.verdict.set(False, "No recorded run: press Run now.")
                return
            self.render_proof(p)
            self.host.changed()

        self.host.worker.submit(
            lambda: self.host.studio.proof(self.name, live), done, self.host.error
        )

    def render_proof(self, p: Proof) -> None:
        passed = sum(ok for _, ok in p.checks)
        self.verdict.set(p.ok, f"{passed} of {len(p.checks)} checks · {p.source.split(' (')[0]}")
        lines = [f"<span style='color:{theme.MUTED}'>{p.source}</span>"]
        for c, ok in p.checks:
            sign, colour = mark(ok)
            lines.append(f"<span style='color:{colour}'>{sign}</span> {c}")
        self.detail.setText("<br>".join(lines))


class Parts(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        w, lay = page(copy.short("proof.about"), "proof.about")
        QVBoxLayout(self).addWidget(w)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.cards = {n: PartCard(host, n, p) for n, p in PARTS}
        for i, (n, _) in enumerate(PARTS):
            grid.addWidget(self.cards[n], i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        lay.addStretch(1)

    def arrive(self, run: str | None = None, live: str | None = None) -> None:
        if run in self.cards:
            self.cards[run].load(live)


class SabotageTab(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        w, lay = page(copy.short("sabotage.about"), "sabotage.about")
        QVBoxLayout(self).addWidget(w)
        body = QHBoxLayout()
        self.list = QListWidget()
        for it in sabotage.ITEMS:
            item = QListWidgetItem(f"{it.id}  {it.text}")
            item.setToolTip(f"Part {it.part} · tests of {it.target}")
            self.list.addItem(item)
        self.list.setCurrentRow(23)
        body.addWidget(self.list, 3)
        side = QVBoxLayout()
        self.b_run = button("Plant it and test", "danger", self.run, "bug")
        side.addWidget(self.b_run)
        self.verdict = Verdict()
        side.addWidget(self.verdict)
        self.b_out = button("Show output", "ghost", self.toggle_output)
        side.addWidget(self.b_out)
        side.addStretch(1)
        body.addLayout(side, 2)
        lay.addLayout(body, 1)
        self.console = Console(160)
        self.console.hide()
        lay.addWidget(self.console)

    def arrive(self) -> None:
        pass

    def toggle_output(self) -> None:
        self.console.setVisible(not self.console.isVisible())
        self.b_out.setText("Hide output" if self.console.isVisible() else "Show output")

    def run(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        item = sabotage.ITEMS[row]
        self.console.clear()
        self.console.say("$ " + " ".join(sabotage.command(item)[0]))
        self.verdict.set(None, f"{item.id}: building with the bug, then testing (minutes)…")
        self.b_run.setEnabled(False)

        def done(o: sabotage.Outcome) -> None:
            self.b_run.setEnabled(True)
            self.verdict.set(
                o.caught, f"{o.id}: caught, a test went red" if o.caught else f"{o.id}: {o.summary}"
            )
            li = self.list.item(row)
            if li is not None:
                li.setForeground(QColor(theme.OK if o.caught else theme.BAD))
            self.host.changed()

        def fail(msg: str) -> None:
            self.b_run.setEnabled(True)
            self.host.error(msg)

        self.host.worker.submit(
            lambda report: self.host.studio.sabotage(item.id, lambda line: report(line)),
            done,
            fail,
            lambda a: self.console.say(str(a[0])),
        )


class EvidenceTab(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        w, lay = page(copy.short("evidence.about"), "evidence.about")
        QVBoxLayout(self).addWidget(w)
        self.grid = QGridLayout()
        self.grid.setSpacing(10)
        lay.addLayout(self.grid)
        self.ledger = QTableWidget(0, 4)
        self.ledger.setHorizontalHeaderLabels(["When (UTC)", "Result", "Gate or measure", "Commit"])
        self.ledger.verticalHeader().hide()
        self.ledger.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(label("Latest gate runs", "strong"))
        lay.addWidget(self.ledger, 1)
        self.fair = label("", "small", wrap=True)
        lay.addWidget(self.fair)

    def arrive(self) -> None:
        def done(out: tuple[Any, Any, Any]) -> None:
            lines, led, fair = out
            clear(self.grid)
            for i, ln in enumerate(lines):
                head = ln.claim.split(" ", 1)[0]
                big = head if "/" in head or head.isdigit() else ""
                tile = Tile(self._caption(ln.source, ln.claim), big or ln.claim)
                tile.setToolTip(f"{ln.source}: {ln.claim}")
                if big:
                    tile.set(self._fraction(ln.claim), theme.OK)
                self.grid.addWidget(tile, i // 5, i % 5)
            rows = [e for e in led if e["gate"] and e["outcome"] in ("PASS", "FAIL")][:12]
            self.ledger.setRowCount(len(rows))
            for i, e in enumerate(rows):
                for j, v in enumerate([e["utc"], e["outcome"], e["gate"], e["commit"]]):
                    item = QTableWidgetItem(v)
                    if j == 1:
                        item.setForeground(
                            QColor(
                                theme.OK
                                if v == "PASS"
                                else theme.BAD
                                if v == "FAIL"
                                else theme.TEXT
                            )
                        )
                    self.ledger.setItem(i, j, item)
            self.ledger.resizeColumnsToContents()
            runs = [
                f"Part {f['part']} {f['outcome']} ({f['failing']}/{f['tests']} failing)"
                for f in fair[:5]
            ]
            self.fair.setText("Clean-room fairness runs, newest first: " + " · ".join(runs))
            self.host.changed()

        self.host.worker.submit(self.host.studio.evidence, done, self.host.error)

    @staticmethod
    def _fraction(claim: str) -> str:
        words = claim.split()
        if len(words) >= 3 and words[1] == "of":
            return f"{words[0]}/{words[2]}"
        return words[0]

    @staticmethod
    def _caption(source: str, claim: str) -> str:
        part = next((c for c in source if c.isdigit()), "")
        if source.startswith("TRACE"):
            return f"Part {part} requirements with a test"
        if source.startswith("PROOFS"):
            return f"Part {part} proofs that tests can fail"
        return f"Part {part} labelled tests ({claim.split('. ', 1)[-1]})"


class ProofSection(QTabWidget):
    TABS = ("parts", "sabotage", "evidence")

    def __init__(self, host: Host) -> None:
        super().__init__()
        self.tabs: dict[str, Any] = {
            "parts": Parts(host),
            "sabotage": SabotageTab(host),
            "evidence": EvidenceTab(host),
        }
        for k, name in zip(self.TABS, ("The four parts", "Sabotage lab", "Evidence"), strict=True):
            self.addTab(self.tabs[k], name)
        self.currentChanged.connect(lambda i: self._arrive_tab(self.TABS[i]))

    def _arrive_tab(self, key: str) -> None:
        if key != "parts":
            self.tabs[key].arrive()

    def arrive(self, tab: str | None = None, **kw: Any) -> None:
        if tab:
            self.setCurrentIndex(self.TABS.index(tab))
        key = self.TABS[self.currentIndex()]
        if key == "parts":
            self.tabs["parts"].arrive(kw.get("run"), kw.get("live"))
        else:
            self.tabs[key].arrive()
