"""L13 architecture tests of Part 2 (Build §5.7 L13; spec §12.2, §12.7).

Every storage file operation goes through the ``Vfs`` (so ``SimVfs`` can crash it), nothing is
written through ``mmap``, the engine uses Part 1 only through its public API, and the Part 1 freeze
manifest is unchanged (P2-T10).
"""

import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Crates whose file I/O must go through `sever_vfs::Vfs`. Allowed exceptions, by file: the engine's
#: platform module (statfs and the ENGINE.lock flock, §12.9), which touch no data.
STORAGE = ("sever-format", "sever-wal", "sever-appendstore", "sever-checkpoint", "sever-txn",
           "sever-engine")  # fmt: skip
DIRECT_IO_ALLOWED = {"crates/sever-engine/src/platform.rs"}
DIRECT_IO = re.compile(r"\bstd::fs\b|\bFile::|\bOpenOptions::new\b|\bstd::os::unix::fs\b")


def code_lines(path: Path) -> list[tuple[int, str]]:
    return [
        (n, line.split("//", 1)[0])
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
    ]


def engine_lines(path: Path) -> list[tuple[int, str]]:
    """``code_lines`` without ``#[cfg(test)]`` items: test-only code is not compiled into the
    engine, so §12.2's rule (the engine's reads and writes go through the ``Vfs``) does not cover
    it (for example, the fuzz-seed writer in sever-format's tests)."""
    out: list[tuple[int, str]] = []
    skip_next_item, depth = False, 0
    raw = path.read_text(encoding="utf-8").splitlines()
    for (n, code), line in zip(code_lines(path), raw, strict=True):
        # Braces are counted on the raw line: `code` cuts at the first "//", even inside a string.
        if depth > 0:
            depth += line.count("{") - line.count("}")
            continue
        if code.strip() == "#[cfg(test)]":
            skip_next_item = True
            continue
        if skip_next_item and code.strip() and not code.strip().startswith("#["):
            skip_next_item = False
            depth = line.count("{") - line.count("}")
            continue
        out.append((n, code))
    return out


@pytest.mark.spec("SR-12.2-1")
@pytest.mark.parametrize("crate", STORAGE)
def test_p2_arch_storage_io_goes_through_the_vfs(crate: str) -> None:
    hits = []
    for p in sorted((ROOT / "crates" / crate / "src").rglob("*.rs")):
        rel = str(p.relative_to(ROOT))
        if rel in DIRECT_IO_ALLOWED or "tests" in p.name:
            continue
        hits += [f"{rel}:{n}" for n, code in engine_lines(p) if DIRECT_IO.search(code)]
    assert not hits, hits


@pytest.mark.spec("SR-12.7-3")
def test_p2_arch_no_writes_through_mmap() -> None:
    lock = (ROOT / "Cargo.lock").read_text(encoding="utf-8")
    assert not re.search(r'^name = "(memmap|memmap2|mmap.*)"$', lock, re.MULTILINE)
    hits = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "crates").rglob("*.rs")
        if re.search(r"\bmmap\b", "\n".join(c for _, c in code_lines(p)))
    ]
    assert not hits, hits


def test_p2_arch_engine_uses_part1_through_its_public_api() -> None:
    # Rust privacy enforces the API boundary; this guards against bypasses (`#[path]` includes of
    # Part 1 sources, `include!` of their files).
    for crate in (*STORAGE, "sever-crashkit", "sever-p2"):
        for p in (ROOT / "crates" / crate).rglob("*.rs"):
            text = "\n".join(c for _, c in code_lines(p))
            assert "#[path" not in text, p
            assert "include!(" not in text, p


def test_p2_arch_part1_freeze_manifest_is_unchanged() -> None:
    manifest = ROOT / "freeze/PART-1.sha256"
    bad = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, path = line.split(maxsplit=1)
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
            bad.append(path)
    assert not bad, f"frozen Part 1 files changed: {bad}"
