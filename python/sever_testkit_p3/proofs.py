"""``proofs`` for Part 3 (CLAUDE.md §6.3): re-runnable evidence for every claim about a Part 3 test.

    PYTHONPATH=python uv run python -m sever_testkit_p3.proofs run [--only PR-1 PR-2 …]
    PYTHONPATH=python uv run python -m sever_testkit_p3.proofs check

The rules are Part 2's (``sever_testkit_p2.proofs``): a proof is a patch in ``tests/proofs/p3/``
that breaks one rule, and the tests it names; ``red`` (each named test passes without the patch and
fails with it), ``green`` and ``limit`` as there; ``check`` is static (Fast CI) and needs a red
proof for every (test, label) pair of a labelled Part 3 test; ``run`` applies each patch to the
committed HEAD in a temporary worktree and writes ``docs/PROOFS_P3.md``.

One field is new: ``workspace`` (``verifier`` or ``audit``) runs a cargo proof in that separate
workspace instead of the root one (Build 3-4 §1.4, §1.6). The builds are Part 3's: ``cli`` builds
``sever-p3``, ``native`` the ``sever-py-p3`` wheel.
"""

import argparse
import datetime
import os
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

from sever_testkit_p2.oracle_check import Audit
from sever_testkit_p2.proofs import (
    CARGO_LINE,
    PYTEST_LINE,
    Proof,
    Verdict,
    _judge,
    _link_missing,
    _sh,
    _short,
    unproven,
)
from sever_testkit_p2.proofs import problems as p2_problems
from sever_testkit_p3 import oracle_check

__all__ = ["Proof3", "load", "main", "problems", "report", "run", "unproven"]

MANIFEST: Final = Path("tests/proofs/p3/MANIFEST.yaml")
REPORT: Final = Path("docs/PROOFS_P3.md")
WORKSPACES: Final = ("", "verifier", "audit")
CLI_PACKAGE: Final = "sever-p3"
SDK_CRATE: Final = "crates/sever-py-p3/Cargo.toml"
#: Proofs share a baseline when runner, package, build and workspace agree.
GroupKey = tuple[str, str, tuple[str, ...], str]


@dataclass
class Proof3(Proof):
    """A Part 2 proof entry, plus the cargo workspace it runs in (``""``: the root one)."""

    workspace: str = ""


def load(root: Path) -> list[Proof3]:
    raw: list[dict[str, Any]] = yaml.safe_load((root / MANIFEST).read_text(encoding="utf-8")) or []
    return [
        Proof3(
            id=str(e["id"]),
            claim=str(e["claim"]),
            kind=str(e["kind"]),
            requirements=[str(r) for r in e.get("requirements", [])],
            patch=str(e["patch"]),
            runner=str(e.get("runner", "cargo")),
            tests=[str(t) for t in e["tests"]],
            package=str(e.get("package", "")),
            env={str(k): str(v) for k, v in (e.get("env") or {}).items()},
            build=tuple(str(b) for b in e.get("build") or ()),
            workspace=str(e.get("workspace", "")),
        )
        for e in raw
    ]


def problems(root: Path, proofs: list[Proof3], audit: Audit) -> list[str]:
    """Part 2's static checks, with patches looked up in ``tests/proofs/p3/``."""
    # Part 2's check looks for each patch in tests/proofs/p2/; drop exactly that message and look
    # in Part 3's directory instead.
    p2_missing = {f"{p.id}: patch {p.patch} is missing" for p in proofs}
    out = [x for x in p2_problems(root, list(proofs), audit) if x not in p2_missing]
    for p in proofs:
        if not (root / MANIFEST.parent / p.patch).is_file():
            out.append(f"{p.id}: patch {p.patch} is missing")
        if p.workspace not in WORKSPACES:
            out.append(f"{p.id}: workspace {p.workspace!r} is not one of {WORKSPACES}")
        if p.workspace and p.runner != "cargo":
            out.append(f"{p.id}: only a cargo proof names a workspace")
    return out


# ---------------------------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------------------------


def _prepare(p: Proof3, wt: Path, env: dict[str, str], data_root: Path) -> tuple[bool, str]:
    """Builds what ``p.build`` asks for inside ``wt``; returns success and the build log."""
    log = ""
    if "data" in p.build:
        _link_missing(data_root / "datasets" / "processed", wt / "datasets" / "processed")
        _link_missing(data_root / "artefacts", wt / "artefacts")
    if "cli" in p.build:
        r = _sh(["nice", "-n", "19", "cargo", "build", "-q", "-j", "2", "--release",
                 "-p", CLI_PACKAGE], wt, env)  # fmt: skip
        log += r.stdout + r.stderr
        if r.returncode != 0:
            return False, log
    if "native" in p.build:
        wheels, native = wt / ".proof-wheels", wt / ".proof-native"
        shutil.rmtree(wheels, ignore_errors=True)
        shutil.rmtree(native, ignore_errors=True)
        r = _sh(
            ["nice", "-n", "19", sys.executable, "-m", "maturin", "build", "--release", "-q",
             "-m", SDK_CRATE, "-o", str(wheels)],
            wt,
            env,
        )  # fmt: skip
        log += r.stdout + r.stderr
        built = sorted(wheels.glob("*.whl"))
        if r.returncode != 0 or not built:
            return False, log
        with zipfile.ZipFile(built[-1]) as z:
            z.extractall(native)
        env["PYTHONPATH"] = f"{native}{os.pathsep}{env['PYTHONPATH']}"
    return True, log


