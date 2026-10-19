"""``registers`` for Part 4: the sabotage, crash, key-file, platform and scan registers are
complete and agree with the requirement catalogue and the gap register (Build 3-4 §2.8–2.10;
Build §2.6; overview EX-2).

    PYTHONPATH=python uv run python -m sever_testkit_p4.registers check

``check`` fails unless ``spec/registers_p4.yaml`` lists exactly SB-24 … SB-30, CT-1 … CT-5 (the rows
of the spec §15.4 crash table), KF-1 … KF-6, PL-1 … PL-13 and SC-1 … SC-8 in order; every entry has
a text and names at least one known requirement, and at least one of each entry's requirements is a
Part 4 one; every sabotage item names a Part 4 crate, the test that catches it and whether the
scanner must find it (with what it finds); key-file and platform entries say whether the engine
must refuse or start, a platform override is one of the two flags, and every ``gap`` is a G-N of
``docs/SPEC_GAPS.md``.
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Final

import yaml

from sever_testkit.spec_trace import load_catalogue
from sever_testkit_p4.oracle_check import PART4_RUST_DIRS

REGISTER: Final = Path("spec/registers_p4.yaml")
GAPS: Final = Path("docs/SPEC_GAPS.md")
EXPECTED: Final = {
    "sabotage": [f"SB-{i}" for i in range(24, 31)],
    "crash": [f"CT-{i}" for i in range(1, 6)],
    "keyfile": [f"KF-{i}" for i in range(1, 7)],
    "platform": [f"PL-{i}" for i in range(1, 14)],
    "scan": [f"SC-{i}" for i in range(1, 9)],
}
CRATES: Final = frozenset(
    d.removeprefix("crates/") for d in PART4_RUST_DIRS if d.startswith("crates/")
)
EXPECT: Final = ("refuse", "start")
FLAGS: Final = ("allow_unsafe_memory", "allow_unsafe_fs")
WHERE: Final = ("image", "wal")


def _gap_ids(root: Path) -> set[str]:
    text = (root / GAPS).read_text(encoding="utf-8")
    return set(re.findall(r"^\| (G-\d+) \|", text, flags=re.MULTILINE))


def problems(root: Path) -> list[str]:
    reg: dict[str, list[dict[str, Any]]] = (
        yaml.safe_load((root / REGISTER).read_text(encoding="utf-8")) or {}
    )
    cat = load_catalogue(root)
    gaps = _gap_ids(root)
    out: list[str] = []
    for kind in reg:
        if kind not in EXPECTED:
            out.append(f"unknown register {kind!r}")
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
            if reqs and not any(cat.get(rid, {}).get("part") == 4 for rid in reqs):
                out.append(f"{eid}: names no Part 4 requirement")
            if "gap" in e and e["gap"] not in gaps:
                out.append(f"{eid}: gap {e['gap']!r} is not in {GAPS}")
            if kind == "sabotage":
                if e.get("crate") not in CRATES:
                    out.append(f"{eid}: crate {e.get('crate')!r} is not a Part 4 crate")
                if not str(e.get("caught_by", "")).strip():
                    out.append(f"{eid}: caught_by is empty")
                if not isinstance(e.get("scanner"), bool):
                    out.append(f"{eid}: scanner must be true or false")
                elif e["scanner"] and not str(e.get("finding", "")).strip():
                    out.append(f"{eid}: a scanner item says what the scanner finds")
            if kind in ("keyfile", "platform") and e.get("expect") not in EXPECT:
                out.append(f"{eid}: expect must be one of {EXPECT}")
            if kind == "platform" and "flag" in e:
                if e["flag"] not in FLAGS:
                    out.append(f"{eid}: flag {e['flag']!r} is not one of {FLAGS}")
                if e.get("expect") != "refuse":
                    out.append(f"{eid}: only a refusal has an override flag")
            if kind == "scan" and e.get("where") not in WHERE:
                out.append(f"{eid}: where must be one of {WHERE}")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="registers-p4", description=__doc__)
    ap.add_argument("command", choices=["check"])
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    probs = problems(args.root)
    for p in probs:
        print(p, file=sys.stderr)
    n = sum(len(v) for v in EXPECTED.values())
    print(f"Part 4 registers: {n} entries expected; {len(probs)} problem(s)")
    return 1 if probs else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
