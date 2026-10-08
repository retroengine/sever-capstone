"""One fair-testing run, stages 0-9 (docs/FAIR_TESTING.md §2).

Each stage writes its outputs into the run folder and is skipped when they already exist, so a
run interrupted at any point resumes with ``fair.sh resume <run_id>``. Stage 2 (the seal) is
written once and never redone: a resumed run checks the seal instead.
"""

import datetime as dt
import json
import secrets
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sever_fair import agent, checks, config, room
from sever_fair.config import Config, Scope
from sever_fair.sandbox import Box, with_python

RUNS = Path.home() / ".sever-fair/runs"
SPENT: list[float] = [0.0]  # what this fair.sh command has spent so far (DB-74)


@dataclass
class Run:
    repo: Path
    cfg: Config
    scope: Scope
    run_id: str
    commit: str
    dir: Path
    stub: bool
    sessions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def part(self) -> dict[str, Any]:
        return self.cfg.part(self.scope.part)

    @property
    def wt(self) -> Path:
        return self.dir / "wt"

    @property
    def room(self) -> Path:
        return self.dir / "room"

    @property
    def log(self) -> Path:
        return self.dir / "logs/script.log"

    def say(self, msg: str) -> None:
        line = f"[{dt.datetime.now(dt.UTC).strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with self.log.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def state(self) -> dict[str, Any]:
        p = self.dir / "state.json"
        data: dict[str, Any] = json.loads(p.read_text()) if p.exists() else {}
        return data

    def save(self, **kv: Any) -> None:
        s = self.state() | kv
        (self.dir / "state.json").write_text(json.dumps(s, indent=1) + "\n")

    def session(self, **kw: Any) -> agent.Session:
        cap = self.cfg.command_cap
        if cap is not None and not self.stub and SPENT[0] >= cap:
            raise SystemExit(
                f"budget: this command has spent ${SPENT[0]:.2f} of its ${cap:.0f} cap (DB-74); "
                f"nothing more starts. Continue with: scripts/fair.sh resume {self.run_id} --yes"
            )
        kw.setdefault("budget_usd", self.cfg.session_cap(kw["role"]))
        kw.setdefault("wait_on_limit", self.cfg.wait_on_limit)
        s = agent.run(
            run_dir=self.dir,
            repo=self.repo,
            stub=self.stub,
            timeout=self.cfg.number("session_timeout_s"),
            **kw,
        )
        rec = {
            "role": s.role,
            "name": s.name,
            "model": s.model,
            "rc": s.rc,
            "cost_usd": s.cost_usd,
            "canary": "pass",
            "log": str(s.log),
        }
        SPENT[0] += s.cost_usd or 0.0
        self.save(sessions=[*self.state().get("sessions", []), rec])
        self.say(f"session {s.name} ({s.model}) rc={s.rc}")
        if s.rc != 0:
            raise SystemExit(
                f"session {s.name} did not complete (rc {s.rc}; {s.log}); nothing was sealed or "
                f"reported from it. Continue with: scripts/fair.sh resume {self.run_id}"
            )
        return s


def new(repo: Path, cfg: Config, scope: Scope, stub: bool, rev: str = "HEAD") -> Run:
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", rev], capture_output=True, text=True, check=True
    ).stdout.strip()
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    tag = f"p{scope.part}" + (f"-{scope.module}" if scope.module else "")
    run_id = f"{stamp}-{tag}-{commit[:8]}" + ("-dry" if stub else "")
    d = RUNS / run_id
    d.mkdir(parents=True)
    run = Run(repo, cfg, scope, run_id, commit, d, stub)
    run.save(
        run_id=run_id,
        commit=commit,
        part=scope.part,
        module=scope.module,
        stub=stub,
        config_sha256=cfg.sha256,
        started=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    )
    return run


