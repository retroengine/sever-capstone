"""Pedersen commitments on ristretto255 and Ed25519 signing (spec §9), Part 3 preview.

Group operations and signatures come from the system libsodium 1.0.18 through ctypes; no primitive
is implemented here (§9.1) except expand_message_xmd (RFC 9380 §5.3.1), a hashing construction.
The independent verifier (python/sever_verify) has its own, separately written, binding.

Secrets (r_t, nonces, keys) come only from the OS (§9.4, CLAUDE.md "never pass a seed into proof or
key generation"): no function here accepts a seed or an RNG.
"""

import ctypes
import ctypes.util
import hashlib
import os
from collections.abc import Iterable, Sequence
from functools import cache

L = 2**252 + 27742317777372353535851937790883648493  # ℓ, the ristretto255 group order (§2.1)
IDENTITY = bytes(32)  # §0.2: the identity is the 32-byte all-zero encoding
DST_GEN = b"PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS"  # §2.3

_path = ctypes.util.find_library("sodium")
if _path is None:
    raise ImportError("libsodium not found (Debian/Ubuntu: apt install libsodium23)")
_lib = ctypes.CDLL(_path)
if _lib.sodium_init() < 0:
    raise ImportError("sodium_init failed")
_P, _ULL = ctypes.c_char_p, ctypes.c_ulonglong
_SIGNATURES: dict[str, list[type]] = {
    "crypto_core_ristretto255_is_valid_point": [_P],
    "crypto_core_ristretto255_add": [_P, _P, _P],
    "crypto_core_ristretto255_sub": [_P, _P, _P],
    "crypto_core_ristretto255_from_hash": [_P, _P],
    "crypto_scalarmult_ristretto255": [_P, _P, _P],
    "crypto_sign_seed_keypair": [_P, _P, _P],
    "crypto_sign_detached": [_P, ctypes.c_void_p, _P, _ULL, _P],
}
for _name, _args in _SIGNATURES.items():
    getattr(_lib, _name).argtypes = _args
    getattr(_lib, _name).restype = ctypes.c_int


def scalar(v: int) -> int:
    """§4.5 integer-to-scalar mapping: v mod ℓ if v >= 0, else ℓ - (|v| mod ℓ)."""
    if v >= 0:
        return v % L
    return L - (abs(v) % L)


def scalar_bytes(k: int) -> bytes:
    """§0.2: scalars are 32 bytes, little-endian, reduced mod ℓ."""
    return (k % L).to_bytes(32, "little")


def wide_reduce(b: bytes) -> int:
    """from_bytes_mod_order_wide: 64 little-endian bytes reduced mod ℓ."""
    return int.from_bytes(b, "little") % L


def random_scalar() -> int:
    """§9.4: 64 bytes from the OS CSPRNG, reduced wide."""
    return wide_reduce(os.urandom(64))


def random_scalars(count: int) -> list[int]:
    """Many §9.4 scalars at once (one OS read)."""
    raw = os.urandom(64 * count)
    return [wide_reduce(raw[64 * i : 64 * i + 64]) for i in range(count)]


def is_valid_point(p: bytes) -> bool:
    """§9.9: canonical encoding of a group element (the identity included)."""
    return len(p) == 32 and _lib.crypto_core_ristretto255_is_valid_point(p) == 1


def point_add(p: bytes, q: bytes) -> bytes:
    out = ctypes.create_string_buffer(32)
    if _lib.crypto_core_ristretto255_add(out, p, q) != 0:
        raise ValueError("invalid point")
    return out.raw


def point_sub(p: bytes, q: bytes) -> bytes:
    out = ctypes.create_string_buffer(32)
    if _lib.crypto_core_ristretto255_sub(out, p, q) != 0:
        raise ValueError("invalid point")
    return out.raw


