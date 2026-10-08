"""Part 2 gate runners that write the run ledger (Build §2.5, §2.8 Full tier, §5.8).

    PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_testkit_p2.gates p2-crash \\
        --data nq-10k --all-seeds --jobs 3
    PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_testkit_p2.gates p2-fuzz \\
        --runs 100000000

``p2-crash`` is gates P2-T1 (0 exactness violations, 0 lost acknowledged operations, 0 corrupt
recoveries, 0 startup refusals after an honest crash), P2-T2 (100 % of recovered states equal an
oracle-allowed state byte for byte) and P2-T3 (0 partial ``delete_user``), on five seeds. Per seed:
the durable oracle writes the stream and its state digests (``sever_refmodel_durable``); the crash
kit runs the generic-records campaign first (overview EX-1 step 1), then the index campaign: a crash
at every VFS operation of all 20,000 operations, every 512-byte offset of 200 sampled WAL writes,
1,000 random points, and a crash during recovery every 50th point; then the oracle checks every
recovered state. The crash kit is built once into a target directory owned by this run.

``p2-fuzz`` is gate P2-T6: each Part 2 parser (WAL record, MANIFEST, checkpoint file, store record)
runs ``--runs`` libFuzzer executions, all at once, with 0 crashes.

``p2-replay`` is gate P2-T5 (Build §5.7 L4, F-5): Part 1's frozen traces (written by the reference
model from the spec) replay through the Part 2 engine in three modes, ``plain``, ``close`` (a clean
close and reopen after every rung) and ``crash`` (a crash and recovery after every rung), with 0
mismatches against the trace, and an unchanged state across every reopen.

``p2-sabotage`` is gate P2-T8 (Build §2.6, L12): ``tests/sabotage/run.sh``, every SB item of
Parts 1 and 2 turns at least one test red.

``p2-measures`` is measure P2-T11 (descriptive, Build §2.5: recorded as found, never rerun to pass):
bytes written and fsyncs per operation, recovery time and resident memory, on real files, running
the operations of the ``nq-100k`` Part 1 trace for seed 42.

``p2-coverage`` and ``p2-mutants`` are gate P2-T9 on ``sever-format``, ``sever-wal``, ``sever-txn``
and ``sever-engine``: lines >= 90 %, branches >= 85 % (whole-workspace tests, ignored included);
mutation score >= 85 % with every survivor triaged in ``docs/MUTANTS_P2.md``.

``p2-checks`` is ``scripts/ci.sh full-checks`` (fast tier, ignored tests, slow Python tests with
the E2E-2.x suite, sabotage, MSRV, cargo deny, docs) and the freeze guard, which is gate P2-T10
(the Part 1 freeze manifest is unchanged): one ledger entry with every step's outcome.

``p2-spikes`` is the proof-spike part of gate P2-T7 (Build §3.4): the throwaway crate
``spikes/p2-proof`` passes; its only output is the ledger entry, then it is deleted.
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from sever_refmodel_durable import oracle as durable
from sever_testkit import ledger
from sever_testkit.seeds import SEEDS


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _build(root: Path, run_commit: str, package: str) -> Path:
    """Builds ``package`` (release) into a target directory owned by this run, so a build made while
    the run is going cannot change the binary that runs the later seeds."""
    target = root / f"target/gate-{run_commit[:12]}"
    subprocess.run(
        ["cargo", "build", "-q", "--release", "-p", package, "--target-dir", str(target)],
        cwd=root,
        check=True,
    )
    return target / "release"


def _finished(path: Path) -> bool:
    """True when a results file ends with its summary line (the run wrote everything)."""
    if not path.exists() or not path.stat().st_size:
        return False
    last = path.read_bytes().rstrip(b"\n").rsplit(b"\n", 1)[-1]
    try:
        return bool(json.loads(last).get("t") == "summary")
    except ValueError:
        return False


def _crash_seed(
    root: Path, data: str, seed: int, bin_dir: Path, extra: list[str], resume: bool = False
) -> dict[str, Any]:
    t0 = time.time()
    out_dir = root / "traces"
    oracle_path = out_dir / f"p2-oracle-{data}-seed{seed}.jsonl"
    if not (resume and oracle_path.exists()):  # the oracle is deterministic: same file again
        durable._main(["write", "--data", data, "--seed", str(seed), "--root", str(root)])
    crashkit = bin_dir / "sever-crashkit"
    generic_out = out_dir / f"p2-generic-seed{seed}.jsonl"
    gen: Any = argparse.Namespace(returncode=0, stderr="")
    if not (resume and _finished(generic_out)):
        gen = subprocess.run(
            [str(crashkit), "generic", "--seed", str(seed), "--steps", "2000", "--out",
             str(generic_out)],
            cwd=root, capture_output=True, text=True, check=False,
        )  # fmt: skip
    campaign_out = out_dir / f"p2-crash-{data}-seed{seed}.jsonl"
    progress = Path(str(campaign_out) + ".progress")
    how = "fresh"
    camp: Any = argparse.Namespace(returncode=0, stderr="")
    if resume and _finished(campaign_out):
        how = "already finished"
    else:
        cont = ["--resume", "1"] if resume and progress.exists() else []
        how = "resumed" if cont else "fresh"
        if not cont:
            progress.unlink(missing_ok=True)
        camp = subprocess.run(
            [str(crashkit), "campaign", "--oracle", str(oracle_path), "--root", str(root),
             "--out", str(campaign_out), "--seed", str(seed), *extra, *cont],
            cwd=root, capture_output=True, text=True, check=False,
        )  # fmt: skip
    generic = json.loads(generic_out.read_text().splitlines()[-1]) if generic_out.exists() else {}
    summary_line: dict[str, Any] = {}
    verdict: dict[str, Any] = {}
    if campaign_out.exists() and campaign_out.stat().st_size:
        summary_line = json.loads(campaign_out.read_text().splitlines()[-1])
        v = durable.check(oracle_path, campaign_out)
        verdict = {**v.__dict__, "failures": v.failures()}
    passed = (
        gen.returncode == 0
        and camp.returncode == 0
        and verdict.get("failures") == 0
        and verdict.get("crash_points", 0) > 0
        and summary_line.get("main_mismatches") == 0
        and summary_line.get("skipped") == 0
    )
    result = {
        "seed": seed,
        "outcome": "PASS" if passed else "FAIL",
        "oracle_sha256": _sha(oracle_path),
        "generic": generic,
        "generic_rc": gen.returncode,
        "campaign": summary_line,
        "campaign_rc": camp.returncode,
        "campaign_run": how,
        "campaign_stderr": camp.stderr[-2000:],
        "campaign_results_sha256": _sha(campaign_out) if campaign_out.exists() else None,
        "verdict": verdict,
        "seconds": round(time.time() - t0),
    }
    print(json.dumps(result), flush=True)
    return result


CODE_PATHS = ("crates", "python", "Cargo.toml", "Cargo.lock")


def _same_code(root: Path, commit: str) -> bool:
    """True when the code a run depends on is exactly `commit`'s (committed and in the tree)."""
    diff = subprocess.run(["git", "diff", "--quiet", commit, "--", *CODE_PATHS], cwd=root,
                          check=False).returncode  # fmt: skip
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", *CODE_PATHS],
        cwd=root, capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    return diff == 0 and not untracked


