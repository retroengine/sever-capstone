"""The map by group (``layout.GroupMap``): what a reviewer should be able to rely on by eye.

The expected values are geometric rules, not numbers taken from the code: two discs that overlap
would mix two groups' colours; two groups with one colour could not be told apart; a group or a dot
that moved between runs would make the map lie about what changed.
"""

import math
import random
import shutil
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from conftest import WORK

from sever_studio import layout
from sever_studio.actions import Studio
from sever_studio.backend import HOLDING

ROOT = Path(__file__).resolve().parents[2]


def fake_members(frozen: int, spawned: int, seed: int) -> dict[str, list[tuple[float, float]]]:
    """Groups as ``Studio.place_groups`` hands them over: frozen groups of 3-40 members bunched by
    meaning, spawned groups of members from anywhere."""
    rng = random.Random(seed)
    out: dict[str, list[tuple[float, float]]] = {}
    for g in range(frozen):
        cx, cy = rng.uniform(-80, 80), rng.uniform(-80, 80)
        out[f"frozen-{g:04d}"] = [
            (cx + rng.gauss(0, 4), cy + rng.gauss(0, 4)) for _ in range(rng.randint(3, 40))
        ]
    for k in range(spawned):
        out[f"spawn-{k:016x}"] = [(rng.uniform(-99, 99), rng.uniform(-99, 99)) for _ in range(8)]
    return out


def overlaps(gm: layout.GroupMap) -> list[tuple[str, str]]:
    a = list(gm.anchors.items())
    return [
        (g, h)
        for i, (g, (x, y, r)) in enumerate(a)
        for h, (u, v, s) in a[i + 1 :]
        if math.hypot(x - u, y - v) < r + s - 1e-6
    ]


@pytest.mark.parametrize(("frozen", "spawned"), [(4, 3), (128, 43), (30, 0), (1, 60)])
def test_map_discs_never_overlap_and_colours_never_repeat(
    tmp_path: Path, frozen: int, spawned: int
) -> None:
    gm = layout.GroupMap(tmp_path / "g.json", spawn_size=8)
    members = fake_members(frozen, spawned, seed=frozen)
    assert gm.ensure(members)
    assert set(gm.anchors) == set(members)
    assert overlaps(gm) == []
    assert len(set(gm.colours.values())) == len(members)
    rgb = [layout.palette_rgb(i) for i in gm.colours.values()]
    assert len(set(rgb)) == len(rgb)  # different numbers, different colours


def test_map_neighbouring_groups_look_clearly_different(tmp_path: Path) -> None:
    gm = layout.GroupMap(tmp_path / "g.json", spawn_size=200)
    gm.ensure(fake_members(128, 43, seed=7))
    lab = {g: layout._lab(layout.palette_rgb(c)) for g, c in gm.colours.items()}
    worst = math.inf
    for g, (x, y, r) in gm.anchors.items():
        for h, (u, v, s) in gm.anchors.items():
            if g < h and math.hypot(x - u, y - v) < r + s + 3 * layout.GAP:  # touching, nearly
                worst = min(worst, float(((lab[g] - lab[h]) ** 2).sum() ** 0.5))
    assert worst > 20  # ΔE*ab above ~10 reads as a different colour at a glance


def test_map_places_and_colours_are_kept(tmp_path: Path) -> None:
    path = tmp_path / "g.json"
    members = fake_members(10, 4, seed=3)
    first = layout.GroupMap(path, spawn_size=8)
    first.ensure(members)
    again = layout.GroupMap(path, spawn_size=8)  # the next run
    assert again.anchors == first.anchors
    assert again.colours == first.colours
    assert not again.ensure(members)
    later = {**members, "spawn-new": [(0.0, 0.0)] * 8, "frozen-0099": [(5.0, 5.0)] * 6}
    assert again.ensure(later)  # a flush and a group that was empty before
    for g in members:
        assert again.anchors[g] == first.anchors[g]
        assert again.colours[g] == first.colours[g]
    assert overlaps(again) == []
    assert len(set(again.colours.values())) == len(later)


def test_map_a_member_is_drawn_inside_its_group_and_never_moves(tmp_path: Path) -> None:
    gm = layout.GroupMap(tmp_path / "g.json", spawn_size=8)
    members = fake_members(6, 2, seed=11)
    gm.ensure(members)
    for g, pts in members.items():
        cx, cy, r = gm.anchors[g]
        for pt in [*pts, (500.0, -500.0)]:  # a later member far away is kept inside too
            x, y = gm.point(g, pt)
            assert math.hypot(x - cx, y - cy) <= r + 1e-9
            assert gm.point(g, pt) == (x, y)


def test_map_outline_holds_every_point() -> None:
    rng = random.Random(5)
    pts = np.array([(rng.gauss(0, 3), rng.gauss(0, 3)) for _ in range(60)])
    ring = layout.outline(pts, pad=1.0)
    assert np.allclose(ring[0], ring[-1])  # closed
    poly = ring[:-1]
    for x, y in pts:  # inside a convex polygon: on the left of every edge (counter-clockwise)
        for (ax, ay), (bx, by) in zip(poly, np.roll(poly, -1, axis=0), strict=True):
            assert (bx - ax) * (y - ay) - (by - ay) * (x - ax) >= 0


# -- on a real (fixture) database --------------------------------------------------------------


@pytest.fixture
def studio() -> Iterator[Studio]:
    work = WORK / "test-map"
    shutil.rmtree(work, ignore_errors=True)
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    yield s
    s.backend.close()
    shutil.rmtree(work, ignore_errors=True)


def test_map_every_record_sits_in_its_own_groups_disc(studio: Studio) -> None:
    studio.fill_bucket("flush")
    recs = studio.backend.index.records
    for rid, rec in recs.items():
        if rec.group == HOLDING:
            continue
        x, y = studio.xy(rid)
        cx, cy, r = studio.groups.anchors[rec.group]
        assert math.hypot(x - cx, y - cy) <= r + 1e-9, rid
    groups = {rec.group for rec in recs.values() if rec.group != HOLDING}
    assert {g for g, *_ in studio.centres()} == groups
    assert len({studio.groups.colours[g] for g in groups}) == len(groups)


def test_map_a_deletion_moves_nothing_else(studio: Studio) -> None:
    recs = studio.backend.index.records
    before = {r: studio.xy(r) for r, rec in recs.items() if rec.group != HOLDING}
    anchors = dict(studio.groups.anchors)
    gone = sorted(before)[5]
    studio.delete([gone])
    after = {r: studio.xy(r) for r, rec in recs.items() if rec.group != HOLDING}
    assert gone not in after
    assert all(after[r] == before[r] for r in after)
    assert studio.groups.anchors == anchors


def test_map_by_meaning_is_still_there(studio: Studio) -> None:
    rid = next(r for r, rec in studio.backend.index.records.items() if rec.group != HOLDING)
    studio.by_group = False
    assert studio.xy(rid) == studio.meaning_xy(rid)


def test_map_a_frozen_centre_is_the_partitions_centroid(studio: Studio) -> None:
    from sever_partition.artefact import decode

    fitted = decode(studio.corpus.artefact.read_bytes()).centroids  # §6.3, label order
    mu = studio.centre("frozen-0002")
    assert mu is not None
    assert np.array_equal(mu, fitted[2])
    rid = next(r for r, rec in studio.backend.index.records.items() if rec.group == "frozen-0002")
    x = studio.backend.vector_of(rid).astype(np.float64)
    own, _ = studio.distances(rid) or (0.0, 0.0)
    assert own == pytest.approx(float(np.sqrt(((x - fitted[2]) ** 2).sum())))
