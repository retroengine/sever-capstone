"""Clean-room helpers for the SEVER-DB Part 3 tests, written from the specification only.

Nothing here touches the engine. It holds:

- the §6.3 artefact parser and a §7.1–7.3 router, so tests can choose vectors whose destination
  (a frozen group or the holding area) follows from the spec with a wide margin;
- the §4.1 normalisation check and the §4.2 quantiser;
- ristretto255 (RFC 9496) and the §9.2 generators (RFC 9380 expand_message_xmd, SHA-512);
- Ed25519 verification (RFC 8032, cofactorless as `verify_strict` requires);
- the RFC 9162 Merkle tree hash, inclusion and consistency verification (§10.1);
- a strict §11.1 / §11.2 certificate parser and the §11.3 verification algorithm.

Each primitive is checked against third-party vectors in test_zz_helper_selfcheck.py.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass

import numpy as np

# --------------------------------------------------------------------------------------------
# §2.3 domain strings (exact bytes)
DST_GEN = b"PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS"
DST_POSK = b"SEVERDB_POSK_V1"
DST_INSERT = b"SEVERDB-INSERT-V1"
DST_STH = b"SEVERDB-STH-V1"
DST_COSIGN = b"SEVERDB-COSIGN-V1"
DST_CERT = b"SEVERDB-CERT-V1"

TOL = 8 * 2.0**-23  # §4.1 step 3
SCALE = 2**24  # §4.2

# --------------------------------------------------------------------------------------------
# §6.3 artefact


@dataclass
class Artefact:
    d: int
    k: int
    seed: int
    tau: float
    shrink: float
    m: int
    encoder: str
    centroids: np.ndarray  # k × d
    P: np.ndarray  # d × d
    raw: bytes


def parse_artefact(path: str) -> Artefact:
    raw = open(path, "rb").read()
    assert raw[:8] == b"SVDBPART"
    ver, d, k = struct.unpack(">HHH", raw[8:14])
    assert ver == 1
    seed, tau, shrink, m = struct.unpack(">QddQ", raw[14:46])
    off = 46 + 32
    (elen,) = struct.unpack(">H", raw[off : off + 2])
    off += 2
    enc = raw[off : off + elen].decode()
    off += elen
    cent = np.frombuffer(raw[off : off + 8 * k * d], dtype=">f8").astype(np.float64).reshape(k, d)
    off += 8 * k * d
    P = np.frombuffer(raw[off : off + 8 * d * d], dtype=">f8").astype(np.float64).reshape(d, d)
    off += 8 * d * d
    assert hashlib.sha256(raw[:off]).digest() == raw[off : off + 32]
    assert off + 32 == len(raw)
    return Artefact(d, k, seed, tau, shrink, m, enc, cent, P, raw)


# --------------------------------------------------------------------------------------------
# §4.1, §4.2


def spec_norm(x) -> float:
    """§4.1 step 2: float64, sequential sum from i = 0."""
    s = 0.0
    for v in np.asarray(x, dtype=np.float32):
        s += float(v) * float(v)
    return math.sqrt(s)


def is_normalised(x) -> bool:
    return abs(spec_norm(x) - 1.0) <= TOL


def quantise(x) -> np.ndarray:
    """§4.2: round_half_to_even((f64)x_i · 2^24). np.rint rounds half to even."""
    return np.rint(np.asarray(x, dtype=np.float32).astype(np.float64) * SCALE).astype(np.int64)


def dequantise(q) -> np.ndarray:
    return np.asarray(q, dtype=np.float64) / SCALE


def unit(v) -> list[float]:
    """A float32 vector normalised so that §4.1 accepts it (checked)."""
    v = np.asarray(v, dtype=np.float64)
    x = (v / np.linalg.norm(v)).astype(np.float32)
    assert is_normalised(x), "helper produced an un-normalised vector"
    return [float(t) for t in x]


def route_frozen(art: Artefact, x):
    """§7.1–7.2: nearest frozen label, the distances to every centroid and d_M."""
    xh = dequantise(quantise(x))
    D = ((xh[None, :] - art.centroids) ** 2).sum(axis=1)
    j = int(np.argmin(D))
    delta = xh - art.centroids[j]
    q = float(delta @ (art.P @ delta))
    return j, D, math.sqrt(max(q, 0.0))


def in_dist_vector(art: Artefact, rng: np.random.Generator, label: int | None = None,
                   margin: float = 0.7) -> list[float]:
    """A vector whose §7.3 destination is frozen group `label` (or any frozen group) with a wide
    margin: d_M ≤ margin·τ and the nearest centroid wins by a clear distance, so the result does
    not depend on summation order. Built by stepping from a centroid along the precision's
    weakest directions."""
    evals, evecs = np.linalg.eigh(art.P)  # small eigenvalue = large variance
    labels = [label] if label is not None else list(range(art.k))
    for _ in range(4000):
        j = labels[int(rng.integers(len(labels)))]
        mu = art.centroids[j]
        # a small random step, mostly in high-variance directions
        coef = rng.normal(size=art.d) / np.sqrt(evals) * rng.uniform(0.05, 0.6)
        v = mu + evecs @ coef / max(1.0, math.sqrt(art.d) / 2)
        x = unit(v)
        jj, D, dm = route_frozen(art, x)
        Ds = np.sort(D)
        if jj == j and dm <= margin * art.tau and Ds[1] - Ds[0] > 1e-6:
            return x
    raise AssertionError("could not build an in-distribution vector")


def ood_vector(art: Artefact, rng: np.random.Generator, factor: float = 1.5) -> list[float]:
    """A vector with d_M > factor·τ: out of distribution (§7.2), so with no spawned group it goes
    to the holding area (§7.3)."""
    for _ in range(4000):
        x = unit(rng.normal(size=art.d))
        _, _, dm = route_frozen(art, x)
        if dm > factor * art.tau:
            return x
    raise AssertionError("could not build an out-of-distribution vector")


def spawn_id(record_ids) -> str:
    """§7.5: spawn- + first 16 hex of SHA-256(‖ u16be(len) ‖ id) over IDs ascending by bytes."""
    h = hashlib.sha256()
    for b in sorted(r.encode() for r in record_ids):
        h.update(struct.pack(">H", len(b)) + b)
    return "spawn-" + h.hexdigest()[:16]


# --------------------------------------------------------------------------------------------
# Field and curve arithmetic (RFC 7748 / RFC 8032 / RFC 9496)

p = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493  # ℓ
Dc = (-121665 * pow(121666, p - 2, p)) % p
D2 = (2 * Dc) % p
SQRT_M1 = pow(2, (p - 1) // 4, p)


def _neg(x: int) -> bool:
    return (x % p) & 1 == 1


def _abs(x: int) -> int:
    x %= p
    return p - x if x & 1 else x


def sqrt_ratio_m1(u: int, v: int):
    u %= p
    v %= p
    v3 = v * v % p * v % p
    v7 = v3 * v3 % p * v % p
    r = u * v3 % p * pow(u * v7 % p, (p - 5) // 8, p) % p
    check = v * r % p * r % p
    correct = check == u
    flipped = check == (-u) % p
    flipped_i = check == (-u * SQRT_M1) % p
    if flipped or flipped_i:
        r = r * SQRT_M1 % p
    r = _abs(r)
    return correct or flipped, r


# RFC 9496 §4.1 constants: SQRT_AD_MINUS_ONE is the odd root, given there as a literal.
SQRT_AD_MINUS_ONE = 25063068953384623474111414158702152701244531502492656460079210482610430750235
assert SQRT_AD_MINUS_ONE * SQRT_AD_MINUS_ONE % p == (-Dc - 1) % p
_ok2, INVSQRT_A_MINUS_D = sqrt_ratio_m1(1, (-1 - Dc) % p)
ONE_MINUS_D_SQ = (1 - Dc * Dc) % p
D_MINUS_ONE_SQ = (Dc - 1) * (Dc - 1) % p

IDENTITY = (0, 1, 1, 0)


def padd(P1, P2):
    X1, Y1, Z1, T1 = P1
    X2, Y2, Z2, T2 = P2
    A = (Y1 - X1) * (Y2 - X2) % p
    B = (Y1 + X1) * (Y2 + X2) % p
    C = T1 * D2 % p * T2 % p
    Dd = Z1 * 2 * Z2 % p
    E, F, G, H = B - A, Dd - C, Dd + C, B + A
    return (E * F % p, G * H % p, F * G % p, E * H % p)


def pneg(P1):
    X, Y, Z, T = P1
    return ((-X) % p, Y, Z, (-T) % p)


def psub(P1, P2):
    return padd(P1, pneg(P2))


def pmul(s: int, P1):
    Q = IDENTITY
    R = P1
    while s > 0:
        if s & 1:
            Q = padd(Q, R)
        R = padd(R, R)
        s >>= 1
    return Q


def msm(scalars, points):
    acc = IDENTITY
    for s, P1 in zip(scalars, points):
        acc = padd(acc, pmul(s % L, P1))
    return acc


def peq_ristretto(P1, P2) -> bool:
    X1, Y1, _, _ = P1
    X2, Y2, _, _ = P2
    return (X1 * Y2 - Y1 * X2) % p == 0 or (Y1 * Y2 - X1 * X2) % p == 0


class DecodeError(ValueError):
    pass


def r_decode(b: bytes):
    """RFC 9496 §4.3.1: canonical decoding; raises DecodeError otherwise."""
    if len(b) != 32:
        raise DecodeError("length")
    s = int.from_bytes(b, "little")
    if s >= p or _neg(s):
        raise DecodeError("non-canonical")
    ss = s * s % p
    u1 = (1 - ss) % p
    u2 = (1 + ss) % p
    u2s = u2 * u2 % p
    v = (-(Dc * u1 % p * u1) - u2s) % p
    was_square, invsqrt = sqrt_ratio_m1(1, v * u2s % p)
    den_x = invsqrt * u2 % p
    den_y = invsqrt * den_x % p * v % p
    x = _abs(2 * s * den_x)
    y = u1 * den_y % p
    t = x * y % p
    if not was_square or _neg(t) or y == 0:
        raise DecodeError("not a ristretto255 point")
    return (x, y, 1, t)


def r_encode(P1) -> bytes:
    X, Y, Z, T = P1
    u1 = (Z + Y) * (Z - Y) % p
    u2 = X * Y % p
    _, invsqrt = sqrt_ratio_m1(1, u1 * u2 % p * u2 % p)
    den1 = invsqrt * u1 % p
    den2 = invsqrt * u2 % p
    z_inv = den1 * den2 % p * T % p
    ix0 = X * SQRT_M1 % p
    iy0 = Y * SQRT_M1 % p
    ench = den1 * INVSQRT_A_MINUS_D % p
    if _neg(T * z_inv):
        x, y, den_inv = iy0, ix0, ench
    else:
        x, y, den_inv = X, Y, den2
    if _neg(x * z_inv):
        y = (-y) % p
    s = _abs(den_inv * (Z - y))
    return s.to_bytes(32, "little")


def _map(t: int):
    r = SQRT_M1 * t % p * t % p
    u = (r + 1) * ONE_MINUS_D_SQ % p
    v = (-1 - r * Dc) * (r + Dc) % p
    was_square, s = sqrt_ratio_m1(u, v)
    s_prime = (-_abs(s * t)) % p
    if not was_square:
        s = s_prime
    c = (p - 1) if was_square else r
    N = (c * (r - 1) % p * D_MINUS_ONE_SQ - v) % p
    w0 = 2 * s * v % p
    w1 = N * SQRT_AD_MINUS_ONE % p
    w2 = (1 - s * s) % p
    w3 = (1 + s * s) % p
    return (w0 * w3 % p, w2 * w1 % p, w1 * w3 % p, w0 * w2 % p)


def from_uniform_bytes(b: bytes):
    assert len(b) == 64
    t1 = int.from_bytes(b[:32], "little") & ((1 << 255) - 1)
    t2 = int.from_bytes(b[32:], "little") & ((1 << 255) - 1)
    return padd(_map(t1), _map(t2))


def expand_message_xmd_sha512(msg: bytes, dst: bytes, n: int) -> bytes:
    """RFC 9380 §5.3.1 with SHA-512 (b_in_bytes 64, s_in_bytes 128)."""
    ell = -(-n // 64)
    assert ell <= 255 and len(dst) <= 255
    dst_prime = dst + bytes([len(dst)])
    msg_prime = bytes(128) + msg + n.to_bytes(2, "big") + b"\x00" + dst_prime
    b0 = hashlib.sha512(msg_prime).digest()
    b = [hashlib.sha512(b0 + b"\x01" + dst_prime).digest()]
    for i in range(2, ell + 1):
        x = bytes(a ^ c for a, c in zip(b0, b[-1]))
        b.append(hashlib.sha512(x + bytes([i]) + dst_prime).digest())
    return b"".join(b)[:n]


_GEN_CACHE: dict[int, tuple] = {}


def generators(d: int):
    """§9.2: H and G_0 … G_{d−1}, as points; cached."""
    if d not in _GEN_CACHE:
        H = from_uniform_bytes(expand_message_xmd_sha512(b"H", DST_GEN, 64))
        G = [from_uniform_bytes(expand_message_xmd_sha512(b"G" + struct.pack(">I", i), DST_GEN, 64))
             for i in range(d)]
        _GEN_CACHE[d] = (H, G)
    return _GEN_CACHE[d]


def gdigest(d: int) -> bytes:
    """§9.6: SHA-512(H ‖ G_0 ‖ … ‖ G_{d−1})."""
    H, G = generators(d)
    return hashlib.sha512(r_encode(H) + b"".join(r_encode(g) for g in G)).digest()


def scalar_of(v: int) -> int:
    """§4.5: v mod ℓ for v ≥ 0, ℓ − (|v| mod ℓ) for v < 0."""
    return v % L if v >= 0 else L - (abs(v) % L)


def scalar_decode(b: bytes) -> int:
    """§9.9: canonical scalar (little-endian, < ℓ) or DecodeError."""
    if len(b) != 32:
        raise DecodeError("length")
    s = int.from_bytes(b, "little")
    if s >= L:
        raise DecodeError("non-canonical scalar")
    return s


def r_add_enc(a: bytes, b: bytes) -> bytes:
    return r_encode(padd(r_decode(a), r_decode(b)))


def r_sub_enc(a: bytes, b: bytes) -> bytes:
    return r_encode(psub(r_decode(a), r_decode(b)))


def r_sum_enc(encs) -> bytes:
    acc = IDENTITY
    for e in encs:
        acc = padd(acc, r_decode(e))
    return r_encode(acc)


IDENTITY_ENC = bytes(32)  # §5.2: the 32-byte all-zero encoding

# --------------------------------------------------------------------------------------------
# Ed25519 (RFC 8032 §5.1.7), cofactorless and rejecting non-canonical encodings

_BY = 4 * pow(5, p - 2, p) % p


def _recover_x(y: int, sign: int):
    if y >= p:
        return None
    x2 = (y * y - 1) * pow(Dc * y * y + 1, p - 2, p) % p
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p != 0:
        x = x * SQRT_M1 % p
    if (x * x - x2) % p != 0:
        return None
    if (x & 1) != sign:
        x = p - x
    return x


_BX = _recover_x(_BY, 0)
ED_B = (_BX, _BY, 1, _BX * _BY % p)


def _ed_decode(b: bytes):
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % p)


def _ed_encode(P1) -> bytes:
    X, Y, Z, _ = P1
    zi = pow(Z, p - 2, p)
    x, y = X * zi % p, Y * zi % p
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _ed_eq(P1, P2) -> bool:
    X1, Y1, Z1, _ = P1
    X2, Y2, Z2, _ = P2
    return (X1 * Z2 - X2 * Z1) % p == 0 and (Y1 * Z2 - Y2 * Z1) % p == 0


def _small_order(P1) -> bool:
    Q = padd(padd(P1, P1), padd(P1, P1))
    Q = padd(Q, Q)
    return _ed_eq(Q, IDENTITY)


def ed25519_verify(pk: bytes, msg: bytes, sig: bytes) -> bool:
    if len(pk) != 32 or len(sig) != 64:
        return False
    A = _ed_decode(pk)
    R = _ed_decode(sig[:32])
    if A is None or R is None or _small_order(A):
        return False
    if _ed_encode(A) != pk or _ed_encode(R) != sig[:32]:
        return False
    S = int.from_bytes(sig[32:], "little")
    if S >= L:
        return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + pk + msg).digest(), "little") % L
    return _ed_eq(pmul(S, ED_B), padd(R, pmul(h, A)))


# --------------------------------------------------------------------------------------------
# RFC 9162 §2.1


def leaf_hash(leaf: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + leaf).digest()


def node_hash(a: bytes, b: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + a + b).digest()


def mth_hashes(hashes: list[bytes]) -> bytes:
    n = len(hashes)
    if n == 0:
        return hashlib.sha256(b"").digest()
    if n == 1:
        return hashes[0]
    k = 1
    while k * 2 < n:
        k *= 2
    return node_hash(mth_hashes(hashes[:k]), mth_hashes(hashes[k:]))


def mth(leaves: list[bytes]) -> bytes:
    return mth_hashes([leaf_hash(x) for x in leaves])


def verify_inclusion(leaf_index: int, tree_size: int, lh: bytes, path: list[bytes], root: bytes) -> bool:
    """RFC 9162 §2.1.3.2."""
    if leaf_index >= tree_size:
        return False
    fn, sn, r = leaf_index, tree_size - 1, lh
    for pnode in path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = node_hash(pnode, r)
            if not fn & 1:
                while True:
                    fn >>= 1
                    sn >>= 1
                    if fn & 1 or fn == 0:
                        break
        else:
            r = node_hash(r, pnode)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == root


def verify_consistency(first: int, second: int, first_hash: bytes, second_hash: bytes,
                       proof: list[bytes]) -> bool:
    """RFC 9162 §2.1.4.2."""
    if not proof or not (0 < first < second):
        return False
    proof = list(proof)
    if first & (first - 1) == 0:  # exact power of two
        proof = [first_hash] + proof
    fn, sn = first - 1, second - 1
    while fn & 1:
        fn >>= 1
        sn >>= 1
    fr = sr = proof[0]
    for c in proof[1:]:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            fr = node_hash(c, fr)
            sr = node_hash(c, sr)
            if not fn & 1:
                while True:
                    fn >>= 1
                    sn >>= 1
                    if fn & 1 or fn == 0:
                        break
        else:
            sr = node_hash(sr, c)
        fn >>= 1
        sn >>= 1
    return fr == first_hash and sr == second_hash and sn == 0


def inclusion_path(leaves_hashes: list[bytes], m: int) -> list[bytes]:
    """RFC 9162 §2.1.3.1 PATH(m, D[n]), for comparison with the engine's proofs."""
    n = len(leaves_hashes)
    if n <= 1:
        return []
    k = 1
    while k * 2 < n:
        k *= 2
    if m < k:
        return inclusion_path(leaves_hashes[:k], m) + [mth_hashes(leaves_hashes[k:])]
    return inclusion_path(leaves_hashes[k:], m - k) + [mth_hashes(leaves_hashes[:k])]


