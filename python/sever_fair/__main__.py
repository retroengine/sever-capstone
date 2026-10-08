"""Command line of the fair-testing system; use it through ``scripts/fair.sh``."""

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from sever_fair import config, pipeline, report, sandbox
from sever_fair.sandbox import Box

ROOT = Path.cwd()


def _start(run: pipeline.Run) -> None:
    from sever_testkit import ledger

    ledger.start(
        ROOT,
        f"fair {'dry-run' if run.stub else 'run'} {run.scope.part}",
        gate="fair testing (docs/FAIR_TESTING.md)",
        run_id=run.run_id,
        run_commit=run.commit,
        part=run.scope.part,
        module=run.scope.module,
    )


def doctor() -> int:
    ok = True

    def line(good: bool, what: str) -> None:
        nonlocal ok
        ok &= good
        print(f"{'ok  ' if good else 'FAIL'} {what}")

    line(shutil.which("bwrap") is not None, "bwrap installed")
    try:
        line(True, f"claude binary: {sandbox.claude_dir()}/claude")
    except SystemExit as e:
        line(False, str(e))
    line(
        bool(sandbox.auth_env()),
        "sandbox credential present (CLAUDE_CODE_OAUTH_TOKEN or "
        f"ANTHROPIC_API_KEY, in the environment or {sandbox.AUTH_FILE})",
    )
    if sandbox.AUTH_FILE.exists():
        line(sandbox.AUTH_FILE.stat().st_mode & 0o077 == 0, f"{sandbox.AUTH_FILE} has mode 600")
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / "out"
        out.mkdir()
        box = Box().rw(out, "/room/out")
        line(
            sandbox.canary(box, ROOT, Path(t) / "canary.log"),
            "FT-2 canary: repository, home, ~/.claude and /mnt absent inside the sandbox",
        )
        print((Path(t) / "canary.log").read_text().strip())
    cfg = config.load(ROOT)
    line(True, f"configs/fair.yaml sha256 {cfg.sha256[:16]}; models {cfg.raw['models']}")
    return 0 if ok else 1


def run_cmd(part: int, module: str | None, stub: bool, rev: str = "HEAD") -> dict[str, Any]:
    cfg = config.load(ROOT)
    run = pipeline.new(ROOT, cfg, cfg.scope(part, module), stub, rev)
    run.say(f"run {run.run_id} in {run.dir}")
    _start(run)
    return pipeline.execute(run)


def resume(run_id: str) -> dict[str, Any]:
    run = pipeline.load(ROOT, config.load(ROOT), run_id)
    run.say(f"resume {run_id}")
    return pipeline.execute(run)


def fix_cmd(run_id: str) -> dict[str, Any]:
    from sever_fair import fix

    run = pipeline.load(ROOT, config.load(ROOT), run_id)
    return fix.fix_run(run, dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M"))


def cycle(part: int, stub: bool) -> int:
    """Run, fix, run again (fresh sessions, fresh tests), up to ``fix_rounds`` times."""
    from sever_fair import fix

    cfg = config.load(ROOT)
    rev = "HEAD"
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M")
    owner: list[dict[str, Any]] = []
    branch = None
    for rnd in range(1, cfg.number("fix_rounds") + 2):
        run = pipeline.new(ROOT, cfg, cfg.scope(part, None), stub, rev)
        run.say(f"cycle round {rnd}: run {run.run_id}")
        _start(run)
        summary = pipeline.execute(run)
        if summary["outcome"] == "PASS" or rnd > cfg.number("fix_rounds"):
            break
        res = fix.fix_run(run, f"{stamp}-r{rnd}")
        branch = res["branch"]
        owner += [r for r in res["results"] if r["status"] == "owner"]
        if not any(r["status"] == "fixed" for r in res["results"]):
            run.say("no finding could be fixed automatically; the rest is the owner's")
            break
        rev = res["head"]
    print(
        json.dumps(
            {
                "outcome": summary["outcome"],
                "last_run": summary["run_id"],
                "fix_branch": branch,
                "owner": owner,
            },
            indent=1,
        )
    )
    return 0 if summary["outcome"] == "PASS" else 1


def verify_freeze(part: int) -> int:
    """FT-10: a PASS fairness run for this part whose owned files match the current ones."""
    digest = report.owned_digest(ROOT, part)
    ledger = ROOT / "docs/RUN_LEDGER.jsonl"
    for line in reversed(
        ledger.read_text(encoding="utf-8").splitlines() if ledger.exists() else []
    ):
        e = json.loads(line)
        if (
            e.get("command") == f"fair run {part}"
            and e.get("outcome") == "PASS"
            and e.get("module") is None
            and digest
            and e.get("owned_sha256") == digest
        ):
            print(f"FT-10: fair run {e['run_id']} PASSED on these files ({digest[:16]})")
            return 0
    print(
        f"FT-10: no PASS fairness run for part {part} on the current files "
        f"({(digest or '?')[:16]}); run scripts/fair.sh cycle {part}"
    )
    return 1


def check() -> int:
    """CI: every kept clean-room test still matches its manifest (FT-10)."""
    bad = 0
    for m in sorted(ROOT.glob("tests/cleanroom/p*/*/MANIFEST.sha256")):
        for line in m.read_text().splitlines():
            sha, rel = line.split("  ", 1)
            p = ROOT / rel
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != sha:
                print(f"changed: {rel}")
                bad += 1
    print(f"clean-room manifests: {'OK' if not bad else f'{bad} changed files'}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="fair.sh")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    for name in ("run", "dry-run"):
        p = sub.add_parser(name)
        p.add_argument("part", type=int)
        p.add_argument("--module")
    p = sub.add_parser("resume")
    p.add_argument("run_id")
    p = sub.add_parser("fix")
    p.add_argument("run_id")
    for name in ("cycle", "dry-cycle"):
        p = sub.add_parser(name)
        p.add_argument("part", type=int)
    p = sub.add_parser("verify-freeze")
    p.add_argument("part", type=int)
    sub.add_parser("check")
    a = ap.parse_args()
    if a.cmd == "doctor":
        return doctor()
    if a.cmd in ("run", "dry-run"):
        s = run_cmd(a.part, a.module, a.cmd == "dry-run")
        return 0 if s["outcome"] in ("PASS", "DRY") else 1
    if a.cmd == "resume":
        return 0 if resume(a.run_id)["outcome"] in ("PASS", "DRY") else 1
    if a.cmd == "fix":
        print(json.dumps(fix_cmd(a.run_id), indent=1))
        return 0
    if a.cmd in ("cycle", "dry-cycle"):
        return cycle(a.part, a.cmd == "dry-cycle")
    if a.cmd == "verify-freeze":
        return verify_freeze(a.part)
    return check()


if __name__ == "__main__":
    sys.exit(main())
