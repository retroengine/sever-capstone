"""ristretto255 group and Ed25519 checks for the verifier, via the system libsodium (spec §9.1).

Written separately from the demo engine on purpose (CLAUDE.md §7: the verifier shares no code with
the engine). No primitive is implemented here except expand_message_xmd (RFC 9380 §5.3.1), which is
a hashing construction, not a group operation.
"""

import ctypes
import ctypes.util
import hashlib
from functools import cache

ORDER = 2**252 + 27742317777372353535851937790883648493  # ℓ, spec §2.1
IDENTITY = bytes(32)  # spec §0.2: the identity is 32 zero bytes
DST_GEN = b"PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS"  # spec §2.3, 41 bytes


class _Sodium:
    def __init__(self) -> None:
        path = ctypes.util.find_library("sodium")
        if path is None:
            raise RuntimeError("libsodium not found (Debian/Ubuntu: apt install libsodium23)")
        self.lib = ctypes.CDLL(path)
        if self.lib.sodium_init() < 0:
            raise RuntimeError("sodium_init failed")
        buf, ull = ctypes.c_char_p, ctypes.c_ulonglong
        for name, args in {
            "crypto_core_ristretto255_is_valid_point": [buf],
            "crypto_core_ristretto255_add": [buf, buf, buf],
            "crypto_core_ristretto255_from_hash": [buf, buf],
            "crypto_scalarmult_ristretto255": [buf, buf, buf],
            "crypto_sign_verify_detached": [buf, buf, ull, buf],
        }.items():
            fn = getattr(self.lib, name)
            fn.argtypes = args
            fn.restype = ctypes.c_int


_SODIUM = _Sodium()


def is_point(p: bytes) -> bool:
    """§9.9: a canonical ristretto255 encoding (RFC 9496 §4.3.1). The identity is a valid point."""
    return len(p) == 32 and _SODIUM.lib.crypto_core_ristretto255_is_valid_point(p) == 1


def add(p: bytes, q: bytes) -> bytes:
    out = ctypes.create_string_buffer(32)
    if _SODIUM.lib.crypto_core_ristretto255_add(out, p, q) != 0:
        raise ValueError("not a valid point")
    return out.raw


def times(k: int, p: bytes) -> bytes:
    """k·P. A zero scalar gives the identity (libsodium itself refuses 0·P)."""
    k %= ORDER
    if k == 0 or p == IDENTITY:
        return IDENTITY
    out = ctypes.create_string_buffer(32)
    if _SODIUM.lib.crypto_scalarmult_ristretto255(out, k.to_bytes(32, "little"), p) != 0:
        raise ValueError("scalar multiplication failed")
    return out.raw


def linear_combination(terms: list[tuple[int, bytes]]) -> bytes:
    """Σ k_j·P_j, term by term (variable time is fine: the verifier's inputs are public)."""
    total = IDENTITY
    for k, p in terms:
        total = add(total, times(k, p))
    return total


def expand_xmd_sha512(msg: bytes, dst: bytes, length: int) -> bytes:
    """RFC 9380 §5.3.1 expand_message_xmd with SHA-512 (b_in_bytes 64, s_in_bytes 128)."""
    blocks = -(-length // 64)
    if blocks > 255 or length > 65535 or len(dst) > 255:
        raise ValueError("expand_message_xmd: input too long")
    dst_prime = dst + bytes([len(dst)])
    b0 = hashlib.sha512(bytes(128) + msg + length.to_bytes(2, "big") + b"\x00" + dst_prime).digest()
    out = [hashlib.sha512(b0 + b"\x01" + dst_prime).digest()]
    for i in range(2, blocks + 1):
        mixed = bytes(a ^ b for a, b in zip(b0, out[-1], strict=True))
        out.append(hashlib.sha512(mixed + bytes([i]) + dst_prime).digest())
    return b"".join(out)[:length]


def from_uniform(b: bytes) -> bytes:
    """RFC 9496 §4.3.4 element derivation from 64 uniform bytes."""
    if len(b) != 64:
        raise ValueError("need 64 bytes")
    out = ctypes.create_string_buffer(32)
    _SODIUM.lib.crypto_core_ristretto255_from_hash(out, b)
    return out.raw


@cache
def generator_table(d: int) -> tuple[bytes, tuple[bytes, ...]]:
    """§9.2: H from msg b"H"; G_i from msg b"G" || u32be(i); one expand call each, DST_GEN."""
    h = from_uniform(expand_xmd_sha512(b"H", DST_GEN, 64))
    gs = tuple(
        from_uniform(expand_xmd_sha512(b"G" + i.to_bytes(4, "big"), DST_GEN, 64)) for i in range(d)
    )
    return h, gs


def to_scalar(v: int) -> int:
    """§4.5: v mod ℓ for v >= 0, ℓ - (|v| mod ℓ) for v < 0."""
    return v % ORDER if v >= 0 else ORDER - (-v % ORDER)


def commitment(values: list[int], blind: int) -> bytes:
    """§9.3: blind·H + Σ scalar(values_i)·G_i."""
    h, gs = generator_table(len(values))
    return linear_combination(
        [(blind, h)] + [(to_scalar(v), g) for v, g in zip(values, gs, strict=True)]
    )


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 verification (libsodium rejects non-canonical and small-order inputs)."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    rc: int = _SODIUM.lib.crypto_sign_verify_detached(signature, message, len(message), public_key)
    return rc == 0
