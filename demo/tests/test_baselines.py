"""T14 (Overview §1.2): the ghost. Two common ways of deleting leave a trace; SEVER does not.

The SEVER side uses the real Group and the oracle. The float side computes "as if never inserted"
in the test itself: the same running-mean method, run on the survivors only.
"""

import numpy as np

from sever_demo.baselines import FloatRunningMean, ghost_report
from sever_demo.group import Group
from spec_oracle import field_diffs
from synthetic import SEED, D, quantised_rows, unit_rows

N_ROWS = 400
N_DELETED = 100


def deleted_mask() -> np.ndarray:
    rng = np.random.default_rng(SEED)
    mask = np.zeros(N_ROWS, dtype=bool)
    mask[rng.choice(N_ROWS, size=N_DELETED, replace=False)] = True
    return mask


def test_float_baseline_is_not_exact() -> None:
    x = unit_rows(N_ROWS)
    mask = deleted_mask()

    # Float running mean: insert all, delete some ...
    run = FloatRunningMean(D)
    for row in x:
        run.insert(row)
    for row in x[mask]:
        run.delete(row)
    # ... versus the same method if the deleted rows had never arrived.
    never = FloatRunningMean(D)
    for row in x[~mask]:
        never.insert(row)
    assert run.n == never.n
    assert not np.array_equal(run.m, never.m)  # the ghost: not bit-identical


def test_sever_group_is_exact_on_the_same_data() -> None:
    # The same insert/delete sequence on a real Group equals the oracle's survivors-only group.
    q = quantised_rows(N_ROWS)
    vecs = q.tolist()
    mask = deleted_mask()
    g = Group(q)
    for row in range(N_ROWS):
        g.insert(f"doc{row}", row)
    for row in np.flatnonzero(mask):
        g.delete(f"doc{row}", int(row))
    survivors = {f"doc{r}": vecs[r] for r in range(N_ROWS) if not mask[r]}
    assert field_diffs(g, survivors, D) == []


def test_soft_delete_keeps_the_deleted_contribution() -> None:
    # Soft delete only flags records: the summary still includes them, so it differs from the
    # survivors-only summary, computed here from the integers.
    q = quantised_rows(N_ROWS)
    mask = deleted_mask()
    report = ghost_report(unit_rows(N_ROWS), q, mask, np.random.default_rng(SEED), cycles=10)
    survivors_mean = q[~mask].astype(np.int64).sum(axis=0) / ((~mask).sum() * 2.0**24)
    everyone_mean = q.astype(np.int64).sum(axis=0) / (N_ROWS * 2.0**24)
    assert report.soft_still_stored == N_DELETED
    assert np.isclose(report.soft_distance, np.linalg.norm(everyone_mean - survivors_mean))
    assert report.soft_distance > 0
    assert report.sever_max_abs_diff == 0


def test_running_mean_single_record() -> None:
    # Sanity of the baseline itself: one insert gives the vector; deleting it gives zeros, n = 0.
    x = unit_rows(1)[0]
    run = FloatRunningMean(D)
    run.insert(x)
    assert np.array_equal(run.m, x)
    run.delete(x)
    assert run.n == 0
    assert not run.m.any()