def load(repo: Path, cfg: Config, run_id: str) -> Run:
    d = RUNS / run_id
    s = json.loads((d / "state.json").read_text())
    if s["config_sha256"] != cfg.sha256 and config.digest_at(repo, s["commit"]) != cfg.sha256:
        raise SystemExit("configs/fair.yaml changed since this run started (FT-8); start a new run")
    return Run(repo, cfg, cfg.scope(s["part"], s["module"]), run_id, s["commit"], d, s["stub"])


# ---- sandboxes ----------------------------------------------------------------------------------


def room_box(
    run: Run,
    *,
    site: Path,
    bindir: Path,
    out: Path,
    scratch: Path,
    work_rw: bool,
    with_work: bool = True,
) -> Box:
    b = Box(cwd="/room")
    with_python(b, run.dir / "venv")
    r = run.room
    b.ro(r / "spec", "/room/spec").ro(r / "api", "/room/api").ro(r / "inputs", "/room/inputs")
    if with_work:
        (b.rw if work_rw else b.ro)(r / "work", "/room/work")
    out.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    b.rw(out, "/room/out").ro(site, "/room/site").ro(bindir, "/room/bin").rw(scratch, "/scratch")
    b.env |= {
        "PYTHONPATH": "/room/site",
        "SEVER_INPUTS": "/room/inputs",
        "SEVER_SCRATCH": "/scratch",
        "SEVER_CLI": "/room/bin/" + run.part["cli"]["bins"][0],
    }
    return b


def judge_box(run: Run, out: Path) -> Box:
    b = Box(cwd="/room")
    with_python(b, run.dir / "venv")
    r = run.room
    b.ro(r / "spec", "/room/spec").ro(r / "api", "/room/api").ro(r / "work", "/room/work")
    out.mkdir(parents=True, exist_ok=True)
    return b.rw(out, "/room/out")


# ---- stage 0: prepare ---------------------------------------------------------------------------


def prepare(run: Run) -> None:
    if run.state().get("prepared"):
        return
    log = run.dir / "logs/prepare.log"
    run.say(f"stage 0: worktree at {run.commit[:12]}, build, room")
    room.worktree(run.repo, run.wt, run.commit, log)
    room.must(_build(run, log), "build", log)
    room.export_engine(run.wt, run.part, run.dir / "engine/site", run.dir / "engine/bin")
    room.build_room(run.wt, run.part, run.room, [run.repo, room.main_checkout(run.repo)])
    room.build_sealed(run.wt, run.part, run.dir / "sealed/site", run.dir / "sealed/bin")
    room.make_venv(run.dir / "venv", log)
    run.say("stage 0: the part's own suite on the unpatched build (baseline)")
    green, detail = own_suite(run, "baseline")
    run.save(prepared=True, baseline_green=green, baseline_detail=detail)


def _build(run: Run, log: Path) -> int:
    return room.build(run.wt, run.part, log)


def own_suite(run: Run, label: str) -> tuple[bool, list[dict[str, Any]]]:
    return room.own_suite(run.wt, run.part, run.dir / f"logs/own-{label}.log")


# ---- stages 1-3: write, seal, run ---------------------------------------------------------------


def write(run: Run) -> None:
    if (run.dir / "seal.json").exists() or run.state().get("written"):
        return
    run.say("stage 1: clean-room tester writes tests against the sealed engine")
    sc = run.scope
    box = room_box(
        run,
        site=run.dir / "sealed/site",
        bindir=run.dir / "sealed/bin",
        out=run.room / "out",
        scratch=run.dir / "scratch/write",
        work_rw=True,
    )
    text = agent.prompt(
        "tester",
        part=sc.part,
        sections=", ".join(f"§{s}" for s in sc.sections),
        not_sections=", ".join(f"§{s}" for s in sc.not_sections) or "nothing",
        module_line=f"This run covers the module `{sc.module}` only." if sc.module else "",
        min_tests=10 if sc.module else 40,
    )
    run.session(
        role="tester",
        name="1-tester",
        model=run.cfg.model("tester"),
        text=text,
        box=box,
        prompt_dir=run.room / "out",
    )
    run.save(written=True)


