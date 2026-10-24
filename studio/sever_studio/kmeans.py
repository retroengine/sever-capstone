"""How the frozen groups were made: the partition builder's k-means (C-15, §6.2), step by step.

This is the **offline build step**, not the database: the engine never runs k-means (§6.1). The
frozen partition was fitted once on a public reference set, SciQ's science passages (the offline
fixture's 240 vectors here), and only its result, the artefact, reaches the engine.

``Run`` repeats it small enough to watch: the rows are quantised and dequantised with C-15's own
``sever_partition.arith`` (§6.2 step 1), the start is scikit-learn's k-means++ (C-15's ``init``),
then each ``step`` is Lloyd's two halves made visible: every row joins its nearest centre, then
every centre moves to its rows' mean. The test proves stepping reaches scikit-learn's own Lloyd
result. ``real_partition`` shows the 128 centres the engine actually uses, each row coloured by its
nearest centre as the engine's routing code finds it (DB-108).

The 2-D picture is one PCA of the rows, fixed for the whole run, so a moving centre visibly moves;
every distance is measured in all ``d`` dimensions.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt
from sever_partition import arith
from sklearn.cluster import kmeans_plusplus

from .corpus import FIXTURE_VECTORS

F64 = npt.NDArray[np.float64]
SCIQ = "datasets/processed/sciq_reference/embeddings.npy"
#: The partition builder's iteration cap (§6.2 step 2).
MAX_ITER = 300


def reference(root: Path, data: str, rows: int) -> npt.NDArray[np.float32]:
    """The first ``rows`` reference rows: SciQ's (NQ data) or the fixture's own."""
    if data == "synthetic":
        doc = json.loads((root / FIXTURE_VECTORS).read_text("utf-8"))
        raw = b"".join(bytes.fromhex(h) for h in doc["ref"] + doc["live"])
        x = np.frombuffer(raw, dtype="<f4").reshape(-1, 16)
    else:
        x = np.load(root / SCIQ, mmap_mode="r")
    return np.asarray(x[:rows], np.float32)


def _projection(xhat: F64) -> tuple[F64, F64]:
    """The mean and the top two principal directions of the rows."""
    mean = xhat.mean(axis=0)
    _, _, vt = np.linalg.svd(xhat - mean, full_matrices=False)
    return mean, vt[:2]


@dataclass
class Partition:
    raw: npt.NDArray[np.float32]
    xhat: F64
    centres: F64
    labels: npt.NDArray[np.int64]
    mean: F64 = field(default_factory=lambda: np.zeros(0))
    axes: F64 = field(default_factory=lambda: np.zeros((2, 0)))

    def project(self, v: F64) -> F64:
        out: F64 = (v - self.mean) @ self.axes.T
        return out

    @property
    def xy(self) -> F64:
        return self.project(self.xhat)

    @property
    def centres_xy(self) -> F64:
        return self.project(self.centres)


class Run(Partition):
    """k-means on ``rows`` reference rows with ``k`` centres, one Lloyd step at a time."""

    def __init__(self, root: Path, data: str, k: int, rows: int, seed: int = 42) -> None:
        raw = reference(root, data, rows)
        xhat = arith.dequantise(arith.quantise(raw))  # §6.2 step 1, C-15's own code
        centres, _ = kmeans_plusplus(xhat, k, random_state=seed)
        mean, axes = _projection(xhat)
        super().__init__(raw, xhat, np.asarray(centres, np.float64), self._nearest(xhat, centres))
        self.mean, self.axes = mean, axes
        self.iteration = 0
        self.done = False
        self.trail: list[F64] = [self.centres_xy.copy()]
        self.inertia = self._inertia()

    @staticmethod
    def _nearest(xhat: F64, centres: F64) -> npt.NDArray[np.int64]:
        d = ((xhat[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
        out: npt.NDArray[np.int64] = d.argmin(axis=1)
        return out

    def _inertia(self) -> float:
        return float(((self.xhat - self.centres[self.labels]) ** 2).sum())

    def step(self) -> None:
        """Assignment, then update; ``done`` when no row changed centre (or §6.2's 300 steps)."""
        labels = self._nearest(self.xhat, self.centres)
        centres = self.centres.copy()
        for j in range(len(centres)):
            members = self.xhat[labels == j]
            if len(members):
                centres[j] = members.mean(axis=0)
        self.done = (self.iteration > 0 and np.array_equal(labels, self.labels)) or (
            self.iteration + 1 >= MAX_ITER
        )
        self.labels, self.centres = labels, centres
        self.iteration += 1
        self.inertia = self._inertia()
        self.trail.append(self.centres_xy.copy())


def real_partition(root: Path, data: str, rows: int) -> Partition:
    """The partition the engine uses: the artefact's centres, each reference row coloured by its
    nearest one as the engine's routing code finds it (§7.1, DB-108)."""
    from sever_db import Explainer

    artefact = (
        root / "golden/p1_partition_small.svp"
        if data == "synthetic"
        else root / "artefacts/partition-seed42.svp"
    )
    e = Explainer(artefact.read_bytes())
    raw = reference(root, data, rows)
    xhat = arith.dequantise(arith.quantise(raw))
    centres = np.asarray(e.frozen_centroids(), np.float64)
    labels = np.array([e.route([float(v) for v in x], [], 1, 1)["j_star"] for x in raw], np.int64)
    mean, axes = _projection(xhat)
    return Partition(raw, xhat, centres, labels, mean, axes)


def separated(rows: list[tuple[str, str, float, float]]) -> dict[str, tuple[int, int]]:
    """``Studio.separation``'s rows counted by kind of group: ``(records, nearer their own centre
    than any other)``. A k-means cluster's records are nearer their own centre; a spawned group's,
    a batch of records that waited together (§7.4), mostly are not."""
    out: dict[str, tuple[int, int]] = {}
    for kind in ("frozen", "spawn"):
        mine = [(own, other) for _, g, own, other in rows if g.startswith(kind)]
        out[kind] = (len(mine), sum(own < other for own, other in mine))
    return out
