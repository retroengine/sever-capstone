"""``spec-trace`` for Part 4 (Build §2.2): Part 1's frozen tool, told which sections Part 4 owns,
with Part 3's scan (which adds the ``verifier/`` and ``audit/`` workspaces).

PYTHONPATH=python uv run python -m sever_testkit_p4.spec_trace report --part 4
PYTHONPATH=python uv run python -m sever_testkit_p4.spec_trace check --part 4 [--complete]
PYTHONPATH=python uv run python -m sever_testkit_p4.spec_trace candidates --part 4
"""

import argparse
import sys
from pathlib import Path
from typing import Final

from sever_testkit import spec_trace as frozen
from sever_testkit_p3.spec_trace import collect

#: Subsections Part 4 owns (CLAUDE.md §6.1: §12.8–12.9, §13, §14.5, §14.7, §15.3–15.4, §15.8–15.9;
#: Build 3-4 §2.3 adds §12.1, §12.6, the sealer-1 rows of §14, §14.3–14.4, §14.8, the key steps of
#: §15.1, §15.2, §15.7, §16.3's scanner, §20.1, §20.3 and Appendix A's Part 4 sizes).
PART4_SECTIONS: Final = [
    "12.1", "12.6", "12.8", "12.9", "13", "13.1", "13.2", "13.3", "13.4",
    "14", "14.3", "14.4", "14.5", "14.7", "14.8",
    "15.1", "15.2", "15.3", "15.4", "15.7", "15.8", "15.9", "16.3", "20.1", "20.3",
]  # fmt: skip


def main(argv: list[str]) -> int:
    frozen.PART_SECTIONS.setdefault(4, PART4_SECTIONS)
    ap = argparse.ArgumentParser(prog="spec-trace-p4", description=__doc__)
    ap.add_argument("command", choices=["report", "check", "candidates"])
    ap.add_argument("--part", type=int, default=4)
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
    print(
        f"Part {a.part}: {len(owned) - len(missing)}/{len(owned)} requirements traced; "
        f"untraced: {len(missing)}"
    )
    return 1 if tr.unknown or (a.complete and missing) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
