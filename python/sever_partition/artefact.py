"""The partition artefact ``partition.svp``, byte for byte (spec §6.3)."""

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

MAGIC: Final = b"SVDBPART"
FORMAT_VERSION: Final = 1
#: magic 8 + version 2 + d 2 + k 2 + seed 8 + tau 8 + shrinkage 8 + m 8 + sha256_reference 32.
FIXED_PREFIX: Final = 78


class ArtefactError(ValueError):
    """A malformed or inconsistent artefact (spec §6.3 checks)."""


@dataclass(frozen=True)
class Artefact:
    """The fields of §6.3, in file order."""

    d: int
    k_frozen: int
    seed: int
    tau: float
    lw_shrinkage: float
    m: int
    sha256_reference: bytes
    encoder: str
    centroids: NDArray[np.float64]  # (k_frozen, d), label order
    precision: NDArray[np.float64]  # (d, d)


def encode(a: Artefact) -> bytes:
    """§6.3: every field big-endian and fixed-width, then SHA-256 of every preceding byte."""
    enc = a.encoder.encode("utf-8")
    if len(a.sha256_reference) != 32:
        raise ArtefactError("sha256_reference must be 32 bytes")
    if a.centroids.shape != (a.k_frozen, a.d) or a.precision.shape != (a.d, a.d):
        raise ArtefactError("matrix shapes do not match d and k_frozen")
    body = b"".join(
        [
            MAGIC,
            struct.pack(">HHHQdd", FORMAT_VERSION, a.d, a.k_frozen, a.seed, a.tau, a.lw_shrinkage),
            struct.pack(">Q", a.m),
            a.sha256_reference,
            struct.pack(">H", len(enc)),
            enc,
            a.centroids.astype(">f8").tobytes(order="C"),
            a.precision.astype(">f8").tobytes(order="C"),
        ]
    )
    return body + hashlib.sha256(body).digest()


def decode(data: bytes) -> Artefact:
    """Parses and checks what ``create_collection`` must check (§6.3): the hash, ``d`` and a finite
    precision matrix; plus magic, version and exact length."""
    if len(data) < FIXED_PREFIX + 2 + 32:
        raise ArtefactError("truncated")
    body, digest = data[:-32], data[-32:]
    if hashlib.sha256(body).digest() != digest:
        raise ArtefactError("sha256_artefact mismatch")
    if body[:8] != MAGIC:
        raise ArtefactError("bad magic")
    version, d, k, seed, tau, shrink = struct.unpack_from(">HHHQdd", body, 8)
    if version != FORMAT_VERSION:
        raise ArtefactError("unsupported format version")
    if d == 0 or d % 8 != 0 or k == 0:
        raise ArtefactError("bad d or k_frozen")
    (m,) = struct.unpack_from(">Q", body, 38)
    sha_ref = body[46:78]
    (enc_len,) = struct.unpack_from(">H", body, 78)
    pos = 80 + enc_len
    encoder = body[80:pos].decode("utf-8")
    need = pos + 8 * (k * d + d * d)
    if len(body) != need:
        raise ArtefactError("length does not match d and k_frozen")
    cen = np.frombuffer(body, dtype=">f8", count=k * d, offset=pos).astype(np.float64)
    pre = np.frombuffer(body, dtype=">f8", count=d * d, offset=pos + 8 * k * d).astype(np.float64)
    if not np.isfinite(pre).all() or not np.isfinite(cen).all() or not math.isfinite(tau):
        raise ArtefactError("non-finite value")
    return Artefact(
        d, k, seed, tau, shrink, m, sha_ref, encoder, cen.reshape(k, d), pre.reshape(d, d)
    )
