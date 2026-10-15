"""``registers`` for Part 3: the attack, auditor-fault and sabotage registers are complete and agree
with the requirement catalogue (Build 3-4 §1.8; overview EX-4, DB-76; Build §2.6).

    PYTHONPATH=python uv run python -m sever_testkit_p3.registers check

``check`` fails unless ``spec/registers_p3.yaml`` lists exactly AT-1 … AT-20, AF-1 … AF-5 and
SB-16 … SB-23 in order, every entry names at least one requirement and every requirement is a Part 3
entry of ``spec/requirements.yaml``, every attack names its §11.3 steps (1–8) and whether it is
re-signed, and every sabotage item names a Part 3 crate.
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Final

import yaml

from sever_testkit.spec_trace import load_catalogue
from sever_testkit_p3.oracle_check import PART3_RUST_DIRS

REGISTER: Final = Path("spec/registers_p3.yaml")
EXPECTED: Final = {
    "attacks": [f"AT-{i}" for i in range(1, 21)],
    "faults": [f"AF-{i}" for i in range(1, 6)],
    "sabotage": [f"SB-{i}" for i in range(16, 24)],
}
CRATES: Final = frozenset(
    d.removeprefix("crates/") for d in PART3_RUST_DIRS if d.startswith("crates/")
)


def problems(root: Path) -> list[str]:
    reg: dict[str, list[dict[str, Any]]] = (
        yaml.safe_load((root / REGISTER).read_text(encoding="utf-8")) or {}
    )
    cat = load_catalogue(root)
    out: list[str] = []
    for kind, want in EXPECTED.items():
        entries = reg.get(kind) or []
        got = [str(e.get("id")) for e in entries]
        if got != want:
            out.append(f"{kind}: IDs {got} are not {want}")
        for e in entries:
            eid = e.get("id")
            if not str(e.get("text", "")).strip():
                out.append(f"{eid}: no text")
            reqs = e.get("requirements") or []
            if not reqs:
                out.append(f"{eid}: names no requirement")
            for rid in reqs:
                if rid not in cat:
                    out.append(f"{eid}: unknown requirement {rid}")
                elif cat[rid].get("part") != 3:
                    out.append(f"{eid}: {rid} is not a Part 3 requirement")
            if kind == "attacks":
                steps = e.get("steps") or []
                if not steps or any(not isinstance(s, int) or not 1 <= s <= 8 for s in steps):
                    out.append(f"{eid}: steps {steps} are not §11.3 steps 1–8")
                if not isinstance(e.get("resign"), bool):
                    out.append(f"{eid}: resign must be true or false")
            if kind == "sabotage":
                if e.get("crate") not in CRATES:
                    out.append(f"{eid}: crate {e.get('crate')!r} is not a Part 3 crate")
                if not str(e.get("caught_by", "")).strip():
                    out.append(f"{eid}: caught_by is empty")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="registers-p3", description=__doc__)
    ap.add_argument("command", choices=["check"])
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    probs = problems(args.root)
    for p in probs:
        print(p, file=sys.stderr)
    n = sum(len(v) for v in EXPECTED.values())
    print(f"Part 3 registers: {n} entries expected; {len(probs)} problem(s)")
    return 1 if probs else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
