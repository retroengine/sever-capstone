"""Studio's application backend: what a real service would hold beside the database.

It owns one account key per account (``accounts.keys``, mode 0600, never shown), inserts through
``prepare_insert``, searches, deletes, and keeps each deletion certificate for the person it belongs
to. It also keeps the application's own index of its records (``index.json``: ID, account, where the
record landed), because the database never hands record IDs or passages back (§13.2). Everything
goes through the public SDK ``sever_db``.

Where a record lands comes from the database itself: ``Receipt.placement`` (§5.1 text form). A
record placed in the holding area stays there until the insert that brings it to the spawn size,
which flushes all of them into one new spawned group (§7.4); that insert's own placement names the
new group, whose ID is recomputed here from its members (§7.5) and must match.
"""

import fcntl
import hashlib
import json
import os
import shutil
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt
from sever_db import (
    Database,
    Deletion,
    DuplicateRecord,
    InsertRequest,
    PlatformUnsafe,
    Receipt,
    UserKey,
    prepare_insert,
)

from .corpus import Corpus

HOLDING = "holding"
Progress = Callable[[int, int], None]


class WorkInUseError(Exception):
    """Another Studio holds this work directory."""


def spawn_id(members: Sequence[str]) -> str:
    """§7.5: ``spawn-`` and the first 16 hex characters of SHA-256 over the founding records' IDs,
    ascending by bytes, each as ``u16be(len) ‖ id``."""
    h = hashlib.sha256()
    for rid in sorted(m.encode("utf-8") for m in members):
        h.update(len(rid).to_bytes(2, "big") + rid)
    return "spawn-" + h.hexdigest()[:16]


