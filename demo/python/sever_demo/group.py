"""One group: exact integer sum S, count n, member list (§5.2-5.5), and optionally its commitment.

A group holds row numbers into one shared int32 array of quantised vectors (§4.2), never copies.

Without commitments (Day 2), the exactness check compares 4 of the 5 fields of §5.5 (S, n, the
blob, the member list) and the blob uses a demo layout (magic SEVERC). With commitments switched on
(the Part 3 preview), the group also keeps r_agg and C_S (§5.2), all five fields are compared, and
the blob is exactly the spec's §5.5 layout (magic SEVERG, with C_S and r_agg).
"""

import hashlib
import struct
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from sever_demo.crypto import IDENTITY, L, commit, point_add, point_sub, scalar_bytes
from sever_demo.errors import (
    DuplicateRecord,
    GroupCapacityExceeded,
    IntegrityViolation,
    Outcome,
)

MAGIC_DEMO = b"SEVERC"  # without commitments: not the spec's layout, so it must not pass as one
MAGIC_SPEC = b"SEVERG"  # with commitments: §5.5 exactly
FORMAT_VERSION = 1
MAX_MEMBERS = 1_000_000  # §5.6 hard cap; keeps |S_i| < 2^44 (§4.4)
_BLOB_BATCH = 1024  # members per piece when streaming the blob into SHA-256

# Deliberate bugs for the must-fail tests (Build §2.6). Each changes exactly one place below.
#   SB-1: flip the low bit of S[0] when a group receives its first member
#   SB-2: skip n -= 1 on delete
#   SB-3: skip the membership check on delete, so a retried delete subtracts twice
#   SB-4 (demo, Part 3 preview): skip r_agg -= r_t on delete (C_S still moves by C_t)
SABOTAGE: str | None = None


@dataclass(frozen=True)
class Transition:
    """What one committed deletion did (§9.3, §9.5). Kept in memory only: r_post and S_post are
    secrets (§13.2); the index uses them once, to build the proof, then drops them."""

    c_t: bytes
    c_s_pre: bytes
    c_s_post: bytes
    r_post: int
    s_post: tuple[int, ...]
    emptied: bool


