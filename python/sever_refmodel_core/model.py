"""The Part 1 reference model (spec §3–§8), one rule at a time.

Every float computation follows the spec's pinned order: float64 sums are sequential
(``np.cumsum(...)[..., -1]``), and the search kernel is the 8-lane float32 layout of §8.2. Integer
sums use Python ``int`` (unbounded), so overflow can never hide a bug here.
"""

import hashlib
import hmac
import math
import re
import struct
from dataclasses import dataclass, field
from typing import Final, Literal

import numpy as np
from numpy.typing import NDArray

from sever_partition import arith
from sever_partition.artefact import Artefact

# --- constants (§2.2) ----------------------------------------------------------------------------

SCALE: Final = 1 << 24
MAX_GROUP_MEMBERS: Final = 1_000_000
SPAWN_TARGET_V1: Final = 200
HOLDING: Final = "holding"
_COUNTER: Final = re.compile(r"[+-]?[0-9]+")  # §3.2 rule 2; Python's [0-9] is ASCII only


# --- errors (§17) --------------------------------------------------------------------------------


class SeverError(Exception):
    """A §17 error. ``kind`` is the §17 name; the message never contains caller data."""

    kind: str = "SeverError"


class WrongDimensionError(SeverError):
    """§4.1 step 0."""

    kind = "WrongDimension"


class NonFiniteError(SeverError):
    """§4.1 step 1."""

    kind = "NonFinite"


class NotNormalisedError(SeverError):
    """§4.1 step 3."""

    kind = "NotNormalised"


class InvalidRecordIdError(SeverError):
    """§3.2 rules 1–2."""

    kind = "InvalidRecordId"


class DuplicateRecordError(SeverError):
    """§3.2 rule 3. ``same_commitment``: Part 1 has no commitments, so a retry is recognised by an
    identical quantised vector (the EP-1 ``NoExtension`` rule)."""

    kind = "DuplicateRecord"

    def __init__(self, same_commitment: bool) -> None:
        super().__init__(f"duplicate record (same commitment: {same_commitment})")
        self.same_commitment = same_commitment


class GroupCapacityExceededError(SeverError):
    """§5.6 hard cap."""

    kind = "GroupCapacityExceeded"


class IntegrityViolationError(SeverError):
    """§7.2 (q < 0), §7.5 (spawn ID collision), §21 invariants."""

    kind = "IntegrityViolation"


# --- §4 arithmetic -------------------------------------------------------------------------------


def check_vector(x: NDArray[np.float32], d: int) -> None:
    """§4.1 steps 0–3, in order."""
    if x.shape != (d,):
        raise WrongDimensionError("wrong dimension")
    if not np.isfinite(x).all():
        raise NonFiniteError("non-finite component")
    x64 = x.astype(np.float64)
    norm = math.sqrt(float(np.cumsum(x64 * x64)[-1]))
    if not abs(norm - 1.0) <= 8.0 * 2.0**-23:
        raise NotNormalisedError("not normalised")


def quantise(x: NDArray[np.float32]) -> tuple[int, ...]:
    """§4.2: round half to even of (f64)x · 2^24."""
    return tuple(int(v) for v in np.round(x.astype(np.float64) * float(SCALE)))


def check_record_id(record_id: str) -> None:
    """§3.2 rules 1 and 2 (rule 3 needs the index)."""
    n = len(record_id.encode("utf-8"))
    if not 1 <= n <= 256:
        raise InvalidRecordIdError("invalid record id")
    if _COUNTER.fullmatch(record_id):
        raise InvalidRecordIdError("invalid record id")


def id_bytes(record_id: str) -> bytes:
    """§0.2: IDs compare by their raw UTF-8 bytes."""
    return record_id.encode("utf-8")


def scrambled_id(k_scramble: bytes, collection_id: bytes, record_id: str) -> bytes:
    """§9.7: HMAC-SHA-512(k_scramble, collection_id ‖ record_id_bytes), 64 bytes."""
    return hmac.new(k_scramble, collection_id + id_bytes(record_id), hashlib.sha512).digest()


