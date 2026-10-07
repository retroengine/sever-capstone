"""``oracle-check`` (CLAUDE.md §6.3): where each Part 2 test gets its expected value.

    PYTHONPATH=python uv run python -m sever_testkit_p2.oracle_check check
    PYTHONPATH=python uv run python -m sever_testkit_p2.oracle_check report

Every test that names a requirement (``#[spec("SR-…")]``, ``@pytest.mark.spec("SR-…")``) also
declares its oracle, in the same annotation block:

    // oracle: A §14.3 segment header table                      (Rust, a line comment)
    @pytest.mark.oracle("A", "§14.3 segment header table")      (Python)

Oracles: **A** the spec (text, worked example, Appendix A, normative table, by hand); **B** an
independent oracle; **B-shared** a B oracle written by the same author as the code under test;
**C** Part 1's frozen code; **D** the code under test itself (round trip, no panic, label echo).

``check`` fails if a labelled test has no oracle or a malformed one, if an A oracle names no ``§``
or Appendix, or if a requirement Part 2 owns is checked only by D tests. ``report`` writes
``docs/TEST_ORACLES_P2.md``, with the B-shared tests the owner reviews by hand.
"""

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from sever_testkit.spec_trace import (
    PY_DEF,
    PY_MARK,
    QUOTED_ID,
    RUST_ATTR,
    RUST_FN,
    _section_key,
    load_catalogue,
)

REPORT: Final = Path("docs/TEST_ORACLES_P2.md")
KINDS: Final = ("A", "B", "B-shared", "C", "D")
NEEDS_SOURCE: Final = frozenset({"A", "B", "B-shared", "C"})

#: Where Part 2's tests live (CLAUDE.md §6.1; Build §5.5). Part 1's files are frozen and untagged.
PART2_RUST_CRATES: Final = [
    "sever-vfs", "sever-format", "sever-wal", "sever-appendstore", "sever-checkpoint",
    "sever-txn", "sever-engine", "sever-crashkit", "sever-p2", "sever-py-p2",
]  # fmt: skip
PART2_PY_PATHS: Final = [
    "python/sever_testkit_p2", "python/sever_refmodel_durable", "python/sever_db_p2",
    "tests/e2e", "tests/architecture/test_architecture_p2.py",
]  # fmt: skip

RUST_ORACLE: Final = re.compile(r"^\s*//\s*oracle:\s*(\S+)\s*(.*?)\s*$")
PY_ORACLE: Final = re.compile(
    r"""@pytest\.mark\.oracle\(\s*["']([^"']+)["']\s*(?:,\s*["']([^"']*)["']\s*)?\)"""
)
PY_ORACLE_ANY: Final = re.compile(r"@pytest\.mark\.oracle\(")
SPEC_REF: Final = re.compile(r"§\s*\d|Appendix\s+[A-Z]")


@dataclass
class Test:
    """One labelled test: its requirement IDs and declared oracles."""

    name: str
    requirements: list[str]
    oracles: list[tuple[str, str]]
    problems: list[str] = field(default_factory=list)


def _problems(oracles: list[tuple[str, str]]) -> list[str]:
    if not oracles:
        return ["no oracle declared"]
    out: list[str] = []
    for kind, source in oracles:
        if kind not in KINDS:
            out.append(f"unknown oracle {kind!r} (use one of {', '.join(KINDS)})")
        elif kind in NEEDS_SOURCE and not source:
            out.append(f"oracle {kind} names no source")
        elif kind == "A" and not SPEC_REF.search(source):
            out.append(f"oracle A source {source!r} names no § or Appendix")
    return out


def scan_rust(path: Path) -> list[Test]:
    """Each ``#[spec]`` and ``// oracle:`` belongs to the next ``fn``, as in ``spec_trace``."""
    out: list[Test] = []
    ids: list[str] = []
    oracles: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        o = RUST_ORACLE.match(line)
        if o:
            oracles.append((o.group(1), o.group(2)))
            continue
        m = RUST_ATTR.search(line)
        if m:
            ids.extend(QUOTED_ID.findall(m.group(1)))
            continue
        f = RUST_FN.search(line)
        if f:
            if ids:
                out.append(Test(f"{path.name}::{f.group(1)}", ids, oracles, _problems(oracles)))
            ids, oracles = [], []
    return out


def scan_python(path: Path) -> list[Test]:
    """Each ``@pytest.mark.spec`` and ``@pytest.mark.oracle`` belongs to the next ``def test_``."""
    out: list[Test] = []
    ids: list[str] = []
    oracles: list[tuple[str, str]] = []
    bad: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        o = PY_ORACLE.search(line)
        if o:
            oracles.append((o.group(1), o.group(2) or ""))
            continue
        if PY_ORACLE_ANY.search(line):
            bad.append(f"malformed oracle mark: {line.strip()}")
            continue
        m = PY_MARK.search(line)
        if m:
            ids.extend(QUOTED_ID.findall(m.group(1)))
            continue
        f = PY_DEF.search(line)
        if f:
            if ids:
                probs = bad + _problems(oracles)
                out.append(Test(f"{path.name}::{f.group(1)}", ids, oracles, probs))
            ids, oracles, bad = [], [], []
    return out


