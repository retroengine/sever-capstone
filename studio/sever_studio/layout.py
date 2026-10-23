"""The 2D map: every 384-dimensional vector drawn as a point, in two layouts.

**By group** (the default): each group is a cluster of its own colour, as a k-means picture shows
it. A group sits where the average of its members' meaning puts it, pushed apart from the others so
no two overlap; inside, each member keeps where its meaning puts it relative to the group's other
members, shrunk to the group's size. A group keeps its place, scale and colour once given
(``GroupMap``, saved in the work directory), so a deletion moves nothing else.

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


def hull(points: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """The convex hull, counter-clockwise (Andrew's monotone chain)."""
    pts = sorted({(float(x), float(y)) for x, y in points})
    if len(pts) < 3:
        return np.array(pts, np.float64).reshape(-1, 2)

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    upper: list[tuple[float, float]] = []
    for pt in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], pt) <= 0:
            lower.pop()
        lower.append(pt)
    for pt in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], pt) <= 0:
            upper.pop()
        upper.append(pt)
    return np.array(lower[:-1] + upper[:-1], np.float64)


def outline(points: npt.NDArray[np.float64], pad: float, steps: int = 6) -> npt.NDArray[np.float64]:
    """A closed boundary ``pad`` outside every point: the hull, its corners rounded."""
    h = hull(points)
    if len(h) == 0:
        return h
    angles = np.linspace(0, 2 * math.pi, 4 * steps, endpoint=False)
    ring = np.stack([np.cos(angles), np.sin(angles)], 1) * pad
    around = (h[:, None, :] + ring[None, :, :]).reshape(-1, 2)  # a circle of radius pad at each
    out = hull(around)
    return np.vstack([out, out[:1]])


class GroupMap:
    """Each group's cluster on the map by group, kept once given: its centre ``(x, y)``, radius
    ``r``, and how its members' meaning positions map into it (their mean then ``(mx, my)``, and the
    shrink factor ``s``); plus its colour number."""

    VERSION = 2

    def __init__(self, path: Path, spawn_size: int) -> None:
        self.path = path
        self.spawn_size = spawn_size
        self.anchors: dict[str, tuple[float, float, float]] = {}
        self.inner: dict[str, tuple[float, float, float]] = {}
        self.colours: dict[str, int] = {}
        #: a spawned group's centre, kept as computed at its creation (§7.5: then frozen)
        self.mu: dict[str, list[float]] = {}
        self.scale = 0.0
        if path.exists():
            doc = json.loads(path.read_text("utf-8"))
            if doc.get("version") == self.VERSION:
                self.anchors = {g: (a[0], a[1], a[2]) for g, a in doc["anchors"].items()}
                self.inner = {g: (a[0], a[1], a[2]) for g, a in doc["inner"].items()}
                self.colours = dict(doc["colours"])
                self.mu = dict(doc["mu"])
                self.scale = doc["scale"]

    def save(self) -> None:
        doc = {
            "version": self.VERSION,
            "anchors": self.anchors,
            "inner": self.inner,
            "colours": self.colours,
            "mu": self.mu,
            "scale": self.scale,
        }
        self.path.write_text(json.dumps(doc), "utf-8")

    def point(self, group: str, meaning: tuple[float, float]) -> tuple[float, float]:
        """Where a member of ``group`` whose position by meaning is ``meaning`` is drawn: its offset
        from the group's mean, shrunk, never outside the group's radius."""
        x, y, r = self.anchors[group]
        mx, my, s = self.inner[group]
        dx, dy = (meaning[0] - mx) * s, (meaning[1] - my) * s
        d = math.hypot(dx, dy)
        if d > r:
            dx, dy = dx * r / d, dy * r / d
        return x + dx, y + dy

    def ensure(
        self,
        members: dict[str, list[tuple[float, float]]],
        centres: dict[str, tuple[float, float]] | None = None,
    ) -> bool:
        """Places every group of ``members`` (group -> its members' positions by meaning) that has
        no place yet, starting from where ``centres`` puts its real centre μ by meaning (else its
        members' mean). True when something was placed."""
        new = sorted(g for g in members if g not in self.anchors and members[g])
        if not new:
            return False
        radii, means = [], []
        for g in new:
            pts = np.array(members[g], np.float64).reshape(-1, 2)
            r = SPREAD * math.sqrt(max(len(pts), 3))
            m = pts.mean(axis=0)
            far = float(np.sqrt(((pts - m) ** 2).sum(1)).max())
            self.inner[g] = (float(m[0]), float(m[1]), r / far if far > 1e-9 else 1.0)
            radii.append(r)
            means.append(np.array((centres or {}).get(g, (m[0], m[1])), np.float64))
        rad_new = np.array(radii)
        start = np.array(means, np.float64).reshape(-1, 2)
        if not self.anchors:  # the first groups set how far meaning spreads the clusters
            packed = math.sqrt(float((rad_new**2).sum()) / PACKING)
            self.scale = packed / max(float(np.abs(start).max()), 1e-9)
        start *= self.scale
        fixed = list(self.anchors.values())
        pos = np.vstack([np.array([a[:2] for a in fixed]).reshape(-1, 2), start])
        rad = np.concatenate([np.array([a[2] for a in fixed]), rad_new])
        moves = np.arange(len(pos)) >= len(fixed)
        # a deterministic nudge, so clusters that start on the same spot can be told apart
        k = np.arange(int(moves.sum()))
        pos[moves] += np.stack([np.cos(k), np.sin(k)], 1) * 0.5
        for _ in range(600):
            d = pos[:, None, :] - pos[None, :, :]
            dist = np.sqrt((d**2).sum(-1)) + np.eye(len(pos))
            overlap = np.clip(rad[:, None] + rad[None, :] + GAP - dist, 0, None)
            np.fill_diagonal(overlap, 0)
            if overlap.max() < 1e-3:
                break
            push = (d / dist[..., None] * overlap[..., None] / 2).sum(1)
            pos[moves] += push[moves]
        for g, (x, y), r in zip(new, pos[moves], rad_new, strict=True):
            self.anchors[g] = (float(x), float(y), float(r))
        self._colour(new)
        self.save()
        return True

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
