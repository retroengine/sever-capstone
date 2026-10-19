"""L13 architecture tests (Build §2.1, §4.4; CLAUDE.md §7).

The core has no I/O, clock or randomness; dependencies point only from later parts to earlier ones;
unsafe code only where listed; the engine fits nothing; the Python packages keep their layering.
"""

import ast
import json
import re
import subprocess
from functools import cache
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Build §4.4: no file I/O, clock, networking or random-number source in these crates.
CORE = ("sever-types", "sever-quant", "sever-index", "sever-search", "sever-partition")
#: The part that owns each crate (Build §3.2). A new crate must be added here, with its part.
PART = {
    "sever-types": 1,
    "sever-quant": 1,
    "sever-partition": 1,
    "sever-index": 1,
    "sever-search": 1,
    "sever-tracekit": 1,
    "sever-p1": 1,
    "sever-spec": 1,
    # Part 2 (Build §3.2)
    "sever-vfs": 2,
    "sever-format": 2,
    "sever-wal": 2,
    "sever-appendstore": 2,
    "sever-checkpoint": 2,
    "sever-txn": 2,
    "sever-engine": 2,
    "sever-crashkit": 2,
    "sever-p2": 2,
    "sever-py-p2": 2,
    # Part 3 (Build 3-4 §1.4)
    "sever-crypto": 3,
    "sever-commit": 3,
    "sever-log": 3,
    "sever-cert": 3,
    "sever-p3": 3,
    "sever-py-p3": 3,
    "sever-crashkit-p3": 3,
    # Part 4 (Build 3-4 §2.4)
    "sever-keys": 4,
    "sever-seal": 4,
    "sever-erasure": 4,
    "sever-platform": 4,
    "sever-db": 4,
    "sever-scan": 4,
    "sever-py": 4,
    "sever-crashkit-p4": 4,
    "sever-eval": 4,
}
#: Composition roots and tooling: nothing in the core may depend on them.
OUTER = (
    "sever-p1", "sever-tracekit", "sever-crashkit", "sever-p2", "sever-py-p2", "sever-p3",
    "sever-py-p3", "sever-crashkit-p3", "sever-crashkit-p4", "sever-eval",
)  # fmt: skip
#: Build §1.2: `unsafe` only in the SIMD kernel (later parts add mlock).
UNSAFE_ALLOWED = {"crates/sever-search/src/kernel.rs"}
#: Crates that would bring I/O, time, networking, randomness or model fitting into the core.
FORBIDDEN_CRATES = re.compile(
    r"^(rand|rand_core|rand_chacha|getrandom|chrono|time|tokio|async-std|mio|hyper|reqwest|ureq|"
    r"memmap2?|linfa.*|smartcore|ndarray-linalg|nalgebra|faer)$"
)
FORBIDDEN_SOURCE = re.compile(
    r"\bstd::(fs|net|time|env|process|thread)\b|\bFile::|\bSystemTime\b|\bInstant\b|\bOsRng\b|"
    r"\bthread_rng\b"
)


