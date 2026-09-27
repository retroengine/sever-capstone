#!/usr/bin/env python3
"""SEVER-DB, phase P0: pin, download, build and encode the datasets, exactly once.

Implements overview §10 and configs/experiments.yaml:

  reference  SciQ (allenai/sciq), all splits, text = support, else question
  live       BEIR Natural Questions (BeIR/nq corpus, BeIR/nq-qrels test)
             text = title + " " + text, record id = corpus _id, cohort = title
  corpora    nq-1m  = every judged passage, then a seeded uniform sample of the rest
             nq-100k = the first 100,000 rows of nq-1m (a strict prefix, so encoding
                      the first two shards already gives you the 100k corpus)
  encoder    sentence-transformers/all-MiniLM-L6-v2, 384-d, 256-token limit,
             truncation, normalize_embeddings=True, float32, CPU

Every output file is hashed into datasets/MANIFEST.sha256 (sha256sum -c compatible),
and every choice, version and count is written to datasets/processed/meta.json.

Usage (on the laptop, inside the project's virtualenv):

  python prepare_data.py pin          # resolve and freeze dataset/model revisions (once)
  python prepare_data.py download     # fetch exactly those revisions
  python prepare_data.py build        # corpora, queries, qrels, non-overlap checks
  python prepare_data.py encode       # embeddings; resumable, run overnight
  python prepare_data.py verify       # re-hash everything against the manifest
  python prepare_data.py all          # pin (if needed) + download + build + encode + verify

  python prepare_data.py selftest     # offline test with synthetic data and a fake encoder
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import gzip
import hashlib
import io
import json
import os
import platform
import re
import struct
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

# ---------------------------------------------------------------- constants

FORMAT_VERSION = "data-1.0"
DIM = 384
MAX_TOKENS = 256
NORM_TOL = 8 * 2.0**-23                     # spec §4.1: 8 float32 ULPs at 1.0
CORPUS_SEED = (42, b"corpus")               # overview §10.6
SIZE_1M = 1_000_000
SIZE_100K = 100_000
SHARD_ROWS = 50_000
BATCH_SIZE = 64

REPOS = {
    "sciq": ("allenai/sciq", "dataset"),
    "nq": ("BeIR/nq", "dataset"),
    "nq_qrels": ("BeIR/nq-qrels", "dataset"),
    "encoder": ("sentence-transformers/all-MiniLM-L6-v2", "model"),
}

BARE_INT = re.compile(r"^[+-]?[0-9]+$")     # spec §3.2 rule 2


def sub_seed(seed: int, label: bytes) -> int:
    """overview §10.6: first 8 bytes of SHA-256(u64be(seed) || label), big-endian."""
    return int.from_bytes(hashlib.sha256(struct.pack(">Q", seed) + label).digest()[:8], "big")


def norm_text(s: str) -> str:
    """Normalisation used only for overlap checks (overview §10.5)."""
    return " ".join(s.lower().split())


def text_hash(s: str) -> bytes:
    return hashlib.sha256(norm_text(s).encode("utf-8")).digest()


def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_rows(arr: np.ndarray, rows_per_chunk: int = 65536) -> str:
    """SHA-256 of the raw little-endian float32 rows (spec §6.3 sha256_reference)."""
    h = hashlib.sha256()
    for i in range(0, arr.shape[0], rows_per_chunk):
        h.update(np.ascontiguousarray(arr[i:i + rows_per_chunk], dtype="<f4").tobytes())
    return h.hexdigest()


def log(msg: str) -> None:
    print(f"[{_dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


class Paths:
    def __init__(self, root: Path):
        self.root = root
        self.datasets = root / "datasets"
        self.pins = self.datasets / "PINS.json"
        self.raw = self.datasets / "raw"
        self.proc = self.datasets / "processed"
        self.meta = self.proc / "meta.json"
        self.manifest = self.datasets / "MANIFEST.sha256"
        self.sciq = self.proc / "sciq_reference"
        self.nq = self.proc / "nq_1m"
        self.queries = self.proc / "nq_queries"


def load_meta(p: Paths) -> dict:
    return json.loads(p.meta.read_text(encoding="utf-8")) if p.meta.exists() else {"format_version": FORMAT_VERSION}


def save_meta(p: Paths, meta: dict) -> None:
    p.proc.mkdir(parents=True, exist_ok=True)
    tmp = p.meta.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
    os.replace(tmp, p.meta)


# ---------------------------------------------------------------- pin / download

def cmd_pin(p: Paths, force: bool = False) -> None:
    if p.pins.exists() and not force:
        log(f"pins already exist at {p.pins}; not changing them (use --force to re-pin, "
            f"which invalidates everything built from the old pins)")
        return
    from huggingface_hub import HfApi
    api = HfApi()
    pins = {"pinned_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(), "repos": {}}
    for name, (repo, kind) in REPOS.items():
        info = api.dataset_info(repo) if kind == "dataset" else api.model_info(repo)
        pins["repos"][name] = {"repo_id": repo, "type": kind, "revision": info.sha}
        log(f"pinned {repo} @ {info.sha}")
    p.datasets.mkdir(parents=True, exist_ok=True)
    p.pins.write_text(json.dumps(pins, indent=2, sort_keys=True), encoding="utf-8", newline="\n")


def load_pins(p: Paths) -> dict:
    if not p.pins.exists():
        sys.exit(f"no pins at {p.pins}; run `pin` first")
    return json.loads(p.pins.read_text(encoding="utf-8"))


def cmd_download(p: Paths) -> None:
    from huggingface_hub import snapshot_download
    pins = load_pins(p)["repos"]
    for name in ("sciq", "nq", "nq_qrels"):
        r = pins[name]
        log(f"downloading {r['repo_id']} @ {r['revision']}")
        snapshot_download(repo_id=r["repo_id"], repo_type="dataset", revision=r["revision"],
                          local_dir=str(p.raw / name))
    log("downloads complete (the encoder is fetched at its pinned revision during `encode`)")


# ---------------------------------------------------------------- raw readers

def _find(root: Path, patterns: list[str], what: str) -> list[Path]:
    for pat in patterns:
        hits = sorted(q for q in root.glob(pat) if q.is_file())
        if hits:
            return hits
    listing = "\n  ".join(str(q.relative_to(root)) for q in sorted(root.rglob("*")) if q.is_file())
    sys.exit(f"could not find {what} under {root} (tried {patterns}). Files present:\n  {listing}")


def _open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else open(path, encoding="utf-8")


def iter_jsonl_or_parquet(files: list[Path], columns: list[str]):
    for f in files:
        if f.suffix == ".parquet":
            t = pq.read_table(f, columns=columns)
            cols = [t.column(c).to_pylist() for c in columns]
            yield from zip(*cols)
        else:
            with _open_text(f) as fh:
                for line in fh:
                    if line.strip():
                        o = json.loads(line)
                        yield tuple(o.get(c, "") for c in columns)


def read_sciq(root: Path) -> tuple[list[str], list[str], int]:
    """SciQ rows in split order train, validation, test; text = support, else question."""
    ids, texts, fallback = [], [], 0
    files = _find(root, ["**/*.parquet", "**/*.jsonl", "**/*.json"], "SciQ data files")
    by_split: dict[str, list[Path]] = {"train": [], "validation": [], "test": []}
    for f in files:
        # classify by the path *inside* the repo only, never by where the repo lives
        parts = [s.lower() for s in f.relative_to(root).parts]
        name = parts[-1]
        split = next((s for s in by_split
                      if name.startswith(s + "-") or name.startswith(s + ".") or name.startswith(s + "_")
                      or s in parts[:-1]), None)
        if split:
            by_split[split].append(f)
    for split in ("train", "validation", "test"):
        if not by_split[split]:
            sys.exit(f"SciQ split {split!r} not found among {files}")
        n = 0
        for question, support in iter_jsonl_or_parquet(sorted(by_split[split]), ["question", "support"]):
            support = (support or "").strip()
            text = support if support else (question or "").strip()
            fallback += 0 if support else 1
            ids.append(f"sciq-{split}-{n:06d}")
            texts.append(text)
            n += 1
    return ids, texts, fallback


def read_qrels(root: Path) -> tuple[list[tuple[str, str, int]], set[str]]:
    f = _find(root, ["**/test.tsv", "**/test.tsv.gz", "**/*test*.parquet"], "NQ test qrels")[0]
    rows: list[tuple[str, str, int]] = []
    if f.suffix == ".parquet":
        t = pq.read_table(f)
        for q, c, s in zip(t.column("query-id").to_pylist(), t.column("corpus-id").to_pylist(),
                           t.column("score").to_pylist()):
            rows.append((str(q), str(c), int(s)))
    else:
        with _open_text(f) as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                rows.append((str(r["query-id"]), str(r["corpus-id"]), int(r["score"])))
    judged = {c for _, c, s in rows if s > 0}
    return rows, judged


def corpus_files(root: Path) -> list[Path]:
    return _find(root, ["**/corpus.jsonl.gz", "**/corpus.jsonl", "**/corpus/*.parquet",
                        "**/corpus*.parquet"], "NQ corpus")


def query_files(root: Path) -> list[Path]:
    return _find(root, ["**/queries.jsonl.gz", "**/queries.jsonl", "**/queries/*.parquet",
                        "**/queries*.parquet"], "NQ queries")


# ---------------------------------------------------------------- build

def check_record_id(rid: str) -> None:
    b = rid.encode("utf-8")
    if not (1 <= len(b) <= 256) or BARE_INT.match(rid):
        sys.exit(f"record id violates spec §3.2: {rid!r}")


def cmd_build(p: Paths, size_big: int = SIZE_1M, size_small: int = SIZE_100K) -> None:
    t0 = time.time()
    meta = load_meta(p)
    if p.pins.exists():
        meta["pins"] = load_pins(p)

    # reference set
    sciq_ids, sciq_texts, fallback = read_sciq(p.raw / "sciq")
    log(f"SciQ: {len(sciq_ids)} passages ({fallback} used the question fallback)")

    # qrels and queries
    qrels, judged = read_qrels(p.raw / "nq_qrels")
    test_qids = sorted({q for q, _, s in qrels if s > 0})
    qtext: dict[str, str] = {}
    for qid, text in iter_jsonl_or_parquet(query_files(p.raw / "nq"), ["_id", "text"]):
        qtext[str(qid)] = text
    missing_q = [q for q in test_qids if q not in qtext]
    if missing_q:
        sys.exit(f"{len(missing_q)} test query ids have no query text, e.g. {missing_q[:3]}")
    log(f"NQ test: {len(test_qids)} queries, {len(qrels)} judgements, {len(judged)} judged passages")

    # pass 1: corpus ids in file order
    files = corpus_files(p.raw / "nq")
    all_ids: list[str] = [str(i) for (i,) in iter_jsonl_or_parquet(files, ["_id"])]
    total = len(all_ids)
    pos = {rid: k for k, rid in enumerate(all_ids)}
    if len(pos) != total:
        sys.exit("duplicate _id values in the NQ corpus")
    missing = judged - pos.keys()
    if missing:
        sys.exit(f"{len(missing)} judged passages missing from the corpus")
    log(f"NQ corpus: {total} passages")
    if size_big > total:
        sys.exit(f"requested corpus size {size_big} exceeds corpus {total}")

    judged_rows = sorted(pos[c] for c in judged)             # corpus order
    judged_set = set(judged_rows)
    rest = np.fromiter((k for k in range(total) if k not in judged_set), dtype=np.int64,
                       count=total - len(judged_rows))
    seed = sub_seed(*CORPUS_SEED)
    rng = np.random.Generator(np.random.PCG64(seed))
    perm = rng.permutation(rest.shape[0])
    fill = rest[perm[: size_big - len(judged_rows)]]
    order = np.concatenate([np.asarray(judged_rows, dtype=np.int64), fill])
    assert order.shape[0] == size_big and np.unique(order).shape[0] == size_big
    del all_ids, pos

    # pass 2: texts for the selected rows, kept in `order`
    slot = np.full(total, -1, dtype=np.int64)
    slot[order] = np.arange(size_big)
    ids = [""] * size_big
    titles = [""] * size_big
    texts = [""] * size_big
    for k, (rid, title, text) in enumerate(iter_jsonl_or_parquet(files, ["_id", "title", "text"])):
        j = slot[k]
        if j >= 0:
            rid = str(rid)
            check_record_id(rid)
            title = (title or "").strip()
            body = (text or "").strip()
            ids[j] = rid
            titles[j] = title
            texts[j] = f"{title} {body}" if title else body
    if any(not r for r in ids):
        sys.exit("internal error: some selected rows were not filled")

    # non-overlap checks (overview §10.5)
    nq_hashes = {text_hash(t) for t in texts}
    sciq_overlap = sum(1 for t in sciq_texts if text_hash(t) in nq_hashes)
    query_overlap = sum(1 for q in test_qids if text_hash(qtext[q]) in nq_hashes)
    id_overlap = len(set(sciq_ids) & set(ids))
    log(f"overlap: sciq/nq text {sciq_overlap}, query/nq text {query_overlap}, ids {id_overlap}")
    if sciq_overlap or query_overlap or id_overlap:
        sys.exit("split non-overlap check FAILED; nothing written")

    # write
    for d in (p.sciq, p.nq, p.queries):
        d.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"id": sciq_ids, "text": sciq_texts}), p.sciq / "passages.parquet")
    judged_flag = np.zeros(size_big, dtype=bool)
    judged_flag[: len(judged_rows)] = True
    pq.write_table(pa.table({"row": np.arange(size_big), "corpus_index": order, "id": ids,
                             "cohort": titles, "text": texts, "judged": judged_flag}),
                   p.nq / "passages.parquet")
    pq.write_table(pa.table({"query_id": test_qids, "text": [qtext[q] for q in test_qids]}),
                   p.queries / "queries.parquet")
    pq.write_table(pa.table({"query_id": [q for q, _, _ in qrels], "corpus_id": [c for _, c, _ in qrels],
                             "score": [s for _, _, s in qrels]}), p.queries / "qrels_test.parquet")

    meta["build"] = {
        "built_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "sciq": {"passages": len(sciq_ids), "question_fallbacks": fallback,
                 "text_rule": "support, else question", "splits": ["train", "validation", "test"]},
        "nq": {"corpus_total": total, "judged_passages": len(judged_rows), "queries": len(test_qids),
               "judgements": len(qrels), "text_rule": "title + ' ' + text",
               "corpus_seed": {"seed": CORPUS_SEED[0], "label": CORPUS_SEED[1].decode(), "value": seed},
               "rng": "numpy PCG64 permutation of non-judged rows in corpus order",
               "size_big": size_big, "size_small": size_small,
               "small_is_prefix_of_big": True,
               "cohorts_big": len(set(titles)), "cohorts_small": len(set(titles[:size_small]))},
        "non_overlap": {"sciq_vs_nq_text": 0, "queries_vs_nq_text": 0, "ids": 0,
                        "normalisation": "lowercase, collapse whitespace, SHA-256"},
        "seconds": round(time.time() - t0, 1),
    }
    save_meta(p, meta)
    log(f"build complete in {meta['build']['seconds']} s")


# ---------------------------------------------------------------- encode

class STEncoder:
    """The real encoder: sentence-transformers at the pinned revision, on CPU."""

    def __init__(self, repo: str, revision: str, threads: int):
        import torch
        from sentence_transformers import SentenceTransformer
        torch.set_num_threads(threads)
        self.model = SentenceTransformer(repo, revision=revision, device="cpu")
        if int(self.model.max_seq_length) != MAX_TOKENS:
            sys.exit(f"model max_seq_length is {self.model.max_seq_length}, expected {MAX_TOKENS}")
        dim = self.model.get_sentence_embedding_dimension()
        if dim != DIM:
            sys.exit(f"model dimension is {dim}, expected {DIM}")
        self.tok = self.model.tokenizer
        self.versions = _versions()

    def encode(self, texts: list[str]) -> np.ndarray:
        out = self.model.encode(texts, batch_size=BATCH_SIZE, normalize_embeddings=True,
                                convert_to_numpy=True, show_progress_bar=False)
        return np.asarray(out, dtype=np.float32)

    def token_lengths(self, texts: list[str]) -> np.ndarray:
        enc = self.tok(texts, add_special_tokens=True, truncation=False, padding=False)
        return np.fromiter((len(x) for x in enc["input_ids"]), dtype=np.int64, count=len(texts))


class FakeEncoder:
    """Selftest only: deterministic unit vectors from SHA-256, no model, no network."""

    versions = {"encoder": "fake-selftest"}

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.empty((len(texts), DIM), dtype=np.float32)
        for i, t in enumerate(texts):
            seed = int.from_bytes(hashlib.sha256(t.encode()).digest()[:8], "big")
            v = np.random.Generator(np.random.PCG64(seed)).standard_normal(DIM)
            out[i] = (v / np.linalg.norm(v)).astype(np.float32)
        return out

    def token_lengths(self, texts: list[str]) -> np.ndarray:
        return np.fromiter((len(t.split()) + 2 for t in texts), dtype=np.int64, count=len(texts))


def _versions() -> dict:
    v = {"python": sys.version.split()[0], "platform": platform.platform(),
         "machine": platform.machine(), "cpu_count": os.cpu_count()}
    for mod in ("numpy", "pyarrow", "torch", "transformers", "sentence_transformers",
                "huggingface_hub", "tokenizers"):
        try:
            v[mod] = __import__(mod).__version__
        except Exception:
            pass
    return v


def check_rows(emb: np.ndarray, what: str) -> float:
    if emb.ndim != 2 or emb.shape[1] != DIM or emb.dtype != np.float32:
        sys.exit(f"{what}: bad shape/dtype {emb.shape} {emb.dtype}")
    if not np.isfinite(emb).all():
        sys.exit(f"{what}: non-finite values")
    norms = np.sqrt(np.sum(emb.astype(np.float64) ** 2, axis=1))
    dev = float(np.max(np.abs(norms - 1.0))) if len(norms) else 0.0
    if dev > NORM_TOL:
        sys.exit(f"{what}: a vector is not normalised (max |norm-1| = {dev:.3e} > {NORM_TOL:.3e})")
    return dev


def encode_set(enc, texts: list[str], out_dir: Path, name: str, shard_rows: int) -> dict:
    """Encode in resumable shards, then assemble <name>.npy."""
    shard_dir = out_dir / f"{name}_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    n = len(texts)
    shards = (n + shard_rows - 1) // shard_rows
    t0 = time.time()
    done_rows = 0
    for s in range(shards):
        a, b = s * shard_rows, min(n, (s + 1) * shard_rows)
        f = shard_dir / f"{s:04d}.npy"
        side = shard_dir / f"{s:04d}.sha256"
        if f.exists() and side.exists() and side.read_text(encoding="utf-8").strip() == sha256_file(f):
            done_rows += b - a
            continue
        ts = time.time()
        emb = enc.encode(texts[a:b])
        check_rows(emb, f"{name} shard {s}")
        tmp = f.with_suffix(".tmp.npy")
        np.save(tmp, emb, allow_pickle=False)
        os.replace(tmp, f)
        side.write_text(sha256_file(f), encoding="utf-8", newline="\n")
        done_rows += b - a
        rate = (b - a) / max(time.time() - ts, 1e-9)
        eta = (n - done_rows) / max(rate, 1e-9)
        log(f"{out_dir.name}: shard {s + 1}/{shards} ({b - a} rows, {rate:.0f} rows/s, ETA {eta / 3600:.2f} h)")

    final = out_dir / f"{name}.npy"
    mm = np.lib.format.open_memmap(final.with_suffix(".tmp.npy"), mode="w+", dtype="<f4", shape=(n, DIM))
    for s in range(shards):
        a, b = s * shard_rows, min(n, (s + 1) * shard_rows)
        mm[a:b] = np.load(shard_dir / f"{s:04d}.npy")
    mm.flush()
    del mm
    os.replace(final.with_suffix(".tmp.npy"), final)
    arr = np.load(final, mmap_mode="r")
    dev = check_rows(np.asarray(arr), name)
    lengths = np.concatenate([enc.token_lengths(texts[i:i + 4096]) for i in range(0, n, 4096)]) \
        if n else np.zeros(0, dtype=np.int64)
    return {"rows": n, "dim": DIM, "dtype": "float32 little-endian", "file": final.name,
            "sha256_rows": sha256_rows(arr), "max_abs_norm_deviation": dev,
            "truncated_rows": int((lengths > MAX_TOKENS).sum()),
            "truncation_rate": float((lengths > MAX_TOKENS).mean()) if n else 0.0,
            "seconds": round(time.time() - t0, 1)}


def cmd_encode(p: Paths, threads: int, fake: bool = False, shard_rows: int = SHARD_ROWS,
               only: list[str] | None = None) -> None:
    meta = load_meta(p)
    if "build" not in meta:
        sys.exit("run `build` first")
    if fake:
        enc = FakeEncoder()
    else:
        r = load_pins(p)["repos"]["encoder"]
        enc = STEncoder(r["repo_id"], r["revision"], threads)
    sets = {
        "sciq": (p.sciq, "embeddings", lambda: pq.read_table(p.sciq / "passages.parquet").column("text").to_pylist()),
        "queries": (p.queries, "embeddings", lambda: pq.read_table(p.queries / "queries.parquet").column("text").to_pylist()),
        "nq": (p.nq, "embeddings", lambda: pq.read_table(p.nq / "passages.parquet").column("text").to_pylist()),
    }
    meta.setdefault("encode", {})
    meta["encode"]["settings"] = {"model": REPOS["encoder"][0], "max_tokens": MAX_TOKENS, "truncate": True,
                                  "normalize_embeddings": True, "device": "cpu", "batch_size": BATCH_SIZE,
                                  "threads": threads, "shard_rows": shard_rows, "fake": fake}
    meta["encode"]["versions"] = enc.versions
    for key in (only or ["sciq", "queries", "nq"]):
        out_dir, name, loader = sets[key]
        texts = loader()
        log(f"encoding {key}: {len(texts)} texts")
        meta["encode"][key] = encode_set(enc, texts, out_dir, name, shard_rows)
        save_meta(p, meta)
    log("encoding complete")


# ---------------------------------------------------------------- manifest / verify

def manifest_files(p: Paths) -> list[Path]:
    keep = []
    for f in sorted(p.proc.rglob("*")):
        if f.is_file() and "_shards" not in f.parts[-2] and not f.name.endswith((".tmp", ".tmp.npy")):
            keep.append(f)
    if p.pins.exists():
        keep.append(p.pins)
    return keep


def cmd_manifest(p: Paths) -> None:
    lines = [f"{sha256_file(f)}  {f.relative_to(p.datasets).as_posix()}" for f in manifest_files(p)]
    p.manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    log(f"manifest written: {len(lines)} files -> {p.manifest}")


def cmd_verify(p: Paths) -> bool:
    if not p.manifest.exists():
        sys.exit("no manifest; run `encode` (or `manifest`) first")
    bad = 0
    listed = set()
    for line in p.manifest.read_text(encoding="utf-8").splitlines():
        h, rel = line.split("  ", 1)
        listed.add(rel)
        f = p.datasets / rel
        if not f.exists() or sha256_file(f) != h:
            log(f"MISMATCH {rel}")
            bad += 1
    extra = [f.relative_to(p.datasets).as_posix() for f in manifest_files(p)
             if f.relative_to(p.datasets).as_posix() not in listed and f.name != "meta.json"]
    for e in extra:
        log(f"UNLISTED {e}")
    ok = bad == 0 and not extra
    log("verify: OK" if ok else f"verify: FAILED ({bad} mismatches, {len(extra)} unlisted)")
    return ok


# ---------------------------------------------------------------- selftest

def cmd_selftest(tmp_root: Path) -> None:
    """Synthetic raw files in the real formats, a fake encoder, small sizes, full pipeline."""
    import shutil
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    p = Paths(tmp_root)
    rng = np.random.Generator(np.random.PCG64(7))

    # SciQ as parquet, one file per split, one empty support to exercise the fallback
    for split, n in (("train", 30), ("validation", 5), ("test", 5)):
        d = p.raw / "sciq" / "data"
        d.mkdir(parents=True, exist_ok=True)
        sup = [f"science support {split} {i} photosynthesis mitochondria" for i in range(n)]
        if split == "train":
            sup[3] = ""
        pq.write_table(pa.table({"question": [f"what is {split} {i}?" for i in range(n)],
                                 "support": sup, "correct_answer": ["x"] * n}),
                       d / f"{split}-00000-of-00001.parquet")
    # NQ corpus + queries as jsonl.gz, qrels as tsv
    nq = p.raw / "nq"
    nq.mkdir(parents=True, exist_ok=True)
    total = 500
    with gzip.open(nq / "corpus.jsonl.gz", "wt", encoding="utf-8") as fh:
        for k in range(total):
            fh.write(json.dumps({"_id": f"doc{k}", "title": f"Article {k // 7}",
                                 "text": f"wikipedia passage number {k} about topic {rng.integers(0, 50)}"}) + "\n")
    with gzip.open(nq / "queries.jsonl.gz", "wt", encoding="utf-8") as fh:
        for q in range(20):
            fh.write(json.dumps({"_id": f"test{q}", "text": f"who asked question {q}?"}) + "\n")
    qr = p.raw / "nq_qrels"
    qr.mkdir(parents=True, exist_ok=True)
    judged = rng.choice(total, size=25, replace=False)
    with open(qr / "test.tsv", "w", encoding="utf-8") as fh:
        fh.write("query-id\tcorpus-id\tscore\n")
        for i, c in enumerate(judged):
            fh.write(f"test{i % 20}\tdoc{c}\t1\n")

    cmd_build(p, size_big=200, size_small=50)
    cmd_encode(p, threads=1, fake=True, shard_rows=64)
    cmd_manifest(p)
    assert cmd_verify(p), "verify failed on a fresh build"

    meta = load_meta(p)
    t = pq.read_table(p.nq / "passages.parquet")
    ids = t.column("id").to_pylist()
    assert len(ids) == 200 and len(set(ids)) == 200
    jflag = t.column("judged").to_pylist()
    assert sum(jflag) == 25 and all(jflag[:25]) and not any(jflag[25:])
    assert {f"doc{c}" for c in judged} == set(ids[:25])
    assert meta["build"]["sciq"]["question_fallbacks"] == 1
    emb = np.load(p.nq / "embeddings.npy")
    assert emb.shape == (200, DIM) and emb.dtype == np.float32
    assert meta["encode"]["nq"]["sha256_rows"] == sha256_rows(emb)

    # determinism: rebuild into a second root and compare hashes
    first = p.manifest.read_text(encoding="utf-8")
    p2 = Paths(tmp_root / "again")
    shutil.copytree(p.raw, p2.raw)
    cmd_build(p2, size_big=200, size_small=50)
    cmd_encode(p2, threads=1, fake=True, shard_rows=64)
    cmd_manifest(p2)
    strip = lambda s: "\n".join(l for l in s.splitlines() if "meta.json" not in l)
    assert strip(first) == strip(p2.manifest.read_text(encoding="utf-8")), "rebuild is not byte-identical"

    # resumability: delete one shard, re-encode, identical result
    victim = p.nq / "embeddings_shards" / "0001.npy"
    victim.unlink()
    cmd_encode(p, threads=1, fake=True, shard_rows=64, only=["nq"])
    cmd_manifest(p)
    assert strip(first) == strip(p.manifest.read_text(encoding="utf-8")), "resume changed the output"

    # tamper detection
    with open(p.nq / "embeddings.npy", "r+b") as fh:
        fh.seek(-4, 2)
        fh.write(b"\x00\x00\x80\x7f")
    assert not cmd_verify(p), "verify missed a tampered file"

    # sub-seed derivation is stable
    assert sub_seed(42, b"corpus") == int.from_bytes(
        hashlib.sha256(struct.pack(">Q", 42) + b"corpus").digest()[:8], "big")
    log("SELFTEST PASSED")


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["pin", "download", "build", "encode", "manifest", "verify",
                                        "all", "selftest"])
    ap.add_argument("--root", type=Path, default=Path("."), help="project root (contains datasets/)")
    ap.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) // 2),
                    help="torch CPU threads (recorded in meta.json; keep it fixed across reruns)")
    ap.add_argument("--only", nargs="+", choices=["sciq", "queries", "nq"], help="encode only these sets")
    ap.add_argument("--force", action="store_true", help="re-pin revisions (invalidates prior builds)")
    a = ap.parse_args()
    p = Paths(a.root.resolve())

    if a.command == "pin":
        cmd_pin(p, a.force)
    elif a.command == "download":
        cmd_download(p)
    elif a.command == "build":
        cmd_build(p)
    elif a.command == "encode":
        cmd_encode(p, a.threads, only=a.only)
        cmd_manifest(p)
    elif a.command == "manifest":
        cmd_manifest(p)
    elif a.command == "verify":
        sys.exit(0 if cmd_verify(p) else 1)
    elif a.command == "all":
        cmd_pin(p)
        cmd_download(p)
        cmd_build(p)
        cmd_encode(p, a.threads)
        cmd_manifest(p)
        sys.exit(0 if cmd_verify(p) else 1)
    elif a.command == "selftest":
        cmd_selftest(p.root / "_selftest")


if __name__ == "__main__":
    main()