def _outcomes(p: Proof3, wt: Path, target: Path) -> tuple[dict[str, str], str]:
    """Runs ``p``'s tests in worktree ``wt``; returns ``{test: ok|FAILED|…}`` and the raw log."""
    env = dict(os.environ, CARGO_TARGET_DIR=str(target / (p.workspace or "root")),
               PYTHONHASHSEED="0", PYTHONPATH="python")  # fmt: skip
    env.update(p.env)
    if p.build:
        data_root = Path(os.environ.get("SEVER_DATA_ROOT", str(target.parent.parent)))
        ok, blog = _prepare(p, wt, env, data_root)
        if not ok:
            return {}, blog
    got: dict[str, str] = {}
    if p.runner == "cargo":
        names = [_short(t) for t in p.tests]
        cmd = ["nice", "-n", "19", "cargo", "test", "-j", "2", "-p", p.package, "--no-fail-fast"]
        r = _sh([*cmd, "--", *names], wt / p.workspace, env)
        log = r.stdout + r.stderr
        for line in log.splitlines():
            m = CARGO_LINE.match(line)
            if m:
                for n in names:
                    if m.group(1) == n or m.group(1).endswith("::" + n):
                        got[n] = m.group(2)
        return got, log
    r = _sh(["nice", "-n", "19", sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider",
             *p.tests], wt, env)  # fmt: skip
    log = r.stdout + r.stderr
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


def run(root: Path, only: list[str]) -> tuple[str, bool, list[Verdict]]:
    """Runs the proofs on the committed HEAD. The proof directory itself is copied from the
    working tree, so a new proof can be tried before it is committed; ``dirty`` says so."""
    head = _sh(["git", "rev-parse", "HEAD"], root).stdout.strip()
    dirty = bool(_sh(["git", "status", "--porcelain", "--", str(MANIFEST.parent)], root).stdout)
    # Absolute: cargo runs inside the temporary worktree, and the cache is shared between runs.
    target = root.resolve() / "target" / "proofs-p3"
    logs = target / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    verdicts: list[Verdict] = []
    with tempfile.TemporaryDirectory(prefix="sever-proofs-p3-") as tmp:
        wt = Path(tmp) / "wt"
        _sh(["git", "worktree", "add", "--detach", str(wt), head], root).check_returncode()
        try:
            shutil.rmtree(wt / MANIFEST.parent, ignore_errors=True)
            shutil.copytree(root / MANIFEST.parent, wt / MANIFEST.parent)
            proofs = [p for p in load(wt) if not only or p.id in only]
            # The worktree's target/ is the shared cache, so CLI paths under target/ resolve.
            (wt / "target").symlink_to(target / "root", target_is_directory=True)
            # One baseline per runner, package, build and workspace, over every test it names.
            groups: dict[GroupKey, list[str]] = {}
            for p in proofs:
                names = groups.setdefault((p.runner, p.package, p.build, p.workspace), [])
                names.extend(t for t in p.tests if t not in names)
            baselines: dict[GroupKey, dict[str, str]] = {}
            for key, tests in groups.items():
                runner, package, build, workspace = key
                probe = Proof3("baseline", "", "red", [], "", runner, tests, package, build=build,
                               workspace=workspace)  # fmt: skip
                baselines[key], blog = _outcomes(probe, wt, target)
                tag = "-".join([runner, workspace or "root", package or "python", *build])
                (logs / f"baseline-{tag}.log").write_text(blog, encoding="utf-8")
            for p in proofs:
                base = baselines[(p.runner, p.package, p.build, p.workspace)]
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
        "# Proofs, Part 3",
        "",
        "Generated by `python -m sever_testkit_p3.proofs run` (CLAUDE.md §6.3). Do not edit.",
        "",
        f"Commit `{head}`{' (proofs not yet committed)' if dirty else ''}, run {now}. "
        f"**{proven} of {len(verdicts)} proofs hold.**",
        "",
        "Each proof applies one patch (`tests/proofs/p3/`) to that commit in a temporary worktree.",
        "**red**: the named tests pass without it and fail with it, so their label can fail.",
        "**green**: the named tests pass with and without it although it breaks the rule, so the",
        "label was removed. **limit**: the same for a test that keeps its label (a red proof",
        "covers it), recording what the test does not notice.",
        "Re-run any proof: `… proofs run --only <ID>`.",
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
    ap = argparse.ArgumentParser(prog="proofs-p3", description=__doc__)
    ap.add_argument("command", choices=["run", "check"])
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--only", nargs="*", default=[])
    args = ap.parse_args(argv)
    root: Path = args.root
    audit = oracle_check.collect(root)
    proofs = load(root)
    probs = problems(root, proofs, audit)
    pairs = unproven(list(proofs), audit)
    if args.command == "check":
        # A patch that no longer applies proves nothing: the code it breaks has moved.
        for patch in sorted({p.patch for p in proofs}):
            path = (root / MANIFEST.parent / patch).resolve()
            if _sh(["git", "apply", "--check", str(path)], root).returncode != 0:
                probs.append(f"{patch}: no longer applies to the working tree")
        for x in probs + [f"no red proof: {u}" for u in pairs]:
            print(x, file=sys.stderr)
        print(f"Part 3: {len(proofs)} proofs; {len(pairs)} label(s) without a red proof")
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
