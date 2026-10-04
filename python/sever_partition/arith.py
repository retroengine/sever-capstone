"""Spec §4 arithmetic and the §7.2 distance, in the pinned float orders, written from the spec.

Only ``np.cumsum(...)[..., -1]`` is used for sums whose order the spec pins: it adds strictly left
to right. ``np.sum`` and ``@`` use pairwise or blocked orders and are never used for these values
(CLAUDE.md §7, "Floats").
"""

from typing import Final

import numpy as np
from numpy.typing import NDArray

#: §2.2: 2^24.
SCALE: Final = float(1 << 24)
#: §2.2, §4.1: 8 float32 ULPs at 1.0.
NORM_TOLERANCE: Final = 8.0 * 2.0**-23


class NotNormalisedError(ValueError):
    """§4.1 failed for some row (the message never names the row's values, §17)."""


class IntegrityViolationError(ArithmeticError):
    """§7.2: ``q < 0``, impossible for a positive-definite precision matrix."""


def check_rows_normalised(x: NDArray[np.float32]) -> None:
    """§4.1 steps 1–3 for every row: finite, and the sequential float64 norm within 8 ULPs of 1."""
    if x.dtype != np.float32 or x.ndim != 2:
        raise NotNormalisedError("expected a 2-D float32 array")
    if not np.isfinite(x).all():
        raise NotNormalisedError("non-finite component")
    x64 = x.astype(np.float64)
    norms = np.sqrt(np.cumsum(x64 * x64, axis=1)[:, -1])  # §4.1 step 2: sequential from i = 0
    if not (np.abs(norms - 1.0) <= NORM_TOLERANCE).all():
        raise NotNormalisedError("row not normalised")


def quantise(x: NDArray[np.float32]) -> NDArray[np.int32]:
    """§4.2: round_half_to_even((f64)x · 2^24) as int32. ``np.round`` rounds half to even."""
    q = np.round(x.astype(np.float64) * SCALE)
    return q.astype(np.int32)


def dequantise(q: NDArray[np.int32]) -> NDArray[np.float64]:
    """§4.3: x̂ = x̃ / 2^24 in float64 (exact)."""
    return q.astype(np.float64) / SCALE


def mahalanobis(
    xhat: NDArray[np.float64],
    centroids: NDArray[np.float64],
    precision: NDArray[np.float64],
    chunk: int = 32,
) -> NDArray[np.float64]:
    """§7.2 for each row of ``xhat`` against its own centroid row, in the pinned order.

    δ = x̂ − μ; y_a = Σ_b P[a][b]·δ_b sequential in b; q = Σ_a δ_a·y_a sequential in a;
    d_M = sqrt(q). Products and sums are separate float64 operations (no fused multiply-add).
    """
    n, d = xhat.shape
    out = np.empty(n, dtype=np.float64)
    for start in range(0, n, chunk):
        delta = xhat[start : start + chunk] - centroids[start : start + chunk]
        # terms[r, a, b] = P[a][b] * δ_b ; cumsum over b is the sequential sum.
        terms = precision[np.newaxis, :, :] * delta[:, np.newaxis, :]
        y = np.cumsum(terms, axis=2)[:, :, -1]
        q = np.cumsum(delta * y, axis=1)[:, -1]
        if (q < 0).any():
            raise IntegrityViolationError("q < 0 (§7.2)")
        out[start : start + chunk] = np.sqrt(q)
    assert out.shape == (n,)
    assert d == precision.shape[0]
    return out
