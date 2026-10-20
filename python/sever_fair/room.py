"""Stage 0: the room, the sealed engine and the real engine (FT-1, FT-3).

The room holds what the spec says a stranger may know: the spec documents, the part's public API
documentation and type stub, and input artefacts. The sealed engine has the real API's names and
signatures, generated from the type stub, but every call raises ``EngineSealed``. The real engine is
the release CLI and native module built from the run's commit in a worktree the sandbox never sees.
"""

import ast
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import config

SEALED_MSG = "EngineSealed: the engine answers only after the tests are sealed (FT-3)"


def sh(
    cmd: list[str], cwd: Path, log: Path, env: dict[str, str] | None = None, timeout: int = 7200
) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as f:
        f.write(("\n$ " + " ".join(cmd) + "\n").encode())
        f.flush()
        try:
            return subprocess.run(
                cmd,
                cwd=cwd,
                stdout=f,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                env={k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"} | (env or {}),
            ).returncode
        except subprocess.TimeoutExpired:
            f.write(b"\n[sever_fair] TIMEOUT\n")
            return 124


def must(rc: int, what: str, log: Path) -> None:
    if rc != 0:
        raise SystemExit(f"{what} failed (rc {rc}); log: {log}")


def excerpt(text: str, start: str, stop: str) -> str:
    i = text.index(start)
    j = text.index(stop, i)
    return text[i:j]


def main_checkout(repo: Path) -> Path:
    """The repository's main working tree (generated data such as ``artefacts/`` lives there)."""
    common = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(common.stdout.strip()).parent


def build_room(repo: Path, part: dict[str, Any], room: Path, data_roots: list[Path]) -> None:
    """Copies the spec, API docs and API files (from the run's commit) and the inputs into a fresh
    room. Inputs that are generated data, not tracked by git, come from the first of
    ``data_roots`` that has them."""
    for sub in ("spec", "api", "inputs", "work/tests", "out"):
        (room / sub).mkdir(parents=True, exist_ok=True)
    for doc in part["docs"]:
        shutil.copy2(repo / doc, room / "spec" / Path(doc).name)
    for d in part["api_docs"]:
        text = (repo / d["file"]).read_text(encoding="utf-8")
        (room / "api" / d["as"]).write_text(excerpt(text, d["from"], d["to"]), encoding="utf-8")
    for f in part["api_files"]:
        src = repo / f
        name = src.name if src.name != "__init__.py" else src.parent.name + ".py"
        shutil.copy2(src, room / "api" / name)
    for f in part["inputs"]:
        src = next((r / f for r in [repo, *data_roots] if (r / f).exists()), None)
        if src is None:
            raise SystemExit(f"input {f} not found in {[str(r) for r in [repo, *data_roots]]}")
        shutil.copy2(src, room / "inputs" / Path(f).name)


class _Seal(ast.NodeTransformer):
    """Turns a type stub into a module whose every function raises EngineSealed."""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        node.body = [ast.parse(f"raise EngineSealed({SEALED_MSG!r})").body[0]]
        return node


def sealed_module(stub: str) -> str:
    tree = ast.parse(stub)
    tree = _Seal().visit(tree)
    head = ast.parse(
        "class EngineSealed(Exception):\n    'The engine is sealed until the tests are (FT-3).'\n"
    ).body
    future = ast.parse("from __future__ import annotations").body
    tree.body = (
        future
        + [n for n in tree.body if isinstance(n, ast.ImportFrom | ast.Import)]
        + head
        + [n for n in tree.body if not isinstance(n, ast.ImportFrom | ast.Import | ast.Expr)]
    )
    ast.fix_missing_locations(tree)
    return (
        '"""Sealed engine (FT-3): the real API\'s names; every call raises."""\n'
        + ast.unparse(tree)
        + "\n"
    )


def build_sealed(repo: Path, part: dict[str, Any], site: Path, bindir: Path) -> None:
    sdk = part["sdk"]
    site.mkdir(parents=True, exist_ok=True)
    native = site / sdk["native"]
    native.mkdir(exist_ok=True)
    (native / "__init__.py").write_text(
        sealed_module((repo / sdk["stub"]).read_text(encoding="utf-8")), encoding="utf-8"
    )
    shutil.copytree(
        repo / sdk["package"],
        site / Path(sdk["package"]).name,
        ignore=shutil.ignore_patterns("tests", "__pycache__"),
    )
    bindir.mkdir(parents=True, exist_ok=True)
    for b in part["cli"]["bins"]:
        p = bindir / b
        p.write_text(f"#!/bin/sh\necho '{SEALED_MSG}' >&2\nexit 99\n", encoding="utf-8")
        p.chmod(0o755)


def make_venv(venv: Path, log: Path) -> None:
    """The room's Python: pytest, hypothesis and numpy, nothing of the project."""
    if (venv / "pyvenv.cfg").exists():
        return
    must(sh(["uv", "venv", "-q", "--python", "3.13", str(venv)], venv.parent, log), "uv venv", log)
    must(
        sh(
            [
                "uv",
                "pip",
                "install",
                "-q",
                "--python",
                str(venv / "bin/python"),
                "pytest",
                "hypothesis",
                "numpy==2.5.*",
            ],
            venv.parent,
            log,
        ),
        "uv pip install",
        log,
    )


def worktree(repo: Path, wt: Path, commit: str, log: Path) -> None:
    """A detached worktree of ``commit`` with the project's environment."""
    if not wt.exists():
        must(
            sh(["git", "worktree", "add", "-q", "--detach", str(wt), commit], repo, log),
            "git worktree add",
            log,
        )
    must(sh(["uv", "sync", "-q", "--frozen"], wt, log), "uv sync", log)


def build(wt: Path, part: dict[str, Any], log: Path) -> int:
    """Release CLI, plus every part's native module installed into the worktree's .venv: the
    part's own suite re-runs every earlier part's tests (F-5), and the repository's Python suite
    imports each part's SDK."""
    bins = [x for b in part["cli"]["bins"] for x in ("--bin", b)]
    e = {"PYTHONHASHSEED": "0"}
    rc = sh(["cargo", "build", "-q", "--release", "-p", part["cli"]["package"], *bins], wt, log, e)
    if rc:
        return rc
    parts = config.load(wt).raw["parts"].values()
    crates = [part["sdk"]["crate"]] + [
        c for c in dict.fromkeys(p["sdk"]["crate"] for p in parts) if c != part["sdk"]["crate"]
    ]
    for crate in crates:
        if not (wt / crate).exists():
            continue
        maturin = ["uv", "run", "--no-sync", "maturin", "develop", "-q", "--release", "--uv"]
        rc = sh([*maturin, "-m", crate], wt, log, e)
        if rc:
            return rc
    return 0


def own_suite(wt: Path, part: dict[str, Any], log: Path) -> tuple[bool, list[dict[str, Any]]]:
    """The part's own suite (configs/fair.yaml ``own_suite``); green when every command passes."""
    import time

    detail = []
    green = True
    for cmd in part["own_suite"]:
        t0 = time.monotonic()
        rc = sh(list(cmd), wt, log, {"PYTHONHASHSEED": "0", "PYTHONPATH": "python"}, timeout=5400)
        detail.append({"cmd": " ".join(cmd), "rc": rc, "seconds": round(time.monotonic() - t0)})
        green &= rc == 0
    return green, detail


def export_engine(wt: Path, part: dict[str, Any], site: Path, bindir: Path) -> None:
    """Copies the built engine into a site folder and a bin folder for the sandbox."""
    if site.exists():
        shutil.rmtree(site)
    if bindir.exists():
        shutil.rmtree(bindir)
    sdk = part["sdk"]
    pkgs = next((wt / ".venv/lib").glob("python3.*/site-packages"))
    shutil.copytree(
        pkgs / sdk["native"], site / sdk["native"], ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(
        wt / sdk["package"],
        site / Path(sdk["package"]).name,
        ignore=shutil.ignore_patterns("tests", "__pycache__"),
    )
    bindir.mkdir(parents=True)
    for b in part["cli"]["bins"]:
        shutil.copy2(wt / "target/release" / b, bindir / b)
