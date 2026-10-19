"""Overview EX-6 (P4-T12, T-5): search stability across the deletion rungs, four arms.

Per seed, ``nq-100k`` streamed 100 % in the seed's order (overview §10.7), measured before any
deletion (rung 0) and after each of the five rungs (§10.8):

1. **SEVER-DB**: the final engine through the SDK (``sever_db``).
2. **Frozen-only**: the same engine with spawning disabled.
3. **Soft-delete IVF**: FAISS ``IndexIVFFlat`` (L2, as §8.1 ranks), trained by k-means on the
   streamed corpus (seed ``kmeans`` mod 2^32, DB-57), ``nlist`` = SEVER-DB's group count for the
   seed at rung 0, ``nprobe`` = ⌈0.25·nlist⌉; deletions filtered at query time.
4. **Rebuild IVF**: the same index retrained from scratch on the survivors after every rung.

Metrics (§10.9): Recall@10 and Recall@100 against brute force over the **original float32** vectors
of the records currently in groups (holding-area records excluded from both sides: they are not
searchable, §7.4); nDCG@10 against the judgements; the drift statistic (standard deviation of
Recall@10 across rungs 1–5, ``ddof`` 0 and 1); balance (coefficient of variation of group sizes,
frozen and spawned separately); shape (groups, spawned groups, out-of-distribution rate).

The stream-fraction sweep (descriptive) streams 25, 50 and 75 % (100 % is the main run) into the
engine and reports rung 0's shape, holding-area occupancy and Recall@10.
"""

import json
import math
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import pyarrow.parquet as pq
from numpy.typing import NDArray

from sever_testkit.seeds import sub_seed
from sever_testkit.traces import cohort_rungs, load_slice

K: Final = 100
FRACTIONS: Final = (0.25, 0.50, 0.75)


@dataclass
class Inputs:
    ids: list[str]
    vectors: NDArray[np.float32]  # in corpus order
    order: NDArray[np.int64]  # the seed's stream order (corpus rows)
    rungs: list[list[list[str]]]
    queries: NDArray[np.float32]
    qrels: list[dict[str, int]]  # per query: corpus id -> relevance
    artefact: Path


def load(root: Path, data: str, seed: int, n_queries: int | None = None) -> Inputs:
    sl = load_slice(root, data)
    n = len(sl.ids)
    vectors = np.ascontiguousarray(np.load(root / sl.vectors_path, mmap_mode="r")[:n])
    order = np.random.Generator(np.random.PCG64(sub_seed(seed, "stream"))).permutation(n)
    qtab = pq.read_table(root / "datasets/processed/nq_queries/queries.parquet")
    qids = qtab.column("query_id").to_pylist()
    queries = np.load(root / sl.queries_path)
    rel: dict[str, dict[str, int]] = {}
    for r in pq.read_table(root / "datasets/processed/nq_queries/qrels_test.parquet").to_pylist():
        rel.setdefault(r["query_id"], {})[r["corpus_id"]] = int(r["score"])
    m = len(qids) if n_queries is None else n_queries
    return Inputs(
        sl.ids,
        vectors,
        order,
        cohort_rungs(sl, seed),
        np.ascontiguousarray(queries[:m], dtype=np.float32),
        [rel.get(q, {}) for q in qids[:m]],
        root / f"artefacts/partition-seed{seed}.svp",
    )


def truth(inp: Inputs, live: NDArray[np.bool_], k: int = K) -> list[list[str]]:
    """Brute-force top-``k`` by squared L2 over the original float32 vectors of ``live`` rows."""
    rows = np.flatnonzero(live)
    x = inp.vectors[rows]
    xn = np.einsum("ij,ij->i", x, x, dtype=np.float64)
    out: list[list[str]] = []
    for s in range(0, len(inp.queries), 256):
        q = inp.queries[s : s + 256].astype(np.float64)
        d = xn[None, :] - 2.0 * (q @ x.T.astype(np.float64))
        part = np.argpartition(d, min(k, d.shape[1] - 1), axis=1)[:, :k]
        for i, p in enumerate(part):
            best = p[np.argsort(d[i, p], kind="stable")]
            out.append([inp.ids[rows[j]] for j in best])
    return out