def _subproof(m: int, hs: list[bytes], b: bool) -> list[bytes]:
    n = len(hs)
    if m == n:
        return [] if b else [mth_hashes(hs)]
    k = 1
    while k * 2 < n:
        k *= 2
    if m <= k:
        return _subproof(m, hs[:k], b) + [mth_hashes(hs[k:])]
    return _subproof(m - k, hs[k:], False) + [mth_hashes(hs[:k])]


def consistency_path(leaves_hashes: list[bytes], m: int) -> list[bytes]:
    """RFC 9162 §2.1.4.1 PROOF(m, D[n])."""
    return _subproof(m, leaves_hashes, True)


# --------------------------------------------------------------------------------------------
# §11.1 / §11.2 certificates


class CertError(ValueError):
    pass


@dataclass
class Checkpoint:
    tree_size: int
    root: bytes
    timestamp_ms: int
    epoch: int
    signature: bytes

    def message(self) -> bytes:
        """§9.8: DST_STH ‖ u64be tree_size ‖ root ‖ u64be timestamp_ms ‖ u32be epoch (66 bytes)."""
        return DST_STH + struct.pack(">Q", self.tree_size) + self.root + struct.pack(
            ">QI", self.timestamp_ms, self.epoch)


@dataclass
class Certificate:
    raw: bytes
    tags: dict
    body: bytes
    signature: bytes
    c_t: bytes
    cs_pre: bytes
    cs_post: bytes
    proof: bytes
    user_sig: bytes
    version: int
    insert_leaf: bytes
    leaf_index: int
    checkpoint: Checkpoint
    path: list
    cosigs: list  # (index, epoch, sig)
    key_period: int
    scrambled_id: bytes
    database_lsn: int
    emptied: int
    kind: int
    collection_id: bytes


