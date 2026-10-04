"""Architecture rules (CLAUDE.md §7): the verifier shares no code with the engine.

Both live under python/ (sever_demo, sever_verify); these tests keep them apart."""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_verifier_never_imports_the_engine() -> None:
    files = list((REPO / "python" / "sever_verify").rglob("*.py"))
    assert files, "python/sever_verify has no Python files"
    for f in files:
        bad = {m for m in imported_modules(f) if m.split(".")[0] == "sever_demo"}
        assert not bad, f"{f.relative_to(REPO)} imports {bad}"


def test_engine_never_imports_the_verifier() -> None:
    # The engine must not lean on the verifier's code either (else the two are not independent).
    for f in (REPO / "python" / "sever_demo").rglob("*.py"):
        bad = {m for m in imported_modules(f) if m.split(".")[0] == "sever_verify"}
        assert not bad, f"{f.relative_to(REPO)} imports {bad}"