def lock(work: Path) -> int:
    """One Studio per work directory: an exclusive lock beside it, held until the process exits."""
    work.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(work.parent / f".{work.name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise WorkInUseError(f"{work} is in use by another Studio") from None
    return fd


@dataclass
class Record:
    """One live record as the application knows it. ``text`` is kept only for records typed in
    Studio (the dataset's own passages are read from the dataset)."""

    account: str
    group: str
    mine: bool = False
    text: str | None = None
    vector: list[float] | None = None


@dataclass
class Flush:
    """The holding area became a spawned group (§7.4)."""

    group: str
    members: list[str]
    expected: str

    @property
    def id_matches(self) -> bool:
        return self.group == self.expected


@dataclass
class Inserted:
    rid: str
    lsn: int | None
    placement: str
    retried: bool
    flush: Flush | None


@dataclass
class Index:
    """``index.json``: the application's own state; no key, ``r_t`` or dataset passage in it."""

    cid: str = ""
    loaded: int = 0
    records: dict[str, Record] = field(default_factory=dict)
    holding: list[str] = field(default_factory=list)
    receipts: list[int] = field(default_factory=list)
    flushes: int = 0


class Backend:
    def __init__(self, corpus: Corpus, work: Path, dev: bool) -> None:
        self.corpus = corpus
        self.work = work
        self.dev = dev
        self.data = work / "data"
        self.keys = work / "keys"
        self.receipts = work / "receipts"
        self.keystore = work / "accounts.keys"
        self.index_file = work / "index.json"
        self.db: Database | None = None
        self.index = Index()
        self.users: dict[str, UserKey] = {}
        self.refused: str | None = None

    # -- opening and state ------------------------------------------------------------------------

    def open(self) -> Database:
        """Opens (recovering, or creating) the database. An unsafe machine is refused (§12.8–12.9);
        with ``dev`` the memory override is used, and the database lists it in ``startup``."""
        self.work.mkdir(parents=True, exist_ok=True)
        self.receipts.mkdir(exist_ok=True)
        try:
            self.db = Database.open(self.data, self.keys, d=self.corpus.d)
            self.refused = None
        except PlatformUnsafe as e:
            self.refused = str(e)
            if not self.dev:
                raise
            self.db = Database.open(self.data, self.keys, d=self.corpus.d, allow_unsafe_memory=True)
        self._load_index()
        self._load_keys()
        return self.db

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None

    @property
    def live(self) -> Database:
        if self.db is None:
            raise RuntimeError("the database is not open")
        return self.db

    @property
    def cid(self) -> str:
        if not self.index.cid:
            self.index.cid = self.live.create_collection(
                self.corpus.artefact, spawn_target=self.corpus.spawn_target
            )
            self.save()
        return self.index.cid

    def _load_index(self) -> None:
        if not self.index_file.exists():
            self.index = Index()
            return
        raw = json.loads(self.index_file.read_text("utf-8"))
        raw["records"] = {k: Record(**v) for k, v in raw["records"].items()}
        self.index = Index(**raw)

    def save(self) -> None:
        doc = asdict(self.index)
        tmp = self.index_file.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, separators=(",", ":"))
        tmp.replace(self.index_file)

    def wipe(self) -> None:
        self.close()
        shutil.rmtree(self.work, ignore_errors=True)
        self.index = Index()
        self.users = {}

    # -- the account keys (the backend's, never the database's) -----------------------------------

    def _load_keys(self) -> None:
        self.users = {}
        if self.keystore.exists():
            for line in self.keystore.read_text("utf-8").splitlines():
                account, secret = json.loads(line)
                self.users[account] = UserKey.from_secret_bytes(bytes.fromhex(secret))

    def user(self, account: str) -> UserKey:
        """The account's key; a new one is stored durably before its first use."""
        if account not in self.users:
            key = UserKey.generate()
            fd = os.open(self.keystore, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(json.dumps([account, key.secret_bytes().hex()]) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self.users[account] = key
        return self.users[account]

    def secrets(self) -> list[str]:
        """Every account key's secret, as hex: for the test that no screen ever shows one."""
        return [k.secret_bytes().hex() for k in self.users.values()]

    # -- inserts ----------------------------------------------------------------------------------

    def request(self, rid: str, vector: npt.NDArray[np.float32], account: str) -> InsertRequest:
        return prepare_insert(self.cid, rid, [float(x) for x in vector], self.user(account))

    def insert(
        self,
        rid: str,
        vector: npt.NDArray[np.float32],
        account: str,
        text: str | None = None,
        mine: bool = False,
        request: InsertRequest | None = None,
        save: bool = True,
    ) -> Inserted:
        """Inserts one record with its passage; a ``request`` given again is a retry (§15.1).
        The index is saved at once unless ``save`` is false (a loop saves when it ends; the
        writer that is killed never saves: its parent owns the index)."""
        req = request or self.request(rid, vector, account)
        passage = (text or self._dataset_text(rid) or "").encode("utf-8") or None
        r: Receipt = self.live.insert(self.cid, req, passage=passage)
        if r.retried:
            return Inserted(rid, None, self.index.records[rid].group, True, None)
        own = [float(x) for x in vector] if mine else None
        flush = self.track(rid, r.placement or HOLDING, account, mine, text if mine else None, own)
        if save:
            self.save()
        return Inserted(rid, r.database_lsn, r.placement or HOLDING, False, flush)

    def track(
        self,
        rid: str,
        placement: str,
        account: str,
        mine: bool = False,
        text: str | None = None,
        vector: list[float] | None = None,
    ) -> Flush | None:
        """Records where an insert landed. An insert whose placement is a new spawned group while
        the holding area is one short of the spawn size is the flush: all of them move there."""
        flush = None
        known = {r.group for r in self.index.records.values()}
        if placement.startswith("spawn-") and placement not in known and self.index.holding:
            members = [*self.index.holding, rid]
            for m in self.index.holding:
                self.index.records[m].group = placement
            self.index.holding = []
            self.index.flushes += 1
            flush = Flush(placement, members, spawn_id(members))
        elif placement == HOLDING:
            self.index.holding.append(rid)
        self.index.records[rid] = Record(account, placement, mine, text, vector)
        return flush

    def insert_next(self, count: int, progress: Progress | None = None) -> list[Inserted]:
        """The next ``count`` dataset passages, with their accounts and text."""
        c = self.corpus
        start = self.index.loaded
        stop = min(start + count, len(c.ids))
        out = []
        for i in range(start, stop):
            out.append(self.insert(c.ids[i], c.vectors[i], c.accounts[i], save=False))
            self.index.loaded = i + 1
            if progress and ((i - start + 1) % 100 == 0 or i + 1 == stop):
                progress(i - start + 1, stop - start)
            if (i - start + 1) % 1000 == 0:
                self.save()
        self.save()
        return out

    def _dataset_text(self, rid: str) -> str | None:
        i = self.corpus.position.get(rid)
        return None if i is None else self.corpus.texts[i]

    # -- reading ----------------------------------------------------------------------------------

    def search(
        self, vector: Sequence[float] | npt.NDArray[np.float32], k: int = 10
    ) -> list[tuple[str, float]]:
        return self.live.search(self.cid, [float(x) for x in vector], k)

    def text_of(self, rid: str) -> str:
        rec = self.index.records.get(rid)
        if rec is not None and rec.text is not None:
            return rec.text
        return self._dataset_text(rid) or ""

    def vector_of(self, rid: str) -> npt.NDArray[np.float32]:
        rec = self.index.records.get(rid)
        if rec is not None and rec.vector is not None:
            return np.asarray(rec.vector, np.float32)
        row: npt.NDArray[np.float32] = self.corpus.vectors[self.corpus.position[rid]]
        return row

    def stored(self, rid: str, vector: npt.NDArray[np.float32], account: str) -> bool:
        """The database holds a live record with this ID: a second insert of it is refused as a
        duplicate (§3.2). Only for a record expected to be live: if it is not, this stores it."""
        try:
            self.live.insert(self.cid, self.request(rid, vector, account))
        except DuplicateRecord:
            return True
        return False

    def total(self) -> int:
        st = self.live.stats(self.cid)
        return st["N"] + st["holding"]

    def accounts(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for rid, rec in self.index.records.items():
            out.setdefault(rec.account, []).append(rid)
        return out

    def mismatches(self) -> list[str]:
        """The application's index against the database's own counts: each group's size, the
        holding area and ``N`` (§5, §7.6). Empty when they agree."""
        st = self.live.stats(self.cid)
        mine = Counter(r.group for r in self.index.records.values())
        out = []
        if mine[HOLDING] != st["holding"] or len(self.index.holding) != st["holding"]:
            out.append(f"holding area: index {mine[HOLDING]}, database {st['holding']}")
        n = sum(v for g, v in mine.items() if g != HOLDING)
        if n != st["N"]:
            out.append(f"N: index {n}, database {st['N']}")
        for g, size in self.live.group_sizes(self.cid):
            if mine[g] != size:
                out.append(f"{g}: index {mine[g]}, database {size}")
        return out

    # -- deletions --------------------------------------------------------------------------------

    def delete(self, rid: str) -> Deletion:
        return self.forget_ids([rid])[0]

    def forget(self, account: str) -> list[Deletion]:
        return self.forget_ids(self.accounts().get(account, []))

    def forget_ids(self, ids: list[str]) -> list[Deletion]:
        """One person's records in one transaction, all or nothing (§12.5); each certificate is
        saved for them with the public anchors."""
        out = self.live.delete_user(self.cid, ids)
        for rid, d in zip(ids, out, strict=True):
            if d.outcome == "deleted" and d.certificate is not None and d.database_lsn is not None:
                (self.receipts / f"{d.database_lsn}.cert").write_bytes(d.certificate)
                self.index.receipts.append(d.database_lsn)
                rec = self.index.records.pop(rid, None)
                if rec is not None and rec.group == HOLDING:
                    self.index.holding.remove(rid)
        (self.receipts / "anchors.json").write_text(self.live.anchors(), "utf-8")
        self.save()
        return out

    def absent(self, rid: str) -> bool:
        """Deleting a record that is not live changes nothing and says ``absent`` (§5.4)."""
        return self.live.delete(self.cid, rid).outcome == "absent"

    # -- after a crash ----------------------------------------------------------------------------

    def reconcile(self, acked: list[tuple[str, str]], in_flight: str | None) -> bool | None:
        """Takes in the inserts a killed writer reported (ID, placement), in order, then asks the
        database whether the insert in flight committed too. Returns that answer (``None`` when
        nothing was in flight)."""
        c = self.corpus
        for rid, placement in acked:
            self.track(rid, placement, c.accounts[c.position[rid]])
        self.index.loaded += len(acked)
        committed = None
        if in_flight is not None:
            i = c.position[in_flight]
            # Not committed: this insert stores it now; committed: refused as a duplicate.
            try:
                r = self.live.insert(
                    self.cid,
                    self.request(in_flight, c.vectors[i], c.accounts[i]),
                    passage=c.texts[i].encode("utf-8"),
                )
                committed = False
                self.track(in_flight, r.placement or HOLDING, c.accounts[i])
            except DuplicateRecord:
                committed = True
                self.track(in_flight, self._surplus_group(), c.accounts[i])
            self.index.loaded += 1
        self.save()
        return committed

    def _surplus_group(self) -> str:
        """Where the database holds one record more than the index knows: the committed insert
        whose answer was lost with the writer."""
        st = self.live.stats(self.cid)
        if st["holding"] > len(self.index.holding):
            return HOLDING
        mine = Counter(r.group for r in self.index.records.values())
        for g, size in self.live.group_sizes(self.cid):
            if size > mine[g]:
                return g
        return HOLDING
