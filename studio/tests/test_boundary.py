"""Studio uses SEVER-DB only as a company's application would (DB-119).

Oracle A: DB-119 and the plan's Stage 6.1. Studio imports only the SDK (``sever_db``), never the
native module, the partition builder, the demos or the test kits; it never runs ``cargo``; and no
string in its code names a repository folder (``crates/``, ``python/``, ``spec/``, ``docs/``,
``results/``) or climbs to the repository root. ``studio.sh`` is the one bridge and is not checked.
"""

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parents[1]
FILES = sorted(
    p
    for d in ("sever_studio", "tests")
    for p in (STUDIO / d).rglob("*.py")
    if p.name != "test_boundary.py"
)
FORBIDDEN_MODULES = ("sever_db_native", "sever_partition", "sever_demo", "sever_testkit")
REPO_PATH = re.compile(r"(?<![\w.\-])(crates|python|spec|docs|results)/")


def imports(tree: ast.AST) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append(node.module)
    return out


def strings(source: str) -> list[str]:
    toks = tokenize.generate_tokens(io.StringIO(source).readline)
    return [t.string for t in toks if t.type in (tokenize.STRING, tokenize.FSTRING_MIDDLE)]


def offences(path: Path) -> list[str]:
    source = path.read_text("utf-8")
    out = [
        f"imports {m}"
        for m in imports(ast.parse(source))
        if m.split(".")[0].startswith(FORBIDDEN_MODULES)
    ]
    for s in strings(source):
        if re.search(r"\bcargo\b", s):
            out.append(f"runs cargo: {s[:60]!r}")
        if m := REPO_PATH.search(s):
            out.append(f"names the repository's {m[0]}: {s[:60]!r}")
    if "parents[2]" in source:
        out.append("climbs to the repository root (parents[2])")
    return out


def test_boundary_scans_every_file_of_studio() -> None:
    assert len(FILES) > 30
    assert STUDIO / "sever_studio/actions.py" in FILES


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(STUDIO)))
def test_boundary_studio_uses_only_the_sdk_and_its_config(path: Path) -> None:
    assert offences(path) == []


def test_boundary_the_guard_catches_each_kind_of_offence(tmp_path: Path) -> None:
    # a guard that never fails proves nothing: each line below must be caught
    bad = {
        "import sever_db_native\n": "imports",
        "from sever_partition.artefact import decode\n": "imports",
        "import sever_testkit_p3.gates\n": "imports",
        'cmd = ["cargo", "build"]\n': "cargo",
        'p = root / "spec/registers_p3.yaml"\n': "spec/",
        'p = root / "docs/RUN_LEDGER.jsonl"\n': "docs/",
        'p = f"{root}/crates/sever-py"\n': "crates/",
        "ROOT = Path(__file__).resolve().parents[2]\n": "parents[2]",
    }
    for line, kind in bad.items():
        f = tmp_path / "probe.py"
        f.write_text("from pathlib import Path\n" + line, "utf-8")
        found = offences(f)
        assert any(kind in o for o in found), (line, found)
    ok = tmp_path / "ok.py"
    ok.write_text('import sever_db\np = data / "datasets/processed/nq_1m"\n', "utf-8")
    assert offences(ok) == []
