"""``proofs`` (CLAUDE.md §6.3): re-runnable evidence for every claim made about a Part 2 test.

    PYTHONPATH=python uv run python -m sever_testkit_p2.proofs run [--only PR-1 PR-2 …]
    PYTHONPATH=python uv run python -m sever_testkit_p2.proofs check

A proof is a patch that breaks one rule of the code, and the tests it names:

- ``red``: each named test passes without the patch and **fails** with it. This is the evidence for
  a label: ``SR-X`` on a test claims the test goes red when rule X breaks.
- ``green``: each named test passes with and without the patch, although the patch breaks the rule
  in ``requirements``. This is the evidence for removing a label the test could not fail for.

``run`` checks out the committed HEAD into a temporary git worktree (the working tree is never
touched), runs every proof there, and writes ``docs/PROOFS_P2.md``: the commit, each verdict, and
the test result lines as evidence. A patch that does not apply or does not compile is a failed
proof, never a red one. ``check`` is static (Fast CI): the manifest is well formed, every patch
exists, every named test exists, and every (test, label) pair of a labelled Part 2 test has a red
proof.
"""

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml

from sever_testkit_p2 import oracle_check

MANIFEST: Final = Path("tests/proofs/p2/MANIFEST.yaml")
REPORT: Final = Path("docs/PROOFS_P2.md")
KINDS: Final = ("red", "green")
RUNNERS: Final = ("cargo", "pytest")
CARGO_LINE: Final = re.compile(r"^test (\S+) \.\.\. (ok|FAILED|ignored)\b")
PYTEST_LINE: Final = re.compile(r"^(\S+::\S+) (PASSED|FAILED|ERROR|SKIPPED)\b")


@dataclass
class Proof:
    """One manifest entry."""

    id: str
    claim: str
    kind: str
    requirements: list[str]
    patch: str
    runner: str
    tests: list[str]
    package: str = ""
    env: dict[str, str] = field(default_factory=dict)


def load(root: Path) -> list[Proof]:
    raw: list[dict[str, Any]] = yaml.safe_load((root / MANIFEST).read_text(encoding="utf-8")) or []
    out: list[Proof] = []
    for e in raw:
        out.append(
            Proof(
                id=str(e["id"]),
                claim=str(e["claim"]),
                kind=str(e["kind"]),
                requirements=[str(r) for r in e.get("requirements", [])],
                patch=str(e["patch"]),
                runner=str(e.get("runner", "cargo")),
                tests=[str(t) for t in e["tests"]],
                package=str(e.get("package", "")),
                env={str(k): str(v) for k, v in (e.get("env") or {}).items()},
            )
        )
    return out


def _short(name: str) -> str:
    """``file.rs::test`` or ``path.py::test`` → ``test``."""
    return name.rsplit("::", 1)[-1]


def problems(root: Path, proofs: list[Proof], audit: oracle_check.Audit) -> list[str]:
    """Static checks of the manifest against the source."""
    out: list[str] = []
    seen: set[str] = set()
    labelled = {_short(t.name): t for t in audit.tests}
    for p in proofs:
        if p.id in seen:
            out.append(f"{p.id}: duplicate ID")
        seen.add(p.id)
        if p.kind not in KINDS:
            out.append(f"{p.id}: kind {p.kind!r} is not one of {KINDS}")
        if p.runner not in RUNNERS:
            out.append(f"{p.id}: runner {p.runner!r} is not one of {RUNNERS}")
        if p.runner == "cargo" and not p.package:
            out.append(f"{p.id}: a cargo proof names its package")
        if not (root / MANIFEST.parent / p.patch).is_file():
            out.append(f"{p.id}: patch {p.patch} is missing")
        if not p.tests:
            out.append(f"{p.id}: names no test")
        if not p.requirements:
            out.append(f"{p.id}: names no requirement")
        for t in p.tests:
            lt = labelled.get(_short(t))
            if p.kind == "red" and lt is not None:
                out.extend(
                    f"{p.id}: {t} does not label {rid}"
                    for rid in p.requirements
                    if rid not in lt.requirements
                )
            if p.kind == "green" and lt is not None:
                out.extend(
                    f"{p.id}: green proof for {rid}, but {t} still labels it"
                    for rid in p.requirements
                    if rid in lt.requirements
                )
    return out


