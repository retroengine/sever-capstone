"""Index tests (spec §3.2, §3.5, §5.4, §7.1; Build E2E-1.4 / DEMO_PLAN T11).

Which group a record belongs in is decided by the oracle's §7.1 nearest-centroid rule, and what each
group must contain is tracked by the test itself. The index's own helpers are not used as judges.
"""

import numpy as np
import pytest

from sever_demo.errors import DuplicateRecord, InvalidRecordId, Outcome
from sever_demo.index import Index
from sever_demo.partition import route
from spec_oracle import field_diffs, nearest
from synthetic import D, K, quantised_rows, record_ids, unit_rows

N_ROWS = 200


def setup() -> tuple[Index, list[list[int]], list[int]]:
    """An index with doc0..doc199 inserted. Returns it, the vectors, and each row's §7.1 group."""
    vectors = quantised_rows(N_ROWS)
    vecs = vectors.tolist()
    centroids = unit_rows(K, seed=7).astype(np.float64)
    want_group = [nearest(v, centroids.tolist()) for v in vecs]  # §7.1, from the oracle
    index = Index(vectors, record_ids(N_ROWS), route(vectors, centroids), K)
    for rid in record_ids(N_ROWS):
        index.insert(rid)
    return index, vecs, want_group


def expected_members(live: set[int], want_group: list[int], g: int, vecs: list[list[int]]) -> dict:
    return {f"doc{r}": vecs[r] for r in live if want_group[r] == g}


def test_insert_routes_to_nearest_centroid() -> None:
    # §7.1: every record sits in the group of its nearest centroid, and each group holds exactly
    # those records (S, n, members, blob).
    index, vecs, want_group = setup()
    live = set(range(N_ROWS))
    for g in range(K):
        assert field_diffs(index.groups[g], expected_members(live, want_group, g, vecs), D) == []


def test_delete_user_multi_group() -> None:
    # T11 (§3.5, Build E2E-1.4): delete a cohort spread over several groups. Every touched group
    # equals a group of its survivors; every other group is byte-for-byte unchanged.
    index, vecs, want_group = setup()
    blobs_before = [index.groups[g].blob() for g in range(K)]

    cohort_rows = list(range(0, N_ROWS, 7))
    outcomes = index.delete_user([f"doc{r}" for r in cohort_rows])
    assert [o for _, o, _ in outcomes] == [Outcome.DELETED] * len(cohort_rows)

    touched = {want_group[r] for r in cohort_rows}
    assert len(touched) >= 2  # the test means nothing if the cohort sits in one group
    live = set(range(N_ROWS)) - set(cohort_rows)
    for g in range(K):
        if g in touched:
            assert (
                field_diffs(index.groups[g], expected_members(live, want_group, g, vecs), D) == []
            )
        else:
            assert index.groups[g].blob() == blobs_before[g]


def test_delete_user_retry_changes_nothing() -> None:
    # §5.4: retrying a cohort deletion returns AlreadyAbsent for every record and changes nothing.
    index, _, _ = setup()
    cohort = [f"doc{r}" for r in range(0, N_ROWS, 5)]
    index.delete_user(cohort)
    blobs = [index.groups[g].blob() for g in range(K)]
    assert [o for _, o, _ in index.delete_user(cohort)] == [Outcome.ALREADY_ABSENT] * len(cohort)
    assert [index.groups[g].blob() for g in range(K)] == blobs


def test_index_rejects_duplicate_live_id() -> None:
    # §3.2 rule 3, across the whole index.
    index, _, _ = setup()
    blobs = [index.groups[g].blob() for g in range(K)]
    with pytest.raises(DuplicateRecord):
        index.insert("doc5")
    assert [index.groups[g].blob() for g in range(K)] == blobs


def test_index_rejects_invalid_id() -> None:
    # §3.2 rule 2 is checked on every insert.
    index = Index(quantised_rows(2), ["doc0", "007"], np.zeros(2, dtype=np.int64), 1)
    with pytest.raises(InvalidRecordId):
        index.insert("007")
    assert index.groups[0].n == 0


def test_index_rejects_non_unique_dataset_ids() -> None:
    with pytest.raises(ValueError, match="not unique"):
        Index(quantised_rows(2), ["doc0", "doc0"], np.zeros(2, dtype=np.int64), 1)