def seal(run: Run) -> dict[str, str]:
    p = run.dir / "seal.json"
    work = run.room / "work"
    if p.exists():
        sealed: dict[str, str] = json.loads(p.read_text())["files"]
        broken = checks.seal_broken(work, sealed)
        if broken:
            raise SystemExit(f"FT-3: sealed tests changed after sealing: {broken}")
        return sealed
    sealed = checks.seal(work)
    if not any(k.startswith("tests/test_") for k in sealed):
        raise SystemExit("stage 1 produced no test files; see logs/1-tester.json")
    p.write_text(json.dumps({"digest": checks.seal_digest(sealed), "files": sealed}, indent=1))
    for f in work.rglob("*"):
        f.chmod(f.stat().st_mode & ~0o222)
    run.say(f"stage 2: sealed {len(sealed)} files, digest {checks.seal_digest(sealed)[:16]}")
    return sealed


def measure(run: Run, label: str, site: Path, bindir: Path) -> dict[str, dict[str, str]]:
    """Runs the sealed tests against an engine, in a sandbox with no network (FT-4)."""
    out = run.dir / "results" / label
    xml = out / "junit.xml"
    if xml.exists():
        return checks.junit(xml)
    seal(run)
    scratch = run.dir / "scratch" / label
    box = room_box(run, site=site, bindir=bindir, out=out, scratch=scratch, work_rw=False)
    box.cwd = "/tmp"
    rc = box.run(
        [
            "/opt/venv/bin/python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--junitxml=/room/out/junit.xml",
            "/room/work/tests",
        ],
        run.dir / f"logs/measure-{label}.log",
        timeout=3600,
    )
    shutil.rmtree(scratch, ignore_errors=True)
    res = checks.junit(xml)
    if not res:
        raise SystemExit(f"measure {label}: no results (rc {rc}); log: logs/measure-{label}.log")
    return res


# ---- stage 4: triage ----------------------------------------------------------------------------

TRIAGE = {"ENGINE_BUG", "TEST_ERROR", "SPEC_GAP"}


def triage(run: Run, baseline: dict[str, dict[str, str]]) -> dict[str, Any]:
    fails = sorted(checks.failing(baseline))
    out = run.dir / "judge/triage"
    path = out / "triage.json"
    if fails and not path.exists():
        run.say(f"stage 4: judge triages {len(fails)} failures")
        out.mkdir(parents=True, exist_ok=True)
        (out / "failures.json").write_text(
            json.dumps([{"test": t, "output": baseline[t]["message"]} for t in fails], indent=1)
        )
        run.session(
            role="triage",
            name="4-triage",
            model=run.cfg.model("judge"),
            text=agent.prompt("triage", part=run.scope.part),
            box=judge_box(run, out),
            prompt_dir=out,
        )
    v, problems = checks.verdicts(path, "test", set(fails), TRIAGE) if fails else ({}, [])
    return {"failures": fails, "verdicts": v, "problems": problems}


# ---- stages 5-7: plant, score, escapes ----------------------------------------------------------


