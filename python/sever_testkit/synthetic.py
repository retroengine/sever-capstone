"""Seeded synthetic vectors (Build §2.7): a clustered "reference" distribution and a shifted "live"
one, so drift and spawning can be forced without downloads.

Rows are normalised in float64 and rounded to float32, as an encoder would deliver them; every row
passes spec §4.1. Seeds feed only data, never keys or nonces (overview §10.6).
"""

import numpy as np
from numpy.typing import NDArray


def _unit_rows(raw: NDArray[np.float64]) -> NDArray[np.float32]:
    """Normalise rows in float64, round once to float32, and re-check §4.1."""
    rows = (raw / np.linalg.norm(raw, axis=1, keepdims=True)).astype(np.float32)
    norms = np.sqrt(np.cumsum(rows.astype(np.float64) ** 2, axis=1)[:, -1])
    assert (np.abs(norms - 1.0) <= 8 * 2.0**-23).all()
    return rows


def clustered(
    n: int, d: int, k: int, seed: int, spread: float = 0.15, shift: float = 0.0
) -> NDArray[np.float32]:
    """``n`` unit rows around ``k`` random unit centres in dimension ``d``.

    ``shift > 0`` moves every centre along a fixed direction (the first axis), giving a "live"
    distribution that sits outside the reference one, so the drift test (§7.2) flags it.
    """
    rng = np.random.Generator(np.random.PCG64(seed))
    centres = rng.standard_normal((k, d))
    centres /= np.linalg.norm(centres, axis=1, keepdims=True)
    if shift:
        centres[:, 0] += shift
    which = rng.integers(0, k, size=n)
    raw = centres[which] + spread * rng.standard_normal((n, d)) / np.sqrt(d)
    return _unit_rows(raw)


def record_ids(n: int, prefix: str = "doc") -> list[str]:
    """Dataset-style IDs (§3.2: never bare integers): ``doc0``, ``doc1``, …"""
    return [f"{prefix}{i}" for i in range(n)]
