"""Kept clean-room tests (FT-10, docs/FAIR_TESTING.md): the sealed tests of passing fairness runs.

Written by a clean-room session from the spec alone; never edited (``scripts/fair.sh check`` and the
Fast CI tier compare every file with its run's MANIFEST.sha256). They need the release CLI, so they
run in the slow tier. Tests the run's judge ruled TEST_ERROR are listed in EXCLUDED.json and
skipped.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INPUTS = [
    "golden/p1_partition_small.svp",
    "golden/p1_partition_small.json",
    "artefacts/partition-seed42.svp",
    "artefacts/partition-seed42.json",
]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "req(ids): requirement IDs (clean-room tests)")
    if not any(Path(__file__).parent.glob("p*/*/MANIFEST.sha256")):
        return  # no kept clean-room tests yet
    inputs = Path(tempfile.mkdtemp(prefix="cleanroom-inputs-"))
    for rel in INPUTS:
        if (ROOT / rel).exists():
            (inputs / Path(rel).name).symlink_to(ROOT / rel)
    scratch = ROOT / "target/cleanroom-scratch"  # on the repository's file system (ext4, §12.9)
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SEVER_INPUTS", str(inputs))
    os.environ.setdefault("SEVER_SCRATCH", str(scratch))
    os.environ.setdefault("SEVER_CLI", str(ROOT / "target/release/sever-db-p2"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    excluded: set[tuple[str, str]] = set()
    for f in Path(__file__).parent.glob("p*/*/EXCLUDED.json"):
        for tid in json.loads(f.read_text())["tests"]:
            excluded.add((str(f.parent), tid.split("::")[-1]))
    for item in items:
        if Path(__file__).parent not in Path(item.path).parents:
            continue
        item.add_marker(pytest.mark.slow)
        run_dir = next(
            (
                str(p)
                for p in Path(item.path).parents
                if p.parent.name.startswith("p") and p.parent.parent == Path(__file__).parent
            ),
            "",
        )
        if (run_dir, item.name) in excluded:
            item.add_marker(pytest.mark.skip(reason="judged TEST_ERROR in its fairness run"))
