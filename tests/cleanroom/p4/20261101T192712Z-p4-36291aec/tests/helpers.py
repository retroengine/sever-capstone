"""Hand-written helpers derived from the SEVER-DB specification only.

Nothing here comes from the engine: every routine re-implements a formula or byte layout of the
spec (cited by §) so that tests can derive expected values by hand.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass

import numpy as np

from sever_db import Database, UserKey, prepare_insert

INPUTS = os.environ.get("SEVER_INPUTS", "/room/inputs")
SMALL_SVP = os.path.join(INPUTS, "p1_partition_small.svp")  # d = 16, 4 frozen groups
BIG_SVP = os.path.join(INPUTS, "partition-seed42.svp")  # d = 384, 128 frozen groups

TOL = 8 * 2.0**-23  # §4.1 step 3 / §2.2: normalisation tolerance
SCALE = 2.0**24  # §4.2: Q24


# ---------------------------------------------------------------- folders, database

def new_root() -> str:
    """A fresh ext4 folder for one test (PROMPT: SEVER_SCRATCH is ext4, /tmp is tmpfs)."""
    return tempfile.mkdtemp(dir=os.environ["SEVER_SCRATCH"])


def new_dirs(root: str | None = None) -> tuple[str, str]:
    """A data directory and a key directory, both empty and both on ext4 (§12.9 allow-list)."""
    root = root or new_root()
    data = os.path.join(root, "data")
    keys = os.path.join(root, "keys")
    os.mkdir(data)
    os.mkdir(keys)
    return data, keys


def open_db(data: str, keys: str, d: int = 16, **kw) -> Database:
    """Open with the development override the test machine needs (PROMPT, §12.8)."""
    kw.setdefault("allow_unsafe_memory", True)
    return Database.open(data, keys, d=d, **kw)


def fs_type(path: str) -> str | None:
    """The filesystem type of the mount holding ``path`` (longest mount-point prefix)."""
    path = os.path.realpath(path)
    best, typ = "", None
    with open("/proc/mounts") as f:
        for line in f:
            parts = line.split()
            mnt = parts[1].replace("\\040", " ")
            if (path == mnt or path.startswith(mnt.rstrip("/") + "/")) and len(mnt) >= len(best):
                best, typ = mnt, parts[2]
    return typ


def rmtree(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------- artefact (§6.3)

@dataclass(frozen=True)
class Artefact:
    d: int
    k: int
    tau: float
    mu: np.ndarray  # k × d, f64
    P: np.ndarray  # d × d, f64
    raw: bytes
    body_len: int  # bytes before sha256_artefact


def parse_svp(path: str) -> Artefact:
    """§6.3 layout, read field by field."""
    b = open(path, "rb").read()
    assert b[:8] == b"SVDBPART"
    _ver, d, k = struct.unpack(">HHH", b[8:14])
    o = 14 + 8  # seed
    tau, _lw = struct.unpack(">dd", b[o : o + 16])
    o += 16 + 8 + 32  # tau, lw_shrinkage, m, sha256_reference
    (el,) = struct.unpack(">H", b[o : o + 2])
    o += 2 + el
    mu = np.frombuffer(b[o : o + 8 * k * d], dtype=">f8").reshape(k, d).astype(np.float64)
    o += 8 * k * d
    P = np.frombuffer(b[o : o + 8 * d * d], dtype=">f8").reshape(d, d).astype(np.float64)
    o += 8 * d * d
    assert hashlib.sha256(b[:o]).digest() == b[o : o + 32] and len(b) == o + 32
    return Artefact(d, k, tau, mu, P, b, o)


_ART: dict[str, Artefact] = {}


def art(path: str = SMALL_SVP) -> Artefact:
    if path not in _ART:
        _ART[path] = parse_svp(path)
    return _ART[path]


# ---------------------------------------------------------------- vector arithmetic (§4, §7, §8)

def norm_ok(x: np.ndarray) -> bool:
    """§4.1 steps 2-3: f64 norm, sequential sum from i = 0, within 8·2^-23 of 1."""
    s = 0.0
    for v in x.astype(np.float64):
        s += float(v) * float(v)
    return abs(math.sqrt(s) - 1.0) <= TOL


def quantise(x: np.ndarray) -> np.ndarray:
    """§4.2: round_half_to_even((f64)x_i · 2^24); np.rint rounds half to even."""
    return np.rint(x.astype(np.float64) * SCALE).astype(np.int64)


def dequant64(x: np.ndarray) -> np.ndarray:
    """§4.3: x̂_i = x̃_i / 2^24 in f64 (exact)."""
    return quantise(x).astype(np.float64) / SCALE


def unit_f32(v: np.ndarray) -> np.ndarray:
    """A float32 vector that passes §4.1 (checked here, not assumed)."""
    x = (v / np.linalg.norm(v)).astype(np.float32)
    assert np.all(np.isfinite(x)) and norm_ok(x)
    return x


def route_frozen(x: np.ndarray, a: Artefact) -> tuple[int, float, float]:
    """§7.1-7.2: (j*, d_M, margin between the two nearest frozen groups' D_j)."""
    xh = dequant64(x)
    D = ((xh - a.mu) ** 2).sum(axis=1)
    order = np.argsort(D, kind="stable")
    j = int(order[0])
    margin = float(D[order[1]] - D[order[0]]) if a.k > 1 else math.inf
    delta = xh - a.mu[j]
    q = float(delta @ a.P @ delta)
    return j, math.sqrt(max(q, 0.0)), margin


def in_dist(j: int, s: int, a: Artefact | None = None, eps: float | None = None) -> np.ndarray:
    """An in-distribution vector of frozen group ``j`` (variant ``s``): the normalised centroid plus
    a small deterministic perturbation. Asserted by hand against §7.1-7.3: nearest frozen group is
    j with a clear margin, and d_M ≤ τ with a clear margin, so the destination is frozen-j."""
    a = a or art()
    eps = 0.04 / math.sqrt(a.d) if eps is None else eps
    rng = np.random.default_rng(1000 * j + s)
    x = unit_f32(a.mu[j] + eps * rng.standard_normal(a.d))
    jj, dm, margin = route_frozen(x, a)
    assert jj == j and margin > 1e-6 and dm < 0.9 * a.tau, (jj, dm, a.tau, margin)
    return x


def ood(s: int, a: Artefact | None = None) -> np.ndarray:
    """An out-of-distribution vector: d_M > τ with a clear margin (§7.2), so with no spawned group it
    goes to the holding area (§7.3, R empty)."""
    a = a or art()
    rng = np.random.default_rng(777_000 + s)
    x = unit_f32(-a.mu[0] + 0.05 * rng.standard_normal(a.d))
    _j, dm, _m = route_frozen(x, a)
    assert dm > 1.5 * a.tau, (dm, a.tau)
    return x


def frozen_id(j: int) -> str:
    """§5.1: frozen-NNNN, 4-digit zero-padded label."""
    return f"frozen-{j:04d}"


def spawn_id(record_ids: list[str]) -> str:
    """§7.5: spawn- + first 16 lowercase hex chars of SHA-256(‖ ascending-by-bytes u16be(len) ‖ id)."""
    h = hashlib.sha256()
    for rid in sorted((r.encode() for r in record_ids)):
        h.update(struct.pack(">H", len(rid)) + rid)
    return "spawn-" + h.hexdigest()[:16]


def kernel_score(q: np.ndarray, x: np.ndarray) -> float:
    """§8.2 pinned kernel in float32: 8 lanes, separate multiply and add, fixed reduction tree.
    x̂ is read as float32 (§4.3: exact when |x̃_i| ≤ 2^24)."""
    q = q.astype(np.float32)
    xh = (quantise(x).astype(np.float64) / SCALE).astype(np.float32)
    L = [np.float32(0.0)] * 8
    for i in range(len(q)):
        t = np.float32(q[i] - xh[i])
        L[i % 8] = np.float32(L[i % 8] + np.float32(t * t))
    r = np.float32(
        np.float32(np.float32(L[0] + L[1]) + np.float32(L[2] + L[3]))
        + np.float32(np.float32(L[4] + L[5]) + np.float32(L[6] + L[7]))
    )
    return float(r)


def insert(db: Database, cid: str, rid: str, x: np.ndarray, user: UserKey, passage: bytes | None = None):
    req = prepare_insert(cid, rid, [float(v) for v in x], user)
    return db.insert(cid, req, passage=passage)


def ids_in(hits) -> list[str]:
    return [h[0] for h in hits]


def total_n(db: Database, cid: str) -> int:
    """N (§2.1): sum of n over frozen and spawned groups (holding area excluded)."""
    return sum(n for _g, n in db.group_sizes(cid))


def sizes(db: Database, cid: str) -> dict[str, int]:
    return dict(db.group_sizes(cid))


# ---------------------------------------------------------------- CRC-32C (§12.7, §14.7)

def _crc_table() -> list[int]:
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x82F63B78 if c & 1 else c >> 1
        t.append(c)
    return t


_T = _crc_table()


def crc32c(data: bytes) -> int:
    c = 0xFFFFFFFF
    for byte in data:
        c = _T[(c ^ byte) & 0xFF] ^ (c >> 8)
    return c ^ 0xFFFFFFFF


assert crc32c(b"123456789") == 0xE3069283  # the CRC-32C check value


# ---------------------------------------------------------------- key file (§14.7)

HDR = 4096
SLOT = 512
PAIR = 1024
SLOT_MAGIC = b"SVKS"


@dataclass(frozen=True)
class KeySlot:
    domain_index: int
    version: int
    key: bytes
    collection_id: bytes
    group_id: str


def keys_path(keys_dir: str) -> str:
    return os.path.join(keys_dir, "KEYS")


def parse_slot(b: bytes) -> KeySlot | None:
    """§14.7 slot: u32be magic ‖ u64be domain_index ‖ u64be key_version ‖ key(32) ‖ collection_id(16)
    ‖ group_id(32) ‖ zero padding ‖ u32be crc32c. None for an absent slot (bad magic or CRC)."""
    assert len(b) == SLOT
    if b[:4] != SLOT_MAGIC:
        return None
    if crc32c(b[:508]) != struct.unpack(">I", b[508:])[0]:
        return None
    di, ver = struct.unpack(">QQ", b[4:20])
    return KeySlot(di, ver, b[20:52], b[52:68], b[68:100].rstrip(b"\0").decode())


def make_slot(domain_index: int, version: int, key: bytes, cid: bytes, group_id: str) -> bytes:
    """Builds a valid §14.7 slot (CRC-32C over the 508 preceding bytes, §14.9 crc rule)."""
    body = (
        SLOT_MAGIC
        + struct.pack(">QQ", domain_index, version)
        + key
        + cid
        + group_id.encode().ljust(32, b"\0")
    ).ljust(508, b"\0")
    return body + struct.pack(">I", crc32c(body))


def read_pairs(keys_dir: str) -> list[tuple[bytes, bytes]]:
    b = open(keys_path(keys_dir), "rb").read()
    n = (len(b) - HDR) // PAIR
    return [(b[HDR + PAIR * i : HDR + PAIR * i + SLOT], b[HDR + PAIR * i + SLOT : HDR + PAIR * (i + 1)]) for i in range(n)]


def active_slots(keys_dir: str) -> dict[tuple[bytes, str], tuple[int, int, KeySlot]]:
    """(collection_id, group_id) → (pair index, slot index 0/1, slot) of every valid slot, after
    asserting the at-rest shape §13.4/§14.7 give once no operation is in flight: one valid slot per
    live pair, the other 512 zero bytes (erased)."""
    out = {}
    for i, (s0, s1) in enumerate(read_pairs(keys_dir)):
        p0, p1 = parse_slot(s0), parse_slot(s1)
        valid = [(si, p) for si, p in ((0, p0), (1, p1)) if p is not None]
        assert len(valid) <= 1, f"pair {i} has two valid slots at rest"
        for si, p in valid:
            other = s1 if si == 0 else s0
            assert other == bytes(SLOT), f"pair {i}: the inactive slot is not erased"
            assert p.domain_index == i, "a slot names its own pair index (§14.7)"
            out[(p.collection_id, p.group_id)] = (i, si, p)
        if not valid:
            assert s0 == bytes(SLOT) and s1 == bytes(SLOT), f"pair {i}: garbage, not erased"
    return out


def assert_keys_well_formed(keys_dir: str) -> None:
    """§14.7: header magic and CRC, length 4,096 + 1,024·pairs, and the at-rest slot shape."""
    b = open(keys_path(keys_dir), "rb").read()
    assert b[:8] == b"SVDBKEYS"
    assert crc32c(b[:4092]) == struct.unpack(">I", b[4092:4096])[0]
    assert (len(b) - HDR) % PAIR == 0
    active_slots(keys_dir)


def write_at(path: str, offset: int, data: bytes) -> None:
    with open(path, "r+b") as f:
        f.seek(offset)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


# ---------------------------------------------------------------- certificate (§11.1)

def parse_cert(c: bytes) -> dict[int, bytes]:
    """§11.1: tags 1…13 in ascending order, each once, u8 tag ‖ u32be length ‖ value; then
    0xFF ‖ u32be 64 ‖ signature; nothing after."""
    o, out = 0, {}
    for tag in range(1, 14):
        assert c[o] == tag
        (ln,) = struct.unpack(">I", c[o + 1 : o + 5])
        out[tag] = c[o + 5 : o + 5 + ln]
        o += 5 + ln
    assert c[o] == 0xFF and struct.unpack(">I", c[o + 1 : o + 5])[0] == 64
    out[0xFF] = c[o + 5 : o + 69]
    assert len(c) == o + 69
    return out


# ---------------------------------------------------------------- byte scanning (§13.2, INV-11)

def all_files(*dirs: str) -> list[str]:
    out = []
    for d in dirs:
        for root, _ds, fs in os.walk(d):
            out += [os.path.join(root, f) for f in fs]
    return out


def files_containing(needle: bytes, *dirs: str, skip: tuple[str, ...] = ()) -> list[str]:
    hits = []
    for p in all_files(*dirs):
        if os.path.basename(p) in skip:
            continue
        try:
            if needle in open(p, "rb").read():
                hits.append(p)
        except OSError:
            pass
    return hits


# ---------------------------------------------------------------- command-line tool (§16.3, Part 4)

CLI = os.environ.get("SEVER_CLI", "sever-db")


def cli_args(cmd: str, data: str, keys: str, *rest: str) -> list[str]:
    return [CLI, cmd, "--data", data, "--keys", keys, *rest, "--allow-unsafe-memory"]


def run_cli(args: list[str], timeout: float = 300) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout)
