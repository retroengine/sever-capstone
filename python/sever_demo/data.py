from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "datasets" / "processed"

TOL = 8 * 2**-23   # how far a row's length may be from 1.0 (about 9.5e-7)

# check normilisation of length 1
def check_norms(X, chunk_rows=20_000):
    n_rows = X.shape[0]
    bad_length = 0
    non_finite = 0
    worst = 0.0
    bad_row_numbers = []

    for start in range(0, n_rows, chunk_rows):
        stop = min(start + chunk_rows, n_rows)
        chunk = np.asarray(X[start:stop], dtype=np.float64)

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
            bad_row_numbers += (np.flatnonzero(~finite | too_far) + start).tolist()[: 10 - len(bad_row_numbers)]

    return {"rows": n_rows, "non_finite": non_finite, "bad_length": bad_length,
            "worst_abs_diff": worst, "first_bad_rows": bad_row_numbers}


def _short(value, limit=70):
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def describe_dataset(name, npy_path, parquet_path):
    print(f"\n=== {name} ===")

    X = np.load(npy_path, mmap_mode="r")
    print("npy shape:", X.shape, "| dtype:", X.dtype)

    f = pq.ParquetFile(parquet_path)
    parquet_rows = f.metadata.num_rows
    print("parquet rows:", parquet_rows)
    print("parquet columns:", f.schema_arrow.names)
    print("rows match:", X.shape[0] == parquet_rows)

    first = next(f.iter_batches(batch_size=3)).to_pylist()
    for i, row in enumerate(first):
        print(f"  parquet row {i}:", {k: _short(v) for k, v in row.items()})

    result = check_norms(X)
    print("norm check:", result)
    return result


if __name__ == "__main__":
    describe_dataset("sciq_reference",
                     PROCESSED / "sciq_reference" / "embeddings.npy",
                     PROCESSED / "sciq_reference" / "passages.parquet")
    describe_dataset("nq_1m",
                     PROCESSED / "nq_1m" / "embeddings.npy",
                     PROCESSED / "nq_1m" / "passages.parquet")
    describe_dataset("nq_queries",
                     PROCESSED / "nq_queries" / "embeddings.npy",
                     PROCESSED / "nq_queries" / "queries.parquet")