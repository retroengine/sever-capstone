"""Every demonstration Studio can give, as plain functions: each does its thing through the public
SDK or the separate programs, checks its claim, and ticks its row of the checklist. The window only
draws what these return; the tests call them directly.
"""

import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
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

#: Rows kept unstored after the prepared ones: filling the holding area, the writer that is killed.
SPARE = 3000
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
    neighbours: list[str]


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
    biggest: list[tuple[str, int]] = field(default_factory=list)


class Studio:
    def __init__(self, root: Path, data: str, work: Path, dev: bool, rows: int) -> None:
        self.root = root.resolve()
        self.data = data
        self.work = work.resolve()
        self.rows = rows
        self.corpus: Corpus = load(root, data, rows + SPARE)
        self.backend = Backend(self.corpus, self.work, dev)
        self.checklist = Checklist()
        self.numbers: dict[str, Any] = {"data": data, "rows": rows}
        self.coords = layout.fit(self.corpus.vectors, cache=work)
        self.extra_xy: dict[str, tuple[float, float]] = {}
        #: the map by group (each group a disc of its own colour) or by meaning (t-SNE)
        self.by_group = True
        self.groups = layout.GroupMap(work / "group-map.json", self.corpus.spawn_target)
        self._spot: dict[tuple[str, str], tuple[float, float]] = {}
        self._frozen: npt.NDArray[np.float64] | None = None
        self.deleted_this_session: list[str] = []
        self._encoder: Any = None

    # -- the map ----------------------------------------------------------------------------------

    def xy(self, rid: str, group: str | None = None) -> tuple[float, float]:
        """Where a record is drawn: in its group's disc (by group), or by meaning. ``group``
        overrides the index's (the replay draws records that may since have gone)."""
        if self.by_group:
            if group is None:
                rec = self.backend.index.records.get(rid)
                group = rec.group if rec is not None else None
            if group is not None and group != HOLDING:
                spot = self._spot.get((rid, group))
                if spot is None:
                    if group not in self.groups.anchors:
                        self.place_groups()
                    if group not in self.groups.anchors:
                        return self.meaning_xy(rid)
                    spot = self.groups.point(group, self.meaning_xy(rid))
                    self._spot[(rid, group)] = spot
                return spot
        return self.meaning_xy(rid)

    def place_groups(self) -> None:
        """Gives every group in the index a place and a colour, if it has none yet: where its real
        centre μ falls on the map by meaning, then pushed clear of the others."""
        members: dict[str, list[tuple[float, float]]] = {}
        ids: dict[str, list[str]] = {}
        for rid, rec in self.backend.index.records.items():
            if rec.group != HOLDING:
                members.setdefault(rec.group, []).append(self.meaning_xy(rid))
                ids.setdefault(rec.group, []).append(rid)
        centres: dict[str, tuple[float, float]] = {}
        for g in members:
            if g in self.groups.anchors:
                continue
            if not g.startswith("frozen-"):  # §7.5: S / n of the group as first seen, then kept
                n, total, _ = self.group_stats(g)
                self.groups.mu[g] = list(total.astype(np.float64) / 2**24 / max(n, 1))
            mu = self.centre(g)
            if mu is not None:
                centres[g] = layout.place(mu.astype(np.float32), self.corpus.vectors, self.coords)
        self.groups.ensure(members, centres)

    def centre(self, group: str) -> npt.NDArray[np.float64] | None:
        """The group's centre μ as the database routes and searches with it: a frozen group's from
        the partition (§6, fitted once by k-means), a spawned group's S / n at creation (§7.5)."""
        if group.startswith("frozen-"):
            if self._frozen is None:
                from sever_partition.artefact import decode

                self._frozen = decode(self.corpus.artefact.read_bytes()).centroids
            k = int(group.split("-")[1])
            return self._frozen[k] if k < len(self._frozen) else None
        mu = self.groups.mu.get(group)
        return np.asarray(mu, np.float64) if mu is not None else None

    def distances(self, rid: str) -> tuple[float, float] | None:
        """A record's distance to its own group's centre and to the nearest other centre, in the
        384 dimensions the database measures (§7.1)."""
        rec = self.backend.index.records.get(rid)
        if rec is None or rec.group == HOLDING:
            return None
        x = self.backend.vector_of(rid).astype(np.float64)
        own = self.centre(rec.group)
        if own is None:
            return None
        others = [
            float(np.sqrt(((x - mu) ** 2).sum()))
            for g in self.groups.anchors
            if g != rec.group and (mu := self.centre(g)) is not None
        ]
        return float(np.sqrt(((x - own) ** 2).sum())), min(others, default=float("nan"))

    def centres(self) -> list[tuple[str, float, float, int]]:
        """Each group with members: where its centre μ is drawn (fixed, as μ is: §6, §7.5) and its
        size."""
        sizes: dict[str, int] = {}
        for rec in self.backend.index.records.values():
            if rec.group != HOLDING:
                sizes[rec.group] = sizes.get(rec.group, 0) + 1
        if any(g not in self.groups.anchors for g in sizes):
            self.place_groups()
        return [(g, *self.groups.anchors[g][:2], n) for g, n in sizes.items()]

    def group_stats(self, group: str) -> tuple[int, npt.NDArray[np.int64], npt.NDArray[np.float64]]:
        """A group's count ``n``, exact sum ``S`` of its members' Q24 integers (§4.2, §5) and mean
        ``S / n`` back in real numbers, from the vectors Studio stored. The database keeps ``S``
        encrypted; these are recomputed here, not read from it."""
        b = self.backend
        rids = [r for r, rec in b.index.records.items() if rec.group == group]
        d = self.corpus.d
        if not rids:
            return 0, np.zeros(d, np.int64), np.zeros(d, np.float64)
        q = wow.quantise(np.stack([b.vector_of(r) for r in rids]).astype(np.float32))
        total = q.astype(np.int64).sum(axis=0)
        return len(rids), total, total.astype(np.float64) / len(rids) / 2**24

    def meaning_xy(self, rid: str) -> tuple[float, float]:
        if rid in self.extra_xy:
            return self.extra_xy[rid]
        i = self.corpus.position.get(rid)
        if i is not None:
            return float(self.coords[i, 0]), float(self.coords[i, 1])
        rec = self.backend.index.records.get(rid)
        if rec is not None and rec.vector is not None:
            p = layout.place(np.asarray(rec.vector, np.float32), self.corpus.vectors, self.coords)
            self.extra_xy[rid] = p
            return p
        return 0.0, 0.0

    def encode(self, text: str) -> npt.NDArray[np.float32]:
        if self.data == "synthetic":
            fixed: npt.NDArray[np.float32] = fixture_encode(text, self.corpus.d)[0]
            return fixed
        if self._encoder is None:
            from .encoder import Encoder

            self._encoder = Encoder(self.work.parent / "models")
        row: npt.NDArray[np.float32] = self._encoder.encode([text])[0]
        return row

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
        art, data = self.corpus.artefact_encoder(), self.corpus.encoder
        if self.data == "synthetic":
            mine = FIXTURE_ENCODER
        else:
            from .encoder import NAME

            mine = NAME
        ok = art == data == mine
        self.checklist.mark("encoder", ok, f"artefact {art}; data {data}; typed text {mine}")
        return art, data, mine

    def clusters(self) -> dict[str, int]:
        b = self.backend
        st = b.live.stats(b.cid)
        problems = b.mismatches()
        ok = not problems and st["frozen"] > 0
        detail = (
            f"{st['frozen']} frozen + {st['spawned']} spawned groups,"
            f" N {st['N']}, holding {st['holding']}"
        )
        self.checklist.mark("clusters", ok, detail if ok else "; ".join(problems))
        return dict(st)

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
        sims = self.corpus.vectors[: b.index.loaded].astype(np.float64) @ vec.astype(np.float64)
        near = [self.corpus.ids[i] for i in np.argsort(-sims)[:3]]
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
        return Added(rid, xy, res, near)

    def _routed(self, res: Inserted) -> None:
        problems = self.backend.mismatches()
        self.checklist.mark(
            "routing",
            not problems,
            f"{res.rid} → {res.placement}" if not problems else "; ".join(problems),
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
        stored = b.stored(rid, vec, b.index.records[rid].account)
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
        self.deleted_this_session += rids
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
        vecs = [b.vector_of(r).astype("<f4").tobytes() for r in sample]
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
        sizes = sorted(
            ((str(p.relative_to(self.work)), p.stat().st_size) for p in files), key=lambda x: -x[1]
        )
        return Disk(len(files), sum(s for _, s in sizes), naive, sever, sizes[:8])

    # -- restart and crash ------------------------------------------------------------------------

    def restart(self) -> tuple[int, int, bool]:
        b = self.backend
        before = b.total()
        b.close()
        b.open()
        after = b.total()
        gone = all(b.absent(r) for r in self.deleted_this_session[-20:])
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
        b, c = self.backend, self.corpus
        before = b.total()
        b.close()
        acks = self.work / "acks.txt"
        acks.unlink(missing_ok=True)
        start = b.index.loaded
        count = min(count, len(c.ids) - start)
        cmd = [sys.executable, "-m", "sever_studio", "crash-child", "--data", self.data]
        cmd += ["--rows", str(self.rows), "--work", str(self.work)]
        cmd += ["--start", str(start), "--count", str(count)]
        cmd += ["--dev"] if b.dev else []
        paths = [str(self.root / "python"), str(Path(__file__).resolve().parents[1])]
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(paths)}
        child = subprocess.Popen(cmd, cwd=self.root, env=env)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline and child.poll() is None:
            if acks.exists() and len(acks.read_text("utf-8").splitlines()) >= count // 2:
                os.kill(child.pid, signal.SIGKILL)
                break
            time.sleep(0.005)
        killed = child.wait() == -signal.SIGKILL
        acked = [
            (ln.split("\t")[0], ln.split("\t")[1])
            for ln in (acks.read_text("utf-8").splitlines() if acks.exists() else [])
            if "\t" in ln
        ]
        nxt = start + len(acked)
        in_flight = c.ids[nxt] if killed and nxt < start + count else None
        b.open()
        committed = b.reconcile(acked, in_flight)
        missing = [
            r
            for r, _ in acked
            if not b.stored(r, c.vectors[c.position[r]], c.accounts[c.position[r]])
        ]
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
        if name == "idea":
            first = [c for c in checks if c.startswith("every touched group")]
            self.checklist.mark(
                "exact",
                all(checks[c] for c in first) and checks.get("no untouched group changed", False),
                (first[0] if first else "") + src,
            )
            ghost = [c for c in checks if "SEVER's sum" in c or "float" in c or "soft delete" in c]
            self.checklist.mark(
                "ghost", all(checks[c] for c in ghost), "SEVER 0; float ≠; soft delete keeps" + src
            )
        elif name == "durable":
            self.checklist.mark("durable", p.ok, f"{len(p.checks)} checks" + src)
        elif name == "receipt":
            self.checklist.mark("chain", p.ok, f"{len(p.checks)} checks" + src)
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

    def crash_test_person(self, size: int = 0) -> tuple[str, list[str]]:
        """A person with many records (the next spare passages), for the killed deletion."""
        b, c = self.backend, self.corpus
        size = size or (40 if self.data == "nq" else 16)
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
        """§4–5 modelled: remove and re-add members ``cycles`` times; float32 against Q24."""
        v = self.corpus.vectors[:200]
        r = wow.race_all(v, cycles, report)
        diff = r.differing[-1][1] if r.differing else 0
        self.checklist.mark(
            "race",
            r.identical and diff > 0,
            f"{cycles:,} cycles: the float mean changed in {diff} of {v.shape[1]} numbers; the "
            f"integer sum is {'bit-identical' if r.identical else 'CHANGED'}",
        )
        return r

    def report(self) -> Path:
        return self.checklist.save(self.work, self.numbers)


def crash_child(
    root: Path, data: str, rows: int, work: Path, start: int, count: int, dev: bool
) -> int:
    """The process that is killed: inserts and writes down each insert the database acknowledged,
    with where it landed."""
    corpus = load(root, data, rows + SPARE)
    b = Backend(corpus, work, dev)
    b.open()
    with (work / "acks.txt").open("a", encoding="utf-8") as acks:
        for i in range(start, min(start + count, len(corpus.ids))):
            r = b.insert(corpus.ids[i], corpus.vectors[i], corpus.accounts[i], save=False)
            acks.write(f"{r.rid}\t{r.placement}\n")
            acks.flush()
            os.fsync(acks.fileno())
    b.close()
    return 0
