"""Pure checks of the fair-testing system: seal, test results, test extraction, diff guards."""

import ast
import fnmatch
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# ---- FT-3: the seal -----------------------------------------------------------------------------


def seal(folder: Path) -> dict[str, str]:
    """SHA-256 of every file under ``folder``, by relative path (caches excluded)."""
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts
    }


def seal_digest(sealed: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(sealed, sort_keys=True).encode()).hexdigest()


def seal_broken(folder: Path, sealed: dict[str, str]) -> list[str]:
    """Paths whose bytes differ from the seal (added, removed or changed)."""
    now = seal(folder)
    return sorted(k for k in now.keys() | sealed.keys() if now.get(k) != sealed.get(k))


# ---- test results -------------------------------------------------------------------------------


def junit(path: Path) -> dict[str, dict[str, str]]:
    """``{test id: {"outcome": passed|failed|error|skipped, "message": …}}`` from a JUnit file."""
    out: dict[str, dict[str, str]] = {}
    if not path.exists():
        return out
    for case in ET.parse(path).getroot().iter("testcase"):
        tid = f"{case.get('classname', '')}::{case.get('name', '')}"
        outcome, message = "passed", ""
        for child in case:
            if child.tag in ("failure", "error", "skipped"):
                outcome = {"failure": "failed"}.get(child.tag, child.tag)
                message = ((child.get("message") or "") + "\n" + (child.text or ""))[-6000:]
        out[tid] = {"outcome": outcome, "message": message}
    return out


def failing(results: dict[str, dict[str, str]]) -> set[str]:
    return {t for t, r in results.items() if r["outcome"] in ("failed", "error")}


# ---- FT-7: labelled tests of the part's own suite -----------------------------------------------

RUST_SPEC = re.compile(r"#\[spec\(([^)]*)\)\]")
SR_ID = re.compile(r"SR-[0-9.]+-[0-9]+")


def python_labelled(path: Path) -> list[dict[str, Any]]:
    """Test functions carrying ``@pytest.mark.spec(...)``, with their source."""
    text = path.read_text(encoding="utf-8")
    found: list[dict[str, Any]] = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        ids: list[str] = []
        for dec in node.decorator_list:
            src = ast.get_source_segment(text, dec) or ""
            if ".spec(" in src:
                ids += SR_ID.findall(src)
        if ids:
            seg = ast.get_source_segment(text, node) or ""
            found.append({"name": node.name, "ids": ids, "source": seg})
    return found


def rust_labelled(path: Path) -> list[dict[str, Any]]:
    """Rust tests carrying ``#[spec("...")]``, with their source (brace matched)."""
    text = path.read_text(encoding="utf-8")
    found: list[dict[str, Any]] = []
    for m in RUST_SPEC.finditer(text):
        fn = re.compile(r"\bfn\s+(\w+)").search(text, m.end())
        if fn is None:
            continue
        open_at = text.find("{", fn.end())
        depth, i = 0, open_at
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        found.append(
            {
                "name": fn.group(1),
                "ids": SR_ID.findall(m.group(1)),
                "source": text[m.start() : i + 1],
            }
        )
    return found


def labelled_tests(root: Path, ids: set[str]) -> list[dict[str, Any]]:
    """Every labelled test (Python and Rust) whose requirement IDs meet ``ids``."""
    out: list[dict[str, Any]] = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if rel.parts[0] in (".venv", "target", "demo") or "cleanroom" in rel.parts:
            continue
        if p.name.startswith("test_"):
            out += [t | {"file": str(rel)} for t in python_labelled(p) if ids & set(t["ids"])]
    for p in sorted(root.glob("crates/*/**/*.rs")):
        rel = p.relative_to(root)
        if "target" in rel.parts:
            continue
        out += [t | {"file": str(rel)} for t in rust_labelled(p) if ids & set(t["ids"])]
    return out


# ---- FT-9: diff guards --------------------------------------------------------------------------

