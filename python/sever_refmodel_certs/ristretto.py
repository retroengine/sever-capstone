"""ristretto255 in pure Python, from RFC 9496 §4 (field arithmetic modulo p = 2^255 − 19, internal
points in extended Edwards coordinates) and RFC 8032 §5.1.4 (point addition). Not constant time:
this is a test oracle and never handles a secret of a real database."""

from dataclasses import dataclass
from typing import Final

P: Final = 2**255 - 19
#: The group order (RFC 9496 §4; spec §2.1).
L: Final = 2**252 + 27742317777372353535851937790883648493

# RFC 9496 §4.1 implementation constants.
D: Final = 37095705934669439343138083508754565189542113879843219016388785533085940283555
SQRT_M1: Final = 19681161376707505956807079304988542015446066515923890162744021073123829784752
SQRT_AD_MINUS_ONE: Final = (
    25063068953384623474111414158702152701244531502492656460079210482610430750235
)
INVSQRT_A_MINUS_D: Final = (
    54469307008909316920995813868745141605393597292927456921205312896311721017578
)
ONE_MINUS_D_SQ: Final = 1159843021668779879193775521855586647937357759715417654439879720876111806838
D_MINUS_ONE_SQ: Final = (
    40440834346308536858101042469323190826248399146238708352240133220865137265952
)


def _inv(x: int) -> int:
    return pow(x, P - 2, P)


def is_negative(e: int) -> bool:
    """RFC 9496 §2.1: the least nonnegative representative is odd."""
    return (e % P) & 1 == 1


def ct_abs(u: int) -> int:
    """RFC 9496 §2.2 ``CT_ABS``."""
    return (-u) % P if is_negative(u) else u % P


