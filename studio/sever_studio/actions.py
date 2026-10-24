"""Every demonstration Studio can give, as plain functions: each does its thing through the public
SDK or the separate programs, checks its claim, and ticks its row of the checklist. The window only
draws what these return; the tests call them directly.
"""

import hashlib
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from sever_db import (
    DuplicateRecord,
    InvalidRecordId,
    NotNormalised,
    SeededNonceForbidden,
    SeverError,
    UserKey,
    WrongDimension,
    prepare_insert,
)

from . import evidence, layout, proofs, sabotage, tools, wow
from .backend import HOLDING, Backend, Flush, Inserted
from .checklist import Checklist
from .corpus import FIXTURE_ENCODER, Corpus, fixture_encode, load

#: Rows kept unstored after the stored ones, for the live demos (filling the holding area, the
#: writer that is killed, the person deleted part-way). Topped up whenever fewer remain (H2).
SPARE = 3000


def stored_so_far(work: Path) -> int:
    """How many corpus rows the work directory's index has used, read before the database opens."""
    try:
        return int(json.loads((work / "index.json").read_text("utf-8"))["loaded"])
    except (OSError, ValueError, KeyError):
        return 0


LIMITS = [
    "That the operator kept no copy of the deleted data. No cryptography can prove that "
    "(overview L-2; §11.3).",
    "That the person personally asked for the deletion. The application holds the account key "
    "and decides who may delete (overview L-27; §3.3).",
    "That the deletion's own log leaf was appended, that a group's certificates chain, and that "
    "the log is consistent: the auditor checks those with the log (§11.3).",
]


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]
    return s or "someone"


@dataclass
class Added:
    rid: str
    xy: tuple[float, float]
    result: Inserted


@dataclass
class Deleted:
    rids: list[str]
    lsns: list[int]
    groups_before: dict[str, int]
    groups_after: dict[str, int]
    total_before: int
    total_after: int
    ok: bool


@dataclass
class Verified:
    lsn: int
    folder: Path
    steps: list[tools.Step]
    verdict: str
    code: int
    flipped: tuple[int, int, int] | None = None  # offset, byte before, byte after
    certificate: bytes = b""


@dataclass
class Crashed:
    acked: int
    in_flight: str | None
    committed: bool | None
    killed: bool
    missing: int
    grew: int


@dataclass
class Disk:
    files: int
    size: int
    naive: dict[str, tuple[int, int]]
    sever: dict[str, tuple[int, int]]


