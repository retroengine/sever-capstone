"""sever_db: the application-backend SDK of the final build (spec §16.2; Build 3-4 §2.4).

The SDK runs on the application backend (§3.3), never on a user's device. Each account has an
Ed25519 key (``UserKey``, §9.8) that the backend keeps in its own key store; it never rotates.
``prepare_insert`` quantises the vector with the engine's quantiser (§4.2), draws ``r_t`` from the
OS (§9.4), computes ``C_t`` (§9.3) and signs ``DST_INSERT ‖ collection_id ‖ C_t`` (§9.8). ``r_t``
travels inside the request and is never readable from Python; the engine stores it. A deletion
takes no ``r_t`` and returns a certificate that anyone can verify offline (§11).

Randomness (§9.6, §16.2): nothing in the SDK accepts a random generator, seed or nonce. Passing
any extra argument to a function that draws randomness or makes a proof raises
``SeededNonceForbidden``.

Retries (§15.1, §15.4): an insert whose acknowledgement was lost is retried with **the same
request**; ``DuplicateRecord`` with ``same_commitment`` true means the first call committed, and the
SDK returns success (``Receipt.retried``). A retried deletion returns ``"absent"``. Every stored
secret is ciphertext, and a deletion erases its old key before it returns (§13.3–13.4).

    from sever_db import Database, UserKey, prepare_insert
    user = UserKey.generate()
    with Database.open("data", "keys") as db:
        cid = db.create_collection("artefacts/partition-seed42.svp")
        receipt = db.insert(cid, prepare_insert(cid, "doc-1", vector, user))
        deletion = db.delete(cid, "doc-1")  # deletion.certificate: bytes (§11.1)
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from os import PathLike
from types import TracebackType
from typing import Literal, Self

import sever_db_native as _native
from sever_db_native import (
    BadUserSignature,
    CommitmentMismatch,
    DuplicateRecord,
    DurabilityFailure,
    GroupCapacityExceeded,
    InsertRequest,
    IntegrityViolation,
    InvalidRecordId,
    NonFinite,
    NotNormalised,
    PlatformUnsafe,
    SeededNonceForbidden,
    SeverError,
    UnknownCollection,
    WrongDimension,
)

__all__ = [
    "BadUserSignature",
    "CommitmentMismatch",
    "Cosignature",
    "Database",
    "Deletion",
    "DuplicateRecord",
    "DurabilityFailure",
    "Engine",
    "GroupCapacityExceeded",
    "InsertRequest",
    "IntegrityViolation",
    "InvalidRecordId",
    "LogCheckpoint",
    "NonFinite",
    "NotNormalised",
    "PlatformUnsafe",
    "Receipt",
    "SeededNonceForbidden",
    "SeverError",
    "UnknownCollection",
    "UserKey",
    "WrongDimension",
    "prepare_insert",
]

Outcome = Literal["deleted", "absent"]


def _rid(record_id: str) -> str:
    """§3.2 rule 1: a record ID is UTF-8. A ``str`` with no UTF-8 encoding (a lone surrogate) is
    ``InvalidRecordId``, and the error holds no part of it (§17); the engine checks the rest."""
    if isinstance(record_id, str):
        try:
            record_id.encode("utf-8")
        except UnicodeEncodeError:
            raise InvalidRecordId("invalid record id: not valid UTF-8") from None
    return record_id


def _no_randomness(extra: Sequence[object], named: Mapping[str, object]) -> None:
    """§16.2: no way to pass a random generator, seed or nonce. Any extra argument is one."""
    if extra or named:
        raise SeededNonceForbidden("randomness cannot be supplied (§9.6, §16.2)")


class UserKey:
    """An account's Ed25519 key (§9.8, §16.2). Never rotates; the backend stores
    ``secret_bytes()`` in its own key store and reloads it with ``from_secret_bytes``."""

    def __init__(self, key: _native.UserKey) -> None:
        self._k = key

    @classmethod
    def generate(cls, *randomness: object, **more: object) -> Self:
        """A new key from the OS random source. No seed can be passed (§16.2)."""
        _no_randomness(randomness, more)
        return cls(_native.UserKey.generate())

    @classmethod
    def from_secret_bytes(cls, secret: bytes) -> Self:
        """A stored key (its 32-byte secret)."""
        return cls(_native.UserKey.from_secret_bytes(secret))

    def secret_bytes(self) -> bytes:
        return self._k.secret_bytes()

    @property
    def public_key(self) -> bytes:
        return self._k.public_key

    def __repr__(self) -> str:
        return "UserKey(<secret>)"  # §17: never print a key


def prepare_insert(
    collection_id: str,
    record_id: str,
    vector: Sequence[float],
    user: UserKey,
    *randomness: object,
    **more: object,
) -> InsertRequest:
    """Quantises (§4.2), draws ``r_t`` from the OS (§9.4), computes ``C_t`` and signs (§9.8).
    Keep the request to retry the insert; ``r_t`` cannot be read from it."""
    _no_randomness(randomness, more)
    if not isinstance(user, UserKey):
        raise TypeError("user must be a UserKey")
    return _native.prepare_insert(collection_id, _rid(record_id), list(map(float, vector)), user._k)


@dataclass(frozen=True)
class Receipt:
    """An acknowledged insert: its ``database_lsn`` (the index of its insert leaf, §10.2) and
    where it landed, or ``retried`` when this call retried an insert that had already committed
    (§15.1)."""

    database_lsn: int | None
    placement: str | None
    retried: bool = False


@dataclass(frozen=True)
class Deletion:
    """One deletion (§15.3): ``"deleted"`` with its ``database_lsn`` and certificate (§11.1), or
    ``"absent"`` if the record was not live (§5.4; a retry)."""

    outcome: Outcome
    database_lsn: int | None = None
    certificate: bytes | None = None


@dataclass(frozen=True)
class Cosignature:
    witness_index: int
    witness_epoch: int
    signature: bytes


@dataclass(frozen=True)
class LogCheckpoint:
    """A signed log checkpoint (§10.3) with its witness cosignatures (§10.4)."""

    tree_size: int
    root: bytes
    timestamp_ms: int
    epoch: int
    operator_signature: bytes
    cosignatures: tuple[Cosignature, ...]


def _deletion(o: tuple[str, int | None, bytes | None]) -> Deletion:
    return Deletion("deleted", o[1], o[2]) if o[0] == "deleted" else Deletion("absent")


class Database:
    """One open database (``ENGINE.lock`` is held until ``close``)."""

    def __init__(self, engine: _native.Engine) -> None:
        self._e = engine

    @classmethod
    def open(
        cls,
        data_dir: str | PathLike[str],
        key_dir: str | PathLike[str],
        d: int = 384,
        allow_unsafe_fs: bool = False,
        allow_unsafe_memory: bool = False,
        *randomness: object,
        **more: object,
    ) -> Self:
        """Opens (recovering, or creating) a database of dimension ``d``. The two overrides are for
        development only: ``allow_unsafe_fs`` for a data or key directory that does not overwrite
        in place (§12.9), ``allow_unsafe_memory`` for unencrypted swap, hibernation or memory that
        cannot be locked (§12.8). Each one used is listed in ``startup``."""
        _no_randomness(randomness, more)
        return cls(_native.Engine.open(data_dir, key_dir, d, allow_unsafe_fs, allow_unsafe_memory))

    @property
    def startup(self) -> tuple[tuple[str, ...], bool]:
        """The startup checks that failed and were overridden, and whether memory is locked."""
        overridden, locked = self._e.startup()
        return tuple(overridden), locked

    @property
    def d(self) -> int:
        return self._e.d()

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
        request: InsertRequest,
        passage: bytes | None = None,
        *randomness: object,
        **more: object,
    ) -> Receipt:
        """Inserts one prepared record (§15.1). A retry of a committed insert, with the same
        request, returns ``Receipt(None, None, retried=True)``."""
        _no_randomness(randomness, more)
        try:
            lsn, placement = self._e.insert(collection, request, passage)
        except DuplicateRecord as e:
            if e.args and e.args[0] is True:
                return Receipt(None, None, retried=True)
            raise
        return Receipt(lsn, placement)

    def delete(
        self, collection: str, record_id: str, *randomness: object, **more: object
    ) -> Deletion:
        """Deletes one record (§15.3); no ``r_t`` argument, and no way to pass randomness into its
        proof (§9.6)."""
        _no_randomness(randomness, more)
        return _deletion(self._e.delete(collection, _rid(record_id)))

    def delete_user(
        self, collection: str, record_ids: Sequence[str], *randomness: object, **more: object
    ) -> list[Deletion]:
        """Deletes every record of a cohort in one transaction, all or nothing (§12.5); the
        certificates of one group chain (§11.3)."""
        _no_randomness(randomness, more)
        return [
            _deletion(o) for o in self._e.delete_user(collection, [_rid(r) for r in record_ids])
        ]

    def certificate(self, database_lsn: int) -> bytes | None:
        """The certificate of the deletion at ``database_lsn`` (§15.4), or ``None``."""
        return self._e.certificate(database_lsn)

    def latest_log_checkpoint(self) -> LogCheckpoint:
        size, root, ts, epoch, sig, cos = self._e.latest_log_checkpoint()
        return LogCheckpoint(size, root, ts, epoch, sig, tuple(Cosignature(*c) for c in cos))

    def inclusion_proof(self, leaf_index: int, tree_size: int) -> list[bytes] | None:
        """RFC 9162 inclusion proof (§10.1), or ``None`` if the sizes are out of range."""
        return self._e.inclusion_proof(leaf_index, tree_size)

    def consistency_proof(self, old_size: int, new_size: int) -> list[bytes] | None:
        """RFC 9162 consistency proof (§10.1), or ``None`` if the sizes are out of range."""
        return self._e.consistency_proof(old_size, new_size)

    def events(self, since: int = 0) -> list[dict[str, object]]:
        """Every committed change's public fields since event ``since`` (DB-107, spec §16.1): the
        kind, created groups with the centroid the engine computed, each touched group's ``n`` and
        ``C_S`` before and after, ``N`` and ``k``, arrivals and departures by scrambled ID, and each
        outcome. Never ``S``, ``r_agg``, ``x̃``, ``r_t``, a record ID or text. Only in an SDK built
        with the cargo feature ``inspect``."""
        if not hasattr(self._e, "events"):
            raise SeverError("this SDK was built without the inspect feature (DB-107)")
        out: list[dict[str, object]] = self._e.events(since)
        return out

    def export_log(self) -> str:
        """The committed log for an auditor (``sever-audit``; DB-86), as JSON: every leaf, where
        each leaf's record went, and every log checkpoint with its cosignatures."""
        return self._e.export_log()

    def anchors(self) -> str:
        """The verifier's trust anchors (§11.3) as JSON: ``d``, ``gdigest``, the operator's and
        each witness's public keys by epoch."""
        return self._e.anchors()

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


#: §16.2's example names the database ``Engine`` (DB-84).
Engine = Database
