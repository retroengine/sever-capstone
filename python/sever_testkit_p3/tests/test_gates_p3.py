"""``gates p3-mutants`` scoring (Build 3-4 §1.9 P3-T9) on hand-written ``outcomes.json`` data."""

import re
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
    # Its sources also compile in golden files from outside it (include_str!, Build §2.2 item 4):
    # on 30 Oct, with the dependency mirrored, the baseline still failed on those.
    (tree / "verifier" / "src").mkdir()
    (tree / "golden").mkdir()
    (tree / "golden" / "g.json").write_text("{}")
    (tree / "verifier" / "src" / "gens.rs").write_text(
        'const G: &str = include_str!("../../golden/g.json");\n'
    )
    scratch.mkdir()
    gates._verifier_scratch(tree, scratch)
    copy = scratch / "cargo-mutants-verifier-xyz"
    assert ((copy / "src" / "../../golden/g.json").resolve()).is_file()
    assert ((copy / "../crates/sever-spec/Cargo.toml").resolve()).is_file()
    assert ((copy / "../crates/sever-spec/src/lib.rs").resolve()).is_file()
    root = (copy / "../Cargo.toml").resolve()
    assert root.is_file()
    assert "[workspace.package]" in root.read_text()
    gates._verifier_scratch_clean(scratch)
    assert not (scratch / "crates").exists()
    assert not (scratch / "golden").exists()
    assert not (scratch / "Cargo.toml").exists()


def test_p3_mutants_sabotage_only_lines_are_excluded(tmp_path: Path) -> None:
    # cargo-mutants also mutates code under #[cfg(feature = "sabotage-SB-N")], which only the
    # sabotage builds compile (Build §2.6): the measured build passes every test with or without
    # the change, so each such mutant is reported missed. On 29 Oct five Part 3 survivors were
    # such lines (builder.rs SB-22, nonce.rs SB-18). The measured build's own code, including a
    # cfg(not(feature = …)) line, stays mutated.
    src = tmp_path / "crates" / "x" / "src"
    src.mkdir(parents=True)
    (src / "a.rs").write_text(
        "fn real() {}\n"  # 1
        '#[cfg(feature = "sabotage-SB-1")]\n'  # 2
        "struct S;\n"  # 3
        '#[cfg(feature = "sabotage-SB-1")]\n'  # 4
        "impl T for S {\n"  # 5
        "    fn f(&self) -> u32 {\n"  # 6
        "        1\n"  # 7
        "    }\n"  # 8
        "}\n"  # 9
        "fn g() {\n"  # 10
        '    #[cfg(not(feature = "sabotage-SB-2"))]\n'  # 11
        "    let a = 1;\n"  # 12
        '    #[cfg(feature = "sabotage-SB-2")]\n'  # 13
        "    let x = {\n"  # 14
        "        1 // { not a brace that counts\n"  # 15
        "    };\n"  # 16
        '    #[cfg(feature = "sabotage-SB-2")]\n'  # 17
        "    return Ok(f(\n"  # 18
        "        x,\n"  # 19
        "    ));\n"  # 20
        "    let b = 2;\n"  # 21
        "}\n"  # 22
    )
    lines = gates.sabotage_lines(tmp_path, ["x"])
    assert lines == {"crates/x/src/a.rs": [3, 5, 6, 7, 8, 9, 14, 15, 16, 18, 19, 20]}
    [rx] = gates.sabotage_excludes(tmp_path, ["x"])
    assert re.match(rx, "crates/x/src/a.rs:7:9: replace S::f -> u32 with 0")
    assert re.match(rx, "crates/x/src/a.rs:20:5: replace f with ()")
    assert not re.match(rx, "crates/x/src/a.rs:12:13: replace 1 with 0")
    assert not re.match(rx, "crates/x/src/a.rs:1:1: replace real with ()")
    assert not re.match(rx, "crates/x/src/a.rs:21:13: replace 2 with 0")
    assert not re.match(rx, "crates/x/src/a.rs:70:1: replace h with ()")