def sqrt_ratio_m1(u: int, v: int) -> tuple[bool, int]:
    """RFC 9496 §4.2 ``SQRT_RATIO_M1(u, v)``."""
    u, v = u % P, v % P
    v3 = v * v % P * v % P
    v7 = v3 * v3 % P * v % P
    r = u * v3 % P * pow(u * v7 % P, (P - 5) // 8, P) % P
    check = v * r % P * r % P
    correct_sign_sqrt = check == u
    flipped_sign_sqrt = check == (-u) % P
    flipped_sign_sqrt_i = check == (-u) * SQRT_M1 % P
    if flipped_sign_sqrt or flipped_sign_sqrt_i:
        r = SQRT_M1 * r % P
    r = ct_abs(r)
    return correct_sign_sqrt or flipped_sign_sqrt, r


@dataclass(frozen=True, eq=False)  # RFC 9496 §4.3.3: never compare coordinates
class Point:
    """An internal representation (x, y, z, t); compare only with :meth:`equals` or the encodings
    (RFC 9496 §4.3.3)."""

    x: int
    y: int
    z: int
    t: int

    def __add__(self, o: "Point") -> "Point":
        # RFC 8032 §5.1.4, extended coordinates, a = −1.
        a = (self.y - self.x) * (o.y - o.x) % P
        b = (self.y + self.x) * (o.y + o.x) % P
        c = self.t * 2 * D * o.t % P
        d = self.z * 2 * o.z % P
        e, f, g, h = (b - a) % P, (d - c) % P, (d + c) % P, (b + a) % P
        return Point(e * f % P, g * h % P, f * g % P, e * h % P)

    def __neg__(self) -> "Point":
        return Point((-self.x) % P, self.y, self.z, (-self.t) % P)

    def __sub__(self, o: "Point") -> "Point":
        return self + (-o)

    def __mul__(self, k: int) -> "Point":
        """Scalar multiplication by repeated addition (RFC 9496 §3), double-and-add on ``k mod ℓ``;
        a zero scalar gives the identity (§9 of the spec)."""
        k %= L
        acc, base = IDENTITY, self
        while k:
            if k & 1:
                acc = acc + base
            base = base + base
            k >>= 1
        return acc

    __rmul__ = __mul__

    def equals(self, o: "Point") -> bool:
        """RFC 9496 §4.3.3."""
        return (self.x * o.y - self.y * o.x) % P == 0 or (self.y * o.y - self.x * o.x) % P == 0


IDENTITY: Final = Point(0, 1, 1, 0)


class DecodeError(ValueError):
    """An encoding RFC 9496 §4.3.1 rejects."""


def decode(b: bytes) -> Point:
    """RFC 9496 §4.3.1."""
    if len(b) != 32:
        raise DecodeError("length")
    s = int.from_bytes(b, "little")
    if s >= P:
        raise DecodeError("non-canonical field element")
    if is_negative(s):
        raise DecodeError("negative field element")
    ss = s * s % P
    u1 = (1 - ss) % P
    u2 = (1 + ss) % P
    u2_sqr = u2 * u2 % P
    v = (-(D * u1 % P * u1) - u2_sqr) % P
    was_square, invsqrt = sqrt_ratio_m1(1, v * u2_sqr)
    den_x = invsqrt * u2 % P
    den_y = invsqrt * den_x % P * v % P
    x = ct_abs(2 * s * den_x)
    y = u1 * den_y % P
    t = x * y % P
    if not was_square or is_negative(t) or y == 0:
        raise DecodeError("not a valid element")
    return Point(x, y, 1, t)


def encode(pt: Point) -> bytes:
    """RFC 9496 §4.3.2."""
    x0, y0, z0, t0 = pt.x, pt.y, pt.z, pt.t
    u1 = (z0 + y0) * (z0 - y0) % P
    u2 = x0 * y0 % P
    _, invsqrt = sqrt_ratio_m1(1, u1 * u2 % P * u2)
    den1 = invsqrt * u1 % P
    den2 = invsqrt * u2 % P
    z_inv = den1 * den2 % P * t0 % P
    ix0 = x0 * SQRT_M1 % P
    iy0 = y0 * SQRT_M1 % P
    enchanted_denominator = den1 * INVSQRT_A_MINUS_D % P
    rotate = is_negative(t0 * z_inv)
    x = iy0 if rotate else x0
    y = ix0 if rotate else y0
    z = z0
    den_inv = enchanted_denominator if rotate else den2
    y = (-y) % P if is_negative(x * z_inv) else y
    s = ct_abs(den_inv * ((z - y) % P))
    return s.to_bytes(32, "little")


def _map(b: bytes) -> Point:
    """RFC 9496 §4.3.4 ``MAP`` on 32 bytes."""
    t = (int.from_bytes(b, "little") % 2**255) % P  # step 1: mask the top bit, reduce mod p
    r = SQRT_M1 * t % P * t % P
    u = (r + 1) * ONE_MINUS_D_SQ % P
    v = (-1 - r * D) * (r + D) % P
    was_square, s = sqrt_ratio_m1(u, v)
    s_prime = (-ct_abs(s * t)) % P
    s = s if was_square else s_prime
    c = P - 1 if was_square else r
    n = (c * (r - 1) % P * D_MINUS_ONE_SQ - v) % P
    w0 = 2 * s * v % P
    w1 = n * SQRT_AD_MINUS_ONE % P
    w2 = (1 - s * s) % P
    w3 = (1 + s * s) % P
    return Point(w0 * w3 % P, w2 * w1 % P, w1 * w3 % P, w0 * w2 % P)


def from_uniform_bytes(b: bytes) -> Point:
    """RFC 9496 §4.3.4 element derivation: ``MAP(b[0:32]) + MAP(b[32:64])``."""
    if len(b) != 64:
        raise ValueError("element derivation takes 64 bytes")
    return _map(b[:32]) + _map(b[32:])


def decode_scalar(b: bytes) -> int:
    """RFC 9496 §4.4 and spec §9.9: 32 bytes little-endian, rejected unless ``0 ≤ s < ℓ``."""
    if len(b) != 32:
        raise DecodeError("length")
    s = int.from_bytes(b, "little")
    if s >= L:
        raise DecodeError("non-canonical scalar")
    return s


def encode_scalar(s: int) -> bytes:
    return (s % L).to_bytes(32, "little")