def seq_sqdist_f64(a: NDArray[np.float64], centroids: NDArray[np.float64]) -> NDArray[np.float64]:
    """Σ_i (a_i − μ_i)² in float64, sequential from i = 0, for each centroid row (§7.1, §8.1)."""
    diff = a[np.newaxis, :] - centroids
    return np.asarray(np.cumsum(diff * diff, axis=1)[:, -1], dtype=np.float64)


def kernel_scores(q: NDArray[np.float32], xs: NDArray[np.float32]) -> NDArray[np.float32]:
    """§8.2: eight float32 lanes, lane j = i mod 8, ``t = q_i − x̂_i; L_j = L_j + t·t`` with the
    multiply and the add separate, starting at +0.0; then
    ((L0 + L1) + (L2 + L3)) + ((L4 + L5) + (L6 + L7))."""
    m, d = xs.shape
    t = (q[np.newaxis, :] - xs).astype(np.float32)
    sq = (t * t).astype(np.float32)
    # lanes[r, s, j] = sq[r, 8s + j]; cumsum over s (float32 accumulator) is each lane's sequence.
    lanes = np.cumsum(sq.reshape(m, d // 8, 8), axis=1, dtype=np.float32)[:, -1, :]
    l0, l1, l2, l3, l4, l5, l6, l7 = (lanes[:, j] for j in range(8))
    return ((l0 + l1) + (l2 + l3)) + ((l4 + l5) + (l6 + l7))


# --- groups (§5) ---------------------------------------------------------------------------------

Kind = Literal["frozen", "spawned"]


@dataclass
class Group:
    """§5.2 core state: S, n, centroid, members (x̃ by record ID). C_S and r_agg join in Part 3.

    ``enc`` caches each member's blob encoding (u16be id_len ‖ id ‖ i64be × d), so a group's blob
    is a sort and a join; the layout is exactly ``core_blob``'s (tested)."""

    gid: str
    kind: Kind
    centroid: NDArray[np.float64]
    d: int
    members: dict[str, tuple[int, ...]] = field(default_factory=dict)
    s: list[int] = field(default_factory=list)
    enc: dict[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.s:
            self.s = [0] * self.d  # §5.2 initial state: S = 0, n = 0

    @property
    def n(self) -> int:
        return len(self.members)

    def add(self, rid: str, xq: tuple[int, ...]) -> None:
        """§5.3 insert: S ← S + x̃, n ← n + 1."""
        self.members[rid] = xq
        self.s = [a + b for a, b in zip(self.s, xq, strict=True)]
        b = id_bytes(rid)
        self.enc[rid] = struct.pack(">H", len(b)) + b + np.asarray(xq, dtype=">i8").tobytes()

    def remove(self, rid: str) -> None:
        """§5.3 delete: S ← S − x̃, n ← n − 1; §5.4 physical excision (no marker)."""
        xq = self.members.pop(rid)
        del self.enc[rid]
        self.s = [a - b for a, b in zip(self.s, xq, strict=True)]

    def blob(self) -> bytes:
        """§5.5 core blob from the cached member encodings."""
        head = b"SEVERC" + struct.pack(">HHQ", 1, self.d, self.n)
        head += struct.pack(f">{self.d}q", *self.s) + struct.pack(">Q", self.n)
        return head + b"".join(self.enc[r] for r in sorted(self.members, key=id_bytes))


def core_blob(d: int, s: list[int], members: dict[str, tuple[int, ...]]) -> bytes:
    """§5.5 canonical group blob, core form (DB-47): magic SEVERC, empty extension region."""
    out = [b"SEVERC", struct.pack(">HHQ", 1, d, len(members))]
    out.append(struct.pack(f">{d}q", *s))
    out.append(struct.pack(">Q", len(members)))  # member_count, equal to n
    for rid in sorted(members, key=id_bytes):  # ascending by record-ID bytes
        b = id_bytes(rid)
        out.append(struct.pack(">H", len(b)) + b)
        out.append(struct.pack(f">{d}q", *members[rid]))  # x̃ widened to i64
    return b"".join(out)


class BlobError(ValueError):
    """§5.5 parser rejection."""


def parse_core_blob(blob: bytes) -> tuple[int, list[int], dict[str, tuple[int, ...]]]:
    """§5.5 parser: rejects member_count ≠ n, unsorted or duplicate IDs, empty IDs, trailing bytes
    (and a wrong magic, DB-47). Returns (n, S, members)."""
    if blob[:6] != b"SEVERC":
        raise BlobError("magic")
    try:
        version, d, n = struct.unpack_from(">HHQ", blob, 6)
        if version != 1:
            raise BlobError("version")
        pos = 18
        s = list(struct.unpack_from(f">{d}q", blob, pos))
        pos += 8 * d
        (count,) = struct.unpack_from(">Q", blob, pos)
        pos += 8
        if count != n:
            raise BlobError("member_count != n")
        members: dict[str, tuple[int, ...]] = {}
        prev: bytes | None = None
        for _ in range(count):
            (ln,) = struct.unpack_from(">H", blob, pos)
            pos += 2
            if ln == 0:
                raise BlobError("empty id")
            raw = blob[pos : pos + ln]
            if len(raw) != ln:
                raise BlobError("truncated")
            pos += ln
            if prev is not None and raw <= prev:
                raise BlobError("unsorted or duplicate ids")
            prev = raw
            xq = tuple(struct.unpack_from(f">{d}q", blob, pos))
            pos += 8 * d
            members[raw.decode("utf-8")] = xq
    except struct.error as e:
        raise BlobError("truncated") from e
    if pos != len(blob):
        raise BlobError("trailing bytes")
    return n, s, members


def has_room(n: int, k: int, big_n: int) -> bool:
    """§5.6, §7.3: a spawned group has room iff 2·k·n < 3·N (exact integers; n < 1.5·N/k)."""
    return 2 * k * n < 3 * big_n


def probe_count(k: int) -> int:
    """§8.1 step 2: p = ⌈0.25·k⌉ over frozen and spawned groups, empty ones included."""
    return -(-k // 4)


# --- the exactness relation (§5.5) ---------------------------------------------------------------


@dataclass(frozen=True)
class GroupSnapshot:
    """A frozen snapshot with every field stored as data, so each can be corrupted on its own
    (§5.5). ``c_s`` is None until commitments exist (Part 3, DB-47)."""

    s: tuple[int, ...]
    n: int
    c_s: bytes | None
    blob: bytes
    member_ids: tuple[str, ...]


class NotEquivalentError(AssertionError):
    """§5.5: two group states differ in at least one field; ``field`` names the first found."""

    def __init__(self, which: str) -> None:
        super().__init__(f"group states differ in {which}")
        self.field = which


def snapshot(g: "Group") -> GroupSnapshot:
    return GroupSnapshot(
        tuple(g.s),
        g.n,
        None,
        core_blob(g.d, g.s, g.members),
        tuple(sorted(g.members, key=id_bytes)),
    )


def assert_state_equivalent(a: GroupSnapshot, b: GroupSnapshot) -> None:
    """§5.5: equivalent iff (1) S, (2) n, (3) C_S, (4) the blob, (5) the member ID list are all
    equal. Each field is compared independently; the redundancy is deliberate."""
    if a.s != b.s:
        raise NotEquivalentError("S")
    if a.n != b.n:
        raise NotEquivalentError("n")
    if a.c_s != b.c_s:
        raise NotEquivalentError("C_S")
    if a.blob != b.blob:
        raise NotEquivalentError("blob")
    if a.member_ids != b.member_ids:
        raise NotEquivalentError("member IDs")


# --- the index (§5, §7, §8) ----------------------------------------------------------------------

Placement = tuple[Literal["frozen", "spawned", "holding"], str]


@dataclass(frozen=True)
class Deleted:
    """§5.4: the record was a member and is now excised. ``gid`` is where it was."""

    gid: str


@dataclass(frozen=True)
class AlreadyAbsent:
    """§5.4: the record was not live; nothing changed."""


Outcome = Deleted | AlreadyAbsent


def spawn_id(founders: list[str]) -> str:
    """§7.5: 'spawn-' + first 16 hex of SHA-256(‖_{ids ascending by bytes} u16be(len) ‖ id)."""
    h = hashlib.sha256()
    for b in sorted(id_bytes(r) for r in founders):
        h.update(struct.pack(">H", len(b)) + b)
    return "spawn-" + h.hexdigest()[:16]


class RefIndex:
    """One collection's index (Part 1): frozen groups from the artefact, spawned groups, holding."""

    def __init__(
        self,
        art: Artefact,
        spawning_enabled: bool = True,
        spawn_target: int = SPAWN_TARGET_V1,
    ) -> None:
        self.d = art.d
        self.tau = art.tau
        self.precision = art.precision
        self.spawning_enabled = spawning_enabled  # Build §4.3: the frozen-only control arm
        self.spawn_target = spawn_target  # §7.4 (200 in v1; gap G-10 for small fixtures)
        self.groups: dict[str, Group] = {}
        for label in range(art.k_frozen):
            gid = f"frozen-{label:04d}"  # §5.1
            self.groups[gid] = Group(gid, "frozen", art.centroids[label].copy(), art.d)
        self.frozen_centroids = art.centroids
        self.holding: dict[str, tuple[int, ...]] = {}
        self.where: dict[str, str] = {}  # live record ID → group ID or HOLDING
        self.big_n = 0  # §7.6 N
        self.ood_inserts = 0

    # -- counters (§7.6) --
    @property
    def k(self) -> int:
        """Frozen + spawned groups, holding excluded (§2.1)."""
        return len(self.groups)

    # -- routing (§7) --
    def route(self, xq: tuple[int, ...]) -> tuple[str, bool]:
        """§7.3 with k and N before this insert. Returns (destination, out_of_distribution)."""
        xhat = np.array(xq, dtype=np.float64) / float(SCALE)
        # §7.1: nearest frozen group, sequential f64, ties to the smaller label (argmin = first).
        dists = seq_sqdist_f64(xhat, self.frozen_centroids)
        j = int(np.argmin(dists))
        if not self.spawning_enabled:
            return f"frozen-{j:04d}", False
        # §7.2: Mahalanobis distance to μ_{j*}.
        try:
            dm = float(
                arith.mahalanobis(xhat[np.newaxis, :], self.frozen_centroids[[j]], self.precision)[
                    0
                ]
            )
        except arith.IntegrityViolationError as e:
            raise IntegrityViolationError("q < 0") from e
        if dm <= self.tau:
            return f"frozen-{j:04d}", False
        # Out of distribution: spillover first (§7.3), room iff 2·k·n < 3·N.
        room = [
            g
            for g in self.groups.values()
            if g.kind == "spawned" and has_room(g.n, self.k, self.big_n)
        ]
        if room:
            best = min(
                room,
                key=lambda g: (
                    float(seq_sqdist_f64(xhat, g.centroid[np.newaxis, :])[0]),
                    id_bytes(g.gid),
                ),
            )
            return best.gid, True
        return HOLDING, True

    # -- insert (§15.1 order of checks; §5.3; §7.4) --
    def insert(self, record_id: str, x: NDArray[np.float32]) -> Placement:
        check_vector(x, self.d)
        check_record_id(record_id)
        xq = quantise(x)
        if record_id in self.where:
            loc = self.where[record_id]
            live = (
                self.holding[record_id] if loc == HOLDING else self.groups[loc].members[record_id]
            )
            raise DuplicateRecordError(same_commitment=live == xq)
        dest, ood = self.route(xq)
        if dest != HOLDING and self.groups[dest].n + 1 > MAX_GROUP_MEMBERS:
            raise GroupCapacityExceededError("group capacity exceeded")
        if dest == HOLDING:
            if len(self.holding) + 1 == self.spawn_target:
                return self._flush_with(record_id, xq)
            self.holding[record_id] = xq
            self.where[record_id] = HOLDING
            self.ood_inserts += 1
            return ("holding", HOLDING)
        self.groups[dest].add(record_id, xq)
        self.where[record_id] = dest
        self.big_n += 1
        self.ood_inserts += int(ood)
        return (self.groups[dest].kind, dest)

    def _flush_with(self, record_id: str, xq: tuple[int, ...]) -> Placement:
        """§7.4–7.5: the insert that brings the holding area to exactly the target size forms
        exactly one spawned group from exactly those records. All checks precede any change."""
        cohort = dict(self.holding)
        cohort[record_id] = xq
        gid = spawn_id(list(cohort))
        if gid in self.groups:
            raise IntegrityViolationError("spawn ID collision")
        s = [sum(col) for col in zip(*cohort.values(), strict=True)]
        n = len(cohort)
        # §7.5: μ_i = ((f64)S_i / 2^24) / n, frozen at creation.
        centroid = np.array([(float(v) / float(SCALE)) / n for v in s], dtype=np.float64)
        g = Group(gid, "spawned", centroid, self.d)
        for rid in sorted(cohort, key=id_bytes):
            g.add(rid, cohort[rid])
            self.where[rid] = gid
        self.groups[gid] = g
        self.holding.clear()
        self.big_n += n
        self.ood_inserts += 1
        return ("spawned", gid)

    # -- delete (§5.4) --
    def delete(self, record_id: str) -> Outcome:
        loc = self.where.pop(record_id, None)
        if loc is None:
            return AlreadyAbsent()  # §5.4: nothing changes
        if loc == HOLDING:
            del self.holding[record_id]  # no accumulator, N unchanged (§7.6)
        else:
            self.groups[loc].remove(record_id)
            self.big_n -= 1
        return Deleted(loc)

    def delete_user(self, record_ids: list[str]) -> list[Outcome]:
        """§3.5, §12.5: a cohort in list order, as one unit (nothing in Part 1 can fail midway)."""
        return [self.delete(r) for r in record_ids]

    # -- search (§8) --
    def search(self, q: NDArray[np.float32], k_results: int) -> list[tuple[str, float]]:
        check_vector(q, self.d)
        q64 = q.astype(np.float64)
        ranked = sorted(
            self.groups.values(),
            key=lambda g: (
                float(seq_sqdist_f64(q64, g.centroid[np.newaxis, :])[0]),
                id_bytes(g.gid),
            ),
        )
        p = probe_count(self.k)  # empty groups included
        ids: list[str] = []
        rows: list[tuple[int, ...]] = []
        for g in ranked[:p]:
            for rid, xq in g.members.items():
                ids.append(rid)
                rows.append(xq)
        if not ids:
            return []
        mirror = (np.array(rows, dtype=np.float64) / float(SCALE)).astype(np.float32)  # §4.3
        scores = kernel_scores(q, mirror)
        order = sorted(range(len(ids)), key=lambda i: (float(scores[i]), id_bytes(ids[i])))
        return [(ids[i], float(scores[i])) for i in order[:k_results]]

    # -- observation --
    def blob(self, gid: str) -> bytes:
        return self.groups[gid].blob()

    def stats(self) -> dict[str, int]:
        spawned = sum(1 for g in self.groups.values() if g.kind == "spawned")
        return {
            "frozen": self.k - spawned,
            "spawned": spawned,
            "N": self.big_n,
            "k": self.k,
            "holding": len(self.holding),
        }

    def check_invariants(self) -> None:
        """INV-4, INV-6, INV-8 and the locator correspondence (INV-7, model form)."""
        total = 0
        for g in self.groups.values():
            if g.n > MAX_GROUP_MEMBERS:
                raise IntegrityViolationError("INV-4")
            expect = (
                [sum(col) for col in zip(*g.members.values(), strict=True)]
                if g.members
                else [0] * self.d
            )
            if g.s != expect:
                raise IntegrityViolationError("INV-6")
            total += g.n
        if total != self.big_n:
            raise IntegrityViolationError("INV-8")
        live = {r: gid for gid, g in self.groups.items() for r in g.members}
        live.update({r: HOLDING for r in self.holding})
        if live != self.where:
            raise IntegrityViolationError("INV-7")
