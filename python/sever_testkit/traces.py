"""Trace files (Build §2.4): the reference model runs a stream and writes, after every operation,
the expected outcome and the SHA-256 of every touched group's canonical blob; after each deletion
rung, every group's blob hash, the stats, and the top-100 results for every query. The Rust
replayer (``sever-tracekit``) runs the same operations and compares every value.

    uv run python -m sever_testkit.traces --data nq-10k --seed 42          # one trace
    uv run python -m sever_testkit.traces --data nq-10k --all-seeds

Stream and rungs follow overview §10.7–10.8: corpus rows in a seed-derived order; cohorts (one per
article title) in a seed-derived order; cumulative rungs of 10, 25, 50, 75 and 90 % of the cohorts,
each cohort deleted with one ``delete_user``.
"""

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TextIO

import numpy as np
import pyarrow.parquet as pq
from numpy.typing import NDArray

from sever_partition import artefact
from sever_refmodel_core import model as m
from sever_testkit.seeds import SEEDS, sub_seed

RUNGS: Final = (0.10, 0.25, 0.50, 0.75, 0.90)  # overview §10.8
TOP_K: Final = 100  # top-10 is the prefix of top-100
#: DB-59: nq-10k is the first 10,000 rows of nq-100k (and of nq-1m).
SLICES: Final = {"nq-10k": 10_000, "nq-100k": 100_000, "nq-1m": 1_000_000}


@dataclass(frozen=True)
class Slice:
    """A corpus slice: IDs, cohort titles, and the path of the vectors (row i is record i)."""

    name: str
    ids: list[str]
    cohorts: list[str]
    vectors_path: str
    queries_path: str


def load_slice(root: Path, name: str) -> Slice:
    """``nq-10k``, ``nq-100k`` or ``nq-1m`` (overview §10.4, DB-59): prefixes of the nq_1m files."""
    n = SLICES[name]
    table = pq.read_table(
        root / "datasets/processed/nq_1m/passages.parquet", columns=["id", "cohort"]
    )
    ids = table.column("id").to_pylist()[:n]
    cohorts = table.column("cohort").to_pylist()[:n]
    return Slice(
        name,
        ids,
        cohorts,
        "datasets/processed/nq_1m/embeddings.npy",
        "datasets/processed/nq_queries/embeddings.npy",
    )


def blob_hash(idx: m.RefIndex, gid: str) -> str:
    return hashlib.sha256(idx.blob(gid)).hexdigest()


def cohort_rungs(slice_: Slice, seed: int) -> list[list[list[str]]]:
    """Overview §10.8: cohorts in the ``cohort-order`` sub-seed order; rung j deletes the cohorts
    from ⌊f_{j−1}·C⌋ to ⌊f_j·C⌋. Each cohort's IDs are listed ascending by bytes."""
    by_title: dict[str, list[str]] = {}
    for rid, title in zip(slice_.ids, slice_.cohorts, strict=True):
        by_title.setdefault(title, []).append(rid)
    titles = sorted(by_title, key=lambda t: t.encode("utf-8"))
    perm = np.random.Generator(np.random.PCG64(sub_seed(seed, "cohort-order"))).permutation(
        len(titles)
    )
    ordered = [titles[i] for i in perm]
    out: list[list[list[str]]] = []
    prev = 0
    for f in RUNGS:
        upto = int(f * len(ordered))
        out.append([sorted(by_title[t], key=m.id_bytes) for t in ordered[prev:upto]])
        prev = upto
    return out


def op_insert(idx: m.RefIndex, rid: str, row: int, x: NDArray[np.float32]) -> dict[str, Any]:
    """One insert through the model, as its trace line (placement or §17 error; touched blob)."""
    line: dict[str, Any] = {"t": "i", "id": rid, "row": row}
    try:
        _kind, gid = idx.insert(rid, np.asarray(x, dtype=np.float32))
        line["p"] = gid
        if gid != m.HOLDING:
            line["g"] = {gid: blob_hash(idx, gid)}
    except m.SeverError as e:
        line["e"] = e.kind
    return line


