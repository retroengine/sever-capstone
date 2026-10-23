"""The four live demonstrations, as plain functions (the window only draws them).

- ``climb``: a receipt's insert leaf climbs the RFC 9162 Merkle tree to the signed root. Studio
  parses the certificate itself (§11.1–11.2) and recomputes every hash with its own code, written
  from RFC 9162 §2.1.3.2; it shares nothing with the engine or ``sever-verify``.
- ``attacks``: forgery attempts on a receipt, each judged by ``sever-verify``.
- ``crash_delete``: one person's deletion, killed with SIGKILL part-way; after recovery all of their
  records are gone or none are (§12.5).
- ``race``: a model of the arithmetic of §4–5. The same vectors are removed and put back again and
  again: a float32 running mean drifts, the Q24 integer sum stays bit-identical.
"""

import hashlib
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from . import tools

# -- §11.1 – 11.2: the certificate, parsed again from the spec ------------------------------------

INSERT_LEAF = (
    209  # §10.2: 0x01 ‖ collection_id 16 ‖ scrambled_id 64 ‖ C_t 32 ‖ user key 32 ‖ signature 64
)
USER_KEY = slice(1 + 16 + 64 + 32, 1 + 16 + 64 + 32 + 32)


class CertificateError(ValueError):
    """Not a certificate as §11.1 defines one."""


@dataclass
class Certificate:
    tags: dict[int, bytes]
    leaf: bytes
    leaf_index: int
    tree_size: int
    root: bytes
    path: list[bytes]
    witnesses: int

    @property
    def user_key(self) -> bytes:
        return self.leaf[USER_KEY]

    @property
    def database_lsn(self) -> int:
        return int.from_bytes(self.tags[10], "big")

    @property
    def from_holding(self) -> bool:
        return self.tags[12] == b"\x01"


def parse(cert: bytes) -> Certificate:
    """Tags 1 … 13 in order, each ``u8 tag ‖ u32be length ‖ value``, then the 0xFF trailer."""
    tags: dict[int, bytes] = {}
    at = 0
    for want in [*range(1, 14), 0xFF]:
        if at + 5 > len(cert):
            raise CertificateError(f"cut off before tag {want}")
        tag, length = cert[at], int.from_bytes(cert[at + 1 : at + 5], "big")
        if tag != want:
            raise CertificateError(f"tag {tag} where {want} belongs")
        tags[tag] = cert[at + 5 : at + 5 + length]
        if len(tags[tag]) != length:
            raise CertificateError(f"tag {tag} is cut off")
        at += 5 + length
    if at != len(cert):
        raise CertificateError("bytes after the trailer")
    inc = tags[6]
    if not inc or inc[0] != 1:
        raise CertificateError("tag 6 is not version 1")
    leaf = inc[1 : 1 + INSERT_LEAF]
    p = 1 + INSERT_LEAF
    leaf_index = int.from_bytes(inc[p : p + 8], "big")
    tree_size = int.from_bytes(inc[p + 8 : p + 16], "big")
    root = inc[p + 16 : p + 48]
    p += 8 + 116  # leaf_index, then the 116-byte log checkpoint
    count = inc[p]
    path = [inc[p + 1 + 32 * i : p + 33 + 32 * i] for i in range(count)]
    if p + 1 + 32 * count != len(inc):
        raise CertificateError("tag 6 has the wrong length")
    return Certificate(tags, leaf, leaf_index, tree_size, root, path, tags[7][0] if tags[7] else 0)


# -- RFC 9162 §2.1.3.2: verifying an inclusion proof ----------------------------------------------


@dataclass(frozen=True)
class Step:
    sibling: bytes
    sibling_left: bool  # the path hash is the left child
    result: bytes


def leaf_hash(leaf: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + leaf).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def climb(leaf: bytes, index: int, size: int, path: list[bytes]) -> tuple[list[Step], bytes, bool]:
    """The steps from the leaf to the root, the root reached, and whether the walk was valid."""
    if index >= size:
        return [], b"", False
    fn, sn = index, size - 1
    r = leaf_hash(leaf)
    steps: list[Step] = []
    for p in path:
        if sn == 0:
            return steps, r, False
        if fn & 1 or fn == sn:
            r = node_hash(p, r)
            steps.append(Step(p, True, r))
            if not fn & 1:
                while fn and not fn & 1:
                    fn >>= 1
                    sn >>= 1
        else:
            r = node_hash(r, p)
            steps.append(Step(p, False, r))
        fn >>= 1
        sn >>= 1
    return steps, r, sn == 0


# -- attacks --------------------------------------------------------------------------------------


@dataclass
class Attack:
    name: str
    did: str
    expect: str
    verdict: str = ""
    caught: bool = False
    by: str = ""


