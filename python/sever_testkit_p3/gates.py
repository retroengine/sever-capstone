"""Part 3 gate runners that write the run ledger (Build §2.5, §2.8 Full tier; Build 3-4 §1.9).

    PYTHONPATH=python uv run python -m sever_testkit_p3.gates p3-mutants --jobs 2

``p3-mutants`` is the mutation part of gate P3-T9 (Build 3-4 §1.8 L12, §1.9): ``cargo-mutants`` on
``sever-crypto``, ``sever-cert`` and ``sever-log`` in the root workspace, and on the separate
``verifier/`` workspace. Mutation score >= 90 % on ``sever-crypto`` and the verifier, >= 85 % on the
others, each on its own; every surviving mutant triaged in ``docs/MUTANTS_P3.md``. Timeouts count
as not caught; unviable mutants (they do not build) are not scored. Its PASS in the ledger is also
what fair testing takes its blind bugs from (DB-75, ``docs/FAIR_TESTING.md`` FT-6).

``p3-crash`` is gate P3-T4 (T-1 with certificates): Part 2's oracle streams through the Part 3
engine with a crash at every VFS operation (``sever-crashkit-p3 campaign``); per seed the oracle
checks every recovered state, and the kit checks the log after every recovery: no orphaned leaf, no
certificate for a rolled-back deletion, every delete leaf's certificate retrievable and valid.

``p3-replay`` is gate P3-T5 (T-3, complete): Part 1's frozen traces through the Part 3 engine, with
the five-field equivalence, ``C_S`` = Σ ``C_t`` and every certificate checked against the commitment
model (``sever-crashkit-p3 replay``).

``p3-attacks`` is gates P3-T1 and P3-T2 (T-4): per seed, 1,000 honest certificates from the engine
and every attack of the register on each, judged by the independent verifier in batch mode: 100 %
of the honest ones accepted, 100 % of the attacks rejected at a step the register lists.

``p3-measures`` is measure P3-T13 (recorded as found): proof and verification time, certificate
size.

``p3-fuzz`` is gate P3-T10: every Part 3 parser, in the engine (``fuzz-p3``) and in the verifier
(``verifier/fuzz``), ``--runs`` executions each, 0 crashes.

``p3-coverage`` is the coverage part of P3-T9: lines >= 95 % on ``sever-crypto`` and the verifier,
>= 90 % on ``sever-commit``, ``sever-log``, ``sever-cert``.

``p3-checks`` is ``scripts/ci.sh full-checks`` (P3-T3, P3-T6 … P3-T8, P3-T11, P3-T12 and the
sabotage register SB-1 … SB-23, P3-T9) as one ledger entry. ``p3-spikes`` is the proof spike of
Build 3-4 §1.11.
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sever_refmodel_durable import oracle as durable
from sever_testkit import ledger
from sever_testkit.seeds import SEEDS

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
    keys = {
        "CaughtMutant": "caught",
        "MissedMutant": "missed",
        "Timeout": "timeout",
        "Unviable": "unviable",
    }
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
    run = subprocess.run(
        ["cargo", "mutants", "--timeout", "300", "-o", str(out_dir), *args],
        cwd=tree,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "TMPDIR": str(tmp)},
    )
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
    started = ledger.start(
        root, cmd, gate=gate, mutated=[*P3_MUTATED, VERIFIER], tests=list(P3_MUTANT_TESTS)
    )
    tree = Path.home() / f".cache/sever-mutants-{started['commit'][:12]}"
    tmp = Path.home() / ".cache/mutants-tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(tree)],
        cwd=root,
        check=False,
        capture_output=True,
    )
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
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(tree)],
            cwd=root,
            check=False,
            capture_output=True,
        )
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
        ledger.entry(
            root,
            cmd,
            gate=gate,
            outcome=data_out["outcome"],
            run_commit=started["commit"],
            result_file=str(path.relative_to(root)),
            result_sha256=sha,
            scores={s.unit: s.score for s in scores},
            untriaged=len(left),
        ),
    )
    print(
        json.dumps(
            {s.unit: round(s.score, 4) for s in scores}
            | {"untriaged": len(left), "outcome": data_out["outcome"]}
        )
    )
    return 0 if passed else 1


def _stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _record(
    root: Path,
    cmd: str,
    gate: str,
    started: dict[str, Any],
    name: str,
    data_out: dict[str, Any],
    **extra: Any,
) -> None:
    path, sha = ledger.result_file(root, f"{name}-{_stamp()}.json", data_out)
    ledger.append(
        root,
        ledger.entry(
            root,
            cmd,
            gate=gate,
            outcome=data_out["outcome"],
            run_commit=started["commit"],
            result_file=str(path.relative_to(root)),
            result_sha256=sha,
            **extra,
        ),
    )


def _kit(root: Path, commit: str) -> Path:
    """Builds the gate kit (release) into a target directory owned by this run."""
    target = root / f"target/gate-p3-{commit[:12]}"
    subprocess.run(
        [
            "cargo",
            "build",
            "-q",
            "--release",
            "-p",
            "sever-crashkit-p3",
            "--target-dir",
            str(target),
        ],
        cwd=root,
        check=True,
    )
    return target / "release/sever-crashkit-p3"


def _verifier(root: Path) -> Path:
    subprocess.run(
        ["cargo", "build", "-q", "--release", "--offline"],
        cwd=root / VERIFIER,
        check=True,
        env={**os.environ, "CARGO_TARGET_DIR": str(root / VERIFIER / "target")},
    )
    return root / VERIFIER / "target/release/sever-verify"


def _crash_seed(root: Path, data: str, seed: int, kit: Path, extra: list[str]) -> dict[str, Any]:
    t0 = time.time()
    oracle_path = root / f"traces/p2-oracle-{data}-seed{seed}.jsonl"
    if not oracle_path.exists():
        durable._main(["write", "--data", data, "--seed", str(seed), "--root", str(root)])
    out = root / f"traces/p3-crash-{data}-seed{seed}.jsonl"
    run = subprocess.run(
        [
            str(kit),
            "campaign",
            "--oracle",
            str(oracle_path),
            "--root",
            str(root),
            "--out",
            str(out),
            "--seed",
            str(seed),
            *extra,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    summary = json.loads(out.read_text().splitlines()[-1]) if out.exists() else {}
    v = durable.check(oracle_path, out) if out.exists() else None
    verdict = {**v.__dict__, "failures": v.failures()} if v else {}
    p3 = (
        "orphaned_leaves",
        "rolled_back_certificates",
        "bad_certificates",
        "main_mismatches",
        "skipped",
    )
    passed = (
        run.returncode == 0
        and verdict.get("failures") == 0
        and verdict.get("crash_points", 0) > 0
        and all(summary.get(k) == 0 for k in p3)
        and summary.get("certificates_checked", 0) > 0
    )
    result = {
        "seed": seed,
        "outcome": "PASS" if passed else "FAIL",
        "summary": summary,
        "verdict": verdict,
        "rc": run.returncode,
        "stderr_tail": run.stderr[-2000:],
        "oracle_sha256": hashlib.sha256(oracle_path.read_bytes()).hexdigest(),
        "results_sha256": hashlib.sha256(out.read_bytes()).hexdigest() if out.exists() else None,
        "seconds": round(time.time() - t0),
    }
    print(json.dumps({"seed": seed, "outcome": result["outcome"], "summary": summary}), flush=True)
    return result


def p3_crash(root: Path, data: str, seeds: list[int], jobs: int, extra: list[str]) -> int:
    """P3-T4: the crash campaign with certificates, every seed."""
    cmd = f"gates p3-crash --data {data} --seeds {seeds} {' '.join(extra)}".strip()
    gate = "P3-T4"
    started = ledger.start(root, cmd, gate=gate, data=data, seeds=seeds)
    kit = _kit(root, started["commit"])
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        per_seed = list(
            pool.map(
                _crash_seed,
                [root] * len(seeds),
                [data] * len(seeds),
                seeds,
                [kit] * len(seeds),
                [extra] * len(seeds),
            )
        )
    passed = all(r["outcome"] == "PASS" for r in per_seed)
    data_out = {
        "gate": "P3-T4: 0 exactness violations, 0 lost acknowledged operations, 0 "
        "certificates for rolled-back deletions, 0 orphaned leaves (T-1 with certificates)",
        "data": data,
        "seeds": per_seed,
        "outcome": "PASS" if passed else "FAIL",
    }
    _record(
        root,
        cmd,
        gate,
        started,
        f"p3-crash-{data}",
        data_out,
        data=data,
        seeds=seeds,
        summary={str(r["seed"]): r["summary"] for r in per_seed},
    )
    return 0 if passed else 1


def _replay_one(root: Path, kit: Path, data: str, seed: int, mode: str) -> dict[str, Any]:
    trace = root / f"traces/p1-{data}-seed{seed}.jsonl"
    out = root / f"traces/p3-replay-{data}-seed{seed}-{mode}.json"
    t0 = time.time()
    run = subprocess.run(
        [
            str(kit),
            "replay",
            "--trace",
            str(trace),
            "--root",
            str(root),
            "--mode",
            mode,
            "--out",
            str(out),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    rep = json.loads(out.read_text()) if out.exists() and out.stat().st_size else {}
    ok = run.returncode == 0 and rep.get("passed") is True
    r = {
        "seed": seed,
        "mode": mode,
        "outcome": "PASS" if ok else "FAIL",
        "report": rep,
        "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
        "stderr_tail": run.stderr[-1500:],
        "seconds": round(time.time() - t0),
    }
    print(json.dumps({k: r[k] for k in ("seed", "mode", "outcome")}), flush=True)
    return r


def p3_replay(root: Path, data: str, seeds: list[int], modes: list[str], jobs: int) -> int:
    """P3-T5: Part 1's traces through the Part 3 engine, five fields and certificates."""
    cmd = f"gates p3-replay --data {data} --seeds {seeds} --modes {','.join(modes)}"
    gate = "P3-T5"
    started = ledger.start(root, cmd, gate=gate, data=data, seeds=seeds)
    kit = _kit(root, started["commit"])
    jobs_list = [(s, m) for s in seeds for m in modes]
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        runs = list(
            pool.map(
                _replay_one,
                [root] * len(jobs_list),
                [kit] * len(jobs_list),
                [data] * len(jobs_list),
                [s for s, _ in jobs_list],
                [m for _, m in jobs_list],
            )
        )
    passed = all(r["outcome"] == "PASS" for r in runs)
    data_out = {
        "gate": "P3-T5: 0 mismatches on the five-field equivalence and the certificate "
        "arithmetic against the model (T-3, complete)",
        "data": data,
        "runs": runs,
        "outcome": "PASS" if passed else "FAIL",
    }
    _record(
        root,
        cmd,
        gate,
        started,
        f"p3-replay-{data}",
        data_out,
        data=data,
        seeds=seeds,
        summary={f"{r['seed']}-{r['mode']}": r["outcome"] for r in runs},
    )
    return 0 if passed else 1


