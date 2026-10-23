"""The 2D map: every 384-dimensional vector drawn as a point where its meaning puts it.

The corpus is laid out once with t-SNE (cosine distance), which keeps near neighbours near.
Distances on the map are only an approximation of the real ones, and the window says so; the
layout is cached in the work directory. Groups are not arranged here: a record is drawn at its own
position whatever its group, so a spawned group, a batch of records that waited together (§7.4),
shows as the scattered batch it is (DB-109).

A vector that is not in the corpus (one typed in Studio, a group's centre) is placed at the
similarity-weighted mean position of its nearest corpus neighbours, beside the passages it
resembles.
"""

import hashlib
from pathlib import Path

import numpy as np
import numpy.typing as npt
from sklearn.manifold import TSNE

Coords = npt.NDArray[np.float64]
#: The layout is a picture, not a measurement: a fixed seed only keeps it the same between runs.
LAYOUT_SEED = 42
SPAN = 100.0


def _key(vectors: npt.NDArray[np.float32]) -> str:
    return hashlib.sha256(np.ascontiguousarray(vectors).tobytes()).hexdigest()[:16]


def fit(vectors: npt.NDArray[np.float32], cache: Path | None = None) -> Coords:
    """2D positions for every row, scaled into ``[-SPAN, SPAN]``."""
    path = cache / f"layout-{len(vectors)}-{_key(vectors)}.npy" if cache else None
    if path is not None and path.exists():
        return np.asarray(np.load(path), np.float64)
    n = len(vectors)
    tsne = TSNE(
        n_components=2,
        perplexity=float(min(30, max(5, (n - 1) // 3))),
        metric="cosine",
        init="pca",
        random_state=LAYOUT_SEED,
    )
    xy = np.asarray(tsne.fit_transform(vectors.astype(np.float64)), np.float64)
    xy -= xy.mean(axis=0)
    xy *= SPAN / max(float(np.abs(xy).max()), 1e-9)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, xy)
    return xy


def place(
    vector: npt.NDArray[np.float32],
    vectors: npt.NDArray[np.float32],
    coords: Coords,
    k: int = 8,
) -> tuple[float, float]:
    """A new vector's position: its ``k`` most similar corpus rows, weighted by similarity."""
    sims = vectors.astype(np.float64) @ vector.astype(np.float64)
    near = np.argsort(-sims)[:k]
    w = np.clip(sims[near], 1e-6, None) ** 4
    x, y = (coords[near] * w[:, None]).sum(axis=0) / w.sum()
    return float(x), float(y)
