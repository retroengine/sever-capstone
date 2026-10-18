"""``registers check`` (Part 4) on small fake repositories built from the committed register."""

from pathlib import Path

import yaml

from sever_testkit_p4 import registers

ROOT = Path(__file__).resolve().parents[3]


def _repo(tmp_path: Path, edit: str = "", new: str = "") -> Path:
    (tmp_path / "spec").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    for rel in ("spec/requirements.yaml", str(registers.GAPS)):
        (tmp_path / rel).write_text((ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")
    reg = (ROOT / registers.REGISTER).read_text(encoding="utf-8")
    if edit:
        assert edit in reg
        reg = reg.replace(edit, new, 1)
    (tmp_path / registers.REGISTER).write_text(reg, encoding="utf-8")
    return tmp_path


def test_p4_registers_the_committed_register_passes() -> None:
    assert registers.problems(ROOT) == []
    reg = yaml.safe_load((ROOT / registers.REGISTER).read_text(encoding="utf-8"))
    # Build 3-4 §2.8: SB-27 is a durability fault, not a leak; every other item leaves a finding.
    assert [e["id"] for e in reg["sabotage"] if not e["scanner"]] == ["SB-27"]
    # Spec §15.4 has five rows.
    assert len(reg["crash"]) == 5


def test_p4_registers_a_missing_sabotage_item_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path, "  - {id: SB-30,", "  - {id: SB-31,")
    assert any(p.startswith("sabotage: IDs") for p in registers.problems(root))


def test_p4_registers_requirements_and_gaps_are_checked(tmp_path: Path) -> None:
    root = _repo(tmp_path, "requirements: [SR-15.4-6]}", "requirements: [SR-5.3-1, SR-99-1]}")
    assert registers.problems(root) == [
        "CT-5: unknown requirement SR-99-1",
        "CT-5: names no Part 4 requirement",
    ]
    root2 = _repo(tmp_path / "b", "gap: G-27}", "gap: G-99}")
    assert registers.problems(root2) == ["KF-5: gap 'G-99' is not in docs/SPEC_GAPS.md"]


def test_p4_registers_crates_flags_and_expectations_are_checked(tmp_path: Path) -> None:
    sb30 = "crate: sever-seal, requirements: [SR-13.2-1]"
    root = _repo(tmp_path, sb30, sb30.replace("sever-seal", "sever-txn"))
    assert registers.problems(root) == ["SB-30: crate 'sever-txn' is not a Part 4 crate"]
    pl11 = "expect: start, requirements: [SR-12.9-3]}"
    root2 = _repo(tmp_path / "b", pl11, pl11.replace("start", "maybe"))
    assert registers.problems(root2) == ["PL-11: expect must be one of ('refuse', 'start')"]
    pl5 = "expect: refuse, flag: allow_unsafe_fs, requirements: [SR-12.9-1,"
    root3 = _repo(tmp_path / "c", pl5, pl5.replace("allow_unsafe_fs", "allow_anything"))
    assert registers.problems(root3) == [
        "PL-5: flag 'allow_anything' is not one of ('allow_unsafe_memory', 'allow_unsafe_fs')"
    ]
