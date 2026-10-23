"""Routing as the engine computes it, beside where the engine put each record (H4, H5; DB-108).

Oracle E: the engine's own placement (the receipt). Oracle A: §4.2 and §7.1–7.2 worked again here
with sequential float64 sums (``np.cumsum(...)[..., -1]``, CLAUDE.md §7), bit for bit.
"""

import struct
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from sever_studio.actions import Studio
from sever_studio.backend import HOLDING

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def studio(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Studio]:
    work = ROOT / "studio/work" / f"test-routing-{tmp_path_factory.getbasetemp().name}"
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    yield s
    s.backend.close()
    s.backend.wipe()


def artefact(path: Path) -> tuple[np.ndarray, np.ndarray, float]:
    """§6.3, read again: centroids, P and τ."""
    raw = path.read_bytes()
    d, k = struct.unpack(">HH", raw[10:14])
    (tau,) = struct.unpack(">d", raw[22:30])
    at = 30 + 8 + 8 + 32
    (n,) = struct.unpack(">H", raw[at : at + 2])
    at += 2 + n
    mu = np.frombuffer(raw[at : at + 8 * k * d], ">f8").reshape(k, d).astype(np.float64)
    at += 8 * k * d
    p = np.frombuffer(raw[at : at + 8 * d * d], ">f8").reshape(d, d).astype(np.float64)
    return mu, p, tau


def test_studio_every_prediction_equals_the_engines_placement(studio: Studio) -> None:
    b = studio.backend
    before = b.routing_checked
    studio.ensure_spares(1_000)
    for _ in range(1_000):
        i = b.index.loaded
        b.insert(studio.corpus.ids[i], studio.corpus.vectors[i], studio.corpus.accounts[i])
        b.index.loaded = i + 1
    assert b.routing_checked - before == 1_000
    assert b.routing_disagreed == []
    placements = {rec.group[:6] for rec in b.index.records.values()}
    assert {"frozen", "spawn-", HOLDING[:6]} <= placements | {HOLDING[:6]}
    studio.clusters()
    studio.fill_bucket("one")
    assert studio.checklist.ticked("routing")


def test_studio_why_a_record_is_where_it_is_is_the_specs_arithmetic(studio: Studio) -> None:
    mu, p, tau = artefact(studio.corpus.artefact)
    b = studio.backend
    for rid, rec in list(b.index.records.items())[:200]:
        x = b.vector_of(rid)
        xhat = np.rint(x.astype(np.float64) * 2.0**24) / 2.0**24
        d = np.cumsum((xhat[None, :] - mu) ** 2, axis=1)[:, -1]
        j = int(np.argmin(d))
        delta = xhat - mu[j]
        dm = float(np.sqrt(np.cumsum(delta * np.cumsum(p * delta[None, :], axis=1)[:, -1])[-1]))
        why = studio.why(rid)
        assert why is not None
        assert why["j_star"] == j
        assert why["nearest"][0][1] == d[j]
        assert why["d_m"] == dm
        assert why["tau"] == tau
        assert (rec.group.startswith("frozen-")) == (dm <= tau)
