"""Part 4's spec-trace, oracle-check and proofs (CLAUDE.md §6.3) on small fake repositories: the
Part 4 paths are scanned, earlier parts' are not, missing Part 4 crates hold no tests, and proofs
are looked up in ``tests/proofs/p4/``."""

from pathlib import Path

from sever_testkit_p4 import oracle_check, proofs, spec_trace

CATALOGUE = """\
- id: SR-13.3-1
  section: "13.3"
  text: "rotation rule"
  kind: must
  part: 4
- id: SR-14.7-3
  section: "14.7"
  text: "torn slot"
  kind: must
  part: 4
"""

LABELLED = """\
// oracle: A §14.7 torn slot, by hand
#[spec("SR-14.7-3")]
fn p4_keys_torn_slot_is_absent() {}
"""

UNTAGGED = """\
#[spec("SR-13.3-1")]
fn p4_erasure_untagged() {}
"""


def _repo(tmp_path: Path, files: dict[str, str], manifest: str = "[]\n") -> Path:
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec/requirements.yaml").write_text(CATALOGUE, encoding="utf-8")
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    pdir = tmp_path / "tests/proofs/p4"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "MANIFEST.yaml").write_text(manifest, encoding="utf-8")
    return tmp_path


def _names(root: Path) -> list[str]:
    return sorted(t.name for t in oracle_check.collect(root).tests)


def test_p4_checks_scan_part4_paths_only(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {
            "crates/sever-keys/src/lib.rs": LABELLED,
            "crates/sever-erasure/target/debug/x.rs": LABELLED,  # build output
            "crates/sever-cert/src/lib.rs": LABELLED,  # Part 3's
            "tests/integration/test_p4_scan.py": "",
            "tests/integration/test_p3_log.py": "",
        },
    )
    assert _names(root) == ["lib.rs::p4_keys_torn_slot_is_absent"]
    _, py = oracle_check.part4_files(root)
    assert [p.name for p in py] == ["test_p4_scan.py"]


def test_p4_checks_no_crates_yet_is_no_tests(tmp_path: Path) -> None:
    root = _repo(tmp_path, {})
    a = oracle_check.collect(root)
    assert a.tests == []
    assert a.failures() == []
    assert a.owned == ["SR-13.3-1", "SR-14.7-3"]


def test_p4_oracle_check_fails_an_untagged_test(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"crates/sever-erasure/src/lib.rs": UNTAGGED})
    assert oracle_check.collect(root).failures() != []


def _entry(pid: str, patch: str) -> str:
    return (
        f"- {{id: {pid}, claim: c, kind: red, requirements: [SR-14.7-3], patch: {patch},"
        " tests: [p4_keys_torn_slot_is_absent], package: sever-keys}\n"
    )


def _proof_problems(root: Path) -> tuple[list[str], list[str]]:
    audit = oracle_check.collect(root)
    ps = proofs.load(root)
    return proofs.problems(root, ps, audit), proofs.unproven(list(ps), audit)


def test_p4_proofs_patches_live_in_the_p4_directory(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"crates/sever-keys/src/lib.rs": LABELLED}, _entry("PR4-K01", "a.patch"))
    (root / "tests/proofs/p4/a.patch").write_text("", encoding="utf-8")
    assert _proof_problems(root) == ([], [])
    (root / "tests/proofs/p4/a.patch").unlink()
    (root / "tests/proofs/p3").mkdir()
    (root / "tests/proofs/p3/a.patch").write_text("", encoding="utf-8")  # the wrong part's
    assert _proof_problems(root)[0] == ["PR4-K01: patch a.patch is missing"]


def test_p4_proofs_every_label_needs_a_red_proof(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"crates/sever-keys/src/lib.rs": LABELLED})
    assert _proof_problems(root) == ([], ["lib.rs::p4_keys_torn_slot_is_absent: SR-14.7-3"])


def test_p4_proofs_ids_are_part4_ids(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"crates/sever-keys/src/lib.rs": LABELLED}, _entry("PR3-K01", "a.patch"))
    (root / "tests/proofs/p4/a.patch").write_text("", encoding="utf-8")
    assert _proof_problems(root)[0] == ["PR3-K01: a Part 4 proof ID starts with PR4-"]


SPLIT = """\
// oracle: A §14.7 torn slot, by hand
#[spec(
    "SR-14.7-3",
    "SR-13.3-1"
)]
fn p4_keys_split_attribute() {}
"""


def test_p4_spec_trace_refuses_a_split_attribute(tmp_path: Path) -> None:
    # The frozen tracer, oracle check and proofs check read one line at a time (BH-1): a split
    # attribute's labels are invisible to all three, so the check refuses it outside frozen files.
    root = _repo(tmp_path, {"crates/sever-keys/src/lib.rs": SPLIT})
    assert spec_trace.split_attributes(root) == ["crates/sever-keys/src/lib.rs:2"]
    assert spec_trace.main(["check", "--part", "4", "--root", str(root)]) == 1
    (root / "freeze").mkdir()
    (root / "freeze/PART-2.sha256").write_text(
        "0" * 64 + "  crates/sever-keys/src/lib.rs\n", encoding="utf-8"
    )
    assert spec_trace.split_attributes(root) == []  # a frozen file cannot be changed
