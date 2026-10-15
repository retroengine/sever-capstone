"""A group's Part 3 state (§5.3–5.5, §9.3–9.4): ``S``, ``n``, ``r_agg`` and ``C_S`` change
together on every insert and delete, and the canonical blob takes its full form (magic ``SEVERG``,
extension region ``C_S ‖ r_agg``, DB-47). Written from the spec; record IDs sort by their UTF-8
bytes (§0.2)."""

import struct
from dataclasses import dataclass, field
from typing import Final

from sever_refmodel_certs import spec
from sever_refmodel_certs.ristretto import IDENTITY, L, Point, decode, encode, encode_scalar

MAGIC_FULL: Final = b"SEVERG"
MAGIC_CORE: Final = b"SEVERC"


@dataclass
class Removal:
    """What a deletion exposes to the certificate (§9.5, §11.1 tags 1–3 and 11)."""

    c_s_pre: bytes
    c_t: bytes
    c_s_post: bytes
    group_emptied: bool


@dataclass
class CertGroup:
    """One frozen or spawned group: members ``{record_id: (x̃, r_t)}`` and the four fields of
    §5.3."""

    d: int
    members: dict[str, tuple[tuple[int, ...], int]] = field(default_factory=dict)
    s: list[int] = field(default_factory=list)
    r_agg: int = 0
    c_s: Point = IDENTITY

    def __post_init__(self) -> None:
        if not self.s:
            self.s = [0] * self.d  # §5.2 initial state; C_S = identity, r_agg = 0

    @property
    def n(self) -> int:
        return len(self.members)

    def insert(self, rid: str, x: tuple[int, ...], r_t: int) -> bytes:
        """§5.3 insert: ``S ← S + x̃``, ``n ← n + 1``, ``r_agg ← r_agg + r_t``, ``C_S ← C_S + C_t``.
        Returns ``C_t``."""
        if rid in self.members or len(x) != self.d:
            raise ValueError("insert: duplicate ID or wrong dimension")
        c_t = spec.commit(list(x), r_t)
        self.members[rid] = (x, r_t % L)
        self.s = [a + b for a, b in zip(self.s, x, strict=True)]
        self.r_agg = (self.r_agg + r_t) % L
        self.c_s = self.c_s + c_t
        return encode(c_t)

    def delete(self, rid: str) -> Removal | None:
        """§5.3 delete with the stored ``r_t`` (§9.4); ``None`` if absent (§5.4,
        ``AlreadyAbsent``)."""
        if rid not in self.members:
            return None
        x, r_t = self.members.pop(rid)
        c_t = spec.commit(list(x), r_t)
        pre = encode(self.c_s)
        self.s = [a - b for a, b in zip(self.s, x, strict=True)]
        self.r_agg = (self.r_agg - r_t) % L
        self.c_s = self.c_s - c_t
        post = encode(self.c_s)
        return Removal(pre, encode(c_t), post, post == bytes(32))

    def full_blob(self) -> bytes:
        """§5.5 full form: ``SEVERG ‖ u16be 1 ‖ u16be d ‖ u64be n ‖ S (i64be × d) ‖ C_S ‖ r_agg ‖
        u64be member_count ‖`` members ascending by ID bytes, each ``u16be id_len ‖ id ‖ x̃`` with
        ``x̃`` as i64be."""
        out = [
            MAGIC_FULL,
            struct.pack(">HHQ", 1, self.d, self.n),
            struct.pack(f">{self.d}q", *self.s),
        ]
        out += [encode(self.c_s), encode_scalar(self.r_agg), struct.pack(">Q", self.n)]
        for rid in sorted(self.members, key=lambda r: r.encode("utf-8")):
            b = rid.encode("utf-8")
            out.append(
                struct.pack(">H", len(b)) + b + struct.pack(f">{self.d}q", *self.members[rid][0])
            )
        return b"".join(out)


class BlobError(ValueError):
    """A §5.5 parser rejection."""


def parse_full_blob(blob: bytes) -> tuple[int, list[int], bytes, bytes, dict[str, tuple[int, ...]]]:
    """§5.5 full-form parser: ``(n, S, C_S, r_agg, members)``; rejects a magic other than ``SEVERG``
    (the core one included), ``member_count ≠ n``, unsorted, duplicate or empty IDs, a
    non-canonical ``C_S`` or ``r_agg`` (§9.9) and trailing bytes."""
    if blob[:6] != MAGIC_FULL:
        raise BlobError("magic")
    try:
        version, d, n = struct.unpack_from(">HHQ", blob, 6)
        if version != 1:
            raise BlobError("version")
        pos = 18
        s = list(struct.unpack_from(f">{d}q", blob, pos))
        pos += 8 * d
        c_s, r_agg = blob[pos : pos + 32], blob[pos + 32 : pos + 64]
        if len(r_agg) != 32:
            raise BlobError("truncated")
        decode(c_s)
        if int.from_bytes(r_agg, "little") >= L:
            raise BlobError("r_agg not canonical")
        pos += 64
        (count,) = struct.unpack_from(">Q", blob, pos)
        pos += 8
        if count != n:
            raise BlobError("member_count != n")
        members: dict[str, tuple[int, ...]] = {}
        prev: bytes | None = None
        for _ in range(count):
            (ln,) = struct.unpack_from(">H", blob, pos)
            pos += 2
            b = blob[pos : pos + ln]
            if ln == 0 or len(b) != ln:
                raise BlobError("empty or truncated ID")
            if prev is not None and b <= prev:
                raise BlobError("IDs not ascending or duplicate")
            pos += ln
            members[b.decode("utf-8")] = tuple(struct.unpack_from(f">{d}q", blob, pos))
            pos += 8 * d
            prev = b
    except struct.error as e:
        raise BlobError("truncated") from e
    except ValueError as e:  # a non-canonical C_S (DecodeError) or a bad UTF-8 ID
        if isinstance(e, BlobError):
            raise
        raise BlobError("field not canonical") from e
    if pos != len(blob):
        raise BlobError("trailing bytes")
    return n, s, c_s, r_agg, members