def recall(found: list[list[str]], true: list[list[str]], k: int) -> float:
    vals = [
        len(set(f[:k]) & set(t[:k])) / min(k, len(t)) for f, t in zip(found, true, strict=True) if t
    ]
    return float(np.mean(vals)) if vals else 0.0


def ndcg10(found: list[list[str]], qrels: list[dict[str, int]], live_ids: set[str]) -> float:
    vals = []
    for f, rel in zip(found, qrels, strict=True):
        judged = sorted((r for c, r in rel.items() if c in live_ids), reverse=True)
        if not judged:
            continue
        dcg = sum(rel.get(c, 0) / math.log2(i + 2) for i, c in enumerate(f[:10]))
        idcg = sum(r / math.log2(i + 2) for i, r in enumerate(judged[:10]))
        vals.append(dcg / idcg)
    return float(np.mean(vals)) if vals else 0.0


def cv(xs: list[int]) -> float | None:
    if not xs:
        return None
    a = np.asarray(xs, dtype=np.float64)
    return float(a.std() / a.mean()) if a.mean() > 0 else None


def drift(r10: list[float]) -> dict[str, float]:
    a = np.asarray(r10[1:], dtype=np.float64)  # rungs 1–5
    return {"ddof0": float(a.std(ddof=0)), "ddof1": float(a.std(ddof=1))}


# ---------------------------------------------------------------------------------------------
# The engine arms.


class Engine:
    """The final engine through the SDK, tracking which records sit in the holding area."""

    def __init__(self, work: Path, inp: Inputs, spawning: bool, unsafe_memory: bool) -> None:
        import sever_db

        self.sdk = sever_db
        shutil.rmtree(work, ignore_errors=True)
        self.db = sever_db.Database.open(
            work / "data", work / "keys", allow_unsafe_memory=unsafe_memory
        )
        self.cid = self.db.create_collection(
            inp.artefact, spawning_enabled=spawning, store_passages=False
        )
        self.user = sever_db.UserKey.generate()
        self.holding: set[str] = set()
        self.groups: set[str] = set()
        self.ood = 0
        self.inserted = 0

    def insert(self, rid: str, v: NDArray[np.float32]) -> None:
        req = self.sdk.prepare_insert(self.cid, rid, v.tolist(), self.user)
        p = self.db.insert(self.cid, req).placement or ""
        self.inserted += 1
        if p == "Holding":
            self.holding.add(rid)
            self.ood += 1
        elif p.startswith("Spawned"):
            if p not in self.groups and len(self.holding) == 199:
                self.holding.clear()  # §7.4: this insert's flush took the other 199
            self.groups.add(p)

    def delete(self, cohort: list[str]) -> None:
        self.db.delete_user(self.cid, cohort)
        self.holding.difference_update(cohort)

    def search(self, queries: NDArray[np.float32]) -> list[list[str]]:
        return [[r for r, _ in self.db.search(self.cid, q.tolist(), K)] for q in queries]

    def shape(self) -> dict[str, Any]:
        st = self.db.stats(self.cid)
        sizes = self.db.group_sizes(self.cid)
        return {
            "stats": st,
            "groups": len(sizes),
            "spawned": sum(1 for g, _ in sizes if g.startswith("spawn-")),
            "empty_groups": sum(1 for _, n in sizes if n == 0),
            "cv_frozen": cv([n for g, n in sizes if g.startswith("frozen-")]),
            "cv_spawned": cv([n for g, n in sizes if g.startswith("spawn-")]),
            "ood_rate": self.ood / max(1, self.inserted),
            "holding": len(self.holding),
        }

    def close(self) -> None:
        self.db.close()