def op_delete(idx: m.RefIndex, ids: list[str]) -> tuple[dict[str, Any], int]:
    """One delete_user through the model, as its trace line; and how many records it deleted."""
    outcomes = idx.delete_user(ids)
    touched = sorted({o.gid for o in outcomes if isinstance(o, m.Deleted) and o.gid != m.HOLDING})
    line = {
        "t": "d",
        "ids": ids,
        "o": [o.gid if isinstance(o, m.Deleted) else "absent" for o in outcomes],
        "g": {g: blob_hash(idx, g) for g in touched},
    }
    return line, sum(isinstance(o, m.Deleted) for o in outcomes)


def checkpoint(idx: m.RefIndex, rung: int, queries: NDArray[np.float32]) -> dict[str, Any]:
    """A checkpoint line: stats, every group's blob hash, top-k for every query."""
    return _checkpoint(idx, rung, queries)


def _checkpoint(idx: m.RefIndex, rung: int, queries: NDArray[np.float32]) -> dict[str, Any]:
    results = []
    for q in queries:
        hits = idx.search(np.asarray(q, dtype=np.float32), TOP_K)
        results.append(
            [
                [rid, np.float32(s).view(np.uint32).item().to_bytes(4, "big").hex()]
                for rid, s in hits
            ]
        )
    return {
        "t": "c",
        "rung": rung,
        "stats": idx.stats(),
        "g": {gid: blob_hash(idx, gid) for gid in idx.groups},
        "r": results,
    }


def write_trace(
    root: Path,
    out: TextIO,
    slice_: Slice,
    seed: int,
    art_path: Path,
    spawn_target: int = m.SPAWN_TARGET_V1,
    n_queries: int | None = None,
) -> dict[str, Any]:
    """Runs the stream through the model and writes the trace. Returns a summary."""
    t0 = time.time()
    art = artefact.decode(art_path.read_bytes())
    idx = m.RefIndex(art, spawn_target=spawn_target)
    vectors = np.load(root / slice_.vectors_path, mmap_mode="r")
    queries = np.load(root / slice_.queries_path)[:n_queries]
    n = len(slice_.ids)
    order = np.random.Generator(np.random.PCG64(sub_seed(seed, "stream"))).permutation(n)
    header = {
        "t": "h",
        "format": "sever-trace-1",
        "data": slice_.name,
        "seed": seed,
        "artefact": str(art_path),
        "artefact_sha256": hashlib.sha256(art_path.read_bytes()).hexdigest(),
        "spawning": True,
        "spawn_target": spawn_target,
        "vectors": slice_.vectors_path,
        "queries": slice_.queries_path,
        "n_queries": len(queries),
        "top_k": TOP_K,
        "rungs": list(RUNGS),
    }

    def emit(obj: dict[str, Any]) -> None:
        out.write(json.dumps(obj, separators=(",", ":")) + "\n")

    emit(header)
    for r in order:
        emit(op_insert(idx, slice_.ids[int(r)], int(r), vectors[int(r)]))
    emit(_checkpoint(idx, 0, queries))
    deleted = 0
    for j, rung in enumerate(cohort_rungs(slice_, seed), start=1):
        for cohort in rung:
            line, n_deleted = op_delete(idx, cohort)
            emit(line)
            deleted += n_deleted
        emit(_checkpoint(idx, j, queries))
    idx.check_invariants()
    return {
        "data": slice_.name,
        "seed": seed,
        "inserts": n,
        "deleted": deleted,
        "final": idx.stats(),
        "seconds": round(time.time() - t0, 1),
    }


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="sever-trace", description=__doc__)
    ap.add_argument("--data", choices=sorted(SLICES), default="nq-10k")
    ap.add_argument("--seed", type=int, action="append")
    ap.add_argument("--all-seeds", action="store_true")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path, default=Path("traces"))
    ap.add_argument("--queries", type=int, default=None, help="limit queries (default: all 3,452)")
    args = ap.parse_args(argv)
    seeds = list(SEEDS) if args.all_seeds else (args.seed or [42])
    root: Path = args.root
    slice_ = load_slice(root, args.data)
    args.out.mkdir(parents=True, exist_ok=True)
    for seed in seeds:
        path = args.out / f"p1-{args.data}-seed{seed}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            summary = write_trace(
                root,
                f,
                slice_,
                seed,
                root / f"artefacts/partition-seed{seed}.svp",
                n_queries=args.queries,
            )
        summary["trace"] = str(path)
        summary["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        print(json.dumps(summary), flush=True)
    return 0


def iter_trace(path: Path) -> Iterator[dict[str, Any]]:
    """Reads a trace back, one operation per line."""
    with path.open(encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
