"""The records the demo stores: real Natural Questions passages, or the offline fixture.

``nq``: the first ``rows`` passages of the pinned NQ corpus (``datasets/processed/nq_1m``), each
with its article title as the *account* that owns it, plus the 3,452 real test questions and which
passages answer them (``qrels``). The first 4,201 passages are the judged ones, so a few thousand
rows already answer most questions. The vectors were made by the encoder the partition names
(all-MiniLM-L6-v2, §3.3), so a question and a passage meet in the same space.

``synthetic``: the golden fixture (``d = 16``, 4 frozen groups, spawn size 8): no data needed.
"""

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pyarrow.parquet as pq

Vectors = npt.NDArray[np.float32]

NQ = "datasets/processed/nq_1m"
QUERIES = "datasets/processed/nq_queries"
SYNTHETIC_ARTEFACT = "golden/p1_partition_small.svp"
SYNTHETIC_VECTORS = "golden/p1_fixture_vectors.json"


class DataMissingError(Exception):
    """The P0 data or the partition artefact is not there (the README says how to get them)."""


@dataclass(frozen=True)
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

    @cached_property
    def position(self) -> dict[str, int]:
        """Record ID → its row."""
        return {rid: i for i, rid in enumerate(self.ids)}

    def by_account(self, upto: int) -> dict[str, list[str]]:
        """Each account's record IDs among the first ``upto`` records."""
        out: dict[str, list[str]] = {}
        for rid, acc in zip(self.ids[:upto], self.accounts[:upto], strict=True):
            out.setdefault(acc, []).append(rid)
        return out


def _encoder_of_data(root: Path) -> str:
    meta = json.loads((root / "datasets/processed/meta.json").read_text(encoding="utf-8"))
    enc = meta["pins"]["repos"]["encoder"]
    return f"{enc['repo_id']}@{enc['revision']}"


def check_encoder(corpus: Corpus) -> str:
    """§3.3: vectors must come from the encoder the partition artefact names."""
    named = str(json.loads(corpus.artefact.with_suffix(".json").read_text("utf-8"))["encoder"])
    if named != corpus.encoder:
        raise DataMissingError(f"the artefact names {named}, the vectors are from {corpus.encoder}")
    return named


def load_nq(root: Path, rows: int, seed: int = 42) -> Corpus:
    artefact = root / f"artefacts/partition-seed{seed}.svp"
    for path in (root / NQ / "passages.parquet", root / QUERIES / "queries.parquet", artefact):
        if not path.exists():
            raise DataMissingError(f"missing {path.relative_to(root)}")
    ids: list[str] = []
    accounts: list[str] = []
    texts: list[str] = []
    batches = pq.ParquetFile(root / NQ / "passages.parquet").iter_batches(
        batch_size=4096, columns=["id", "cohort", "text"]
    )
    for batch in batches:
        need = rows - len(ids)
        if need <= 0:
            break
        b = batch.slice(0, need).to_pydict()
        ids += [str(x) for x in b["id"]]
        accounts += [str(x) for x in b["cohort"]]
        texts += [str(x) for x in b["text"]]
    vectors = np.asarray(np.load(root / NQ / "embeddings.npy", mmap_mode="r")[:rows], np.float32)
    queries = pq.read_table(root / QUERIES / "queries.parquet").to_pylist()
    qvec = np.asarray(np.load(root / QUERIES / "embeddings.npy", mmap_mode="r"), np.float32)
    row_of = {q["query_id"]: i for i, q in enumerate(queries)}
    answers: dict[int, set[str]] = {}
    for r in pq.read_table(root / QUERIES / "qrels_test.parquet").to_pylist():
        if r["score"] > 0 and r["query_id"] in row_of:
            answers.setdefault(row_of[r["query_id"]], set()).add(r["corpus_id"])
    return Corpus(
        name="nq",
        d=384,
        artefact=artefact,
        spawn_target=200,
        encoder=_encoder_of_data(root),
        ids=ids,
        accounts=accounts,
        texts=texts,
        vectors=vectors,
        questions=[str(q["text"]) for q in queries],
        question_vectors=qvec,
        answers={q: frozenset(a) for q, a in answers.items()},
    )


def load_synthetic(root: Path, rows: int) -> Corpus:
    """The fixture's 240 unit vectors; seven made-up accounts; each "question" is a record's own
    vector, so its answer is that record."""
    doc = json.loads((root / SYNTHETIC_VECTORS).read_text(encoding="utf-8"))
    raw = b"".join(bytes.fromhex(h) for h in doc["ref"] + doc["live"])
    vectors = np.frombuffer(raw, dtype="<f4").reshape(-1, 16)[:rows].astype(np.float32)
    n = len(vectors)
    ids = [f"rec-{i:03d}" for i in range(n)]
    picks = list(range(0, n, max(1, n // 12)))
    return Corpus(
        name="synthetic",
        d=16,
        artefact=root / SYNTHETIC_ARTEFACT,
        spawn_target=8,
        encoder="test-encoder@0",
        ids=ids,
        accounts=[f"account-{i % 7}" for i in range(n)],
        texts=[f"synthetic passage number {i}, owned by account-{i % 7}" for i in range(n)],
        vectors=vectors,
        questions=[f"the record nearest to fixture vector {i}" for i in picks],
        question_vectors=vectors[picks],
        answers={q: frozenset({ids[i]}) for q, i in enumerate(picks)},
    )


def load(root: Path, data: str, rows: int) -> Corpus:
    if data == "synthetic":
        return load_synthetic(root, rows)
    if data == "nq":
        return load_nq(root, rows)
    raise ValueError(f"unknown data {data!r} (nq or synthetic)")
