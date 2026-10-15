"""Proof of knowledge of the group state (§9.5), from the spec text: the deletion context, the
Fiat–Shamir challenge, the prover with given nonces (the hedged derivation of §9.6 is not modelled:
it is not consensus-critical) and the verifier."""

import hashlib
from typing import Final

from sever_refmodel_certs import spec
from sever_refmodel_certs.ristretto import (
    DecodeError,
    L,
    Point,
    decode,
    decode_scalar,
    encode,
    encode_scalar,
)

DST_POSK: Final = b"SEVERDB_POSK_V1"  # §2.3


def ctx_bytes(
    c_s_pre: bytes, c_t: bytes, scrambled_id: bytes, database_lsn: int, collection_id: bytes
) -> bytes:
    """The 152-byte context ``C_S_pre (32) ‖ C_t (32) ‖ scrambled_id (64) ‖ u64be(database_lsn) ‖
    collection_id (16)``."""
    sizes = (len(c_s_pre), len(c_t), len(scrambled_id), len(collection_id))
    if sizes != (32, 32, 64, 16):
        raise ValueError("ctx: wrong field size")
    out = c_s_pre + c_t + scrambled_id + database_lsn.to_bytes(8, "big") + collection_id
    assert len(out) == 152
    return out


def challenge(c_s_post: bytes, a: bytes, ctx: bytes) -> int:
    """``c = from_bytes_mod_order_wide(SHA-512(DST_POSK ‖ C_S_post ‖ A ‖ ctx))``, a 231-byte
    preimage."""
    pre = DST_POSK + c_s_post + a + ctx
    if len(pre) != 231:
        raise ValueError("challenge: preimage is not 231 bytes")
    return int.from_bytes(hashlib.sha512(pre).digest(), "little") % L


def prove(s_post: list[int], r_post: int, ctx: bytes, k_r: int, k: list[int]) -> bytes:
    """The §9.5 prover with the nonces given; returns ``A ‖ z_r ‖ z_0 ‖ … ‖ z_{d−1}``."""
    d = len(s_post)
    if len(k) != d:
        raise ValueError("prove: one nonce per component")
    h, gs = spec.generators(d)
    c_s_post = encode(spec.commit(s_post, r_post))
    a_pt = h * k_r
    for ki, g in zip(k, gs, strict=True):
        a_pt = a_pt + g * ki
    a = encode(a_pt)
    c = challenge(c_s_post, a, ctx)
    z_r = (k_r + c * r_post) % L
    z = [(ki + c * spec.scalar(si)) % L for ki, si in zip(k, s_post, strict=True)]
    return a + encode_scalar(z_r) + b"".join(encode_scalar(zi) for zi in z)


def verify(c_s_post: bytes, ctx: bytes, proof: bytes, d: int) -> bool:
    """The §9.5 verifier: canonical decoding, then ``z_r·H + Σ z_i·G_i = A + c·C_S_post``."""
    if len(proof) != 32 + 32 + 32 * d:
        return False
    try:
        a_pt = decode(proof[:32])
        z_r = decode_scalar(proof[32:64])
        z = [decode_scalar(proof[64 + 32 * i : 96 + 32 * i]) for i in range(d)]
        c_pt: Point = decode(c_s_post)
    except DecodeError:
        return False
    h, gs = spec.generators(d)
    c = challenge(c_s_post, proof[:32], ctx)
    lhs = h * z_r
    for zi, g in zip(z, gs, strict=True):
        lhs = lhs + g * zi
    return lhs.equals(a_pt + c_pt * c)
