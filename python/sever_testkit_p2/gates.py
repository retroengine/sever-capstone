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

``p2-spikes`` is the proof-spike part of gate P2-T7 (Build §3.4): the throwaway crate
``spikes/p2-proof`` passes; its only output is the ledger entry, then it is deleted.
"""

import argparse
import concurrent.futures
import hashlib
import json
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


def _crash_seed(
    root: Path, data: str, seed: int, bin_dir: Path, extra: list[str]
) -> dict[str, Any]:
    t0 = time.time()
    out_dir = root / "traces"
    oracle_path = out_dir / f"p2-oracle-{data}-seed{seed}.jsonl"
    durable._main(["write", "--data", data, "--seed", str(seed), "--root", str(root)])
    crashkit = bin_dir / "sever-crashkit"
    generic_out = out_dir / f"p2-generic-seed{seed}.jsonl"
    gen = subprocess.run(
        [str(crashkit), "generic", "--seed", str(seed), "--steps", "2000", "--out",
         str(generic_out)],
        cwd=root, capture_output=True, text=True, check=False,
    )  # fmt: skip
    campaign_out = out_dir / f"p2-crash-{data}-seed{seed}.jsonl"
    camp = subprocess.run(
        [str(crashkit), "campaign", "--oracle", str(oracle_path), "--root", str(root),
         "--out", str(campaign_out), "--seed", str(seed), *extra],
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
        "campaign_stderr": camp.stderr[-2000:],
        "campaign_results_sha256": _sha(campaign_out) if campaign_out.exists() else None,
        "verdict": verdict,
        "seconds": round(time.time() - t0),
    }
    print(json.dumps(result), flush=True)
    return result


def p2_crash(root: Path, data: str, seeds: list[int], jobs: int, extra: list[str]) -> int:
    cmd = f"gates p2-crash --data {data} --seeds {seeds} {' '.join(extra)}".strip()
    artefacts = {s: _sha(root / f"artefacts/partition-seed{s}.svp") for s in seeds}
    gate = "P2-T1, P2-T2, P2-T3"
    started = ledger.start(root, cmd, gate=gate, data=data, seeds=seeds, artefacts=artefacts)
    run_commit = started["commit"]
    bin_dir = _build(root, run_commit, "sever-crashkit")
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        futs = [pool.submit(_crash_seed, root, data, s, bin_dir, extra) for s in seeds]
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
    f = sub.add_parser("p2-fuzz")
    f.add_argument("--runs", type=int, default=100_000_000)
    f.add_argument("--root", type=Path, default=Path("."))
    rp = sub.add_parser("p2-replay")
    rp.add_argument("--data", default="nq-10k")
    rp.add_argument("--seed", type=int, action="append")
    rp.add_argument("--all-seeds", action="store_true")
    rp.add_argument("--jobs", type=int, default=1)
    rp.add_argument("--root", type=Path, default=Path("."))
    sb = sub.add_parser("p2-sabotage")
    sb.add_argument("--root", type=Path, default=Path("."))
    sp = sub.add_parser("p2-spikes")
    sp.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    if args.cmd == "p2-replay":
        rseeds = list(SEEDS) if args.all_seeds else (args.seed or [42])
        return p2_replay(args.root.resolve(), args.data, rseeds, args.jobs)
    if args.cmd == "p2-sabotage":
        return p2_sabotage(args.root.resolve())
    if args.cmd == "p2-spikes":
        return p2_spikes(args.root.resolve())
    if args.cmd == "p2-fuzz":
        return p2_fuzz(args.root.resolve(), args.runs)
    seeds = list(SEEDS) if args.all_seeds else (args.seed or [42])
    if args.cmd == "p2-crash":
        extra = ["--limit-ops", str(args.limit_ops)] if args.limit_ops else []
        return p2_crash(args.root, args.data, seeds, args.jobs, extra)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
