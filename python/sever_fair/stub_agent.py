"""Offline stand-in for a session (dry runs only): fixed, simple outputs for each role.

Runs inside the same sandbox as a real session, so a dry run exercises every mount, the canary, the
seal, the measured run, the scoring and the report, with no model and no credential.
"""

import json
import sys
from pathlib import Path

CONFTEST = """import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "req(ids): requirement IDs")
"""

TESTS = '''"""Stub clean-room tests (dry run): one should pass, one is wrong on purpose."""
import os
import tempfile
from pathlib import Path

import pytest

from sever_db_p2 import Database


def _dirs():
    root = tempfile.mkdtemp(dir=os.environ["SEVER_SCRATCH"])
    return Path(root, "data"), Path(root, "keys")


def _unit(d, i):
    v = [0.0] * d
    v[i % d] = 1.0
    return v


@pytest.mark.req("SR-15.1-1")
def test_stub_insert_then_delete_leaves_no_member():
    """§5: deleting the only record leaves every group empty (stub)."""
    data, keys = _dirs()
    with Database.open(data, keys) as db:
        cid = db.create_collection(Path(os.environ["SEVER_INPUTS"], "p1_partition_small.svp"),
                                   spawn_target=8)
        db.insert(cid, "a", _unit(16, 0))
        assert db.delete(cid, "a") == "deleted"
        assert sum(n for _, n in db.group_sizes(cid)) == 0


def test_stub_wrong_on_purpose():
    """A deliberately wrong expectation, so the dry run has a failure to triage."""
    data, keys = _dirs()
    with Database.open(data, keys) as db:
        assert db.collections() == ["no-such-collection"]
'''


def main() -> None:
    role = sys.argv[1]
    out = Path("/room/out")
    if role == "tester":
        tests = Path("/room/work/tests")
        (tests / "conftest.py").write_text(CONFTEST)
        (tests / "test_stub.py").write_text(TESTS)
        Path("/room/work/NOTES.md").write_text("Stub run: no notes.\n")
    elif role == "triage":
        fails = json.loads((out / "failures.json").read_text())
        verdicts = [
            {
                "test": f["test"],
                "verdict": "TEST_ERROR",
                "section": "§16.2",
                "reason": "Stub verdict.",
            }
            for f in fails
        ]
        (out / "triage.json").write_text(json.dumps(verdicts, indent=1))
    elif role == "planter":
        bugs = out / "bugs"
        bugs.mkdir(exist_ok=True)
        target = Path("/src/crates/sever-wal/src/lib.rs")
        old = target.read_text()
        target.write_text(old + "// stub plant: a comment only, an equivalent mutant\n")
        import subprocess

        diff = subprocess.run(["git", "-C", "/src", "diff"], capture_output=True, text=True).stdout
        target.write_text(old)
        (bugs / "01.patch").write_text(diff)
        (bugs / "01.json").write_text(
            json.dumps(
                {
                    "id": "01",
                    "files": ["crates/sever-wal/src/lib.rs"],
                    "section": "§12.3",
                    "requirement": None,
                    "behaviour": "none (stub)",
                    "why": "stub",
                }
            )
        )
        (bugs / "02.patch").write_text("this is not a patch\n")
        (bugs / "02.json").write_text(
            json.dumps(
                {
                    "id": "02",
                    "files": [],
                    "section": "§12.3",
                    "requirement": None,
                    "behaviour": "does not apply (stub)",
                    "why": "stub",
                }
            )
        )
    elif role == "escape":
        esc = json.loads((out / "escapes.json").read_text())
        (out / "escape_verdicts.json").write_text(
            json.dumps(
                [
                    {"id": e["id"], "verdict": "EQUIVALENT", "section": "§12.3", "reason": "Stub."}
                    for e in esc
                ]
            )
        )
    elif role == "oracle":
        files = sorted(p.name for p in (out / "audit").glob("*.txt"))
        (out / "oracle.json").write_text(
            json.dumps(
                [{"file": f, "verdict": "AGREE", "section": "§0", "reason": "Stub."} for f in files]
            )
        )
    # fix roles: the stub changes nothing, so the guards hand the finding to the owner.


if __name__ == "__main__":
    main()
