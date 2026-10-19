"""DB-54 / Build 3-4 §2.8 L13: the ``key-export`` isolation test.

``key-export`` hands every generated key to a sink outside the disk image, for the forensic scanner
only. It must touch exactly one function (key generation), and no measured binary may be built
with it: the engine (``sever-db``), the SDK (``sever-py``) and the measuring harness
(``sever-eval``) resolve ``sever-keys`` without the feature.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MEASURED = ("sever-db", "sever-py", "sever-eval")


@pytest.mark.oracle("A", "DB-54 (overview §6): key-export touches exactly one function")
def test_p4_arch_key_export_is_emitted_from_key_generation_only() -> None:
    src = (ROOT / "crates/sever-keys/src/lib.rs").read_text(encoding="utf-8")
    calls = re.findall(r"export::emit\(", src)
    assert len(calls) == 1
    generate = src[src.index("pub fn generate()") :]
    generate = generate[: generate.index("\n    }\n")]
    assert "export::emit(" in generate
    others = [
        p
        for p in (ROOT / "crates").glob("*/src/**/*.rs")
        if "sever-keys" not in str(p) and "export::emit(" in p.read_text(encoding="utf-8")
    ]
    assert others == []


@pytest.mark.oracle("A", "DB-54 (overview §6): key-export is absent from the measured build")
@pytest.mark.parametrize("package", MEASURED)
def test_p4_arch_measured_builds_resolve_sever_keys_without_key_export(package: str) -> None:
    out = subprocess.run(
        ["cargo", "tree", "-q", "-p", package, "-e", "normal,features", "-i", "sever-keys"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "sever-keys" in out
    assert 'feature "key-export"' not in out
