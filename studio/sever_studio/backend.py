"""Studio's application backend: what a real service would hold beside the database.

It owns one account key per account (``accounts.keys``, mode 0600, never shown), inserts through
``prepare_insert``, searches, deletes, and keeps each deletion certificate for the person it belongs
to. It also keeps the application's own index of its records (``index.json``: ID, account, where the
record landed, its insert's log position), because the database never hands passages back (§13.2).
Everything goes through the public SDK ``sever_db``.

The engine decides where each record is, and its own log says so (DB-109): an insert's
``database_lsn`` is the index of its leaf (§10.2), and ``replay`` rebuilds every live record's group
from ``export_log`` (placements, flushes, deletions by their certificate's scrambled ID, §11.1).
The index is a cache that ``mismatches`` checks against that replay, record by record.
"""

import fcntl
import hashlib
import json
import os
import shutil
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt
from sever_db import (
    Database,
    Deletion,
    InsertRequest,
    PlatformUnsafe,
    Receipt,
    UserKey,
    prepare_insert,
)

from .corpus import Corpus

HOLDING = "holding"
INSERT_LEAF = 0x01  # §10.2
Progress = Callable[[int, int], None]


@dataclass(frozen=True)
class Replay:
    """The engine's log, replayed: insert ``database_lsn`` -> its record's group now; the holding
    area's records in arrival order; and per group, the newest commitment the engine published
    for it (``C_S_post`` of its latest deletion, with that deletion's ``database_lsn``)."""

    groups: dict[int, str]
    holding: list[int]
    commitments: dict[str, tuple[int, bytes]] = field(default_factory=dict)


def cert_field(cert: bytes, want: int) -> bytes:
    """§11.1: a certificate is ``u8 tag ‖ u32be length ‖ value`` fields, tags 1 … 13 in order."""
    at = 0
    while at + 5 <= len(cert):
        tag, length = cert[at], int.from_bytes(cert[at + 1 : at + 5], "big")
        if tag == want:
            return cert[at + 5 : at + 5 + length]
        at += 5 + length
    raise ValueError(f"a certificate without tag {want}")


class WorkInUseError(Exception):
    """Another Studio holds this work directory."""


def spawn_id(members: Sequence[str]) -> str:
    """§7.5: ``spawn-`` and the first 16 hex characters of SHA-256 over the founding records' IDs,
    ascending by bytes, each as ``u16be(len) ‖ id``."""
    h = hashlib.sha256()
    for rid in sorted(m.encode("utf-8") for m in members):
        h.update(len(rid).to_bytes(2, "big") + rid)
    return "spawn-" + h.hexdigest()[:16]


def lock(work: Path, what: str = "run") -> int:
    """One Studio per work directory: an exclusive lock beside it, held until the process exits
    (the system drops it when the process dies, so a lock is never stale). The lock file says who
    holds it, so a second Studio can tell the person what to wait for."""
    work.parent.mkdir(parents=True, exist_ok=True)
    path = work.parent / f".{work.name}.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        try:
            who = json.loads(path.read_text("utf-8"))
        except ValueError:
            who = {}
        doing = {"prepare": "preparing the database", "run": "open in a window"}.get(
            str(who.get("what")), "in use"
        )
        note = f", {who['note']}" if who.get("note") else ""
        raise WorkInUseError(
            f"{work.name} is busy: another Studio is {doing} (pid {who.get('pid', '?')}, since "
            f"{who.get('since', '?')}{note}). Wait for it to finish, or close it."
        ) from None
    note_lock(fd, what)
    return fd


def note_lock(fd: int, what: str, note: str = "") -> None:
    """Writes who holds the lock (and how far it has got) into the lock file."""
    doc = {"pid": os.getpid(), "what": what, "since": time.strftime("%H:%M:%S"), "note": note}
    os.ftruncate(fd, 0)
    os.pwrite(fd, json.dumps(doc).encode("utf-8"), 0)


