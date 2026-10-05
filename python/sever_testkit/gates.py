"""Gate runners that write the run ledger (Build §2.5, §2.8 Full tier).

    uv run python -m sever_testkit.gates p1-differential --data nq-10k --all-seeds
    uv run python -m sever_testkit.gates p1-differential --data nq-100k --all-seeds
    uv run python -m sever_testkit.gates p1-quant-recall --data nq-100k

``p1-differential`` is gates P1-T2 and P1-T5: the model writes a trace per seed, the Rust replayer
compares every value, and the gate passes only with 0 mismatches and 0 deleted records returned.
``p1-quant-recall`` is the measure P1-T7 (overview T-6, first size): reported as found.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from sever_testkit import ledger, traces
from sever_testkit.seeds import SEEDS


def p1_differential(root: Path, data: str, seeds: list[int], n_queries: int | None) -> int:
    cmd = f"gates p1-differential --data {data} --seeds {seeds}"
    artefacts = {
        s: hashlib.sha256((root / f"artefacts/partition-seed{s}.svp").read_bytes()).hexdigest()
        for s in seeds
    }
    started = ledger.start(
        root, cmd, gate="P1-T2, P1-T5", data=data, seeds=seeds, artefacts=artefacts
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
    slice_ = traces.load_slice(root, data)
    per_seed: list[dict[str, Any]] = []
    for seed in seeds:
        path = root / f"traces/p1-{data}-seed{seed}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            summary = traces.write_trace(
                root,
                f,
                slice_,
                seed,
                root / f"artefacts/partition-seed{seed}.svp",
                n_queries=n_queries,
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
        per_seed.append(summary)
    passed = all(s["replay"].get("result") == "PASS" for s in per_seed)
    data_out = {
        "gate": "P1-T2 (0 mismatches), P1-T5 (0 deleted returned)",
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
            gate="P1-T2, P1-T5",
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

    # Brute force by exact float64 squared distance, chunked; ties broken by row index (stable).
    def topk(mat_rows: np.ndarray) -> np.ndarray:
        best_d = np.full((len(q), k), np.inf)
        best_i = np.full((len(q), k), -1, dtype=np.int64)
        q64 = q.astype(np.float64)
        qn = (q64 * q64).sum(axis=1)[:, None]
        for s in range(0, n, 50_000):
            blk = np.asarray(mat_rows[s : s + 50_000], dtype=np.float64)
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
        "method": "exact float64 brute force; ties by row index; "
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


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gates", description=__doc__)
    ap.add_argument("gate", choices=["p1-differential", "p1-quant-recall"])
    ap.add_argument("--data", default="nq-10k", choices=sorted(traces.SLICES))
    ap.add_argument("--seed", type=int, action="append")
    ap.add_argument("--all-seeds", action="store_true")
    ap.add_argument("--queries", type=int, default=None)
    ap.add_argument("--root", type=Path, default=Path("."))
    a = ap.parse_args(argv)
    seeds = list(SEEDS) if a.all_seeds else (a.seed or [42])
    if a.gate == "p1-differential":
        return p1_differential(a.root.resolve(), a.data, seeds, a.queries)
    return p1_quant_recall(a.root.resolve(), a.data)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