FIXED = {1: 32, 5: 64, 8: 4, 9: 64, 10: 8, 11: 1, 12: 1, 13: 16}


def parse_certificate(raw: bytes, d: int) -> Certificate:
    """§11.1: tags 1…13 ascending, each once, then 0xFF ‖ u32be 64 ‖ signature; strict."""
    off = 0
    tags = {}
    for want in range(1, 14):
        if off + 5 > len(raw):
            raise CertError("missing tag %d" % want)
        tag = raw[off]
        (ln,) = struct.unpack(">I", raw[off + 1 : off + 5])
        if tag != want:
            raise CertError("tag %d where %d expected" % (tag, want))
        val = raw[off + 5 : off + 5 + ln]
        if len(val) != ln:
            raise CertError("short value")
        tags[tag] = val
        off += 5 + ln
    body = raw[:off]
    if raw[off : off + 5] != b"\xff" + struct.pack(">I", 64):
        raise CertError("trailer")
    sig = raw[off + 5 : off + 69]
    if len(sig) != 64 or off + 69 != len(raw):
        raise CertError("trailing bytes or short signature")
    for t, n in FIXED.items():
        if len(tags[t]) != n:
            raise CertError("tag %d length" % t)
    kind = tags[12][0]
    if kind not in (0, 1) or tags[11][0] not in (0, 1):
        raise CertError("tag 11/12 outside {0,1}")
    if kind == 0:
        if len(tags[2]) != 32 or len(tags[3]) != 32 or len(tags[4]) != 64 + 32 * d:
            raise CertError("group deletion field length")
    # tag 6
    t6 = tags[6]
    if len(t6) < 1 + 209 + 8 + 116 + 1:
        raise CertError("tag 6 short")
    version = t6[0]
    leaf = t6[1:210]
    (leaf_index,) = struct.unpack(">Q", t6[210:218])
    ts, root, tms, ep = struct.unpack(">Q", t6[218:226])[0], t6[226:258], *struct.unpack(">QI", t6[258:270])
    cpsig = t6[270:334]
    plen = t6[334]
    if len(t6) != 335 + 32 * plen:
        raise CertError("tag 6 path length")
    path = [t6[335 + 32 * i : 367 + 32 * i] for i in range(plen)]
    # tag 7
    t7 = tags[7]
    if not t7 or len(t7) != 1 + 69 * t7[0]:
        raise CertError("tag 7 length")
    cos = []
    for i in range(t7[0]):
        e = t7[1 + 69 * i : 70 + 69 * i]
        cos.append((e[0], struct.unpack(">I", e[1:5])[0], e[5:69]))
    return Certificate(
        raw=raw, tags=tags, body=body, signature=sig, c_t=tags[1], cs_pre=tags[2],
        cs_post=tags[3], proof=tags[4], user_sig=tags[5], version=version, insert_leaf=leaf,
        leaf_index=leaf_index, checkpoint=Checkpoint(ts, root, tms, ep, cpsig), path=path,
        cosigs=cos, key_period=struct.unpack(">I", tags[8])[0], scrambled_id=tags[9],
        database_lsn=struct.unpack(">Q", tags[10])[0], emptied=tags[11][0], kind=kind,
        collection_id=tags[13])


