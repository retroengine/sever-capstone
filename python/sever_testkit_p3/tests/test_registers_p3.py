"""``registers check`` (Part 3) on small fake repositories built from the committed register."""

from pathlib import Path

import yaml

from sever_testkit_p3 import registers

ROOT = Path(__file__).resolve().parents[3]


def _repo(tmp_path: Path, edit: str = "", new: str = "") -> Path:
    (tmp_path / "spec").mkdir(parents=True)
    cat = (ROOT / "spec/requirements.yaml").read_text(encoding="utf-8")
    (tmp_path / "spec/requirements.yaml").write_text(cat, encoding="utf-8")
    reg = (ROOT / registers.REGISTER).read_text(encoding="utf-8")
    if edit:
        assert edit in reg
        reg = reg.replace(edit, new, 1)
    (tmp_path / registers.REGISTER).write_text(reg, encoding="utf-8")
    return tmp_path


def test_p3_registers_the_committed_register_passes() -> None:
    assert registers.problems(ROOT) == []
    reg = yaml.safe_load((ROOT / registers.REGISTER).read_text(encoding="utf-8"))
    assert [e["id"] for e in reg["attacks"] if not e["resign"]] == ["AT-4"]


def test_p3_registers_a_missing_attack_fails(tmp_path: Path) -> None:
    line = '  - {id: AT-20, text: "A log checkpoint'
    root = _repo(tmp_path, line, '  - {id: AT-21, text: "A log checkpoint')
    assert any(p.startswith("attacks: IDs") for p in registers.problems(root))


def test_p3_registers_requirements_must_be_known_part3_ids(tmp_path: Path) -> None:
    root = _repo(tmp_path, "requirements: [SR-11.3-5]}", "requirements: [SR-5.3-1, SR-99-1]}")
    assert registers.problems(root) == [
        "AT-15: SR-5.3-1 is not a Part 3 requirement",
        "AT-15: unknown requirement SR-99-1",
    ]


def test_p3_registers_steps_and_crates_are_checked(tmp_path: Path) -> None:
    root = _repo(tmp_path, "resign: true, steps: [5]", "resign: true, steps: [9]")
    assert registers.problems(root) == ["AT-15: steps [9] are not §11.3 steps 1–8"]
    root2 = _repo(tmp_path / "b", "crate: sever-p3,", "crate: sever-txn,")
    assert registers.problems(root2) == ["SB-21: crate 'sever-txn' is not a Part 3 crate"]
