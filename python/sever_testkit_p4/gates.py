"""Part 4 gate runners that write the run ledger (Build §2.5, §2.8 Full tier; Build 3-4 §2.10).

    PYTHONPATH=python uv run python -m sever_testkit_p4.gates p4-crash --data nq-10k --all-seeds

``p4-crash`` is gate P4-T3 (T-1 on the final build): Part 2's oracle streams through the final
engine (``sever-crashkit-p4 campaign``) with a crash at every VFS operation on either disk, torn
key-file slots, and active-key losses at the end. Per seed: the oracle checks every recovered
state; the kit checks the log, that no stale key slot survives recovery, that every live record
opens, and that every injected loss of an active key makes the engine refuse to start.

``p4-replay`` and ``p4-attacks`` are P4-T9's re-runs of T-3 (Part 1's traces, the five fields and
the certificate arithmetic) and T-4 (honest certificates accepted, every attack rejected by the
separate verifier) on the final build.

``p4-forensics`` is P4-T1 and P4-T2 (overview EX-2, T-2): ``sever_experiments.ex2`` on a raw ext4
image per seed, then the scanner's sensitivity to each sabotage build it applies to.

``p4-checks`` is ``scripts/ci.sh full-checks`` (P4-T4 … P4-T8 as tests, P4-T10's sabotage register
SB-1 … SB-30 and traceability, P4-T11's freeze guard) as one ledger entry. ``p4-coverage`` and
``p4-mutants`` are P4-T10's line coverage (>= 95 %) and mutation score (>= 90 %) on ``sever-keys``,
``sever-seal`` and ``sever-erasure``; ``p4-fuzz`` is its 0 crashes in ``--runs`` executions per
parser.

The measures, recorded as found: ``p4-ex6`` (P4-T12, EX-6), ``p4-quant-recall`` (P4-T13, T-6 at
``nq-1m``), ``p4-ex7`` (P4-T14, EX-7) and ``p4-ex8`` (P4-T15, EX-8).
"""

import argparse
import concurrent.futures
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Final

from sever_refmodel_durable import oracle as durable
from sever_testkit import ledger
from sever_testkit.seeds import SEEDS
from sever_testkit_p3 import gates as p3

KIT: Final = "sever-crashkit-p4"
#: P4-T10: the Part 4 key, sealing and erasure crates, each on its own.
P4_UNITS: Final = ("sever-keys", "sever-seal", "sever-erasure")
COVERAGE_MIN: Final = 0.95
MUTATION_MIN: Final = 0.90
#: Tests run against every mutant: the mutated crates and the crates built on them.
P4_MUTANT_TESTS: Final = ("sever-keys", "sever-seal", "sever-erasure", "sever-db", "sever-scan")
TRIAGE: Final = Path("docs/MUTANTS_P4.md")
FUZZ: Final = tuple(
    ("fuzz-p4", t)
    for t in ("key_slot", "wrapped_value", "bucket_block", "envelope", "scan_targets")
)


def _kit(root: Path, commit: str) -> Path:
    """Builds the Part 4 gate kit (release) into a target directory owned by this run."""
    target = root / f"target/gate-p4-{commit[:12]}"
    subprocess.run(
        ["cargo", "build", "-q", "--release", "-p", KIT, "--target-dir", str(target)],
        cwd=root,
        check=True,
    )
    return target / f"release/{KIT}"


# ---------------------------------------------------------------------------------------------
# P4-T3: the crash campaign with every participant.

#: Summary fields that must be 0 on every seed (P4-T3; the Part 3 log checks included).
ZERO: Final = (
    "orphaned_leaves",
    "rolled_back_certificates",
    "bad_certificates",
    "main_mismatches",
    "skipped",
    "method_mismatches",
    "refusals",
    "stale_key_slots",
    "unreadable_records",
    "reopen_mismatches",
)


def crash_ok(summary: dict[str, Any], verdict: dict[str, Any], rc: int) -> bool:
    """One seed's P4-T3 verdict."""
    return (
        rc == 0
        and verdict.get("failures") == 0
        and verdict.get("crash_points", 0) > 0
        and all(summary.get(k) == 0 for k in ZERO)
        and summary.get("certificates_checked", 0) > 0
        and summary.get("compared", 0) > 0
        and summary.get("keytear", 0) > 0
        and summary.get("key_loss_injected", 0) > 0
        and summary.get("key_loss_refused") == summary.get("key_loss_injected")
    )