@cache
def metadata() -> dict[str, Any]:
    out = subprocess.run(
        ["cargo", "metadata", "--format-version", "1", "--locked"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    data: dict[str, Any] = json.loads(out)
    return data


def normal_closure(name: str) -> set[str]:
    """Every crate `name` depends on at run time (normal edges, transitively)."""
    md = metadata()
    by_id = {p["id"]: p for p in md["packages"]}
    nodes = {n["id"]: n for n in md["resolve"]["nodes"]}
    start = next(p["id"] for p in md["packages"] if p["name"] == name and p["source"] is None)
    seen: set[str] = set()
    todo = [start]
    while todo:
        cur = todo.pop()
        for dep in nodes[cur]["deps"]:
            if any(k["kind"] is None for k in dep["dep_kinds"]) and dep["pkg"] not in seen:
                seen.add(dep["pkg"])
                todo.append(dep["pkg"])
    return {by_id[i]["name"] for i in seen}


def workspace_crates() -> list[dict[str, Any]]:
    return [p for p in metadata()["packages"] if p["source"] is None]


@pytest.mark.spec("SR-6.1-1")
@pytest.mark.parametrize("crate", CORE)
def test_p1_arch_core_has_no_io_clock_rng_or_fitting_dependency(crate: str) -> None:
    bad = sorted(c for c in normal_closure(crate) if FORBIDDEN_CRATES.match(c))
    assert not bad, f"{crate} depends on {bad}"


@pytest.mark.parametrize("crate", CORE)
def test_p1_arch_core_source_has_no_io_clock_or_rng(crate: str) -> None:
    hits = []
    for p in sorted((ROOT / "crates" / crate / "src").rglob("*.rs")):
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("//", 1)[0]
            if FORBIDDEN_SOURCE.search(code):
                hits.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not hits, "\n".join(hits)


def test_p1_arch_dependencies_point_to_earlier_parts_and_inward() -> None:
    for p in workspace_crates():
        name = p["name"]
        assert name in PART, f"crate {name} has no part in the architecture map"
        for dep in p["dependencies"]:
            if dep["kind"] is not None or dep["name"] not in PART:
                continue
            assert PART[dep["name"]] <= PART[name], f"{name} (part {PART[name]}) → {dep['name']}"
            if name in CORE:
                assert dep["name"] not in OUTER, f"core crate {name} depends on {dep['name']}"


def test_p1_arch_unsafe_only_where_listed() -> None:
    hits = set()
    for p in (ROOT / "crates").rglob("*.rs"):
        text = p.read_text(encoding="utf-8")
        if re.search(r"\bunsafe\s*(\{|fn|impl)", text):
            hits.add(str(p.relative_to(ROOT)))
    extra = sorted(hits - UNSAFE_ALLOWED)
    assert not extra, f"unsafe outside the allowed list: {extra}"
    lints = (ROOT / "Cargo.toml").read_text(encoding="utf-8")
    assert 'unsafe_code = "forbid"' in lints


@pytest.mark.spec("SR-6.1-1")
def test_p1_arch_no_rust_code_fits_a_partition() -> None:
    # Test functions (p1_…) are named after behaviour and may say "fits"; they are not fitting code.
    fitting = re.compile(
        r"\bfn\s+(?!p\d_)\w*(kmeans|k_means|ledoit|fit|train)\w*\s*[<(]", re.IGNORECASE
    )
    hits = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "crates").rglob("*.rs")
        if fitting.search(p.read_text(encoding="utf-8"))
    ]
    assert not hits, hits


def imports(package: str) -> set[str]:
    """Modules imported by a Python package (tests excluded), as dotted names."""
    out: set[str] = set()
    for p in (ROOT / "python" / package).rglob("*.py"):
        if "tests" in p.parts:
            continue
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                out.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                out.add(node.module)
    return out


#: Which of our modules each package may import: builder ← model ← test kit; the renderer stands
#: alone. The builder takes the k-means sub-seed from sever_testkit.seeds (Build §4.4 puts seed
#: derivation in the test kit), a leaf module that imports only the standard library.
LAYERS: dict[str, set[str]] = {
    "sever_partition": {"sever_testkit.seeds"},
    "sever_refmodel_core": {"sever_partition"},
    "sever_testkit": {"sever_partition", "sever_refmodel_core"},
    "sever_demo": set(),
    # Part 2
    "sever_refmodel_durable": {"sever_partition", "sever_refmodel_core", "sever_testkit"},
    "sever_testkit_p2": {"sever_testkit", "sever_refmodel_durable"},
    "sever_db_p2": {"sever_db_p2_native"},
    # Part 3
    "sever_db_p3": {"sever_db_p3_native"},
    "sever_demo_p3": {"sever_db_p3", "sever_testkit.traces"},
}


def allowed(module: str, rules: set[str]) -> bool:
    return any(module == r or module.startswith(r + ".") for r in rules)


@pytest.mark.parametrize("package", sorted(LAYERS))
def test_p1_arch_python_layering(package: str) -> None:
    ours = {m for m in imports(package) if m.startswith("sever_") and m.split(".")[0] != package}
    bad = sorted(m for m in ours if not allowed(m, LAYERS[package]))
    assert not bad, f"{package} imports {bad}"


def test_p1_arch_seeds_is_a_stdlib_leaf() -> None:
    tree = ast.parse((ROOT / "python/sever_testkit/seeds.py").read_text(encoding="utf-8"))
    mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert mods <= {"hashlib", "struct", "typing"}, mods
