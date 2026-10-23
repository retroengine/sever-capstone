"""Live: four demonstrations that go further than the receipt screen.

The log tree, the attack lab, a deletion killed part-way, and the race between a float mean and the
integer sum. The work is in ``wow.py`` and ``actions.Studio``; this only draws it.
"""

import itertools
import random
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from .. import explain, kmeans, wow
from ..proofs import Proof
from . import copy, theme
from .hood import LEFT, page
from .host import Host
from .widgets import Empty, Tile, Timeline, Verdict, button, clear, label, mark


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


class Tree(QWidget):
    """The climb: the leaf at the bottom, one level per path hash, the root at the top. Our hash is
    blue; the sibling the path supplies is grey, on its side. Levels light up one by one."""

    def __init__(self) -> None:
        super().__init__()
        self.steps: list[wow.Step] = []
        self.leaf = b""
        self.root = b""
        self.signed = b""
        self.shown = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._next)
        self.setMinimumHeight(360)

    def play(self, leaf: bytes, steps: list[wow.Step], root: bytes, signed: bytes) -> None:
        self.leaf, self.steps, self.root, self.signed = leaf, steps, root, signed
        self.shown = 0
        self.timer.start(380)
        self.update()

    def _next(self) -> None:
        self.shown += 1
        if self.shown > len(self.steps) + 1:
            self.timer.stop()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt's name)
        if not self.leaf:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        levels = len(self.steps) + 1
        h = float(self.height() - 70)
        dy = h / max(1, levels)
        cx = self.width() / 2
        box_w, box_h = 150.0, 30.0
        ours = QColor(theme.ACCENT)
        sib = QColor(theme.MUTED)

        def box(x: float, y: float, text: str, colour: QColor, filled: bool) -> None:
            r = QRectF(x - box_w / 2, y - box_h / 2, box_w, box_h)
            p.setPen(QPen(colour, 1.6))
            fill = QColor(colour)
            fill.setAlpha(40 if filled else 10)
            p.setBrush(fill)
            p.drawRoundedRect(r, 8, 8)
            p.setPen(QColor(theme.TEXT))
            p.setFont(theme.font(theme.SMALL, mono=True))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

        y = 30 + h
        box(cx, y, "leaf " + short(wow.leaf_hash(self.leaf)), ours, True)
        x = cx
        for i, st in enumerate(self.steps):
            if i >= self.shown:
                break
            ny = y - dy
            side = -1 if st.sibling_left else 1
            sx = x + side * (box_w + 24)
            sx = min(max(box_w / 2 + 4, sx), self.width() - box_w / 2 - 4)
            box(sx, y, short(st.sibling), sib, False)
            p.setPen(QPen(ours, 1.4))
            p.drawLine(QPointF(x, y - box_h / 2), QPointF(cx, ny + box_h / 2))
            p.setPen(QPen(sib, 1.0, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(sx, y - box_h / 2), QPointF(cx, ny + box_h / 2))
            last = i == len(self.steps) - 1
            colour = QColor(theme.OK) if last and self.root == self.signed else ours
            box(cx, ny, ("root " if last else "") + short(st.result), colour, True)
            x, y = cx, ny
        if self.shown > len(self.steps):
            good = self.root == self.signed
            p.setFont(theme.font(theme.BODY, QFont.Weight.Bold))
            p.setPen(QColor(theme.OK if good else theme.BAD))
            p.drawText(
                QRectF(0, 0, self.width(), 24),
                Qt.AlignmentFlag.AlignHCenter,
                ("= the signed root " if good else "≠ the signed root ") + short(self.signed),
            )
        p.end()


class TreeTab(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        w, lay = page(copy.short("live.tree"), "live.tree")
        QVBoxLayout(self).addWidget(w)
        row = QHBoxLayout()
        self.pick = ReceiptPicker(host)
        row.addWidget(self.pick)
        row.addWidget(button("Climb", "primary", self.climb, "play"))
        row.addStretch(1)
        lay.addLayout(row)
        self.facts = label("", "small", wrap=True)
        lay.addWidget(self.facts)
        self.tree = Tree()
        lay.addWidget(self.tree, 1)
        self.verdict = Verdict()
        lay.addWidget(self.verdict)
        self.empty = Empty("receipt", "Delete something first: every deletion gives a receipt.")
        lay.addWidget(self.empty)

    def arrive(self) -> None:
        self.pick.fill()
        has = self.pick.count() > 0
        self.empty.setVisible(not has)
        self.tree.setVisible(has)

    def climb(self) -> None:
        lsn = self.pick.lsn()
        if lsn is None:
            return

        def done(out: tuple[wow.Certificate, list[wow.Step], bytes, bool]) -> None:
            cert, steps, root, ok = out
            self.facts.setText(
                f"Your record's insert leaf #{cert.leaf_index} of {cert.tree_size:,} · "
                f"{len(steps)} hashes from the receipt (at most ⌈log₂ {cert.tree_size:,}⌉ = "
                f"{explain.levels(cert.tree_size)}) · your key {short(cert.user_key)} · "
                f"{cert.witnesses} witnesses cosigned the root.\n"
                "Each level: SHA-256(0x01 ‖ left ‖ right); the leaf: SHA-256(0x00 ‖ leaf) "
                "(RFC 9162 §2.1). Change any byte below and every hash above changes."
            )
            self.tree.play(cert.leaf, steps, root, cert.root)
            QTimer.singleShot(
                380 * (len(steps) + 2),
                lambda: self.verdict.set(
                    ok, "Studio recomputed every hash itself; the top equals the signed root"
                ),
            )
            self.host.changed()

        self.verdict.set(None, "climbing…")
        self.host.worker.submit(lambda: self.host.studio.climb(lsn), done, self.host.error)


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


class KillTab(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        w, lay = page(copy.short("live.kill"), "live.kill")
        QVBoxLayout(self).addWidget(w)
        lay.addWidget(button("Kill a deletion five times", "danger", self.run, "zap"), 0, LEFT)
        tiles = QHBoxLayout()
        self.t_none = Tile("times: none deleted")
        self.t_all = Tile("times: all deleted")
        self.t_first = Tile("times: it finished first")
        self.t_half = Tile("times: half deleted")
        for t in (self.t_none, self.t_all, self.t_first, self.t_half):
            tiles.addWidget(t)
        lay.addLayout(tiles)
        self.rows = QVBoxLayout()
        lay.addLayout(self.rows)
        lay.addWidget(label(copy.short("live.kill.timeline"), "small", wrap=True))
        self.timeline = Timeline()
        lay.addWidget(self.timeline)
        self.verdict = Verdict()
        lay.addWidget(self.verdict)
        lay.addStretch(1)
        self.marks: list[tuple[float, str]] = []

    def arrive(self) -> None:
        pass

    def run(self) -> None:
        s = self.host.studio
        rng = random.Random()
        self.marks = []
        self.timeline.set([])
        clear(self.rows)
        self.verdict.set(None, "deleting a person in a second process, and killing it…")

        def go(report: Any) -> list[wow.CrashDelete]:
            out = []
            for _ in range(5):
                account, _ = s.crash_test_person()
                r = s.crash_delete(account, rng.uniform(0.2, 1.3))
                out.append(r)
                report(r)
            return out

        def one(a: tuple[Any, ...]) -> None:
            r: wow.CrashDelete = a[0]
            text = {
                "none": "killed before the commit point: none deleted",
                "all": "killed after the commit point: all deleted",
                "finished first": "the deletion finished before the kill",
                "partial": f"HALF: {r.deleted} of {r.records} deleted",
            }[r.outcome]
            v = Verdict()
            v.set(
                r.outcome != "partial",
                f"{r.records} records · killed at {r.planned_ms:.0f} ms · {text}",
            )
            self.rows.addWidget(v)
            per = float(self.host.studio.numbers.get("delete_user_ms_per_record", 0) or 0)
            if per and r.outcome != "finished first":
                self.marks.append((r.planned_ms / (per * max(1, r.records)), r.outcome))
                self.timeline.set(self.marks)

        def done(out: list[wow.CrashDelete]) -> None:
            n = {
                k: sum(r.outcome == k for r in out)
                for k in ("none", "all", "finished first", "partial")
            }
            self.t_none.set(str(n["none"]), theme.OK)
            self.t_all.set(str(n["all"]), theme.OK)
            self.t_first.set(str(n["finished first"]), theme.MUTED)
            self.t_half.set(str(n["partial"]), theme.OK if n["partial"] == 0 else theme.BAD)
            self.verdict.set(*wow.kill_verdict([r.outcome for r in out]))
            self.host.changed()

        self.host.worker.submit(go, done, self.host.error, one)


class RaceTab(QWidget):
    CYCLES = 20_000

    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        w, lay = page(copy.short("live.race"), "live.race")
        QVBoxLayout(self).addWidget(w)
        lay.addWidget(label(copy.short("live.race.model"), "muted", wrap=True))
        row = QHBoxLayout()
        row.addWidget(
            button(f"Model: remove and re-add, {self.CYCLES:,} times", "", self.run, "play")
        )
        row.addWidget(
            button("Run the engine's proof (Part 1)", "primary", self.engine_proof, "shield")
        )
        row.addStretch(1)
        lay.addLayout(row)
        self.engine = Verdict()
        lay.addWidget(self.engine)
        tiles = QHBoxLayout()
        self.t_float = Tile("model: numbers of the float mean that changed")
        self.t_int = Tile("model: numbers of the integer sum that changed")
        tiles.addWidget(self.t_float)
        tiles.addWidget(self.t_int)
        lay.addLayout(tiles)
        self.plot = pg.PlotWidget()
        self.plot.setBackground(theme.SURFACE)
        self.plot.setMenuEnabled(False)
        self.plot.setLabel("bottom", "remove-and-re-add cycles")
        self.plot.setLabel("left", "numbers changed")
        self.plot.addLegend(offset=(-10, -50))
        self.f_line = self.plot.plot(
            [], [], pen=pg.mkPen(theme.BAD, width=2.5), name="float32 running mean (model)"
        )
        self.i_line = self.plot.plot(
            [], [], pen=pg.mkPen(theme.OK, width=2.5), name="integer sum (model)"
        )
        self.plot.setMinimumHeight(240)
        lay.addWidget(self.plot, 1)
        self.verdict = Verdict()
        lay.addWidget(self.verdict)
        self.xs: list[int] = []
        self.fs: list[int] = []
        self.ints: list[float] = []

    def arrive(self) -> None:
        pass

    def engine_proof(self) -> None:
        """The same claim from the engine: Part 1's own program, run now on the fixture."""

        def done(p: Proof | None) -> None:
            if p is None:
                return
            lines = [c for c, _ in p.checks if "SEVER's sum" in c or "float running mean" in c]
            ok = p.ok and all(dict(p.checks)[c] for c in lines)
            self.engine.set(ok, "sever-demo idea, run now: " + "; ".join(lines))
            self.host.changed()

        self.engine.set(None, "running sever-demo idea on the fixture…")
        self.host.worker.submit(
            lambda: self.host.studio.proof("idea", "synthetic"), done, self.host.error
        )

    def run(self) -> None:
        self.xs, self.fs, self.ints = [], [], []
        d = self.host.studio.corpus.d

        def step(a: tuple[Any, ...]) -> None:
            c, _, ierr, diff, _ = a
            self.xs.append(c)
            self.fs.append(diff)
            self.ints.append(ierr)
            self.f_line.setData(self.xs, self.fs)
            self.i_line.setData(self.xs, self.ints)
            self.t_float.set(f"{diff}/{d}", theme.BAD)
            self.t_int.set(f"{int(ierr)}/{d}", theme.OK)

        def done(r: wow.RaceResult) -> None:
            diff = r.differing[-1][1] if r.differing else 0
            self.verdict.set(
                r.identical and diff > 0,
                f"Model: same members all along, the float mean drifted in {diff} of {d} numbers;"
                " the integer sum is bit-identical",
            )
            self.host.changed()

        self.verdict.set(None, "racing…")
        self.host.worker.submit(
            lambda report: self.host.studio.race(self.CYCLES, report), done, self.host.error, step
        )


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
        row.addStretch(1)
        lay.addLayout(row)
        self.state = Verdict()
        lay.addWidget(self.state)
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
        palette = theme.OKABE_ITO
        return [pg.mkBrush(palette[int(j) % len(palette)]) for j in labels]

    def _draw(self, part: Any, trail: list[Any] | None) -> None:
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
    TABS = ("kmeans", "tree", "attacks", "kill", "race")

    def __init__(self, host: Host) -> None:
        super().__init__()
        self.tabs: dict[str, Any] = {
            "kmeans": KMeansTab(host),
            "tree": TreeTab(host),
            "attacks": AttackTab(host),
            "kill": KillTab(host),
            "race": RaceTab(host),
        }
        names = ("Groups made", "Log tree", "Attack lab", "Kill a delete", "Float vs exact")
        for k, name in zip(self.TABS, names, strict=True):
            self.addTab(self.tabs[k], name)
        self.currentChanged.connect(lambda i: self.tabs[self.TABS[i]].arrive())

    def arrive(self, tab: str | None = None, **kw: Any) -> None:
        if tab:
            self.setCurrentIndex(self.TABS.index(tab))
        self.tabs[self.TABS[self.currentIndex()]].arrive()