def p2_crash(
    root: Path, data: str, seeds: list[int], jobs: int, extra: list[str], resume: bool = False
) -> int:
    """P2-T1…T3. With ``resume``, continues the interrupted run named by the run-state file:
    only if the code equals that run's commit; finished seeds are kept, interrupted campaigns
    continue from their saved progress (results identical to an uninterrupted run), and the
    ledger gets a new "started" line naming the run it resumes."""
    cmd = f"gates p2-crash --data {data} --seeds {seeds} {' '.join(extra)}".strip()
    artefacts = {s: _sha(root / f"artefacts/partition-seed{s}.svp") for s in seeds}
    gate = "P2-T1, P2-T2, P2-T3"
    state_path = root / f"traces/p2-crash-{data}-run.json"
    if resume:
        st = json.loads(state_path.read_text(encoding="utf-8"))
        if (st["seeds"], st["extra"]) != (seeds, extra):
            raise SystemExit("--resume: seeds or settings differ from the interrupted run")
        run_commit = st["run_commit"]
        if not _same_code(root, run_commit):
            raise SystemExit(f"--resume: the code differs from {run_commit[:12]}; start afresh")
        ledger.start(
            root,
            cmd + " --resume",
            gate=gate,
            data=data,
            seeds=seeds,
            artefacts=artefacts,
            resume_of=st["started_utc"],
            run_commit=run_commit,
        )
        bin_dir = _build(root, run_commit, "sever-crashkit")
    else:
        started = ledger.start(root, cmd, gate=gate, data=data, seeds=seeds, artefacts=artefacts)
        run_commit = started["commit"]
        bin_dir = _build(root, run_commit, "sever-crashkit")
        state_path.write_text(json.dumps({"run_commit": run_commit, "seeds": seeds,
                                          "extra": extra, "started_utc": started["utc"]}),
                              encoding="utf-8")  # fmt: skip
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        futs = [pool.submit(_crash_seed, root, data, s, bin_dir, extra, resume) for s in seeds]
        per_seed = [f.result() for f in futs]
    passed = all(s["outcome"] == "PASS" for s in per_seed)
    data_out = {
        "gate": "P2-T1 (0 exactness violations, 0 lost acknowledged operations, 0 corrupt "
        "recoveries, 0 refusals), P2-T2 (100 % oracle-allowed states), P2-T3 (0 partial "
        "delete_user)",
        "data": data,
        "seeds": per_seed,
        "outcome": "PASS" if passed else "FAIL",
    }
    path, sha = ledger.result_file(
        root, f"p2-crash-{data}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", data_out
    )
    ledger.append(
        root,
        ledger.entry(
            root,
            cmd,
            gate=gate,
            data=data,
            seeds=seeds,
            artefacts=artefacts,
            outcome=data_out["outcome"],
            run_commit=run_commit,
            result_file=str(path.relative_to(root)),
            result_sha256=sha,
            summary={str(s["seed"]): s["verdict"] for s in per_seed},
        ),
    )
    return 0 if passed else 1


