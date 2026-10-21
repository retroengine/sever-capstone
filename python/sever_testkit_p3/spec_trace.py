"""``spec-trace`` for Part 3 (Build §2.2): Part 1's frozen tool, told which sections Part 3 owns,
and also scanning the ``verifier/`` and ``audit/`` workspaces (Build 3-4 §1.4), which live outside
``crates/`` where the frozen tool looks.

PYTHONPATH=python uv run python -m sever_testkit_p3.spec_trace report --part 3
PYTHONPATH=python uv run python -m sever_testkit_p3.spec_trace check --part 3 [--complete]
PYTHONPATH=python uv run python -m sever_testkit_p3.spec_trace candidates --part 3
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Final

from sever_testkit import spec_trace as frozen

#: Subsections Part 3 owns (CLAUDE.md §6.1: §9, §10, §11, §16.2–16.3; Build 3-4 §1 adds §3.3, §4.5,
#: the has_rt rule of §14.4 and the certificate and log steps of §15.1 and §15.3). §9.7 is Part 1's.
PART3_SECTIONS: Final = [
    "3.3", "4.5", "9", "9.1", "9.2", "9.3", "9.4", "9.5", "9.6", "9.8", "9.9",
    "10", "10.1", "10.2", "10.3", "10.4", "10.5", "11", "11.1", "11.2", "11.3",
    "14.4", "15.1", "15.3", "16.2", "16.3",
]  # fmt: skip
#: Rust code bases of Part 3 outside ``crates/`` (separate workspaces, Build 3-4 §1.6).
EXTRA_RUST: Final = ("verifier", "audit")


def collect(root: Path) -> frozen.Trace:
    """The frozen scan (``crates/``, ``python/``, ``tests/``) plus the separate workspaces."""
    tr = frozen.collect(root)
    for base in EXTRA_RUST:
        for p in sorted((root / base).rglob("*.rs")):
            if "target" in p.relative_to(root / base).parts:
                continue
            for rid, test in frozen._scan(p, frozen.RUST_ATTR, frozen.RUST_FN):
                if rid not in tr.requirements:
                    tr.unknown.append((rid, test))
                elif test not in tr.tests[rid]:
                    tr.tests[rid].append(test)
    return tr


#: An attribute opened on a line that does not close it (BH-1), by file suffix.
SPLIT_OPEN: Final = {
    ".rs": re.compile(r"^\s*#\[(?:sever_spec::)?spec\([^)]*$"),
    ".py": re.compile(r"^\s*@pytest\.mark\.spec\([^)]*$"),
}


def _frozen_files(root: Path) -> set[str]:
    out: set[str] = set()
    for m in sorted((root / "freeze").glob("PART-*.sha256")):
        for line in m.read_text(encoding="utf-8").splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                out.add(parts[1].lstrip("*"))
    return out


def split_attributes(root: Path) -> list[str]:
    """``path:line`` of every ``#[spec(`` or ``@pytest.mark.spec(`` that spans lines, outside frozen
    files. The frozen tracer, oracle check and proofs check read one line at a time, so a split
    attribute's labels are invisible to all three (BH-1)."""
    frozen_files = _frozen_files(root)
    out: list[str] = []
    for base in ("crates", "python", "tests", *EXTRA_RUST):
        for p in sorted((root / base).rglob("*")):
            pattern = SPLIT_OPEN.get(p.suffix)
            if pattern is None or "target" in p.relative_to(root).parts:
                continue
            rel = p.relative_to(root).as_posix()
            if rel in frozen_files:
                continue
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    out.append(f"{rel}:{n}")
    return out


def main(argv: list[str]) -> int:
    frozen.PART_SECTIONS.setdefault(3, PART3_SECTIONS)
    ap = argparse.ArgumentParser(prog="spec-trace-p3", description=__doc__)
    ap.add_argument("command", choices=["report", "check", "candidates"])
    ap.add_argument("--part", type=int, default=3)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--complete", action="store_true", help="every owned requirement needs a test")
    a = ap.parse_args(argv)
    root: Path = a.root
    if a.command == "candidates":
        sys.stdout.write(frozen.candidates(root, a.part))
        return 0
    tr = collect(root)
    if a.command == "report":
        out = root / f"docs/TRACE_PART_{a.part}.md"
        out.write_text(frozen.report(tr, a.part), encoding="utf-8")
        print(out)
    owned = [rid for rid, r in tr.requirements.items() if r.get("part") == a.part]
    missing = [rid for rid in owned if not tr.tests.get(rid)]
    for rid, test in tr.unknown:
        print(f"unknown requirement ID {rid} in {test}", file=sys.stderr)
    split = split_attributes(root)
    for at in split:
        print(f"{at}: a #[spec(…)] split over lines is invisible to the checks", file=sys.stderr)
    print(
        f"Part {a.part}: {len(owned) - len(missing)}/{len(owned)} requirements traced; "
        f"untraced: {missing}"
    )
    return 1 if tr.unknown or split or (a.complete and missing) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