def unproven(proofs: list[Proof], audit: oracle_check.Audit) -> list[str]:
    """``test: SR-X`` for every label of a labelled Part 2 test that no red proof covers."""
    covered = {
        (_short(t), r) for p in proofs if p.kind == "red" for t in p.tests for r in p.requirements
    }
    return [
        f"{t.name}: {rid}"
        for t in audit.tests
        for rid in t.requirements
        if (_short(t.name), rid) not in covered
    ]


# ---------------------------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------------------------


def _sh(
    cmd: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False)


def _outcomes(p: Proof, wt: Path, target: Path) -> tuple[dict[str, str], str]:
    """Runs ``p``'s tests in worktree ``wt``; returns ``{test: ok|FAILED|…}`` and the raw log."""
    env = dict(os.environ, CARGO_TARGET_DIR=str(target), PYTHONHASHSEED="0", PYTHONPATH="python")
    env.update(p.env)
    if p.runner == "cargo":
        names = [_short(t) for t in p.tests]
        cmd = ["nice", "-n", "19", "cargo", "test", "-j", "2", "-p", p.package, "--no-fail-fast"]
        r = _sh([*cmd, "--", *names], wt, env)
        log = r.stdout + r.stderr
        got: dict[str, str] = {}
        for line in log.splitlines():
            m = CARGO_LINE.match(line)
            if m:
                for n in names:
                    if m.group(1) == n or m.group(1).endswith("::" + n):
                        got[n] = m.group(2)
        return got, log
    r = _sh(
        [
            "nice",
            "-n",
            "19",
            sys.executable,
            "-m",
            "pytest",
            "-v",
            "-p",
            "no:cacheprovider",
            *p.tests,
        ],
        wt,
        env,
    )
    log = r.stdout + r.stderr
    got = {}
    for line in log.splitlines():
        m = PYTEST_LINE.match(line.strip())
        if not m:
            continue
        node = re.sub(r"\[.*\]$", "", m.group(1))  # every parameter of a parametrized test
        status = "ok" if m.group(2) == "PASSED" else m.group(2)
        for t in p.tests:
            if node == t:
                key = _short(t)
                got[key] = status if got.get(key, "ok") == "ok" else got[key]
    return got, log


@dataclass
class Verdict:
    proof: Proof
    ok: bool
    why: str
    baseline: dict[str, str]
    patched: dict[str, str]


def _judge(p: Proof, base: dict[str, str], patched: dict[str, str], applied: bool) -> Verdict:
    names = [_short(t) for t in p.tests]
    if not applied:
        return Verdict(p, False, "patch does not apply", base, patched)
    if any(base.get(n) != "ok" for n in names):
        return Verdict(p, False, "a named test does not pass without the patch", base, patched)
    if any(n not in patched for n in names):
        return Verdict(
            p, False, "a named test did not run with the patch (compile error?)", base, patched
        )
    if p.kind == "red":
        bad = [n for n in names if patched[n] not in ("FAILED", "ERROR")]
        why = f"stayed green: {', '.join(bad)}" if bad else "every named test went red"
        return Verdict(p, not bad, why, base, patched)
    bad = [n for n in names if patched[n] != "ok"]
    why = f"went red: {', '.join(bad)}" if bad else "every named test stayed green"
    return Verdict(p, not bad, why, base, patched)


