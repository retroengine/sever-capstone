"""Overview EX-7 (P4-T14, the cost of provable deletion) and EX-8 (P4-T15, scale), DB-54.

EX-7: per data size and seed, the three builds run the same stream through ``sever-bench``: the
measured engine (``sever``), the same engine built with ``noerase`` (encryption kept, no key
rotation, no key erase) and Part 2's engine with a durable tombstone per deletion
(``softdelete``). Each run inserts the stream, deletes the five rungs (one ``delete_user`` per
cohort), runs 1,000 searches, checkpoints, closes and reopens. Reported as found, with 95 %
percentile-bootstrap intervals over the seeds (descriptive).

P4-T14 reads the deletion phase's bytes per deleted record: the secret material §13.6 predicts
(≈ 12.9 KB: re-wrapped envelopes, the new key slot, the bucket block) and the WAL bytes by record
type (G-29, DB-90).

EX-8: ``nq-1m`` into the measured engine, no deletions; resident memory against Appendix A's
≈ 3.8 GB, recovery time (the reopen), disk use including certificates.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Final

import numpy as np

from sever_experiments import ex2
from sever_testkit.traces import load_slice

ARMS: Final = ("sever", "noerase", "softdelete")


def build(root: Path) -> dict[str, Path]:
    """``sever-bench`` twice: the measured engine and ``noerase``."""
    out = {}
    for tag, feats in (("bench", []), ("bench-noerase", ["--features", "noerase"])):
        target = root / "target" / tag
        subprocess.run(
            [
                "cargo",
                "build",
                "-q",
                "--release",
                "-p",
                "sever-eval",
                *feats,
                "--target-dir",
                str(target),
            ],
            cwd=root,
            check=True,
        )
        out[tag] = target / "release/sever-bench"
    return {"sever": out["bench"], "softdelete": out["bench"], "noerase": out["bench-noerase"]}


def prepare(root: Path, data: str, seed: int, work: Path, rungs: int) -> None:
    ladder = ex2.prepare(root, data, seed, work)
    for j, cohorts in enumerate(ladder[:rungs], start=1):
        (work / f"rung{j}.json").write_text(json.dumps(cohorts), encoding="utf-8")
    sl = load_slice(root, data)
    q = np.load(root / sl.queries_path)[:1000]
    np.ascontiguousarray(q, dtype="<f4").tofile(work / "queries.f32")
    (work / "stream.jsonl").write_text(
        "".join(
            json.dumps({"id": json.loads(line)["id"]}) + "\n"
            for line in (work / "stream.jsonl").read_text(encoding="utf-8").splitlines()
        ),
        encoding="utf-8",
    )


def run_one(
    root: Path, bins: dict[str, Path], arm: str, data: str, seed: int, rungs: int
) -> dict[str, Any]:
    work = root / "target" / f"ex7-work-{data}-seed{seed}"
    dbdir = work / f"db-{arm}"
    if not (work / "stream.f32").exists():
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        prepare(root, data, seed, work, rungs)
    shutil.rmtree(dbdir, ignore_errors=True)
    out = work / f"result-{arm}.json"
    t0 = time.time()
    r = subprocess.run(
        [
            str(bins[arm]),
            "run",
            "--arm",
            arm,
            "--dir",
            str(dbdir),
            "--work",
            str(work),
            "--artefact",
            str(root / f"artefacts/partition-seed{seed}.svp"),
            "--rungs",
            str(rungs),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    shutil.rmtree(dbdir, ignore_errors=True)
    if r.returncode != 0:
        return {"arm": arm, "seed": seed, "error": r.stderr.strip()[-500:]}
    res: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    res.update({"seed": seed, "data": data, "seconds": round(time.time() - t0)})
    print(json.dumps({"arm": arm, "seed": seed, "data": data, "ok": True}), flush=True)
    return res


def secret_material(r: dict[str, Any]) -> dict[str, float]:
    """P4-T14: per deleted record, what the deletion phase wrote of each kind."""
    pr = r["delete"]["per_record"]
    n = max(1, r["delete"]["records"])
    c = pr["counts"]
    wal = c["wal_by_type"]
    return {
        "wal_bytes": sum(wal.values()) / n,
        "wal_bucket_block": wal.get("BucketBlock", 0) / n,
        "wal_extension": wal.get("Extension", 0) / n,
        "key_file": c["bytes"].get("keys/KEYS", 0) / n,
        "wrapped_store": c["bytes"].get("wrapped", 0) / n,
        "all_bytes": c["total_bytes"] / n,
    }


def bootstrap(xs: list[float], resamples: int = 10_000) -> list[float] | None:
    if len(xs) < 2:
        return None
    rng = np.random.Generator(np.random.PCG64(0))
    a = np.asarray(xs, dtype=np.float64)
    m = [float(rng.choice(a, len(a)).mean()) for _ in range(resamples)]
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Per arm: mean and 95 % bootstrap interval over seeds of the headline numbers."""
    out: dict[str, Any] = {}
    for arm in ARMS:
        rs = [r for r in results if r.get("arm") == arm and "error" not in r]
        if not rs:
            continue
        pick = {
            "insert_p50_us": [r["insert"]["latency"]["p50_us"] for r in rs],
            "insert_p99_us": [r["insert"]["latency"]["p99_us"] for r in rs],
            "insert_per_second": [r["insert"]["latency"]["per_second"] for r in rs],
            "delete_call_p50_us": [r["delete"]["latency_per_call"]["p50_us"] for r in rs],
            "delete_call_p99_us": [r["delete"]["latency_per_call"]["p99_us"] for r in rs],
            "insert_bytes_per_op": [r["insert"]["per_op"]["bytes_per_op"] for r in rs],
            "insert_fsyncs_per_op": [r["insert"]["per_op"]["fsyncs_per_op"] for r in rs],
            "delete_bytes_per_record": [r["delete"]["per_record"]["bytes_per_op"] for r in rs],
            "delete_fsyncs_per_record": [r["delete"]["per_record"]["fsyncs_per_op"] for r in rs],
            "certificate_bytes": [r["certificate_bytes"]["mean"] for r in rs],
            "peak_memory": [r["memory"]["peak"] for r in rs],
            "reopen_seconds": [r["reopen_seconds"] for r in rs],
        }
        out[arm] = {
            k: {"mean": float(np.mean(v)), "ci95": bootstrap([float(x) for x in v])}
            for k, v in pick.items()
        }
        out[arm]["secret_material_per_deleted_record"] = [secret_material(r) for r in rs]
    return out
