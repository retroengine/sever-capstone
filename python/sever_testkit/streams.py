"""Operation streams at the small fixture size (Build §2.7, §4.7 L4 and L5).

A stream is a list of operations (insert a fixture row under an ID, ``delete_user`` a list of IDs,
or a checkpoint). The reference model runs it and writes a trace; the Rust replayer
(``sever-tracekit``) runs the same operations and compares every value after every step, with the
survivors check after every deletion. IDs come from a small pool, so re-inserting a deleted ID,
inserting a live ID again and deleting an absent one all happen often; the fixture's 120
out-of-distribution rows and spawn size 8 make flushes, spillover and empty groups frequent.
"""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Final, TextIO

import numpy as np
from numpy.typing import NDArray

from sever_partition import artefact
from sever_refmodel_core import model as m
from sever_testkit import traces

SPAWN_TARGET: Final = 8  # Build §2.7 small fixtures (gap G-10)
N_QUERIES: Final = 24

Op = tuple[Any, ...]  # ("i", row, id) | ("d", [ids]) | ("c",)


def fixture_rows(root: Path) -> NDArray[np.float32]:
    """The 240 fixture rows: 120 in distribution (``ref``), then 120 out of distribution."""
    doc = json.loads((root / "golden/p1_fixture_vectors.json").read_text(encoding="utf-8"))
    rows = [np.frombuffer(bytes.fromhex(h), dtype="<f4") for h in doc["ref"] + doc["live"]]
    return np.stack(rows).astype(np.float32)


def write_fixture(root: Path, dst: Path) -> None:
    """A replay root at ``dst``: the golden small artefact, the rows and the queries as .npy."""
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "golden/p1_partition_small.svp", dst / "partition.svp")
    rows = fixture_rows(root)
    np.save(dst / "vectors.npy", rows)
    # Queries: rows from both halves (they are normalised, so §8.1 accepts them).
    np.save(dst / "queries.npy", np.concatenate([rows[:12], rows[120:132]]))


def write_stream_trace(fixture: Path, out: TextIO, ops: list[Op]) -> dict[str, int]:
    """Runs ``ops`` through the model and writes the trace (paths relative to ``fixture``)."""
    art_bytes = (fixture / "partition.svp").read_bytes()
    idx = m.RefIndex(artefact.decode(art_bytes), spawn_target=SPAWN_TARGET)
    vectors = np.load(fixture / "vectors.npy")
    queries = np.load(fixture / "queries.npy")
    header = {
        "t": "h",
        "format": "sever-trace-1",
        "data": "small-fixture",
        "artefact": "partition.svp",
        "artefact_sha256": hashlib.sha256(art_bytes).hexdigest(),
        "spawning": True,
        "spawn_target": SPAWN_TARGET,
        "vectors": "vectors.npy",
        "queries": "queries.npy",
        "n_queries": len(queries),
        "top_k": traces.TOP_K,  # the checkpoint lists the model's top TOP_K
    }

    def emit(obj: dict[str, Any]) -> None:
        out.write(json.dumps(obj, separators=(",", ":")) + "\n")

    emit(header)
    counts = {"i": 0, "d": 0, "c": 0, "deleted": 0}
    rung = 0
    for op in [*ops, ("c",)]:
        if op[0] == "i":
            emit(traces.op_insert(idx, op[2], op[1], vectors[op[1]]))
        elif op[0] == "d":
            line, n = traces.op_delete(idx, list(op[1]))
            emit(line)
            counts["deleted"] += n
        else:
            rung += 1
            emit(traces.checkpoint(idx, rung, queries))
        counts[op[0]] += 1
    idx.check_invariants()
    return counts


def random_ops(rng: np.random.Generator, n_ops: int, pool: int = 60) -> list[Op]:
    """L4: a random stream. 55 % inserts (any of the 240 rows), 25 % single deletes, 15 %
    ``delete_user`` of 2–6 IDs, 5 % checkpoints; IDs from ``s0 … s<pool−1>``."""
    ops: list[Op] = []
    for _ in range(n_ops):
        u = rng.random()
        if u < 0.55:
            ops.append(("i", int(rng.integers(0, 240)), f"s{int(rng.integers(0, pool))}"))
        elif u < 0.80:
            ops.append(("d", [f"s{int(rng.integers(0, pool))}"]))
        elif u < 0.95:
            k = int(rng.integers(2, 7))
            ops.append(("d", [f"s{int(i)}" for i in rng.integers(0, pool, size=k)]))
        else:
            ops.append(("c",))
    return ops