def engine_arm(
    inp: Inputs, work: Path, spawning: bool, unsafe_memory: bool, log: Callable[[str], None]
) -> dict[str, Any]:
    t0 = time.time()
    e = Engine(work, inp, spawning, unsafe_memory)
    try:
        for i in inp.order:
            e.insert(inp.ids[i], inp.vectors[i])
        live = np.ones(len(inp.ids), dtype=bool)
        index = {rid: i for i, rid in enumerate(inp.ids)}
        rungs: list[dict[str, Any]] = []
        r10: list[float] = []
        for j in range(len(inp.rungs) + 1):
            if j:
                for c in inp.rungs[j - 1]:
                    e.delete(c)
                    live[[index[r] for r in c]] = False
            in_groups = live.copy()
            in_groups[[index[r] for r in e.holding]] = False
            true = truth(inp, in_groups)
            found = e.search(inp.queries)
            live_ids = {inp.ids[i] for i in np.flatnonzero(in_groups)}
            r10.append(recall(found, true, 10))
            rungs.append(
                {
                    "rung": j,
                    "records": int(in_groups.sum()),
                    "recall10": r10[-1],
                    "recall100": recall(found, true, 100),
                    "ndcg10": ndcg10(found, inp.qrels, live_ids),
                    "shape": e.shape(),
                }
            )
            log(f"rung {j}: recall10 {r10[-1]:.4f}")
    finally:
        e.close()
        shutil.rmtree(work, ignore_errors=True)
    return {"rungs": rungs, "drift": drift(r10), "seconds": round(time.time() - t0)}


# ---------------------------------------------------------------------------------------------
# The FAISS arms.


def _ivf(x: NDArray[np.float32], ids: NDArray[np.int64], nlist: int, seed: int) -> Any:
    import faiss

    d = x.shape[1]
    quant = faiss.IndexFlatL2(d)
    index = faiss.IndexIVFFlat(quant, d, nlist, faiss.METRIC_L2)
    index.cp.seed = sub_seed(seed, "kmeans") % 2**32
    index.train(x)
    index.add_with_ids(x, ids)
    return index


def _search(index: Any, q: NDArray[np.float32], nprobe: int, deleted: NDArray[np.int64]) -> Any:
    import faiss

    params = faiss.SearchParametersIVF()
    params.nprobe = nprobe
    if len(deleted):
        params.sel = faiss.IDSelectorNot(faiss.IDSelectorBatch(deleted))
    _, idx = index.search(q, K, params=params)
    return idx


def faiss_arms(
    inp: Inputs, seed: int, nlist: int, log: Callable[[str], None]
) -> dict[str, dict[str, Any]]:
    t0 = time.time()
    nprobe = math.ceil(0.25 * nlist)
    rows = inp.order  # the streamed corpus, in stream order
    x = np.ascontiguousarray(inp.vectors[rows])
    soft = _ivf(x, rows.astype(np.int64), nlist, seed)
    live = np.ones(len(inp.ids), dtype=bool)
    index = {rid: i for i, rid in enumerate(inp.ids)}
    out: dict[str, list[dict[str, Any]]] = {"soft_delete_ivf": [], "rebuild_ivf": []}
    for j in range(len(inp.rungs) + 1):
        if j:
            for c in inp.rungs[j - 1]:
                live[[index[r] for r in c]] = False
        true = truth(inp, live)
        live_ids = {inp.ids[i] for i in np.flatnonzero(live)}
        dead = np.flatnonzero(~live).astype(np.int64)
        surv = rows[live[rows]]
        rebuilt = (
            soft
            if j == 0
            else _ivf(np.ascontiguousarray(inp.vectors[surv]), surv.astype(np.int64), nlist, seed)
        )
        for arm, idx, filt in (("soft_delete_ivf", soft, dead), ("rebuild_ivf", rebuilt, dead[:0])):
            got = _search(idx, inp.queries, nprobe, filt)
            found = [[inp.ids[i] for i in row if i >= 0] for row in got]
            out[arm].append(
                {
                    "rung": j,
                    "records": int(live.sum()),
                    "recall10": recall(found, true, 10),
                    "recall100": recall(found, true, 100),
                    "ndcg10": ndcg10(found, inp.qrels, live_ids),
                }
            )
        log(f"faiss rung {j}: soft {out['soft_delete_ivf'][-1]['recall10']:.4f}")
    return {
        arm: {
            "rungs": rs,
            "drift": drift([r["recall10"] for r in rs]),
            "nlist": nlist,
            "nprobe": nprobe,
            "seconds": round(time.time() - t0),
        }
        for arm, rs in out.items()
    }