def register_steps(root: Path) -> dict[str, list[int]]:
    text = (root / "spec/registers_p3.yaml").read_text(encoding="utf-8")
    return {
        m[0]: [int(x) for x in m[1].split(",")]
        for m in re.findall(r"\{id: (AT-\d+),.*?steps: \[([\d, ]+)\]", text)
    }


def judge(verdicts: Path, steps: dict[str, list[int]]) -> dict[str, Any]:
    """Every honest certificate accepted; every attack rejected at a step its register row lists."""
    honest = [0, 0]
    attacks: dict[str, list[int]] = {k: [0, 0] for k in steps}
    wrong: list[dict[str, Any]] = []
    with verdicts.open(encoding="utf-8") as f:
        for raw in f:
            v = json.loads(raw)
            k = v["kind"]
            if k == "honest":
                honest[0] += 1
                honest[1] += bool(v["accepted"])
                if not v["accepted"] and len(wrong) < 20:
                    wrong.append(v)
                continue
            row = attacks.setdefault(k, [0, 0])
            row[0] += 1
            good = not v["accepted"] and v.get("step") in steps.get(k, [])
            row[1] += good
            if not good and len(wrong) < 20:
                wrong.append(v)
    ok = (
        honest[0] > 0
        and honest[0] == honest[1]
        and all(n > 0 and n == g for n, g in attacks.values())
        and set(attacks) == set(steps)
    )
    return {"honest": honest, "attacks": attacks, "wrong": wrong, "ok": ok}