def _crash_seed(root: Path, data: str, seed: int, kit: Path, extra: list[str]) -> dict[str, Any]:
    t0 = time.time()
    oracle_path = root / f"traces/p2-oracle-{data}-seed{seed}.jsonl"
    if not oracle_path.exists():
        durable._main(["write", "--data", data, "--seed", str(seed), "--root", str(root)])
    out = root / f"traces/p4-crash-{data}-seed{seed}.jsonl"
    progress = Path(str(out) + ".progress")
    run: Any = argparse.Namespace(returncode=0, stderr="")
    if p3._finished(out):
        how = "already finished"
    else:
        cont = ["--resume", "1"] if progress.exists() else []
        how = "resumed" if cont else "fresh"
        run = p3._campaign(root, kit, oracle_path, out, seed, [*extra, *cont])
    summary = json.loads(out.read_text().splitlines()[-1]) if out.exists() else {}
    v = durable.check(oracle_path, out) if out.exists() else None
    verdict = {**v.__dict__, "failures": v.failures()} if v else {}
    ok = crash_ok(summary, verdict, run.returncode)
    print(json.dumps({"seed": seed, "outcome": "PASS" if ok else "FAIL"}), flush=True)
    return {
        "seed": seed,
        "outcome": "PASS" if ok else "FAIL",
        "summary": summary,
        "verdict": verdict,
        "rc": run.returncode,
        "run": how,
        "stderr_tail": run.stderr[-2000:],
        "oracle_sha256": hashlib.sha256(oracle_path.read_bytes()).hexdigest(),
        "results_sha256": hashlib.sha256(out.read_bytes()).hexdigest() if out.exists() else None,
        "seconds": round(time.time() - t0),
    }


def p4_crash(root: Path, data: str, seeds: list[int], jobs: int, extra: list[str]) -> int:
    """P4-T3. A seed whose results file is complete is kept; an interrupted one continues from
    its saved progress (identical results, DB-88). Delete ``traces/p4-crash-*`` to start over."""
    cmd = f"gates p4-crash --data {data} --seeds {seeds} {' '.join(extra)}".strip()
    gate = "P4-T3"
    started = ledger.start(root, cmd, gate=gate, data=data, seeds=seeds)
    kit = _kit(root, started["commit"])
    # A Part 4 run holds both disks' snapshots (2 to 3.5 GB at nq-10k): size --jobs to memory.
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        per_seed = list(
            pool.map(_crash_seed, *zip(*[(root, data, s, kit, extra) for s in seeds], strict=False))
        )
    passed = all(r["outcome"] == "PASS" for r in per_seed)
    data_out = {
        "gate": "P4-T3: 0 exactness violations, 0 lost acknowledged operations, 0 undecryptable "
        "live records, 0 stale key slots after recovery; 100 % of active-key losses refused",
        "data": data,
        "seeds": per_seed,
        "outcome": "PASS" if passed else "FAIL",
    }
    p3._record(
        root,
        cmd,
        gate,
        started,
        f"p4-crash-{data}",
        data_out,
        data=data,
        seeds=seeds,
        summary={str(r["seed"]): r["outcome"] for r in per_seed},
    )
    return 0 if passed else 1


# ---------------------------------------------------------------------------------------------
# P4-T9: T-3 and T-4 on the final build.


def _replay_one(root: Path, kit: Path, data: str, seed: int) -> dict[str, Any]:
    trace = root / f"traces/p1-{data}-seed{seed}.jsonl"
    out = root / f"traces/p4-replay-{data}-seed{seed}.json"
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
            "plain",
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
    print(json.dumps({"seed": seed, "outcome": "PASS" if ok else "FAIL"}), flush=True)
    return {
        "seed": seed,
        "outcome": "PASS" if ok else "FAIL",
        "report": rep,
        "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
        "stderr_tail": run.stderr[-1500:],
        "seconds": round(time.time() - t0),
    }


