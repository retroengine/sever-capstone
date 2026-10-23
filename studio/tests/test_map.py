"""The map shows the records where their meaning puts them, and nothing Studio invents (C4, DB-109).

Oracle A: §6.3 (a frozen centre is the artefact's centroid, read again here), §7.5 (a spawned
centre is the one the engine reported), §7.4 (a spawned group is a batch of waiting records, so the
map must not draw it as a cluster). The map is a 2-D picture of 384-D distances: every dot is at its
t-SNE position, whatever its group.
"""

import struct
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from sever_studio import layout
from sever_studio.actions import Studio
from sever_studio.backend import HOLDING
from sever_studio.ui import theme

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def studio(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Studio]:
    work = ROOT / "studio/work" / f"test-map-{tmp_path_factory.getbasetemp().name}"
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    s.fill_bucket("flush")
    yield s
    s.backend.close()
    s.backend.wipe()


def test_map_every_dot_is_where_its_meaning_puts_it(studio: Studio) -> None:
    for rid, rec in studio.backend.index.records.items():
        if rec.group != HOLDING:
            assert studio.xy(rid) == studio.meaning_xy(rid)


def test_map_a_frozen_centre_is_the_partitions_centroid(studio: Studio) -> None:
    raw = studio.corpus.artefact.read_bytes()
    d, k = struct.unpack(">HH", raw[10:14])
    (n,) = struct.unpack(">H", raw[78:80])
    at = 80 + n
    fitted = np.frombuffer(raw[at : at + 8 * k * d], ">f8").reshape(k, d)  # §6.3, label order
    for j in range(k):
        mu = studio.centre(f"frozen-{j:04d}")
        assert mu is not None
        assert np.array_equal(mu, fitted[j])


def test_map_draws_a_centre_for_every_group_the_engine_has(studio: Studio) -> None:
    b = studio.backend
    drawn = {g for g, *_ in studio.centres()}
    engine = {g for g, _ in b.live.group_sizes(b.cid)}
    known = {g for g in engine if studio.centre(g) is not None}
    assert drawn == known
    assert any(g.startswith("spawn-") for g in drawn)


def test_map_each_group_has_its_own_colour(studio: Studio) -> None:
    # oracle: D the owner's ask (23 Oct 2026): every group the engine has is told apart by colour;
    # the bucket keeps its grey
    b = studio.backend
    groups = [g for g, _ in b.group_sizes()] + [f"frozen-{j:04d}" for j in range(128)]
    names = {g: theme.group_colour(g).name() for g in set(groups)}
    assert len(set(names.values())) == len(names)
    assert theme.group_colour(HOLDING).name() == theme.HOLDING


def test_map_3d_has_a_position_for_every_laid_out_row_and_is_kept(studio: Studio) -> None:
    # oracle: D the 3-D picture is t-SNE again with three axes, on the same rows as the 2-D one,
    # kept in the work directory like it
    xyz = studio.layout3()
    assert xyz.shape == (len(studio.coords), 3)
    assert float(np.abs(xyz).max()) <= layout.SPAN + 1e-9
    assert list(studio.work.glob("layout3-*.npy"))
    again = layout.fit(studio.corpus.vectors[: len(studio.coords)], cache=studio.work, dims=3)
    assert np.array_equal(again, xyz)
    for rid in list(studio.backend.index.records)[:20]:
        assert len(studio.xyz(rid)) == 3
    for g, *at, _ in studio.centres3():
        assert len(at) == 3, g
