"""One application backend using the database: what the tour and the shell both drive.

This is the code a real backend would hold (§3.3). It keeps each account's key in its own key
store (``accounts.keys``, mode 0600, never printed), inserts through ``prepare_insert``, searches,
deletes, and hands each deletion certificate to the person it belongs to. Everything it does goes
through the public SDK ``sever_db``; nothing here reaches inside the engine.
"""

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sever_db import Database, Deletion, DuplicateRecord, PlatformUnsafe, UserKey, prepare_insert

from .data import Corpus


def say(line: str = "") -> None:
    print(line, flush=True)


@dataclass
class State:
    """What the backend remembers between runs (``state.json``): no secret is in it."""

    cid: str = ""
    loaded: int = 0
    deleted: list[str] = field(default_factory=list)
    receipts: list[int] = field(default_factory=list)


class Session:
    def __init__(self, corpus: Corpus, work: Path, dev: bool) -> None:
        self.corpus = corpus
        self.work = work
        self.dev = dev
        self.data = work / "data"
        self.keys = work / "keys"
        self.receipts = work / "receipts"
        self.state_file = work / "state.json"
        self.keystore = work / "accounts.keys"
        self.db: Database | None = None
        self.state = State()
        self.users: dict[str, UserKey] = {}
        self.refused: str | None = None

    # -- opening -----------------------------------------------------------------------------

    def open(self) -> Database:
        """Opens (recovering, or creating) the database. Without ``--dev``, an unsafe platform is
        refused (§12.8–12.9); with it, the memory override is used and reported."""
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
        if self.state_file.exists():
            self.state = State(**json.loads(self.state_file.read_text("utf-8")))
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

    def save(self) -> None:
        self.state_file.write_text(json.dumps(self.state.__dict__, indent=1), "utf-8")

    def wipe(self) -> None:
        self.close()
        shutil.rmtree(self.work, ignore_errors=True)
        self.state = State()
        self.users = {}

    # -- the account key store (the backend's, not the database's) -----------------------------

    def _load_keys(self) -> None:
        self.users = {}
        if self.keystore.exists():
            for line in self.keystore.read_text("utf-8").splitlines():
                a, s = json.loads(line)
                self.users[a] = UserKey.from_secret_bytes(bytes.fromhex(s))

    def user(self, account: str) -> UserKey:
        """The account's key. A new account's key is stored (one appended line, mode 0600) before
        it is first used, so a crash never leaves a record signed by a key the backend lost."""
        if account not in self.users:
            key = UserKey.generate()
            fd = os.open(self.keystore, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a") as f:
                f.write(json.dumps([account, key.secret_bytes().hex()]) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self.users[account] = key
        return self.users[account]

    # -- the operations ------------------------------------------------------------------------

    def create(self) -> str:
        if not self.state.cid:
            self.state.cid = self.live.create_collection(
                self.corpus.artefact, spawn_target=self.corpus.spawn_target
            )
            self.save()
        return self.state.cid

    def insert_next(self, count: int, progress: bool = True) -> tuple[int, float]:
        """Inserts the next ``count`` records of the corpus with their passages; returns how many
        and the mean seconds per insert."""
        c, db, cid = self.corpus, self.live, self.create()
        start, stop = self.state.loaded, min(self.state.loaded + count, len(c.ids))
        t0 = time.perf_counter()
        for i in range(start, stop):
            req = prepare_insert(cid, c.ids[i], c.vectors[i].tolist(), self.user(c.accounts[i]))
            db.insert(cid, req, passage=c.texts[i].encode("utf-8"))
            if progress and (i - start + 1) % 500 == 0:
                say(f"     {i - start + 1:>6} / {stop - start} inserted")
        self.state.loaded = stop
        self.save()
        n = stop - start
        return n, (time.perf_counter() - t0) / max(1, n)

    def search(self, vector: Any, k: int = 10) -> list[tuple[str, float]]:
        return self.live.search(self.create(), [float(x) for x in vector], k)

    def searchable(self, rid: str) -> bool:
        """Found by a search with its own vector. Records waiting in the holding area are stored
        but never searched until 200 of them form a new group (§7.4, §8)."""
        i = self.corpus.position[rid]
        return any(h == rid for h, _ in self.search(self.corpus.vectors[i], 3))

    def stored(self, rid: str) -> bool:
        """The database holds a live record with this ID: a second insert of the ID is refused as
        a duplicate (§3.2). Only for records expected to be live: if it is not, this stores it."""
        i = self.corpus.position[rid]
        req = prepare_insert(
            self.create(), rid, self.corpus.vectors[i].tolist(), self.user(self.corpus.accounts[i])
        )
        try:
            self.live.insert(self.create(), req)
        except DuplicateRecord:
            return True
        return False

    def absent(self, rid: str) -> bool:
        """No live record has this ID: deleting it again is "absent" and changes nothing (§5.4)."""
        return self.live.delete(self.create(), rid).outcome == "absent"

    def total(self) -> int:
        """Every stored record: ``N`` counts the groups' records, ``holding`` the rest (§5)."""
        st = self.live.stats(self.create())
        return st["N"] + st["holding"]

    def forget(self, record_ids: list[str]) -> list[Deletion]:
        """One person's records, all or nothing (§12.5); each certificate is saved for them."""
        out = self.live.delete_user(self.create(), record_ids)
        for rid, d in zip(record_ids, out, strict=True):
            if d.outcome == "deleted" and d.certificate is not None and d.database_lsn is not None:
                (self.receipts / f"{d.database_lsn}.cert").write_bytes(d.certificate)
                self.state.receipts.append(d.database_lsn)
                self.state.deleted.append(rid)
        (self.receipts / "anchors.json").write_text(self.live.anchors(), "utf-8")
        self.save()
        return out

    def live_ids(self) -> list[str]:
        gone = set(self.state.deleted)
        return [r for r in self.corpus.ids[: self.state.loaded] if r not in gone]

    def accounts(self) -> dict[str, list[str]]:
        gone = set(self.state.deleted)
        return {
            a: [r for r in ids if r not in gone]
            for a, ids in self.corpus.by_account(self.state.loaded).items()
        }