@dataclass
class Record:
    """One live record as the application knows it. ``text`` is kept only for records typed in
    Studio (the dataset's own passages are read from the dataset)."""

    account: str
    group: str
    mine: bool = False
    text: str | None = None
    vector: list[float] | None = None
    #: the insert's ``database_lsn``: the index of its leaf in the public log (§10.2)
    lsn: int | None = None


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
    #: each receipt's record and account (``database_lsn`` as text -> [ID, account])
    owners: dict[str, list[str]] = field(default_factory=dict)


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
        #: the last replay of the engine's log; dropped by every insert, deletion and reopen
        self._replay: Replay | None = None

    # -- opening and state ------------------------------------------------------------------------

    def open(self) -> Database:
        """Opens (recovering, or creating) the database. An unsafe machine is refused (§12.8–12.9);
        with ``dev`` the memory override is used, and the database lists it in ``startup``."""
        self.work.mkdir(parents=True, exist_ok=True)
        self.receipts.mkdir(exist_ok=True)
        self._replay = None
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
            f.write(json.dumps(doc, separators=(",", ":")))  # dumps: the C encoder, not dump's
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
        self._replay = None
        if r.retried:
            return Inserted(rid, None, self.index.records[rid].group, True, None)
        own = [float(x) for x in vector] if mine else None
        flush = self.track(
            rid, r.placement or HOLDING, account, mine, text if mine else None, own, r.database_lsn
        )
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
        lsn: int | None = None,
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
        self.index.records[rid] = Record(account, placement, mine, text, vector, lsn)
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

    def is_live(self, rid: str) -> bool:
        """The engine's log holds this record's insert and no deletion of it (§10.2, §11.1)."""
        rec = self.index.records.get(rid)
        return rec is not None and rec.lsn is not None and rec.lsn in self.replay().groups

    def total(self) -> int:
        st = self.live.stats(self.cid)
        return st["N"] + st["holding"]

    def accounts(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for rid, rec in self.index.records.items():
            out.setdefault(rec.account, []).append(rid)
        return out

    def replay(self) -> Replay:
        """Every live record's group, rebuilt from the engine's own log (DB-86): an insert leaf
        names where its record went, an insert that flushed names the new group of everything then
        in the holding area (§7.4), and a deletion leaf's certificate names the record it removed
        by its scrambled ID (§11.1 tag 9) and the group's commitment after it (tag 3). Kept until
        this backend next writes or reopens."""
        if self._replay is not None:
            return self._replay
        log = json.loads(self.live.export_log())
        leaves = log["leaves"]
        group: dict[bytes, str] = {}
        lsn_of: dict[bytes, int] = {}
        holding: list[bytes] = []
        published: dict[str, tuple[int, bytes]] = {}
        for i, (h, p) in enumerate(zip(leaves, log["placements"], strict=True)):
            leaf = bytes.fromhex(h)
            if leaf[0] == INSERT_LEAF:
                sid = leaf[17:81]
                lsn_of[sid] = i
                if p["flush"]:
                    for w in holding:
                        group[w] = p["flush"]
                    holding = []
                group[sid] = p["group"]
                if p["group"] == HOLDING:
                    holding.append(sid)
            else:
                cert = leaf[1:]
                sid = cert_field(cert, 9)
                left = group.pop(sid)
                if left == HOLDING:
                    holding.remove(sid)
                elif cs := cert_field(cert, 3):
                    published[left] = (i, cs)
        out = Replay(
            {lsn_of[s]: g for s, g in group.items()}, [lsn_of[s] for s in holding], published
        )
        self._replay = out
        return out

    def mismatches(self) -> list[str]:
        """The application's index against the engine's log, record by record, and against the
        engine's own counts (§5, §7.6). Empty when they agree."""
        truth = self.replay()
        out = []
        known: set[int] = set()
        for rid, rec in self.index.records.items():
            if rec.lsn is None:
                out.append(f"{rid}: no log position (an index from an older Studio: prepare again)")
                continue
            known.add(rec.lsn)
            engine = truth.groups.get(rec.lsn)
            if engine != rec.group:
                out.append(f"{rid}: index {rec.group}, engine {engine or 'deleted'}")
        unknown = len(set(truth.groups) - known)
        if unknown:
            out.append(f"{unknown} live record(s) in the engine that the index does not know")
        st = self.live.stats(self.cid)
        sizes = Counter(truth.groups.values())
        if sizes[HOLDING] != st["holding"]:
            out.append(f"holding area: log {sizes[HOLDING]}, engine {st['holding']}")
        for g, size in self.live.group_sizes(self.cid):
            if sizes[g] != size:
                out.append(f"{g}: log {sizes[g]}, engine {size}")
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
        self._replay = None
        for rid, d in zip(ids, out, strict=True):
            if d.outcome == "deleted" and d.certificate is not None and d.database_lsn is not None:
                (self.receipts / f"{d.database_lsn}.cert").write_bytes(d.certificate)
                self.index.receipts.append(d.database_lsn)
                rec = self.index.records.pop(rid, None)
                self.index.owners[str(d.database_lsn)] = [rid, rec.account if rec else ""]
                if rec is not None and rec.group == HOLDING:
                    self.index.holding.remove(rid)
        (self.receipts / "anchors.json").write_text(self.live.anchors(), "utf-8")
        self.save()
        return out

    def receipt_owner(self, lsn: int) -> tuple[str, str] | None:
        """The record and account a receipt of this application belongs to."""
        o = self.index.owners.get(str(lsn))
        return (o[0], o[1]) if o else None

    def absent(self, rid: str) -> bool:
        """Deleting a record that is not live changes nothing and says ``absent`` (§5.4)."""
        self._replay = None
        return self.live.delete(self.cid, rid).outcome == "absent"

    # -- after a crash ----------------------------------------------------------------------------

    def reconcile(self, acked: list[tuple[str, str, int]], in_flight: str | None) -> bool | None:
        """Takes in the inserts a killed writer reported (ID, placement, log position), in order,
        then reads the engine's log for the insert in flight: committed if the log holds one live
        insert the index does not know (its answer was lost with the writer). Returns that answer
        (``None`` when nothing was in flight)."""
        c = self.corpus
        for rid, placement, lsn in acked:
            self.track(rid, placement, c.accounts[c.position[rid]], lsn=lsn)
        self.index.loaded += len(acked)
        committed = None
        if in_flight is not None:
            i = c.position[in_flight]
            truth = self.replay()
            known = {r.lsn for r in self.index.records.values()}
            lost = [lsn for lsn in truth.groups if lsn not in known]
            committed = len(lost) == 1
            if committed:
                self.track(in_flight, truth.groups[lost[0]], c.accounts[i], lsn=lost[0])
            else:
                r = self.live.insert(
                    self.cid,
                    self.request(in_flight, c.vectors[i], c.accounts[i]),
                    passage=c.texts[i].encode("utf-8"),
                )
                self._replay = None
                self.track(in_flight, r.placement or HOLDING, c.accounts[i], lsn=r.database_lsn)
            self.index.loaded += 1
        self.adopt(self.replay())
        self.save()
        return committed

    def adopt(self, truth: Replay) -> None:
        """Takes each known record's group, and the holding area's order, from the engine's log."""
        by_lsn = {r.lsn: rid for rid, r in self.index.records.items() if r.lsn is not None}
        for lsn, g in truth.groups.items():
            if lsn in by_lsn:
                self.index.records[by_lsn[lsn]].group = g
        self.index.holding = [by_lsn[lsn] for lsn in truth.holding if lsn in by_lsn]