REPLAY_MODES = ("plain", "close", "crash")


def _replay_one(root: Path, bin_dir: Path, data: str, seed: int, mode: str) -> dict[str, Any]:
    t0 = time.time()
    trace = root / f"traces/p1-{data}-seed{seed}.jsonl"
    out = root / f"traces/p2-replay-{data}-seed{seed}-{mode}.jsonl"
    run = subprocess.run(
        [str(bin_dir / "sever-crashkit"), "replay-p1", "--trace", str(trace), "--root",
         str(root), "--mode", mode, "--out", str(out)],
        cwd=root, capture_output=True, text=True, check=False,
    )  # fmt: skip
    summary = json.loads(out.read_text().splitlines()[-1]) if out.exists() else {}
    result = {
        "seed": seed,
        "mode": mode,
        "trace_sha256": _sha(trace),
        "rc": run.returncode,
        "summary": summary,
        "stderr_tail": run.stderr.splitlines()[-5:],
        "seconds": round(time.time() - t0),
        "outcome": "PASS" if run.returncode == 0 and summary.get("passed") is True else "FAIL",
    }
    print(json.dumps(result), flush=True)
    return result


def p2_replay(root: Path, data: str, seeds: list[int], jobs: int) -> int:
    """P2-T5: every Part 1 trace of ``data`` through the Part 2 engine, in every mode."""
    cmd = f"gates p2-replay --data {data} --seeds {seeds}"
    gate = "P2-T5"
    started = ledger.start(root, cmd, gate=gate, data=data, seeds=seeds, modes=list(REPLAY_MODES))
    bin_dir = _build(root, started["commit"], "sever-crashkit")
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        futs = [
            pool.submit(_replay_one, root, bin_dir, data, s, m) for s in seeds for m in REPLAY_MODES
        ]
        runs = [f.result() for f in futs]
    passed = all(r["outcome"] == "PASS" for r in runs)
    data_out = {"gate": "P2-T5 (Part 1 traces through the Part 2 engine, with and without "
                "restarts: 0 mismatches, 0 state changes across a reopen)", "data": data,
                "runs": runs, "outcome": "PASS" if passed else "FAIL"}  # fmt: skip
    path, sha = ledger.result_file(
        root, f"p2-replay-{data}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", data_out
    )
    ledger.append(
        root,
        ledger.entry(
            root,
            cmd,
            gate=gate,
            data=data,
            seeds=seeds,
            outcome=data_out["outcome"],
            run_commit=started["commit"],
            result_file=str(path.relative_to(root)),
            result_sha256=sha,
            summary={f"{r['seed']}-{r['mode']}": r["outcome"] for r in runs},
        ),
    )
    return 0 if passed else 1


