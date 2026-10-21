"""The programs a user runs next to the database, and the plaintext check of its disk.

``sever-verify`` (``verifier/``) and ``sever-audit`` (``audit/``) are separate workspaces that share
no code with the engine (spec §16.3): whoever receives a certificate checks it with them, offline,
with no access to the database. ``sever-db`` is the command-line tool of the final build.
"""

import os
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

Needles = dict[str, list[bytes]]


@dataclass(frozen=True)
class Tools:
    verify: Path
    audit: Path
    cli: Path


def _cargo(args: Sequence[str], cwd: Path, target: Path) -> None:
    env = {**os.environ, "CARGO_TARGET_DIR": str(target)}
    subprocess.run(["cargo", *args], cwd=cwd, check=True, env=env)


def build(root: Path, cli: bool = False) -> Tools:
    """Builds whatever is missing (release, ``--locked``: the versions in the lock files)."""
    t = Tools(
        verify=root / "verifier/target/release/sever-verify",
        audit=root / "audit/target/release/sever-audit",
        cli=root / "target/release/sever-db",
    )
    for ws, binary in (("verifier", t.verify), ("audit", t.audit)):
        if not binary.exists():
            _cargo(["build", "-q", "--release", "--locked"], root / ws, root / ws / "target")
    if cli and not t.cli.exists():
        _cargo(["build", "-q", "--release", "--locked", "-p", "sever-db"], root, root / "target")
    return t


def run(args: Sequence[str | Path], cwd: Path) -> tuple[int, str]:
    p = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True, check=False)
    return p.returncode, (p.stdout + p.stderr).strip()


def files_under(dirs: Iterable[Path]) -> list[Path]:
    return sorted(p for d in dirs for p in d.rglob("*") if p.is_file())


def count_hits(files: Sequence[Path], needles: Needles) -> dict[str, tuple[int, int]]:
    """``kind → (found, looked for)``: how many needles of each kind occur anywhere in ``files``
    (a raw byte search, as a thief with a copy of the disk would run)."""
    blobs = [f.read_bytes() for f in files]
    return {
        kind: (sum(1 for n in found if any(n in b for b in blobs)), len(found))
        for kind, found in needles.items()
    }


def write_naive(
    naive: Path, ids: Sequence[str], texts: Sequence[str], vectors: Sequence[bytes]
) -> None:
    """The naive copy: the same records as a usual store keeps them, in the clear: each record's
    ID and passage as raw UTF-8 bytes (not JSON, whose escapes would hide some of them from the
    byte search)."""
    naive.mkdir(exist_ok=True)
    with (naive / "records.txt").open("w", encoding="utf-8", newline="") as f:
        for r, t in zip(ids, texts, strict=True):
            f.write(f"{r}\t{t}\n")
    (naive / "vectors.f32").write_bytes(b"".join(vectors))


def needles_of(ids: Sequence[str], texts: Sequence[str], vectors: Sequence[bytes]) -> Needles:
    """What to look for: each record's ID, two 32-byte windows of its passage text, and the
    first 32 bytes of its float32 vector."""
    windows: list[bytes] = []
    for t in texts:
        b = t.encode("utf-8")
        windows += [b[:32], b[len(b) // 2 : len(b) // 2 + 32]]
    return {
        "record IDs": [i.encode("utf-8") for i in ids],
        "passage text": [w for w in windows if len(w) >= 16],
        "vectors": [v[:32] for v in vectors],
    }
