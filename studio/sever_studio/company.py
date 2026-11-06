"""Acme Notes on SEVER-DB: a small company app that stores a person's notes, answers questions from
them, and forgets the person on request. Every number and every word of text comes from a real
call to the SDK, and each call is logged with its result (``calls``).

- ``store_notes``: each note encoded, signed with the person's key, inserted with its text (§3.4,
  §15.1); where the engine put it, its log position, and whether the engine's own routing code
  predicted that place (§7.3, DB-108).
- ``retrieve``: the question encoded, ``search`` (§8), the groups the engine's search code opened
  (§8.1, DB-108), then ``passage()`` for each hit: the text comes only from the engine (§16.1).
- ``forget``: ``delete_user`` for all the person's notes, all or nothing (§12.5), with each touched
  group's ``n`` before and after and one receipt per note (§11).
- ``gone_checks``: after the deletion, her own words searched again, ``passage()`` read for each of
  her IDs, the database's files searched byte by byte for her text and vectors (§13.2), and every
  receipt checked by ``sever-verify`` (§11.3).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import numpy as np
import numpy.typing as npt

from . import assistant, tools
from .actions import Deleted, Studio
from .backend import HOLDING
from .ordinary import Ordinary

T = TypeVar("T")
Vector = npt.NDArray[np.float32]


@dataclass(frozen=True)
class Call:
    """One real call to the database: what, a summary of its arguments, its result, its time."""

    what: str
    args: str
    result: str
    ms: float


@dataclass(frozen=True)
class Note:
    rid: str
    lsn: int | None
    placement: str
    #: the engine's routing code predicted this place before the insert (§7.3, DB-108)
    agreed: bool

    @property
    def waiting(self) -> bool:
        return self.placement == HOLDING


@dataclass(frozen=True)
class Hit:
    n: int
    rid: str
    distance: float
    #: the passage as ``passage()`` returned it, or ``None`` when the engine has none
    text: str | None
    account: str
    mine: bool


@dataclass(frozen=True)
class Retrieved:
    question: str
    hits: list[Hit]
    opened: list[str]


@dataclass
class Scan:
    """Her notes searched for in the database's own files: ``kind -> (found, looked for)``."""

    files: int
    hits: dict[str, tuple[int, int]]


@dataclass
class Chroma:
    """The same person forgotten on the ordinary store, measured the same way."""

    deleted: int
    found_by_query: list[str]
    readable: list[str]
    before: Scan
    after: Scan


@dataclass
class Gone:
    name: str
    deleted: Deleted
    #: her IDs that a search with her own words still returns
    found_by_search: list[str]
    #: her IDs whose ``passage()`` still returns text
    readable: list[str]
    before: Scan
    after: Scan
    #: ``(log position, sever-verify's verdict, accepted)`` for each receipt
    receipts: list[tuple[int, str, bool]] = field(default_factory=list)
    chroma: Chroma | None = None

    @property
    def clean(self) -> bool:
        return (
            not self.found_by_search
            and not self.readable
            and all(f == 0 for f, _ in self.after.hits.values())
            and bool(self.receipts)
            and all(ok for _, _, ok in self.receipts)
        )


