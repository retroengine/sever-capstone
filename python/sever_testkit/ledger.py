"""The run ledger (overview §13.3; Build §1.3): append-only, written by the harness, never by hand.

Each entry records the date, command, code commit (and whether the tree was dirty), the dataset
manifest hash, the partition artefact hashes, the seeds, a platform report, the outcome and the
SHA-256 of the result file. A run that cannot write its entry does not start: ``start`` writes a
"started" entry before any work, and raises if it cannot.
"""

import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Final

LEDGER: Final = Path("docs/RUN_LEDGER.jsonl")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False
    ).stdout.strip()


def _platform() -> dict[str, Any]:
    flags = ""
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8")
        line = next((ln for ln in cpuinfo.splitlines() if ln.startswith("flags")), "")
        flags = " ".join(f for f in ("avx2", "fma", "aes", "sha_ni", "avx512f") if f" {f}" in line)
    except OSError:
        pass
    swaps = Path("/proc/swaps")
    swap_on = swaps.exists() and len(swaps.read_text(encoding="utf-8").splitlines()) > 1
    return {
        "machine": platform.machine(),
        "kernel": platform.release(),
        "python": platform.python_version(),
        "cpu_flags": flags,
        "swap_on": swap_on,
        "wsl": "microsoft" in platform.release().lower(),
        "allow_unsafe_memory": None,
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(root: Path, command: str, **fields: Any) -> dict[str, Any]:
    """A ledger entry with the provenance fields filled in."""
    manifest = root / "datasets/MANIFEST.sha256"
    return {
        "utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "command": command,
        "commit": _git(root, "rev-parse", "HEAD"),
        # The ledger itself is excluded: a running gate's "started" line is uncommitted by design.
        "git_dirty": bool(_git(root, "status", "--porcelain", "--", ".", f":!{LEDGER}")),
        "dataset_manifest_sha256": _sha(manifest) if manifest.exists() else None,
        "platform": _platform(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        **fields,
    }


def append(root: Path, record: dict[str, Any]) -> None:
    """Appends one line. Raises if the ledger cannot be written (the run must not continue)."""
    path = root / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


def start(root: Path, command: str, **fields: Any) -> dict[str, Any]:
    """Writes the "started" entry before any work (overview §13.3)."""
    rec = entry(root, command, outcome="started", **fields)
    append(root, rec)
    return rec


def result_file(root: Path, name: str, data: dict[str, Any]) -> tuple[Path, str]:
    """Writes a write-once result file under results/ and returns its path and SHA-256."""
    out = root / "results" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise FileExistsError("results/ is write-once")
    out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    return out, _sha(out)