def run(root: Path, only: list[str]) -> tuple[str, bool, list[Verdict]]:
    """Runs the proofs on the committed HEAD. The proof directory itself is copied from the
    working tree, so a new proof can be tried before it is committed; ``dirty`` says so."""
    head = _sh(["git", "rev-parse", "HEAD"], root).stdout.strip()
    dirty = bool(_sh(["git", "status", "--porcelain", "--", str(MANIFEST.parent)], root).stdout)
    target = root / "target" / "proofs"
    logs = target / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    verdicts: list[Verdict] = []
    with tempfile.TemporaryDirectory(prefix="sever-proofs-") as tmp:
        wt = Path(tmp) / "wt"
        _sh(["git", "worktree", "add", "--detach", str(wt), head], root).check_returncode()
        try:
            shutil.rmtree(wt / MANIFEST.parent, ignore_errors=True)
            shutil.copytree(root / MANIFEST.parent, wt / MANIFEST.parent)
            proofs = [p for p in load(wt) if not only or p.id in only]
            # One baseline per runner and package, over every test its proofs name.
            groups: dict[tuple[str, str], list[str]] = {}
            for p in proofs:
                names = groups.setdefault((p.runner, p.package), [])
                names.extend(t for t in p.tests if t not in names)
            baselines: dict[tuple[str, str], dict[str, str]] = {}
            for (runner, package), tests in groups.items():
                probe = Proof("baseline", "", "red", [], "", runner, tests, package)
                baselines[(runner, package)], blog = _outcomes(probe, wt, target)
                (logs / f"baseline-{runner}-{package or 'python'}.log").write_text(
                    blog, encoding="utf-8"
                )
            for p in proofs:
                base = baselines[(p.runner, p.package)]
                patch = (wt / MANIFEST.parent / p.patch).resolve()
                applied = _sh(["git", "apply", str(patch)], wt).returncode == 0
                patched, plog = _outcomes(p, wt, target) if applied else ({}, "")
                _sh(["git", "checkout", "--", "."], wt)
                v = _judge(p, base, patched, applied)
                verdicts.append(v)
                (logs / f"{p.id}.log").write_text(plog, encoding="utf-8")
                print(f"{p.id}: {'PROVEN' if v.ok else 'NOT PROVEN'} ({v.why})", flush=True)
        finally:
            _sh(["git", "worktree", "remove", "--force", str(wt)], root)
    return head, dirty, verdicts


def report(head: str, dirty: bool, verdicts: list[Verdict], unproven_pairs: list[str]) -> str:
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")
    proven = sum(v.ok for v in verdicts)
    lines = [
        "# Proofs, Part 2",
        "",
        "Generated by `python -m sever_testkit_p2.proofs run` (CLAUDE.md §6.3). Do not edit.",
        "",
        f"Commit `{head}`{' (proofs not yet committed)' if dirty else ''}, run {now}. "
        f"**{proven} of {len(verdicts)} proofs hold.**",
        "",
        "Each proof applies one patch (`tests/proofs/p2/`) to that commit in a temporary worktree.",
        "**red**: the named tests pass without it and fail with it, so their label can fail.",
        "**green**: the named tests pass with and without it although it breaks the rule, so the",
        "label was removed. Re-run any proof: `… proofs run --only <ID>`.",
        "",
        "| Proof | Kind | Requirements | Claim | Verdict | Tests: without → with the patch |",
        "|---|---|---|---|---|---|",
    ]
    for v in verdicts:
        p = v.proof
        ev = "<br>".join(
            f"`{_short(t)}`: {v.baseline.get(_short(t), '—')} → {v.patched.get(_short(t), '—')}"
            for t in p.tests
        )
        verdict = "**holds**" if v.ok else f"**FAILS**: {v.why}"
        claim = p.claim.replace("|", "\\|")
        lines.append(
            f"| {p.id} | {p.kind} | {', '.join(p.requirements)} | {claim} | {verdict} | {ev} |"
        )
    lines += ["", "## Labels without a red proof", ""]
    lines += [f"- {u}" for u in unproven_pairs] if unproven_pairs else ["None."]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="proofs", description=__doc__)
    ap.add_argument("command", choices=["run", "check"])
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--only", nargs="*", default=[])
    args = ap.parse_args(argv)
    root: Path = args.root
    audit = oracle_check.collect(root)
    proofs = load(root)
    probs = problems(root, proofs, audit)
    pairs = unproven(proofs, audit)
    if args.command == "check":
        for x in probs + [f"no red proof: {u}" for u in pairs]:
            print(x, file=sys.stderr)
        print(f"Part 2: {len(proofs)} proofs; {len(pairs)} label(s) without a red proof")
        return 1 if probs or pairs else 0
    if probs:
        for x in probs:
            print(x, file=sys.stderr)
        return 1
    head, dirty, verdicts = run(root, args.only)
    if not args.only:
        (root / REPORT).write_text(report(head, dirty, verdicts, pairs), encoding="utf-8")
        print(root / REPORT)
    return 0 if all(v.ok for v in verdicts) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
