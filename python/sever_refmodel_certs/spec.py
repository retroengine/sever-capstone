"""The spec's crypto definitions on top of the RFC primitives: domain strings (§2.3), ``scalar(v)``
(§4.5), the generators (§9.2) and their digest (§9.6)."""

import hashlib
from functools import cache
from typing import Final

from sever_refmodel_certs.ristretto import L, Point, encode, from_uniform_bytes
from sever_refmodel_certs.xmd import expand_message_xmd_sha512

DST_GEN: Final = b"PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS"  # §2.3
D_V1: Final = 384  # §2.2


def scalar(v: int) -> int:
    """§4.5: ``v mod ℓ`` if ``v ≥ 0``, ``ℓ − (|v| mod ℓ)`` if ``v < 0``, for ``v`` in i64."""
    if not -(2**63) <= v < 2**63:
        raise ValueError("scalar(v) is defined for i64")
    return v % L if v >= 0 else L - (abs(v) % L)


def hash_to_group(msg: bytes) -> Point:
    """§9.2: ``ristretto255_from_uniform_bytes(expand_message_xmd_sha512(msg, DST_GEN, 64))``."""
    return from_uniform_bytes(expand_message_xmd_sha512(msg, DST_GEN, 64))


def generator_h() -> Point:
    """§9.2: ``H`` from ``msg = b"H"``."""
    return hash_to_group(b"H")


def generator_g(i: int) -> Point:
    """§9.2: ``G_i`` from ``msg = b"G" ‖ u32be(i)``."""
    return hash_to_group(b"G" + i.to_bytes(4, "big"))


@cache
def generators(d: int = D_V1) -> tuple[Point, tuple[Point, ...]]:
    """``(H, (G_0 … G_{d−1}))``, one ``expand_message`` call each (§9.2)."""
    return generator_h(), tuple(generator_g(i) for i in range(d))


def gdigest(d: int = D_V1) -> bytes:
    """§9.6: ``SHA-512(H ‖ G_0 ‖ … ‖ G_{d−1})`` over the 32-byte encodings."""
    h, gs = generators(d)
    return hashlib.sha512(encode(h) + b"".join(encode(g) for g in gs)).digest()


def commit(values: list[int], blind: int, d: int | None = None) -> Point:
    """§9.3: ``blind·H + Σ_i scalar(values_i)·G_i``, the record commitment ``C_t`` (values = x̃,
    i32) or the group commitment ``C_S`` (values = S, i64)."""
    n = len(values) if d is None else d
    if len(values) != n:
        raise ValueError("commit: wrong number of components")
    h, gs = generators(n)
    acc = h * (blind % L)
    for v, g in zip(values, gs, strict=True):
        acc = acc + g * scalar(v)
    return acc
