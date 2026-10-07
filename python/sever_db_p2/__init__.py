"""sever_db_p2: the application-backend SDK for Part 2 (spec §16.2 without commitments; Build §5.5).

The SDK runs on the application backend (§3.3), never on a user's device. Part 2 has no
commitments, user keys or signatures (they arrive in Part 3), so an insert is a record ID, a
normalised vector and optional passage text. A plaintext database (DB-48): no confidentiality claim.

Retries (§15.1, §15.4): an insert whose acknowledgement was lost is retried by calling ``insert``
again; ``DuplicateRecord`` with ``same_commitment`` true means the first call committed, and the SDK
returns success (``Receipt.retried``). A retried deletion returns ``"absent"``.

    from sever_db_p2 import Database
    with Database.open("data", "keys") as db:
        cid = db.create_collection("artefacts/partition-seed42.svp")
        db.insert(cid, "doc-1", vector, passage=b"...")
        db.search(cid, query, k=10)
        db.delete(cid, "doc-1")
"""

from collections.abc import Sequence
from dataclasses import dataclass
from os import PathLike
from types import TracebackType
from typing import Literal, Self

import sever_db_p2_native as _native
from sever_db_p2_native import (
    DuplicateRecord,
    DurabilityFailure,
    GroupCapacityExceeded,
    IntegrityViolation,
    InvalidRecordId,
    NonFinite,
    NotNormalised,
    PlatformUnsafe,
    SeverError,
    UnknownCollection,
    WrongDimension,
)

__all__ = [
    "Database",
    "DuplicateRecord",
    "DurabilityFailure",
    "GroupCapacityExceeded",
    "IntegrityViolation",
    "InvalidRecordId",
    "NonFinite",
    "NotNormalised",
    "PlatformUnsafe",
    "Receipt",
    "SeverError",
    "UnknownCollection",
    "WrongDimension",
]

Outcome = Literal["deleted", "absent"]


@dataclass(frozen=True)
class Receipt:
    """An acknowledged insert: where it landed, or ``retried`` when this call was a retry of an
    insert that had already committed (§15.1)."""

    placement: str | None
    retried: bool = False


class Database:
    """One open database (``ENGINE.lock`` is held until ``close``)."""

    def __init__(self, engine: _native.Engine) -> None:
        self._e = engine

    @classmethod
    def open(
        cls,
        data_dir: str | PathLike[str],
        key_dir: str | PathLike[str],
        allow_unsafe_fs: bool = False,
    ) -> Self:
        """Opens (recovering, or creating) a database. ``allow_unsafe_fs`` is for development on
        tmpfs only (§12.9; recorded in the run ledger)."""
        return cls(_native.Engine.open(data_dir, key_dir, allow_unsafe_fs))

    def create_collection(
        self,
        artefact: str | PathLike[str],
        spawn_target: int = 200,
        spawning_enabled: bool = True,
        store_passages: bool = True,
    ) -> str:
        """A new collection over a partition artefact (§6.3); returns its ID (32 hex characters)."""
        return self._e.create_collection(artefact, spawn_target, spawning_enabled, store_passages)

    def insert(
        self,
        collection: str,
        record_id: str,
        vector: Sequence[float],
        passage: bytes | None = None,
    ) -> Receipt:
        """Inserts one record. A retry of a committed insert returns ``Receipt(None, True)``."""
        try:
            return Receipt(self._e.insert(collection, record_id, list(map(float, vector)), passage))
        except DuplicateRecord as e:
            if e.args and e.args[0] is True:
                return Receipt(None, retried=True)
            raise

    def delete(self, collection: str, record_id: str) -> Outcome:
        """Deletes one record: ``"deleted"``, or ``"absent"`` if it was not live (a retry)."""
        return "deleted" if self._e.delete(collection, record_id) == "deleted" else "absent"

    def delete_user(self, collection: str, record_ids: Sequence[str]) -> list[Outcome]:
        """Deletes every record of a cohort in one transaction: all or nothing (§12.5)."""
        return [
            "deleted" if o == "deleted" else "absent"
            for o in self._e.delete_user(collection, list(record_ids))
        ]

    def search(
        self, collection: str, query: Sequence[float], k: int = 10
    ) -> list[tuple[str, float]]:
        """The ``k`` nearest records (§8.1): ``(record_id, score)``, closest first."""
        return self._e.search(collection, list(map(float, query)), k)

    def stats(self, collection: str) -> dict[str, int]:
        return self._e.stats(collection)

    def group_sizes(self, collection: str) -> list[tuple[str, int]]:
        """``(group ID, n)`` of every frozen and spawned group, in creation order."""
        return self._e.group_sizes(collection)

    def collections(self) -> list[str]:
        return self._e.collections()

    def drop_collection(self, collection: str) -> None:
        self._e.drop_collection(collection)

    def checkpoint(self) -> None:
        self._e.checkpoint()

    def close(self) -> None:
        """Clean shutdown (a storage checkpoint) and release of the lock."""
        self._e.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