class Group:
    def __init__(
        self, vectors: npt.NDArray[np.int32], blinding: Sequence[int] | None = None
    ) -> None:
        if vectors.ndim != 2 or vectors.dtype != np.int32:
            raise ValueError("vectors must be a 2-D int32 array")
        self.vectors = vectors
        self.d = int(vectors.shape[1])
        # §5.2 initial state: S = 0, n = 0, r_agg = 0, C_S = identity, no members. S is i64 (§4.4).
        self.S = np.zeros(self.d, dtype=np.int64)
        self.n = 0
        self.members: dict[str, int] = {}  # record ID -> row in `vectors`
        self.blinding = blinding  # row -> r_t (§9.4), owned by the index; never shown or stored
        self.committed = False
        self.r_agg = 0
        self.C_S = IDENTITY
        self.last_transition: Transition | None = None

    def start_commitments(self) -> None:
        """Switch commitments on: r_agg = Σ r_t over the members, C_S = commit(S, r_agg).

        Demo shortcut, stated: the engine adds each C_t on insert (§5.3). Loading 1M records
        that way takes about 70 ms each (~20 h), so a loaded group's C_S is computed in one step.
        It is the same value: commitments add (C(a) + C(b) = C(a + b)). Every insert and delete
        after this point updates C_S record by record.
        """
        if self.blinding is None:
            raise ValueError("no blinding values: the index owns them")
        self.r_agg = sum(self.blinding[row] for row in self.members.values()) % L
        self.C_S = commit(self.S.tolist(), self.r_agg)
        self.committed = True

    def _record_commitment(self, row: int) -> tuple[int, bytes]:
        assert self.blinding is not None
        r_t = self.blinding[row]
        return r_t, commit(self.vectors[row].tolist(), r_t)  # §9.3: C_t = r_t·H + Σ x̃_i·G_i

    def insert(self, rid: str, row: int) -> None:
        # §3.2 rule 3: an ID can be live only once. (The index also checks this across groups.)
        if rid in self.members:
            raise DuplicateRecord("record ID is already live")
        # §5.6: an insert that would make n > 1,000,000 is rejected. Group sizes may appear (§17).
        if self.n + 1 > MAX_MEMBERS:
            raise GroupCapacityExceeded(f"group already holds {self.n} members")
        # Plan, then apply: everything that can fail is computed before any field changes.
        r_t, c_t = self._record_commitment(row) if self.committed else (0, IDENTITY)
        # §5.3: S <- S + x̃, n <- n + 1, r_agg <- r_agg + r_t, C_S <- C_S + C_t, together (INV-2).
        self.S += self.vectors[row].astype(np.int64)
        self.n += 1
        self.members[rid] = row
        if self.committed:
            self.C_S = point_add(self.C_S, c_t)
            self.r_agg = (self.r_agg + r_t) % L
        if SABOTAGE == "SB-1" and self.n == 1:
            self.S[0] ^= 1

    def delete(self, rid: str, row: int) -> Outcome:
        """Delete record `rid`, whose vector the caller presents as dataset row `row`."""
        if SABOTAGE != "SB-3":
            # §5.4: membership check *before* subtracting. Absent -> AlreadyAbsent, nothing changes.
            if rid not in self.members:
                return Outcome.ALREADY_ABSENT
            if self.members[rid] != row:
                raise IntegrityViolation("presented vector does not match the stored member")
        r_t, c_t = self._record_commitment(row) if self.committed else (0, IDENTITY)
        c_s_pre = self.C_S
        # §5.3: S <- S - x̃, n <- n - 1, r_agg <- r_agg - r_t, C_S <- C_S - C_t, together (INV-2).
        self.S -= self.vectors[row].astype(np.int64)
        if SABOTAGE != "SB-2":
            self.n -= 1
        # §5.4 physical excision: the member is removed, no deletion marker is kept.
        self.members.pop(rid, None)
        if self.committed:
            self.C_S = point_sub(self.C_S, c_t)
            if SABOTAGE != "SB-4":
                self.r_agg = (self.r_agg - r_t) % L
            self.last_transition = Transition(
                c_t=c_t,
                c_s_pre=c_s_pre,
                c_s_post=self.C_S,
                r_post=self.r_agg,
                s_post=tuple(int(v) for v in self.S),
                emptied=self.n == 0,
            )
        return Outcome.DELETED

    def sorted_members(self) -> list[tuple[bytes, int]]:
        """Members as (ID as UTF-8 bytes, row), ascending by the bytes (§3.2, §5.5)."""
        return sorted((rid.encode("utf-8"), row) for rid, row in self.members.items())

    def blob_chunks(self) -> Iterator[bytes]:
        """The canonical group blob, in pieces.

        With commitments (§5.5 exactly):
            b"SEVERG" | u16be version | u16be d | u64be n | i64be x d (S) | C_S (32) | r_agg (32) |
            u64be member_count | per member, ascending by ID bytes:
            u16be id_len | id | i64be x d (x̃)
        Without: magic b"SEVERC" and no C_S / r_agg (the Day 2 demo layout).
        """
        members = self.sorted_members()
        magic = MAGIC_SPEC if self.committed else MAGIC_DEMO
        yield magic + struct.pack(">HHQ", FORMAT_VERSION, self.d, self.n)
        yield self.S.astype(">i8").tobytes()
        if self.committed:
            yield self.C_S + scalar_bytes(self.r_agg)  # §0.2: scalar = 32 bytes little-endian
        yield struct.pack(">Q", len(members))  # §5.5: MUST equal n (SB-2 breaks this)
        for start in range(0, len(members), _BLOB_BATCH):
            batch = members[start : start + _BLOB_BATCH]
            rows = np.fromiter((row for _, row in batch), dtype=np.int64, count=len(batch))
            vecs = self.vectors[rows].astype(">i8")
            yield b"".join(
                struct.pack(">H", len(id_bytes)) + id_bytes + vec.tobytes()
                for (id_bytes, _), vec in zip(batch, vecs, strict=True)
            )

    def blob(self) -> bytes:
        return b"".join(self.blob_chunks())

    def blob_hash(self) -> str:
        # Streamed: a 7,800-member group's blob is about 24 MB; never build it whole to hash it.
        h = hashlib.sha256()
        for piece in self.blob_chunks():
            h.update(piece)
        return h.hexdigest()

    def snapshot(self) -> "Snapshot":
        return Snapshot(
            S=self.S.astype(">i8").tobytes(),
            n=self.n,
            member_ids=tuple(id_bytes for id_bytes, _ in self.sorted_members()),
            blob_sha256=self.blob_hash(),
            committed=self.committed,
            C_S=self.C_S,
        )


