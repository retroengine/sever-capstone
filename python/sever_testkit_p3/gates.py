"""Part 3 gate runners that write the run ledger (Build §2.5, §2.8 Full tier; Build 3-4 §1.9).

    PYTHONPATH=python uv run python -m sever_testkit_p3.gates p3-mutants --jobs 2

``p3-mutants`` is the mutation part of gate P3-T9 (Build 3-4 §1.8 L12, §1.9): ``cargo-mutants`` on
``sever-crypto``, ``sever-cert`` and ``sever-log`` in the root workspace, and on the separate
``verifier/`` workspace. Mutation score >= 90 % on ``sever-crypto`` and the verifier, >= 85 % on the
others, each on its own; every surviving mutant triaged in ``docs/MUTANTS_P3.md``. Timeouts count
as not caught; unviable mutants (they do not build) are not scored. Its PASS in the ledger is also
what fair testing takes its blind bugs from (DB-75, ``docs/FAIR_TESTING.md`` FT-6).

The other Part 3 gates join this module as the modules they test are built.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sever_testkit import ledger

#: Mutated crates of the root workspace and their minimum score (Build 3-4 §1.9 P3-T9).
P3_MUTATED: Final = {"sever-crypto": 0.90, "sever-cert": 0.85, "sever-log": 0.85}
#: Tests run against every root-workspace mutant: the mutated crates and the crates built on them.
P3_MUTANT_TESTS: Final = ("sever-crypto", "sever-commit", "sever-log", "sever-cert", "sever-p3")
#: The verifier is its own workspace (Build 3-4 §1.6); all of it is mutated, all its tests run.
VERIFIER: Final = "verifier"
VERIFIER_MIN: Final = 0.90
TRIAGE: Final = Path("docs/MUTANTS_P3.md")


@dataclass(frozen=True)
class Score:
    """One scored unit (a crate, or the whole verifier)."""

    unit: str
    caught: int
    missed: int
    timeout: int
    unviable: int
    minimum: float

    @property
    def score(self) -> float:
        tested = self.caught + self.missed + self.timeout
        return self.caught / tested if tested else 0.0

    @property
    def ok(self) -> bool:
        return self.caught + self.missed + self.timeout > 0 and self.score >= self.minimum


def survivors(outcomes: dict[str, Any], prefix: str = "") -> list[str]:
    """Missed and timed-out mutants, as ``path:line:col: replacement`` (the triage key)."""
    out: list[str] = []
    for o in outcomes.get("outcomes", []):
        m = o.get("scenario", {}).get("Mutant") if isinstance(o.get("scenario"), dict) else None
        if m and o.get("summary") in ("MissedMutant", "Timeout"):
            out.append(prefix + str(m["name"]).split(" in ")[0])
    return out


def score(
    outcomes: dict[str, Any], minimum: dict[str, float], unit: str | None = None
) -> list[Score]:
    """Per-unit counts from a ``cargo-mutants`` ``outcomes.json``. Each mutant's unit is its
    package, or ``unit`` for every mutant when given (the verifier is scored as one). A unit in
    ``minimum`` with no mutant at all scores 0: a crate that produced no mutants is not a pass."""
    counts: dict[str, dict[str, int]] = {u: {} for u in minimum}
    keys = {"CaughtMutant": "caught", "MissedMutant": "missed", "Timeout": "timeout",
            "Unviable": "unviable"}  # fmt: skip
    for o in outcomes.get("outcomes", []):
        m = o.get("scenario", {}).get("Mutant") if isinstance(o.get("scenario"), dict) else None
        k = keys.get(str(o.get("summary")))
        if not m or k is None:
            continue
        u = unit or str(m.get("package", ""))
        c = counts.setdefault(u, {})
        c[k] = c.get(k, 0) + 1
    return [
        Score(
            u,
            caught=c.get("caught", 0),
            missed=c.get("missed", 0),
            timeout=c.get("timeout", 0),
            unviable=c.get("unviable", 0),
            minimum=minimum.get(u, 1.0),
        )
        for u, c in sorted(counts.items())
    ]


def untriaged(missed: list[str], triage: str) -> list[str]:
    return [m for m in missed if m not in triage]


def _missing_code(root: Path) -> list[str]:
    need = [
        root / "crates" / c / "Cargo.toml" for c in dict.fromkeys((*P3_MUTATED, *P3_MUTANT_TESTS))
    ]
    need.append(root / VERIFIER / "Cargo.toml")
    return [str(p.relative_to(root)) for p in need if not p.is_file()]


def _mutants(tree: Path, out_dir: Path, args: list[str], tmp: Path) -> tuple[int, dict[str, Any]]:
    shutil.rmtree(out_dir, ignore_errors=True)
    run = subprocess.run(["cargo", "mutants", "--timeout", "300", "-o", str(out_dir), *args],
                         cwd=tree, capture_output=True, text=True, check=False,
                         env={**os.environ, "TMPDIR": str(tmp)})  # fmt: skip
    path = out_dir / "mutants.out/outcomes.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return run.returncode, data


def p3_mutants(root: Path, jobs: int) -> int:
    """P3-T9 (mutants): every unit at its minimum score, every survivor triaged."""
    missing = _missing_code(root)
    if missing:
        print(f"p3-mutants: not runnable yet, missing {missing}", file=sys.stderr)
        return 2
    cmd = f"gates p3-mutants --jobs {jobs}"
    gate = "P3-T9 mutants"
    started = ledger.start(root, cmd, gate=gate, mutated=[*P3_MUTATED, VERIFIER],
                           tests=list(P3_MUTANT_TESTS))  # fmt: skip
    tree = Path.home() / f".cache/sever-mutants-{started['commit'][:12]}"
    tmp = Path.home() / ".cache/mutants-tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=root, check=False,
                   capture_output=True)  # fmt: skip
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(tree), started["commit"]], cwd=root, check=True
    )
    try:
        args = ["-j", str(jobs)]
        for p in P3_MUTATED:
            args += ["-p", p]
        for p in P3_MUTANT_TESTS:
            args += ["--test-package", p]
        rc_root, out_root = _mutants(tree, root / "traces/mutants-p3-gate", args, tmp)
        rc_ver, out_ver = _mutants(
            tree,
            root / "traces/mutants-p3-verifier",
            ["-j", str(jobs), "-d", VERIFIER, "--workspace", "--test-workspace", "true"],
            tmp,
        )
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=root, check=False,
                       capture_output=True)  # fmt: skip
    scores = score(out_root, dict(P3_MUTATED)) + score(
        out_ver, {VERIFIER: VERIFIER_MIN}, unit=VERIFIER
    )
    missed = survivors(out_root) + survivors(out_ver, prefix=f"{VERIFIER}/")
    triage = (root / TRIAGE).read_text(encoding="utf-8") if (root / TRIAGE).exists() else ""
    left = untriaged(missed, triage)
    passed = all(s.ok for s in scores) and not left
    data_out = {
        "gate": "P3-T9: mutation score >= 90 % (sever-crypto, verifier), >= 85 % (sever-cert, "
        "sever-log); every survivor triaged",
        "scores": {
            s.unit: {
                "score": s.score,
                "minimum": s.minimum,
                "caught": s.caught,
                "missed": s.missed,
                "timeout": s.timeout,
                "unviable": s.unviable,
            }
            for s in scores
        },
        "missed": missed,
        "untriaged": left,
        "cargo_mutants_exit": {"root": rc_root, VERIFIER: rc_ver},
        "outcome": "PASS" if passed else "FAIL",
    }
    path, sha = ledger.result_file(
        root, f"p3-mutants-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", data_out
    )
    ledger.append(
        root,
        ledger.entry(root, cmd, gate=gate, outcome=data_out["outcome"],
                     run_commit=started["commit"], result_file=str(path.relative_to(root)),
                     result_sha256=sha, scores={s.unit: s.score for s in scores},
                     untriaged=len(left)),
    )  # fmt: skip
    print(json.dumps({s.unit: round(s.score, 4) for s in scores}
                     | {"untriaged": len(left), "outcome": data_out["outcome"]}))  # fmt: skip
    return 0 if passed else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gates-p3", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    mu = sub.add_parser("p3-mutants")
    mu.add_argument("--jobs", type=int, default=2)
    mu.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    if args.cmd == "p3-mutants":
        return p3_mutants(args.root.resolve(), args.jobs)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
