"""Tests of the fair-testing system's own rules (docs/FAIR_TESTING.md)."""

import json
import shutil
from pathlib import Path

import pytest

from sever_fair import checks, room, sandbox
from sever_fair.sandbox import Box

ROOT = Path(__file__).resolve().parents[3]


def test_fair_seal_detects_added_changed_and_removed_files(tmp_path: Path) -> None:
    """FT-3: any change to a sealed test is seen."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_a.py").write_text("x = 1\n")
    (tmp_path / "tests/test_b.py").write_text("y = 1\n")
    sealed = checks.seal(tmp_path)
    assert checks.seal_broken(tmp_path, sealed) == []
    (tmp_path / "tests/test_a.py").write_text("x = 2\n")
    (tmp_path / "tests/test_b.py").unlink()
    (tmp_path / "tests/test_c.py").write_text("z = 1\n")
    assert checks.seal_broken(tmp_path, sealed) == [
        "tests/test_a.py",
        "tests/test_b.py",
        "tests/test_c.py",
    ]


def test_fair_sealed_engine_keeps_names_and_raises_on_every_call(tmp_path: Path) -> None:
    """FT-3: the sealed engine has the stub's names and signatures; every call raises."""
    stub = (ROOT / "python/sever_db_p2_native.pyi").read_text()
    pkg = tmp_path / "sever_db_p2_native"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(room.sealed_module(stub))
    import importlib.util

    spec = importlib.util.spec_from_file_location("sealed_native", pkg / "__init__.py")
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert issubclass(mod.DurabilityFailure, mod.SeverError)
    with pytest.raises(mod.EngineSealed):
        mod.Engine.open("d", "k")
    with pytest.raises(mod.EngineSealed):
        mod.Engine.search(object(), "c", [0.0], 3)


def test_fair_junit_reads_outcomes(tmp_path: Path) -> None:
    xml = tmp_path / "j.xml"
    xml.write_text(
        '<testsuites><testsuite><testcase classname="test_a" name="test_ok"/>'
        '<testcase classname="test_a" name="test_bad">'
        '<failure message="boom">tb</failure></testcase>'
        '<testcase classname="test_a" name="test_err"><error message="e"/></testcase>'
        '<testcase classname="test_a" name="test_skip"><skipped message="s"/></testcase>'
        "</testsuite></testsuites>"
    )
    r = checks.junit(xml)
    assert checks.failing(r) == {"test_a::test_bad", "test_a::test_err"}
    assert r["test_a::test_ok"]["outcome"] == "passed"
    assert r["test_a::test_skip"]["outcome"] == "skipped"


