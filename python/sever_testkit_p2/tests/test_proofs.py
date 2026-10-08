"""``proofs`` (CLAUDE.md §6.3): verdicts and the static manifest checks, on a small fake repo."""

from pathlib import Path

from sever_testkit_p2 import oracle_check, proofs

CATALOGUE = """\
- id: SR-14.3-1
  section: "14.3"
  text: "group header"
  kind: table-row
  part: 2
- id: SR-15.1-1
  section: "15.1"
  text: "insert"
  kind: step
  part: 2
"""

RUST = """\
// oracle: A §14.3 by hand
#[spec("SR-14.3-1", "SR-15.1-1")]
fn p2_format_two() {}

// oracle: A §15.1 by hand
#[spec("SR-15.1-1")]
fn p2_format_one() {}

#[test]
fn p2_format_unlabelled() {}
"""


def _repo(tmp_path: Path, manifest: str, patches: tuple[str, ...] = ("a.patch",)) -> Path:
    (tmp_path / "spec").mkdir(parents=True)
    (tmp_path / "spec/requirements.yaml").write_text(CATALOGUE, encoding="utf-8")
    src = tmp_path / "crates/sever-format/src"
    src.mkdir(parents=True)
    (src / "lib.rs").write_text(RUST, encoding="utf-8")
    pdir = tmp_path / "tests/proofs/p2"
    pdir.mkdir(parents=True)
    (pdir / "MANIFEST.yaml").write_text(manifest, encoding="utf-8")
    for p in patches:
        (pdir / p).write_text("", encoding="utf-8")
    return tmp_path


def _entry(pid: str, kind: str, reqs: str, tests: str, patch: str = "a.patch") -> str:
    return (
        f"- id: {pid}\n  claim: c\n  kind: {kind}\n  requirements: [{reqs}]\n"
        f"  patch: {patch}\n  package: sever-format\n  tests: [{tests}]\n"
    )


FULL = (
    _entry("P1", "red", "SR-14.3-1", "p2_format_two")
    + _entry("P2", "red", "SR-15.1-1", "p2_format_two, p2_format_one")
    + _entry("P3", "green", "SR-14.3-1", "p2_format_one")
)


def _check(root: Path) -> tuple[list[str], list[str]]:
    audit = oracle_check.collect(root)
    ps = proofs.load(root)
    return proofs.problems(root, ps, audit), proofs.unproven(ps, audit)


def test_p2_proofs_a_complete_manifest_passes(tmp_path: Path) -> None:
    assert _check(_repo(tmp_path, FULL)) == ([], [])


def test_p2_proofs_every_label_needs_a_red_proof(tmp_path: Path) -> None:
    probs, pairs = _check(_repo(tmp_path, _entry("P1", "red", "SR-14.3-1", "p2_format_two")))
    assert probs == []
    assert pairs == ["lib.rs::p2_format_two: SR-15.1-1", "lib.rs::p2_format_one: SR-15.1-1"]


def test_p2_proofs_a_green_proof_does_not_prove_a_label(tmp_path: Path) -> None:
    # A green proof naming a labelled test is itself a problem, and never counts as coverage.
    m = _entry("P1", "green", "SR-14.3-1", "p2_format_two") + _entry(
        "P2", "red", "SR-15.1-1", "p2_format_two, p2_format_one"
    )
    probs, pairs = _check(_repo(tmp_path, m))
    assert probs == ["P1: green proof for SR-14.3-1, but p2_format_two still labels it"]
    assert pairs == ["lib.rs::p2_format_two: SR-14.3-1"]


def test_p2_proofs_a_red_proof_must_name_tests_with_that_label(tmp_path: Path) -> None:
    probs, _ = _check(_repo(tmp_path, FULL + _entry("P4", "red", "SR-14.3-1", "p2_format_one")))
    assert probs == ["P4: p2_format_one does not label SR-14.3-1"]


def test_p2_proofs_a_green_proof_must_name_tests_without_that_label(tmp_path: Path) -> None:
    probs, _ = _check(_repo(tmp_path, FULL + _entry("P4", "green", "SR-14.3-1", "p2_format_two")))
    assert probs == ["P4: green proof for SR-14.3-1, but p2_format_two still labels it"]


def test_p2_proofs_manifest_problems_are_reported(tmp_path: Path) -> None:
    m = FULL + _entry("P1", "blue", "SR-14.3-1", "p2_format_two", patch="missing.patch")
    probs, _ = _check(_repo(tmp_path, m))
    assert "P1: duplicate ID" in probs
    assert any("kind 'blue'" in p for p in probs)
    assert "P1: patch missing.patch is missing" in probs


def _p(kind: str) -> proofs.Proof:
    return proofs.Proof("P", "c", kind, ["SR-14.3-1"], "a.patch", "cargo", ["lib.rs::t"], "x")


def test_p2_proofs_verdicts() -> None:
    ok, red = {"t": "ok"}, {"t": "FAILED"}
    assert proofs._judge(_p("red"), ok, red, True).ok
    assert not proofs._judge(_p("red"), ok, ok, True).ok, "stayed green"
    assert not proofs._judge(_p("red"), red, red, True).ok, "red without the patch"
    assert not proofs._judge(_p("red"), ok, {}, True).ok, "did not run: compile error"
    assert not proofs._judge(_p("red"), ok, {}, False).ok, "patch does not apply"
    assert proofs._judge(_p("green"), ok, ok, True).ok
    assert not proofs._judge(_p("green"), ok, red, True).ok
    assert proofs._judge(_p("limit"), ok, ok, True).ok
    assert not proofs._judge(_p("limit"), ok, red, True).ok


def test_p2_proofs_a_limit_keeps_the_label_and_does_not_prove_it(tmp_path: Path) -> None:
    m = FULL + _entry("P4", "limit", "SR-14.3-1", "p2_format_two")
    probs, pairs = _check(_repo(tmp_path / "a", m))
    assert probs == []
    assert pairs == []
    only = _entry("P1", "limit", "SR-14.3-1", "p2_format_two")
    _, pairs = _check(_repo(tmp_path / "b", only))
    assert "lib.rs::p2_format_two: SR-14.3-1" in pairs