def _verify(root: Path, folder: Path, cert: bytes, anchors: str) -> tuple[int, str, str]:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "certificate.bin").write_bytes(cert)
    (folder / "anchors.json").write_text(anchors, "utf-8")
    t = tools.build(root)
    code, out = tools.run(
        [t.verify, "certificate.bin", "--anchors", "anchors.json", "--explain"], folder
    )
    steps, verdict = tools.explain_steps(out)
    del steps
    return code, verdict, out


def attacks(
    root: Path,
    work: Path,
    cert: bytes,
    anchors: str,
    claimant_key: bytes | None,
    other: bytes | None,
) -> list[Attack]:
    """Each attack forges or bends the receipt, or the trust anchors, in one way. ``claimant_key``
    is the public key of the person holding the receipt; ``other`` is someone else's receipt."""
    lab = work / "attack-lab"
    shutil.rmtree(lab, ignore_errors=True)
    a = json.loads(anchors)
    out: list[Attack] = []

    def run(att: Attack, folder: str, c: bytes, anc: str, step: str) -> None:
        code, verdict, _ = _verify(root, lab / folder, c, anc)
        att.verdict = verdict or f"exit {code}"
        att.caught = code == 1 and verdict.startswith(f"REJECT (step {step}")
        att.by = f"sever-verify, step {step}" if att.caught else "not caught"
        out.append(att)

    flipped = bytearray(cert)
    flipped[len(cert) // 3] ^= 0x01
    run(
        Attack(
            "Change one byte",
            "flipped one bit in the middle of the receipt",
            "rejected: every byte is signed",
        ),
        "flip",
        bytes(flipped),
        anchors,
        "2",
    )
    run(
        Attack("Cut it short", "kept only the first two thirds", "rejected: it does not parse"),
        "cut",
        cert[: len(cert) * 2 // 3],
        anchors,
        "1",
    )
    weak = json.loads(anchors)
    for w in range(2, len(weak["witnesses"])):
        weak["witnesses"][w] = {}
    run(
        Attack(
            "Bribe the witnesses",
            "only 2 witnesses' keys are trusted, as if the others had colluded",
            "rejected: needs 4 independent witnesses",
        ),
        "witnesses",
        cert,
        json.dumps(weak),
        "4",
    )
    fake = json.loads(anchors)
    witness_key = next(iter(a["witnesses"][0].values()))
    fake["operator"] = {e: witness_key for e in fake["operator"]}
    run(
        Attack(
            "Another operator",
            "checked with a different operator's key, as a receipt from another service would be",
            "rejected: not signed by this operator",
        ),
        "operator",
        cert,
        json.dumps(fake),
        "2",
    )
    if other is not None and claimant_key is not None:
        att = Attack(
            "Someone else's receipt",
            "handed over a real receipt that belongs to another account",
            "valid, but the key inside is not yours",
        )
        code, verdict, _ = _verify(root, lab / "other", other, anchors)
        theirs = parse(other).user_key
        att.verdict = (
            f"{verdict}; the leaf's key {'is' if theirs == claimant_key else 'is not'} yours"
        )
        att.caught = code == 0 and theirs != claimant_key
        att.by = "your own key check" if att.caught else "not caught"
        out.append(att)
    return out


# -- a deletion killed part-way -------------------------------------------------------------------


@dataclass
class CrashDelete:
    account: str
    records: int
    planned_ms: float
    killed: bool
    deleted: int
    outcome: str  # "none", "all", "partial" (a violation), "finished first"
    took_ms: float | None = None  # how long the whole deletion took, when it finished first


def kill_verdict(outcomes: list[str]) -> tuple[bool | None, str]:
    """What a series of killed deletions showed (§12.5): only runs the kill landed in count; a
    half deletion is a failure; "all" needs a kill after the commit point."""
    killed = [o for o in outcomes if o in ("none", "all", "partial")]
    if not killed:
        return None, "no kill landed: every deletion finished first. Run it again."
    if "partial" in killed:
        return False, f"{killed.count('partial')} of {len(killed)} kills left a half deletion"
    n = f"{len(killed)} kill{'s' if len(killed) != 1 else ''}"
    if "all" not in killed:
        return True, (
            f"{n}, each before the commit point: none deleted, never half. A kill after it is "
            "Part 2's proof (Proof tab)."
        )
    if "none" not in killed:
        return True, f"{n}, each after the commit point: all deleted, never half"
    return True, f"{n}: before the commit point none, after it all; never half"


def crash_delete(studio: Any, ids: list[str], account: str, kill_after_ms: float) -> CrashDelete:
    """A second process deletes ``ids`` in one transaction (``delete_user``) and is killed with
    SIGKILL ``kill_after_ms`` after it starts. Recovery; then the engine's log says, record by
    record, which of them went: all of them or none (§12.5)."""
    b = studio.backend
    lsns = {rid: b.index.records[rid].lsn for rid in ids if rid in b.index.records}
    b.close()
    marks = studio.work / "crash-delete"
    shutil.rmtree(marks, ignore_errors=True)
    marks.mkdir(parents=True)
    (marks / "ids.json").write_text(json.dumps(ids), "utf-8")
    paths = [str(studio.root / "python"), str(Path(__file__).resolve().parents[1])]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(paths)}
    cmd = [sys.executable, "-m", "sever_studio", "delete-child", "--data", studio.data]
    cmd += [
        "--rows",
        str(studio.rows),
        "--work",
        str(studio.work),
        "--ids",
        str(marks / "ids.json"),
    ]
    cmd += ["--dev"] if b.dev else []
    child = subprocess.Popen(cmd, cwd=studio.root, env=env)
    deadline = time.monotonic() + 120
    while not (marks / "begin").exists() and child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.002)
    time.sleep(max(0.0, kill_after_ms) / 1000)
    if child.poll() is None:
        os.kill(child.pid, signal.SIGKILL)
    killed = child.wait() == -signal.SIGKILL
    finished = (marks / "done").exists()
    b.open()
    live = b.replay().groups
    deleted = [rid for rid, lsn in lsns.items() if lsn not in live]
    for rid in deleted:
        rec = b.index.records.pop(rid)
        if rec.group == "holding":
            b.index.holding.remove(rid)
    b.save()
    gone = len(deleted)
    if finished:
        outcome = "finished first"
    elif gone == 0:
        outcome = "none"
    elif gone == len(ids):
        outcome = "all"
    else:
        outcome = "partial"
    took = float((marks / "done").read_text("utf-8")) if finished else None
    return CrashDelete(
        account, len(ids), kill_after_ms, killed and not finished, gone, outcome, took
    )


