"""L13 architecture tests of Part 3 (Build 3-4 §1.6, §1.8 L13; spec §9.1, §20.1)."""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Spec §9.1 and §20.1: the primitive crates and their pinned versions, typed from the tables.
PRIMITIVES = {
    "curve25519-dalek": "4.1.3",
    "ed25519-dalek": "2.2.0",
    "merlin": "3.0.0",
    "sha2": "0.10.9",
    "hmac": "0.12.1",
}
#: Support crates §20.1 also pins, which implement no primitive of their own.
SUPPORT = {"rand_core": "0.6.4", "zeroize": "1.9.0"}


def lock_versions() -> dict[str, set[str]]:
    lock = tomllib.loads((ROOT / "Cargo.lock").read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for p in lock["package"]:
        out.setdefault(p["name"], set()).add(p["version"])
    return out


@pytest.mark.spec("SR-9.1-1")
@pytest.mark.oracle("A", "§9.1 primitive table and §20.1 pinned versions, typed by hand")
def test_p3_arch_crypto_uses_only_the_pinned_primitives() -> None:
    manifest = tomllib.loads((ROOT / "crates/sever-crypto/Cargo.toml").read_text(encoding="utf-8"))
    deps = manifest["dependencies"]
    allowed = PRIMITIVES | SUPPORT
    assert set(deps) <= set(allowed), f"not in §9.1/§20.1: {set(deps) - set(allowed)}"
    for name, spec in deps.items():
        version = spec if isinstance(spec, str) else spec["version"]
        assert version == f"={allowed[name]}", f"{name} {version}: §20.1 pins ={allowed[name]}"
    locked = lock_versions()
    for name in deps:
        assert locked[name] == {allowed[name]}, f"{name} resolves to {locked[name]}"
    # §9.1: no primitive is implemented by the project except expand_message_xmd (DB-52).
    src = "\n".join(
        p.read_text(encoding="utf-8") for p in (ROOT / "crates/sever-crypto/src").glob("*.rs")
    )
    own = set(re.findall(r"\bimpl\s+(?:\w+::)*(Digest|Mac|BlockCipher|Aead)\s+for\b", src))
    assert own == set(), f"a primitive trait is implemented in sever-crypto: {own}"
