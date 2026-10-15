"""Part 3's spec-trace, oracle-check and proofs (CLAUDE.md §6.3) on small fake repositories: the
Part 3 paths are scanned (the separate workspaces included), Part 2's are not, and proofs are
looked up in ``tests/proofs/p3/``."""

from pathlib import Path

from sever_testkit_p3 import oracle_check, proofs, spec_trace

CATALOGUE = """\
- id: SR-9.5-1
  section: "9.5"
  text: "proof of knowledge"
  kind: must
  part: 3
- id: SR-11.3-1
  section: "11.3"
  text: "verification algorithm"
  kind: step
  part: 3
"""

LABELLED = """\
// oracle: A §11.3 step 1, by hand
#[spec("SR-11.3-1")]
fn p3_verify_step_one() {}
"""

UNTAGGED = """\
#[spec("SR-9.5-1")]
fn p3_crypto_untagged() {}
"""


def _repo(tmp_path: Path, files: dict[str, str], manifest: str = "[]\n") -> Path:
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec/requirements.yaml").write_text(CATALOGUE, encoding="utf-8")
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    pdir = tmp_path / "tests/proofs/p3"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "MANIFEST.yaml").write_text(manifest, encoding="utf-8")
    for d in ("crates", "python"):
        (tmp_path / d).mkdir(exist_ok=True)
    return tmp_path


def _names(root: Path) -> list[str]:
    return sorted(t.name for t in oracle_check.collect(root).tests)


def test_p3_checks_scan_the_separate_workspaces(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {
            "verifier/sever-verify/src/lib.rs": LABELLED,
            "audit/src/main.rs": LABELLED.replace("p3_verify", "p3_audit"),
        },
    )
    assert _names(root) == ["lib.rs::p3_verify_step_one", "main.rs::p3_audit_step_one"]
    tr = spec_trace.collect(root)
    assert sorted(tr.tests["SR-11.3-1"]) == [
        "lib.rs::p3_verify_step_one",
        "main.rs::p3_audit_step_one",
    ]


def test_p3_checks_skip_build_output(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"verifier/target/debug/build/x/out/gen.rs": UNTAGGED})
    assert _names(root) == []
    assert not spec_trace.collect(root).tests


def test_p3_checks_ignore_part2_paths_and_pick_p3_test_files(tmp_path: Path) -> None:
    # Split so that the frozen spec-trace, which reads this file line by line, sees no mark here.
    py = "@pytest.mark." + 'spec("SR-9.5-1")\ndef test_x() -> None: ...\n'
    root = _repo(
        tmp_path,
        {
            "crates/sever-format/src/lib.rs": UNTAGGED,  # Part 2: not Part 3's to check
            "tests/e2e/test_p2_e2e.py": "import pytest\n" + py,
            "tests/e2e/test_p3_receipt.py": "import pytest\n" + py,
            "tests/spec/test_certificate_p3.py": "import pytest\n" + py,
        },
    )
    assert _names(root) == ["test_certificate_p3.py::test_x", "test_p3_receipt.py::test_x"]


def test_p3_oracle_check_fails_an_untagged_verifier_test(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"verifier/src/lib.rs": UNTAGGED})
    fails = oracle_check.collect(root).failures()
    assert fails == ["lib.rs::p3_crypto_untagged: no oracle declared"]


def test_p3_spec_trace_reports_unknown_ids_in_the_verifier(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"verifier/src/lib.rs": '#[spec("SR-99.9-9")]\nfn p3_x() {}\n'})
    assert spec_trace.collect(root).unknown == [("SR-99.9-9", "lib.rs::p3_x")]


def _entry(pid: str, patch: str, workspace: str = "verifier") -> str:
    return (
        f"- id: {pid}\n  claim: c\n  kind: red\n  requirements: [SR-11.3-1]\n"
        f"  patch: {patch}\n  package: sever-verify\n  workspace: {workspace}\n"
        "  tests: [p3_verify_step_one]\n"
    )


def _proof_problems(root: Path) -> tuple[list[str], list[str]]:
    audit = oracle_check.collect(root)
    ps = proofs.load(root)
    return proofs.problems(root, ps, audit), proofs.unproven(list(ps), audit)


def test_p3_proofs_patches_live_in_the_p3_directory(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"verifier/src/lib.rs": LABELLED}, _entry("PR-1", "a.patch"))
    (root / "tests/proofs/p3/a.patch").write_text("", encoding="utf-8")
    assert _proof_problems(root) == ([], [])
    (root / "tests/proofs/p3/a.patch").unlink()
    (root / "tests/proofs/p2").mkdir()
    (root / "tests/proofs/p2/a.patch").write_text("", encoding="utf-8")  # the wrong part's
    assert _proof_problems(root)[0] == ["PR-1: patch a.patch is missing"]


def test_p3_proofs_every_label_needs_a_red_proof(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"verifier/src/lib.rs": LABELLED})
    assert _proof_problems(root) == ([], ["lib.rs::p3_verify_step_one: SR-11.3-1"])


def test_p3_proofs_reject_an_unknown_workspace(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"verifier/src/lib.rs": LABELLED}, _entry("PR-1", "a.patch", "engine"))
    (root / "tests/proofs/p3/a.patch").write_text("", encoding="utf-8")
    assert _proof_problems(root)[0] == [
        "PR-1: workspace 'engine' is not one of ('', 'verifier', 'audit')"
    ]