def delete_child(studio: Any, ids_file: Path) -> int:
    """The process that is killed: it marks the start, deletes, and marks the end."""
    ids = json.loads(ids_file.read_text("utf-8"))
    b = studio.backend
    b.open()
    marks = ids_file.parent
    (marks / "begin").write_text("1", "utf-8")
    t0 = time.perf_counter()
    b.live.delete_user(b.cid, ids)
    (marks / "done").write_text(f"{(time.perf_counter() - t0) * 1000:.1f}", "utf-8")
    b.close()
    return 0


# -- the race: float32 running mean against the Q24 integer sum (§4.2, §5) ------------------------


@dataclass
class RaceResult:
    cycles: int
    float_error: list[tuple[int, float]] = field(default_factory=list)
    integer_error: list[tuple[int, float]] = field(default_factory=list)
    differing: list[tuple[int, int]] = field(default_factory=list)
    identical: bool = True


def quantise(x: npt.NDArray[np.float32]) -> npt.NDArray[np.int64]:
    """§4.2: x̃ = round(x · 2^24), ties to even, as integers (summed as i64)."""
    return np.rint(x.astype(np.float64) * (1 << 24)).astype(np.int64)


def race(
    vectors: npt.NDArray[np.float32],
    cycles: int,
    every: int = 100,
    seed: int = 42,
) -> Iterator[tuple[int, float, float, int, bool]]:
    """Removes a member and puts it back, ``cycles`` times. Yields every ``every`` cycles: the
    cycle, the float32 running mean's largest error against the true mean, the integer sum's (0
    when bit-identical), how many of the mean's numbers no longer equal their starting bits, and
    whether the integer sum equals the one it started from. The members never change, so a
    correct summary would never change either."""
    x = vectors.astype(np.float32)
    n = len(x)
    truth = x.astype(np.float64).mean(axis=0)
    mean = np.zeros(x.shape[1], np.float32)
    for k in range(n):  # the running mean as an incremental index keeps it
        mean = mean + (x[k] - mean) / np.float32(k + 1)
    start = mean.copy()
    s0 = quantise(x).sum(axis=0)
    s = s0.copy()
    rng = random.Random(seed)  # the order of the cycles only
    q = quantise(x)
    for c in range(1, cycles + 1):
        i = rng.randrange(n)
        mean = (mean * np.float32(n) - x[i]) / np.float32(n - 1)
        s = s - q[i]
        mean = mean + (x[i] - mean) / np.float32(n)
        s = s + q[i]
        if c % every == 0 or c == cycles:
            ferr = float(np.abs(mean.astype(np.float64) - truth).max())
            ierr = float(np.abs(s - s0).max())
            yield c, ferr, ierr, int((mean != start).sum()), bool(np.array_equal(s, s0))


def race_all(
    vectors: npt.NDArray[np.float32], cycles: int, report: Callable[..., None] | None = None
) -> RaceResult:
    out = RaceResult(cycles)
    for c, ferr, ierr, diff, same in race(vectors, cycles):
        out.float_error.append((c, ferr))
        out.integer_error.append((c, ierr))
        out.differing.append((c, diff))
        out.identical = out.identical and same
        if report:
            report(c, ferr, ierr, diff, same)
    return out