def p3_attacks(root: Path, data: str, seeds: list[int], n: int, jobs: int) -> int:
    """P3-T1, P3-T2: honest certificates accepted, attacks rejected, by the separate verifier."""
    cmd = f"gates p3-attacks --data {data} --seeds {seeds} --n {n}"
    gate = "P3-T1, P3-T2"
    started = ledger.start(root, cmd, gate=gate, data=data, seeds=seeds, n=n)
    kit = _kit(root, started["commit"])
    verifier = _verifier(root)
    steps = register_steps(root)

    def one(seed: int) -> dict[str, Any]:
        batch = root / f"traces/p3-attacks-{data}-seed{seed}.jsonl"
        out = root / f"traces/p3-attacks-{data}-seed{seed}.verdicts.jsonl"
        gen = subprocess.run(
            [
                str(kit),
                "attacks",
                "--root",
                str(root),
                "--data",
                data,
                "--seed",
                str(seed),
                "--n",
                str(n),
                "--out",
                str(batch),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        with out.open("w", encoding="utf-8") as f:
            ver = subprocess.run(
                [str(verifier), "--batch", str(batch)],
                cwd=root,
                stdout=f,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        j = judge(out, steps) if gen.returncode == 0 and ver.returncode == 0 else {"ok": False}
        r = {
            "seed": seed,
            "outcome": "PASS" if j["ok"] else "FAIL",
            "judged": j,
            "generator": gen.stderr[-500:],
            "verifier_rc": ver.returncode,
        }
        print(json.dumps({"seed": seed, "outcome": r["outcome"]}), flush=True)
        return r

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        per_seed = list(pool.map(one, seeds))
    passed = all(r["outcome"] == "PASS" for r in per_seed)
    data_out = {
        "gate": "P3-T1: 100 % of honest certificates accepted by the independent verifier; "
        "P3-T2: 100 % of AT-1 … AT-20 rejected on every honest certificate",
        "data": data,
        "n": n,
        "seeds": per_seed,
        "outcome": "PASS" if passed else "FAIL",
    }
    _record(
        root,
        cmd,
        gate,
        started,
        f"p3-attacks-{data}",
        data_out,
        data=data,
        seeds=seeds,
        summary={str(r["seed"]): r["outcome"] for r in per_seed},
    )
    return 0 if passed else 1


def p3_measures(root: Path, data: str, n: int) -> int:
    """P3-T13 (a measure): recorded as found."""
    cmd = f"gates p3-measures --data {data} --n {n}"
    gate = "P3-T13 (measure)"
    started = ledger.start(root, cmd, gate=gate, data=data)
    kit = _kit(root, started["commit"])
    out = root / f"traces/p3-measures-{data}.json"
    run = subprocess.run(
        [
            str(kit),
            "measure",
            "--root",
            str(root),
            "--data",
            data,
            "--n",
            str(n),
            "--out",
            str(out),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    found = json.loads(out.read_text()) if out.exists() and out.stat().st_size else {}
    data_out = {
        "measure": "P3-T13",
        "data": data,
        "found": found,
        "rc": run.returncode,
        "outcome": "RECORDED" if run.returncode == 0 else "ERROR",
        "stderr_tail": run.stderr[-1000:],
    }
    _record(root, cmd, gate, started, f"p3-measures-{data}", data_out, data=data)
    print(json.dumps(data_out))
    return 0 if run.returncode == 0 else 1


#: Fuzz targets: (fuzz directory, target).
FUZZ: Final = (
    ("fuzz-p3", "certificate"),
    ("fuzz-p3", "log_record"),
    ("fuzz-p3", "witnessed"),
    ("fuzz-p3", "placement"),
    ("verifier/fuzz", "verify"),
    ("audit/fuzz", "export"),
)


def p3_fuzz(root: Path, runs: int) -> int:
    """P3-T10: ``runs`` executions per parser, in both code bases, 0 crashes."""
    cmd = f"gates p3-fuzz --runs {runs}"
    gate = "P3-T10"
    started = ledger.start(root, cmd, gate=gate, runs=runs, targets=[f"{d}:{t}" for d, t in FUZZ])
    procs = {}
    for d, t in FUZZ:
        corpus = root / d / "corpus" / t
        corpus.mkdir(parents=True, exist_ok=True)
        seeds_dir = root / d / "seeds" / t
        procs[f"{d}:{t}"] = subprocess.Popen(
            [
                "cargo",
                "+nightly",
                "fuzz",
                "run",
                "--fuzz-dir",
                d,
                "-O",
                t,
                str(corpus),
                *([str(seeds_dir)] if seeds_dir.is_dir() else []),
                "--",
                f"-runs={runs}",
                "-print_final_stats=1",
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    out: dict[str, Any] = {}
    for name, p in procs.items():
        log = p.communicate()[0]
        done = [ln for ln in log.splitlines() if ln.startswith("Done ")]
        out[name] = {
            "exit": p.returncode,
            "done": done[-1] if done else None,
            "crashed": p.returncode != 0 or "panicked" in log or "ERROR: libFuzzer" in log,
            "tail": log.splitlines()[-12:],
        }
    passed = all(not v["crashed"] and v["done"] for v in out.values())
    data_out = {
        "gate": "P3-T10 (0 crashes)",
        "runs_per_target": runs,
        "targets": out,
        "outcome": "PASS" if passed else "FAIL",
    }
    _record(
        root,
        cmd,
        gate,
        started,
        "p3-fuzz",
        data_out,
        summary={t: v["done"] for t, v in out.items()},
    )
    print(json.dumps({t: v["done"] for t, v in out.items()} | {"outcome": data_out["outcome"]}))
    return 0 if passed else 1


#: Coverage minimums (Build 3-4 §1.9 P3-T9): file prefix → minimum line coverage.
COVERAGE: Final = {
    "crates/sever-crypto/src/": 0.95,
    "crates/sever-commit/src/": 0.90,
    "crates/sever-log/src/": 0.90,
    "crates/sever-cert/src/": 0.90,
}
VERIFIER_COVERAGE: Final = 0.95


def _llvm_cov(cwd: Path, args: list[str]) -> tuple[int, list[dict[str, Any]], str]:
    run = subprocess.run(
        [
            "cargo",
            "+nightly",
            "llvm-cov",
            "--release",
            "-q",
            "--json",
            "--summary-only",
            *args,
            "--",
            "--include-ignored",
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    files = json.loads(run.stdout)["data"][0]["files"] if run.stdout.strip() else []
    return run.returncode, files, run.stderr[-1500:]


def p3_coverage(root: Path) -> int:
    """P3-T9 (coverage): line coverage per crate and of the verifier."""
    cmd = "gates p3-coverage"
    gate = "P3-T9 coverage"
    started = ledger.start(root, cmd, gate=gate)
    rc, files, err = _llvm_cov(root, ["--workspace"])
    rc_v, vfiles, err_v = _llvm_cov(root / VERIFIER, ["--offline"])
    units: dict[str, list[float]] = {k: [0, 0] for k in COVERAGE}
    units[VERIFIER] = [0, 0]
    for base, fs in ((root, files), (root / VERIFIER, vfiles)):
        for f in fs:
            name = f["filename"].split(str(base) + "/", 1)[-1]
            if name.endswith("/tests.rs") or "/tests/" in name or name.endswith("_tests.rs"):
                continue
            unit = (
                VERIFIER
                if base != root and name.startswith("src/")
                else next((k for k in COVERAGE if name.startswith(k)), None)
            )
            if unit is None:
                continue
            units[unit][0] += f["summary"]["lines"]["covered"]
            units[unit][1] += f["summary"]["lines"]["count"]
    rates = {u: c / t if t else 0.0 for u, (c, t) in units.items()}
    mins = {**COVERAGE, VERIFIER: VERIFIER_COVERAGE}
    passed = rc == 0 and rc_v == 0 and all(rates[u] >= mins[u] for u in mins)
    data_out = {
        "gate": "P3-T9: lines >= 95 % (sever-crypto, verifier), >= 90 % (other Part 3 crates)",
        "rates": rates,
        "minimums": mins,
        "tests_ok": [rc == 0, rc_v == 0],
        "stderr_tail": [err, err_v],
        "outcome": "PASS" if passed else "FAIL",
    }
    _record(root, cmd, gate, started, "p3-coverage", data_out, rates=rates)
    print(json.dumps({u: round(r, 4) for u, r in rates.items()} | {"outcome": data_out["outcome"]}))
    return 0 if passed else 1


def p3_checks(root: Path) -> int:
    """``scripts/ci.sh full-checks``: every step PASS (one ledger entry)."""
    cmd = "gates p3-checks"
    gate = "Full-tier checks (P3-T3, P3-T6, P3-T7, P3-T8, P3-T9 sabotage, P3-T11, P3-T12)"
    started = ledger.start(root, cmd, gate=gate)
    t0 = time.time()
    run = subprocess.run(
        ["scripts/ci.sh", "full-checks"], cwd=root, capture_output=True, text=True, check=False
    )
    steps = {
        ln.split(":")[0].removeprefix("STEP "): ln.split(":", 1)[1].strip().split(" ")[0]
        for ln in run.stdout.splitlines()
        if ln.startswith("STEP ")
    }
    passed = run.returncode == 0 and bool(steps) and all(v == "PASS" for v in steps.values())
    data_out = {
        "gate": "scripts/ci.sh full-checks: every step PASS",
        "steps": steps,
        "seconds": round(time.time() - t0),
        "stdout_tail": run.stdout.splitlines()[-40:],
        "outcome": "PASS" if passed else "FAIL",
    }
    _record(root, cmd, gate, started, "p3-checks", data_out, steps=steps)
    print(json.dumps(steps | {"outcome": data_out["outcome"]}))
    return 0 if passed else 1


def p3_spikes(root: Path) -> int:
    """Build 3-4 §1.11: the proof spike passes; its only output is this ledger entry."""
    cmd = "gates p3-spikes"
    gate = "Part 3 proof spike (Build 3-4 §1.11)"
    started = ledger.start(root, cmd, gate=gate)
    run = subprocess.run(
        ["cargo", "test", "--release", "--manifest-path", "spikes/p3-proof/Cargo.toml"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    results = [ln for ln in run.stdout.splitlines() if ln.startswith("test ")]
    passed = run.returncode == 0 and bool(results)
    data_out = {
        "gate": gate,
        "tests": results,
        "outcome": "PASS" if passed else "FAIL",
        "stderr_tail": run.stderr.splitlines()[-15:],
    }
    _record(root, cmd, gate, started, "p3-spikes", data_out, tests=results)
    print(json.dumps([*results, data_out["outcome"]]))
    return 0 if passed else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gates-p3", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    mu = sub.add_parser("p3-mutants")
    mu.add_argument("--jobs", type=int, default=2)
    mu.add_argument("--root", type=Path, default=Path("."))
    for name in ("p3-crash", "p3-replay", "p3-attacks"):
        c = sub.add_parser(name)
        c.add_argument("--data", default="nq-10k")
        c.add_argument("--seed", type=int, action="append")
        c.add_argument("--all-seeds", action="store_true")
        c.add_argument("--jobs", type=int, default=2)
        c.add_argument("--root", type=Path, default=Path("."))
        if name == "p3-replay":
            c.add_argument("--modes", default="plain")
        if name == "p3-attacks":
            c.add_argument("--n", type=int, default=1000)
    me = sub.add_parser("p3-measures")
    me.add_argument("--data", default="nq-10k")
    me.add_argument("--n", type=int, default=200)
    me.add_argument("--root", type=Path, default=Path("."))
    fz = sub.add_parser("p3-fuzz")
    fz.add_argument("--runs", type=int, default=100_000_000)
    fz.add_argument("--root", type=Path, default=Path("."))
    for name in ("p3-coverage", "p3-checks", "p3-spikes"):
        sub.add_parser(name).add_argument("--root", type=Path, default=Path("."))
    args, extra = ap.parse_known_args(argv)
    root = args.root.resolve()
    seeds = (
        list(SEEDS) if getattr(args, "all_seeds", False) else (getattr(args, "seed", None) or [42])
    )
    if args.cmd == "p3-mutants":
        return p3_mutants(root, args.jobs)
    if args.cmd == "p3-crash":
        return p3_crash(root, args.data, seeds, args.jobs, extra)
    if args.cmd == "p3-replay":
        return p3_replay(root, args.data, seeds, args.modes.split(","), args.jobs)
    if args.cmd == "p3-attacks":
        return p3_attacks(root, args.data, seeds, args.n, args.jobs)
    if args.cmd == "p3-measures":
        return p3_measures(root, args.data, args.n)
    if args.cmd == "p3-fuzz":
        return p3_fuzz(root, args.runs)
    if args.cmd == "p3-coverage":
        return p3_coverage(root)
    if args.cmd == "p3-checks":
        return p3_checks(root)
    if args.cmd == "p3-spikes":
        return p3_spikes(root)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
