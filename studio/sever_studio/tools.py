"""The programs Studio runs beside the database, and the raw search of its disk.

``sever-verify`` (``verifier/``) and ``sever-audit`` (``audit/``) are separate workspaces that share
no code with the engine (§16.3): whoever holds a certificate checks it with them, offline, with no
access to the database.
"""

import os
import re
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

Needles = dict[str, list[bytes]]


@dataclass(frozen=True)
class Tools:
    verify: Path
    audit: Path


def _cargo(args: Sequence[str], cwd: Path, target: Path) -> None:
    env = {**os.environ, "CARGO_TARGET_DIR": str(target)}
    subprocess.run(["cargo", *args], cwd=cwd, check=True, env=env)


def build(root: Path) -> Tools:
    """Builds whichever checker is missing (release, ``--locked``)."""
    t = Tools(
        verify=root / "verifier/target/release/sever-verify",
        audit=root / "audit/target/release/sever-audit",
    )
    for ws, binary in (("verifier", t.verify), ("audit", t.audit)):
        if not binary.exists():
            _cargo(["build", "-q", "--release", "--locked"], root / ws, root / ws / "target")
    return t


def run(args: Sequence[str | Path], cwd: Path, timeout: float | None = None) -> tuple[int, str]:
    p = subprocess.run(
        [str(a) for a in args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    return p.returncode, (p.stdout + p.stderr).strip()


@dataclass(frozen=True)
class Step:
    """One step of ``sever-verify --explain`` (§11.3): its number, what it checks, its verdict."""

    number: int
    checks: str
    verdict: str  # "ok", "n/a (group)", "FAILED: ...", "not reached"

    @property
    def state(self) -> str:
        if self.verdict == "ok":
            return "ok"
        if self.verdict.startswith("FAILED"):
            return "fail"
        return "skip"


_STEP = re.compile(r"^step (\d+)\s+(.*?)\s{2,}(\S.*)$")


def explain_steps(output: str) -> tuple[list[Step], str]:
    """The steps, and the final line (``ACCEPT`` or ``REJECT (step N: reason)``)."""
    steps, verdict = [], ""
    for line in output.splitlines():
        m = _STEP.match(line.strip())
        if m:
            steps.append(Step(int(m[1]), m[2].strip(), m[3].strip()))
        elif line.startswith(("ACCEPT", "REJECT")):
            verdict = line.strip()
    return steps, verdict


def files_under(dirs: Iterable[Path]) -> list[Path]:
    return sorted(p for d in dirs if d.exists() for p in d.rglob("*") if p.is_file())


def count_hits(files: Sequence[Path], needles: Needles) -> dict[str, tuple[int, int]]:
    """``kind -> (found, looked for)``: a raw byte search, as a thief with a copy of the disk
    would run, over every file."""
    blobs = [f.read_bytes() for f in files]
    return {
        kind: (sum(1 for n in found if any(n in b for b in blobs)), len(found))
        for kind, found in needles.items()
    }


def needles_of(ids: Sequence[str], texts: Sequence[str], vectors: Sequence[bytes]) -> Needles:
    """Each record's ID, two 32-byte windows of its text, and the first 32 bytes of its float32
    vector."""
    windows: list[bytes] = []
    for t in texts:
        b = t.encode("utf-8")
        windows += [b[:32], b[len(b) // 2 : len(b) // 2 + 32]]
    return {
        "record IDs": [i.encode("utf-8") for i in ids],
        "passage text": [w for w in windows if len(w) >= 16],
        "vectors": [v[:32] for v in vectors],
    }


def write_naive(
    where: Path, ids: Sequence[str], texts: Sequence[str], vecs: Sequence[bytes]
) -> None:
    """The same records as an ordinary store keeps them: ID and text as raw UTF-8, vectors as
    float32 bytes."""
    where.mkdir(parents=True, exist_ok=True)
    with (where / "records.txt").open("w", encoding="utf-8", newline="") as f:
        for r, t in zip(ids, texts, strict=True):
            f.write(f"{r}\t{t}\n")
    (where / "vectors.f32").write_bytes(b"".join(vecs))