TEST_PATHS = ("tests/*", "crates/*/tests/*", "python/*/tests/*", "fuzz*/seeds/*")
NEVER_TOUCH = (
    "tests/cleanroom/*",
    "docs/audit/*",
    "golden/*",
    "freeze/*",
    "configs/*",
    "results/*",
    "docs/RUN_LEDGER.jsonl",
    "python/sever_fair/*",
    "scripts/fair.sh",
    "scripts/freeze.sh",
    "scripts/ci.sh",
)
SPEC = "docs/SEVER-DB_SPECIFICATION.md"
GAPS = "docs/SPEC_GAPS.md"
OVERVIEW = "docs/SEVER-DB_PROJECT_OVERVIEW.md"


def _any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def is_test_path(path: str) -> bool:
    return _any(path, TEST_PATHS) and not path.startswith("tests/cleanroom/")


def guard_test_change(paths: list[str]) -> list[str]:
    """Step 1 of a fix may add or change test files only (FT-9)."""
    v = [f"{p}: not a test file" for p in paths if not is_test_path(p)]
    v += [f"{p}: never touched by a fix" for p in paths if _any(p, NEVER_TOUCH)]
    return v


def guard_fix_change(paths: list[str], frozen: set[str]) -> list[str]:
    """Step 2 of a fix: no tests, no protected paths, no frozen files, spec only with its gap."""
    v = [f"{p}: a fix may not change tests" for p in paths if is_test_path(p)]
    v += [f"{p}: never touched by a fix" for p in paths if _any(p, NEVER_TOUCH)]
    v += [f"{p}: file of a frozen part (erratum, F-6: owner)" for p in paths if p in frozen]
    if SPEC in paths and not (GAPS in paths and OVERVIEW in paths):
        v.append(f"{SPEC} changed without both {GAPS} and {OVERVIEW} (CLAUDE.md §2)")
    return v


def guard_gap_change(paths: list[str]) -> list[str]:
    """A spec-gap fix changes exactly the spec, the gap list and the decision register."""
    want = {SPEC, GAPS, OVERVIEW}
    v = [f"{p}: a gap fix changes only {sorted(want)}" for p in paths if p not in want]
    v += [f"{p}: missing from a gap fix" for p in sorted(want - set(paths))]
    return v


def patch_files(patch: str) -> list[str]:
    """Paths a unified diff touches."""
    files = set()
    for line in patch.splitlines():
        if line.startswith(("+++ b/", "--- a/")):
            files.add(line[6:].strip())
    return sorted(files)


def plant_violations(files: list[str], plant_paths: list[str]) -> list[str]:
    """A planted bug must sit inside the plant paths and outside test code (FT-6)."""
    v = []
    for f in files:
        inside = any(f == p or f.startswith(p.rstrip("/") + "/") for p in plant_paths)
        if not inside:
            v.append(f"{f}: outside the plant paths")
        elif "/tests/" in f or f.endswith("/tests.rs"):
            v.append(f"{f}: test code")
    return v


# ---- judge outputs ------------------------------------------------------------------------------


def verdicts(
    path: Path, key: str, expected: set[str], allowed: set[str]
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Loads a judge's JSON list; returns verdicts by ``key`` and every problem found."""
    problems: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {}, [f"{path.name}: unreadable ({e.__class__.__name__})"]
    out: dict[str, dict[str, str]] = {}
    for item in data if isinstance(data, list) else []:
        k = str(item.get(key, ""))
        if item.get("verdict") not in allowed:
            problems.append(f"{k}: verdict {item.get('verdict')!r} not in {sorted(allowed)}")
        elif k in out:
            problems.append(f"{k}: judged twice")
        else:
            out[k] = {
                "verdict": str(item["verdict"]),
                "section": str(item.get("section", "")),
                "reason": str(item.get("reason", "")),
            }
    problems += [f"{k}: no verdict" for k in sorted(expected - out.keys())]
    problems += [f"{k}: judged but not asked" for k in sorted(out.keys() - expected)]
    return out, problems
