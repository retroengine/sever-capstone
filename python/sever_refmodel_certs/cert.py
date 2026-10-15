"""Deletion certificates (§11), from the spec text: the TLV encoding of §11.1, the
``insert_inclusion`` field of §11.2, the signed messages of §9.8, and the eight-step verification
algorithm of §11.3. This is the oracle the engine's ``sever-cert`` and the verifier are checked
against; it shares no code with either.

:func:`verify` raises :class:`VerifyError` naming the §11.3 step that failed (the attack register,
``spec/registers_p3.yaml``, lists the steps allowed to reject each attack).
"""

import hashlib
from dataclasses import dataclass, field
from typing import Final

from sever_refmodel_certs import ed25519, merkle, posk
from sever_refmodel_certs.ristretto import IDENTITY, DecodeError, decode, decode_scalar, encode

# §2.3 domain strings.
DST_INSERT: Final = b"SEVERDB-INSERT-V1"
DST_STH: Final = b"SEVERDB-STH-V1"
DST_COSIGN: Final = b"SEVERDB-COSIGN-V1"
DST_CERT: Final = b"SEVERDB-CERT-V1"

TAGS: Final = range(1, 14)
TRAILER: Final = 0xFF
INSERT_LEAF_LEN: Final = 209
CHECKPOINT_LEN: Final = 116
COSIGNATURE_LEN: Final = 69
THRESHOLD: Final = 4  # §10.4: four of five
#: Tags whose value has one fixed length (§11.1); tags 2, 3 and 4 may also be empty.
FIXED: Final = {1: 32, 5: 64, 8: 4, 9: 64, 10: 8, 11: 1, 12: 1, 13: 16}


class VerifyError(ValueError):
    """A certificate §11.3 rejects, with the step that rejected it."""

    def __init__(self, step: int, reason: str) -> None:
        super().__init__(f"step {step}: {reason}")
        self.step = step
        self.reason = reason


# §9.8 messages.
def insert_message(collection_id: bytes, c_t: bytes) -> bytes:
    return DST_INSERT + collection_id + c_t


def checkpoint_message(tree_size: int, root: bytes, timestamp_ms: int, epoch: int) -> bytes:
    return (
        DST_STH
        + tree_size.to_bytes(8, "big")
        + root
        + timestamp_ms.to_bytes(8, "big")
        + epoch.to_bytes(4, "big")
    )


def cosign_message(checkpoint_msg: bytes) -> bytes:
    return DST_COSIGN + checkpoint_msg


def insert_leaf(
    collection_id: bytes, scrambled_id: bytes, c_t: bytes, user_public_key: bytes, user_sig: bytes
) -> bytes:
    """§10.2: ``0x01 ‖ collection_id (16) ‖ scrambled_id (64) ‖ C_t (32) ‖ user_public_key (32) ‖
    user_signature (64)``."""
    out = b"\x01" + collection_id + scrambled_id + c_t + user_public_key + user_sig
    if len(out) != INSERT_LEAF_LEN:
        raise ValueError("insert leaf: wrong field size")
    return out


@dataclass(frozen=True)
class Checkpoint:
    """§10.3 ``(tree_size, root, timestamp_ms, epoch, operator_signature)``."""

    tree_size: int
    root: bytes
    timestamp_ms: int
    epoch: int
    signature: bytes

    def message(self) -> bytes:
        return checkpoint_message(self.tree_size, self.root, self.timestamp_ms, self.epoch)

    def to_bytes(self) -> bytes:
        """§11.2: ``u64be tree_size ‖ root ‖ u64be timestamp_ms ‖ u32be epoch ‖ signature``."""
        return (
            self.tree_size.to_bytes(8, "big")
            + self.root
            + self.timestamp_ms.to_bytes(8, "big")
            + self.epoch.to_bytes(4, "big")
            + self.signature
        )

    @staticmethod
    def parse(b: bytes) -> "Checkpoint":
        if len(b) != CHECKPOINT_LEN:
            raise VerifyError(1, "checkpoint length")
        return Checkpoint(
            int.from_bytes(b[:8], "big"),
            b[8:40],
            int.from_bytes(b[40:48], "big"),
            int.from_bytes(b[48:52], "big"),
            b[52:116],
        )


