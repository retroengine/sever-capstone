"""The proofs screen (each part's own program, run and read back), the sabotage lab, and the
evidence the project's tools generated."""

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import sabotage
from ..proofs import Proof
from . import theme
from .host import Host
from .widgets import Card, Console, button, label, tick, tick_colour

ABOUT = {
    "idea": (
        "Part 1 · The Idea",
        "A whole cohort is deleted. Each touched group's state (count, sum, blinding total, "
        "commitment, members) must equal the state rebuilt from its survivors alone, bit for bit "
        "(§5); a float running mean and a soft-delete index, given the same deletion, do not.",
    ),
    "durable": (
        "Part 2 · The Database",
        "A multi-group deletion, crashed on a simulated disk just before and just after its "
        "commit point, then a real process killed with SIGKILL at the same two places: after "
        "recovery, every record deleted or none, and the survivors check holds (§12).",
    ),
    "receipt": (
        "Part 3 · The Receipt",
        "The receipt end to end: inserted through the SDK, deleted, verified offline, one byte "
        "flipped, the limits stated, a person's certificates chained, the log audited (§11).",
    ),
    "erase": (
        "Part 4 · The Erasure",
        "A forensic scanner given the whole disk image, free space included, and every key it can "
        "carve from it. It recovers a live record (it can see), then finds nothing of the deleted "
        "ones. The same run built with group-key rotation skipped (SB-24) leaks (§13).",
    ),
}


class ProofCard(Card):
    def __init__(self, host: Host, name: str) -> None:
        title, note = ABOUT[name]
        super().__init__(title, note)
        self.host = host
        self.name = name
        row = QHBoxLayout()
        if name != "erase":
            row.addWidget(button("Recorded nq-10k run", "", lambda: self.load(None)))
        row.addWidget(
            button(
                "Run it now" if name == "erase" else "Run now: fixture",
                "primary",
                lambda: self.load("synthetic"),
            )
        )
        if name in ("idea", "durable", "receipt") and host.studio.data == "nq":
            row.addWidget(button("Run now: nq-10k", "", lambda: self.load("nq-10k")))
        row.addStretch(1)
        self.body.addLayout(row)
        self.source = label("", "muted", wrap=True)
        self.add(self.source)
        self.checks = label("", wrap=True)
        self.add(self.checks)
        self.detail = label("", "mono", wrap=True)
        self.detail.setTextFormat(Qt.TextFormat.RichText)
        self.detail.setStyleSheet("font-size: 9pt;")
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.checks.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.add(self.detail)

    def load(self, live: str | None) -> None:
        self.source.setText(
            "running…" + (" (an nq-10k run takes minutes)" if live == "nq-10k" else "")
        )
        self.checks.setText("")
        self.detail.setText("")

        def done(p: Proof | None) -> None:
            if p is None:
                self.source.setText("No recorded run in artefacts/demo/: run it now instead.")
                return
            self.render_proof(p)
            self.host.changed()

        self.host.worker.submit(
            lambda: self.host.studio.proof(self.name, live), done, self.host.error
        )

    def render_proof(self, p: Proof) -> None:
        self.source.setText(f"{p.source} · {'all checks pass' if p.ok else 'A CHECK FAILED'}")
        self.checks.setText(
            "<br>".join(
                f"<span style='color:{tick_colour(ok)}'>{tick(ok)}</span> {c}" for c, ok in p.checks
            )
        )
        r = p.report
        if self.name == "idea" and r:
            rows = [
                f"{'group':<24} {'n':>11}  {'blob after':<10}  {'survivors':<10}  exact",
            ]
            for g in r.get("groups", []):
                rows.append(
                    f"{g['group']:<24} {g['n_before']:>4} → {g['n_after']:<4}  "
                    f"{g['blob_sha_after'][:10]}  {g['survivors_blob_sha'][:10]}"
                    f"  {tick(g['exact'])}"
                )
            ghost = r.get("ghost", {}).get("per_group", [])
            if ghost:
                g0 = ghost[0]
                rows += [
                    "",
                    "the ghost, first group (distance from the survivors-only summary):",
                    f"  soft-delete IVF     {g0['soft_delete_distance']:.3e}"
                    "  (the record is still stored)",
                    f"  float running mean  {g0['float_mean_max_abs_diff']:.3e}"
                    f"  ({g0['float_mean_components_differing']} components differ)",
                    f"  SEVER-DB            {g0['sever_max_abs_diff']}  (bit-identical)",
                ]
            self.detail.setText("<pre>" + "\n".join(rows) + "</pre>")
        elif self.name == "durable" and r:
            rows = []
            for row in [*r.get("simulated", []), *r.get("sigkill", [])]:
                where = row.get("crash") or f"SIGKILL at {row.get('paused_at')}"
                rows.append(f"{where:<25} {row['verdict']:<13} {row['left']}/{row['of']} left")
            self.detail.setText("<pre>" + "\n".join(rows) + "</pre>")
        elif self.name == "receipt" and r:
            leaf = r.get("insert_leaf", {})
            du = r.get("delete_user", {})
            self.detail.setText(
                "<pre>"
                f"insert leaf {leaf.get('index')}: type {leaf.get('type')}, user key"
                f" {str(leaf.get('user_public_key', ''))[:16]}…\n"
                f"certificate: {r.get('certificate', {}).get('bytes')} bytes\n"
                f"flipped byte {r.get('flipped', {}).get('byte')}:"
                f" {r.get('flipped', {}).get('verdict')}\n"
                f"delete_user: {du.get('certificates')} certificates, {du.get('chained')} chained\n"
                f"audit: {du.get('audit')}"
                "</pre>"
            )
        elif self.name == "erase" and r:
            n, s = r.get("normal", {}), r.get("sb24", {})
            self.detail.setText(
                "<table cellspacing=8><tr><th></th><th>the real build</th><th>SB-24: key rotation"
                " skipped</th></tr>"
                + "".join(
                    f"<tr><td>{k}.</td><td>{n.get(k, '')}</td><td style='color:"
                    f"{theme.BAD if k in ('3', '5') else theme.TEXT}'>{s.get(k, '')}</td></tr>"
                    for k in ("1", "3", "5")
                )
                + "</table><p style='color:#8c92a6'>The program counts what the scan decrypted"
                " (old accumulator versions, deleted records' keys and payloads); it does not yet"
                " print the reconstructed vector itself (Build 3-4 §2.11 step 4).</p>"
            )


