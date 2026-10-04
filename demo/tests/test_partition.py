"""Partition and routing tests (spec §6.2 steps 1-2, §7.1; Overview §10.6; gap G-1)."""

import hashlib

import numpy as np
from sklearn.cluster import KMeans

from sever_demo.partition import fit_centroids, kmeans_seed, route, sub_seed
from spec_oracle import nearest
from synthetic import K, quantised_rows, unit_rows


def test_sub_seed_follows_overview_10_6() -> None:
    # Overview §10.6, written out here: first 8 bytes of SHA-256(u64be(seed) || label), as a u64.
    for seed in [42, 123, 777, 2024, 9999]:
        for label in [b"kmeans", b"stream", b"cohort-order"]:
            digest = hashlib.sha256(seed.to_bytes(8, "big") + label).digest()
            assert sub_seed(seed, label) == int.from_bytes(digest[:8], "big")


def test_kmeans_seed_is_sub_seed_mod_2_32() -> None:
    # Gap G-1: scikit-learn needs a seed below 2^32; the decision is "sub-seed mod 2^32".
    for seed in [42, 123, 777, 2024, 9999]:
        digest = hashlib.sha256(seed.to_bytes(8, "big") + b"kmeans").digest()
        assert kmeans_seed(seed) == int.from_bytes(digest[:8], "big") % 2**32


def test_fit_centroids_uses_the_pinned_kmeans() -> None:
    # §6.2 step 1: fit on quantised-then-dequantised rows (written out here, not via quant.py).
    # §6.2 step 2: the pinned KMeans call, with the spec's parameters written out here.
    x = unit_rows(400)
    x_hat = np.rint(x.astype(np.float64) * 2**24) / 2**24
    digest = hashlib.sha256((42).to_bytes(8, "big") + b"kmeans").digest()
    km = KMeans(
        n_clusters=K,
        init="k-means++",
        n_init=10,
        max_iter=300,
        tol=1e-4,
        algorithm="lloyd",
        random_state=int.from_bytes(digest[:8], "big") % 2**32,
    ).fit(x_hat)
    assert np.array_equal(fit_centroids(x, seed=42, k=K), km.cluster_centers_)


def test_route_ties_go_to_smaller_label() -> None:
    # §7.1: x = e0 is exactly as far from e1 as from e2 (distance^2 = 2, computed exactly).
    q = np.zeros((1, 16), dtype=np.int32)
    q[0, 0] = 2**24  # x̂ = 1.0
    centroids = np.zeros((3, 16))
    centroids[0, 3] = 5.0  # far away
    centroids[1, 1] = 1.0
    centroids[2, 2] = 1.0
    assert route(q, centroids).tolist() == [1]
    assert route(q, centroids[[0, 2, 1]]).tolist() == [1]
    assert nearest(q[0].tolist(), centroids.tolist()) == 1  # the oracle agrees


def test_route_matches_sequential_distance() -> None:
    # The demo's fast matrix form must pick the same group as §7.1's sequential float64 sum.
    q = quantised_rows(300)
    centroids = unit_rows(K, seed=7).astype(np.float64)
    want = [nearest(row, centroids.tolist()) for row in q.tolist()]
    assert route(q, centroids, chunk_rows=64).tolist() == want


def test_route_is_a_pure_function() -> None:
    # §7: the same (x̃, state) always gives the same group, whatever else is routed with it.
    q = quantised_rows(50)
    centroids = unit_rows(K, seed=7).astype(np.float64)
    together = route(q, centroids)
    alone = [int(route(q[i : i + 1], centroids)[0]) for i in range(50)]
    assert together.tolist() == alone
    assert route(q[::-1], centroids).tolist() == together.tolist()[::-1]