@dataclass(frozen=True)
class Inclusion:
    """§11.2 ``insert_inclusion`` (version 1)."""

    leaf: bytes
    leaf_index: int
    checkpoint: Checkpoint
    path: list[bytes]

    def to_bytes(self) -> bytes:
        return (
            b"\x01"
            + self.leaf
            + self.leaf_index.to_bytes(8, "big")
            + self.checkpoint.to_bytes()
            + len(self.path).to_bytes(1, "big")
            + b"".join(self.path)
        )

    @staticmethod
    def parse(b: bytes) -> "Inclusion":
        fixed = 1 + INSERT_LEAF_LEN + 8 + CHECKPOINT_LEN + 1
        if len(b) < fixed:
            raise VerifyError(1, "tag 6 length")
        if b[0] != 1:
            raise VerifyError(1, "insert_inclusion version")
        n = b[fixed - 1]
        if len(b) != fixed + 32 * n:
            raise VerifyError(1, "tag 6 length")
        cp = Checkpoint.parse(b[1 + INSERT_LEAF_LEN + 8 : fixed - 1])
        path = [b[fixed + 32 * i : fixed + 32 * (i + 1)] for i in range(n)]
        return Inclusion(
            b[1 : 1 + INSERT_LEAF_LEN],
            int.from_bytes(b[1 + INSERT_LEAF_LEN : 1 + INSERT_LEAF_LEN + 8], "big"),
            cp,
            path,
        )


@dataclass(frozen=True)
class Cosig:
    """§11.1 tag 7 entry: ``u8 witness_index ‖ u32be witness_epoch ‖ signature``."""

    index: int
    epoch: int
    signature: bytes

    def to_bytes(self) -> bytes:
        return bytes([self.index]) + self.epoch.to_bytes(4, "big") + self.signature


def cosignatures_value(cosigs: list[Cosig]) -> bytes:
    return bytes([len(cosigs)]) + b"".join(c.to_bytes() for c in cosigs)


def tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + len(value).to_bytes(4, "big") + value


def body(values: dict[int, bytes]) -> bytes:
    """§11.1: tags 1 … 13 in ascending order, each exactly once."""
    return b"".join(tlv(t, values[t]) for t in TAGS)


def sign_certificate(values: dict[int, bytes], operator_secret: bytes) -> bytes:
    """The body, then ``0xFF ‖ u32be 64 ‖`` the operator's signature over ``DST_CERT ‖ body``."""
    b = body(values)
    return b + tlv(TRAILER, ed25519.sign(operator_secret, DST_CERT + b))


@dataclass
class Parsed:
    """A strictly parsed certificate: every tag's raw value, the body and the trailer."""

    values: dict[int, bytes]
    body: bytes
    signature: bytes
    inclusion: Inclusion = field(init=False)
    cosigs: list[Cosig] = field(init=False)

    def __post_init__(self) -> None:
        self.inclusion = Inclusion.parse(self.values[6])
        v = self.values[7]
        if not v or len(v) != 1 + COSIGNATURE_LEN * v[0]:
            raise VerifyError(1, "tag 7 length")
        self.cosigs = [
            Cosig(e[0], int.from_bytes(e[1:5], "big"), e[5:])
            for e in (
                v[1 + COSIGNATURE_LEN * i : 1 + COSIGNATURE_LEN * (i + 1)] for i in range(v[0])
            )
        ]

    def u(self, tag: int) -> int:
        return int.from_bytes(self.values[tag], "big")


def parse(cert: bytes, d: int) -> Parsed:
    """Step 1's strict parse (§11.1): every tag once, in order; fixed lengths; tags 11 and 12 in
    {0, 1} (DB-76); tag 6 version 1; the trailer; no trailing bytes."""
    values: dict[int, bytes] = {}
    pos = 0
    for expected in [*TAGS, TRAILER]:
        if pos + 5 > len(cert):
            raise VerifyError(1, "truncated")
        tag, n = cert[pos], int.from_bytes(cert[pos + 1 : pos + 5], "big")
        if tag != expected:
            raise VerifyError(1, f"tag {tag} where tag {expected} belongs")
        if pos + 5 + n > len(cert):
            raise VerifyError(1, "truncated")
        if expected == TRAILER:
            if n != 64:
                raise VerifyError(1, "trailer length")
            body_end = pos
        values[tag] = cert[pos + 5 : pos + 5 + n]
        pos += 5 + n
    if pos != len(cert):
        raise VerifyError(1, "trailing bytes")
    for t, n in FIXED.items():
        if len(values[t]) != n:
            raise VerifyError(1, f"tag {t} length")
    for t in (2, 3):
        if len(values[t]) not in (0, 32):
            raise VerifyError(1, f"tag {t} length")
    if len(values[4]) not in (0, 64 + 32 * d):
        raise VerifyError(1, "tag 4 length")
    for t in (11, 12):
        if values[t][0] > 1:
            raise VerifyError(1, f"tag {t} value")
    return Parsed({t: values[t] for t in TAGS}, cert[:body_end], values[TRAILER])