def p2_sabotage(root: Path) -> int:
    """P2-T8: every sabotage build (SB-1 … SB-15) makes a test fail."""
    cmd = "gates p2-sabotage"
    gate = "P2-T8 (and F-5: P1-T8 re-run)"
    started = ledger.start(root, cmd, gate=gate)
    t0 = time.time()
    run = subprocess.run(
        ["bash", "tests/sabotage/run.sh"], cwd=root, capture_output=True, text=True, check=False
    )
    lines = [
        ln for ln in run.stdout.splitlines() if ln.split(" ", 1)[0] in ("PASS", "FAIL", "ERROR")
    ]
    ids = {ln.split()[1] for ln in lines}
    want = {f"SB-{i}" for i in range(1, 16)}
    passed = run.returncode == 0 and all(ln.startswith("PASS") for ln in lines) and want <= ids
    data_out = {"gate": "P2-T8: every SB item makes a test fail", "lines": lines,
                "missing": sorted(want - ids), "seconds": round(time.time() - t0),
                "outcome": "PASS" if passed else "FAIL",
                "stderr_tail": run.stderr.splitlines()[-10:]}  # fmt: skip
    path, sha = ledger.result_file(
        root, f"p2-sabotage-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", data_out
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
            summary=lines,
        ),
    )
    print(json.dumps([*lines, data_out["outcome"]]))
    return 0 if passed else 1


def p2_measures(root: Path, data: str, seed: int) -> int:
    """P2-T11: a measure. The run is recorded whatever it finds."""
    cmd = f"gates p2-measures --data {data} --seed {seed}"
    gate = "P2-T11 (measure)"
    started = ledger.start(root, cmd, gate=gate, data=data, seeds=[seed])
    bin_dir = _build(root, started["commit"], "sever-crashkit")
    trace = root / f"traces/p1-{data}-seed{seed}.jsonl"
    out = root / f"traces/p2-measures-{data}-seed{seed}.jsonl"
    run = subprocess.run(
        [str(bin_dir / "sever-crashkit"), "measure", "--trace", str(trace), "--root", str(root),
         "--out", str(out), "--work", str(root / "target/measure-p2")],
        cwd=root, capture_output=True, text=True, check=False,
    )  # fmt: skip
    found = json.loads(out.read_text().splitlines()[-1]) if out.exists() else {}
    data_out = {"measure": "P2-T11", "data": data, "seed": seed,
                "trace_sha256": _sha(trace), "rc": run.returncode, "found": found,
                "stderr_tail": run.stderr.splitlines()[-10:],
                "outcome": "RECORDED" if run.returncode == 0 else "ERROR"}  # fmt: skip
    path, sha = ledger.result_file(
        root, f"p2-measures-{data}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", data_out
    )
    ledger.append(
        root,
        ledger.entry(
            root,
            cmd,
            gate=gate,
            data=data,
            seeds=[seed],
            outcome=data_out["outcome"],
            run_commit=started["commit"],
            result_file=str(path.relative_to(root)),
            result_sha256=sha,
        ),
    )
    print(json.dumps(data_out))
    return 0 if run.returncode == 0 else 1


P2_CRATES = ("crates/sever-format/src/", "crates/sever-wal/src/", "crates/sever-txn/src/",
             "crates/sever-engine/src/")  # fmt: skip
P2_MUTATED = ("sever-format", "sever-wal", "sever-txn", "sever-engine")
P2_MUTANT_TESTS = (*P2_MUTATED, "sever-checkpoint", "sever-appendstore")