class Studio:
    def __init__(self, root: Path, data: str, work: Path, dev: bool, rows: int) -> None:
        self.root = root.resolve()
        self.data = data
        self.work = work.resolve()
        self.rows = rows
        self.corpus: Corpus = load(root, data, max(rows, stored_so_far(work)) + SPARE)
        self.backend = Backend(self.corpus, self.work, dev)
        self.checklist = Checklist()
        self.numbers: dict[str, Any] = {"data": data, "rows": rows}
        self.coords = layout.fit(self.corpus.vectors, cache=work)
        self.extra_xy: dict[str, tuple[float, float]] = {}
        #: the 3-D layout, made the first time the 3-D mode opens (``layout3``)
        self.coords3: layout.Coords | None = None
        self.extra_xyz: dict[str, tuple[float, float, float]] = {}
        self._centre_xyz: dict[str, tuple[float, float, float]] = {}
        #: where each group's centre is drawn: among the passages nearest it
        self._centre_xy: dict[str, tuple[float, float]] = {}
        self._frozen: npt.NDArray[np.float64] | None = None
        #: (record ID, its insert's log position) of each deletion this session
        self.deleted_this_session: list[tuple[str, int]] = []
        self._encoder: Any = None
        self._explainer: Any = None
        self.backend.predict = self.predict

    # -- the map ----------------------------------------------------------------------------------

    def xy(self, rid: str) -> tuple[float, float]:
        """Where a record is drawn: where its meaning puts it (t-SNE), whatever its group."""
        return self.meaning_xy(rid)

    def centre(self, group: str) -> npt.NDArray[np.float64] | None:
        """The group's centre μ as the database routes and searches with it: a frozen group's from
        the partition the engine verified (§6.3), a spawned group's as the engine computed it at the
        flush and reported it (§7.5, DB-107); ``None`` when that report was lost with a killed
        process. Studio never computes one."""
        if group.startswith("frozen-"):
            if self._frozen is None:
                from sever_partition.artefact import decode

                self._frozen = decode(self.corpus.artefact.read_bytes()).centroids
            k = int(group.split("-")[1])
            return self._frozen[k] if k < len(self._frozen) else None
        mu = self.backend.centroids().get(group)
        return np.asarray(mu, np.float64) if mu is not None else None

    def centres(self) -> list[tuple[str, float, float, int]]:
        """Every group the engine has whose centre μ is known (§6.3, §7.5), with where it is drawn
        (among the passages nearest it, as a typed text is) and its size from ``group_sizes``."""
        b = self.backend
        out = []
        for g, n in b.group_sizes():
            mu = self.centre(g)
            if mu is None:
                continue
            if g not in self._centre_xy:
                self._centre_xy[g] = layout.place(
                    mu.astype(np.float32), self.corpus.vectors[: len(self.coords)], self.coords
                )
            out.append((g, *self._centre_xy[g], n))
        return out

    def centre_xy(self, group: str) -> tuple[float, float] | None:
        return next(((x, y) for g, x, y, _ in self.centres() if g == group), None)

    def group_card(self, group: str) -> dict[str, Any]:
        """What the engine says about a group: its size ``n`` (``group_sizes``), the newest
        commitment it published for it (``C_S_post`` of its latest deletion, §11.1 tag 3), and its
        centre μ with where that number comes from. ``S`` stays encrypted in the engine (§13.2) and
        is not shown."""
        b = self.backend
        n = dict(b.group_sizes()).get(group, 0)
        replay = b.replay_if_ready()
        published = replay.commitments.get(group) if replay else None
        mu = self.centre(group)
        return {
            "group": group,
            "n": n,
            "commitment": published[1].hex() if published else None,
            "commitment_lsn": published[0] if published else None,
            "mu": mu,
            "mu_source": (
                "the partition artefact the engine verified (§6.3)"
                if group.startswith("frozen-")
                else "the engine, at the flush that created it (§7.5)"
                if mu is not None
                else "unknown: the flush happened in a process that was killed"
            ),
        }

    def meaning_xy(self, rid: str) -> tuple[float, float]:
        if rid in self.extra_xy:
            return self.extra_xy[rid]
        i = self.corpus.position.get(rid)
        if i is not None and i < len(self.coords):
            return float(self.coords[i, 0]), float(self.coords[i, 1])
        if i is not None:  # loaded after the layout was made: placed beside its nearest passages
            p = layout.place(
                self.corpus.vectors[i], self.corpus.vectors[: len(self.coords)], self.coords
            )
            self.extra_xy[rid] = p
            return p
        rec = self.backend.index.records.get(rid)
        if rec is not None and rec.vector is not None:
            p = layout.place(np.asarray(rec.vector, np.float32), self.corpus.vectors, self.coords)
            self.extra_xy[rid] = p
            return p
        return 0.0, 0.0

    # -- the 3-D mode -----------------------------------------------------------------------------

    def layout3(self) -> layout.Coords:
        """The 3-D picture of the same rows as the 2-D one: t-SNE with three axes, made once and
        kept in the work directory (minutes on NQ the first time)."""
        if self.coords3 is None:
            self.coords3 = layout.fit(
                self.corpus.vectors[: len(self.coords)], cache=self.work, dims=3
            )
        return self.coords3

    def xyz(self, rid: str) -> tuple[float, float, float]:
        """Where a record is drawn in 3-D: where its meaning puts it, as ``xy`` in 2-D."""
        c3 = self.layout3()
        if rid in self.extra_xyz:
            return self.extra_xyz[rid]
        i = self.corpus.position.get(rid)
        if i is not None and i < len(c3):
            return float(c3[i, 0]), float(c3[i, 1]), float(c3[i, 2])
        p = layout.place3(self.backend.vector_of(rid), self.corpus.vectors, c3)
        self.extra_xyz[rid] = p
        return p

    def centres3(self) -> list[tuple[str, float, float, float, int]]:
        """``centres`` in 3-D."""
        c3 = self.layout3()
        out = []
        for g, n in self.backend.group_sizes():
            mu = self.centre(g)
            if mu is None:
                continue
            if g not in self._centre_xyz:
                self._centre_xyz[g] = layout.place3(
                    mu.astype(np.float32), self.corpus.vectors[: len(c3)], c3
                )
            out.append((g, *self._centre_xyz[g], n))
        return out

    def separation(self, per_group: int = 8) -> list[tuple[str, str, float, float]]:
        """Are the groups clusters, in all the dimensions? For up to ``per_group`` stored records of
        each group: ``(record, group, D to its own centre, D to the nearest other centre)``, both
        as the engine's search code ranks groups (§8.1 step 1, DB-108). A record of a cluster is
        nearer its own centre than any other."""
        b = self.backend
        members: dict[str, list[str]] = {}
        for rid, rec in b.index.records.items():
            if rec.group != HOLDING:
                some = members.setdefault(rec.group, [])
                if len(some) < per_group:
                    some.append(rid)
        groups = []
        for g, _ in b.group_sizes():
            mu = self.centre(g)
            if mu is not None:
                groups.append((g, [float(v) for v in mu]))
        known = {g for g, _ in groups}
        out = []
        for g, rids in members.items():
            if g not in known:
                continue
            for rid in rids:
                ranked = self.explainer().search([float(v) for v in b.vector_of(rid)], groups)[
                    "ranked"
                ]
                own = next(d for h, d in ranked if h == g)
                other = next(d for h, d in ranked if h != g)
                out.append((rid, g, float(own), float(other)))
        return out

    def encode(self, text: str) -> npt.NDArray[np.float32]:
        if self.data == "synthetic":
            fixed: npt.NDArray[np.float32] = fixture_encode(text, self.corpus.d)[0]
            return fixed
        row: npt.NDArray[np.float32] = self.encoder_rows([text])[0]
        return row

    # -- routing, as the engine computes it (DB-108) -----------------------------------------------

    def explainer(self) -> Any:
        if self._explainer is None:
            from sever_db import Explainer

            self._explainer = Explainer(self.corpus.artefact.read_bytes())
        return self._explainer

    def predict(self, vector: npt.NDArray[np.float32]) -> dict[str, Any]:
        """§7.1–7.3 for ``vector`` against the engine's state now: the spawned groups with the
        centres the engine reported and their sizes, ``N`` and ``k`` from ``stats``. ``unknown``
        lists the spawned groups with room whose centre was lost with a killed process: while it is
        not empty, an out-of-distribution destination cannot be worked out."""
        b = self.backend
        st = b.live.stats(b.cid)
        centres = b.centroids()
        sizes = [(g, n) for g, n in b.live.group_sizes(b.cid) if g.startswith("spawn-")]
        spawned = [(g, centres[g], n) for g, n in sizes if g in centres]
        out: dict[str, Any] = self.explainer().route(
            [float(v) for v in vector], spawned, st["N"], st["k"]
        )
        out["unknown"] = [g for g, n in sizes if g not in centres and 2 * st["k"] * n < 3 * st["N"]]
        return out

    def search_explained(self, query: npt.NDArray[np.float32]) -> dict[str, Any]:
        """§8.1 steps 1–2 by the engine's search code (DB-108): every frozen and spawned group the
        engine has, empty ones too, ranked by its centre's distance to the query, and how many are
        opened. A group whose centre was lost with a killed process is listed in ``unknown``."""
        b = self.backend
        groups, unknown = [], []
        for g, _ in b.live.group_sizes(b.cid):
            mu = self.centre(g)
            if mu is None:
                unknown.append(g)
            else:
                groups.append((g, [float(v) for v in mu]))
        out: dict[str, Any] = self.explainer().search([float(v) for v in query], groups)
        out["unknown"] = unknown
        return out

    def why(self, rid: str) -> dict[str, Any] | None:
        """For a stored record, the parts of §7.1–7.2 that do not depend on when it arrived: its
        nearest frozen groups, ``j*``, ``d_M`` and ``τ``."""
        if rid not in self.backend.index.records:
            return None
        return self.predict(self.backend.vector_of(rid))

    def spares_left(self) -> int:
        return len(self.corpus.ids) - self.backend.index.loaded

    def ensure_spares(self, need: int) -> None:
        """Loads more passages when fewer than ``need`` remain unstored; the rows already loaded
        stay as they are (``corpus.load`` is prefix-stable)."""
        if self.spares_left() >= need:
            return
        self.corpus = load(self.root, self.data, self.backend.index.loaded + max(need, SPARE))
        self.backend.corpus = self.corpus

    def store_first(self, progress: Callable[[int, int], None] | None = None) -> list[Inserted]:
        """Stores the first ``rows`` passages and writes where each landed
        (``prepare-events.jsonl``, for the replay)."""
        out = self.backend.insert_next(self.rows, progress)
        with (self.work / "prepare-events.jsonl").open("w", encoding="utf-8") as f:
            for r in out:
                row = {"rid": r.rid, "placement": r.placement}
                if r.flush is not None:
                    row["flush"] = r.flush.group
                f.write(json.dumps(row) + "\n")
        return out

    def reset(self, progress: Callable[[int, int], None] | None = None) -> None:
        """A fresh demo database: everything in the work directory is deleted (database, keys,
        receipts, layout) and the first ``rows`` passages are stored again."""
        b = self.backend
        b.wipe()
        self.work.mkdir(parents=True)
        self.corpus = load(self.root, self.data, self.rows + SPARE)
        b.corpus = self.corpus
        self.coords = layout.fit(self.corpus.vectors, cache=self.work)
        self._centre_xy.clear()
        self.extra_xy.clear()
        self.coords3 = None
        self._centre_xyz.clear()
        self.extra_xyz.clear()
        self.deleted_this_session = []
        self.open()
        self.store_first(progress)

    # -- start ------------------------------------------------------------------------------------

    def open(self) -> tuple[str | None, tuple[str, ...], bool]:
        db = self.backend.open()
        _ = self.backend.cid
        overridden, locked = db.startup
        ok = self.backend.refused is None or bool(overridden)
        self.checklist.mark(
            "startup",
            ok,
            ("refused: " + self.backend.refused + "; " if self.backend.refused else "")
            + f"overrides {list(overridden) or 'none'}, memory locked {locked}",
        )
        self.numbers["startup_overrides"] = list(overridden)
        return self.backend.refused, overridden, locked

    def verify_data(self, progress: Callable[[int, int], None] | None = None) -> tuple[int, int]:
        """Re-hashes every pinned data file against ``datasets/MANIFEST.sha256`` (P0); for the
        offline fixture, checks the golden files match the committed ones."""
        if self.data == "synthetic":
            code = subprocess.run(
                ["git", "diff", "--quiet", "HEAD", "--", "golden/"], cwd=self.root, check=False
            ).returncode
            self.checklist.mark("data", code == 0, "golden/ fixture matches the commit")
            return (1, 0) if code == 0 else (0, 1)
        lines = (self.root / "datasets/MANIFEST.sha256").read_text("utf-8").splitlines()
        ok = bad = 0
        for k, line in enumerate(lines, 1):
            want, name = line.split(maxsplit=1)
            h = hashlib.sha256()
            with (self.root / "datasets" / name.lstrip("*")).open("rb") as f:
                while chunk := f.read(1 << 22):
                    h.update(chunk)
            if h.hexdigest() == want:
                ok += 1
            else:
                bad += 1
            if progress:
                progress(k, len(lines))
        self.checklist.mark("data", bad == 0 and ok > 0, f"{ok} files re-hashed, {bad} mismatches")
        return ok, bad

    def encoder_check(self) -> tuple[str, str, str]:
        """The partition, the stored vectors and Studio's encoder name the same model, and on NQ
        Studio's encoder gives the stored vectors back: five stored passages re-encoded, each at
        cosine ≥ 0.9999 with its stored vector (H6). The fixture has no encoder."""
        art, data = self.corpus.artefact_encoder(), self.corpus.encoder
        if self.data == "synthetic":
            mine = FIXTURE_ENCODER
            ok = art == data == mine
            self.checklist.mark(
                "encoder", ok, f"artefact {art}; data {data}; the fixture has no encoder"
            )
            return art, data, mine
        from .encoder import NAME

        mine = NAME
        rows = list(range(5))
        again = self.encoder_rows([self.corpus.texts[i] for i in rows])
        stored = self.corpus.vectors[rows].astype(np.float64)
        cos = (again.astype(np.float64) * stored).sum(axis=1)
        ok = art == data == mine and bool((cos >= 0.9999).all())
        self.checklist.mark(
            "encoder",
            ok,
            f"one model named everywhere ({mine.split('@')[0]}); 5 stored passages re-encoded, "
            f"cosine with their stored vectors {cos.min():.6f} … {cos.max():.6f}",
        )
        return art, data, mine

    def encoder_rows(self, texts: list[str]) -> npt.NDArray[np.float32]:
        if self._encoder is None:
            from .encoder import Encoder

            self._encoder = Encoder(self.work.parent / "models")
        rows: npt.NDArray[np.float32] = self._encoder.encode(texts)
        return rows

    def clusters(self) -> dict[str, int]:
        b = self.backend
        st = dict(b.live.stats(b.cid))
        st["empty"] = sum(1 for _, n in b.live.group_sizes(b.cid) if n == 0)
        problems = b.mismatches()
        ok = not problems and st["frozen"] > 0
        detail = (
            f"{st['frozen']} frozen + {st['spawned']} spawned groups,"
            f" N {st['N']}, holding {st['holding']}"
        )
        self.checklist.mark("clusters", ok, detail if ok else "; ".join(problems))
        return st

    # -- inserts ----------------------------------------------------------------------------------

    def add_mine(self, account: str, text: str) -> Added:
        """Your own record: encoded, signed with the account's key, inserted with its text."""
        b = self.backend
        k = sum(1 for r in b.index.records.values() if r.mine) + 1
        rid = f"you-{slug(account)}-{k}"
        while rid in b.index.records:
            k += 1
            rid = f"you-{slug(account)}-{k}"
        vec = self.encode(text)
        before = b.total()
        res = b.insert(rid, vec, account, text=text, mine=True)
        xy = layout.place(vec, self.corpus.vectors, self.coords)
        self.extra_xy[rid] = xy
        grew = b.total() - before == 1
        self.checklist.mark(
            "insert", res.lsn is not None and grew, f"acknowledged at log position {res.lsn}"
        )
        norm = float(np.linalg.norm(vec.astype(np.float64)))
        self.checklist.mark(
            "freetext",
            abs(norm - 1) < 1e-6,
            f"{len(vec)} numbers from {self.corpus.encoder}, length {norm:.7f}",
        )
        self._routed(res)
        return Added(rid, xy, res)

    def _routed(self, res: Inserted) -> None:
        """Ticks routing when every insert so far went where the engine's own routing code said
        it would (§7.3, DB-108), and the index agrees with the engine's log."""
        b = self.backend
        problems = b.mismatches()
        if b.routing_disagreed:
            problems.append(
                f"placed elsewhere than predicted: {', '.join(b.routing_disagreed[:5])}"
            )
        self.checklist.mark(
            "routing",
            not problems and b.routing_checked > 0,
            f"{b.routing_checked:,} inserts, each placed where the engine's routing code said"
            f" (last: {res.rid} → {res.placement})"
            + (
                f"; {b.routing_unknown:,} could not be worked out: a spawned centre was lost with"
                " a killed process"
                if b.routing_unknown
                else ""
            )
            if not problems
            else "; ".join(problems),
        )
        if res.flush is not None:
            self._flushed(res.flush)

    def _flushed(self, f: Flush) -> None:
        ok = (
            f.id_matches
            and len(f.members) == self.corpus.spawn_target
            and not self.backend.mismatches()
        )
        self.checklist.mark(
            "flush",
            ok,
            f"{len(f.members)} records → {f.group}; recomputed ID {f.expected}"
            + (" (matches)" if f.id_matches else " (DIFFERS)"),
        )

    def fill_bucket(
        self,
        until: str = "flush",
        limit: int = SPARE,
        progress: Callable[[int, int, Inserted], None] | None = None,
    ) -> list[Inserted]:
        """Inserts the next dataset passages until the holding area flushes (``until="flush"``)
        or holds at least one record (``"one"``), or ``limit`` inserts."""
        self.ensure_spares(limit)
        b, c = self.backend, self.corpus
        out: list[Inserted] = []
        for _ in range(limit):
            i = b.index.loaded
            if i >= len(c.ids):
                break
            res = b.insert(c.ids[i], c.vectors[i], c.accounts[i], save=False)
            b.index.loaded = i + 1
            out.append(res)
            if progress:
                progress(len(b.index.holding), c.spawn_target, res)
            if res.flush is not None or (until == "one" and b.index.holding):
                break
        b.save()
        if out:
            self._routed(out[-1])
        return out

    def retry(self) -> tuple[Inserted, Inserted]:
        """An insert whose answer was lost, sent again with the same request (§15.1)."""
        b, c = self.backend, self.corpus
        k = 1
        while f"retry-demo-{k}" in b.index.records:
            k += 1
        rid = f"retry-demo-{k}"
        vec = c.vectors[len(c.ids) - 1]
        req = b.request(rid, vec, "retry-demo")
        before = b.total()
        first = b.insert(rid, vec, "retry-demo", text="a retried insert", mine=True, request=req)
        again = b.insert(rid, vec, "retry-demo", request=req)
        once = b.total() - before == 1
        self.checklist.mark(
            "retry", again.retried and once, f"second answer: retried={again.retried}; stored once"
        )
        self.extra_xy[rid] = layout.place(vec, c.vectors, self.coords)
        return first, again

    def refusals(self) -> list[tuple[str, str, bool, str]]:
        """Five invalid inputs: (what, error class expected, refused as expected, message)."""
        b, c = self.backend, self.corpus
        cid, db = b.cid, b.live
        user = UserKey.generate()
        unit = c.vectors[0].astype(np.float64)
        live = next(iter(b.index.records))
        cases: list[tuple[str, type[SeverError], Callable[[], object]]] = [
            (
                "a vector that is not unit length",
                NotNormalised,
                lambda: prepare_insert(cid, "new-1", (unit * 2).tolist(), user),
            ),
            (
                f"a vector of {c.d + 1} numbers instead of {c.d}",
                WrongDimension,
                lambda: db.insert(cid, prepare_insert(cid, "new-2", [1.0] + [0.0] * c.d, user)),
            ),
            (
                'a record ID that is a bare number ("12345")',
                InvalidRecordId,
                lambda: db.insert(cid, prepare_insert(cid, "12345", unit.tolist(), user)),
            ),
            (
                "a second record with a live record's ID",
                DuplicateRecord,
                lambda: db.insert(cid, prepare_insert(cid, live, unit.tolist(), user)),
            ),
            ("a seed passed to key generation", SeededNonceForbidden, lambda: UserKey.generate(42)),
        ]
        out = []
        for label, kind, call in cases:
            try:
                call()
                out.append((label, kind.__name__, False, "accepted"))
            except kind as e:
                msg = f"{type(e).__name__}: {e}"
                clean = live not in msg and "12345" not in msg and "new-" not in msg
                out.append((label, kind.__name__, clean, msg))
            except SeverError as e:
                out.append((label, kind.__name__, False, f"{type(e).__name__}: {e}"))
        ok = all(r[2] for r in out)
        self.checklist.mark("refusals", ok, f"{sum(r[2] for r in out)} of {len(out)} refused")
        return out

    # -- reading ----------------------------------------------------------------------------------

    def hover(self, rid: str) -> dict[str, Any]:
        b = self.backend
        rec = b.index.records.get(rid)
        if rec is None:
            return {}
        vec = b.vector_of(rid)
        info = {
            "rid": rid,
            "account": rec.account,
            "group": rec.group,
            "mine": rec.mine,
            "text": b.text_of(rid),
            "source": "typed in Studio" if rec.mine else "the dataset",
            "vector": vec,
        }
        if not self.checklist.verdicts.get("hover"):
            self.checklist.mark(
                "hover",
                bool(info["text"]) and len(vec) == self.corpus.d,
                f"{rid}: {rec.group}, {len(vec)} numbers",
            )
        return info

    def ask(self, question: int | str, k: int = 10) -> tuple[str, list[tuple[str, float, bool]]]:
        """Search with a dataset question (by number) or with text typed in Studio."""
        c = self.corpus
        if isinstance(question, int):
            text, vec, answers = (
                c.questions[question],
                c.question_vectors[question],
                c.answers.get(question, frozenset()),
            )
        else:
            text, vec, answers = question, self.encode(question), frozenset()
        hits = [(rid, d, rid in answers) for rid, d in self.backend.search(vec, k)]
        return text, hits

    def search_quality(self) -> tuple[int, int, int, float]:
        """Every question whose judged answer is stored: answer first (hit@1), in the top 10."""
        c, b = self.corpus, self.backend
        live = set(b.index.records)
        qs = [q for q, a in c.answers.items() if a & live]
        t0 = time.perf_counter()
        at1 = at10 = 0
        for q in qs:
            top = [h for h, _ in b.search(c.question_vectors[q], 10)]
            at1 += bool(top) and top[0] in c.answers[q]
            at10 += bool(set(top) & c.answers[q])
        ms = (time.perf_counter() - t0) * 1000 / max(1, len(qs))
        self.numbers.update(questions=len(qs), hit_at_1=at1, hit_at_10=at10, search_ms=round(ms, 3))
        self.checklist.mark(
            "search", at10 > 0, f"{len(qs)} questions: first {at1}, top 10 {at10}, {ms:.2f} ms each"
        )
        return len(qs), at1, at10, ms

    def unsearchable(self) -> tuple[str | None, bool, bool]:
        """A record in the holding area: stored, but no search finds it, not even with its own
        vector; a record in a group is found by its own vector (the control)."""
        b = self.backend
        if not b.index.holding:
            return None, False, False
        rid = b.index.holding[-1]
        vec = b.vector_of(rid)
        found = any(h == rid for h, _ in b.search(vec, 10))
        stored = b.is_live(rid)
        grouped = next(r for r, rec in b.index.records.items() if rec.group != HOLDING)
        control = any(h == grouped for h, _ in b.search(b.vector_of(grouped), 3))
        self.checklist.mark(
            "unsearchable",
            stored and not found and control,
            f"{rid}: stored {stored}, found by its own vector {found};"
            f" control {grouped} found {control}",
        )
        return rid, found, stored

    # -- deletions --------------------------------------------------------------------------------

    def _sizes(self) -> dict[str, int]:
        b = self.backend
        sizes = dict(b.live.group_sizes(b.cid))
        sizes[HOLDING] = b.live.stats(b.cid)["holding"]
        return sizes

    def delete(self, rids: list[str], key: str = "delete") -> Deleted:
        b = self.backend
        groups = {b.index.records[r].group for r in rids if r in b.index.records}
        lsns_of = {r: b.index.records[r].lsn for r in rids if r in b.index.records}
        before, total = self._sizes(), b.total()
        t0 = time.perf_counter()
        out = b.forget_ids(rids)
        if rids:
            self.numbers["delete_ms_per_record"] = round(
                (time.perf_counter() - t0) * 1000 / len(rids), 1
            )
        after, total_after = self._sizes(), b.total()
        lsns = [d.database_lsn for d in out if d.database_lsn is not None]
        gone = sum(d.outcome == "deleted" for d in out)
        ok = (
            gone == len(rids)
            and all(d.certificate for d in out)
            and total - total_after == gone
            and not b.mismatches()
        )
        self.deleted_this_session += [(r, n) for r, n in lsns_of.items() if n is not None]
        self.checklist.mark(
            key,
            ok,
            f"{gone} deleted from {len(groups)} group(s), {len(lsns)} certificates; "
            f"total {total} → {total_after}",
        )
        return Deleted(
            rids,
            lsns,
            {g: before.get(g, 0) for g in groups},
            {g: after.get(g, 0) for g in groups},
            total,
            total_after,
            ok,
        )

    def forget(self, account: str) -> Deleted:
        return self.delete(self.backend.accounts().get(account, []), key="forget")

    def delete_again(self, rid: str) -> bool:
        b = self.backend
        total = b.total()
        absent = b.absent(rid)
        ok = absent and b.total() == total
        self.checklist.mark("absent", ok, f'{rid}: "absent", total unchanged at {total}')
        return ok

    # -- receipts ---------------------------------------------------------------------------------

    def _hand_over(self, lsn: int) -> Path:
        """The certificate and the public anchors, alone in a folder: all the person holds."""
        folder = self.work / "handed-over" / str(lsn)
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        shutil.copy(self.backend.receipts / f"{lsn}.cert", folder / "certificate.bin")
        (folder / "anchors.json").write_text(self.backend.live.anchors(), "utf-8")
        return folder

    def verify(self, lsn: int) -> Verified:
        folder = self._hand_over(lsn)
        t = tools.build(self.root)
        code, out = tools.run(
            [t.verify, "certificate.bin", "--anchors", "anchors.json", "--explain"], folder
        )
        steps, verdict = tools.explain_steps(out)
        ok = code == 0 and verdict == "ACCEPT"
        self.checklist.mark("verify", ok, f"certificate at {lsn}: {verdict or out[:80]}")
        cert = (folder / "certificate.bin").read_bytes()
        return Verified(lsn, folder, steps, verdict, code, certificate=cert)

    def tamper(self, lsn: int, offset: int | None = None) -> Verified:
        folder = self._hand_over(lsn)
        cert = bytearray((folder / "certificate.bin").read_bytes())
        at = len(cert) // 2 if offset is None else offset
        old = cert[at]
        cert[at] ^= 0x01
        (folder / "certificate.bin").write_bytes(bytes(cert))
        t = tools.build(self.root)
        code, out = tools.run(
            [t.verify, "certificate.bin", "--anchors", "anchors.json", "--explain"], folder
        )
        steps, verdict = tools.explain_steps(out)
        ok = code == 1 and verdict.startswith("REJECT (step")
        self.checklist.mark("tamper", ok, f"byte {at} flipped: {verdict}")
        return Verified(lsn, folder, steps, verdict, code, (at, old, cert[at]), bytes(cert))

    def limits(self) -> list[str]:
        self.checklist.mark("limits", True, f"{len(LIMITS)} limits stated")
        return LIMITS

    # -- the log ----------------------------------------------------------------------------------

    def log(self) -> dict[str, Any]:
        db = self.backend.live
        cp = db.latest_log_checkpoint()
        path = db.inclusion_proof(cp.tree_size - 1, cp.tree_size) if cp.tree_size else None
        witnesses = len({c.witness_index for c in cp.cosignatures})
        ok = witnesses >= 4 and path is not None
        self.checklist.mark(
            "log", ok, f"{cp.tree_size} leaves, epoch {cp.epoch}, {witnesses} witnesses cosigned"
        )
        return {
            "tree_size": cp.tree_size,
            "root": cp.root.hex(),
            "epoch": cp.epoch,
            "timestamp_ms": cp.timestamp_ms,
            "witnesses": witnesses,
            "cosignatures": [(c.witness_index, c.witness_epoch) for c in cp.cosignatures],
            "inclusion_path": len(path) if path is not None else None,
        }

    def audit(self) -> tuple[int, str]:
        b = self.backend
        auditor = self.work / "auditor"
        shutil.rmtree(auditor, ignore_errors=True)
        auditor.mkdir(parents=True)
        (auditor / "log.json").write_text(b.live.export_log(), "utf-8")
        (auditor / "anchors.json").write_text(b.live.anchors(), "utf-8")
        t = tools.build(self.root)
        args: list[str | Path] = [t.audit, "log.json", "--anchors", "anchors.json"]
        for lsn in b.index.receipts:
            p = b.receipts / f"{lsn}.cert"
            if p.exists():
                args += ["--certificate", p]
        code, out = tools.run(args, auditor)
        self.checklist.mark("audit", code == 0, out[:160])
        return code, out

    # -- the disk ---------------------------------------------------------------------------------

    def disk(self) -> Disk:
        b = self.backend
        files = tools.files_under([b.data, b.keys])
        live = list(b.index.records)
        sample = live[:: max(1, len(live) // 40)][:40]
        texts = [b.text_of(r) for r in sample]
        vecs = [b.vector_of(r) for r in sample]
        needles = tools.needles_of(sample, texts, vecs)
        naive_dir = self.work / "naive-store"
        shutil.rmtree(naive_dir, ignore_errors=True)
        tools.write_naive(naive_dir, sample, texts, vecs)
        naive = tools.count_hits(tools.files_under([naive_dir]), needles)
        sever = tools.count_hits(files, needles)
        ok = all(f == n for f, n in naive.values()) and all(f == 0 for f, _ in sever.values())
        self.numbers["plaintext_hits"] = {k: v[0] for k, v in sever.items()}
        self.checklist.mark(
            "disk",
            ok,
            "naive copy: "
            + ", ".join(f"{k} {f}/{n}" for k, (f, n) in naive.items())
            + "; SEVER-DB: "
            + ", ".join(f"{k} {f}/{n}" for k, (f, n) in sever.items()),
        )
        return Disk(len(files), sum(p.stat().st_size for p in files), naive, sever)

    # -- restart and crash ------------------------------------------------------------------------

    def restart(self) -> tuple[int, int, bool]:
        b = self.backend
        before = b.total()
        b.close()
        b.open()
        after = b.total()
        live = b.replay().groups
        gone = all(n not in live for _, n in self.deleted_this_session[-20:])
        self.checklist.mark(
            "restart",
            before == after and gone and not b.mismatches(),
            f"{before} records before, {after} after; deleted ones still absent: {gone}",
        )
        return before, after, gone

    def crash(self, count: int = 200) -> Crashed:
        """Closes the database; a second process inserts the next ``count`` passages, writing each
        acknowledged one down; once half are acknowledged it is killed with SIGKILL. Recovery,
        then every acknowledged insert is looked for."""
        self.ensure_spares(count)
        b, c = self.backend, self.corpus
        before = b.total()
        b.close()
        acks = self.work / "acks.txt"
        acks.unlink(missing_ok=True)
        start = b.index.loaded
        count = min(count, len(c.ids) - start)
        cmd = [sys.executable, "-m", "sever_studio", "crash-child", "--data", self.data]
        cmd += ["--rows", str(len(c.ids)), "--work", str(self.work)]
        cmd += ["--start", str(start), "--count", str(count)]
        cmd += ["--dev"] if b.dev else []
        paths = [str(self.root / "python"), str(Path(__file__).resolve().parents[1])]
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(paths)}
        child = subprocess.Popen(cmd, cwd=self.root, env=env)
        deadline = time.monotonic() + 600
        first: float | None = None
        while time.monotonic() < deadline and child.poll() is None:
            n = len(acks.read_text("utf-8").splitlines()) if acks.exists() else 0
            if n and first is None:
                first = time.monotonic()
            if n >= count // 2 and first is not None:
                # M5: at a random moment within one average insert, so the kill can land inside
                # an insert, before or after its commit, not only between two inserts
                per = (time.monotonic() - first) / max(1, n - 1)
                time.sleep(random.uniform(0.0, per))
                os.kill(child.pid, signal.SIGKILL)
                break
            time.sleep(0.002)
        killed = child.wait() == -signal.SIGKILL
        acked = [
            (f[0], f[1], int(f[2]))
            for ln in (acks.read_text("utf-8").splitlines() if acks.exists() else [])
            if len(f := ln.split("\t")) == 3
        ]
        nxt = start + len(acked)
        in_flight = c.ids[nxt] if killed and nxt < start + count else None
        b.open()
        committed = b.reconcile(acked, in_flight)
        live = b.replay().groups
        missing = [r for r, _, lsn in acked if lsn not in live]
        grew = b.total() - before
        ok = killed and bool(acked) and not missing and not b.mismatches()
        self.numbers.update(crash_acked=len(acked), crash_missing=len(missing), crash_killed=killed)
        self.checklist.mark(
            "crash",
            ok,
            f"killed after {len(acked)} acknowledged inserts; after recovery all there: "
            f"{not missing}; the insert in flight had committed: {committed}",
        )
        return Crashed(len(acked), in_flight, committed, killed, len(missing), grew)

    # -- proofs, sabotage, evidence ---------------------------------------------------------------

    def proof(self, name: str, live: str | None) -> proofs.Proof | None:
        """``live``: ``synthetic`` or ``nq-10k`` to run it now; ``None`` for the recorded run."""
        p = (
            proofs.run(self.root, name, live, self.work / "proofs")
            if live
            else proofs.load_recorded(self.root, name)
        )
        if p is None:
            return None
        checks = dict(p.checks)
        src = f" ({p.source})"
        how = "live" if live else "recorded"
        if name == "idea":
            first = [c for c in checks if c.startswith("every touched group")]
            self.checklist.mark(
                "exact",
                all(checks[c] for c in first) and checks.get("no untouched group changed", False),
                (first[0] if first else "") + src,
                how,
            )
            ghost = [c for c in checks if "SEVER's sum" in c or "float" in c or "soft delete" in c]
            self.checklist.mark(
                "ghost",
                all(checks[c] for c in ghost),
                "SEVER 0; float ≠; soft delete keeps" + src,
                how,
            )
            # the race's claim, shown by the engine's own program (C3): its sum is bit-identical
            # to the survivors-only sum and the float running mean is not
            drift = [c for c in checks if "SEVER's sum" in c or "float running mean" in c]
            self.checklist.mark(
                "race",
                bool(drift) and all(checks[c] for c in drift),
                "sever-demo idea: integer sum bit-identical, float mean not" + src,
                how,
            )
        elif name == "durable":
            self.checklist.mark("durable", p.ok, f"{len(p.checks)} checks" + src, how)
        elif name == "receipt":
            self.checklist.mark("chain", p.ok, f"{len(p.checks)} checks" + src, how)
        elif name == "erase":
            ch = list(checks.items())
            self.checklist.mark("shred", all(ok for _, ok in ch[:3]), ch[2][0] + src)
            self.checklist.mark("phasec", ch[3][1], ch[3][0] + src)
            self.checklist.mark("leak", ch[4][1], ch[4][0] + src)
        return p

    def sabotage(self, sb: str, on_line: Callable[[str], None] | None = None) -> sabotage.Outcome:
        out = sabotage.run(self.root, sb, on_line)
        self.checklist.mark("sabotage", out.caught, f"{sb}: {out.summary}")
        return out

    def evidence(self) -> tuple[list[evidence.Line], list[dict[str, Any]], list[dict[str, Any]]]:
        lines = evidence.headlines(self.root)
        led = evidence.ledger(self.root)
        fair = evidence.fairness(self.root)
        self.checklist.mark(
            "evidence",
            len(lines) >= 4 and bool(led),
            f"{len(lines)} reports, {len(led)} ledger runs",
        )
        return lines, led, fair

    # -- the live demonstrations (wow.py) --------------------------------------------------------

    def climb(self, lsn: int) -> tuple[wow.Certificate, list[wow.Step], bytes, bool]:
        """The receipt's insert leaf, hashed up its RFC 9162 path to the signed root (§11.2)."""
        cert = wow.parse((self.backend.receipts / f"{lsn}.cert").read_bytes())
        steps, root, valid = wow.climb(cert.leaf, cert.leaf_index, cert.tree_size, cert.path)
        ok = valid and root == cert.root and cert.witnesses >= 4
        self.checklist.mark(
            "climb",
            ok,
            f"receipt #{lsn}: {len(steps)} hashes from leaf {cert.leaf_index} to the root of "
            f"{cert.tree_size} leaves; {'equals' if root == cert.root else 'DIFFERS FROM'} the "
            f"signed root; {cert.witnesses} witnesses",
        )
        return cert, steps, root, ok

    def attack_lab(self, lsn: int) -> list[wow.Attack]:
        """Forgery attempts on receipt ``lsn``, judged by sever-verify (§11.3)."""
        mine = (self.backend.receipts / f"{lsn}.cert").read_bytes()
        key = wow.parse(mine).user_key
        other = None
        for n in reversed(self.backend.index.receipts):
            p = self.backend.receipts / f"{n}.cert"
            if n != lsn and p.exists() and wow.parse(p.read_bytes()).user_key != key:
                other = p.read_bytes()
                break
        out = wow.attacks(self.root, self.work, mine, self.backend.live.anchors(), key, other)
        caught = sum(a.caught for a in out)
        self.checklist.mark(
            "attacks", caught == len(out) >= 4, f"{caught} of {len(out)} attempts caught"
        )
        return out

    def operator_forgeries(self) -> list[wow.Forgery]:
        """Part 3's register of forgeries made with the operator's own keys (P3-T2), judged by
        sever-verify: each must be rejected at a step its register row lists."""
        return wow.operator_forgeries(self.root, self.work)

    def crash_test_person(self, size: int = 0) -> tuple[str, list[str]]:
        """A person with many records (the next spare passages), for the killed deletion."""
        size = size or (40 if self.data == "nq" else 16)
        self.ensure_spares(size)
        b, c = self.backend, self.corpus
        account = f"Crash-test person {len(b.index.receipts) + b.index.loaded}"
        ids = []
        for _ in range(size):
            i = b.index.loaded
            if i >= len(c.ids):
                break
            b.insert(c.ids[i], c.vectors[i], account, save=False)
            b.index.records[c.ids[i]].account = account
            b.index.loaded = i + 1
            ids.append(c.ids[i])
        b.save()
        return account, ids

    def crash_delete(self, account: str, fraction: float) -> wow.CrashDelete:
        """Deletes ``account`` in a second process, killed ``fraction`` of the way through the
        expected time; all or nothing after recovery (§12.5)."""
        ids = self.backend.accounts().get(account, [])
        if "delete_user_ms_per_record" not in self.numbers:
            # Learn how long one person's deletion takes: time a throwaway one of the same size.
            _, spare = self.crash_test_person(len(ids))
            t0 = time.perf_counter()
            self.backend.forget_ids(spare)
            took = (time.perf_counter() - t0) * 1000
            self.numbers["delete_user_ms_per_record"] = round(took / max(1, len(spare)), 2)
        per = float(self.numbers["delete_user_ms_per_record"])
        r = wow.crash_delete(self, ids, account, fraction * per * max(1, len(ids)))
        if r.took_ms is not None:  # learn how long a whole deletion takes, to land inside it
            self.numbers["delete_user_ms_per_record"] = round(r.took_ms / max(1, len(ids)), 2)
        if r.outcome in ("none", "all"):
            ok = r.killed and not self.backend.mismatches()
            self.checklist.mark(
                "crashdelete",
                ok,
                f"{account}: killed at {r.planned_ms:.0f} ms; {r.outcome} of {r.records} records "
                "deleted after recovery",
            )
        elif r.outcome == "partial":
            self.checklist.mark(
                "crashdelete", False, f"{r.deleted} of {r.records} deleted: NOT all or nothing"
            )
        return r

    def race(self, cycles: int, report: Callable[..., None] | None = None) -> wow.RaceResult:
        """Studio's numpy model of §4–5 (not the engine): remove and re-add members ``cycles``
        times; float32 against Q24. It ticks nothing: the row's check is Part 1's own program
        (``proof("idea", ...)``)."""
        r = wow.race_all(self.corpus.vectors[:200], cycles, report)
        self.numbers["race_model_differing"] = r.differing[-1][1] if r.differing else 0
        return r

    def report(self) -> Path:
        return self.checklist.save(self.work, self.numbers)


def crash_child(
    root: Path, data: str, rows: int, work: Path, start: int, count: int, dev: bool
) -> int:
    """The process that is killed: inserts and writes down each insert the database acknowledged,
    with where it landed."""
    corpus = load(root, data, rows)  # the parent passes its own corpus size
    b = Backend(corpus, work, dev)
    b.open()
    with (work / "acks.txt").open("a", encoding="utf-8") as acks:
        for i in range(start, min(start + count, len(corpus.ids))):
            r = b.insert(corpus.ids[i], corpus.vectors[i], corpus.accounts[i], save=False)
            acks.write(f"{r.rid}\t{r.placement}\t{r.lsn}\n")
            acks.flush()
            os.fsync(acks.fileno())
    b.close()
    return 0