def sweep(
    inp: Inputs, work: Path, unsafe_memory: bool, log: Callable[[str], None]
) -> list[dict[str, Any]]:
    out = []
    for f in FRACTIONS:
        n = int(f * len(inp.order))
        e = Engine(work, inp, True, unsafe_memory)
        try:
            for i in inp.order[:n]:
                e.insert(inp.ids[i], inp.vectors[i])
            in_groups = np.zeros(len(inp.ids), dtype=bool)
            in_groups[inp.order[:n]] = True
            index = {rid: i for i, rid in enumerate(inp.ids)}
            in_groups[[index[r] for r in e.holding]] = False
            r10 = recall(e.search(inp.queries), truth(inp, in_groups), 10)
            out.append({"fraction": f, "streamed": n, "recall10": r10, "shape": e.shape()})
            log(f"sweep {f}: recall10 {r10:.4f}")
        finally:
            e.close()
            shutil.rmtree(work, ignore_errors=True)
    return out


def run_seed(
    root: Path,
    data: str,
    seed: int,
    unsafe_memory: bool = True,
    n_queries: int | None = None,
    with_sweep: bool = True,
) -> dict[str, Any]:
    def log(msg: str) -> None:
        print(json.dumps({"seed": seed, "msg": msg}), flush=True)

    inp = load(root, data, seed, n_queries)
    work = root / "target" / f"ex6-work-seed{seed}"
    arms: dict[str, Any] = {"sever_db": engine_arm(inp, work, True, unsafe_memory, log)}
    nlist = int(arms["sever_db"]["rungs"][0]["shape"]["groups"])
    arms["frozen_only"] = engine_arm(inp, work, False, unsafe_memory, log)
    arms.update(faiss_arms(inp, seed, nlist, log))
    return {
        "seed": seed,
        "data": data,
        "queries": len(inp.queries),
        "arms": arms,
        "sweep": sweep(inp, work, unsafe_memory, log) if with_sweep else [],
    }


def statistics(per_seed: list[dict[str, Any]]) -> dict[str, Any]:
    """Overview §11 statistics: T-5 per seed; Welch's t-test (alpha 0.005, two-sided) and TOST
    (delta 0.005) on the per-seed drift of SEVER-DB against soft-delete IVF; percentile bootstrap
    95 % intervals (10,000 resamples) of each arm's mean drift (descriptive)."""
    from scipy import stats

    def drifts(arm: str) -> NDArray[np.float64]:
        return np.asarray([s["arms"][arm]["drift"]["ddof0"] for s in per_seed], dtype=np.float64)

    a, b = drifts("sever_db"), drifts("soft_delete_ivf")
    out: dict[str, Any] = {
        "t5_per_seed": {str(s["seed"]): s["arms"]["sever_db"]["drift"] for s in per_seed},
        "t5_met": bool(np.all(a <= 0.005)),
    }
    if len(per_seed) >= 2:
        w = stats.ttest_ind(a, b, equal_var=False)
        delta = 0.005
        lo = stats.ttest_ind(a + delta, b, equal_var=False, alternative="greater")
        hi = stats.ttest_ind(a - delta, b, equal_var=False, alternative="less")
        out["welch"] = {"t": float(w.statistic), "p": float(w.pvalue), "alpha": 0.005}
        out["tost"] = {"delta": delta, "p": float(max(lo.pvalue, hi.pvalue))}
    rng = np.random.Generator(np.random.PCG64(0))
    ci: dict[str, list[float]] = {}
    for arm in per_seed[0]["arms"]:
        d = drifts(arm)
        boots = [float(rng.choice(d, len(d)).mean()) for _ in range(10_000)]
        ci[arm] = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
    out["bootstrap_mean_drift_95"] = ci
    return out
