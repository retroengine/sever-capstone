"""Spec §6.2 step 7: the independent Ledoit–Wolf oracle.

Plain NumPy from the published estimator (Ledoit & Wolf 2004, the shrinkage of their Theorem 1
toward ``m·I``), sharing no code with scikit-learn. With ``X`` centred by its column means and
``S = Xᵀ X / n`` (``assume_centered = False``)::

    m   = tr(S) / p
    d²  = ‖S − m·I‖²_F / p
    b̄²  = (1/n²) Σ_k ‖x_k x_kᵀ − S‖²_F / p  =  (Σ_k ‖x_k‖⁴ / n − ‖S‖²_F) / (n·p)
    b²  = min(b̄², d²)
    shrinkage = b² / d²   (0 when b² = 0)
    Σ*  = shrinkage · m · I + (1 − shrinkage) · S

The closed form for b̄² uses Σ_k x_kᵀ S x_k = n·‖S‖²_F, so no n×p×p array is formed.
"""

import numpy as np
from numpy.typing import NDArray


def ledoit_wolf(x: NDArray[np.float64]) -> tuple[NDArray[np.float64], float]:
    """Returns ``(Σ*, shrinkage)`` for the rows of ``x`` (one observation per row)."""
    n, p = x.shape
    xc = x - x.mean(axis=0)
    s = (xc.T @ xc) / n
    m = float(np.trace(s)) / p
    s_minus = s - m * np.eye(p)
    d2 = float(np.sum(s_minus * s_minus)) / p
    row_sq = np.sum(xc * xc, axis=1)
    b2_bar = (float(np.sum(row_sq * row_sq)) / n - float(np.sum(s * s))) / (n * p)
    b2 = min(b2_bar, d2)
    shrinkage = 0.0 if b2 == 0.0 else b2 / d2
    sigma = shrinkage * m * np.eye(p) + (1.0 - shrinkage) * s
    return sigma, shrinkage