def part2_files(root: Path) -> tuple[list[Path], list[Path]]:
    """Rust and Python source files that hold Part 2 tests."""
    rust: list[Path] = []
    for crate in PART2_RUST_CRATES:
        rust.extend(sorted((root / "crates" / crate).rglob("*.rs")))
    py: list[Path] = []
    for rel in PART2_PY_PATHS:
        p = root / rel
        py.extend([p] if p.is_file() else sorted(p.rglob("*.py")))
    return rust, py


@dataclass
class Audit:
    """All labelled Part 2 tests, and per requirement the oracle kinds that check it."""

    tests: list[Test]
    by_requirement: dict[str, list[Test]]
    owned: list[str]

    def failures(self) -> list[str]:
        out = [f"{t.name}: {p}" for t in self.tests for p in t.problems]
        for rid in self.d_only():
            names = ", ".join(t.name for t in self.by_requirement[rid])
            out.append(f"{rid}: checked only by D (code-under-test) oracles: {names}")
        return out

    def d_only(self) -> list[str]:
        """Owned requirements whose tests all declare oracles, and all of them D."""
        out: list[str] = []
        for rid in self.owned:
            tests = self.by_requirement.get(rid, [])
            kinds = {k for t in tests for k, _ in t.oracles}
            if tests and kinds and kinds <= {"D"} and all(t.oracles for t in tests):
                out.append(rid)
        return out


def collect(root: Path, part: int = 2) -> Audit:
    rust, py = part2_files(root)
    tests = [t for p in rust for t in scan_rust(p)] + [t for p in py for t in scan_python(p)]
    by_req: dict[str, list[Test]] = defaultdict(list)
    for t in tests:
        for rid in t.requirements:
            by_req[rid].append(t)
    cat = load_catalogue(root)
    owned = sorted(
        (rid for rid, r in cat.items() if r.get("part") == part),
        key=lambda rid: (_section_key(str(cat[rid]["section"])), rid),
    )
    return Audit(tests, by_req, owned)


def _cell(oracles: list[tuple[str, str]]) -> str:
    if not oracles:
        return "**none**"
    return "<br>".join(f"**{k}** {s}".strip().replace("|", "\\|") for k, s in oracles)


def report(a: Audit) -> str:
    """The Markdown of ``docs/TEST_ORACLES_P2.md``."""
    counts: dict[str, int] = defaultdict(int)
    for t in a.tests:
        for k in {k for k, _ in t.oracles} or {"none"}:
            counts[k] += 1
    lines = [
        "# Test oracles, Part 2",
        "",
        "Generated by `python -m sever_testkit_p2.oracle_check report` (CLAUDE.md §6.3).",
        "Do not edit.",
        "",
        "Where each labelled test gets its expected value: **A** the spec by hand, **B** an",
        "independent oracle, **B-shared** an oracle by the same author as the code, **C** Part 1's",
        "frozen code, **D** the code under test itself. No requirement may rest on D alone.",
        "",
        f"**{len(a.tests)} labelled tests.** "
        + ", ".join(f"{k}: {counts[k]}" for k in (*KINDS, "none") if counts.get(k)),
        "",
        "## Requirements",
        "",
        "| Requirement | A | B | B-shared | C | D | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    d_only = set(a.d_only())
    for rid in a.owned:
        tests = a.by_requirement.get(rid, [])
        n = {k: sum(1 for t in tests if any(o == k for o, _ in t.oracles)) for k in KINDS}
        status = "**D only**" if rid in d_only else ("no test" if not tests else "ok")
        if any(t.problems for t in tests):
            status += " (untagged tests)"
        lines.append(f"| {rid} | " + " | ".join(str(n[k]) for k in KINDS) + f" | {status} |")
    shared = [t for t in a.tests if any(k == "B-shared" for k, _ in t.oracles)]
    lines += ["", "## B-shared: for the owner to review by hand", ""]
    if shared:
        lines += [
            "The expected values come from an oracle written by the same author as the code, so",
            "a shared misreading of the spec would pass. Check each oracle rule against its § by",
            "hand.",
            "",
        ]
        lines += [f"- `{t.name}` ({', '.join(t.requirements)}): {_cell(t.oracles)}" for t in shared]
    else:
        lines.append("None.")
    lines += ["", "## Tests", "", "| Test | Requirements | Oracle |", "|---|---|---|"]
    for t in sorted(a.tests, key=lambda t: t.name):
        lines.append(f"| `{t.name}` | {', '.join(t.requirements)} | {_cell(t.oracles)} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="oracle-check", description=__doc__)
    ap.add_argument("command", choices=["check", "report"])
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    root: Path = args.root
    a = collect(root)
    if args.command == "report":
        out = root / REPORT
        out.write_text(report(a), encoding="utf-8")
        print(out)
    fails = a.failures()
    for f in fails:
        print(f, file=sys.stderr)
    tagged = sum(1 for t in a.tests if not t.problems)
    print(
        f"Part 2: {tagged}/{len(a.tests)} labelled tests declare a valid oracle; "
        f"{len(a.d_only())} requirement(s) rest on D alone"
    )
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
