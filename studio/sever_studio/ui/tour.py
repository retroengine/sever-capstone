"""The guided tour: the project in chapters, in the order a reviewer should see it.

Each chapter names its place, one line to read, notes for the presenter, and the checklist rows its
"Do it" shows.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from . import theme
from .widgets import Popover, button, label, lift


@dataclass(frozen=True)
class Chapter:
    title: str
    section: str
    tab: str | None
    line: str
    notes: str
    rows: tuple[str, ...]


CHAPTERS = [
    Chapter(
        "The idea",
        "home",
        None,
        "Delete a vector, and prove it.",
        "Deleting a vector should leave the database exactly as if it never arrived, and anyone "
        "should be able to check that without access to it. Averages can't be undone exactly; "
        "integer sums can.",
        (),
    ),
    Chapter(
        "Checked before opening",
        "home",
        None,
        "Pinned data, a checked machine, one encoder.",
        "Every data file is re-hashed. The database refuses an unsafe machine; here it opens with "
        "the development override and says so. One model encodes everything.",
        ("data", "startup", "encoder", "clusters"),
    ),
    Chapter(
        "The data as a map",
        "explore",
        None,
        "Each dot is a passage, coloured by its group.",
        "Ten thousand real Wikipedia passages. Filled dots: frozen groups; rings: spawned groups. "
        "Hover any dot for its text and its 384 numbers.",
        ("hover",),
    ),
    Chapter(
        "Add yourself",
        "explore",
        None,
        "Type a name and a sentence.",
        "It is encoded by the same model, signed with your key, stored encrypted, and lands where "
        "the routing rule sends it. Do it: adds a sample record.",
        ("insert", "freetext", "routing"),
    ),
    Chapter(
        "The waiting bucket",
        "explore",
        None,
        "Stored, but no search finds it, until 200 gather.",
        "Records that fit no group wait. At 200 they all leave as one new group, named by a hash "
        "of its members.",
        ("unsearchable", "flush"),
    ),
    Chapter(
        "Search",
        "explore",
        None,
        "A real question; ✓ marks the judged answer.",
        "The beam goes to the ten nearest records. Then the same over every question.",
        ("search",),
    ),
    Chapter(
        "Delete",
        "explore",
        None,
        "The dot goes; deleting again changes nothing.",
        "Subtracted exactly, keys rotated, old keys overwritten, a receipt returned. A retry says "
        "absent.",
        ("delete", "absent"),
    ),
    Chapter(
        "Forget a person",
        "explore",
        None,
        "Every record of one account, all or nothing.",
        "One transaction across many groups.",
        ("forget",),
    ),
    Chapter(
        "Floats drift, integers don’t",
        "live",
        "race",
        "The same members, again and again: only the integers stay exact.",
        "A float running mean changes in almost every number although nothing changed; the "
        "integer sum stays bit-identical.",
        ("race",),
    ),
    Chapter(
        "The receipt",
        "receipts",
        None,
        "Checked offline; one flipped byte fails it.",
        "A separate program, no database, only the public anchors. It names the step that failed. "
        "And it can't prove the operator kept no copy.",
        ("verify", "tamper", "limits"),
    ),
    Chapter(
        "Climb the log",
        "live",
        "tree",
        "Your receipt, hashed up to the signed root.",
        "Studio recomputes every hash on the path itself; the top equals the root the operator "
        "signed and the witnesses cosigned.",
        ("climb",),
    ),
    Chapter(
        "Try to cheat",
        "live",
        "attacks",
        "Five forgeries; each one caught.",
        "Change a byte, cut it short, bribe witnesses, another operator, someone else’s receipt.",
        ("attacks",),
    ),
    Chapter(
        "The public log",
        "hood",
        "log",
        "Signed, cosigned, audited.",
        "Every change is a leaf of an append-only log, cosigned by independent witnesses; the "
        "auditor replays it all.",
        ("log", "audit"),
    ),
    Chapter(
        "The disk",
        "hood",
        "disk",
        "A thief's byte search finds nothing.",
        "Everything found in an ordinary store; nothing in SEVER-DB's.",
        ("disk",),
    ),
    Chapter(
        "Pull the plug",
        "hood",
        "crash",
        "Kill the writer; nothing confirmed is lost.",
        "A restart loses nothing; a writer killed mid-stream loses no confirmed insert.",
        ("restart", "crash"),
    ),
    Chapter(
        "Kill a deletion",
        "live",
        "kill",
        "Kill it mid-delete, five times: never half.",
        "A whole person deleted in one transaction by a process killed at a random moment; after "
        "recovery all or none.",
        ("crashdelete",),
    ),
    Chapter(
        "Bad input",
        "hood",
        "rules",
        "Refused with a typed error; retries stored once.",
        "Errors never contain an ID, a vector or a key.",
        ("refusals", "retry"),
    ),
    Chapter(
        "Inside the engine",
        "proof",
        "parts",
        "Each part proves its claim from inside.",
        "Survivors-only state, floats' ghost, all or nothing at the commit point, chained "
        "receipts, and a forensic scan that finds nothing deleted unless key rotation is skipped.",
        ("exact", "ghost", "durable", "chain", "shred", "leak", "phasec"),
    ),
    Chapter(
        "Planted bugs",
        "proof",
        "sabotage",
        "Plant a bug; a test goes red.",
        "Every guarantee has a test, and every test has been shown able to fail. Compiling takes "
        "minutes.",
        ("sabotage",),
    ),
    Chapter(
        "The evidence",
        "proof",
        "evidence",
        "Read from the project's generated files.",
        "Traceability, proofs, oracles, gate runs, fairness runs, failures included. Then save "
        "the report.",
        ("evidence",),
    ),
]


class Progress(QWidget):
    """One dot per chapter, drawn, so a narrow bar packs them closer instead of cutting them off."""

    def __init__(self, count: int) -> None:
        super().__init__()
        self.count = count
        self.at = 0
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt's name)
        return QSize(self.count * 14, 14)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt's name)
        return QSize(self.count * 5, 14)

    def set_at(self, at: int) -> None:
        self.at = at
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt's name)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        step = self.width() / self.count
        r = min(4.0, step * 0.35)
        for k in range(self.count):
            colour = theme.ACCENT if k == self.at else (theme.TEXT if k < self.at else theme.LINE)
            p.setBrush(QColor(colour))
            p.drawEllipse(QPointF(step * (k + 0.5), self.height() / 2), r, r)


class TourBar(QFrame):
    """A slim bar at the bottom: where we are, one line, Back / Do it / Next."""

    def __init__(
        self, parent: QWidget, go: Callable[[Chapter], None], do: Callable[[Chapter], None]
    ) -> None:
        super().__init__(parent)
        self.setObjectName("tour")
        lift(self)
        self.go = go
        self.do_it = do
        self.i = 0
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 10, 10)
        lay.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = label("", "strong")
        self.line = label("", "muted")
        text.addWidget(self.title)
        text.addWidget(self.line)
        lay.addLayout(text, 1)
        self.dots = Progress(len(CHAPTERS))
        lay.addWidget(self.dots)
        self.b_notes = button("Notes", "ghost", self.notes)
        lay.addWidget(self.b_notes)
        lay.addWidget(button("", "", lambda: self.step(-1), "left", "Back"))
        lay.addWidget(button("Do it", "primary", lambda: self.do_it(CHAPTERS[self.i]), "play"))
        lay.addWidget(button("", "", lambda: self.step(1), "right", "Next (N)"))
        lay.addWidget(button("", "ghost", self.hide, "x", "Close the tour"))
        self.hide()

    def start(self) -> None:
        self.i = 0
        self.show()
        self.show_chapter()

    def step(self, d: int) -> None:
        self.i = max(0, min(len(CHAPTERS) - 1, self.i + d))
        self.show_chapter()

    def show_chapter(self) -> None:
        ch = CHAPTERS[self.i]
        self.title.setText(f"{self.i + 1}. {ch.title}")
        self.line.setText(ch.line)
        self.dots.set_at(self.i)
        self.go(ch)
        self.place()

    def notes(self) -> None:
        ch = CHAPTERS[self.i]
        Popover(ch.title, ch.notes).show_below(self.b_notes)

    def place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        w = min(980, parent.width() - 32)
        self.setFixedWidth(w)
        self.adjustSize()
        self.move((parent.width() - w) // 2, parent.height() - self.height() - 16)
        self.raise_()
