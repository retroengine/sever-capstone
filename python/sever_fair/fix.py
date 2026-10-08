"""FT-9: fix a run's findings in their own worktree, one at a time, red first, diff-guarded.

The worktree is ``~/.sever-fair/fix/<run_id>`` on a new branch ``p<N>-fairfix-<stamp>`` from the
run's commit; the checkout under test is never touched. Every session is fresh and sandboxed (the
fixer may see the code: it is the builder's role, not the tester's). The script, not the session,
checks each rule from the diff and makes each commit, with the repository's own git identity.
"""

import json
import subprocess
from pathlib import Path
from typing import Any

from sever_fair import agent, checks, room
from sever_fair.pipeline import Run
from sever_fair.sandbox import Box, with_python

FIXES = Path.home() / ".sever-fair/fix"


def _git(wt: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(wt), *args], capture_output=True, text=True, check=False
    ).stdout


def changed(wt: Path) -> list[str]:
    out = _git(wt, "status", "--porcelain", "-uall")
    return sorted({ln[3:].split(" -> ")[-1] for ln in out.splitlines() if ln})


def frozen(wt: Path) -> set[str]:
    files: set[str] = set()
    for m in (wt / "freeze").glob("PART-*.sha256"):
        files |= {ln.split("  ", 1)[1] for ln in m.read_text().splitlines() if "  " in ln}
    return files


def discard(wt: Path, to: str) -> None:
    _git(wt, "reset", "-q", "--hard", to)
    _git(wt, "clean", "-qfd", "-e", "target")


