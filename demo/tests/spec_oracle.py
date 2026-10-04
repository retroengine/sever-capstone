"""Expected values written from the specification, never from the code under test.

Rules for this file (CLAUDE.md §7: "the reference model is written from the spec only"):
- imports nothing from sever_demo;
- plain Python integers and floats, no NumPy, so it shares no arithmetic path with the code;
- every function cites the rule it encodes.

Vectors are given as Python lists of the quantised integers x̃ (§4.2).
"""

import struct
from collections.abc import Mapping, Sequence
from typing import Any

# Demo blob (DEMO_PLAN §5.5, after spec §5.5 without C_S and r_agg).
MAGIC = b"SEVERC"
FORMAT_VERSION = 1


def group_sum(members: Mapping[str, Sequence[int]], d: int) -> list[int]:
    """§5.3: S is the sum of the members' x̃, component by component."""
    total = [0] * d
    for vec in members.values():
        for i in range(d):
            total[i] += int(vec[i])
    return total


def group_blob(members: Mapping[str, Sequence[int]], d: int) -> bytes:
    """The canonical blob of a group whose members are exactly `members` (ID -> x̃).

    b"SEVERC" | u16be version | u16be d | u64be n | i64be x d (S) | u64be member_count |
    per member, ascending by ID UTF-8 bytes: u16be id_len | id bytes | i64be x d (x̃)
    """
    n = len(members)
    out = MAGIC + struct.pack(">HHQ", FORMAT_VERSION, d, n)
    out += b"".join(struct.pack(">q", s) for s in group_sum(members, d))
    out += struct.pack(">Q", n)
    for rid in sorted(members, key=lambda r: r.encode("utf-8")):  # §3.2: compare by UTF-8 bytes
        raw = rid.encode("utf-8")
        out += struct.pack(">H", len(raw)) + raw
        out += b"".join(struct.pack(">q", int(v)) for v in members[rid])
    return out


def nearest(x: Sequence[int], centroids: Sequence[Sequence[float]]) -> int:
    """§7.1: argmin over j of sum_i (x̂_i - mu_j,i)^2, float64, sequential from i = 0; ties to the
    smaller label. x̂ = x̃ / 2^24 (§4.3)."""
    best_j, best_d = -1, float("inf")
    for j, mu in enumerate(centroids):
        dist = 0.0
        for i, xi in enumerate(x):
            diff = xi / 2**24 - float(mu[i])
            dist += diff * diff
        if dist < best_d:  # strict: an equal distance keeps the smaller label
            best_j, best_d = j, dist
    return best_j


def observed(group: Any) -> tuple[list[int], int, list[bytes], bytes]:
    """The four §5.5 fields as the outside world sees them: S, n, member IDs, blob bytes."""
    s = [int(v) for v in group.S]
    ids = sorted(r.encode("utf-8") for r in group.members)
    return s, int(group.n), ids, bytes(group.blob())


def expected(
    members: Mapping[str, Sequence[int]], d: int
) -> tuple[list[int], int, list[bytes], bytes]:
    """The four §5.5 fields of a group built from `members` only (the survivors)."""
    ids = sorted(r.encode("utf-8") for r in members)
    return group_sum(members, d), len(members), ids, group_blob(members, d)


def field_diffs(group: Any, members: Mapping[str, Sequence[int]], d: int) -> list[str]:
    """§5.5: each field compared on its own. Returns the names of the fields that differ."""
    names = ["S", "n", "members", "blob"]
    return [
        f for f, a, b in zip(names, observed(group), expected(members, d), strict=True) if a != b
    ]


# --- Part 3 preview: the full five-field relation (§5.5) with commitments ---------------------
# C_S is computed by the independent verifier's code (python/sever_verify), which shares nothing
# with the engine and is itself pinned to the RFC 9496 / RFC 9380 test vectors (test_crypto.py).
from sever_verify.ristretto import ORDER, commitment  # noqa: E402


def committed_blob(
    members: Mapping[str, Sequence[int]], blinding: Mapping[str, int], d: int
) -> bytes:
    """§5.5 exactly: b"SEVERG" | u16be 1 | u16be d | u64be n | i64be x d (S) | C_S |
    r_agg (32, LE) | u64be member_count |
    members ascending by ID bytes: u16be len | id | i64be x d."""
    n = len(members)
    s = group_sum(members, d)
    r_agg = sum(blinding[r] for r in members) % ORDER
    out = b"SEVERG" + struct.pack(">HHQ", 1, d, n)
    out += b"".join(struct.pack(">q", v) for v in s)
    out += commitment(s, r_agg) + r_agg.to_bytes(32, "little")
    out += struct.pack(">Q", n)
    for rid in sorted(members, key=lambda r: r.encode("utf-8")):
        raw = rid.encode("utf-8")
        out += struct.pack(">H", len(raw)) + raw
        out += b"".join(struct.pack(">q", int(v)) for v in members[rid])
    return out


def committed_field_diffs(
    group: Any, members: Mapping[str, Sequence[int]], blinding: Mapping[str, int], d: int
) -> list[str]:
    """§5.5: all five fields, each on its own: S, n, members, C_S, blob."""
    s = group_sum(members, d)
    r_agg = sum(blinding[r] for r in members) % ORDER
    want = {
        "S": s,
        "n": len(members),
        "members": sorted(r.encode("utf-8") for r in members),
        "C_S": commitment(s, r_agg),
        "blob": committed_blob(members, blinding, d),
    }
    got = {
        "S": [int(v) for v in group.S],
        "n": int(group.n),
        "members": sorted(r.encode("utf-8") for r in group.members),
        "C_S": bytes(group.C_S),
        "blob": bytes(group.blob()),
    }
    return [f for f in want if want[f] != got[f]]
