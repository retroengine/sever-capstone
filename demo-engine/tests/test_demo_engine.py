"""The demo's own tests: every entry point runs offline on the golden fixture and its checks pass.

These are smoke tests of the demo, not of the engine (the engine's tests are under ``tests/`` and in
each crate). Each run uses its own directory under ``demo-engine/work/`` (ext4; §12.9 refuses
tmpfs).
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

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
