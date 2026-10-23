"""The beginner diagrams, as data: each step's title and the real numbers for the record shown.

Every number comes from the engine (its receipts, events and sizes), its routing code
(``Studio.why``, DB-108) or the dataset, never from arithmetic of Studio's own. The window draws
these with ``widgets.Flow``; the tests read them directly.
"""

import math
from typing import TYPE_CHECKING

from .backend import HOLDING, cert_field

if TYPE_CHECKING:
    from .actions import Deleted, Studio

Steps = list[tuple[str, str]]

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


def insert_flow(studio: "Studio", rid: str) -> Steps:
    """How a stored record got to its group: encode, quantise, nearest frozen centre, drift test,
    destination (§3.3, §4.2, §7.1–7.3)."""
    b = studio.backend
    rec = b.index.records[rid]
    why = studio.why(rid)
    text = " ".join(b.text_of(rid).split())
    x = b.vector_of(rid)
    steps: Steps = [
        ("The passage", (text[:70] + "…") if len(text) > 70 else text),
        (
            "Encoded: x",
            f"{len(x)} numbers of length 1: [{x[0]:.5f}, {x[1]:.5f}, …] (the pinned encoder, §3.3)",
        ),
    ]
    if why is None:
        return steps
    xt = why["x_tilde"]
    (j, d), *rest = why["nearest"]
    near = f"; next frozen-{rest[0][0]:04d}: {rest[0][1]:.4f}" if rest else ""
    inside = why["in_distribution"]
    steps += [
        ("Quantised: x̃ = round(x · 2²⁴)", f"[{xt[0]:,}, {xt[1]:,}, …] whole numbers (§4.2)"),
        ("Nearest frozen centre (§7.1)", f"frozen-{j:04d}: D = Σ(x̂ − μ)² = {d:.4f}{near}"),
        (
            "Drift test (§7.2)",
            f"d_M = {why['d_m']:.3f} {'≤' if inside else '>'} τ = {why['tau']:.3f}: "
            + ("in distribution" if inside else "out of distribution"),
        ),
        (
            "Where the engine put it (§7.3)",
            rec.group
            + (
                ""
                if inside
                else " (out of distribution: the nearest spawned group with room, else the bucket)"
            ),
        ),
    ]
    return steps


def delete_flow(studio: "Studio", d: "Deleted") -> Steps:
    """What one deletion did inside the engine and what it published (§5.3, §10, §11, §13.3)."""
    b = studio.backend
    if not d.lsns:
        return []
    lsn = d.lsns[0]
    cert = (b.receipts / f"{lsn}.cert").read_bytes()
    pre, post = cert_field(cert, 2), cert_field(cert, 3)
    group = next(iter(d.groups_before), HOLDING)
    n0, n1 = d.groups_before.get(group, 0), d.groups_after.get(group, 0)
    if group == HOLDING or not post:
        first = ("Removed from the bucket", "it was in no group: no sum to change (§7.4)")
        commit = ("Commitment", "none: a bucket deletion's receipt has no C_S (§11.3 step 7)")
    else:
        first = (f"Removed from {group}", f"S − x̃ and n {n0} → {n1}, exactly (§5.3)")
        commit = (
            "Its commitment",
            f"C_S {pre.hex()[:12]}… → {post.hex()[:12]}…: moved by exactly C_t (§9.3)",
        )
    return [
        first,
        commit,
        (f"Receipt #{lsn}", "signed by the operator; checkable offline by anyone (§11)"),
        ("Public log", f"leaf #{lsn} appended; witnesses cosign the checkpoint (§10)"),
        (
            "Keys",
            "the group's and the record's bucket key replaced, the old ones overwritten: the "
            "deleted bytes can no longer be decrypted (§13.3–13.4)",
        ),
    ]


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


#: §12.3, §15.1: an insert's way to durable (kills before COMMIT store nothing, after it store all).
COMMIT = [
    ("Request", "the insert arrives, checked and planned in memory (§15.1)"),
    ("WAL records", "written to the write-ahead log and fsynced (§12.3)"),
    ("COMMIT", "the commit record, fsynced: the commit point. Before it nothing happened"),
    ("Applied", "the change goes into memory; the engine may now answer"),
    ("Acknowledged", "the answer reaches you. Killed between COMMIT and here: stored, unanswered"),
]

#: §13.1–13.4: the key hierarchy and what a deletion destroys.
KEYS = [
    ("Group key GK_g", "one per group; wraps the group's bucket keys and seals S and r_agg"),
    ("Bucket key BK_g,b", "one per bucket (64 per group); wraps its records' keys"),
    ("Record key RK_t", "one per record; encrypts its x̃, r_t and text (§13.2)"),
    (
        "On delete",
        "new GK and BK are written, the old ones overwritten in the key file: the deleted "
        "record's RK cannot be unwrapped any more (§13.3–13.4)",
    ),
]

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
