"""Are the groups clusters? Measured in all 384 dimensions, not on a picture.

For a stored record, its own group's centre against the nearest other centre, both as §8.1 step 1
ranks groups (the engine's search code, DB-108). Oracle A: §8.1 step 1, D_g = Σ((f64)q_i − μ_g,i)²
with a sequential sum, worked again here with ``np.cumsum``; the centres are the partition's
(§6.3) and the engine's reported ones (§7.5).
"""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from sever_studio import kmeans
from sever_studio.actions import Studio

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def studio(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Studio]:
    work = ROOT / "studio/work" / f"test-clusters-{tmp_path_factory.getbasetemp().name}"
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    s.fill_bucket("flush")
    yield s
    s.backend.close()
    s.backend.wipe()


def test_clusters_each_distance_is_section_8_1s_d(studio: Studio) -> None:
    rows = studio.separation(per_group=3)
    mus = {g: studio.centre(g) for g, _ in studio.backend.group_sizes()}
    for rid, g, own, other in rows:
        q = studio.backend.vector_of(rid).astype(np.float64)
        d = {h: float(np.cumsum((q - mu) ** 2)[-1]) for h, mu in mus.items() if mu is not None}
        assert own == d[g], rid
        assert other == min(v for h, v in d.items() if h != g), rid
    kinds = {g.split("-")[0] for _, g, _, _ in rows}
    assert kinds == {"frozen", "spawn"}


def test_clusters_samples_every_group_with_members_at_most_per_group(studio: Studio) -> None:
    rows = studio.separation(per_group=2)
    sizes = dict(studio.backend.group_sizes())
    by: dict[str, int] = {}
    for _, g, _, _ in rows:
        by[g] = by.get(g, 0) + 1
    for g, n in sizes.items():
        if n and studio.centre(g) is not None:
            assert by.get(g, 0) == min(2, n), g


def test_clusters_the_summary_counts_records_nearer_their_own_centre(studio: Studio) -> None:
    # oracle: D counting: a record is nearer its own centre when its D_own < its D_other
    rows = studio.separation(per_group=4)
    summary = kmeans.separated(rows)
    for kind in ("frozen", "spawn"):
        mine = [(own, other) for _, g, own, other in rows if g.startswith(kind)]
        assert summary[kind] == (len(mine), sum(own < other for own, other in mine))
