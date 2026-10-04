"""Offline verification of a SEVER-DB deletion certificate (spec §11.1, §11.3), Part 3 preview.

Needs only the certificate bytes and the trust anchors (operator public key per epoch, d). Shares
no code with the engine. Preview: the transparency log is not built, so tags 5-7 (user insert
signature, log inclusion, witness cosignatures) are empty, and §11.3 steps 3-5 are reported as
NOT CHECKED, never as passed.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any

from sever_verify.ristretto import (
    IDENTITY,
    ORDER,
    add,
    ed25519_verify,
    generator_table,
    is_point,
    linear_combination,
    times,
)

DST_CERT = b"SEVERDB-CERT-V1"
DST_POSK = b"SEVERDB_POSK_V1"
NAMES = {
    1: "commitment_to_deleted_vector",
    2: "group_commitment_before",
    3: "group_commitment_after",
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
}
PASS, FAIL, NOT_CHECKED = "PASS", "FAIL", "NOT CHECKED"


class ParseError(ValueError):
    pass


@dataclass
class Report:
    steps: list[tuple[str, str, str]] = field(default_factory=list)  # (step, status, detail)

    def add(self, step: str, ok: bool | None, detail: str = "") -> None:
        self.steps.append((step, NOT_CHECKED if ok is None else PASS if ok else FAIL, detail))

    @property
    def accepted(self) -> bool:
        """§11.3 step 8: accept only if no checked step failed (and at least one ran)."""
        return bool(self.steps) and all(s != FAIL for _, s, _ in self.steps)


def parse(data: bytes, d: int) -> tuple[dict[int, bytes], bytes, bytes]:
    """§11.1 strict parse. Returns (fields, signed_bytes, signature).

    Rejects missing, repeated or out-of-order tags, wrong lengths for fixed-size fields, a bad
    trailer, and trailing bytes.
    """
    fixed = {
        1: {32},
        2: {0, 32},
        3: {0, 32},
        4: {0, 64 + 32 * d},
        5: {0, 64},
        8: {4},
        9: {64},
        10: {8},
        11: {1},
        12: {1},
        13: {16},
    }
    fields: dict[int, bytes] = {}
    pos = 0
    for tag in range(1, 14):
        if pos + 5 > len(data):
            raise ParseError(f"truncated before tag {tag}")
        if data[pos] != tag:
            raise ParseError(f"expected tag {tag}, found {data[pos]}")
        length = int.from_bytes(data[pos + 1 : pos + 5], "big")
        value = data[pos + 5 : pos + 5 + length]
        if len(value) != length:
            raise ParseError(f"tag {tag} truncated")
        if tag in fixed and length not in fixed[tag]:
            raise ParseError(f"tag {tag} has length {length}")
        fields[tag] = value
        pos += 5 + length
    signed = data[:pos]
    if data[pos : pos + 5] != b"\xff" + (64).to_bytes(4, "big"):
        raise ParseError("missing signature trailer")
    signature = data[pos + 5 : pos + 69]
    if len(signature) != 64:
        raise ParseError("signature truncated")
    if pos + 69 != len(data):
        raise ParseError("trailing bytes")
    return fields, signed, signature


def _scalar(b: bytes) -> int | None:
    v = int.from_bytes(b, "little")
    return v if v < ORDER else None  # §9.9: canonical scalars only


def verify_proof(proof: bytes, c_s_post: bytes, ctx: bytes, d: int) -> bool:
    """§9.5 verifier: z_r·H + Σ z_i·G_i == A + c·C_S_post."""
    a = proof[:32]
    zs = [_scalar(proof[32 + 32 * i : 64 + 32 * i]) for i in range(d + 1)]
    if not is_point(a) or any(z is None for z in zs):
        return False
    c = int.from_bytes(hashlib.sha512(DST_POSK + c_s_post + a + ctx).digest(), "little") % ORDER
    h, gs = generator_table(d)
    left = linear_combination([(z, p) for z, p in zip(zs, (h, *gs), strict=True) if z is not None])
    return left == add(a, times(c, c_s_post))


def verify(data: bytes, anchors: dict[str, Any]) -> Report:
    """§11.3, steps 1 to 8, with the preview's NOT CHECKED steps named."""
    rep = Report()
    d = int(anchors["d"])
    try:
        f, signed, signature = parse(data, d)
    except ParseError as exc:
        rep.add("1 parse (§11.1)", False, str(exc))
        return rep
    c_t, c_pre, c_post = f[1], f[2], f[3]
    points_ok = all(is_point(p) for p in (c_t, c_pre, c_post) if p)
    rep.add(
        "1 parse, canonical points, C_t not identity",
        points_ok and c_t != IDENTITY,
        "" if points_ok else "non-canonical point",
    )
    if not points_ok:
        return rep

    epoch = int.from_bytes(f[8], "big")
    key_hex = anchors["operator_public_keys"].get(str(epoch))
    rep.add(
        "2 operator signature (DST_CERT)",
        key_hex is not None
        and ed25519_verify(bytes.fromhex(key_hex), DST_CERT + signed, signature),
        f"epoch {epoch}" if key_hex else f"no anchor key for epoch {epoch}",
    )

    preview = not f[5] and not f[6] and not f[7]
    why = "transparency log not built (preview)"
    rep.add("3 insert inclusion in a signed log", None if preview else False, why)
    rep.add("4 witness cosignatures (>= 4 of 5)", None if preview else False, why)
    rep.add("5 ordering: lsn > insert leaf index", None if preview else False, why)

    kind, emptied = f[12][0], f[11][0]
    if kind == 0:
        rep.add("6a C_S_post + C_t = C_S_pre", add(c_post, c_t) == c_pre)
        ctx = c_pre + c_t + f[9] + f[10] + f[13]
        rep.add("6b proof of knowledge of C_S_post (§9.5)", verify_proof(f[4], c_post, ctx, d))
        rep.add("6c group emptied <=> C_S_post is identity", (emptied == 1) == (c_post == IDENTITY))
    else:
        rep.add(
            "7 holding-area deletion: tags 2-4 empty, tag 11 = 0",
            not c_pre and not c_post and not f[4] and emptied == 0,
        )
    return rep