def plant(run: Run) -> Path:
    bugs = run.dir / "plant/out/bugs"
    if run.state().get("planted"):
        return bugs
    run.say("stage 5: planter plants blind bugs")
    src = run.dir / "plant/src"
    if src.exists():
        shutil.rmtree(src)
    src.mkdir(parents=True)
    archive = subprocess.run(
        ["git", "-C", str(run.repo), "archive", run.commit], capture_output=True, check=True
    ).stdout
    subprocess.run(
        [
            "tar",
            "-x",
            "-C",
            str(src),
            "--exclude=tests/cleanroom",
            "--exclude=docs/audit",
            "--exclude=results",
        ],
        input=archive,
        check=True,
    )
    q = {"cwd": src, "check": True, "capture_output": True}
    subprocess.run(["git", "init", "-q"], **q)  # type: ignore[call-overload]
    subprocess.run(["git", "add", "-A"], **q)  # type: ignore[call-overload]
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=planter",
            "-c",
            "user.email=planter@sandbox",  # throwaway repo
            "commit",
            "-qm",
            "source",
        ],
        **q,
    )  # type: ignore[call-overload]
    bugs.mkdir(parents=True, exist_ok=True)
    b = Box(cwd="/src")
    with_python(b, run.dir / "venv")
    b.ro(run.room / "spec", "/room/spec").rw(src, "/src").rw(bugs.parent, "/room/out")
    text = agent.prompt(
        "planter",
        part=run.scope.part,
        count=run.cfg.number("plant_count"),
        plant_paths=", ".join(f"`{p}`" for p in run.scope.plant_paths),
    )
    run.session(
        role="planter",
        name="5-planter",
        model=run.cfg.model("planter"),
        text=text,
        box=b,
        prompt_dir=bugs.parent,
    )
    run.save(planted=True)
    return bugs


