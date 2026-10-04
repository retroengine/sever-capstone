"""Frozen partition: fit 128 centroids on SciQ, route to the nearest (§6.2 steps 1-2, §7.1).

Demo scope: only the frozen groups. The drift threshold, Ledoit-Wolf and spawning (§6.2 steps 3-7,
§7.2-7.5) are not built, which is the spec's `spawning_enabled = false` configuration (Build §4.3).
"""

import hashlib
import struct

import numpy as np
import numpy.typing as npt
from sklearn.cluster import KMeans

from sever_demo.quant import dequantise, quantise

K_FROZEN = 128  # §6.2


def sub_seed(seed: int, label: bytes) -> int:
    """Overview §10.6: u64 from the first 8 bytes of SHA-256(u64be(seed) || label)."""
    return int.from_bytes(hashlib.sha256(struct.pack(">Q", seed) + label).digest()[:8], "big")


def kmeans_seed(seed: int) -> int:
    # Gap G-1: scikit-learn only accepts seeds below 2^32, so the u64 sub-seed is reduced mod 2^32.
    return sub_seed(seed, b"kmeans") % 2**32


def fit_centroids(
    x_ref: npt.NDArray[np.float32], seed: int, k: int = K_FROZEN
) -> npt.NDArray[np.float64]:
    """§6.2 steps 1-2. Returns the centroids, row j = group frozen-j."""
    # Step 1: fit on exactly the representation the engine routes: quantise, then dequantise.
    x_hat = dequantise(quantise(x_ref))
    # Step 2: the pinned k-means call.
    km = KMeans(
        n_clusters=k,
        init="k-means++",
        n_init=10,
        max_iter=300,
        tol=1e-4,
        algorithm="lloyd",
        random_state=kmeans_seed(seed),
    )
    km.fit(x_hat)
    return np.asarray(km.cluster_centers_, dtype=np.float64)


def route(
    q: npt.NDArray[np.int32], centroids: npt.NDArray[np.float64], chunk_rows: int = 20_000
) -> npt.NDArray[np.int64]:
    """Nearest centroid for each quantised row (§7.1). Ties go to the smaller label.

    Demo shortcut, said openly: distances use ||x||^2 - 2 x.mu + ||mu||^2 with matrix products,
    not §7.1's sequential sum, so a near-tie could be decided differently from the Rust engine.
    Routing is still a pure function of (x̃, centroids) (§7), and exactness does not depend on
    which group a vector lands in.
    """
    c_sq = np.einsum("ij,ij->i", centroids, centroids)
    labels = np.empty(q.shape[0], dtype=np.int64)
    for start in range(0, q.shape[0], chunk_rows):
        x = dequantise(q[start : start + chunk_rows])  # §4.3: float64, exact
        dist = np.einsum("ij,ij->i", x, x)[:, None] - 2.0 * (x @ centroids.T) + c_sq[None, :]
        # argmin returns the first minimum, so ties go to the smaller label.
        labels[start : start + chunk_rows] = np.argmin(dist, axis=1)
    return labels