def make_ctx(c: Certificate) -> bytes:
    """§9.5: C_S_pre ‖ C_t ‖ scrambled_id ‖ u64be(database_lsn) ‖ collection_id (152 bytes)."""
    return c.cs_pre + c.c_t + c.scrambled_id + struct.pack(">Q", c.database_lsn) + c.collection_id


def verify_proof(c: Certificate, d: int) -> bool:
    """§9.5 verifier: z_r·H + Σ z_i·G_i = A + c·C_S_post."""
    H, G = generators(d)
    A_enc = c.proof[:32]
    A = r_decode(A_enc)
    zs = [scalar_decode(c.proof[32 + 32 * i : 64 + 32 * i]) for i in range(d + 1)]
    ch = int.from_bytes(hashlib.sha512(DST_POSK + c.cs_post + A_enc + make_ctx(c)).digest(),
                        "little") % L
    lhs = msm(zs, [H] + list(G))
    rhs = padd(A, pmul(ch, r_decode(c.cs_post)))
    return peq_ristretto(lhs, rhs)


def anchor_key(keys: dict, epoch: int):
    v = keys.get(str(epoch))
    return bytes.fromhex(v) if v is not None else None


def verify_certificate(raw: bytes, anchors: dict, check_proof: bool = True):
    """§11.3 steps 1–8. Returns (True, None) or (False, step number)."""
    d = anchors["d"]
    try:  # step 1
        c = parse_certificate(raw, d)
        if c.c_t == IDENTITY_ENC:
            return False, 1
        r_decode(c.c_t)
        if c.kind == 0:
            r_decode(c.cs_pre)
            r_decode(c.cs_post)
            r_decode(c.proof[:32])
            for i in range(d + 1):
                scalar_decode(c.proof[32 + 32 * i : 64 + 32 * i])
    except (CertError, DecodeError):
        return False, 1
    opk = anchor_key(anchors["operator"], c.key_period)  # step 2
    if opk is None or not ed25519_verify(opk, DST_CERT + c.body, c.signature):
        return False, 2
    leaf = c.insert_leaf  # step 3
    if c.version != 1 or leaf[0] != 1:
        return False, 3
    if leaf[1:17] != c.collection_id or leaf[17:81] != c.scrambled_id or leaf[81:113] != c.c_t \
            or leaf[145:209] != c.user_sig:
        return False, 3
    if not ed25519_verify(leaf[113:145], DST_INSERT + c.collection_id + c.c_t, c.user_sig):
        return False, 3
    cp = c.checkpoint
    if not verify_inclusion(c.leaf_index, cp.tree_size, leaf_hash(leaf), c.path, cp.root):
        return False, 3
    k = anchor_key(anchors["operator"], cp.epoch)
    if k is None or not ed25519_verify(k, cp.message(), cp.signature):
        return False, 3
    good = set()  # step 4
    for idx, ep, sig in c.cosigs:
        if idx >= len(anchors["witnesses"]):
            continue
        wk = anchor_key(anchors["witnesses"][idx], ep)
        if wk is not None and ed25519_verify(wk, DST_COSIGN + cp.message(), sig):
            good.add(idx)
    if len(good) < 4:
        return False, 4
    if not c.database_lsn > c.leaf_index:  # step 5
        return False, 5
    if c.kind == 0:  # step 6
        if r_add_enc(c.cs_post, c.c_t) != c.cs_pre:
            return False, 6
        if check_proof and not verify_proof(c, d):
            return False, 6
        if (c.emptied == 1) != (c.cs_post == IDENTITY_ENC):
            return False, 6
    else:  # step 7
        if c.cs_pre or c.cs_post or c.proof or c.emptied != 0:
            return False, 7
    return True, None


def load_anchors(s: str) -> dict:
    return json.loads(s)