def score(run: Run, baseline: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    path = run.dir / "score.json"
    done: list[dict[str, Any]] = json.loads(path.read_text()) if path.exists() else []
    seen = {d["id"] for d in done}
    bugs = run.dir / "plant/out/bugs"
    base_fail = checks.failing(baseline)
    for patch in sorted(bugs.glob("*.patch")):
        bid = patch.stem
        if bid in seen:
            continue
        run.say(f"stage 6: scoring planted bug {bid}")
        rec: dict[str, Any] = {"id": bid, "claim": _json(bugs / f"{bid}.json")}
        text = patch.read_text(encoding="utf-8", errors="replace")
        files = checks.patch_files(text)
        rec["files"] = files
        log = run.dir / f"logs/score-{bid}.log"
        _reset(run, log)
        bad = checks.plant_violations(files, run.scope.plant_paths) if files else ["empty patch"]
        if bad:
            rec |= {"valid": False, "why": "; ".join(bad)}
        elif room.sh(["git", "apply", str(patch)], run.wt, log):
            rec |= {"valid": False, "why": "does not apply"}
        elif _build(run, log):
            rec |= {"valid": False, "why": "does not build"}
        else:
            site, bindir = run.dir / f"score/{bid}/site", run.dir / f"score/{bid}/bin"
            room.export_engine(run.wt, run.part, site, bindir)
            res = measure(run, f"bug-{bid}", site, bindir)
            new_fail = sorted(checks.failing(res) - base_fail)
            green, detail = own_suite(run, f"bug-{bid}")
            rec |= {
                "valid": True,
                "caught_by_cleanroom": new_fail,
                "caught_by_own_suite": not green,
                "own_suite": detail,
                "patch": text,
            }
        done.append(rec)
        path.write_text(json.dumps(done, indent=1))
    _reset(run, run.dir / "logs/score-reset.log")
    return done


def _reset(run: Run, log: Path) -> None:
    room.sh(["git", "checkout", "-q", "--", "."], run.wt, log)
    room.sh(["git", "clean", "-qfd", "-e", "target"], run.wt, log)


def _json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


ESCAPE = {"TEST_GAP", "EQUIVALENT"}


def escapes(run: Run, scored: list[dict[str, Any]]) -> dict[str, Any]:
    esc = [
        s
        for s in scored
        if s.get("valid") and not s["caught_by_cleanroom"] and not s["caught_by_own_suite"]
    ]
    out = run.dir / "judge/escapes"
    path = out / "escape_verdicts.json"
    if esc and not path.exists():
        run.say(f"stage 7: judge rules on {len(esc)} escaped bugs")
        out.mkdir(parents=True, exist_ok=True)
        (out / "escapes.json").write_text(
            json.dumps(
                [{"id": s["id"], "patch": s["patch"], "claim": s["claim"]} for s in esc], indent=1
            )
        )
        b = Box(cwd="/room")
        with_python(b, run.dir / "venv")
        b.ro(run.room / "spec", "/room/spec").rw(out, "/room/out")
        run.session(
            role="escape",
            name="7-escapes",
            model=run.cfg.model("judge"),
            text=agent.prompt("escape", part=run.scope.part),
            box=b,
            prompt_dir=out,
        )
    v, problems = checks.verdicts(path, "id", {s["id"] for s in esc}, ESCAPE) if esc else ({}, [])
    return {"escaped": [s["id"] for s in esc], "verdicts": v, "problems": problems}


# ---- stage 8: oracle audit ----------------------------------------------------------------------

ORACLE = {"AGREE", "DISAGREE", "CANNOT_DERIVE"}


def oracle_audit(run: Run) -> dict[str, Any]:
    out = run.dir / "judge/oracle"
    audit = out / "audit"
    sample_p = run.dir / "oracle_sample.json"
    if not sample_p.exists():
        reqs = yaml.safe_load((run.wt / "spec/requirements.yaml").read_text(encoding="utf-8"))
        ids = {r["id"] for r in reqs if r.get("part") == run.scope.part and _in_scope(run, r)}
        pool = checks.labelled_tests(run.wt, ids)
        k = min(run.cfg.number("oracle_sample"), len(pool))
        picked = secrets.SystemRandom().sample(pool, k)  # FT-7: OS entropy; the draw is recorded
        sample_p.write_text(json.dumps({"pool": len(pool), "picked": picked}, indent=1))
        audit.mkdir(parents=True, exist_ok=True)
        for i, t in enumerate(picked, 1):
            (audit / f"{i:02d}.txt").write_text(
                f"file: {t['file']}\ntest: {t['name']}\nrequirements: {', '.join(t['ids'])}\n\n"
                f"{t['source']}\n\n---- context: the top of {t['file']} (helpers, imports) ----\n\n"
                f"{(run.wt / t['file']).read_text(encoding='utf-8')[:6000]}\n",
                encoding="utf-8",
            )
    sample = json.loads(sample_p.read_text())
    expected = {f"{i:02d}.txt" for i in range(1, len(sample["picked"]) + 1)}
    path = out / "oracle.json"
    if expected and not path.exists():
        run.say(f"stage 8: judge audits {len(expected)} labelled tests (pool {sample['pool']})")
        b = Box(cwd="/room")
        with_python(b, run.dir / "venv")
        b.ro(run.room / "spec", "/room/spec").rw(out, "/room/out")
        run.session(
            role="oracle",
            name="8-oracle",
            model=run.cfg.model("judge"),
            text=agent.prompt("oracle", part=run.scope.part),
            box=b,
            prompt_dir=out,
        )
    v, problems = checks.verdicts(path, "file", expected, ORACLE) if expected else ({}, [])
    return {"pool": sample["pool"], "picked": sample["picked"], "verdicts": v, "problems": problems}


def _in_scope(run: Run, req: dict[str, Any]) -> bool:
    sec = str(req.get("section", ""))

    def under(s: str) -> bool:
        return sec == s or sec.startswith(s + ".")

    return any(under(s) for s in run.scope.sections) and not any(
        under(s) for s in run.scope.not_sections
    )


# ---- the whole run ------------------------------------------------------------------------------


def execute(run: Run) -> dict[str, Any]:
    from sever_fair import report

    prepare(run)
    write(run)
    seal(run)
    run.say("stage 3: sealed tests against the real engine (no network)")
    baseline = measure(run, "baseline", run.dir / "engine/site", run.dir / "engine/bin")
    tri = triage(run, baseline)
    plant(run)
    scored = score(run, baseline)
    esc = escapes(run, scored)
    orc = oracle_audit(run)
    summary = report.write(run, baseline, tri, scored, esc, orc)
    # the build worktree is several GB; everything the report and a fix need is kept outside it
    room.sh(["git", "worktree", "remove", "--force", str(run.wt)], run.repo, run.log)
    return summary