class ProofsScreen(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.addWidget(label("Proofs from inside the engine", "h2"))
        lay.addWidget(
            label(
                "Some claims cannot be seen through the SDK, by design: it never hands out a "
                "group's sum, and a forensic scan needs the raw disk. Each part ships a program "
                "that shows its claim from inside. Studio runs it and reads what it reports.",
                "muted",
                wrap=True,
            )
        )
        grid = QGridLayout()
        grid.setSpacing(12)
        self.cards = {n: ProofCard(host, n) for n in ("idea", "durable", "receipt", "erase")}
        for i, n in enumerate(("idea", "durable", "receipt", "erase")):
            grid.addWidget(self.cards[n], i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        lay.addStretch(1)

    def arrive(self, **kw: Any) -> None:
        name = kw.get("run")
        if name in self.cards:
            self.cards[name].load(kw.get("live"))


class SabotageScreen(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.addWidget(label("The sabotage lab", "h2"))
        lay.addWidget(
            label(
                "A test that never fails proves nothing. Each item below is the real code with "
                "exactly one deliberate bug, switched on by a build flag. Pick one and run the "
                "tests of the crate that owns it: at least one must go red (Build §2.6). Here red "
                "is the good outcome.",
                "muted",
                wrap=True,
            )
        )
        self.table = QTableWidget(len(sabotage.ITEMS), 4)
        self.table.setHorizontalHeaderLabels(["", "Planted bug", "Part", "Tests run"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 470)
        self.table.setColumnWidth(2, 50)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for i, it in enumerate(sabotage.ITEMS):
            for j, v in enumerate([it.id, it.text, str(it.part), it.target]):
                self.table.setItem(i, j, QTableWidgetItem(v))
        self.table.selectRow(23)
        self.table.setMinimumHeight(260)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.b_run = button("Plant it and run the tests", "danger", self.run)
        row.addWidget(self.b_run)
        self.verdict = label("", "h3", wrap=True)
        row.addWidget(self.verdict, 1)
        lay.addLayout(row)
        self.console = Console(200)
        lay.addWidget(self.console)

    def arrive(self, **kw: Any) -> None:
        pass

    def run(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        item = sabotage.ITEMS[rows[0].row()]
        self.console.clear()
        self.console.say(f"$ {' '.join(sabotage.command(item)[0])}   (compiling can take minutes)")
        self.verdict.setText(f"{item.id}: building with the bug, running the tests…")
        self.b_run.setEnabled(False)

        def progress(a: tuple[Any, ...]) -> None:
            self.console.say(str(a[0]))

        def done(o: sabotage.Outcome) -> None:
            self.b_run.setEnabled(True)
            colour = theme.OK if o.caught else theme.BAD
            self.verdict.setText(
                f"<span style='color:{colour}'>{tick(o.caught)} {o.id}: "
                + (f"caught, {o.summary}" if o.caught else o.summary)
                + "</span>"
            )
            cell = self.table.item(rows[0].row(), 0)
            if cell is not None:
                cell.setForeground(QColor(colour))
            self.host.changed()

        def fail(msg: str) -> None:
            self.b_run.setEnabled(True)
            self.host.error(msg)

        self.host.worker.submit(
            lambda report: self.host.studio.sabotage(item.id, lambda line: report(line)),
            done,
            fail,
            progress,
        )


class EvidenceScreen(QWidget):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.addWidget(label("The evidence", "h2"))
        lay.addWidget(
            label(
                "Read from the files the project's tools generated, nothing typed in: which "
                "requirements have tests, which test labels are proven able to fail, where each "
                "expected value comes from, every gate run with its commit, and the clean-room "
                "fairness runs as they ended, failures included.",
                "muted",
                wrap=True,
            )
        )
        self.lines = QVBoxLayout()
        lay.addLayout(self.lines)
        tables = QHBoxLayout()
        self.ledger = QTableWidget(0, 5)
        self.ledger.setHorizontalHeaderLabels(
            ["UTC", "Outcome", "Gate or measure", "Commit", "Run"]
        )
        self.ledger.verticalHeader().hide()
        self.ledger.horizontalHeader().setStretchLastSection(True)
        self.fair = QTableWidget(0, 5)
        self.fair.setHorizontalHeaderLabels(["Fairness run", "Part", "Outcome", "Tests", "Failing"])
        self.fair.verticalHeader().hide()
        self.fair.horizontalHeader().setStretchLastSection(True)
        lc = Card("Run ledger (docs/RUN_LEDGER.jsonl), newest first", "")
        lc.add(self.ledger)
        fc = Card("Fairness runs (results/fair-*.json)", "")
        fc.add(self.fair)
        tables.addWidget(lc, 3)
        tables.addWidget(fc, 2)
        lay.addLayout(tables, 1)

    def arrive(self, **kw: Any) -> None:
        def done(out: tuple[Any, Any, Any]) -> None:
            lines, led, fair = out
            while self.lines.count():
                it = self.lines.takeAt(0)
                w = it.widget() if it is not None else None
                if w is not None:
                    w.deleteLater()
            grid = QGridLayout()
            for i, ln in enumerate(lines):
                c = Card(ln.source, "", "card2")
                c.add(label(ln.claim, wrap=True))
                grid.addWidget(c, i // 5, i % 5)
            w = QWidget()
            w.setLayout(grid)
            self.lines.addWidget(w)
            self._fill(
                self.ledger,
                [[e["utc"], e["outcome"], e["gate"], e["commit"], e["command"]] for e in led],
                1,
            )
            self._fill(
                self.fair,
                [
                    [
                        f["run"],
                        str(f["part"]),
                        str(f["outcome"]),
                        str(f["tests"]),
                        str(f["failing"]),
                    ]
                    for f in fair
                ],
                2,
            )
            self.host.changed()

        self.host.worker.submit(self.host.studio.evidence, done, self.host.error)

    @staticmethod
    def _fill(t: QTableWidget, rows: list[list[str]], outcome_col: int) -> None:
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                item = QTableWidgetItem(v)
                if j == outcome_col:
                    item.setForeground(
                        QColor(
                            theme.OK if v == "PASS" else theme.BAD if v == "FAIL" else theme.TEXT
                        )
                    )
                t.setItem(i, j, item)
        t.resizeColumnsToContents()
