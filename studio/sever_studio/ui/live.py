"""Live: how the frozen groups were made, and the attack lab.

The work is in ``kmeans.py``, ``wow.py`` and ``actions.Studio``; this only draws it.
"""

import itertools
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from .. import kmeans, wow
from . import copy, theme
from .hood import page
from .host import Host
from .widgets import Verdict, button, clear, label, mark


def short(b: bytes, n: int = 8) -> str:
    return b.hex()[:n] + "…"


class ReceiptPicker(QComboBox):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        self.setMinimumWidth(220)

    def fill(self) -> None:
        current = self.currentData()
        self.clear()
        for lsn in reversed(self.host.studio.backend.index.receipts):
            rid, _ = self.host.studio.backend.receipt_owner(lsn) or ("", "")
            self.addItem(f"Receipt #{lsn}" + (f"  · {rid}" if rid else ""), lsn)
        if current is not None:
            i = self.findData(current)
            if i >= 0:
                self.setCurrentIndex(i)

    def lsn(self) -> int | None:
        v = self.currentData()
        return int(v) if v is not None else None


class AttackTab(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        w, lay = page(copy.short("live.attacks"), "live.attacks")
        QVBoxLayout(self).addWidget(w)
        row = QHBoxLayout()
        self.pick = ReceiptPicker(host)
        row.addWidget(self.pick)
        row.addWidget(button("Try to cheat", "danger", self.run, "zap"))
        row.addWidget(
            button(
                "The operator cheats (Part 3)",
                "",
                self.operator,
                "shield",
                "Part 3's 20 forgeries made with the operator's own keys (P3-T2)",
            )
        )
        row.addStretch(1)
        lay.addLayout(row)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(10)
        lay.addLayout(self.grid)
        self.total = Verdict()
        lay.addWidget(self.total)
        lay.addWidget(label(copy.long("live.attacks.note"), "small", wrap=True))
        self.forged = label("", "small", wrap=True)
        self.forged.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.forged)
        lay.addStretch(1)

    def arrive(self) -> None:
        self.pick.fill()

    def operator(self) -> None:
        """Part 3's register of forgeries made with the operator's keys, judged by sever-verify."""

        def done(out: list[wow.Forgery]) -> None:
            caught = sum(f.caught for f in out)
            lines = [
                f"<b>{caught} of {len(out)} operator forgeries rejected</b> by sever-verify, each "
                "at a step its register row names (Part 3's own generator, P3-T2):"
            ]
            for f in out:
                sign, colour = mark(f.caught)
                at = ", ".join(str(x) for x in sorted(f.rejected_at)) or "—"
                lines.append(
                    f"<span style='color:{colour}'>{sign}</span> {f.id} {f.text}: step {at}"
                    f" ({f.tries} tries)"
                )
            self.forged.setText("<br>".join(lines))
            self.host.changed()

        self.forged.setText("building Part 3's attack generator and forging…")
        self.host.worker.submit(self.host.studio.operator_forgeries, done, self.host.error)

    def run(self) -> None:
        lsn = self.pick.lsn()
        if lsn is None:
            self.host.toast("Delete something first: there is no receipt yet.", False)
            return

        def done(out: list[wow.Attack]) -> None:
            clear(self.grid)
            for i, a in enumerate(out):
                sign, colour = mark(a.caught)
                self.grid.addWidget(label(a.name, "strong"), i, 0)
                did = label(a.did, "small", wrap=True)
                self.grid.addWidget(did, i, 1)
                v = label(
                    f"<span style='color:{colour}; font-weight:700'>{sign} caught</span> · {a.by}"
                    if a.caught
                    else f"<span style='color:{colour}'>{sign} not caught</span>"
                )
                v.setToolTip(a.verdict)
                self.grid.addWidget(v, i, 2)
            self.grid.setColumnStretch(1, 1)
            caught = sum(a.caught for a in out)
            self.total.set(caught == len(out), f"{caught} of {len(out)} attempts caught")
            self.host.changed()

        self.total.set(None, "attacking…")
        self.host.worker.submit(lambda: self.host.studio.attack_lab(lsn), done, self.host.error)


