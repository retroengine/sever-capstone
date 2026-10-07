"""``oracle_check`` (CLAUDE.md §6.3) on small fake repositories."""

from pathlib import Path

from sever_testkit_p2 import oracle_check

CATALOGUE = """\
- id: SR-14.3-1
  section: "14.3"
  text: "segment header"
  kind: table-row
  part: 2
- id: SR-15.1-1
  section: "15.1"
  text: "open"
  kind: must
  part: 2
"""


def _repo(tmp_path: Path, rust: str, py: str = "") -> Path:
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec/requirements.yaml").write_text(CATALOGUE, encoding="utf-8")
    src = tmp_path / "crates/sever-format/src"
    src.mkdir(parents=True)
    (src / "lib.rs").write_text(rust, encoding="utf-8")
    e2e = tmp_path / "tests/e2e"
    e2e.mkdir(parents=True)
    (e2e / "test_x.py").write_text(py, encoding="utf-8")
    return tmp_path


GOOD_RUST = """\
#[test]
// oracle: A §14.3 segment header, bytes by hand
#[spec("SR-14.3-1")]
fn p2_format_header_bytes() {}

// oracle: D round trip
#[spec("SR-14.3-1")]
#[test]
fn p2_format_header_round_trip() {}
"""

# Built by concatenation so that neither scanner (this one, spec_trace) reads the fixture as a test.
M = "@pytest.mark."
GOOD_PY = f"""\
{M}spec("SR-15.1-1")
{M}oracle("B", "sever_refmodel_core traces")
def test_p2_open():
    pass
"""


def test_p2_oracle_check_passes_a_correctly_tagged_repo(tmp_path: Path) -> None:
    a = oracle_check.collect(_repo(tmp_path, GOOD_RUST, GOOD_PY))
    assert a.failures() == []
    assert len(a.tests) == 3
    assert [k for k, _ in a.tests[0].oracles] == ["A"]


def test_p2_oracle_check_fails_an_untagged_labelled_test(tmp_path: Path) -> None:
    rust = GOOD_RUST + '#[spec("SR-15.1-1")]\nfn p2_untagged() {}\n'
    fails = oracle_check.collect(_repo(tmp_path, rust, GOOD_PY)).failures()
    assert fails == ["lib.rs::p2_untagged: no oracle declared"]


def test_p2_oracle_check_ignores_unlabelled_tests(tmp_path: Path) -> None:
    rust = GOOD_RUST + "#[test]\nfn p2_helper_test() {}\n"
    assert oracle_check.collect(_repo(tmp_path, rust, GOOD_PY)).failures() == []


def test_p2_oracle_check_fails_a_requirement_resting_on_d_alone(tmp_path: Path) -> None:
    rust = GOOD_RUST.replace("oracle: A §14.3 segment header, bytes by hand", "oracle: D echo")
    a = oracle_check.collect(_repo(tmp_path, rust, GOOD_PY))
    assert a.d_only() == ["SR-14.3-1"]
    assert len(a.failures()) == 1
    assert a.failures()[0].startswith("SR-14.3-1: checked only by D")


def test_p2_oracle_check_fails_an_a_oracle_without_a_section(tmp_path: Path) -> None:
    rust = GOOD_RUST.replace("A §14.3 segment header", "A segment header")
    fails = oracle_check.collect(_repo(tmp_path, rust, GOOD_PY)).failures()
    assert len(fails) == 1
    assert "names no § or Appendix" in fails[0]


def test_p2_oracle_check_accepts_an_appendix_source(tmp_path: Path) -> None:
    rust = GOOD_RUST.replace("A §14.3 segment header", "A Appendix A derived sizes")
    assert oracle_check.collect(_repo(tmp_path, rust, GOOD_PY)).failures() == []


def test_p2_oracle_check_fails_unknown_and_sourceless_oracles(tmp_path: Path) -> None:
    py = GOOD_PY.replace('"B", "sever_refmodel_core traces"', '"B"')
    rust = GOOD_RUST.replace("// oracle: D round trip", "// oracle: E round trip")
    fails = oracle_check.collect(_repo(tmp_path, rust, py)).failures()
    assert any("unknown oracle 'E'" in f for f in fails)
    assert any("oracle B names no source" in f for f in fails)


def test_p2_oracle_check_fails_a_malformed_python_mark(tmp_path: Path) -> None:
    py = GOOD_PY.replace('.oracle("B", "sever_refmodel_core traces")', ".oracle(B)")
    fails = oracle_check.collect(_repo(tmp_path, GOOD_RUST, py)).failures()
    assert any("malformed oracle mark" in f for f in fails)


def test_p2_oracle_check_report_lists_b_shared_tests(tmp_path: Path) -> None:
    py = GOOD_PY.replace('"B", "sever_refmodel_core', '"B-shared", "sever_refmodel_durable')
    md = oracle_check.report(oracle_check.collect(_repo(tmp_path, GOOD_RUST, py)))
    shared = md.split("## B-shared")[1].split("## Tests")[0]
    assert "test_x.py::test_p2_open" in shared
    assert "| SR-14.3-1 | 1 | 0 | 0 | 0 | 1 | ok |" in md