class Company:
    def __init__(self, studio: Studio, ordinary: Ordinary | None = None) -> None:
        self.studio = studio
        #: the same app on Chroma, beside it (``None``: shown as not set up)
        self.ordinary = ordinary
        self.calls: list[Call] = []
        #: what each person stored this session: her notes' IDs, texts and vectors, kept in memory
        #: only for the checks after her deletion (never written anywhere)
        self.people: dict[str, list[tuple[str, str, Vector]]] = {}

    # -- the call log ---------------------------------------------------------------------------

    def _call(self, what: str, args: str, fn: Callable[[], T], result: Callable[[T], str]) -> T:
        t0 = time.perf_counter()
        out = fn()
        ms = (time.perf_counter() - t0) * 1000
        self.calls.append(Call(what, args, result(out), round(ms, 1)))
        return out

    # -- storing --------------------------------------------------------------------------------

    def store_notes(self, name: str, notes: list[str]) -> list[Note]:
        s, b = self.studio, self.studio.backend
        out = []
        for text in (t.strip() for t in notes):
            if not text:
                continue
            added = self._call(
                "insert",
                f"{name}'s note, {len(text.encode('utf-8'))} bytes of text, signed with "
                f"{name}'s key",
                lambda text=text: s.add_mine(name, text),  # type: ignore[misc]
                lambda a: f"{a.rid} → {a.result.placement} at log #{a.result.lsn}",
            )
            res = added.result
            vec = b.vector_of(added.rid)
            self.people.setdefault(name, []).append((added.rid, text, vec))
            agreed = res.predicted is not None and added.rid not in b.routing_disagreed
            out.append(Note(added.rid, res.lsn, res.placement, agreed))
            if self.ordinary is not None:
                self.ordinary.store(name, [added.rid], [text], [vec])
        return out

    def notes_of(self, name: str) -> list[str]:
        """Her live notes, as the app's index has them."""
        b = self.studio.backend
        return [r for r in b.accounts().get(name, []) if b.index.records[r].mine]

    def let_others_write(self) -> int:
        """Other users' notes (the dataset's passages) until the holding area flushes (§7.4)."""
        out = self._call(
            "insert × many",
            "other users' notes, until the holding area flushes",
            lambda: self.studio.fill_bucket("flush"),
            lambda r: (
                f"{len(r)} inserted"
                + (f"; flushed into {r[-1].flush.group}" if r and r[-1].flush else "")
            ),
        )
        return len(out)

    # -- asking ---------------------------------------------------------------------------------

    def retrieve(self, question: str, k: int = 5) -> Retrieved:
        s, b = self.studio, self.studio.backend
        vec = s.encode(question)
        found = self._call(
            "search",
            f"the question's {len(vec)} numbers, k = {k}",
            lambda: b.search(vec, k),
            lambda h: f"{len(h)} hits: " + ", ".join(r for r, _ in h),
        )
        explained = self._call(
            "explain_search",
            "the same query, against every group's centre",
            lambda: s.search_explained(vec),
            lambda e: f"{e['probed']} of {len(e['ranked'])} groups opened",
        )
        opened = _opened(explained)
        hits = []
        for n, (rid, dist) in enumerate(found, 1):
            raw = self._call(
                "passage",
                rid,
                lambda rid=rid: b.live.passage(b.cid, rid),  # type: ignore[misc]
                lambda p: "absent" if p is None else f"{len(p)} bytes",
            )
            rec = b.index.records.get(rid)
            hits.append(
                Hit(
                    n,
                    rid,
                    float(dist),
                    raw.decode("utf-8") if raw is not None else None,
                    rec.account if rec else "",
                    bool(rec and rec.mine),
                )
            )
        return Retrieved(question, hits, opened)

    def ask(self, question: str, k: int = 5) -> tuple[Retrieved, assistant.Answer]:
        """Retrieve, then the assistant writes from exactly the passages ``passage()`` returned."""
        got = self.retrieve(question, k)
        passages = [h.text for h in got.hits if h.text is not None]
        ans = assistant.answer(question, passages)
        self.studio.checklist.mark(
            "assistant",
            bool(got.hits) and len(passages) == len(got.hits),
            f"{len(got.hits)} hits, each passage read with passage(); "
            + ("answer by the model" if ans.ai else ans.note),
        )
        return got, ans

    # -- forgetting -----------------------------------------------------------------------------

    def scan(self, name: str) -> Scan:
        """Her notes' IDs, text and vectors searched for in every file of the database (§13.2)."""
        b = self.studio.backend
        mine = self.people.get(name, [])
        needles = tools.needles_of(
            [r for r, _, _ in mine], [t for _, t, _ in mine], [v for _, _, v in mine]
        )
        files = tools.files_under([b.data, b.keys])
        return Scan(len(files), tools.count_hits(files, needles))

    def forget(self, name: str) -> Gone:
        s, b = self.studio, self.studio.backend
        before = self.scan(name)
        rids = self.notes_of(name)
        deleted = self._call(
            "delete_user",
            f"{len(rids)} notes of {name}, in one transaction",
            lambda: s.delete(rids, key="forget"),
            lambda d: (
                f"{len(d.rids)} deleted, receipts " + (", ".join(f"#{n}" for n in d.lsns) or "none")
            ),
        )
        mine = self.people.get(name, [])
        ids = {r for r, _, _ in mine}
        found = []
        for _rid, text, _ in mine:
            hits = self._call(
                "search",
                f"{name}'s own words",
                lambda text=text: b.search(s.encode(text), 10),  # type: ignore[misc]
                lambda h: f"{len(h)} hits",
            )
            found += [r for r, _ in hits if r in ids]
        readable = []
        for rid, _, _ in mine:
            raw = self._call(
                "passage",
                rid,
                lambda rid=rid: b.live.passage(b.cid, rid),  # type: ignore[misc]
                lambda p: "absent" if p is None else f"{len(p)} bytes",
            )
            if raw is not None:
                readable.append(rid)
        after = self.scan(name)
        receipts = []
        for lsn in deleted.lsns:
            v = s.verify(lsn)
            receipts.append((lsn, v.verdict, v.code == 0 and v.verdict == "ACCEPT"))
        gone = Gone(name, deleted, sorted(set(found)), readable, before, after, receipts)
        gone.chroma = self._forget_on_chroma(name)
        s.checklist.mark(
            "gone",
            gone.clean,
            f"{len(receipts)} receipts ACCEPT; search finds {len(gone.found_by_search)}, "
            f"passage() reads {len(readable)}; in the files after: "
            + ", ".join(f"{k} {f}/{n}" for k, (f, n) in after.hits.items()),
        )
        return gone

    def _forget_on_chroma(self, name: str) -> Chroma | None:
        o = self.ordinary
        mine = self.people.get(name, [])
        if o is None or not mine:
            return None
        ids, texts, vecs = [r for r, _, _ in mine], [t for _, t, _ in mine], [v for _, _, v in mine]
        before = o.scan(ids, texts, vecs)
        o.delete(ids)
        found = sorted({r for v in vecs for r in o.query(v, 10) if r in set(ids)})
        readable = o.read(ids)
        after = o.scan(ids, texts, vecs)
        c = Chroma(
            len(ids),
            found,
            readable,
            Scan(before.files, before.hits),
            Scan(after.files, after.hits),
        )
        self.studio.checklist.mark(
            "compare",
            True,
            f"Chroma: {len(ids)} deleted; query finds {len(found)}, get() reads {len(readable)}; "
            "in its files after: " + ", ".join(f"{k} {f}/{n}" for k, (f, n) in after.hits.items()),
        )
        return c

    # -- the engine's state ---------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        """Records, groups, the holding area and the log, as the engine reports them."""
        b = self.studio.backend
        st = b.live.stats(b.cid)
        cp = b.live.latest_log_checkpoint()
        return {
            "records": st["N"],
            "frozen groups": st["frozen"],
            "spawned groups": st["spawned"],
            "holding area": st["holding"],
            "log leaves": cp.tree_size,
            "latest checkpoint": f"size {cp.tree_size}, root {cp.root.hex()[:16]}…",
        }


def _opened(explained: dict[str, Any]) -> list[str]:
    """The group IDs the engine's search code opened (§8.1 step 2): the first ``probed`` of the
    groups it ranked by their centre's distance to the query."""
    return [str(g) for g, _ in explained["ranked"][: explained["probed"]]]
