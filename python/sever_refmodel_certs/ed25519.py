"""Ed25519 in pure Python, from RFC 8032 §5.1 (signing, §5.1.6; verification, §5.1.7; point
encoding and decoding, §5.1.2–5.1.3), with the stricter checks spec §9.8 asks for
(``verify_strict``): the scalar ``S`` must be below ℓ, and neither the public key nor ``R`` may be a
point of small order. Points are the extended Edwards coordinates of :mod:`ristretto` (the same
curve; RFC 8032 §5.1.4 addition), compared here by their projective coordinates, never with
ristretto's equality (which ignores torsion). Not constant time: a test oracle that only ever
signs with fixed test keys."""

import hashlib
from typing import Final

from sever_refmodel_certs.ristretto import IDENTITY, SQRT_M1, D, L, P, Point

# RFC 8032 §5.1: the base point B, y = 4/5 with x positive (even).
_BY: Final = 4 * pow(5, P - 2, P) % P


class SignatureError(ValueError):
    """A key or a signature RFC 8032 (or the strict checks) rejects."""


def _recover_x(y: int, sign: int) -> int:
    """RFC 8032 §5.1.3 steps 2–4."""
    u = (y * y - 1) % P
    v = (D * y * y + 1) % P
    x = u * pow(v, 3, P) % P * pow(u * pow(v, 7, P) % P, (P - 5) // 8, P) % P
    vxx = v * x * x % P
    if vxx == (-u) % P:
        x = x * SQRT_M1 % P
    elif vxx != u:
        raise SignatureError("not a point on the curve")
    if x == 0 and sign == 1:
        raise SignatureError("x = 0 with the sign bit set")
    if x & 1 != sign:
        x = P - x
    return x


B: Final = Point(_recover_x(_BY, 0), _BY, 1, _recover_x(_BY, 0) * _BY % P)


def encode_point(pt: Point) -> bytes:
    """RFC 8032 §5.1.2."""
    zi = pow(pt.z, P - 2, P)
    x, y = pt.x * zi % P, pt.y * zi % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def decode_point(b: bytes) -> Point:
    """RFC 8032 §5.1.3; a y coordinate ≥ p is rejected (step 1)."""
    if len(b) != 32:
        raise SignatureError("length")
    n = int.from_bytes(b, "little")
    sign, y = n >> 255, n & ((1 << 255) - 1)
    if y >= P:
        raise SignatureError("non-canonical y")
    x = _recover_x(y, sign)
    return Point(x, y, 1, x * y % P)


def _same(a: Point, b: Point) -> bool:
    """Projective equality on the Edwards curve (torsion counts)."""
    return (a.x * b.z - b.x * a.z) % P == 0 and (a.y * b.z - b.y * a.z) % P == 0


def _mul(pt: Point, k: int) -> Point:
    """``[k]pt`` without reducing ``k`` (``Point.__mul__`` reduces mod ℓ, which is wrong for
    points outside the prime-order subgroup)."""
    acc = IDENTITY
    while k:
        if k & 1:
            acc = acc + pt
        pt = pt + pt
        k >>= 1
    return acc


def _small_order(pt: Point) -> bool:
    return _same(_mul(pt, 8), IDENTITY)


def _expand(secret: bytes) -> tuple[int, bytes]:
    """RFC 8032 §5.1.5 steps 1–3: the clamped scalar ``s`` and the ``prefix``."""
    if len(secret) != 32:
        raise SignatureError("a secret key is 32 bytes")
    h = hashlib.sha512(secret).digest()
    a = bytearray(h[:32])
    a[0] &= 248
    a[31] &= 127
    a[31] |= 64
    return int.from_bytes(a, "little"), h[32:]


def public_key(secret: bytes) -> bytes:
    """RFC 8032 §5.1.5 step 4."""
    s, _ = _expand(secret)
    return encode_point(_mul(B, s))


def sign(secret: bytes, msg: bytes) -> bytes:
    """RFC 8032 §5.1.6 (deterministic)."""
    s, prefix = _expand(secret)
    a = encode_point(_mul(B, s))
    r = int.from_bytes(hashlib.sha512(prefix + msg).digest(), "little") % L
    rb = encode_point(_mul(B, r))
    k = int.from_bytes(hashlib.sha512(rb + a + msg).digest(), "little") % L
    return rb + ((r + k * s) % L).to_bytes(32, "little")


def verify(public: bytes, msg: bytes, sig: bytes) -> bool:
    """RFC 8032 §5.1.7 with the cofactorless equation ``[S]B = R + [k]A``, ``S < ℓ``, and no
    small-order ``A`` or ``R`` (spec §9.8, ``verify_strict``)."""
    if len(sig) != 64:
        return False
    try:
        a = decode_point(public)
        r = decode_point(sig[:32])
    except SignatureError:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= L or _small_order(a) or _small_order(r):
        return False
    k = int.from_bytes(hashlib.sha512(sig[:32] + public + msg).digest(), "little") % L
    return _same(_mul(B, s), r + _mul(a, k))
