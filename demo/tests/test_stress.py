"""T12 (P1-T1 in miniature): 2,000 seeded operations with the full check after every one.

The test keeps its own record of which records are live and where (§7.1 via the oracle), and after
every operation compares the touched group with the oracle's group of exactly those records.
"""

import numpy as np

from sever_demo.errors import Outcome
from sever_demo.index import Index
from sever_demo.partition import route
from spec_oracle import field_diffs, nearest
from synthetic import SEED, D, K, quantised_rows, record_ids, unit_rows

N_ROWS = 300
N_OPS = 2000


def test_stress_random_ops() -> None:
    vectors = quantised_rows(N_ROWS)
    vecs = vectors.tolist()
    ids = record_ids(N_ROWS)
    centroids = unit_rows(K, seed=7).astype(np.float64)
    want_group = [nearest(v, centroids.tolist()) for v in vecs]
    index = Index(vectors, ids, route(vectors, centroids), K)

    rng = np.random.default_rng(SEED)
    live: set[int] = set()
    for row in rng.permutation(N_ROWS):
        index.insert(ids[row])
        live.add(int(row))

    counts = {"delete": 0, "delete_absent": 0, "reinsert": 0}
    failures: list[tuple[int, str, list[str]]] = []
    for op in range(N_OPS):
        row = int(rng.integers(N_ROWS))
        g = want_group[row]
        if row in live:
            outcome, gid = index.delete(ids[row])
            assert (outcome, gid) == (Outcome.DELETED, g)
            live.remove(row)
            kind = "delete"
        elif rng.random() < 0.5:
            blobs = [index.groups[j].blob() for j in range(K)]
            outcome, _ = index.delete(ids[row])
            assert outcome is Outcome.ALREADY_ABSENT
            assert [index.groups[j].blob() for j in range(K)] == blobs  # §5.4: nothing changed
            kind = "delete_absent"
        else:
            assert index.insert(ids[row]) == g
            live.add(row)
            kind = "reinsert"
        counts[kind] += 1

        want = {ids[r]: vecs[r] for r in live if want_group[r] == g}
        diffs = field_diffs(index.groups[g], want, D)
        if diffs:
            failures.append((op, kind, diffs))

    assert failures == []
    assert min(counts.values()) > 100  # every kind of operation really happened
    assert sum(index.groups[j].n for j in range(K)) == len(live)


def test_stress_with_commitments() -> None:
    # Part 3 preview: 600 seeded operations with commitments on. After every operation the touched
    # group matches the oracle on all five fields (§5.5), and every deletion's certificate verifies.
    from sever_verify.certificate import verify
    from spec_oracle import committed_field_diffs

    n_rows, n_ops = 120, 600
    vectors = quantised_rows(n_rows)
    vecs = vectors.tolist()
    ids = record_ids(n_rows)
    centroids = unit_rows(K, seed=7).astype(np.float64)
    want_group = [nearest(v, centroids.tolist()) for v in vecs]
    index = Index(vectors, ids, route(vectors, centroids), K)
    for rid in ids:
        index.insert(rid)
    index.enable_commitments()
    blinding = index.groups[0].blinding
    assert blinding is not None
    anchors = index.anchors()

    rng = np.random.default_rng(SEED)
    live = set(range(n_rows))
    failures: list[tuple[int, list[str]]] = []
    certs = 0
    for op in range(n_ops):
        row = int(rng.integers(n_rows))
        g = want_group[row]
        if row in live:
            index.delete(ids[row])
            live.remove(row)
            assert index.last_certificate is not None
            assert verify(index.last_certificate, anchors).accepted
            certs += 1
        else:
            index.insert(ids[row])
            live.add(row)
        want = {ids[r]: vecs[r] for r in live if want_group[r] == g}
        diffs = committed_field_diffs(index.groups[g], want, {ids[r]: blinding[r] for r in live}, D)
        if diffs:
            failures.append((op, diffs))
    assert failures == []
    assert certs > 100
