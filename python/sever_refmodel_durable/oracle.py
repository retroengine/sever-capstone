"""The durable oracle (Build §5.5) and the crash-campaign stream (Build §5.7 L10).

    PYTHONPATH=python uv run python -m sever_refmodel_durable.oracle write --data nq-10k --seed 42
    PYTHONPATH=python uv run python -m sever_refmodel_durable.oracle check ORACLE RESULTS

**State digest.** The canonical state of one collection, byte for byte:

    SHA-256( b"SEVERDB-STATE-1" ‖ u64be N ‖ u64be k ‖ u32be group_count
             ‖ per frozen and spawned group, ascending by ID bytes:
                   u16be id_len ‖ id ‖ u32be blob_len ‖ canonical blob (§5.5, core form)
             ‖ u32be holding_count ‖ per holding record, ascending by ID bytes: u16be len ‖ id )

Two states with the same digest have the same blobs (so the same S, n and members in every group),
the same holding area and the same counters.

**The stream** (20,000 operations over the 10,000 passages of ``nq-10k``): the Part 1 stream's
inserts (all passages, in the ``stream`` sub-seed order); its deletion rungs (each cohort one
``delete_user``, overview §10.8); single deletions of every remaining record, ascending by ID bytes;
then re-inserts in stream order until the stream has ``total`` operations.

**Oracle file** (JSONL): a header with the digest of the initial state, then one line per
operation with the digest after it: ``{"t":"i","id","row","s"}``, ``{"t":"d","ids","s"}``
(``delete_user``) or ``{"t":"x","id","s"}`` (one ``delete``).
"""

import argparse
import hashlib
import json
import struct
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from sever_partition import artefact
from sever_refmodel_core import model as m

DOMAIN: Final = b"SEVERDB-STATE-1"
TOTAL_OPS: Final = 20_000  # Build §5.7 L10


def state_digest(idx: m.RefIndex) -> bytes:
    """The canonical state digest (module docstring)."""
    h = hashlib.sha256(DOMAIN)
    h.update(struct.pack(">QQI", idx.big_n, idx.k, len(idx.groups)))
    for gid in sorted(idx.groups, key=m.id_bytes):
        g = gid.encode("utf-8")
        blob = idx.blob(gid)
        h.update(struct.pack(">H", len(g)) + g + struct.pack(">I", len(blob)) + blob)
    holding = sorted(idx.holding, key=m.id_bytes)
    h.update(struct.pack(">I", len(holding)))
    for rid in holding:
        b = m.id_bytes(rid)
        h.update(struct.pack(">H", len(b)) + b)
    return h.digest()


Op = tuple[str, Any, Any]  # ("i", id, row) | ("d", [ids], None) | ("x", id, None)


def crash_stream(
    ids: Sequence[str],
    order: Sequence[int],
    rungs: Sequence[Sequence[Sequence[str]]],
    total: int = TOTAL_OPS,
) -> list[Op]:
    """The campaign stream (module docstring). ``order`` is the insert order of row indices;
    ``rungs`` the cohort lists of each deletion rung."""
    ops: list[Op] = [("i", ids[r], r) for r in order]
    deleted: set[str] = set()
    for rung in rungs:
        for cohort in rung:
            ops.append(("d", list(cohort), None))
            deleted.update(cohort)
    for rid in sorted((ids[r] for r in order if ids[r] not in deleted), key=m.id_bytes):
        ops.append(("x", rid, None))
    for r in order:
        if len(ops) >= total:
            break
        ops.append(("i", ids[r], r))
    return ops[:total]


def apply(idx: m.RefIndex, op: Op, vectors: Any) -> None:
    """One operation through the model. Errors the engine would also raise are part of the
    stream's meaning only if they change nothing (they never do: the stream is valid)."""
    kind, a, b = op
    if kind == "i":
        idx.insert(a, np.asarray(vectors[b], dtype=np.float32))
    elif kind == "d":
        idx.delete_user(list(a))
    else:
        idx.delete(a)


