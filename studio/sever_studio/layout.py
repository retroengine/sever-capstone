"""The 2D map: every 384-dimensional vector drawn as a point, in two layouts.

**By group** (the default): each group is a disc of its own colour around its centre, so the map
shows what the database stores. Frozen groups sit in the middle, roughly where their passages sit
by meaning and pushed apart so none overlap; spawned groups take the next place on rings around
them, in the order they appear. Each group keeps its place and colour once given (``GroupMap``,
saved in the work directory), and each record keeps its spot in the disc (a hash of its ID).

**By meaning**: the corpus is laid out once with t-SNE (cosine distance), which keeps near
neighbours near. Distances on the map are only an approximation of the real ones; the window says
so. The layout is cached in the work directory.

A vector that is not in the corpus (one typed in Studio) is placed at the similarity-weighted mean
position of its nearest corpus neighbours, which puts it beside the passages it resembles.
"""

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import numpy.typing as npt
from sklearn.manifold import TSNE

Coords = npt.NDArray[np.float64]
#: The layout is a picture, not a measurement: a fixed seed only keeps it the same between runs.
LAYOUT_SEED = 42
SPAN = 100.0


def _key(vectors: npt.NDArray[np.float32]) -> str:
    return hashlib.sha256(np.ascontiguousarray(vectors).tobytes()).hexdigest()[:16]


def fit(vectors: npt.NDArray[np.float32], cache: Path | None = None) -> Coords:
    """2D positions for every row, scaled into ``[-SPAN, SPAN]``."""
    path = cache / f"layout-{len(vectors)}-{_key(vectors)}.npy" if cache else None
    if path is not None and path.exists():
        return np.asarray(np.load(path), np.float64)
    n = len(vectors)
    tsne = TSNE(
        n_components=2,
        perplexity=float(min(30, max(5, (n - 1) // 3))),
        metric="cosine",
        init="pca",
        random_state=LAYOUT_SEED,
    )
    xy = np.asarray(tsne.fit_transform(vectors.astype(np.float64)), np.float64)
    xy -= xy.mean(axis=0)
    xy *= SPAN / max(float(np.abs(xy).max()), 1e-9)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, xy)
    return xy


def place(
    vector: npt.NDArray[np.float32],
    vectors: npt.NDArray[np.float32],
    coords: Coords,
    k: int = 8,
) -> tuple[float, float]:
    """A new vector's position: its ``k`` most similar corpus rows, weighted by similarity."""
    sims = vectors.astype(np.float64) @ vector.astype(np.float64)
    near = np.argsort(-sims)[:k]
    w = np.clip(sims[near], 1e-6, None) ** 4
    x, y = (coords[near] * w[:, None]).sum(axis=0) / w.sum()
    return float(x), float(y)


# -- by group ----------------------------------------------------------------------------------

#: A disc's radius is SPREAD · √(its capacity), in map units; GAP keeps discs apart.
SPREAD = 1.0
GAP = 2.0
#: The frozen discs fill this share of the circle they are packed in.
PACKING = 0.45


def palette_rgb(index: int, light: bool = True) -> tuple[int, int, int]:
    """Colour number ``index``: hues a golden angle apart, in three shades, so no two numbers give
    the same colour and consecutive numbers look far apart."""
    h = (index * 0.618033988749895) % 1.0
    if light:
        s, v = ((0.80, 0.80), (0.70, 0.58), (0.95, 0.68))[index % 3]
    else:
        s, v = ((0.62, 0.98), (0.50, 0.85), (0.78, 0.92))[index % 3]
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))[i]
    return int(r * 255), int(g * 255), int(b * 255)


def _lab(rgb: tuple[int, int, int]) -> npt.NDArray[np.float64]:
    """sRGB to CIE L*a*b* (D65): distances there follow what the eye sees."""
    c = np.array(rgb, np.float64) / 255
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = m @ c / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def disc_point(rid: str, x: float, y: float, r: float) -> tuple[float, float]:
    """A record's spot in its group's disc: uniform over the disc, fixed by the ID alone, so it
    never moves when other records come or go."""
    h = hashlib.sha256(rid.encode()).digest()
    u = int.from_bytes(h[:8], "big") / 2**64
    v = int.from_bytes(h[8:16], "big") / 2**64
    rr = r * math.sqrt(v)
    return x + rr * math.cos(2 * math.pi * u), y + rr * math.sin(2 * math.pi * u)


