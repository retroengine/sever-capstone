"""The sabotage lab: plant one deliberate bug, and watch a test catch it (Build §2.6, L12).

Each SB item is the real code built with exactly one bug (the feature ``sabotage-SB-N``; for SB-10,
``SEVER_SABOTAGE=SB-10`` in Python). The item passes when at least one test goes red: a test that
never fails proves nothing (overview §9.2). The list and the crate that owns each item are those of
``tests/sabotage/run.sh``; the wording is the register's (Build §2.6, ``spec/registers_p3.yaml``,
``spec/registers_p4.yaml``).

Proptest saves each failing case under ``crates/<crate>/proptest-regressions/``; a case only a
sabotage build fails is not a regression of the real code, and those files may belong to a frozen
part (F-2), so they are put back exactly as they were, as ``run.sh`` does.
"""

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

P4_TESTS = ["sever-seal", "sever-erasure", "sever-db", "sever-scan"]


@dataclass(frozen=True)
class Item:
    id: str
    text: str
    part: int
    kind: (
        str  # "rust" (feature on the crate), "p4" (feature on the owner, Part 4's tests), "python"
    )
    target: str  # the crate, the owning crate, or the Python test path


ITEMS = [
    Item("SB-1", "Flip one bit of a group sum", 1, "rust", "sever-index"),
    Item("SB-2", "Skip the count decrement on deletion", 1, "rust", "sever-index"),
    Item("SB-3", "Subtract twice on a retried deletion", 1, "rust", "sever-index"),
    Item("SB-4", "Forget the locator update after a slot move", 1, "rust", "sever-index"),
    Item("SB-5", "Keep a deleted vector in the search mirror", 1, "rust", "sever-index"),
    Item("SB-6", "Skip empty groups when filling the probe budget", 1, "rust", "sever-search"),
    Item("SB-7", 'Route to "the most recently created group with room"', 1, "rust", "sever-index"),
    Item(
        "SB-8",
        "Put a vector in the holding area before checking spillover",
        1,
        "rust",
        "sever-index",
    ),
    Item("SB-9", "Enable FMA contraction in the SIMD kernel", 1, "rust", "sever-search"),
    Item(
        "SB-10",
        "Average per-group Ledoit–Wolf fits instead of one pooled fit",
        1,
        "python",
        "python/sever_partition",
    ),
    Item("SB-11", "Accept a WAL record with a bad CRC", 2, "rust", "sever-format"),
    Item("SB-12", "Skip the directory fsync after a rename", 2, "rust", "sever-vfs"),
    Item("SB-13", "Replay an uncommitted transaction", 2, "rust", "sever-wal"),
    Item("SB-14", "Retry a failed fsync", 2, "rust", "sever-vfs"),
    Item("SB-15", "Apply a change to memory before its COMMIT is durable", 2, "rust", "sever-txn"),
    Item("SB-16", "Swap the order of the challenge preimage", 3, "rust", "sever-crypto"),
    Item("SB-17", "Omit the deletion context from the challenge", 3, "rust", "sever-crypto"),
    Item("SB-18", "Reuse a proof nonce", 3, "rust", "sever-crypto"),
    Item("SB-19", "Accept a non-canonical point or scalar", 3, "rust", "sever-crypto"),
    Item("SB-20", "Accept three of five cosignatures", 3, "rust", "sever-log"),
    Item("SB-21", "Issue a certificate for a rolled-back deletion", 3, "rust", "sever-p3"),
    Item("SB-22", "Set group_emptied_by_this_deletion wrongly", 3, "rust", "sever-cert"),
    Item("SB-23", "Reduce the challenge from 32 bytes instead of 64", 3, "rust", "sever-crypto"),
    Item("SB-24", "Skip group-key rotation", 4, "p4", "sever-seal"),
    Item("SB-25", "Skip bucket-key rotation", 4, "p4", "sever-erasure"),
    Item("SB-26", "Skip holding-area rotation on flush", 4, "p4", "sever-erasure"),
    Item("SB-27", "Erase the old key before commit", 4, "p4", "sever-erasure"),
    Item("SB-28", "Write a plaintext vector into the WAL", 4, "p4", "sever-seal"),
    Item("SB-29", "Write an unwrapped key to disk", 4, "p4", "sever-seal"),
    Item("SB-30", "Reuse an AEAD nonce", 4, "p4", "sever-seal"),
]
BY_ID = {i.id: i for i in ITEMS}


@dataclass(frozen=True)
class Outcome:
    id: str
    caught: bool  # at least one test went red
    compiled: bool
    summary: str
    output: str


def command(item: Item) -> tuple[list[str], dict[str, str]]:
    if item.kind == "rust":
        return ["cargo", "test", "-q", "-p", item.target, "--features", f"sabotage-{item.id}"], {}
    if item.kind == "p4":
        cmd = ["cargo", "test", "-q"]
        for c in P4_TESTS:
            cmd += ["-p", c]
        return [*cmd, "--features", f"{item.target}/sabotage-{item.id}"], {}
    pytest = ["uv", "run", "--no-sync", "pytest", "-q", "-p", "no:cacheprovider"]
    return (
        [*pytest, "-m", "not slow and not mustfail", item.target],
        {"SEVER_SABOTAGE": item.id, "PYTHONHASHSEED": "0"},
    )


def run(root: Path, sb: str, on_line: Callable[[str], None] | None = None) -> Outcome:
    """Builds and tests the code with the one planted bug; puts proptest's files back after."""
    item = BY_ID[sb]
    cmd, extra = command(item)
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV",)}
    env.update(extra)
    keep = Path(tempfile.mkdtemp(prefix="sever-sabotage-"))
    crates = sorted(p.name for p in (root / "crates").iterdir() if p.is_dir())
    for c in crates:
        src = root / "crates" / c / "proptest-regressions"
        if src.is_dir():
            shutil.copytree(src, keep / c)
    lines: list[str] = []
    try:
        with subprocess.Popen(
            cmd,
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ) as p:
            assert p.stdout is not None
            for line in p.stdout:
                lines.append(line.rstrip("\n"))
                if on_line:
                    on_line(line.rstrip("\n"))
    finally:
        for c in crates:
            dst = root / "crates" / c / "proptest-regressions"
            shutil.rmtree(dst, ignore_errors=True)
            if (keep / c).is_dir():
                shutil.copytree(keep / c, dst)
        shutil.rmtree(keep, ignore_errors=True)
    out = "\n".join(lines)
    if item.kind == "python":
        failed = [ln for ln in lines if " failed" in ln and ln.strip()[:1].isdigit()]
        caught, compiled = bool(failed), True
        summary = failed[-1] if failed else "every test stayed green"
    else:
        compiled = not any(ln.startswith("error[") or ln == "error" for ln in lines)
        caught = "test result: FAILED" in out
        red = sum(1 for ln in lines if ln.endswith("FAILED") or "--- FAILED" in ln)
        summary = (
            f"{red} failing test line(s)"
            if caught
            else (
                "the sabotage build does not compile" if not compiled else "every test stayed green"
            )
        )
    return Outcome(sb, caught and compiled, compiled, summary, out)