def oracle_lines(
    idx: m.RefIndex, ops: Sequence[Op], vectors: Any, header: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    """The oracle file's lines: the header with the initial digest, then each op with its digest."""
    yield {**header, "t": "h", "format": "sever-oracle-1", "ops": len(ops),
           "s0": state_digest(idx).hex()}  # fmt: skip
    for op in ops:
        apply(idx, op, vectors)
        kind, a, b = op
        line: dict[str, Any] = {"t": kind, "s": state_digest(idx).hex()}
        if kind == "i":
            line.update(id=a, row=int(b))
        elif kind == "d":
            line.update(ids=list(a))
        else:
            line.update(id=a)
        yield line


def write_oracle(
    out: Path,
    art_path: Path,
    ops: Sequence[Op],
    vectors: Any,
    header: dict[str, Any],
    spawn_target: int = m.SPAWN_TARGET_V1,
) -> str:
    """Writes the oracle file; returns its SHA-256."""
    art = artefact.decode(art_path.read_bytes())
    idx = m.RefIndex(art, spawn_target=spawn_target)
    with out.open("w", encoding="utf-8") as f:
        for line in oracle_lines(
            idx, ops, vectors, {**header, "artefact": str(art_path), "spawn_target": spawn_target}
        ):
            f.write(json.dumps(line, separators=(",", ":")) + "\n")
    idx.check_invariants()
    return hashlib.sha256(out.read_bytes()).hexdigest()


@dataclass
class Verdict:
    """The campaign's counts (Build §5.8 P2-T1 to P2-T3); every one must be 0."""

    crash_points: int = 0
    not_oracle_state: int = 0  # P2-T2 (and P2-T1 "corrupt recoveries")
    lost_acknowledged: int = 0  # P2-T1: recovered state is older than the acknowledged prefix
    partial_delete_user: int = 0  # P2-T3
    startup_refusals: int = 0  # P2-T1: recovery refused after an honest crash
    bad_retries: int = 0  # §15.1, §15.4: retry semantics
    double_crash_mismatch: int = 0  # recovery is idempotent (crash during recovery)
    by_kind: dict[str, int] = field(default_factory=dict)

    def failures(self) -> int:
        return (
            self.not_oracle_state
            + self.lost_acknowledged
            + self.partial_delete_user
            + self.startup_refusals
            + self.bad_retries
            + self.double_crash_mismatch
        )


def check(oracle: Path, results: Path) -> Verdict:
    """Checks every crash result against the oracle. A result line is
    ``{"op": i, "acked": a, "state": hex | null, "retry": "ok"|"bad", "double": hex|null, ...}``:
    ``i`` the index of the operation in flight, ``a`` the operations acknowledged before it
    (a = i), ``state`` the recovered digest (``null`` if recovery refused to start)."""
    lines = [json.loads(x) for x in oracle.read_text(encoding="utf-8").splitlines()]
    header, ops = lines[0], lines[1:]
    digests = [header["s0"], *(o["s"] for o in ops)]
    v = Verdict()
    with results.open(encoding="utf-8") as f:
        for raw in f:
            r = json.loads(raw)
            if r.get("t") != "crash":
                continue
            v.crash_points += 1
            v.by_kind[r["kind"]] = v.by_kind.get(r["kind"], 0) + 1
            a = int(r["acked"])
            state = r["state"]
            if state is None:
                v.startup_refusals += 1
                continue
            allowed = {digests[a]} | ({digests[a + 1]} if a + 1 < len(digests) else set())
            if state not in allowed:
                v.not_oracle_state += 1
                if state in digests[:a]:
                    v.lost_acknowledged += 1
                if a < len(ops) and ops[a]["t"] == "d":
                    v.partial_delete_user += 1
            if r.get("retry") == "bad":
                v.bad_retries += 1
            if r.get("double") is not None and r["double"] != state:
                v.double_crash_mismatch += 1
    return v


def fixture_rows() -> NDArray[np.float32]:
    """The small fixture's vectors (``golden/p1_fixture_vectors.json``): 120 in distribution, then
    120 out of distribution, d = 16."""
    doc = json.loads(Path("golden/p1_fixture_vectors.json").read_text(encoding="utf-8"))
    rows = [bytes.fromhex(h) for h in doc["ref"] + doc["live"]]
    return np.frombuffer(b"".join(rows), dtype="<f4").reshape(len(rows), 16)


def small_stream() -> list[Op]:
    """A small campaign stream on the fixture (spawn target 8): every row inserted, cohorts of 3
    (every third one deleted as a ``delete_user``), single deletions, re-inserts; 400 operations."""
    n = 240
    ids = [f"s{i:03d}" for i in range(n)]
    order = list(np.random.Generator(np.random.PCG64(7)).permutation(n))
    cohorts = [sorted(ids[i : i + 3], key=m.id_bytes) for i in range(0, n, 3)]
    rungs = [cohorts[0:20], cohorts[20:40], cohorts[40:60]]
    return crash_stream(ids, [int(r) for r in order], rungs, 400)


def write_small(out: Path) -> str:
    """Writes the small-fixture oracle (a golden file for the Rust crash kit's fast tests)."""
    return write_oracle(
        out,
        Path("golden/p1_partition_small.svp"),
        small_stream(),
        fixture_rows(),
        {"data": "small-fixture", "seed": 7, "vectors": "golden/p1_fixture_vectors.json"},
        spawn_target=8,
    )


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="sever-oracle", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="write the oracle file of one seed")
    w.add_argument("--data", default="nq-10k")
    w.add_argument("--seed", type=int, default=42)
    w.add_argument("--root", type=Path, default=Path("."))
    w.add_argument("--out", type=Path, default=Path("traces"))
    w.add_argument("--total", type=int, default=TOTAL_OPS)
    sm = sub.add_parser("small", help="write the small-fixture oracle (golden file)")
    sm.add_argument("--out", type=Path, default=Path("golden/p2_oracle_small.jsonl"))
    c = sub.add_parser("check", help="check a campaign's results against an oracle file")
    c.add_argument("oracle", type=Path)
    c.add_argument("results", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "small":
        print(json.dumps({"oracle": str(args.out), "sha256": write_small(args.out)}))
        return 0
    if args.cmd == "check":
        v = check(args.oracle, args.results)
        print(json.dumps({**v.__dict__, "failures": v.failures()}))
        return 0 if v.failures() == 0 and v.crash_points > 0 else 1
    from sever_testkit import traces  # the frozen Part 1 stream and rung definitions
    from sever_testkit.seeds import sub_seed

    root: Path = args.root
    slice_ = traces.load_slice(root, args.data)
    order = np.random.Generator(np.random.PCG64(sub_seed(args.seed, "stream"))).permutation(
        len(slice_.ids)
    )
    rungs = traces.cohort_rungs(slice_, args.seed)
    ops = crash_stream(slice_.ids, [int(r) for r in order], rungs, args.total)
    vectors: NDArray[np.float32] = np.load(root / slice_.vectors_path, mmap_mode="r")
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"p2-oracle-{args.data}-seed{args.seed}.jsonl"
    sha = write_oracle(
        out,
        root / f"artefacts/partition-seed{args.seed}.svp",
        ops,
        vectors,
        {"data": args.data, "seed": args.seed, "vectors": slice_.vectors_path},
    )
    print(json.dumps({"oracle": str(out), "ops": len(ops), "sha256": sha}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