class GroupMap:
    """Each group's centre, radius and colour number on the map by group, kept once given."""

    def __init__(self, path: Path, spawn_size: int) -> None:
        self.path = path
        self.spawn_radius = SPREAD * math.sqrt(spawn_size)
        self.anchors: dict[str, tuple[float, float, float]] = {}
        self.colours: dict[str, int] = {}
        self.outer: float | None = None
        self.scale = 1.0
        self.spawned = 0
        if path.exists():
            doc = json.loads(path.read_text("utf-8"))
            self.anchors = {g: (a[0], a[1], a[2]) for g, a in doc["anchors"].items()}
            self.colours = dict(doc["colours"])
            self.outer, self.scale, self.spawned = doc["outer"], doc["scale"], doc["spawned"]

    def save(self) -> None:
        doc = {
            "anchors": self.anchors,
            "colours": self.colours,
            "outer": self.outer,
            "scale": self.scale,
            "spawned": self.spawned,
        }
        self.path.write_text(json.dumps(doc), "utf-8")

    def ensure(self, members: dict[str, list[tuple[float, float]]]) -> bool:
        """Places every group of ``members`` (group -> its members' positions by meaning, groups
        in the order they appeared) that has no place yet. True when something was placed."""
        new = [g for g in members if g not in self.anchors]
        if not new:
            return False
        frozen = sorted(g for g in new if g.startswith("frozen-"))
        if frozen:
            self._place_frozen(frozen, members)
        if self.outer is None:
            self.outer = max((math.hypot(x, y) + r for x, y, r in self.anchors.values()), default=0)
        for g in new:
            if not g.startswith("frozen-"):
                self.anchors[g] = self._ring_slot(self.spawned)
                self.spawned += 1
        self._colour(new)
        self.save()
        return True

    def _place_frozen(self, new: list[str], members: dict[str, list[tuple[float, float]]]) -> None:
        radii = np.array([SPREAD * math.sqrt(max(len(members[g]), 3)) for g in new])
        start = np.array([np.mean(members[g], axis=0) for g in new], np.float64).reshape(-1, 2)
        fixed = [a for g, a in self.anchors.items() if g.startswith("frozen-")]
        if not fixed:
            packed = math.sqrt(float((radii**2).sum()) / PACKING)
            self.scale = packed / max(float(np.abs(start).max()), 1e-9)
        start *= self.scale
        pos = np.vstack([np.array([a[:2] for a in fixed]).reshape(-1, 2), start])
        rad = np.concatenate([np.array([a[2] for a in fixed]), radii])
        moves = np.arange(len(pos)) >= len(fixed)
        # a deterministic nudge, so discs that start on the same spot can be told apart
        pos[moves] += np.stack([np.cos(np.arange(moves.sum())), np.sin(np.arange(moves.sum()))], 1)
        pos[moves] *= 1 + 1e-3
        for _ in range(400):
            d = pos[:, None, :] - pos[None, :, :]
            dist = np.sqrt((d**2).sum(-1)) + np.eye(len(pos))
            overlap = np.clip(rad[:, None] + rad[None, :] + GAP - dist, 0, None)
            np.fill_diagonal(overlap, 0)
            if overlap.max() < 1e-3:
                break
            push = (d / dist[..., None] * overlap[..., None] / 2).sum(1)
            pos[moves] += push[moves]
        for g, (x, y), r in zip(new, pos[moves], radii, strict=True):
            self.anchors[g] = (float(x), float(y), float(r))

    def _ring_slot(self, k: int) -> tuple[float, float, float]:
        """Spawned group number ``k``: rings around the frozen groups, filled clockwise from the
        top."""
        rs = self.spawn_radius
        pitch = 2 * rs + GAP
        radius = (self.outer or 0) + rs + 2 * GAP
        while True:
            n = max(1, int(2 * math.pi * radius / pitch))
            if k < n:
                a = math.pi / 2 - 2 * math.pi * k / n
                return radius * math.cos(a), radius * math.sin(a), rs
            k -= n
            radius += pitch

    def _colour(self, new: list[str]) -> None:
        """A colour number per new group, never one already used, chosen to differ most from the
        colours of its nearest groups on the map."""
        size = len(self.anchors) + 48
        labs = np.array([_lab(palette_rgb(i)) for i in range(size)])
        free = np.ones(size, bool)
        free[[c for c in self.colours.values() if c < size]] = False
        for g in new:
            x, y, _ = self.anchors[g]
            near = sorted(
                (math.hypot(x - a[0], y - a[1]), h)
                for h, a in self.anchors.items()
                if h in self.colours
            )[:8]
            pool = np.flatnonzero(free)
            if near:
                theirs = labs[[self.colours[h] for _, h in near]]
                gap = np.linalg.norm(labs[pool][:, None, :] - theirs[None], axis=2).min(1)
                best = int(pool[int(np.argmax(gap))])
            else:
                best = int(pool[0])
            self.colours[g] = best
            free[best] = False
