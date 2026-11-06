"""The project's evidence, read from the files the tools generated (none of it is typed in here).

``studio.sh setup`` copies them into the evidence folder named in ``config.toml`` (DB-119):

- ``TRACE_PART_N.md``: requirements with a test (Build §2.2).
- ``PROOFS_PN.md``: red and green proofs that each test label can fail (CLAUDE.md §6.3).
- ``TEST_ORACLES_PN.md``: where each test's expected value comes from.
- ``RUN_LEDGER.jsonl``: every gate and measure run, with its commit and outcome.
- ``fair-*.json``: the clean-room fairness runs (CLAUDE.md §6.4), shown as they ended.
- ``TAGS``: the freeze tags and the date of each (``git tag``), for the claim cards.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_BOLD = re.compile(r"\*\*([^*\n]*\d[^*\n]*)\*\*([^\n]*)")


@dataclass(frozen=True)
class Line:
    source: str
    claim: str


def headlines(folder: Path) -> list[Line]:
    """The bold summary line of each generated report."""
    out = []
    names = [f"TRACE_PART_{n}.md" for n in (1, 2, 3, 4)]
    names += [f"PROOFS_P{n}.md" for n in (2, 3, 4)]
    names += [f"TEST_ORACLES_P{n}.md" for n in (2, 3, 4)]
    for name in names:
        path = folder / name
        if path.exists():
            text = path.read_text("utf-8")
            m = _BOLD.search(text)
            if m:
                out.append(Line(name, (m[1] + m[2]).strip()))
    return out


def ledger(folder: Path, last: int = 40) -> list[dict[str, Any]]:
    """The newest ``last`` run-ledger entries, newest first: when, what, commit, outcome."""
    path = folder / "RUN_LEDGER.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text("utf-8").splitlines()[-last:]:
        e = json.loads(line)
        rows.append(
            {
                "utc": e.get("utc", "")[:16].replace("T", " "),
                "command": e.get("command", ""),
                "gate": e.get("gate") or e.get("measure") or "",
                "outcome": e.get("outcome", ""),
                "commit": str(e.get("commit", ""))[:8] + ("*" if e.get("git_dirty") else ""),
            }
        )
    return rows[::-1]


def fairness(folder: Path) -> list[dict[str, Any]]:
    """The fairness runs that were not dry runs, newest first."""
    rows = []
    for path in sorted(folder.glob("fair-*.json"), reverse=True):
        if path.stem.endswith("-dry"):
            continue
        d = json.loads(path.read_text("utf-8"))
        rows.append(
            {
                "run": d.get("run_id", path.stem),
                "part": d.get("part"),
                "outcome": d.get("outcome"),
                "tests": d.get("tests"),
                "failing": d.get("failing"),
            }
        )
    return rows


#: Each part's freeze tag (the newest erratum counts) and the gate that proves its claim.
PARTS = [
    ("1", "part-1-frozen", "P1-T2"),
    ("2", "part-2-frozen", "P2-T1"),
    ("3", "part-3-frozen", "P3-T1"),
    ("4", "part-4-frozen", "P4-T1"),
]


@dataclass(frozen=True)
class Status:
    part: str
    #: the freeze tag and its date, or ``("", "")`` when the part is not frozen
    tag: str
    tagged: str
    gate: str
    #: the newest ledger run of that gate: outcome, date, data slice ("" when none)
    outcome: str
    ran: str
    data: str

    @property
    def line(self) -> str:
        frozen = f"frozen: {self.tag} ({self.tagged})" if self.tag else "not frozen"
        run = (
            f"{self.gate} {self.outcome} on {self.ran}" + (f", {self.data}" if self.data else "")
            if self.outcome
            else f"{self.gate}: no run in the ledger"
        )
        return f"{frozen} · {run}"


def claim_status(folder: Path | None) -> list[Status]:
    """Each part's claim as the evidence has it: its freeze tag (``TAGS``) and the newest run of
    its gate in the run ledger. Nothing is assumed: a missing file shows as missing."""
    tags: dict[str, str] = {}
    runs: list[dict[str, Any]] = []
    if folder is not None:
        if (folder / "TAGS").exists():
            for line in (folder / "TAGS").read_text("utf-8").splitlines():
                name, _, date = line.partition(" ")
                tags[name] = date
        if (folder / "RUN_LEDGER.jsonl").exists():
            runs = [
                json.loads(x)
                for x in (folder / "RUN_LEDGER.jsonl").read_text("utf-8").split("\n")
                if x
            ]
    out = []
    for part, prefix, gate in PARTS:
        mine = sorted(t for t in tags if t == prefix or t.startswith(prefix + "-e"))
        tag = mine[-1] if mine else ""
        last = next(
            (e for e in reversed(runs) if re.search(rf"\b{gate}\b", str(e.get("gate") or ""))),
            None,
        )
        out.append(
            Status(
                part,
                tag,
                tags.get(tag, ""),
                gate,
                str(last.get("outcome", "")) if last else "",
                str(last.get("utc", ""))[:10] if last else "",
                str(last.get("data") or "") if last else "",
            )
        )
    return out
