"""``gates p3-mutants`` scoring (Build 3-4 §1.9 P3-T9) on hand-written ``outcomes.json`` data."""

from pathlib import Path
from typing import Any

from sever_testkit_p3 import gates


def _o(package: str, summary: str, name: str = "src/a.rs:1:1: replace x with y") -> dict[str, Any]:
    return {"scenario": {"Mutant": {"name": name, "package": package}}, "summary": summary}


def _out(*outcomes: dict[str, Any]) -> dict[str, Any]:
    return {"outcomes": [{"scenario": "Baseline", "summary": "Success"}, *outcomes]}


def test_p3_mutants_scores_each_crate_against_its_own_minimum() -> None:
    # sever-crypto: 9 caught of 10 = 90 % (minimum 90 %); sever-log: 4 of 5 = 80 % (minimum 85 %).
    data = _out(
        *[_o("sever-crypto", "CaughtMutant")] * 9,
        _o("sever-crypto", "MissedMutant"),
        _o("sever-crypto", "Unviable"),
        *[_o("sever-log", "CaughtMutant")] * 4,
        _o("sever-log", "Timeout"),
        *[_o("sever-cert", "CaughtMutant")] * 3,
    )
    by = {s.unit: s for s in gates.score(data, dict(gates.P3_MUTATED))}
    assert (by["sever-crypto"].score, by["sever-crypto"].ok) == (0.9, True)
    assert by["sever-crypto"].unviable == 1
    assert (by["sever-log"].score, by["sever-log"].ok) == (0.8, False)
    assert by["sever-cert"].ok


def test_p3_mutants_a_crate_without_mutants_fails() -> None:
    data = _out(_o("sever-crypto", "CaughtMutant"), _o("sever-log", "CaughtMutant"))
    by = {s.unit: s for s in gates.score(data, dict(gates.P3_MUTATED))}
    assert not by["sever-cert"].ok


def test_p3_mutants_the_verifier_is_one_unit() -> None:
    data = _out(
        *[_o("sever-verify", "CaughtMutant")] * 8,
        _o("sever-verify-tlv", "CaughtMutant"),
        _o("sever-verify-tlv", "MissedMutant"),
    )
    [s] = gates.score(data, {gates.VERIFIER: gates.VERIFIER_MIN}, unit=gates.VERIFIER)
    assert (s.unit, s.caught, s.missed, s.ok) == ("verifier", 9, 1, True)


def test_p3_mutants_survivors_need_triage() -> None:
    data = _out(
        _o("sever-verify", "MissedMutant", "src/v.rs:3:9: replace == with != in check"),
        _o("sever-verify", "Timeout", "src/v.rs:7:1: replace f -> bool with true"),
        _o("sever-verify", "CaughtMutant", "src/v.rs:9:1: replace g with ()"),
    )
    missed = gates.survivors(data, prefix="verifier/")
    assert missed == [
        "verifier/src/v.rs:3:9: replace == with !=",
        "verifier/src/v.rs:7:1: replace f -> bool with true",
    ]
    triage = "- `verifier/src/v.rs:3:9: replace == with !=` equivalent: …"
    assert gates.untriaged(missed, triage) == ["verifier/src/v.rs:7:1: replace f -> bool with true"]


def test_p3_mutants_the_verifier_copy_finds_its_path_dependencies(tmp_path: Path) -> None:
    # cargo-mutants copies only verifier/ into its scratch folder (scratch/<copy>/), so the
    # verifier's dev-dependency `../crates/sever-spec` resolves to scratch/crates/sever-spec, and
    # that crate inherits `edition.workspace = true` from the root manifest above it. On 29 Oct
    # (the v1.0 laptop run) neither was there: the baseline build failed, 0 verifier mutants ran.
    tree, scratch = tmp_path / "tree", tmp_path / "scratch"
    (tree / "verifier").mkdir(parents=True)
    (tree / "crates" / "sever-spec" / "src").mkdir(parents=True)
    (tree / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["crates/*"]\n[workspace.package]\nedition = "2024"\n'
    )
    (tree / "crates" / "sever-spec" / "Cargo.toml").write_text(
        '[package]\nname = "sever-spec"\nedition.workspace = true\n'
    )
    (tree / "crates" / "sever-spec" / "src" / "lib.rs").write_text("")
    (tree / "verifier" / "Cargo.toml").write_text(
        '[package]\nname = "sever-verify"\n[workspace]\n'
        '[dev-dependencies]\nsever-spec = { path = "../crates/sever-spec" }\n'
    )
    scratch.mkdir()
    gates._verifier_scratch(tree, scratch)
    copy = scratch / "cargo-mutants-verifier-xyz"
    assert ((copy / "../crates/sever-spec/Cargo.toml").resolve()).is_file()
    assert ((copy / "../crates/sever-spec/src/lib.rs").resolve()).is_file()
    root = (copy / "../Cargo.toml").resolve()
    assert root.is_file()
    assert "[workspace.package]" in root.read_text()
    gates._verifier_scratch_clean(scratch)
    assert not (scratch / "crates").exists()
    assert not (scratch / "Cargo.toml").exists()
