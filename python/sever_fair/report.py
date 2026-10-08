"""Stage 9: the pass rule (FT-8), the findings, the report, the ledger entry and, on a pass, the
sealed clean-room tests kept in ``tests/cleanroom/`` (FT-10)."""

import datetime as dt
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sever_fair import checks

if TYPE_CHECKING:
    from sever_fair.pipeline import Run

LIMITS = (
    "Every session runs a Claude model, so a misreading all of them share survives; different "
    "models for tester and judge reduce this, they do not remove it. A wrong spec is tested "
    "faithfully. One machine runs everything: power-loss durability beyond what WSL's virtual disk "
    "provides is a stated limit, not a result."
)


def owned_digest(root: Path, part: int) -> str | None:
    """SHA-256 of the freeze manifest the part would get at ``root`` (FT-10)."""
    r = subprocess.run(
        ["scripts/freeze.sh", "list", str(part)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return None
    return hashlib.sha256(r.stdout.encode()).hexdigest()


def findings(
    run: "Run",
    tri: dict[str, Any],
    scored: list[dict[str, Any]],
    esc: dict[str, Any],
    orc: dict[str, Any],
    baseline: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t, v in sorted(tri["verdicts"].items()):
        if v["verdict"] in ("ENGINE_BUG", "SPEC_GAP"):
            out.append(
                {
                    "kind": v["verdict"],
                    "test": t,
                    "section": v["section"],
                    "reason": v["reason"],
                    "output": baseline[t]["message"][-3000:],
                    "source": _test_source(run, t),
                }
            )
    by_id = {s["id"]: s for s in scored}
    for bid, v in sorted(esc["verdicts"].items()):
        if v["verdict"] == "TEST_GAP":
            out.append(
                {
                    "kind": "TEST_GAP",
                    "bug": bid,
                    "section": v["section"],
                    "reason": v["reason"],
                    "patch": by_id[bid]["patch"],
                    "claim": by_id[bid]["claim"],
                }
            )
    for f, v in sorted(orc["verdicts"].items()):
        if v["verdict"] == "DISAGREE":
            i = int(f.split(".")[0]) - 1
            out.append(
                {
                    "kind": "ORACLE_DISAGREE",
                    "file": orc["picked"][i]["file"],
                    "test": orc["picked"][i]["name"],
                    "section": v["section"],
                    "reason": v["reason"],
                }
            )
    for n, f in enumerate(out, 1):
        f["id"] = f"F-{n}"
    return out


def _test_source(run: "Run", tid: str) -> str:
    mod = tid.split("::")[0].split(".")[-1]
    p = run.room / "work/tests" / f"{mod}.py"
    return p.read_text(encoding="utf-8")[:12000] if p.exists() else ""


def verdict(
    run: "Run",
    tri: dict[str, Any],
    scored: list[dict[str, Any]],
    esc: dict[str, Any],
    orc: dict[str, Any],
    fs: list[dict[str, Any]],
) -> tuple[str, list[tuple[str, str, bool]]]:
    rule = run.cfg.passrule
    st = run.state()
    n = {
        k: sum(1 for f in fs if f["kind"] == k)
        for k in ("ENGINE_BUG", "SPEC_GAP", "TEST_GAP", "ORACLE_DISAGREE")
    }
    valid = sum(1 for s in scored if s.get("valid"))
    problems = tri["problems"] + esc["problems"] + orc["problems"]
    rows = [
        (
            "own suite green on the unpatched build",
            str(st.get("baseline_green")),
            bool(st.get("baseline_green")) == bool(rule["baseline_green"]),
        ),
        ("engine bugs (triage)", str(n["ENGINE_BUG"]), n["ENGINE_BUG"] <= rule["engine_bugs"]),
        ("spec gaps (triage)", str(n["SPEC_GAP"]), n["SPEC_GAP"] <= rule["spec_gaps"]),
        ("test gaps (escaped real bugs)", str(n["TEST_GAP"]), n["TEST_GAP"] <= rule["test_gaps"]),
        (
            "oracle disagreements",
            str(n["ORACLE_DISAGREE"]),
            n["ORACLE_DISAGREE"] <= rule["oracle_disagreements"],
        ),
        ("valid planted bugs", f"{valid} of {len(scored)}", valid >= rule["min_valid_plants"]),
        ("judge outputs complete", "; ".join(problems) or "yes", not problems),
    ]
    ok = all(r[2] for r in rows)
    if run.stub:
        return "DRY", rows
    return ("PASS" if ok else "FAIL"), rows


def write(
    run: "Run",
    baseline: dict[str, dict[str, str]],
    tri: dict[str, Any],
    scored: list[dict[str, Any]],
    esc: dict[str, Any],
    orc: dict[str, Any],
) -> dict[str, Any]:
    from sever_testkit import ledger

    fs = findings(run, tri, scored, esc, orc, baseline)
    outcome, rows = verdict(run, tri, scored, esc, orc, fs)
    sealed = json.loads((run.dir / "seal.json").read_text())
    st = run.state()
    summary: dict[str, Any] = {
        "run_id": run.run_id,
        "part": run.scope.part,
        "module": run.scope.module,
        "commit": run.commit,
        "outcome": outcome,
        "config_sha256": run.cfg.sha256,
        "seal_digest": sealed["digest"],
        "owned_sha256": owned_digest(run.wt, run.scope.part),
        "rows": [{"check": a, "value": b, "ok": c} for a, b, c in rows],
        "tests": len(baseline),
        "failing": len(checks.failing(baseline)),
        "triage": tri["verdicts"],
        "planted": [{k: v for k, v in s.items() if k != "patch"} for s in scored],
        "escapes": esc["verdicts"],
        "oracle": {
            "pool": orc["pool"],
            "verdicts": orc["verdicts"],
            "picked": [(p["file"], p["name"]) for p in orc["picked"]],
        },
        "findings": fs,
        "sessions": st.get("sessions", []),
    }
    (run.dir / "findings.json").write_text(json.dumps(fs, indent=1))
    (run.dir / "summary.json").write_text(json.dumps(summary, indent=1))
    md = markdown(run, summary, baseline)
    (run.dir / "REPORT.md").write_text(md, encoding="utf-8")
    name = f"FAIRNESS_P{run.scope.part}" + (f"_{run.scope.module}" if run.scope.module else "")
    if run.stub:
        name += "_DRY"
    audit = run.repo / "docs/audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / f"{name}.md").write_text(md, encoding="utf-8")
    _, sha = ledger.result_file(run.repo, f"fair-{run.run_id}.json", summary)
    rec = ledger.entry(
        run.repo,
        f"fair {'dry-run' if run.stub else 'run'} {run.scope.part}",
        gate="fair testing (docs/FAIR_TESTING.md)",
        outcome=outcome,
        run_id=run.run_id,
        run_commit=run.commit,
        part=run.scope.part,
        module=run.scope.module,
        owned_sha256=summary["owned_sha256"],
        seal_digest=sealed["digest"],
        result_file=f"results/fair-{run.run_id}.json",
        result_sha256=sha,
    )
    ledger.append(run.repo, rec)
    if outcome == "PASS" and run.scope.module is None:
        keep_tests(run, tri)
    run.say(f"stage 9: {outcome}; report docs/audit/{name}.md; {len(fs)} findings")
    return summary


def keep_tests(run: "Run", tri: dict[str, Any]) -> None:
    """FT-10: the passing run's sealed tests join the repository, with a manifest."""
    dest = run.repo / f"tests/cleanroom/p{run.scope.part}/{run.run_id}"
    if dest.exists():
        return
    shutil.copytree(run.room / "work", dest, ignore=shutil.ignore_patterns("__pycache__"))
    for f in dest.rglob("*"):
        f.chmod(f.stat().st_mode | 0o200)
    excluded = sorted(t for t, v in tri["verdicts"].items() if v["verdict"] == "TEST_ERROR")
    (dest / "EXCLUDED.json").write_text(
        json.dumps({"why": "judged TEST_ERROR in the run's triage", "tests": excluded}, indent=1)
        + "\n"
    )
    lines = []
    for p in sorted(dest.rglob("*")):
        if p.is_file() and p.name != "MANIFEST.sha256":
            rel = p.relative_to(run.repo)
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {rel}\n")
    (dest / "MANIFEST.sha256").write_text("".join(lines))


def markdown(run: "Run", s: dict[str, Any], baseline: dict[str, dict[str, str]]) -> str:
    when = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    scope = f"Part {s['part']}" + (f", module `{s['module']}`" if s["module"] else "")
    lines = [
        f"# Fairness report: {scope}",
        "",
        f"Generated by `python -m sever_fair` (docs/FAIR_TESTING.md) on {when}. Do not edit.",
        "",
        f"**Outcome: {s['outcome']}**"
        + (" (dry run with stub agents: plumbing only, never a pass)" if run.stub else ""),
        "",
        f"Run `{s['run_id']}`, commit `{s['commit']}`, config SHA-256 `{s['config_sha256'][:16]}`, "
        f"seal `{s['seal_digest'][:16]}`, owned files `{(s['owned_sha256'] or '?')[:16]}`.",
        "",
        "## Pass rule (configs/fair.yaml, pre-registered)",
        "",
        "| Check | Value | Holds |",
        "|---|---|---|",
        *[f"| {r['check']} | {r['value']} | {'yes' if r['ok'] else '**no**'} |" for r in s["rows"]],
        "",
        "## Findings",
        "",
    ]
    if not s["findings"]:
        lines.append("None.")
    for f in s["findings"]:
        what = f.get("test") or f.get("bug") or f.get("file")
        lines.append(f"- **{f['id']} {f['kind']}** `{what}` ({f['section']}): {f['reason']}")
    lines += [
        "",
        f"## Clean-room tests (FT-1, FT-3): {s['tests']} sealed tests, {s['failing']} failing",
        "",
        "| Test | Outcome | Verdict | § |",
        "|---|---|---|---|",
    ]
    for t, r in sorted(baseline.items()):
        v = s["triage"].get(t, {})
        lines.append(
            f"| `{t}` | {r['outcome']} | {v.get('verdict', '')} | {v.get('section', '')} |"
        )
    lines += [
        "",
        "## Planted bugs (FT-6)",
        "",
        "| Bug | Claim | Valid | Own suite | Clean room | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for p in s["planted"]:
        claim = (
            (p.get("claim") or {}).get("behaviour", "") if isinstance(p.get("claim"), dict) else ""
        )
        sec = (p.get("claim") or {}).get("section", "") if isinstance(p.get("claim"), dict) else ""
        if not p.get("valid"):
            lines.append(f"| {p['id']} | {sec} {claim} | no: {p.get('why')} | | | |")
            continue
        v = s["escapes"].get(p["id"], {}).get("verdict", "caught")
        lines.append(
            f"| {p['id']} | {sec} {claim} | yes | {'red' if p['caught_by_own_suite'] else 'green'}"
            f" | {len(p['caught_by_cleanroom'])} new failures | {v} |"
        )
    lines += [
        "",
        f"## Oracle audit (FT-7): {len(s['oracle']['picked'])} of {s['oracle']['pool']} "
        "labelled tests, drawn with OS entropy",
        "",
        "| Test | Verdict | § |",
        "|---|---|---|",
    ]
    for i, (f, name) in enumerate(s["oracle"]["picked"], 1):
        v = s["oracle"]["verdicts"].get(f"{i:02d}.txt", {})
        lines.append(f"| `{f}::{name}` | {v.get('verdict', '')} | {v.get('section', '')} |")
    lines += [
        "",
        "## Sessions (FT-1, FT-2, FT-5)",
        "",
        "| Session | Model | Exit | Canary | Cost (USD) |",
        "|---|---|---|---|---|",
    ]
    for x in s["sessions"]:
        lines.append(
            f"| {x['name']} | {x['model']} | {x['rc']} | {x['canary']} | {x['cost_usd']} |"
        )
    lines += ["", "## Limits", "", LIMITS, ""]
    return "\n".join(lines)