def p2_coverage(root: Path) -> int:
    """P2-T9 (coverage): lines >= 90 %, branches >= 85 % over the four crates."""
    cmd = "gates p2-coverage"
    gate = "P2-T9 coverage"
    started = ledger.start(root, cmd, gate=gate)
    rust = subprocess.run(
        ["cargo", "+nightly", "llvm-cov", "--branch", "--release", "-q", "--workspace", "--json",
         "--summary-only", "--", "--include-ignored"],
        cwd=root, capture_output=True, text=True, check=False,
    )  # fmt: skip
    files = json.loads(rust.stdout)["data"][0]["files"] if rust.stdout else []
    lines, branches, per_file = [0, 0], [0, 0], {}
    for f in files:
        name = f["filename"].split(str(root) + "/", 1)[-1]
        if not name.startswith(P2_CRATES) or name.endswith("/tests.rs"):
            continue
        sm = f["summary"]
        lines[0] += sm["lines"]["covered"]
        lines[1] += sm["lines"]["count"]
        branches[0] += sm["branches"]["covered"]
        branches[1] += sm["branches"]["count"]
        per_file[name] = {"lines": sm["lines"]["percent"], "branches": sm["branches"]["percent"]}
    lr, br = lines[0] / max(lines[1], 1), branches[0] / max(branches[1], 1)
    passed = rust.returncode == 0 and lr >= 0.90 and br >= 0.85
    data_out = {"gate": "P2-T9: lines >= 90 %, branches >= 85 %", "lines": [*lines, lr],
                "branches": [*branches, br], "files": per_file, "tests_ok": rust.returncode == 0,
                "stderr_tail": rust.stderr.splitlines()[-10:],
                "outcome": "PASS" if passed else "FAIL"}  # fmt: skip
    path, sha = ledger.result_file(
        root, f"p2-coverage-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", data_out
    )
    ledger.append(
        root,
        ledger.entry(root, cmd, gate=gate, outcome=data_out["outcome"],
                     run_commit=started["commit"], result_file=str(path.relative_to(root)),
                     result_sha256=sha, rust_lines=lr, rust_branches=br),
    )  # fmt: skip
    print(json.dumps({"lines": lr, "branches": br, "outcome": data_out["outcome"]}))
    return 0 if passed else 1


def p2_mutants(root: Path, jobs: int) -> int:
    """P2-T9 (mutants): score >= 85 %, every survivor triaged in docs/MUTANTS_P2.md."""
    cmd = f"gates p2-mutants --jobs {jobs}"
    gate = "P2-T9 mutants"
    started = ledger.start(
        root, cmd, gate=gate, mutated=list(P2_MUTATED), tests=list(P2_MUTANT_TESTS)
    )
    tree = Path.home() / f".cache/sever-mutants-{started['commit'][:12]}"
    tmp = Path.home() / ".cache/mutants-tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=root, check=False,
                   capture_output=True)  # fmt: skip
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(tree), started["commit"]], cwd=root, check=True
    )
    out_dir = root / "traces/mutants-p2-gate"
    shutil.rmtree(out_dir, ignore_errors=True)
    args = ["cargo", "mutants", "-j", str(jobs), "--timeout", "300", "-o", str(out_dir)]
    for p in P2_MUTATED:
        args += ["-p", p]
    for p in P2_MUTANT_TESTS:
        args += ["--test-package", p]
    run = subprocess.run(args, cwd=tree, capture_output=True, text=True, check=False,
                         env={**os.environ, "TMPDIR": str(tmp)})  # fmt: skip
    subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=root, check=False,
                   capture_output=True)  # fmt: skip
    outcomes = json.loads((out_dir / "mutants.out/outcomes.json").read_text(encoding="utf-8"))
    counts = {
        k: outcomes.get(k, 0) for k in ("caught", "missed", "timeout", "unviable", "total_mutants")
    }
    tested = counts["caught"] + counts["missed"] + counts["timeout"]
    score = counts["caught"] / max(tested, 1)
    missed = (out_dir / "mutants.out/missed.txt").read_text(encoding="utf-8").splitlines()
    triage_file = root / "docs/MUTANTS_P2.md"
    triage = triage_file.read_text(encoding="utf-8") if triage_file.exists() else ""
    untriaged = [m for m in missed if m.split(" in ")[0] not in triage]
    passed = score >= 0.85 and not untriaged
    data_out = {"gate": "P2-T9: score >= 85 %, every survivor triaged", "counts": counts,
                "score": score, "missed": missed, "untriaged": untriaged,
                "cargo_mutants_exit": run.returncode,
                "outcome": "PASS" if passed else "FAIL"}  # fmt: skip
    path, sha = ledger.result_file(
        root, f"p2-mutants-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", data_out
    )
    ledger.append(
        root,
        ledger.entry(root, cmd, gate=gate, outcome=data_out["outcome"],
                     run_commit=started["commit"], result_file=str(path.relative_to(root)),
                     result_sha256=sha, score=score, counts=counts, untriaged=len(untriaged)),
    )  # fmt: skip
    print(json.dumps({"score": score, "counts": counts, "untriaged": len(untriaged),
                      "outcome": data_out["outcome"]}))  # fmt: skip
    return 0 if passed else 1