@dataclass(frozen=True)
class Snapshot:
    """A frozen copy of a group's state, so one moment can be compared with another (§5.5)."""

    S: bytes
    n: int
    member_ids: tuple[bytes, ...]
    blob_sha256: str
    committed: bool = False
    C_S: bytes = IDENTITY


def compare(a: Snapshot, b: Snapshot) -> dict[str, bool]:
    """§5.5 exactness relation, each field compared on its own: S, n, members, blob, and C_S
    when either side has commitments (5 of 5 fields); without commitments, 4 of 5."""
    result = {
        "S": a.S == b.S,
        "n": a.n == b.n,
        "members": a.member_ids == b.member_ids,
        "blob": a.blob_sha256 == b.blob_sha256,
    }
    if a.committed or b.committed:
        result["C_S"] = a.committed == b.committed and a.C_S == b.C_S
    return result


def fresh_sum(vectors: npt.NDArray[np.int32], rows: Iterable[int]) -> npt.NDArray[np.int64]:
    """S recomputed from scratch by separate code, so a check never compares S with itself."""
    idx = np.fromiter(rows, dtype=np.int64)
    # dtype=int64 accumulates in i64 directly (exact), without an i64 copy of every row.
    total: npt.NDArray[np.int64] = vectors[idx].sum(axis=0, dtype=np.int64)
    return total


def rebuild(
    vectors: npt.NDArray[np.int32],
    items: Iterable[tuple[str, int]],
    rng: np.random.Generator,
    blinding: Sequence[int] | None = None,
    committed: bool = False,
) -> Group:
    """A new group holding `items`, inserted in a shuffled order. With `committed`, its r_agg and
    C_S are then computed in one step from its own S and members (a different path from a live
    group's record-by-record point arithmetic)."""
    pairs = list(items)
    fresh = Group(vectors, blinding)
    for i in rng.permutation(len(pairs)):
        rid, row = pairs[i]
        fresh.insert(rid, row)
    if committed:
        fresh.start_commitments()
    return fresh


def survivors_report(
    group: Group, rng: np.random.Generator
) -> tuple[Snapshot, Snapshot, dict[str, bool]]:
    """survivors_check, plus both snapshots it compared (live, rebuilt), so a screen can show them.

    One rebuild, so the random generator is used exactly as by survivors_check.
    """
    rebuilt = rebuild(
        group.vectors, group.members.items(), rng, group.blinding, committed=group.committed
    )
    live, fresh = group.snapshot(), rebuilt.snapshot()
    result = compare(live, fresh)
    rows = list(group.members.values())
    result["S"] = result["S"] and bool(np.array_equal(group.S, fresh_sum(group.vectors, rows)))
    result["n"] = result["n"] and group.n == len(rows)
    return live, fresh, result


def survivors_check(group: Group, rng: np.random.Generator) -> dict[str, bool]:
    """Is this group exactly a group built from its survivors only? (§5.3 "as if never inserted")

    Compares the live group with a fresh group built from the current members in a shuffled order,
    and also checks S and n against values computed without any Group code.
    """
    return survivors_report(group, rng)[2]