class KMeansTab(QWidget):
    """How the frozen groups were made: C-15's k-means, offline, step by step (§6.2)."""

    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        self.nq = host.studio.data == "nq"
        self.k, self.rows = (8, 2_000) if self.nq else (4, 240)
        w, lay = page(copy.short("live.kmeans"), "live.kmeans")
        QVBoxLayout(self).addWidget(w)
        lay.addWidget(label(copy.long("live.kmeans.offline"), "muted", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button(f"Start (k = {self.k})", "primary", self.start, "play"))
        row.addWidget(button("Step", "", self.step, "right"))
        row.addWidget(button("Run to the end", "", self.run, "layers"))
        row.addWidget(button("The real partition", "", self.real, "map"))
        row.addWidget(button("Are they clusters? (384-D)", "", self.clusters, "check"))
        row.addStretch(1)
        lay.addLayout(row)
        self.state = Verdict()
        lay.addWidget(self.state)
        # the 384-D measurement: own centre against the nearest other, by the engine's search code
        self.sep = pg.PlotWidget()
        self.sep.setBackground(theme.SURFACE)
        self.sep.setMenuEnabled(False)
        self.sep.setLabel("bottom", copy.short("live.kmeans.ratio"))
        self.sep.setLabel("left", "records")
        self.sep.addLegend(offset=(-10, 10))
        self.sep.setMinimumHeight(320)
        self.sep.hide()
        lay.addWidget(self.sep, 1)
        self.plot = pg.PlotWidget()
        self.plot.setBackground(theme.SURFACE)
        self.plot.setMenuEnabled(False)
        self.plot.setAspectLocked(True)
        self.plot.hideAxis("left")
        self.plot.hideAxis("bottom")
        self.points = pg.ScatterPlotItem(pxMode=True, size=5)
        self.trails = pg.PlotDataItem(pen=pg.mkPen(theme.MUTED, width=1), connect="pairs")
        self.marks = pg.ScatterPlotItem(pxMode=True)
        for item in (self.points, self.trails, self.marks):
            self.plot.addItem(item)
        self.plot.setMinimumHeight(320)
        lay.addWidget(self.plot, 1)
        self.k_run: Any = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def arrive(self) -> None:
        pass

    def _colours(self, labels: Any) -> list[Any]:
        # the same colour as frozen group j on the map
        return [pg.mkBrush(theme.group_colour(f"frozen-{int(j):04d}")) for j in labels]

    def _draw(self, part: Any, trail: list[Any] | None) -> None:
        self.sep.hide()
        self.plot.show()
        self.points.setData(pos=part.xy, brush=self._colours(part.labels), pen=pg.mkPen(None))
        self.marks.setData(
            pos=part.centres_xy,
            symbol="x",
            size=16,
            brush=pg.mkBrush(theme.TEXT),
            pen=pg.mkPen(theme.SURFACE, width=0.8),
        )
        if trail and len(trail) > 1:
            # each centre's path: one segment per step, from where it was to where it moved
            ends = [pair for a, b in itertools.pairwise(trail) for pair in zip(a, b, strict=True)]
            arr = np.array([pt for pair in ends for pt in pair], np.float64).reshape(-1, 2)
            self.trails.setData(arr[:, 0], arr[:, 1])
        else:
            self.trails.setData([], [])

    def _show(self) -> None:
        r = self.k_run
        self._draw(r, r.trail)
        self.state.set(
            True if r.done else None,
            f"iteration {r.iteration} · Σ‖x̂ − μ‖² = {r.inertia:.3f}"
            + (" · converged: no row changed centre" if r.done else ""),
        )

    def start(self) -> None:
        s = self.host.studio

        def done(r: Any) -> None:
            self.k_run = r
            self._show()

        self.timer.stop()
        self.state.set(None, "quantising the reference rows and choosing k-means++ starts…")
        self.host.worker.submit(
            lambda: kmeans.Run(s.root, s.data, self.k, self.rows), done, self.host.error
        )

    def step(self) -> None:
        if self.k_run is None:
            self.start()
            return
        if not self.k_run.done:
            self.k_run.step()
        self._show()

    def run(self) -> None:
        if self.k_run is None:
            self.start()
        self.timer.start(250)

    def _tick(self) -> None:
        if self.k_run is None:
            return
        if self.k_run.done:
            self.timer.stop()
            return
        self.step()

    def clusters(self) -> None:
        """For up to 8 stored records of every group: D to its own centre ÷ D to the nearest other
        centre, both in all the dimensions as the engine's search code ranks groups (§8.1). Below 1:
        nearer its own centre, as in a cluster."""
        s = self.host.studio

        def done(rows: list[tuple[str, str, float, float]]) -> None:
            self.timer.stop()
            self.plot.hide()
            self.sep.show()
            self.sep.clear()
            edges = np.linspace(0.0, 2.0, 41)
            for kind, name, colour in (
                ("frozen", "frozen groups (k-means)", theme.FROZEN),
                ("spawn", "spawned groups (batches)", theme.MUTED),
            ):
                ratio = [min(own / other, 1.999) for _, g, own, other in rows if g.startswith(kind)]
                counts, _ = np.histogram(ratio, bins=edges)
                fill = QColor(colour)
                fill.setAlpha(150)
                self.sep.addItem(
                    pg.BarGraphItem(
                        x0=edges[:-1],
                        x1=edges[1:],
                        height=counts,
                        brush=pg.mkBrush(fill),
                        pen=pg.mkPen(colour),
                        name=name,
                    )
                )
            self.sep.addItem(pg.InfiniteLine(1.0, angle=90, pen=pg.mkPen(theme.TEXT, width=1.5)))
            got = kmeans.separated(rows)
            (fn, fk), (sn, sk) = got["frozen"], got["spawn"]
            self.state.set(
                True,
                f"Measured in all {s.corpus.d} dimensions: {fk:,} of {fn:,} records of frozen"
                f" groups ({fk / max(fn, 1):.0%}) are nearer their own centre than any other; of"
                f" spawned groups, {sk:,} of {sn:,} ({sk / max(sn, 1):.0%})",
            )

        self.state.set(None, "measuring every group's records against every centre…")
        self.host.worker.submit(lambda: s.separation(per_group=8), done, self.host.error)

    def real(self) -> None:
        s = self.host.studio

        def done(part: Any) -> None:
            self.timer.stop()
            self._draw(part, None)
            self.state.set(
                True,
                f"The partition the engine uses: {len(part.centres)} centres fitted once on all "
                "the reference rows; each row coloured by its nearest centre, by the engine's "
                "routing code",
            )

        self.state.set(None, "reading the artefact and routing every reference row…")
        self.host.worker.submit(
            lambda: kmeans.real_partition(s.root, s.data, self.rows), done, self.host.error
        )


class Live(QTabWidget):
    TABS = ("kmeans", "attacks")

    def __init__(self, host: Host) -> None:
        super().__init__()
        self.tabs: dict[str, Any] = {
            "kmeans": KMeansTab(host),
            "attacks": AttackTab(host),
        }
        names = ("Groups made", "Attack lab")
        for k, name in zip(self.TABS, names, strict=True):
            self.addTab(self.tabs[k], name)
        self.currentChanged.connect(lambda i: self.tabs[self.TABS[i]].arrive())

    def arrive(self, tab: str | None = None, **kw: Any) -> None:
        if tab:
            self.setCurrentIndex(self.TABS.index(tab))
        self.tabs[self.TABS[self.currentIndex()]].arrive()
