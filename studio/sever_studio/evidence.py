"""The project's evidence, read from the files the tools generated (none of it is typed in here).

- ``docs/TRACE_PART_N.md``: requirements with a test (Build §2.2).
- ``docs/PROOFS_PN.md``: red and green proofs that each test label can fail (CLAUDE.md §6.3).
- ``docs/TEST_ORACLES_PN.md``: where each test's expected value comes from.
- ``docs/RUN_LEDGER.jsonl``: every gate and measure run, with its commit and outcome.
- ``results/fair-*.json``: the clean-room fairness runs (CLAUDE.md §6.4), shown as they ended,
  FAIL included.
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


def headlines(root: Path) -> list[Line]:
    """The bold summary line of each generated report."""
    out = []
    names = [f"TRACE_PART_{n}.md" for n in (1, 2, 3, 4)]
    names += [f"PROOFS_P{n}.md" for n in (2, 3, 4)]
    names += [f"TEST_ORACLES_P{n}.md" for n in (2, 3, 4)]
    for name in names:
        path = root / "docs" / name
        if path.exists():
            text = path.read_text("utf-8")
            m = _BOLD.search(text)
            if m:
                out.append(Line(name, (m[1] + m[2]).strip()))
    return out


def ledger(root: Path, last: int = 40) -> list[dict[str, Any]]:
    """The newest ``last`` run-ledger entries, newest first: when, what, commit, outcome."""
    path = root / "docs/RUN_LEDGER.jsonl"
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


def fairness(root: Path) -> list[dict[str, Any]]:
    """The fairness runs that were not dry runs, newest first."""
    rows = []
    for path in sorted((root / "results").glob("fair-*.json"), reverse=True):
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
