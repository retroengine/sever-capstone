"""Gate runners that write the run ledger (Build §2.5, §2.8 Full tier).

    uv run python -m sever_testkit.gates p1-differential --data nq-10k --all-seeds
    uv run python -m sever_testkit.gates p1-differential --data nq-100k --all-seeds
    uv run python -m sever_testkit.gates p1-quant-recall --data nq-100k
    uv run python -m sever_testkit.gates p1-fuzz --runs 100000000
    uv run python -m sever_testkit.gates p1-synthetic --streams 1000 --ops 1000 --jobs 5
    uv run python -m sever_testkit.gates p1-spikes

``p1-differential`` is gates P1-T2 and P1-T5, plus the P1-T1 survivors check after every deletion
and the P1-T4 kernel check on every scored query–vector pair: the model writes a trace per seed,
the Rust replayer compares every value, and the gate passes only when every failure count is 0.
Seeds run in ``--jobs`` parallel processes (about 0.2 GB each at nq-10k, 2 GB at nq-100k).
``p1-quant-recall`` is the measure P1-T7 (overview T-6, first size): reported as found.
``p1-synthetic`` is the L4 synthetic differential (Build §4.7; evidence for P1-T1, P1-T2 and P1-T5):
seeded random streams at the small fixture size, model against engine after every operation.
``p1-spikes`` runs the throwaway proof spikes of Build §3.4 (part of gate P1-T13) and records the
result; the spike code is deleted afterwards.
``p1-fuzz`` is gate P1-T12: each Part 1 parser runs ``--runs`` libFuzzer executions (both at once)
from the committed seeds, and the gate passes only with 0 crashes.
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

import numpy as np

from sever_testkit import ledger, streams, traces
from sever_testkit.seeds import SEEDS, sub_seed


def _differential_seed(
    root: Path, data: str, seed: int, n_queries: int | None, replayer: Path
) -> dict[str, Any]:
    """One seed: the model writes the trace, then the run's replayer checks it."""
    slice_ = traces.load_slice(root, data)
    path = root / f"traces/p1-{data}-seed{seed}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        summary = traces.write_trace(
            root, f, slice_, seed, root / f"artefacts/partition-seed{seed}.svp", n_queries=n_queries
        )
    summary["trace_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    rep = subprocess.run(
        [str(replayer), "replay", str(path), "--root", str(root)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    summary["replay"] = (
        json.loads(rep.stdout.strip().splitlines()[-1])
        if rep.stdout.strip()
        else {"result": "ERROR", "stderr": rep.stderr[-2000:]}
    )
    summary["replay_stderr"] = rep.stderr[-2000:]
    print(json.dumps(summary), flush=True)
    return summary


def p1_differential(
    root: Path, data: str, seeds: list[int], n_queries: int | None, jobs: int = 1
) -> int:
    cmd = f"gates p1-differential --data {data} --seeds {seeds}"
    artefacts = {
        s: hashlib.sha256((root / f"artefacts/partition-seed{s}.svp").read_bytes()).hexdigest()
        for s in seeds
    }
    started = ledger.start(
        root, cmd, gate="P1-T2, P1-T5, P1-T1, P1-T4", data=data, seeds=seeds, artefacts=artefacts
    )
    run_commit = started["commit"]
    # The replayer is built once into a target directory owned by this run, so a build made while
    # the run is going (it takes hours) cannot change the binary that replays the later seeds.
    target_dir = root / f"target/gate-{run_commit[:12]}"
    subprocess.run(
        [
            "cargo",
            "build",
            "-q",
            "--release",
            "-p",
            "sever-tracekit",
            "--target-dir",
            str(target_dir),
        ],
        cwd=root,
        check=True,
    )
    replayer = target_dir / "release/sever-tracekit"
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = [
            pool.submit(_differential_seed, root, data, seed, n_queries, replayer) for seed in seeds
        ]
        per_seed = [f.result() for f in futures]  # in seed order
    passed = all(s["replay"].get("result") == "PASS" for s in per_seed)
    data_out = {
        "gate": "P1-T2 (0 mismatches), P1-T5 (0 deleted returned), P1-T1 (0 survivors-check "
        "failures), P1-T4 (0 kernel mismatches)",
        "data": data,
        "seeds": per_seed,
        "outcome": "PASS" if passed else "FAIL",
    }
    path, sha = ledger.result_file(
        root,
        f"p1-differential-{data}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json",
        data_out,
    )
    ledger.append(
        root,
        ledger.entry(
            root,
            cmd,
            gate="P1-T2, P1-T5, P1-T1, P1-T4",
            data=data,
            seeds=seeds,
            artefacts=artefacts,
            outcome=data_out["outcome"],
            # The code that ran is the commit at start; "commit" is HEAD when the run ended.
            run_commit=run_commit,
            result_file=str(path.relative_to(root)),
            result_sha256=sha,
            summary={str(s["seed"]): s["replay"] for s in per_seed},
        ),
    )
    return 0 if passed else 1


def p1_quant_recall(root: Path, data: str) -> int:
    """P1-T7 / overview T-6: Recall@10 of brute force over dequantised vectors against brute force
    over the original float32 vectors, all 3,452 queries. A measure: reported exactly as found."""
    cmd = f"gates p1-quant-recall --data {data}"
    ledger.start(root, cmd, measure="P1-T7 (T-6, pre-registered >= 0.999)", data=data)
    n = traces.SLICES[data]
    x = np.load(root / "datasets/processed/nq_1m/embeddings.npy", mmap_mode="r")[:n]
    q = np.load(root / "datasets/processed/nq_queries/embeddings.npy")
    k = 10
    hits = 0
    t0 = time.time()

    # Brute force by float64 squared distance |q|² − 2q·x + |x|², in blocks of 10,000 rows (peak
    # memory about 1.5 GB at nq-100k); ties broken by row index.
    block = 10_000

    def topk(mat_rows: np.ndarray) -> np.ndarray:
        best_d = np.full((len(q), k), np.inf)
        best_i = np.full((len(q), k), -1, dtype=np.int64)
        q64 = q.astype(np.float64)
        qn = (q64 * q64).sum(axis=1)[:, None]
        for s in range(0, n, block):
            blk = np.asarray(mat_rows[s : s + block], dtype=np.float64)
            dist = qn - 2.0 * q64 @ blk.T + (blk * blk).sum(axis=1)[None, :]
            idx = np.arange(s, s + blk.shape[0])
            cand_d = np.concatenate([best_d, dist], axis=1)
            cand_i = np.concatenate([best_i, np.broadcast_to(idx, dist.shape)], axis=1)
            order = np.lexsort((cand_i, cand_d), axis=1)[:, :k]
            best_d = np.take_along_axis(cand_d, order, axis=1)
            best_i = np.take_along_axis(cand_i, order, axis=1)
        return best_i

    truth = topk(x)
    deq = np.round(np.asarray(x, dtype=np.float64) * 2.0**24) / 2.0**24  # §4.2–4.3, exact in f64
    approx = topk(deq)
    for a, b in zip(truth, approx, strict=True):
        hits += len(set(a.tolist()) & set(b.tolist()))
    recall = hits / (len(q) * k)
    out = {
        "measure": "P1-T7 (overview T-6, first size)",
        "data": data,
        "queries": len(q),
        "k": k,
        "recall_at_10": recall,
        "target_pre_registered": 0.999,
        "met": recall >= 0.999,
        "seconds": round(time.time() - t0, 1),
        "method": "float64 brute force, |q|^2 - 2 q.x + |x|^2; ties by row index; "
        "dequantised = round_half_even(x*2^24)/2^24",
    }
    path, sha = ledger.result_file(
        root, f"p1-quant-recall-{data}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", out
    )
    ledger.append(
        root,
        ledger.entry(
            root,
            cmd,
            measure="P1-T7",
            data=data,
            outcome="measured",
            result_file=str(path.relative_to(root)),
            result_sha256=sha,
            recall_at_10=recall,
        ),
    )
    print(json.dumps(out))
    return 0


def _synthetic_seed(
    root: Path, fixture: Path, seed: int, n_streams: int, n_ops: int, replayer: Path
) -> dict[str, Any]:
    """``n_streams`` streams for one overview seed; one replayer call for all of them."""
    out_dir = fixture / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(n_streams):
        rng = np.random.Generator(np.random.PCG64([sub_seed(seed, "stream"), i]))
        path = out_dir / f"stream{i:04d}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            streams.write_stream_trace(fixture, f, streams.random_ops(rng, n_ops))
        paths.append(str(path))
    rep = subprocess.run(
        [str(replayer), "replay", *paths, "--root", str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    rows = [json.loads(ln) for ln in rep.stdout.splitlines() if ln.startswith("{")]
    keys = ("ops", "compared", "mismatches", "deleted_returned", "survivor_groups_checked",
            "survivor_failures", "kernel_pairs", "kernel_mismatches")  # fmt: skip
    total: dict[str, Any] = {k: sum(int(r[k]) for r in rows) for k in keys}
    total["streams_replayed"] = len(rows)
    total["streams_failed"] = sum(r["result"] != "PASS" for r in rows)
    total["stderr"] = rep.stderr[-1500:]
    print(json.dumps({"seed": seed} | total), flush=True)
    return {"seed": seed} | total


def p1_synthetic(root: Path, n_streams: int, n_ops: int, jobs: int) -> int:
    """L4: ``n_streams`` streams of ``n_ops`` operations, split evenly over the five seeds."""
    cmd = f"gates p1-synthetic --streams {n_streams} --ops {n_ops}"
    started = ledger.start(root, cmd, gate="L4 synthetic differential (P1-T1, P1-T2, P1-T5)")
    target_dir = root / f"target/gate-{started['commit'][:12]}"
    subprocess.run(
        ["cargo", "build", "-q", "--release", "-p", "sever-tracekit", "--target-dir",
         str(target_dir)],
        cwd=root,
        check=True,
    )  # fmt: skip
    replayer = target_dir / "release/sever-tracekit"
    fixture = root / "traces/synthetic"
    streams.write_fixture(root, fixture)
    per = n_streams // len(SEEDS)
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = [
            pool.submit(_synthetic_seed, root, fixture, seed, per, n_ops, replayer)
            for seed in SEEDS
        ]
        per_seed = [f.result() for f in futures]
    failures = ("mismatches", "deleted_returned", "survivor_failures", "kernel_mismatches",
                "streams_failed")  # fmt: skip
    passed = all(s["streams_replayed"] == per for s in per_seed) and all(
        s[k] == 0 for s in per_seed for k in failures
    )
    data_out = {"gate": "L4: 0 of every failure count", "streams": per * len(SEEDS),
                "ops_per_stream": n_ops, "seeds": per_seed,
                "outcome": "PASS" if passed else "FAIL"}  # fmt: skip
    path, sha = ledger.result_file(
        root, f"p1-synthetic-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", data_out
    )
    ledger.append(
        root,
        ledger.entry(
            root,
            cmd,
            gate="L4 synthetic differential (P1-T1, P1-T2, P1-T5)",
            outcome=data_out["outcome"],
            run_commit=started["commit"],
            result_file=str(path.relative_to(root)),
            result_sha256=sha,
            summary={str(s["seed"]): {k: s[k] for k in ("compared", *failures)} for s in per_seed},
        ),
    )
    return 0 if passed else 1


def p1_spikes(root: Path) -> int:
    """Build §3.4: the Part 1 proof spikes pass; their only output is this ledger entry."""
    cmd = "gates p1-spikes"
    started = ledger.start(root, cmd, gate="P1-T13 proof spikes (Build §3.4)")
    t0 = time.time()
    run = subprocess.run(
        ["cargo", "test", "--release", "--manifest-path", "spikes/p1-proof/Cargo.toml"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    results = [ln for ln in run.stdout.splitlines() if ln.startswith("test ")]
    passed = run.returncode == 0
    data_out = {"gate": "Build §3.4 proof spikes", "tests": results,
                "seconds": round(time.time() - t0, 1), "outcome": "PASS" if passed else "FAIL",
                "stderr_tail": run.stderr.splitlines()[-15:]}  # fmt: skip
    path, sha = ledger.result_file(
        root, f"p1-spikes-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", data_out
    )
    ledger.append(
        root,
        ledger.entry(
            root,
            cmd,
            gate="P1-T13 proof spikes (Build §3.4)",
            outcome=data_out["outcome"],
            run_commit=started["commit"],
            result_file=str(path.relative_to(root)),
            result_sha256=sha,
            tests=results,
        ),
    )
    print(json.dumps(data_out["tests"] + [data_out["outcome"]]))
    return 0 if passed else 1


FUZZ_TARGETS = ("artefact_parse", "blob_parse")


def p1_fuzz(root: Path, runs: int) -> int:
    """P1-T12: ``runs`` executions per parser, 0 crashes."""
    cmd = f"gates p1-fuzz --runs {runs}"
    started = ledger.start(root, cmd, gate="P1-T12", runs=runs, targets=list(FUZZ_TARGETS))
    fuzz = root / "fuzz"
    procs = {}
    for t in FUZZ_TARGETS:
        (fuzz / "corpus" / t).mkdir(parents=True, exist_ok=True)
        procs[t] = subprocess.Popen(
            ["cargo", "+nightly", "fuzz", "run", t, f"corpus/{t}", f"seeds/{t}", "--",
             f"-runs={runs}", "-print_final_stats=1"],
            cwd=fuzz,
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
    data_out = {"gate": "P1-T12 (0 crashes)", "runs_per_target": runs, "targets": out,
                "outcome": "PASS" if passed else "FAIL"}  # fmt: skip
    path, sha = ledger.result_file(
        root, f"p1-fuzz-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", data_out
    )
    ledger.append(
        root,
        ledger.entry(
            root,
            cmd,
            gate="P1-T12",
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
    ap = argparse.ArgumentParser(prog="gates", description=__doc__)
    ap.add_argument(
        "gate",
        choices=["p1-differential", "p1-quant-recall", "p1-fuzz", "p1-synthetic", "p1-spikes"],
    )
    ap.add_argument("--streams", type=int, default=1000, help="p1-synthetic: streams in all")
    ap.add_argument("--ops", type=int, default=1000, help="p1-synthetic: operations per stream")
    ap.add_argument("--runs", type=int, default=100_000_000, help="p1-fuzz: executions per parser")
    ap.add_argument("--data", default="nq-10k", choices=sorted(traces.SLICES))
    ap.add_argument("--seed", type=int, action="append")
    ap.add_argument("--all-seeds", action="store_true")
    ap.add_argument("--queries", type=int, default=None)
    ap.add_argument("--jobs", type=int, default=1, help="seeds run in parallel")
    ap.add_argument("--root", type=Path, default=Path("."))
    a = ap.parse_args(argv)
    seeds = list(SEEDS) if a.all_seeds else (a.seed or [42])
    if a.gate == "p1-differential":
        return p1_differential(a.root.resolve(), a.data, seeds, a.queries, a.jobs)
    if a.gate == "p1-spikes":
        return p1_spikes(a.root.resolve())
    if a.gate == "p1-synthetic":
        return p1_synthetic(a.root.resolve(), a.streams, a.ops, a.jobs)
    if a.gate == "p1-fuzz":
        return p1_fuzz(a.root.resolve(), a.runs)
    return p1_quant_recall(a.root.resolve(), a.data)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
