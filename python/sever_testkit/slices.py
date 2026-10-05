"""Exports the ``id`` and ``cohort`` columns of the P0 corpus for the Rust demo (sever-demo idea).

    PYTHONPATH=python uv run python -m sever_testkit.slices

The Rust workspace does not read Parquet: every Rust Parquet reader pulls a second ``getrandom``
major version, which spec §20.3 check 1 forbids. This writes ``artefacts/nq_1m.ids.jsonl`` once
(gitignored, like the partition artefacts): a header line with the manifest hash of the passages
file, then one ``[id, cohort]`` JSON array per corpus row, in file order. The text column is never
read (CLAUDE.md §8). Every slice is a prefix of this file (DB-59).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Final

import pyarrow.parquet as pq

PASSAGES: Final = "processed/nq_1m/passages.parquet"
OUT: Final = Path("artefacts/nq_1m.ids.jsonl")
FORMAT: Final = "sever-ids-1"


def manifest_sha(root: Path, rel: str) -> str:
    """The pinned SHA-256 of ``datasets/<rel>`` from ``datasets/MANIFEST.sha256``."""
    for line in (root / "datasets/MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        sha, _, name = line.partition("  ")
        if name == rel:
            return sha
    raise KeyError(rel)


def export(root: Path, passages: Path, out: Path, passages_sha256: str) -> int:
    """Writes the header and one ``[id, cohort]`` line per row. Returns the row count."""
    table = pq.read_table(passages, columns=["id", "cohort"])
    ids = table.column("id").to_pylist()
    cohorts = table.column("cohort").to_pylist()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        header = {"format": FORMAT, "passages_sha256": passages_sha256, "rows": len(ids)}
        f.write(json.dumps(header) + "\n")
        for rid, cohort in zip(ids, cohorts, strict=True):
            f.write(json.dumps([rid, cohort], ensure_ascii=False) + "\n")
    tmp.replace(out)
    return len(ids)


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="sever-slices", description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("."))
    a = ap.parse_args(argv)
    root: Path = a.root
    rows = export(root, root / "datasets" / PASSAGES, root / OUT, manifest_sha(root, PASSAGES))
    print(f"{root / OUT}: {rows} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
