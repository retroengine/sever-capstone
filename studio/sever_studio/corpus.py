"""The records Studio stores and the questions it asks.

``nq``: the first rows of the pinned Natural Questions corpus (``datasets/processed/nq_1m``, P0).
Each passage's article title is the *account* that owns it. The 3,452 real test questions come
with the passages judged to answer them (``qrels``); the first 4,201 passages are the judged ones.
``prepare`` stores ``rows`` of them; the rows after them stay unstored for the live demos (filling
the holding area, the writer that is killed).

``synthetic``: the golden fixture (``d = 16``, 4 frozen groups, spawn size 8, 240 vectors), offline,
then made-up records in seeded blocks.

Both grow without changing what came before (``load(root, data, size)`` with a larger ``size`` keeps
the first rows identical), so the live demos never run out of passages.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pyarrow.parquet as pq

Vectors = npt.NDArray[np.float32]

NQ = "datasets/processed/nq_1m"
QUERIES = "datasets/processed/nq_queries"
FIXTURE_ARTEFACT = "golden/p1_partition_small.svp"
FIXTURE_VECTORS = "golden/p1_fixture_vectors.json"
FIXTURE_ENCODER = "test-encoder@0"


class DataMissingError(Exception):
    """The P0 data or the partition artefact is not there."""


@dataclass
class Corpus:
    name: str
    d: int
    artefact: Path
    spawn_target: int
    encoder: str
    ids: list[str]
    accounts: list[str]
    texts: list[str]
    vectors: Vectors
    questions: list[str]
    question_vectors: Vectors
    answers: dict[int, frozenset[str]]
    position: dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        self.position = {rid: i for i, rid in enumerate(self.ids)}

    def artefact_encoder(self) -> str:
        """The encoder the partition artefact names (§3.3)."""
        return str(json.loads(self.artefact.with_suffix(".json").read_text("utf-8"))["encoder"])


def _data_encoder(root: Path) -> str:
    meta = json.loads((root / "datasets/processed/meta.json").read_text("utf-8"))
    enc = meta["pins"]["repos"]["encoder"]
    return f"{enc['repo_id']}@{enc['revision']}"


def load_nq(root: Path, rows: int, seed: int = 42) -> Corpus:
    artefact = root / f"artefacts/partition-seed{seed}.svp"
    for path in (root / NQ / "passages.parquet", root / QUERIES / "queries.parquet", artefact):
        if not path.exists():
            raise DataMissingError(f"missing {path.relative_to(root)}")
    ids: list[str] = []
    accounts: list[str] = []
    texts: list[str] = []
    for batch in pq.ParquetFile(root / NQ / "passages.parquet").iter_batches(
        batch_size=8192, columns=["id", "cohort", "text"]
    ):
        b = batch.slice(0, rows - len(ids)).to_pydict()
        ids += [str(x) for x in b["id"]]
        accounts += [str(x) for x in b["cohort"]]
        texts += [str(x) for x in b["text"]]
        if len(ids) >= rows:
            break
    vectors = np.asarray(np.load(root / NQ / "embeddings.npy", mmap_mode="r")[:rows], np.float32)
    queries = pq.read_table(root / QUERIES / "queries.parquet").to_pylist()
    row_of = {q["query_id"]: i for i, q in enumerate(queries)}
    answers: dict[int, set[str]] = {}
    for r in pq.read_table(root / QUERIES / "qrels_test.parquet").to_pylist():
        if r["score"] > 0 and r["query_id"] in row_of:
            answers.setdefault(row_of[r["query_id"]], set()).add(str(r["corpus_id"]))
    return Corpus(
        name="nq",
        d=384,
        artefact=artefact,
        spawn_target=200,
        encoder=_data_encoder(root),
        ids=ids,
        accounts=accounts,
        texts=texts,
        vectors=vectors,
        questions=[str(q["text"]) for q in queries],
        question_vectors=np.asarray(np.load(root / QUERIES / "embeddings.npy"), np.float32),
        answers={q: frozenset(a) for q, a in answers.items()},
    )


#: Made-up records after the fixture's 240 come in blocks of this many, block k from seed 42 + k.
FIXTURE_EXTRA = 2000


def _fixture_block(base: npt.NDArray[np.float64], k: int) -> npt.NDArray[np.float64]:
    rng = np.random.default_rng(42 + k)
    near = base[rng.integers(0, len(base), FIXTURE_EXTRA // 2)]
    near = near + rng.normal(0, 0.02, near.shape)
    far = rng.normal(0, 1, (FIXTURE_EXTRA - len(near), 16))
    extra = np.concatenate([near, far])
    extra = extra[rng.permutation(len(extra))]
    out: npt.NDArray[np.float64] = extra / np.linalg.norm(extra, axis=1, keepdims=True)
    return out


def load_fixture(root: Path, size: int = 0) -> Corpus:
    """The fixture's 240 unit vectors, then made-up ones in blocks of ``FIXTURE_EXTRA`` until there
    are at least ``size``: half close to a fixture vector (they join its group), half in random
    directions (they fit no group, so they fill the holding area). Seven made-up accounts; question
    i is record 20·i's own vector, so its answer is that record."""
    doc = json.loads((root / FIXTURE_VECTORS).read_text("utf-8"))
    raw = b"".join(bytes.fromhex(h) for h in doc["ref"] + doc["live"])
    base = np.frombuffer(raw, dtype="<f4").reshape(-1, 16).astype(np.float64)
    blocks = max(1, -(-(size - len(base)) // FIXTURE_EXTRA))
    extra = np.concatenate([_fixture_block(base, k) for k in range(blocks)])
    vectors = np.concatenate([base, extra]).astype(np.float32)
    ids = [f"rec-{i:03d}" for i in range(len(base))]
    ids += [f"syn-{i:04d}" for i in range(len(extra))]
    picks = list(range(0, len(base), 20))
    return Corpus(
        name="synthetic",
        d=16,
        artefact=root / FIXTURE_ARTEFACT,
        spawn_target=8,
        encoder=FIXTURE_ENCODER,
        ids=ids,
        accounts=[f"account-{i % 7}" for i in range(len(ids))],
        texts=[f"synthetic passage {i}, owned by account-{i % 7}" for i in range(len(ids))],
        vectors=vectors,
        questions=[f"the record nearest to fixture vector {i}" for i in picks],
        question_vectors=vectors[picks],
        answers={q: frozenset({ids[i]}) for q, i in enumerate(picks)},
    )


def fixture_encode(text: str, d: int = 16) -> Vectors:
    """The offline fixture has no encoder: a stand-in that maps text to a unit vector by hashing
    (``test-encoder@0``). Only ever used with ``--data synthetic``."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    v = np.array([b - 127.5 for b in (h * 2)[:d]], dtype=np.float64)
    return (v / np.linalg.norm(v)).astype(np.float32)[None, :]


def load(root: Path, data: str, rows: int) -> Corpus:
    """At least ``rows`` passages (the fixture comes in whole blocks)."""
    if data == "synthetic":
        return load_fixture(root, rows)
    if data == "nq":
        return load_nq(root, rows)
    raise ValueError(f"unknown data {data!r} (nq or synthetic)")
