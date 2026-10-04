import hashlib
import os
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]  # the demo/ folder
# The data is the demo's one outside input: ../datasets next to demo/, or $SEVER_DATASETS (Docker
# mounts it read-only at /data). Read only, never written (CLAUDE.md §8).
DATASETS = Path(os.environ.get("SEVER_DATASETS") or REPO.parent / "datasets")
PROCESSED = DATASETS / "processed"

TOL = 8 * 2**-23  # how far a row's length may be from 1.0 (about 9.5e-7)


# Check that every row has length 1 (§4.1). Check, never fix.
def check_norms(x: npt.NDArray[np.floating[Any]], chunk_rows: int = 20_000) -> dict[str, Any]:
    n_rows = x.shape[0]
    bad_length = 0
    non_finite = 0
    worst = 0.0
    bad_row_numbers: list[int] = []

    for start in range(0, n_rows, chunk_rows):
        stop = min(start + chunk_rows, n_rows)
        chunk = np.asarray(x[start:stop], dtype=np.float64)

        finite = np.isfinite(chunk).all(axis=1)
        non_finite += int((~finite).sum())

        squares = chunk * chunk
        total = np.cumsum(squares, axis=1)[:, -1]
        length = np.sqrt(total)

        off = np.abs(length - 1.0)
        off_ok = off[finite]
        if off_ok.size:
            worst = max(worst, float(off_ok.max()))

        too_far = finite & (off > TOL)
        bad_length += int(too_far.sum())
        if len(bad_row_numbers) < 10:
            bad_row_numbers += (np.flatnonzero(~finite | too_far) + start).tolist()[
                : 10 - len(bad_row_numbers)
            ]

    return {
        "rows": n_rows,
        "non_finite": non_finite,
        "bad_length": bad_length,
        "worst_abs_diff": worst,
        "first_bad_rows": bad_row_numbers,
    }


def check_manifest(datasets: Path = DATASETS) -> list[str]:
    """Re-hash every file in datasets/MANIFEST.sha256. Returns the paths that do not match.

    Same rule as `prepare_data.py verify` (P0): a missing file or a different SHA-256 is a mismatch.
    """
    mismatches = []
    for line in (datasets / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        expected, rel = line.split("  ", 1)
        path = datasets / rel
        if not path.exists():
            mismatches.append(rel)
            continue
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(1 << 22):
                h.update(chunk)
        if h.hexdigest() != expected:
            mismatches.append(rel)
    return mismatches


def load_ids_and_cohorts(
    parquet_path: Path, rows: int | None = None
) -> tuple[list[str], list[str]]:
    """NQ record IDs and cohorts (Wikipedia titles), in row order. Passage text is not read."""
    table = pq.read_table(parquet_path, columns=["id", "cohort"])
    if rows is not None:
        table = table.slice(0, rows)
    ids = [str(v) for v in table.column("id").to_pylist()]
    cohorts = [str(v) for v in table.column("cohort").to_pylist()]
    return ids, cohorts


def _short(value: object, limit: int = 70) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def describe_dataset(name: str, npy_path: Path, parquet_path: Path) -> dict[str, Any]:
    print(f"\n=== {name} ===")

    x = np.load(npy_path, mmap_mode="r")
    print("npy shape:", x.shape, "| dtype:", x.dtype)

    f = pq.ParquetFile(parquet_path)
    parquet_rows = f.metadata.num_rows
    print("parquet rows:", parquet_rows)
    print("parquet columns:", f.schema_arrow.names)
    print("rows match:", x.shape[0] == parquet_rows)

    first = next(f.iter_batches(batch_size=3)).to_pylist()
    for i, row in enumerate(first):
        print(f"  parquet row {i}:", {k: _short(v) for k, v in row.items()})

    result = check_norms(x)
    print("norm check:", result)
    return result


if __name__ == "__main__":
    describe_dataset(
        "sciq_reference",
        PROCESSED / "sciq_reference" / "embeddings.npy",
        PROCESSED / "sciq_reference" / "passages.parquet",
    )
    describe_dataset(
        "nq_1m", PROCESSED / "nq_1m" / "embeddings.npy", PROCESSED / "nq_1m" / "passages.parquet"
    )
    describe_dataset(
        "nq_queries",
        PROCESSED / "nq_queries" / "embeddings.npy",
        PROCESSED / "nq_queries" / "queries.parquet",
    )
