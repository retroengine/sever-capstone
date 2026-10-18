"""``proofs`` for Part 4 (CLAUDE.md §6.3): re-runnable evidence for every claim about a Part 4 test.

    PYTHONPATH=python uv run python -m sever_testkit_p4.proofs check

The rules are Part 2's (``sever_testkit_p2.proofs``), with Part 3's manifest entry (``Proof3``,
whose ``workspace`` field Part 4 leaves empty): a proof is a patch in ``tests/proofs/p4/`` that
breaks one rule, and the tests it names; ``check`` is static (Fast CI) and needs a red proof for
every (test, label) pair of a labelled Part 4 test. ``run`` (each patch applied to the committed
HEAD in a temporary worktree, writing ``docs/PROOFS_P4.md``) arrives with the first Part 4 proof:
until then the manifest is empty and there is nothing to run.
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Final

import yaml

from sever_testkit_p2.oracle_check import Audit
from sever_testkit_p2.proofs import _sh, unproven
from sever_testkit_p2.proofs import problems as p2_problems
from sever_testkit_p3.proofs import Proof3
from sever_testkit_p4 import oracle_check

__all__ = ["MANIFEST", "load", "main", "problems", "unproven"]

MANIFEST: Final = Path("tests/proofs/p4/MANIFEST.yaml")


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


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="proofs-p4", description=__doc__)
    ap.add_argument("command", choices=["check"])
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    root: Path = args.root
    audit = oracle_check.collect(root)
    proofs = load(root)
    probs = problems(root, proofs, audit)
    pairs = unproven(list(proofs), audit)
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
