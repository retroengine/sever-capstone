"""Two ways of deleting that leave a ghost, run on the same data as SEVER (DEMO_PLAN §5.7).

1. Float running mean: the group keeps an average in float32 and "un-averages" on delete.
2. Soft delete: the record is flagged, but the group's summary keeps its contribution.

Honesty rule: report the measured numbers as they are. The float error is small; the claim is
"not bit-identical", not "huge".
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

F32 = npt.NDArray[np.float32]
F64 = npt.NDArray[np.float64]
I32 = npt.NDArray[np.int32]


class FloatRunningMean:
    """An average kept in float32, updated one record at a time."""

    def __init__(self, d: int) -> None:
        self.m = np.zeros(d, dtype=np.float32)
        self.n = 0

    def insert(self, x: F32) -> None:
        self.n += 1
        self.m = self.m + (x - self.m) / np.float32(self.n)

    def delete(self, x: F32) -> None:
        if self.n == 1:
            self.m = np.zeros_like(self.m)
        else:
            self.m = (self.m * np.float32(self.n) - x) / np.float32(self.n - 1)
        self.n -= 1


def exact_mean(x: F32) -> F64:
    """The survivors-only mean in float64, summed sequentially (fixed order, CLAUDE.md §7)."""
    if x.shape[0] == 0:
        return np.zeros(x.shape[1], dtype=np.float64)
    total: F64 = np.cumsum(x.astype(np.float64), axis=0)[-1]
    mean: F64 = total / x.shape[0]
    return mean


@dataclass
class GhostReport:
    members: int
    deleted: int
    sever_max_abs_diff: int  # integer S after deletes vs S from survivors only
    sever_bit_identical: bool
    float_max_abs_diff: float  # float32 running mean vs exact survivors mean
    float_bit_identical: bool  # vs the same running mean built from survivors only
    float_cycle_error: dict[int, float]  # error after N delete/re-insert cycles
    soft_still_stored: int  # deleted records still inside the soft-delete structure
    soft_distance: float  # L2 distance between soft-delete summary and survivors mean

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def ghost_report(
    x: F32,
    q: I32,
    deleted: npt.NDArray[np.bool_],
    rng: np.random.Generator,
    cycles: int = 1000,
) -> GhostReport:
    """Insert all rows of a group in the given order, delete the `deleted` ones, compare.

    x: the group's float32 vectors in insertion order; q: the same rows quantised (§4.2).
    """
    survivors = ~deleted
    d = x.shape[1]

    # SEVER: integer S, one record at a time, then subtract the deleted ones (§5.3).
    s = np.zeros(d, dtype=np.int64)
    for row in q:
        s += row.astype(np.int64)
    for row in q[deleted]:
        s -= row.astype(np.int64)
    s_survivors = q[survivors].astype(np.int64).sum(axis=0)
    sever_diff = int(np.abs(s - s_survivors).max())

    # Float running mean, insert all then delete, against (a) the same method built from the
    # survivors only and (b) the exact float64 mean of the survivors.
    run = FloatRunningMean(d)
    for row in x:
        run.insert(row)
    for row in x[deleted]:
        run.delete(row)
    never = FloatRunningMean(d)
    for row in x[survivors]:
        never.insert(row)
    truth = exact_mean(x[survivors])
    float_diff = float(np.abs(run.m.astype(np.float64) - truth).max())
    float_same = bool(np.array_equal(run.m, never.m))

    # Error growth: delete a random survivor and insert it again, many times. The true mean
    # never changes, so any movement is pure rounding error.
    checkpoints = {1, 10, 100, 1000, cycles}
    cycle_error: dict[int, float] = {}
    surv_rows = x[survivors]
    for c in range(1, cycles + 1):
        row = surv_rows[int(rng.integers(len(surv_rows)))]
        run.delete(row)
        run.insert(row)
        if c in checkpoints:
            cycle_error[c] = float(np.abs(run.m.astype(np.float64) - truth).max())

    # Soft delete: deleted records are only flagged, so the summary is the mean of everything.
    soft_summary = q.astype(np.int64).sum(axis=0) / (len(q) * 2.0**24)
    soft_distance = float(np.linalg.norm(soft_summary - s_survivors / (survivors.sum() * 2.0**24)))

    return GhostReport(
        members=len(x),
        deleted=int(deleted.sum()),
        sever_max_abs_diff=sever_diff,
        sever_bit_identical=sever_diff == 0,
        float_max_abs_diff=float_diff,
        float_bit_identical=float_same,
        float_cycle_error=cycle_error,
        soft_still_stored=int(deleted.sum()),
        soft_distance=soft_distance,
    )
