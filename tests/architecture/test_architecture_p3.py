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


#: Build 3-4 §1.4: the verifier's own primitives (spec §9.1, §20.1) and the JSON reader of its
#: anchors and bundled golden files; nothing else, and nothing of the engine.
VERIFIER_DEPS = {k: PRIMITIVES[k] for k in ("curve25519-dalek", "ed25519-dalek", "sha2")}


@pytest.mark.spec("SR-9.2-4")
@pytest.mark.oracle(
    "A",
    "§9.2 'The verifier (C-16) performs the same checks with its own code'; Build 3-4 §1.4 "
    "'verifier/ (separate workspace) … its own parser, generator derivation, proof check'",
)
def test_p3_arch_verifier_shares_no_code_with_the_engine() -> None:
    manifest = tomllib.loads((ROOT / "verifier/Cargo.toml").read_text(encoding="utf-8"))
    assert "workspace" in manifest, "verifier/ is its own workspace"
    deps = manifest["dependencies"]
    assert set(deps) == {*VERIFIER_DEPS, "serde_json"}, set(deps)
    for name, pin in VERIFIER_DEPS.items():
        assert deps[name] == f"={pin}", f"{name}: §20.1 pins ={pin}"
    # Test labels only: the #[spec] attribute (Build §2.2) holds no verification code (DB-85).
    assert set(manifest.get("dev-dependencies", {})) <= {"sever-spec"}
    lock = tomllib.loads((ROOT / "verifier/Cargo.lock").read_text(encoding="utf-8"))
    names = {p["name"] for p in lock["package"]}
    engine = {p.name for p in (ROOT / "crates").iterdir()} - {"sever-spec"}
    assert not names & engine, f"the verifier links engine crates: {names & engine}"
    for p in (ROOT / "verifier/src").rglob("*.rs"):
        used = set(re.findall(r"\b(sever_\w+)::", p.read_text(encoding="utf-8")))
        assert used <= {"sever_verify", "sever_spec"}, f"{p.name}: {used}"


#: The verifier's files the auditor copies (Build 3-4 §1.4: "Reuses verifier code by copying it").
COPIED = ("anchors", "cert", "dst", "gens", "hex", "merkle", "posk", "verify", "xmd")


@pytest.mark.spec("SR-11.3-10")
@pytest.mark.oracle(
    "A",
    "Build 3-4 §1.4 'audit/ (separate crate) … Reuses verifier code by copying it, not by a path "
    "dependency'; §11.3 the auditor (C-17) checks what a certificate cannot",
)
def test_p3_arch_auditor_copies_the_verifier_and_depends_on_neither() -> None:
    manifest = tomllib.loads((ROOT / "audit/Cargo.toml").read_text(encoding="utf-8"))
    assert "workspace" in manifest, "audit/ is its own workspace"
    assert set(manifest["dependencies"]) == {*VERIFIER_DEPS, "serde_json"}
    assert set(manifest.get("dev-dependencies", {})) <= {"sever-spec"}
    for name in COPIED:
        mine = (ROOT / "audit/src" / f"{name}.rs").read_bytes()
        assert mine == (ROOT / "verifier/src" / f"{name}.rs").read_bytes(), f"{name}.rs drifted"
    lock = tomllib.loads((ROOT / "audit/Cargo.lock").read_text(encoding="utf-8"))
    names = {p["name"] for p in lock["package"]}
    engine = {p.name for p in (ROOT / "crates").iterdir()} - {"sever-spec"}
    assert not names & (engine | {"sever-verify"}), names & (engine | {"sever-verify"})
    for p in (ROOT / "audit/src").rglob("*.rs"):
        used = set(re.findall(r"\b(sever_\w+)::", p.read_text(encoding="utf-8")))
        assert used <= {"sever_audit", "sever_spec"}, f"{p.name}: {used}"
