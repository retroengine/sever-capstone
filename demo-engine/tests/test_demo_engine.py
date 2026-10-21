"""The demo's own tests: every entry point runs offline on the golden fixture and its checks pass.

These are smoke tests of the demo, not of the engine (the engine's tests are under ``tests/`` and in
each crate). Each run uses its own directory under ``demo-engine/work/`` (ext4; §12.9 refuses
tmpfs).
"""

import fcntl
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from sever_tour import tools

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
ENV = {**os.environ, "PYTHONHASHSEED": "0", "PYTHONPATH": f"{ROOT / 'python'}:{HERE}"}


def run(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=timeout, check=False
    )


def fresh(name: str) -> Path:
    work = HERE / "work" / name
    shutil.rmtree(work, ignore_errors=True)
    return work


def test_the_tour_passes_every_check() -> None:
    work = fresh("test-tour")
    p = run([sys.executable, "-m", "sever_tour", "tour", "--data", "synthetic", "--dev",
             "--work", str(work)])  # fmt: skip
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-2000:]
    report = json.loads((work / "report.json").read_text("utf-8"))
    assert len(report["checks"]) >= 24
    assert all(c["ok"] for c in report["checks"])
    assert report["numbers"]["crash_killed"] is True
    assert report["numbers"]["crash_lost"] == 0


def test_the_shell_runs_a_whole_session() -> None:
    work = fresh("test-shell")
    script = (
        "load 30; ask 0; questions vector; accounts; forget account-1; receipts; verify; tamper;"
        " delete rec-000; delete rec-000; show rec-002; show rec-001; disk; stats; log; restart;"
        " crash; audit; quit"
    )
    p = run([sys.executable, "-m", "sever_tour", "shell", "--data", "synthetic", "--dev",
             "--work", str(work), "-c", script])  # fmt: skip
    out = p.stdout
    assert p.returncode == 0, out[-3000:] + p.stderr[-2000:]
    assert "error:" not in out, out
    assert "ACCEPT" in out
    assert '"accepted":false' in out
    assert "\nabsent\n" in out
    assert "acknowledged but missing: 0" in out
    assert '"findings":[]' in out
    assert "0 of 40 found in the clear" in out or "found in the clear" in out


def test_the_examples_run() -> None:
    fresh("quickstart")
    fresh("backend")
    q = run([sys.executable, str(HERE / "examples/quickstart.py")])
    assert q.returncode == 0, q.stdout + q.stderr
    assert "delete again: absent" in q.stdout
    assert '"accepted":true' in q.stdout
    b = run([sys.executable, str(HERE / "examples/backend.py")])
    assert b.returncode == 0, b.stdout + b.stderr
    assert "refused: DuplicateRecord" in b.stdout
    assert "bob's note-1 now: []" in b.stdout
    assert b.stdout.count(": accepted") == 3
    assert "REJECTED" not in b.stdout


def test_the_command_line_tour_runs() -> None:
    p = run(["bash", str(HERE / "cli-tour.sh")])
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-2000:]
    assert p.stdout.count('"accepted":true') == 6
    assert "(exit 1: rejected)" in p.stdout
    assert '{"outcome":"absent"}' in p.stdout
    assert '"findings":[]' in p.stdout


def test_a_work_directory_in_use_is_refused_before_anything_is_wiped() -> None:
    """Two tours on one work directory (20 Oct 2026): the second wiped the first one's open
    database. A run takes the lock beside its work directory first, and refuses if it is held."""
    work = fresh("test-in-use")
    work.mkdir(parents=True)
    (work / "kept").write_text("the first run's files", "utf-8")
    fd = os.open(work.parent / f".{work.name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for cmd in (["tour"], ["shell", "-c", "quit"]):
            p = run([sys.executable, "-m", "sever_tour", cmd[0], "--data", "synthetic", "--dev",
                     "--work", str(work), *cmd[1:]], timeout=120)  # fmt: skip
            assert p.returncode == 2, p.stdout[-2000:] + p.stderr[-2000:]
            assert "in use" in p.stdout
            assert (work / "kept").exists()
    finally:
        os.close(fd)


def test_the_naive_copy_holds_every_passage_byte_for_byte(tmp_path: Path) -> None:
    """Chapter 5 searches the naive copy for 32-byte windows of each passage; a passage with a
    quote, a backslash or a newline must still be found (the copy was JSON, which escapes them)."""
    ids = ["rec-a", "rec-b"]
    texts = [
        '"Quoted" at the start, a back\\slash in the middle of this passage, and more',
        "A first line that is long enough\nand a second line after the newline, long enough",
    ]
    vecs = [np.arange(16, dtype="<f4").tobytes(), np.ones(16, dtype="<f4").tobytes()]
    tools.write_naive(tmp_path / "naive", ids, texts, vecs)
    needles = tools.needles_of(ids, texts, vecs)
    seen = tools.count_hits(tools.files_under([tmp_path / "naive"]), needles)
    assert all(found == wanted for found, wanted in seen.values()), seen
