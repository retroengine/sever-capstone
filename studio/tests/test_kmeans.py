"""How the frozen groups were made: k-means as the partition builder runs it, offline (§6.2).

Oracle A: §6.2 step 1 (k-means runs on x̂ = dequantise(quantise(x)), §4.2–4.3). Oracle B:
scikit-learn's Lloyd run in one go from the same start: stepping it one iteration at a time must
reach the same centres. Oracle E: in the real partition each reference row's colour is its nearest
frozen centre by the engine's own routing code.
"""

from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans

from sever_studio import kmeans

ROOT = Path(__file__).resolve().parents[2]


def test_kmeans_runs_on_the_quantised_reference_rows() -> None:
    run = kmeans.Run(ROOT, "synthetic", k=4, rows=240)
    x = run.raw.astype(np.float64)
    assert np.array_equal(run.xhat, np.rint(x * 2.0**24) / 2.0**24)


def test_kmeans_stepping_reaches_the_one_shot_centres() -> None:
    run = kmeans.Run(ROOT, "synthetic", k=4, rows=240)
    start = run.centres.copy()
    while not run.done:
        run.step()
    one = KMeans(n_clusters=4, init=start, n_init=1, max_iter=300, tol=0, algorithm="lloyd")
    one.fit(run.xhat)
    assert np.allclose(run.centres, one.cluster_centers_, atol=1e-12)
    assert np.array_equal(run.labels, one.labels_)
    assert run.iteration >= 1


def test_kmeans_each_step_assigns_to_the_nearest_centre_then_moves_it_to_the_mean() -> None:
    run = kmeans.Run(ROOT, "synthetic", k=4, rows=240)
    before = run.centres.copy()
    run.step()
    d = ((run.xhat[:, None, :] - before[None]) ** 2).sum(axis=2)
    assert np.array_equal(run.labels, d.argmin(axis=1))
    for j in range(4):
        assert np.allclose(run.centres[j], run.xhat[run.labels == j].mean(axis=0), atol=1e-12)


def test_kmeans_the_real_partition_colours_rows_by_the_engines_nearest_centre() -> None:
    real = kmeans.real_partition(ROOT, "synthetic", rows=240)
    from sever_db_native import Explainer

    e = Explainer((ROOT / "golden/p1_partition_small.svp").read_bytes())
    for i in range(0, 240, 17):
        want = e.route([float(v) for v in real.raw[i]], [], 100, 4)["j_star"]
        assert real.labels[i] == want
    assert real.centres.shape == (4, 16)
