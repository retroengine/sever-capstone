"""Spec §20.1 for Part 4: the AEAD crate is pinned, and the lockfile holds one version of each
crate family the cryptography depends on (two copies of a CSPRNG or a curve would be two sources
of truth)."""

import re
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _lock() -> dict[str, list[str]]:
    text = (ROOT / "Cargo.lock").read_text(encoding="utf-8")
    out: dict[str, list[str]] = defaultdict(list)
    for name, version in re.findall(
        r'\[\[package\]\]\nname = "([^"]+)"\nversion = "([^"]+)"', text
    ):
        out[name].append(version)
    return out


@pytest.mark.spec("SR-20.1-1")
@pytest.mark.oracle("A", "§20.1 aes-gcm-siv 0.11.1 (aead 0.5, the rand_core 0.6 family)")
def test_p4_arch_the_aead_crate_is_pinned_with_one_copy_of_each_family() -> None:
    lock = _lock()
    assert lock["aes-gcm-siv"] == ["0.11.1"]
    assert len(lock["aead"]) == 1
    assert lock["aead"][0].startswith("0.5.")
    assert len(lock["rand_core"]) == 1
    assert lock["rand_core"][0].startswith("0.6.")
    for family in ("digest", "getrandom", "curve25519-dalek"):
        assert len(lock[family]) == 1, (family, lock[family])
