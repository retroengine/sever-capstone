"""EX-6's FAISS arms (P4-T12, overview EX-6): every overview seed builds the IVF index."""

import numpy as np
import pytest

from sever_experiments import ex6


@pytest.mark.parametrize("seed", [42, 123, 777, 2024, 9999])  # Overview §10.6
def test_p4_ex6_the_ivf_arm_takes_every_overview_seed(seed: int) -> None:
    # faiss's ClusteringParameters.seed is a signed 32-bit int. On 30 Oct (the v1.0 laptop run)
    # seed 123's k-means sub-seed reduced mod 2^32 was 3,130,619,076 and the setter raised
    # OverflowError, so P4-T12 failed in its FAISS arm for that seed.
    x = np.random.default_rng(0).standard_normal((64, 8)).astype(np.float32)
    index = ex6._ivf(x, np.arange(64, dtype=np.int64), 4, seed)
    assert index.ntotal == 64
    assert 0 <= index.cp.seed < 2**31
