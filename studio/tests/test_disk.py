"""The disk search can see every form a record could take on disk (C2 of the Studio audit).

Oracle A: §13.2 (a slot's payload holds the record ID, its ``x̃`` and its text) and §4.2
(``x̃_i = round_half_to_even(x_i · 2^24)``, stored as ``i32``). Integers on disk are big-endian
(§0.2); little-endian is searched too. A needle that cannot match ``x̃`` proves nothing about it.
"""

from pathlib import Path

import numpy as np

from sever_studio import tools


def q24(x: np.ndarray) -> np.ndarray:
    return np.rint(x.astype(np.float64) * 2.0**24).astype(np.int64)


def sample(n: int = 40) -> tuple[list[str], list[str], list[np.ndarray]]:
    rng = np.random.default_rng(7)
    vecs = [v / np.linalg.norm(v) for v in rng.normal(size=(n, 16)).astype(np.float32)]
    ids = [f"rec-{i:03d}" for i in range(n)]
    texts = [f"passage number {i} about something long enough to window" for i in range(n)]
    return ids, texts, [v.astype(np.float32) for v in vecs]


def test_studio_disk_needles_find_a_plaintext_quantised_vector(tmp_path: Path) -> None:
    ids, texts, vecs = sample()
    needles = tools.needles_of(ids, texts, vecs)
    for order in (">i4", "<i4"):
        f = tmp_path / f"x{order[0]}.bin"
        f.write_bytes(b"".join(q24(v).astype(order).tobytes() for v in vecs))
        hits = tools.count_hits([f], needles)
        assert hits["x̃ (stored integers)"] == (40, 40), (order, hits)
        assert hits["record IDs"] == (0, 40)


def test_studio_disk_naive_store_holds_every_form(tmp_path: Path) -> None:
    ids, texts, vecs = sample()
    tools.write_naive(tmp_path, ids, texts, vecs)
    hits = tools.count_hits(tools.files_under([tmp_path]), tools.needles_of(ids, texts, vecs))
    assert all(found == n for found, n in hits.values()), hits