def mul(k: int, p: bytes) -> bytes:
    """k·P. CLAUDE.md §7: a zero scalar MUST give the identity; libsodium refuses 0·P, so the
    identity is returned here instead of calling it."""
    k %= L
    if k == 0 or p == IDENTITY:
        return IDENTITY
    out = ctypes.create_string_buffer(32)
    if _lib.crypto_scalarmult_ristretto255(out, scalar_bytes(k), p) != 0:
        raise ValueError("scalar multiplication failed")
    return out.raw


def msm(scalars: Iterable[int], points: Iterable[bytes]) -> bytes:
    """Σ k_i·P_i. Zero terms are skipped (they add the identity)."""
    acc = IDENTITY
    for k, p in zip(scalars, points, strict=True):
        if k % L:
            acc = point_add(acc, mul(k, p))
    return acc


def expand_message_xmd_sha512(msg: bytes, dst: bytes, len_in_bytes: int) -> bytes:
    """RFC 9380 §5.3.1 with H = SHA-512 (b_in_bytes = 64, s_in_bytes = 128)."""
    ell = (len_in_bytes + 63) // 64
    if ell > 255 or len_in_bytes > 65535 or len(dst) > 255:
        raise ValueError("expand_message_xmd: length out of range")
    dst_prime = dst + len(dst).to_bytes(1, "big")
    z_pad = bytes(128)
    l_i_b_str = len_in_bytes.to_bytes(2, "big")
    b_0 = hashlib.sha512(z_pad + msg + l_i_b_str + b"\x00" + dst_prime).digest()
    b_i = hashlib.sha512(b_0 + b"\x01" + dst_prime).digest()
    uniform = b_i
    for i in range(2, ell + 1):
        b_i = hashlib.sha512(
            bytes(x ^ y for x, y in zip(b_0, b_i, strict=True)) + i.to_bytes(1, "big") + dst_prime
        ).digest()
        uniform += b_i
    return uniform[:len_in_bytes]


def from_uniform_bytes(b: bytes) -> bytes:
    """RFC 9496 §4.3.4: a group element from 64 uniform bytes (libsodium from_hash)."""
    if len(b) != 64:
        raise ValueError("from_uniform_bytes needs 64 bytes")
    out = ctypes.create_string_buffer(32)
    _lib.crypto_core_ristretto255_from_hash(out, b)
    return out.raw


@cache
def generators(d: int) -> tuple[bytes, tuple[bytes, ...]]:
    """§9.2: H and G_0 … G_{d-1}, one independent expand_message call each, fixed DST."""
    h = from_uniform_bytes(expand_message_xmd_sha512(b"H", DST_GEN, 64))
    g = tuple(
        from_uniform_bytes(expand_message_xmd_sha512(b"G" + i.to_bytes(4, "big"), DST_GEN, 64))
        for i in range(d)
    )
    return h, g


def commit(values: Sequence[int], r: int) -> bytes:
    """§9.3: r·H + Σ scalar(v_i)·G_i (a record's C_t, or a group's C_S from S and r_agg)."""
    h, g = generators(len(values))
    return point_add(mul(r, h), msm((scalar(int(v)) for v in values), g))


def ed25519_keypair() -> tuple[bytes, bytes]:
    """(public key 32, secret key 64) from a 32-byte seed read from the OS. Kept in memory only."""
    pk, sk = ctypes.create_string_buffer(32), ctypes.create_string_buffer(64)
    if _lib.crypto_sign_seed_keypair(pk, sk, os.urandom(32)) != 0:
        raise RuntimeError("key generation failed")
    return pk.raw, sk.raw


def ed25519_public_from_seed(seed: bytes) -> tuple[bytes, bytes]:
    """Only for the RFC 8032 known-answer test: the seed is a published test vector, not a key."""
    pk, sk = ctypes.create_string_buffer(32), ctypes.create_string_buffer(64)
    _lib.crypto_sign_seed_keypair(pk, sk, seed)
    return pk.raw, sk.raw


def ed25519_sign(secret_key: bytes, message: bytes) -> bytes:
    sig = ctypes.create_string_buffer(64)
    if _lib.crypto_sign_detached(sig, None, message, len(message), secret_key) != 0:
        raise RuntimeError("signing failed")
    return sig.raw
