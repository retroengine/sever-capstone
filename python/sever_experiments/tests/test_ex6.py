"""EX-6's FAISS arms (P4-T12, overview EX-6): every overview seed builds the IVF index."""

from typing import Any

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


class _Placed:
    def __init__(self, placement: str) -> None:
        self.placement = placement


class _FakeDb:
    """Places records as the engine names them: "holding", or a group ID (`frozen-…`, `spawn-…`)."""

    def __init__(self, placements: list[str]) -> None:
        self.placements = iter(placements)

    def insert(self, cid: object, req: object) -> _Placed:
        return _Placed(next(self.placements))


class _FakeSdk:
    @staticmethod
    def prepare_insert(*args: object) -> None:
        return None


# oracle: A §7.4 (a full holding area moves into one new spawned group, so none of its records
# stays in the holding area); group IDs as the engine names them ("spawn-…", as shape() reads)
@pytest.mark.oracle("A", "§7.4 holding area flush into a new spawned group")
def test_p4_ex6_a_flush_empties_the_tracked_holding_area() -> None:
    e: Any = object.__new__(ex6.Engine)  # fakes stand in for the SDK and the database
    e.sdk, e.cid, e.user = _FakeSdk(), "c", None
    e.holding, e.groups, e.ood, e.inserted = set(), set(), 0, 0
    e.db = _FakeDb(["holding"] * 199 + ["spawn-0001", "frozen-0003", "holding"])
    v = np.zeros(4, dtype=np.float32)
    for i in range(202):
        e.insert(f"r{i}", v)
    assert e.holding == {"r201"}
    assert e.groups == {"spawn-0001"}
