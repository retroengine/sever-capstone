"""Proof of knowledge of a group's state (spec §9.5), Part 3 preview.

After a deletion the operator proves it knows (r_post, s_0 … s_{d-1}) with
    C_S_post = r_post·H + Σ s_i·G_i,   s_i = scalar(S_post_i).
A multi-secret Schnorr proof (Okamoto), made non-interactive by Fiat-Shamir. Without it, an operator
could publish C_S_pre - C_t without knowing (or having) any real group state.

Deviation, stated: §9.6 derives nonces from a Merlin transcript (witness + statement + OS entropy).
Merlin has no Python implementation here, so nonces are 64 OS bytes each, reduced wide. They are
still never seeded and never reused.
"""

import hashlib
import struct
from collections.abc import Sequence

from sever_demo.crypto import L, generators, msm, random_scalars, scalar, scalar_bytes, wide_reduce

DST_POSK = b"SEVERDB_POSK_V1"  # §2.3, 15 bytes
CTX_LEN = 152


def context(
    c_s_pre: bytes, c_t: bytes, scrambled_id: bytes, database_lsn: int, collection_id: bytes
) -> bytes:
    """§9.5 deletion context, 152 bytes:
    C_S_pre (32) ‖ C_t (32) ‖ scrambled_id (64) ‖ u64be lsn ‖ collection_id (16)."""
    if (len(c_s_pre), len(c_t), len(scrambled_id), len(collection_id)) != (32, 32, 64, 16):
        raise ValueError("context field has the wrong length")
    ctx = c_s_pre + c_t + scrambled_id + struct.pack(">Q", database_lsn) + collection_id
    assert len(ctx) == CTX_LEN
    return ctx


def challenge(c_s_post: bytes, a: bytes, ctx: bytes) -> int:
    """§9.5: c = from_bytes_mod_order_wide(SHA-512(DST_POSK ‖ C_S_post ‖ A ‖ ctx)).

    The preimage is 15 + 32 + 32 + 152 = 231 bytes."""
    preimage = DST_POSK + c_s_post + a + ctx
    assert len(preimage) == 15 + 32 + 32 + CTX_LEN
    return wide_reduce(hashlib.sha512(preimage).digest())


def prove(r_post: int, s_post: Sequence[int], c_s_post: bytes, ctx: bytes) -> bytes:
    """Returns A ‖ z_r ‖ z_0 … z_{d-1} (32 + 32 + 32·d bytes; 12,352 at d = 384)."""
    d = len(s_post)
    h, g = generators(d)
    secrets = [r_post % L] + [scalar(int(v)) for v in s_post]
    nonces = random_scalars(d + 1)  # k_r, k_0 … k_{d-1}, fresh from the OS
    a = msm(nonces, (h, *g))
    c = challenge(c_s_post, a, ctx)
    z = [(k + c * x) % L for k, x in zip(nonces, secrets, strict=True)]
    return a + b"".join(scalar_bytes(v) for v in z)
