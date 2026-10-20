"""``proofs`` for Part 4 (CLAUDE.md §6.3): re-runnable evidence for every claim about a Part 4 test.

    PYTHONPATH=python uv run python -m sever_testkit_p4.proofs check

The rules are Part 2's (``sever_testkit_p2.proofs``), with Part 3's manifest entry (``Proof3``,
whose ``workspace`` field Part 4 leaves empty): a proof is a patch in ``tests/proofs/p4/`` that
breaks one rule, and the tests it names; ``check`` is static (Fast CI) and needs a red proof for
every (test, label) pair of a labelled Part 4 test. ``run`` applies each patch to the committed
HEAD in a temporary worktree and writes ``docs/PROOFS_P4.md``, with Part 3's runner pointed at Part
4's manifest (the runner is Part 3's file, which Part 4 does not edit, DB-89).

    PYTHONPATH=python uv run python -m sever_testkit_p4.proofs run [--only PR4-…]
"""

import argparse
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

import yaml

from sever_testkit_p2.oracle_check import Audit
from sever_testkit_p2.proofs import Verdict, _sh, unproven
from sever_testkit_p2.proofs import problems as p2_problems
from sever_testkit_p3 import proofs as p3proofs
from sever_testkit_p3.proofs import Proof3
from sever_testkit_p4 import oracle_check

__all__ = ["MANIFEST", "REPORT", "load", "main", "problems", "report", "run", "unproven"]

MANIFEST: Final = Path("tests/proofs/p4/MANIFEST.yaml")
REPORT: Final = Path("docs/PROOFS_P4.md")


def load(root: Path) -> list[Proof3]:
    raw: list[dict[str, Any]] = yaml.safe_load((root / MANIFEST).read_text(encoding="utf-8")) or []
    return [
        Proof3(
            id=str(e["id"]),
            claim=str(e["claim"]),
            kind=str(e["kind"]),
            requirements=[str(r) for r in e.get("requirements", [])],
            patch=str(e["patch"]),
            runner=str(e.get("runner", "cargo")),
            tests=[str(t) for t in e["tests"]],
            package=str(e.get("package", "")),
            env={str(k): str(v) for k, v in (e.get("env") or {}).items()},
            build=tuple(str(b) for b in e.get("build") or ()),
        )
        for e in raw
    ]


def problems(root: Path, proofs: list[Proof3], audit: Audit) -> list[str]:
    """Part 2's static checks, with patches looked up in ``tests/proofs/p4/``."""
    p2_missing = {f"{p.id}: patch {p.patch} is missing" for p in proofs}
    out = [x for x in p2_problems(root, list(proofs), audit) if x not in p2_missing]
    for p in proofs:
        if not (root / MANIFEST.parent / p.patch).is_file():
            out.append(f"{p.id}: patch {p.patch} is missing")
        if not p.id.startswith("PR4-"):
            out.append(f"{p.id}: a Part 4 proof ID starts with PR4-")
    return out


@contextmanager
def _part4_manifest() -> Iterator[None]:
    """Part 3's runner, reading Part 4's manifest and building Part 4's SDK and CLI (``native``,
    ``cli``) for the duration."""
    saved = (p3proofs.MANIFEST, p3proofs.load, p3proofs.SDK_CRATE, p3proofs.CLI_PACKAGE)
    (p3proofs.MANIFEST, p3proofs.load, p3proofs.SDK_CRATE, p3proofs.CLI_PACKAGE) = (  # type: ignore[misc]
        MANIFEST, load, "crates/sever-py/Cargo.toml", "sever-db"
    )  # fmt: skip
    try:
        yield
    finally:
        (p3proofs.MANIFEST, p3proofs.load, p3proofs.SDK_CRATE, p3proofs.CLI_PACKAGE) = saved  # type: ignore[misc]


def run(root: Path, only: list[str]) -> tuple[str, bool, list[Verdict]]:
    """Every Part 4 proof on the committed HEAD (Part 3's ``run``, on Part 4's manifest)."""
    with _part4_manifest():
        return p3proofs.run(root, only)


def report(head: str, dirty: bool, verdicts: list[Verdict], unproven_pairs: list[str]) -> str:
    text = p3proofs.report(head, dirty, verdicts, unproven_pairs)
    return (
        text.replace("# Proofs, Part 3", "# Proofs, Part 4", 1)
        .replace("sever_testkit_p3.proofs run", "sever_testkit_p4.proofs run", 1)
        .replace("(`tests/proofs/p3/`)", "(`tests/proofs/p4/`)", 1)
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="proofs-p4", description=__doc__)
    ap.add_argument("command", choices=["check", "run"])
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--only", nargs="*", default=[])
    args = ap.parse_args(argv)
    root: Path = args.root
    audit = oracle_check.collect(root)
    proofs = load(root)
    probs = problems(root, proofs, audit)
    pairs = unproven(list(proofs), audit)
    if args.command == "run":
        if probs:
            for x in probs:
                print(x, file=sys.stderr)
            return 1
        head, dirty, verdicts = run(root, args.only)
        if not args.only:
            (root / REPORT).write_text(report(head, dirty, verdicts, pairs), encoding="utf-8")
            print(root / REPORT)
        return 0 if all(v.ok for v in verdicts) else 1
    # A patch that no longer applies proves nothing: the code it breaks has moved.
    for patch in sorted({p.patch for p in proofs}):
        path = (root / MANIFEST.parent / patch).resolve()
        if _sh(["git", "apply", "--check", str(path)], root).returncode != 0:
            probs.append(f"{patch}: no longer applies to the working tree")
    for x in probs + [f"no red proof: {u}" for u in pairs]:
        print(x, file=sys.stderr)
    print(f"Part 4: {len(proofs)} proofs; {len(pairs)} label(s) without a red proof")
    return 1 if probs or pairs else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