def commit(wt: Path, message: str) -> str:
    _git(wt, "add", "-A")
    r = subprocess.run(
        ["git", "-C", str(wt), "commit", "-q", "-m", message],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode:
        raise SystemExit(f"commit failed: {r.stderr}")
    return _git(wt, "rev-parse", "HEAD").strip()


def fixer_box(run: Run, wt: Path, out: Path) -> Box:
    """The fixer's sandbox: the fix worktree, the toolchains, nothing else of the home folder."""
    home = Path.home()
    b = Box(cwd=str(wt))
    with_python(b, wt / ".venv")
    b.rw(wt)
    b.ro(home / ".rustup", "/opt/rustup").ro(home / ".cargo/bin", "/opt/cargo/bin")
    for sub in ("registry", "git"):
        if (home / ".cargo" / sub).exists():
            b.rw(home / ".cargo" / sub, f"/opt/cargo/{sub}")
    b.ro(home / ".local/bin/uv", "/opt/uvbin/uv")
    if (home / ".cache/uv").exists():
        b.rw(home / ".cache/uv", "/opt/uvcache")
    out.mkdir(parents=True, exist_ok=True)
    b.rw(out, "/room/out")
    b.env |= {
        "PATH": "/opt/cargo/bin:/opt/uvbin:/usr/local/bin:/usr/bin:/bin",
        "RUSTUP_HOME": "/opt/rustup",
        "CARGO_HOME": "/opt/cargo",
        "UV_CACHE_DIR": "/opt/uvcache",
        "CARGO_NET_OFFLINE": "true",
        "UV_OFFLINE": "1",
        "PYTHONPATH": "python",
    }
    return b


def describe(f: dict[str, Any]) -> str:
    keep = {k: v for k, v in f.items() if k not in ("source",)}
    text = "```json\n" + json.dumps(keep, indent=1)[:20000] + "\n```"
    if f.get("source"):
        text += "\n\nThe clean-room test (sealed; it stays outside the repository):\n\n```python\n"
        text += f["source"][:12000] + "\n```"
    return text


def fix_run(run: Run, stamp: str) -> dict[str, Any]:
    fs: list[dict[str, Any]] = json.loads((run.dir / "findings.json").read_text())
    wt = FIXES / run.run_id
    branch = f"p{run.scope.part}-fairfix-{stamp}"
    log = run.dir / "logs/fix.log"
    if not wt.exists():
        room.must(
            room.sh(
                ["git", "worktree", "add", "-q", "-b", branch, str(wt), run.commit], run.repo, log
            ),
            "git worktree add",
            log,
        )
    room.must(room.sh(["uv", "sync", "-q", "--frozen"], wt, log), "uv sync", log)
    room.must(room.build(wt, run.part, log), "build", log)
    results: list[dict[str, Any]] = []
    for f in fs:
        run.say(f"fix {f['id']} {f['kind']}")
        res = _one(run, wt, f, log)
        results.append({"id": f["id"], "kind": f["kind"]} | res)
        run.say(
            f"fix {f['id']}: {res['status']}" + (f" ({res.get('why')})" if res.get("why") else "")
        )
    out = {
        "branch": branch,
        "worktree": str(wt),
        "head": _git(wt, "rev-parse", "HEAD").strip(),
        "results": results,
    }
    (run.dir / "fix.json").write_text(json.dumps(out, indent=1))
    return out


def _session(run: Run, wt: Path, name: str, text: str) -> None:
    out = run.dir / "fix" / name
    run.session(
        role=name.split("-")[1],
        name=name,
        model=run.cfg.model("fixer"),
        text=text,
        box=fixer_box(run, wt, out),
        prompt_dir=out,
        canary_allow=[str(wt)],
    )


def _one(run: Run, wt: Path, f: dict[str, Any], log: Path) -> dict[str, Any]:
    start = _git(wt, "rev-parse", "HEAD").strip()
    fid = f["id"]
    if f["kind"] == "ORACLE_DISAGREE":
        return {"status": "owner", "why": "an existing test's expected value is disputed (FT-7)"}
    if f["kind"] == "SPEC_GAP":
        _session(
            run, wt, f"fix-gap-{fid}", agent.prompt("fix_gap", worktree=wt, finding=describe(f))
        )
        bad = checks.guard_gap_change(changed(wt))
        if bad:
            discard(wt, start)
            return {"status": "owner", "why": "; ".join(bad)}
        sha = commit(wt, f"docs(spec): decide the gap fair testing found ({fid}, {f['section']})")
        return {"status": "fixed", "commits": [sha]}
    # TEST_GAP and ENGINE_BUG start with a regression test (step 1)
    goal = (
        "passes on the current code and fails when this planted bug is applied (the patch is in "
        "the finding)"
        if f["kind"] == "TEST_GAP"
        else "fails on the current code because of this engine bug, and will pass once it is fixed"
    )
    _session(
        run,
        wt,
        f"fix-test-{fid}",
        agent.prompt("fix_test", worktree=wt, finding=describe(f), goal=goal),
    )
    bad = checks.guard_test_change(changed(wt))
    if not changed(wt):
        bad = ["the session changed nothing"]
    if bad:
        discard(wt, start)
        return {"status": "owner", "why": "; ".join(bad)}
    green, _ = room.own_suite(wt, run.part, log)
    if f["kind"] == "TEST_GAP":
        if not green:
            discard(wt, start)
            return {"status": "owner", "why": "the new test is red on the unpatched code"}
        sha = commit(wt, f"test: catch the planted bug fair testing found ({fid}, {f['section']})")
        patch = run.dir / "plant/out/bugs" / f"{f['bug']}.patch"
        red = False
        if room.sh(["git", "apply", str(patch)], wt, log) == 0:
            red = room.build(wt, run.part, log) == 0 and not room.own_suite(wt, run.part, log)[0]
        discard(wt, sha)
        room.build(wt, run.part, log)
        if not red:
            discard(wt, start)
            return {"status": "owner", "why": "the new test does not turn red with the planted bug"}
        return {"status": "fixed", "commits": [sha]}
    if green:
        discard(wt, start)
        return {"status": "owner", "why": "the regression test is not red on the current code"}
    test_sha = commit(
        wt, f"test: regression for the engine bug fair testing found ({fid}, {f['section']})"
    )
    retry = ""
    test_diff = _git(wt, "show", "--format=", test_sha)[:30000]
    for attempt in (1, 2):
        _session(
            run,
            wt,
            f"fix-code-{fid}-{attempt}",
            agent.prompt(
                "fix_code", worktree=wt, finding=describe(f), retry=retry, test_diff=test_diff
            ),
        )
        bad = checks.guard_fix_change(changed(wt), frozen(wt))
        if not changed(wt):
            bad = ["the session changed nothing"]
        if bad:
            discard(wt, test_sha)
            retry = "\nThe previous attempt was discarded: " + "; ".join(bad)
            continue
        ci_log = run.dir / f"logs/fix-ci-{fid}-{attempt}.log"
        if room.sh(["scripts/ci.sh", "fast"], wt, ci_log, timeout=7200) == 0:
            sha = commit(wt, f"fix: engine bug fair testing found ({fid}, {f['section']})")
            return {"status": "fixed", "commits": [test_sha, sha]}
        tail = ci_log.read_text(errors="replace")[-4000:]
        discard(wt, test_sha)
        retry = (
            "\nThe previous attempt was discarded; `scripts/ci.sh fast` failed:\n```\n"
            + tail
            + "\n```"
        )
    discard(wt, start)
    return {
        "status": "owner",
        "why": "no fix passed the guards and scripts/ci.sh fast in two attempts",
    }