@dataclass(frozen=True)
class Anchors:
    """§11.3 trust anchors: operator keys by epoch, witness keys by ``(index, epoch)``, and the
    generator count ``d`` (the generator golden file fixes the generators)."""

    operators: dict[int, bytes]
    witnesses: dict[tuple[int, int], bytes]
    d: int


def verify(cert: bytes, anchors: Anchors) -> None:
    """§11.3 steps 1–8; returns only if every step passes."""
    # 1. Parse strictly; decode every point and scalar canonically; C_t is not the identity.
    p = parse(cert, anchors.d)
    try:
        c_t = decode(p.values[1])
        pre = decode(p.values[2]) if p.values[2] else None
        post = decode(p.values[3]) if p.values[3] else None
        if p.values[4]:
            decode(p.values[4][:32])
            for i in range(1 + anchors.d):
                decode_scalar(p.values[4][32 + 32 * i : 64 + 32 * i])
    except DecodeError as e:
        raise VerifyError(1, f"non-canonical encoding ({e})") from None
    if c_t.equals(IDENTITY):
        raise VerifyError(1, "C_t is the identity")
    # 2. Operator signature for tag 8's epoch.
    key = anchors.operators.get(p.u(8))
    if key is None:
        raise VerifyError(2, "unknown operator epoch")
    if not ed25519.verify(key, DST_CERT + p.body, p.signature):
        raise VerifyError(2, "operator signature")
    # 3. Insert inclusion.
    inc = p.inclusion
    leaf = inc.leaf
    if leaf[0] != 0x01:
        raise VerifyError(3, "leaf type")
    coll, sid, leaf_ct, upk, usig = leaf[1:17], leaf[17:81], leaf[81:113], leaf[113:145], leaf[145:]
    if (coll, sid, leaf_ct, usig) != (p.values[13], p.values[9], p.values[1], p.values[5]):
        raise VerifyError(3, "leaf fields differ from tags 13, 9, 1, 5")
    if not ed25519.verify(upk, insert_message(coll, leaf_ct), usig):
        raise VerifyError(3, "user signature")
    cp = inc.checkpoint
    if not merkle.verify_inclusion(
        merkle.leaf_hash(leaf), inc.leaf_index, cp.tree_size, inc.path, cp.root
    ):
        raise VerifyError(3, "inclusion path")
    cp_key = anchors.operators.get(cp.epoch)
    if cp_key is None or not ed25519.verify(cp_key, cp.message(), cp.signature):
        raise VerifyError(3, "checkpoint signature")
    # 4. At least four cosignatures from distinct witnesses, each valid for its epoch.
    msg = cosign_message(cp.message())
    good = {
        c.index
        for c in p.cosigs
        if (k := anchors.witnesses.get((c.index, c.epoch))) is not None
        and ed25519.verify(k, msg, c.signature)
    }
    if len(good) < THRESHOLD:
        raise VerifyError(4, f"{len(good)} distinct valid cosignatures")
    # 5. Ordering.
    lsn = p.u(10)
    if lsn <= inc.leaf_index:
        raise VerifyError(5, "database_lsn not after the insert leaf")
    kind, emptied = p.u(12), p.u(11)
    if kind == 0:
        # 6. From a group.
        if pre is None or post is None or not p.values[4]:
            raise VerifyError(6, "a group deletion needs tags 2, 3 and 4")
        if not (post + c_t).equals(pre):
            raise VerifyError(6, "C_S_post + C_t != C_S_pre")
        ctx = posk.ctx_bytes(p.values[2], p.values[1], p.values[9], lsn, p.values[13])
        if not posk.verify(p.values[3], ctx, p.values[4], anchors.d):
            raise VerifyError(6, "proof of knowledge")
        if emptied != int(post.equals(IDENTITY)):
            raise VerifyError(6, "group_emptied disagrees with C_S_post")
    # 7. From the holding area.
    elif p.values[2] or p.values[3] or p.values[4] or emptied != 0:
        raise VerifyError(7, "a holding-area certificate carries arithmetic fields")
    # 8. Every step passed.


def secret(label: str) -> bytes:
    """A fixed test secret key, ``SHA-512(label)[:32]`` (golden vectors only; never a database's
    key)."""
    return hashlib.sha512(label.encode("ascii")).digest()[:32]


def identity_bytes() -> bytes:
    return encode(IDENTITY)
