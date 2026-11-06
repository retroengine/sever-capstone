"""Evidence: the project's generated files, read as they are."""

from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGridLayout,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import copy, theme
from .hood import page
from .host import Host
from .widgets import Tile, clear, label


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
    TABS = ("evidence",)

    def __init__(self, host: Host) -> None:
        super().__init__()
        self.tabs: dict[str, Any] = {"evidence": EvidenceTab(host)}
        self.addTab(self.tabs["evidence"], "Evidence")

    def arrive(self, tab: str | None = None, **kw: Any) -> None:
        self.tabs["evidence"].arrive()
