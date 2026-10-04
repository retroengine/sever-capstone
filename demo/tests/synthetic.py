"""Small synthetic fixtures (Build §2.7): d = 16, 4 groups, seed 42 (CLAUDE.md §6.2)."""

import numpy as np
import numpy.typing as npt

from sever_demo.quant import quantise

D = 16
K = 4
SEED = 42


def unit_rows(n_rows: int, d: int = D, seed: int = SEED) -> npt.NDArray[np.float32]:
    """n_rows random vectors of length 1, stored as float32 like the real data."""
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n_rows, d))
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    return x.astype(np.float32)


def quantised_rows(n_rows: int, d: int = D, seed: int = SEED) -> npt.NDArray[np.int32]:
    return quantise(unit_rows(n_rows, d, seed))


def record_ids(n_rows: int) -> list[str]:
    return [f"doc{i}" for i in range(n_rows)]
