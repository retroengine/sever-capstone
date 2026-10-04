"""Write certificates to disk and check them with the independent verifier, run as its own process.

The verifier (python/sever_verify) is never imported here: it runs as `python -m sever_verify`
in its own process, as an outsider would run it on the files (spec §11.3: no database access).
Certificates and anchors are public data; nothing secret is written.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]


def write_receipts(folder: Path, anchors: dict[str, Any], certificates: list[bytes]) -> list[Path]:
    """Writes anchors.json and one <lsn>.cert per certificate (lsn = position in `certificates`)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "anchors.json").write_text(json.dumps(anchors, indent=1), encoding="utf-8")
    paths = []
    for lsn, data in enumerate(certificates):
        path = folder / f"{lsn:06d}.cert"
        if not path.exists():
            path.write_bytes(data)
        paths.append(path)
    return paths


def run_verifier(anchors: Path, certs: list[Path]) -> tuple[dict[str, bool], str]:
    """Runs the verifier in a separate process. Returns ({file name: accepted}, its output)."""
    env = {**os.environ, "PYTHONPATH": str(REPO / "python")}
    cmd = [sys.executable, "-m", "sever_verify", str(anchors), *(str(c) for c in certs)]
    done = subprocess.run(
        cmd, env=env, cwd=anchors.parent, capture_output=True, text=True, check=False
    )
    if done.returncode not in (0, 1):
        raise RuntimeError(f"verifier failed to run: {done.stderr.strip()[-300:]}")
    if len(certs) == 1:
        accepted = {certs[0].name: done.stdout.strip().endswith("ACCEPTED")}
    else:
        accepted = {}
        for line in done.stdout.splitlines():
            name, _, verdict = line.partition(": ")
            if verdict:
                accepted[name] = verdict.startswith("ACCEPTED")
    return accepted, done.stdout


def tampered_copy(src: Path, dst: Path, position: int) -> Path:
    """A copy of a certificate with one bit flipped at `position` (a forged or damaged receipt)."""
    data = bytearray(src.read_bytes())
    data[position % len(data)] ^= 0x01
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(bytes(data))
    return dst
