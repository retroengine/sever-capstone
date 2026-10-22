"""The pinned sentence encoder (§3.3) as ONNX: the same model, at the same revision, that made the
dataset's vectors (``datasets/processed/meta.json``), so typed text and stored passages meet in one
space. The files are fetched once and checked by SHA-256 before every use.

The dataset was encoded with sentence-transformers: at most 256 tokens (longer text truncated),
mean pooling over the attention mask, then normalised (``normalize_embeddings=True``). This does
the same; it normalises in float64 and rounds to float32, because the database validates unit
length and never normalises for us (§4.1).
"""

import hashlib
import urllib.request
from pathlib import Path

import numpy as np
import numpy.typing as npt
import onnxruntime as ort
from tokenizers import Tokenizer

REPO = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
NAME = f"{REPO}@{REVISION}"
MAX_TOKENS = 256
#: local name -> (path in the repository at REVISION, SHA-256). model.onnx's hash is its LFS object
#: ID; tokenizer.json's was checked against its git blob ID at REVISION.
FILES = {
    "model.onnx": (
        "onnx/model.onnx",
        "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452",
    ),
    "tokenizer.json": (
        "tokenizer.json",
        "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
    ),
}


class EncoderError(Exception):
    """The encoder files are missing, cannot be fetched, or are not the pinned ones."""


def model_dir(models: Path) -> Path:
    return models / f"all-MiniLM-L6-v2@{REVISION}"


def fetch(models: Path) -> Path:
    """Downloads whatever is missing from the pinned revision and checks every file's hash."""
    where = model_dir(models)
    where.mkdir(parents=True, exist_ok=True)
    for local, (remote, _) in FILES.items():
        path = where / local
        if not path.exists():
            url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{remote}"
            tmp = path.with_suffix(".part")
            try:
                with urllib.request.urlopen(url, timeout=120) as r, tmp.open("wb") as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
            except OSError as e:
                raise EncoderError(f"cannot fetch {remote}: {e}") from None
            tmp.replace(path)
    check(where)
    return where


def check(where: Path) -> None:
    for local, (_, sha) in FILES.items():
        path = where / local
        if not path.exists():
            raise EncoderError(f"missing {path} (run studio/studio.sh setup)")
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise EncoderError(f"{local} is not the pinned file (SHA-256 differs)")


class Encoder:
    """``encode(texts)`` -> float32 unit vectors, one row per text."""

    name = NAME

    def __init__(self, models: Path) -> None:
        where = model_dir(models)
        check(where)
        self.tok = Tokenizer.from_file(str(where / "tokenizer.json"))
        self.tok.enable_truncation(MAX_TOKENS)
        self.tok.enable_padding()
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(where / "model.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        self.inputs = {i.name for i in self.session.get_inputs()}

    def encode(self, texts: list[str]) -> npt.NDArray[np.float32]:
        enc = self.tok.encode_batch(texts)
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
        hidden = np.asarray(self.session.run(None, feed)[0], dtype=np.float64)
        m = mask[:, :, None].astype(np.float64)
        pooled = (hidden * m).sum(axis=1) / np.maximum(m.sum(axis=1), 1e-9)
        unit = pooled / np.linalg.norm(pooled, axis=1, keepdims=True)
        return unit.astype(np.float32)
