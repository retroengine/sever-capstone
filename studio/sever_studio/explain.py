"""Words for what the engine did: the certificate's fields, one observed line per deletion, the
glossary.

Every number comes from the engine (its receipts and sizes), never from arithmetic of Studio's own
(audit 2, H4: nothing is stated that was not observed).
"""

import math
from typing import TYPE_CHECKING

from .backend import HOLDING

if TYPE_CHECKING:
    from .actions import Deleted

#: §11.1, the certificate's fields by tag.
FIELDS = {
    1: "commitment_to_deleted_vector (C_t)",
    2: "group_commitment_before (C_S_pre)",
    3: "group_commitment_after (C_S_post)",
    4: "posk_proof",
    5: "user_authorisation_signature",
    6: "insert_inclusion",
    7: "witness_cosignatures",
    8: "key_period",
    9: "scrambled_record_id",
    10: "database_lsn",
    11: "group_emptied_by_this_deletion",
    12: "deletion_kind",
    13: "collection_id",
    0xFF: "operator signature",
}


def deleted_line(d: "Deleted") -> str:
    """One line of what a deletion was observed to do: each touched group's ``n`` before and after
    (the engine's ``group_sizes``) and the receipt numbers. Nothing Studio did not observe."""
    if not d.rids:
        return "nothing deleted"
    groups = sorted(set(d.groups_before) | set(d.groups_after))
    sizes = "; ".join(
        f"{g} n {d.groups_before.get(g, 0)} → {d.groups_after.get(g, 0)}"
        for g in groups
        if g != HOLDING
    )
    held = sum(1 for g in groups if g == HOLDING)
    parts = [f"deleted {len(d.rids)} record{'s' if len(d.rids) != 1 else ''}"]
    if sizes:
        parts.append(sizes)
    if held:
        parts.append("from the holding area: no group sum to change (§7.4)")
    if d.lsns:
        parts.append("receipt " + ", ".join(f"#{n}" for n in d.lsns))
    return "; ".join(parts)


def cert_field_at(cert: bytes, offset: int) -> tuple[int, str]:
    """The §11.1 field a byte of a certificate belongs to: ``(tag, name)``."""
    at = 0
    while at + 5 <= len(cert):
        tag, length = cert[at], int.from_bytes(cert[at + 1 : at + 5], "big")
        if offset < at + 5 + length:
            return tag, FIELDS.get(tag, f"tag {tag}")
        at += 5 + length
    return 0xFF, FIELDS[0xFF]


def levels(tree_size: int) -> int:
    """How many hashes an inclusion path needs at most: ⌈log₂ n⌉ (RFC 9162 §2.1.3)."""
    return math.ceil(math.log2(tree_size)) if tree_size > 1 else 0


GLOSSARY = [
    ("x, x̃, x̂", "the vector; x̃ = round(x · 2²⁴) as whole numbers (Q24, §4.2); x̂ = x̃ / 2²⁴"),
    ("S, n", "a group's exact integer sum of its members' x̃, and their count (§5.2)"),
    ("μ", "a group's centre: fixed, for routing and search (§6, §7.5)"),
    ("τ, d_M", "the drift threshold and the Mahalanobis distance compared with it (§7.2)"),
    ("Frozen group", "one of the 128 groups fitted once, offline, by k-means on SciQ (§6)"),
    ("Bucket", "Studio's name for the holding area: records that fit no group yet (§7.4)"),
    ("Flush", "the bucket reaching 200: those records become one spawned group (§7.4)"),
    ("Spawned group", "a group made by a flush: a batch, not a cluster (§7.4–7.5)"),
    ("r_t, C_t", "a record's secret blinding number and its public commitment (§9.3–9.4)"),
    ("C_S", "a group's Pedersen commitment: S hidden, but every change provable (§9.3)"),
    ("Merkle tree", "the log's hash tree: one root fixes every leaf below it (§10)"),
    ("WAL", "the write-ahead log: changes written before they count (§12.3)"),
    ("Receipt", "a deletion certificate: what the deletion did, signed (§11)"),
]
