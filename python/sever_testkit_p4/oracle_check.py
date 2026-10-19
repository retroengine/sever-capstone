"""``oracle-check`` for Part 4 (CLAUDE.md §6.3): Part 2's frozen checker on Part 4's paths.

    PYTHONPATH=python uv run python -m sever_testkit_p4.oracle_check check
    PYTHONPATH=python uv run python -m sever_testkit_p4.oracle_check report

The rules are Part 2's, unchanged (``sever_testkit_p2.oracle_check``), as for Part 3: every test
that names a requirement declares its oracle (A, B, B-shared, C, D), an A oracle names a ``§`` or
Appendix, and no requirement Part 4 owns rests on D alone. ``report`` writes
``docs/TEST_ORACLES_P4.md``.
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Final

from sever_testkit.spec_trace import _section_key, load_catalogue
from sever_testkit_p2.oracle_check import Audit, Test, scan_python, scan_rust
from sever_testkit_p2.oracle_check import report as p2_report

REPORT: Final = Path("docs/TEST_ORACLES_P4.md")

#: Where Part 4's tests live (Build 3-4 §2.4). The crates may not exist yet; a missing directory
#: holds no tests.
PART4_RUST_DIRS: Final = [
    "crates/sever-keys", "crates/sever-seal", "crates/sever-erasure", "crates/sever-platform",
    "crates/sever-scan", "crates/sever-db", "crates/sever-py",
]  # fmt: skip
PART4_PY_PATHS: Final = [
    "python/sever_testkit_p4", "python/sever_db", "python/sever_experiments",
    "python/sever_report", "python/sever_demo_p4",
]  # fmt: skip
#: Part 4 test files in the shared level directories of ``tests/`` carry ``p4`` in their name.
PART4_TEST_GLOBS: Final = ["test_p4_*.py", "test_*_p4.py"]


def part4_files(root: Path) -> tuple[list[Path], list[Path]]:
    """Rust and Python source files that hold Part 4 tests (build output excluded)."""
    rust: list[Path] = []
    for rel in PART4_RUST_DIRS:
        base = root / rel
        if base.is_dir():
            rust.extend(
                p for p in sorted(base.rglob("*.rs")) if "target" not in p.relative_to(base).parts
            )
    py: list[Path] = []
    for rel in PART4_PY_PATHS:
        if (root / rel).is_dir():
            py.extend(sorted((root / rel).rglob("*.py")))
    tests = root / "tests"
    found = {p for g in PART4_TEST_GLOBS for p in tests.rglob(g)} if tests.is_dir() else set()
    py.extend(sorted(p for p in found if p not in py))
    return rust, py


def collect(root: Path, part: int = 4) -> Audit:
    rust, py = part4_files(root)
    tests: list[Test] = [t for p in rust for t in scan_rust(p)]
    tests += [t for p in py for t in scan_python(p)]
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


def report(a: Audit) -> str:
    """The Markdown of ``docs/TEST_ORACLES_P4.md``: Part 2's report, retitled."""
    text = p2_report(a)
    for old, new in (
        ("# Test oracles, Part 2", "# Test oracles, Part 4"),
        ("sever_testkit_p2.oracle_check", "sever_testkit_p4.oracle_check"),
    ):
        if old not in text:
            raise RuntimeError(f"Part 2's report no longer contains {old!r}")
        text = text.replace(old, new)
    return text


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="oracle-check-p4", description=__doc__)
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
        f"Part 4: {tagged}/{len(a.tests)} labelled tests declare a valid oracle; "
        f"{len(a.d_only())} requirement(s) rest on D alone"
    )
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