def test_fair_finds_labelled_python_and_rust_tests(tmp_path: Path) -> None:
    """FT-7: the audit pool holds every labelled test with its whole source."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_x.py").write_text(
        'import pytest\n\n@pytest.mark.spec("SR-12.3-1", "SR-12.3-2")\ndef test_one():\n'
        "    assert 1 == 1\n\ndef test_unlabelled():\n    pass\n"
    )
    (tmp_path / "crates/c/src").mkdir(parents=True)
    (tmp_path / "crates/c/src/lib.rs").write_text(
        '#[cfg(test)]\nmod tests {\n    #[test]\n    #[spec("SR-14-2")]\n    fn two() {\n'
        "        if true { assert!(true); }\n    }\n}\n"
    )
    found = checks.labelled_tests(tmp_path, {"SR-12.3-2", "SR-14-2"})
    names = {(t["file"], t["name"]) for t in found}
    assert names == {("tests/test_x.py", "test_one"), ("crates/c/src/lib.rs", "two")}
    rust = next(t for t in found if t["name"] == "two")
    assert rust["source"].rstrip().endswith("}")
    assert "assert!(true)" in rust["source"]


def test_fair_test_step_may_change_tests_only() -> None:
    """FT-9 step 1."""
    assert checks.guard_test_change(["tests/e2e/test_new.py", "crates/sever-wal/tests/t.rs"]) == []
    assert checks.guard_test_change(["crates/sever-wal/src/lib.rs"])
    assert checks.guard_test_change(["tests/cleanroom/p2/x/test_a.py"])
    assert checks.guard_test_change(["golden/p2_x.json"])
    frozen = {"crates/sever-wal/src/lib.rs", "tests/e2e/test_p2_e2e.py"}
    assert checks.guard_test_change(["crates/sever-wal/tests/new.rs"], frozen)
    assert checks.guard_test_change(["tests/e2e/test_p2_e2e.py"], frozen)
    assert checks.guard_test_change(["tests/fair/test_p2_new.py"], frozen) == []


def test_fair_fix_step_guards() -> None:
    """FT-9 step 2: no tests, no protected paths, no frozen files, spec only with its gap."""
    assert checks.guard_fix_change(["crates/sever-wal/src/lib.rs"], set()) == []
    assert checks.guard_fix_change(["tests/e2e/test_p2_e2e.py"], set())
    assert checks.guard_fix_change(["configs/fair.yaml"], set())
    assert checks.guard_fix_change(["python/sever_fair/checks.py"], set())
    assert checks.guard_fix_change(
        ["crates/sever-index/src/lib.rs"], {"crates/sever-index/src/lib.rs"}
    )
    assert checks.guard_fix_change([checks.SPEC], set())
    assert checks.guard_fix_change([checks.SPEC, checks.GAPS, checks.OVERVIEW], set()) == []
    assert checks.guard_gap_change([checks.SPEC, checks.GAPS, checks.OVERVIEW]) == []
    assert checks.guard_gap_change([checks.SPEC, checks.GAPS])
    assert checks.guard_gap_change([checks.SPEC, checks.GAPS, checks.OVERVIEW, "crates/a/src/b.rs"])


def test_fair_planted_bugs_stay_in_plant_paths() -> None:
    """FT-6."""
    paths = ["crates/sever-wal/src", "python/sever_db_p2/__init__.py"]
    assert checks.plant_violations(["crates/sever-wal/src/lib.rs"], paths) == []
    assert checks.plant_violations(["python/sever_db_p2/__init__.py"], paths) == []
    assert checks.plant_violations(["crates/sever-index/src/lib.rs"], paths)
    assert checks.plant_violations(["crates/sever-wal/src/tests/a.rs"], paths)
    patch = "--- a/crates/x/src/a.rs\n+++ b/crates/x/src/a.rs\n@@ -1 +1 @@\n-a\n+b\n"
    assert checks.patch_files(patch) == ["crates/x/src/a.rs"]


def test_fair_judge_output_must_cover_every_item_once(tmp_path: Path) -> None:
    """FT-5: a judge's missing, duplicate, unknown or invalid verdicts are problems."""
    p = tmp_path / "v.json"
    p.write_text(
        json.dumps(
            [
                {"test": "a", "verdict": "ENGINE_BUG"},
                {"test": "a", "verdict": "TEST_ERROR"},
                {"test": "c", "verdict": "MAYBE"},
                {"test": "z", "verdict": "SPEC_GAP"},
            ]
        )
    )
    v, problems = checks.verdicts(
        p, "test", {"a", "b", "c"}, {"ENGINE_BUG", "TEST_ERROR", "SPEC_GAP"}
    )
    assert v["a"]["verdict"] == "ENGINE_BUG"
    assert any("a: judged twice" in x for x in problems)
    assert any("b: no verdict" in x for x in problems)
    assert any("c: verdict" in x for x in problems)
    assert any("z: judged but not asked" in x for x in problems)


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="needs bwrap")
def test_fair_canary_sees_room_but_not_repository(tmp_path: Path) -> None:
    """FT-2: inside the sandbox the repository and ~/.claude are absent; a leak is detected."""
    out = tmp_path / "out"
    out.mkdir()
    box = Box().rw(out, "/room/out")
    assert sandbox.canary(box, ROOT, tmp_path / "ok.log")
    leaky = Box().rw(out, "/room/out").ro(ROOT)
    assert not sandbox.canary(leaky, ROOT, tmp_path / "leak.log")
    assert "REACHABLE" in (tmp_path / "leak.log").read_text()


def test_fair_usage_limit_waits_until_the_named_reset() -> None:
    """A usage limit (429) waits for the reset time it names, plus two minutes."""
    import datetime as dt

    from sever_fair.agent import reset_wait

    now = dt.datetime(2026, 10, 8, 16, 33, 40, tzinfo=dt.UTC)
    msg = "You've hit your session limit · resets 4:40pm (UTC)"
    assert reset_wait(msg, now) == (6 * 60 + 20) + 120
    assert reset_wait("resets 9am (UTC)", now) == ((24 - 16 + 9) * 3600 - 33 * 60 - 40) + 120
    assert reset_wait("no time given", now) == 30 * 60


def test_fair_cost_settings_do_not_change_the_fairness_digest() -> None:
    """DB-74: budgets decide when to stop, not what is tested; FT-8 sees every other change."""
    from sever_fair.config import testing_digest

    base = {"models": {"tester": "opus"}, "plant_count": 10, "budget": {"command_usd": 40}}
    cheaper = base | {"budget": {"command_usd": 5}, "on_usage_limit": "wait"}
    fewer_bugs = base | {"plant_count": 5}
    assert testing_digest(base) == testing_digest(cheaper)
    assert testing_digest(base) != testing_digest(fewer_bugs)
