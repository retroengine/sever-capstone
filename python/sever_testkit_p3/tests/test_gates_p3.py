"""``gates p3-mutants`` scoring (Build 3-4 §1.9 P3-T9) on hand-written ``outcomes.json`` data."""

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
