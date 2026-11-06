"""The guided tour: the company demo in ten chapters, one action each.

Each chapter names its place, one line to read, notes for the presenter, the checklist rows it
shows, and (on the Assistant) the steps its "Do it" runs.
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
    #: the checklist rows the chapter shows
    rows: tuple[str, ...]
    #: the Assistant's steps its "Do it" runs, in order (``rows`` are run when empty)
    do: tuple[str, ...] = ()


#: Ten chapters, one action each (audit 2, §3).
CHAPTERS = [
    Chapter(
        "The company",
        "home",
        None,
        "Acme Notes: a notes app with an AI assistant, on SEVER-DB.",
        "A company stores its customers' notes as vectors so its assistant can find them. A "
        "customer asks to be forgotten. SEVER-DB deletes exactly, hands the customer a receipt "
        "anyone can check offline, and leaves nothing of them in its files. Each part's claim is "
        "shown with its status: frozen, and the gate that proved it.",
        ("data", "startup", "encoder", "clusters"),
    ),
    Chapter(
        "Store your notes",
        "assistant",
        None,
        "Each note encoded, signed with your key, stored encrypted.",
        "The engine says where each note went and its log position; the engine's own routing "
        "code predicted that place before the insert (§7.3). The call appears under SEVER-DB "
        "calls.",
        ("insert", "freetext", "routing"),
        ("store",),
    ),
    Chapter(
        "The holding area",
        "assistant",
        None,
        "A note far from every group waits: stored, not searchable.",
        "Most notes are far from the frozen centres, which were fitted on science questions. "
        "They wait in the holding area until enough gather to become a new group (§7.4). Let "
        "other users write fills it; the new group's name is a hash of its members (§7.5).",
        ("flush",),
        ("others",),
    ),
    Chapter(
        "Ask the assistant",
        "assistant",
        None,
        "The answer is written only from passages the database returned.",
        "Your question is searched; every passage shown was read with passage(), so a deleted "
        "one cannot appear. With GROQ_API_KEY set, Groq writes the answer and cites [n]; what "
        "Groq receives is outside the database.",
        ("assistant", "search"),
        ("ask",),
    ),
    Chapter(
        "Forget me",
        "assistant",
        None,
        "All your notes deleted in one transaction; one receipt each.",
        "Then the report checks, row by row: a search with your own words, a passage() read of "
        "each of your notes, and a byte search of every database file for your text and vectors "
        "(§13.2).",
        ("gone", "forget"),
        ("forget",),
    ),
    Chapter(
        "Verify the receipts",
        "assistant",
        None,
        "sever-verify, with only the receipts and the public anchors.",
        "A separate program that shares no code with the database checks each receipt offline "
        "(§11.3). Save receipts… writes the files and the exact command, to run in a terminal.",
        ("verify", "limits"),
        ("verify",),
    ),
    Chapter(
        "Flip a byte",
        "assistant",
        None,
        "One changed byte, and the receipt is rejected at a named step.",
        "Every byte of a receipt is signed by the operator, so any edit fails. The attack lab "
        "(Live) tries many more forgeries, including the operator's own (P3-T2).",
        ("tamper",),
        ("flip",),
    ),
    Chapter(
        "Beside an ordinary store",
        "assistant",
        None,
        "The same app on Chroma: forgotten by its API, and its files searched the same way.",
        "Chroma's delete() makes the notes unreadable through its API. The report's right "
        "column shows what a byte search of its folder finds afterwards, measured, not assumed.",
        ("compare",),
        ("report",),
    ),
    Chapter(
        "How the groups were made",
        "live",
        "kmeans",
        "Frozen groups are k-means clusters; spawned groups are batches.",
        "The frozen centres were fitted once, offline (§6.2): here the same algorithm runs with "
        "one start, small enough to watch. Are they clusters? Measured in 384-D with the "
        "engine's search code: most frozen records are nearer their own centre, most spawned "
        "ones are not.",
        (),
    ),
    Chapter(
        "The log and the auditor",
        "hood",
        "log",
        "Every change in a signed public log; an auditor checks all of it.",
        "Each insert and deletion is a leaf of an RFC 9162 Merkle tree, signed by the operator "
        "and cosigned by five witnesses, simulated by the database in v1 (§10.4, L-7). "
        "sever-audit checks the whole log and every receipt (§11.3).",
        ("log", "audit"),
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
        # clear of the map's "Add yourself" button at the bottom left
        left = 200
        w = min(980, parent.width() - left - 16)
        self.setFixedWidth(w)
        self.adjustSize()
        x = max(left, (parent.width() - w) // 2)
        self.move(x, parent.height() - self.height() - 16)
        self.raise_()