def p2_checks(root: Path) -> int:
    """``scripts/ci.sh full-checks``: every step PASS (P2-T4, P2-T10 and the Full-tier checks)."""
    cmd = "gates p2-checks"
    gate = "Full-tier checks (P2-T4, P2-T10, E2E-2.x, L1-L9)"
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
    data_out = {"gate": "scripts/ci.sh full-checks: every step PASS", "steps": steps,
                "seconds": round(time.time() - t0, 1),
                "stdout_tail": run.stdout.splitlines()[-40:],
                "outcome": "PASS" if passed else "FAIL"}  # fmt: skip
    path, sha = ledger.result_file(
        root, f"p2-checks-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", data_out
    )
    ledger.append(
        root,
        ledger.entry(root, cmd, gate=gate, outcome=data_out["outcome"],
                     run_commit=started["commit"], result_file=str(path.relative_to(root)),
                     result_sha256=sha, steps=steps),
    )  # fmt: skip
    print(json.dumps(steps | {"outcome": data_out["outcome"]}))
    return 0 if passed else 1


def p2_spikes(root: Path) -> int:
    """Build §3.4: the Part 2 proof spikes pass; their only output is this ledger entry."""
    cmd = "gates p2-spikes"
    gate = "P2-T7 proof spikes (Build §3.4)"
    started = ledger.start(root, cmd, gate=gate)
    t0 = time.time()
    run = subprocess.run(
        ["cargo", "test", "--release", "--manifest-path", "spikes/p2-proof/Cargo.toml"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    results = [ln for ln in run.stdout.splitlines() if ln.startswith("test ")]
    passed = run.returncode == 0 and len(results) > 0
    data_out = {"gate": "Build §3.4 proof spikes", "tests": results,
                "seconds": round(time.time() - t0, 1), "outcome": "PASS" if passed else "FAIL",
                "stderr_tail": run.stderr.splitlines()[-15:]}  # fmt: skip
    path, sha = ledger.result_file(
        root, f"p2-spikes-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", data_out
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
            tests=results,
        ),
    )
    print(json.dumps([*results, data_out["outcome"]]))
    return 0 if passed else 1


FUZZ_TARGETS = ("wal_record", "manifest", "checkpoint_file", "store_record")


def p2_fuzz(root: Path, runs: int) -> int:
    """P2-T6: ``runs`` executions per parser, 0 crashes."""
    cmd = f"gates p2-fuzz --runs {runs}"
    started = ledger.start(root, cmd, gate="P2-T6", runs=runs, targets=list(FUZZ_TARGETS))
    fuzz = root / "fuzz-p2"
    procs = {}
    for t in FUZZ_TARGETS:
        (fuzz / "corpus" / t).mkdir(parents=True, exist_ok=True)
        procs[t] = subprocess.Popen(
            ["cargo", "+nightly", "fuzz", "run", "--fuzz-dir", "fuzz-p2", "-O", t,
             f"fuzz-p2/corpus/{t}", f"fuzz-p2/seeds/{t}", "--", f"-runs={runs}",
             "-print_final_stats=1"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )  # fmt: skip
    out: dict[str, Any] = {}
    for t, p in procs.items():
        log = p.communicate()[0]
        done = [ln for ln in log.splitlines() if ln.startswith("Done ")]
        out[t] = {
            "exit": p.returncode,
            "done": done[-1] if done else None,
            "crashed": p.returncode != 0 or "panicked" in log or "ERROR: libFuzzer" in log,
            "tail": log.splitlines()[-12:],
        }
    passed = all(not v["crashed"] and v["done"] for v in out.values())
    data_out = {"gate": "P2-T6 (0 crashes)", "runs_per_target": runs, "targets": out,
                "outcome": "PASS" if passed else "FAIL"}  # fmt: skip
    path, sha = ledger.result_file(
        root, f"p2-fuzz-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", data_out
    )
    ledger.append(
        root,
        ledger.entry(
            root,
            cmd,
            gate="P2-T6",
            outcome=data_out["outcome"],
            run_commit=started["commit"],
            result_file=str(path.relative_to(root)),
            result_sha256=sha,
            summary={t: v["done"] for t, v in out.items()},
        ),
    )
    print(json.dumps({t: v["done"] for t, v in out.items()} | {"outcome": data_out["outcome"]}))
    return 0 if passed else 1


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gates-p2", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("p2-crash")
    c.add_argument("--data", default="nq-10k")
    c.add_argument("--seed", type=int, action="append")
    c.add_argument("--all-seeds", action="store_true")
    c.add_argument("--jobs", type=int, default=1)
    c.add_argument("--root", type=Path, default=Path("."))
    c.add_argument("--limit-ops", type=int, default=None, help="smoke runs only; not a gate")
    c.add_argument("--resume", action="store_true", help="continue the interrupted run")
    f = sub.add_parser("p2-fuzz")
    f.add_argument("--runs", type=int, default=100_000_000)
    f.add_argument("--root", type=Path, default=Path("."))
    rp = sub.add_parser("p2-replay")
    rp.add_argument("--data", default="nq-10k")
    rp.add_argument("--seed", type=int, action="append")
    rp.add_argument("--all-seeds", action="store_true")
    rp.add_argument("--jobs", type=int, default=1)
    rp.add_argument("--root", type=Path, default=Path("."))
    ck = sub.add_parser("p2-checks")
    ck.add_argument("--root", type=Path, default=Path("."))
    cv = sub.add_parser("p2-coverage")
    cv.add_argument("--root", type=Path, default=Path("."))
    mu = sub.add_parser("p2-mutants")
    mu.add_argument("--jobs", type=int, default=2)
    mu.add_argument("--root", type=Path, default=Path("."))
    me = sub.add_parser("p2-measures")
    me.add_argument("--data", default="nq-100k")
    me.add_argument("--seed", type=int, default=42)
    me.add_argument("--root", type=Path, default=Path("."))
    sb = sub.add_parser("p2-sabotage")
    sb.add_argument("--root", type=Path, default=Path("."))
    sp = sub.add_parser("p2-spikes")
    sp.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    if args.cmd == "p2-replay":
        rseeds = list(SEEDS) if args.all_seeds else (args.seed or [42])
        return p2_replay(args.root.resolve(), args.data, rseeds, args.jobs)
    if args.cmd == "p2-checks":
        return p2_checks(args.root.resolve())
    if args.cmd == "p2-coverage":
        return p2_coverage(args.root.resolve())
    if args.cmd == "p2-mutants":
        return p2_mutants(args.root.resolve(), args.jobs)
    if args.cmd == "p2-measures":
        return p2_measures(args.root.resolve(), args.data, args.seed)
    if args.cmd == "p2-sabotage":
        return p2_sabotage(args.root.resolve())
    if args.cmd == "p2-spikes":
        return p2_spikes(args.root.resolve())
    if args.cmd == "p2-fuzz":
        return p2_fuzz(args.root.resolve(), args.runs)
    seeds = list(SEEDS) if args.all_seeds else (args.seed or [42])
    if args.cmd == "p2-crash":
        extra = ["--limit-ops", str(args.limit_ops)] if args.limit_ops else []
        return p2_crash(args.root.resolve(), args.data, seeds, args.jobs, extra, args.resume)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