def p4_replay(root: Path, data: str, seeds: list[int], jobs: int) -> int:
    """P4-T9 (T-3 on the final build): Part 1's traces, five fields and certificates."""
    cmd = f"gates p4-replay --data {data} --seeds {seeds}"
    gate = "P4-T9 (T-3)"
    started = ledger.start(root, cmd, gate=gate, data=data, seeds=seeds)
    kit = _kit(root, started["commit"])
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        runs = list(
            pool.map(_replay_one, *zip(*[(root, kit, data, s) for s in seeds], strict=False))
        )
    passed = all(r["outcome"] == "PASS" for r in runs)
    data_out = {
        "gate": "P4-T9: 0 mismatches on the five-field equivalence and the certificate "
        "arithmetic against the model, on the final build (T-3)",
        "data": data,
        "runs": runs,
        "outcome": "PASS" if passed else "FAIL",
    }
    p3._record(
        root,
        cmd,
        gate,
        started,
        f"p4-replay-{data}",
        data_out,
        data=data,
        seeds=seeds,
        summary={str(r["seed"]): r["outcome"] for r in runs},
    )
    return 0 if passed else 1


def p4_attacks(root: Path, data: str, seeds: list[int], n: int, jobs: int) -> int:
    """P4-T9 (T-4 on the final build): honest certificates accepted, every attack rejected."""
    cmd = f"gates p4-attacks --data {data} --seeds {seeds} --n {n}"
    gate = "P4-T9 (T-4)"
    started = ledger.start(root, cmd, gate=gate, data=data, seeds=seeds, n=n)
    kit = _kit(root, started["commit"])
    verifier = p3._verifier(root)
    steps = p3.register_steps(root)

    def one(seed: int) -> dict[str, Any]:
        batch = root / f"traces/p4-attacks-{data}-seed{seed}.jsonl"
        out = root / f"traces/p4-attacks-{data}-seed{seed}.verdicts.jsonl"
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
        ok_run = gen.returncode == 0 and ver.returncode == 0
        j = p3.judge(out, steps) if ok_run else {"ok": False}
        print(json.dumps({"seed": seed, "outcome": "PASS" if j["ok"] else "FAIL"}), flush=True)
        return {
            "seed": seed,
            "outcome": "PASS" if j["ok"] else "FAIL",
            "judged": j,
            "generator": gen.stderr[-500:],
            "verifier_rc": ver.returncode,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        per_seed = list(pool.map(one, seeds))
    passed = all(r["outcome"] == "PASS" for r in per_seed)
    data_out = {
        "gate": "P4-T9: 100 % of honest certificates accepted and 100 % of AT-1 … AT-20 "
        "rejected by the independent verifier, on the final build (T-4)",
        "data": data,
        "n": n,
        "seeds": per_seed,
        "outcome": "PASS" if passed else "FAIL",
    }
    p3._record(
        root,
        cmd,
        gate,
        started,
        f"p4-attacks-{data}",
        data_out,
        data=data,
        seeds=seeds,
        summary={str(r["seed"]): r["outcome"] for r in per_seed},
    )
    return 0 if passed else 1


# ---------------------------------------------------------------------------------------------
# P4-T1, P4-T2: forensics.


def p4_forensics(
    root: Path, data: str, seeds: list[int], image_gib: int, unsafe_memory: bool
) -> int:
    """P4-T1 (0 findings, every seed and rung) and P4-T2 (100 % of controls recovered; each
    applicable sabotage build gives a finding)."""
    from sever_experiments import ex2

    cmd = f"gates p4-forensics --data {data} --seeds {seeds} --image-gib {image_gib}"
    gate = "P4-T1, P4-T2"
    started = ledger.start(root, cmd, gate=gate, data=data, seeds=seeds)
    driver, scanner = ex2.build(root)
    per_seed = [
        ex2.run_seed(root, data, s, driver, scanner, image_gib, 5, unsafe_memory) for s in seeds
    ]
    sens = ex2.sensitivity(root, unsafe_memory=unsafe_memory)
    controls = all(all(sc["planted_found"].values()) for r in per_seed for sc in r["scans"])
    t1 = all(r["ok"] for r in per_seed)
    passed = t1 and controls and sens["ok"]
    data_out = {
        "gate": "P4-T1: 0 findings on the raw image after the ingest and every rung, every seed; "
        "P4-T2: 100 % of planted secrets found before every scan, each applicable sabotage build "
        ">= 1 finding",
        "data": data,
        "seeds": per_seed,
        "sensitivity": sens,
        "outcome": "PASS" if passed else "FAIL",
    }
    p3._record(
        root,
        cmd,
        gate,
        started,
        f"p4-forensics-{data}",
        data_out,
        data=data,
        seeds=seeds,
        overrides=per_seed[0]["overrides"] if per_seed else [],
        summary={"T1": t1, "controls": controls, "sensitivity": sens["ok"]},
    )
    print(json.dumps({"T1": t1, "controls": controls, "sensitivity": sens["ok"]}))
    return 0 if passed else 1


# ---------------------------------------------------------------------------------------------
# P4-T10: coverage, mutants, fuzz; P4-T4 … T8, T10 (register), T11: the full checks.


def p4_coverage(root: Path) -> int:
    """P4-T10 (coverage): lines >= 95 % on each of the three Part 4 crates."""
    cmd = "gates p4-coverage"
    gate = "P4-T10 coverage"
    started = ledger.start(root, cmd, gate=gate)
    args = ["--workspace"]
    rc, files, err = p3._llvm_cov(root, args)
    units = {u: [0, 0] for u in P4_UNITS}
    for f in files:
        name = f["filename"].split(str(root) + "/", 1)[-1]
        if name.endswith("/tests.rs") or "/tests/" in name or name.endswith("_tests.rs"):
            continue
        u = next((u for u in P4_UNITS if name.startswith(f"crates/{u}/src/")), None)
        if u:
            units[u][0] += f["summary"]["lines"]["covered"]
            units[u][1] += f["summary"]["lines"]["count"]
    rates = {u: c / t if t else 0.0 for u, (c, t) in units.items()}
    passed = rc == 0 and all(r >= COVERAGE_MIN for r in rates.values())
    data_out = {
        "gate": "P4-T10: lines >= 95 % on sever-keys, sever-seal and sever-erasure",
        "rates": rates,
        "minimum": COVERAGE_MIN,
        "tests_ok": rc == 0,
        "stderr_tail": err,
        "outcome": "PASS" if passed else "FAIL",
    }
    p3._record(root, cmd, gate, started, "p4-coverage", data_out, rates=rates)
    print(json.dumps({u: round(r, 4) for u, r in rates.items()} | {"outcome": data_out["outcome"]}))
    return 0 if passed else 1


def p4_mutants(root: Path, jobs: int) -> int:
    """P4-T10 (mutants): >= 90 % on each Part 4 crate; every survivor triaged."""
    cmd = f"gates p4-mutants --jobs {jobs}"
    gate = "P4-T10 mutants"
    started = ledger.start(
        root, cmd, gate=gate, mutated=list(P4_UNITS), tests=list(P4_MUTANT_TESTS)
    )
    tree = Path.home() / f".cache/sever-mutants-p4-{started['commit'][:12]}"
    tmp = Path.home() / ".cache/mutants-tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    git = ["git", "worktree"]
    subprocess.run(
        [*git, "remove", "--force", str(tree)], cwd=root, check=False, capture_output=True
    )
    subprocess.run([*git, "add", "--detach", str(tree), started["commit"]], cwd=root, check=True)
    try:
        args = ["-j", str(jobs)]
        for p in P4_UNITS:
            args += ["-p", p]
        for p in P4_MUTANT_TESTS:
            args += ["--test-package", p]
        rc, out = p3._mutants(tree, root / "traces/mutants-p4-gate", args, tmp)
    finally:
        subprocess.run(
            [*git, "remove", "--force", str(tree)], cwd=root, check=False, capture_output=True
        )
    scores = p3.score(out, dict.fromkeys(P4_UNITS, MUTATION_MIN))
    missed = p3.survivors(out)
    triage = (root / TRIAGE).read_text(encoding="utf-8") if (root / TRIAGE).exists() else ""
    left = p3.untriaged(missed, triage)
    passed = all(s.ok for s in scores) and not left
    data_out = {
        "gate": "P4-T10: mutation score >= 90 % on sever-keys, sever-seal and sever-erasure; "
        "every survivor triaged",
        "scores": {
            s.unit: {
                "score": s.score,
                "caught": s.caught,
                "missed": s.missed,
                "timeout": s.timeout,
                "unviable": s.unviable,
            }
            for s in scores
        },
        "missed": missed,
        "untriaged": left,
        "cargo_mutants_exit": rc,
        "outcome": "PASS" if passed else "FAIL",
    }
    p3._record(
        root,
        cmd,
        gate,
        started,
        "p4-mutants",
        data_out,
        scores={s.unit: s.score for s in scores},
        untriaged=len(left),
    )
    print(
        json.dumps(
            {s.unit: round(s.score, 4) for s in scores}
            | {"untriaged": len(left), "outcome": data_out["outcome"]}
        )
    )
    return 0 if passed else 1


def p4_fuzz(root: Path, runs: int) -> int:
    """P4-T10 (fuzz): ``runs`` executions per Part 4 parser, 0 crashes."""
    cmd = f"gates p4-fuzz --runs {runs}"
    gate = "P4-T10 fuzz"
    started = ledger.start(root, cmd, gate=gate, runs=runs, targets=[t for _, t in FUZZ])
    procs = {}
    for d, t in FUZZ:
        corpus = root / d / "corpus" / t
        corpus.mkdir(parents=True, exist_ok=True)
        procs[t] = subprocess.Popen(
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
        "gate": "P4-T10 (0 crashes)",
        "runs_per_target": runs,
        "targets": out,
        "outcome": "PASS" if passed else "FAIL",
    }
    p3._record(
        root,
        cmd,
        gate,
        started,
        "p4-fuzz",
        data_out,
        summary={t: v["done"] for t, v in out.items()},
    )
    print(json.dumps({t: v["done"] for t, v in out.items()} | {"outcome": data_out["outcome"]}))
    return 0 if passed else 1


def p4_checks(root: Path) -> int:
    """``scripts/ci.sh full-checks``: every step PASS (one ledger entry)."""
    cmd = "gates p4-checks"
    gate = "Full-tier checks (P4-T4 … P4-T8, P4-T10 sabotage and traceability, P4-T11)"
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
    p3._record(root, cmd, gate, started, "p4-checks", data_out, steps=steps)
    print(json.dumps(steps | {"outcome": data_out["outcome"]}))
    return 0 if passed else 1


# ---------------------------------------------------------------------------------------------
# Measures (P4-T12 … P4-T15): recorded as found, never a reason to change code or rerun.


def _measure(root: Path, cmd: str, label: str, name: str, found: dict[str, Any]) -> int:
    started = ledger.start(root, cmd, measure=label)
    data_out = {"measure": label, "found": found, "outcome": "RECORDED"}
    p3._record(root, cmd, label, started, name, data_out)
    print(json.dumps({"measure": label, "outcome": "RECORDED"}))
    return 0


def p4_ex6(root: Path, data: str, seeds: list[int], unsafe_memory: bool, sweep: bool) -> int:
    """P4-T12 (overview EX-6, T-5): the four arms across the rungs, and the statistics."""
    from sever_experiments import ex6

    per_seed = [ex6.run_seed(root, data, s, unsafe_memory, with_sweep=sweep) for s in seeds]
    found = {"data": data, "seeds": per_seed, "statistics": ex6.statistics(per_seed)}
    return _measure(
        root,
        f"gates p4-ex6 --data {data} --seeds {seeds}",
        "P4-T12 (T-5, pre-registered drift <= 0.005 per seed)",
        f"p4-ex6-{data}",
        found,
    )


def p4_ex7(root: Path, data: str, seeds: list[int], rungs: int) -> int:
    """P4-T14 (overview EX-7): the three builds, five rungs, every seed."""
    from sever_experiments import ex7

    bins = ex7.build(root)
    results = [ex7.run_one(root, bins, arm, data, s, rungs) for s in seeds for arm in ex7.ARMS]
    for s in seeds:
        shutil.rmtree(root / "target" / f"ex7-work-{data}-seed{s}", ignore_errors=True)
    found = {"data": data, "results": results, "summary": ex7.summary(results)}
    return _measure(
        root,
        f"gates p4-ex7 --data {data} --seeds {seeds}",
        "P4-T14 (EX-7)",
        f"p4-ex7-{data}",
        found,
    )


def p4_ex8(root: Path, seeds: list[int]) -> int:
    """P4-T15 (overview EX-8): load nq-1m into the measured engine, then restart."""
    from sever_experiments import ex7

    bins = ex7.build(root)
    results = [ex7.run_one(root, bins, "sever", "nq-1m", s, 0) for s in seeds]
    for s in seeds:
        shutil.rmtree(root / "target" / f"ex7-work-nq-1m-seed{s}", ignore_errors=True)
    found = {
        "results": results,
        "predicted_resident_bytes": 3.8e9,
        "note": "Appendix A budget; reopen_seconds is the recovery time",
    }
    return _measure(root, f"gates p4-ex8 --seeds {seeds}", "P4-T15 (EX-8)", "p4-ex8", found)


def p4_quant_recall(root: Path) -> int:
    """P4-T13 (T-6, second size): Part 1's P1-T7 measure, unchanged, at nq-1m."""
    from sever_testkit import gates as p1

    return p1.p1_quant_recall(root, "nq-1m")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gates-p4", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("p4-crash", "p4-replay", "p4-attacks", "p4-forensics"):
        c = sub.add_parser(name)
        c.add_argument(
            "--data", default="nq-100k" if name in ("p4-replay", "p4-forensics") else "nq-10k"
        )
        c.add_argument("--seed", type=int, action="append")
        c.add_argument("--all-seeds", action="store_true")
        c.add_argument("--jobs", type=int, default=2)
        c.add_argument("--root", type=Path, default=Path("."))
        if name == "p4-attacks":
            c.add_argument("--n", type=int, default=1000)
        if name == "p4-forensics":
            c.add_argument("--image-gib", type=int, default=16)
            c.add_argument(
                "--locked-memory",
                action="store_true",
                help="the machine allows mlockall (ulimit -l unlimited): no allow_unsafe_memory",
            )
    mu = sub.add_parser("p4-mutants")
    mu.add_argument("--jobs", type=int, default=2)
    mu.add_argument("--root", type=Path, default=Path("."))
    fz = sub.add_parser("p4-fuzz")
    fz.add_argument("--runs", type=int, default=100_000_000)
    fz.add_argument("--root", type=Path, default=Path("."))
    for name in ("p4-coverage", "p4-checks", "p4-quant-recall"):
        sub.add_parser(name).add_argument("--root", type=Path, default=Path("."))
    for name in ("p4-ex6", "p4-ex7", "p4-ex8"):
        c = sub.add_parser(name)
        c.add_argument("--data", default="nq-100k")
        c.add_argument("--seed", type=int, action="append")
        c.add_argument("--all-seeds", action="store_true")
        c.add_argument("--root", type=Path, default=Path("."))
        c.add_argument("--rungs", type=int, default=5)
        c.add_argument("--no-sweep", action="store_true")
        c.add_argument("--locked-memory", action="store_true")
    args, extra = ap.parse_known_args(argv)
    root = args.root.resolve()
    seeds = (
        list(SEEDS) if getattr(args, "all_seeds", False) else (getattr(args, "seed", None) or [42])
    )
    if args.cmd == "p4-crash":
        return p4_crash(root, args.data, seeds, args.jobs, extra)
    if args.cmd == "p4-replay":
        return p4_replay(root, args.data, seeds, args.jobs)
    if args.cmd == "p4-attacks":
        return p4_attacks(root, args.data, seeds, args.n, args.jobs)
    if args.cmd == "p4-forensics":
        return p4_forensics(root, args.data, seeds, args.image_gib, not args.locked_memory)
    if args.cmd == "p4-mutants":
        return p4_mutants(root, args.jobs)
    if args.cmd == "p4-fuzz":
        return p4_fuzz(root, args.runs)
    if args.cmd == "p4-coverage":
        return p4_coverage(root)
    if args.cmd == "p4-checks":
        return p4_checks(root)
    if args.cmd == "p4-quant-recall":
        return p4_quant_recall(root)
    if args.cmd == "p4-ex6":
        return p4_ex6(root, args.data, seeds, not args.locked_memory, not args.no_sweep)
    if args.cmd == "p4-ex7":
        return p4_ex7(root, args.data, seeds, args.rungs)
    if args.cmd == "p4-ex8":
        return p4_ex8(root, seeds)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
