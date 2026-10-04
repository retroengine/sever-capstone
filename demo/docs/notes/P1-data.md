# `data.py`: loading the data and the norm check (§4.1)

> **Location (4 Oct 2026):** this demo now lives in `demo/` and runs on its own (`demo/README.md`). Paths below are relative to `demo/`; the spec, `CLAUDE.md`, `docs/PROGRESS.md` and `datasets/` are at the repository root (`../`).

File: [python/sever_demo/data.py](../../python/sever_demo/data.py). Tests: [tests/test_data.py](../../tests/test_data.py).

## One line

Open each dataset read-only, print its basic facts, and count every row whose length is not 1.

## Why

- **Normalised** means each row (one embedding, 384 numbers) has length 1:
  `length = √(x₁² + x₂² + … + x₃₈₄²)`.
- Q24 (next module) assumes length ≈ 1. That is what keeps every number under `2^24 + 16` and the
  sums inside `i64`. A row of length 5 would break that bound.
- The spec says **check, never fix** (§4.1). We report, we don't normalise.

## How it works: `check_norms(X, chunk_rows=20_000)`

1. Take 20,000 rows at a time, converted to float64.
2. Find rows containing NaN or ±inf → `non_finite`.
3. Square every number, add the squares **left to right** (`np.cumsum(..., axis=1)[:, -1]`), take √.
4. `off = |length − 1|`. A finite row with `off > TOL` → `bad_length`.
5. Track the worst `off` (finite rows only) and the first 10 bad row numbers.
6. Return the counts. It never raises.

`TOL = 8 * 2**-23` ≈ 9.5e-7 = **8 float32 steps** at 1.0 (one step = `2^-23` ≈ 1.19e-7).

`describe_dataset(...)` prints shape, dtype, parquet row count and columns, whether the counts match,
3 sample rows, and the norm check.

## Decisions

| Decision | Why | Spec |
|---|---|---|
| `REPO = Path(__file__).resolve().parents[2]` | Paths work from any folder (`[0]` sever_demo, `[1]` python, `[2]` repo) | — |
| `np.load(..., mmap_mode="r")` | 1M × 384 × 4 B = 1.5 GB; only touched pages are read. `"r"` makes writes fail, so `datasets/` can't be damaged | CLAUDE.md §8 |
| Chunks of 20,000 rows | One float64 chunk ≈ 61 MB, ~180 MB with copies. All at once ≈ 9 GB | — |
| Convert to float64 before squaring | The spec computes the norm in float64; squaring in float32 rounds every square | §4.1 |
| `cumsum`, not `np.sum` / `np.linalg.norm` | Float addition depends on order. `np.sum` uses an order NumPy may change. A fixed left-to-right order makes Python and Rust accept/reject exactly the same rows | §4.1, CLAUDE.md §7 |
| Check non-finite **first** | `NaN > TOL` is `False`, so a NaN row would slip through the length test | §4.1 |
| A NaN row counts only as `non_finite` | Each bad row is counted once | — |
| `worst` uses finite rows only | `max` over NaN gives NaN and hides the real worst value | — |
| Bad row numbers `+ start`, max 10, no values | Chunk-local index → real row. Never print vector values | §17 |
| Count, don't raise | A whole-dataset report. Rejecting on insert is the index's job later | §4.1 |
| `rows match` check | Row *i* of the `.npy` belongs to row *i* of the parquet; a mismatch attaches every ID to the wrong vector | — |

## Measured results (re-run 2 Oct 2026)

Command: `PYTHONHASHSEED=0 uv run python python/sever_demo/data.py`

| Dataset | Rows | Columns | Rows match | Non-finite | Bad length | Worst `off` |
|---|---|---|---|---|---|---|
| `sciq_reference` | 13,679 | `id, text` | yes | 0 | 0 | 1.39e-7 |
| `nq_1m` | 1,000,000 | `row, corpus_index, id, cohort, text, judged` | yes | 0 | 0 | 1.84e-7 (1.54 steps) |
| `nq_queries` | 3,452 | `query_id, text` | yes | 0 | 0 | 1.31e-7 |

All are float32, d = 384. The worst row uses 1.54 of the 8 allowed steps, about 5× margin.

Data facts to remember:
- NQ IDs look like `doc0`, `doc1`, `doc6`. They are **not** row numbers (row 2 is `doc6`).
- SciQ IDs look like `sciq-train-000000`. Query IDs look like `test0`.
- `cohort` is the Wikipedia title (for example `Minority interest`). `delete_user` will delete one cohort.

## Tests (`tests/test_data.py`, 7 items)

| Test | Proves |
|---|---|
| `test_norm_accepts_good_rows` | Clean unit rows give 0 failures |
| `test_norm_rejects_non_finite` ×3 | NaN, +inf, −inf each counted once, as non-finite only, at the right row |
| `test_norm_rejects_just_outside_tolerance` | Length `1 + 2·TOL` is caught |
| `test_norm_accepts_just_inside_tolerance` | Length `1 + 0.5·TOL` passes (both sides of the line are tested) |
| `test_norm_row_numbers_correct_across_chunks` | Bad row 7 with `chunk_rows=3` is reported as 7, not 1 (catches a missing `+ start`) |

- `SPEC_TOL` is written out in the test, **not imported** from `data.py`. If someone loosened the
  code's tolerance, an imported value would loosen the test too.
- Small synthetic data (`d = 16`) for unit tests; the full data is for the demo run (Build §2.7).

## Trap questions

**1. "Why not `np.linalg.norm(X, axis=1)`? It's one line."**
<details><summary>Answer</summary>
Its addition order is NumPy's choice and can change. A row right on the edge could pass one order and
fail another. The spec pins left-to-right float64 so Python and Rust agree on every row.
</details>

**2. "Isn't `cumsum` wasteful? It keeps 384 partial sums per row."**
<details><summary>Answer</summary>
Yes, and chunking keeps that small. A loop over the 384 columns gives the same order with less memory.
`cumsum` was chosen because it's short.
</details>

**3. "Your worst row is 1.54 steps from 1. The spec says correct data is within 1 step. Is your data broken?"**
<details><summary>Answer</summary>
No. Each of the 384 numbers was rounded to float32 separately, and those small errors add up in the
length. 1.54 is well inside the 8-step limit. The spec's "within 1 step" wording is approximate. That's
a candidate gap entry, not a failure.
</details>

**4. "What happens to a row of all zeros?"**
<details><summary>Answer</summary>
Length 0, so `off = 1`, far beyond the tolerance → `bad_length`. A zero vector embeds nothing.
</details>

**5. "Why 8 steps, and not 1 step or 1%?"**
<details><summary>Answer</summary>
1 step is too tight (real data reaches 1.54). 1% is far too loose. The job is catching *forgotten*
normalisation, which is off by a lot. 8 steps also fixes the Q24 bound at exactly `2^24 + 16`.
</details>

**6. "Does addition order matter for the integer sums `S` later?"**
<details><summary>Answer</summary>
No. Integer addition is exact in any order; that's the point of the project. Order matters only for
**float** work: this norm check, the float baseline and routing distances.
</details>

**7. "Could this script damage the dataset?"**
<details><summary>Answer</summary>
No. `mmap_mode="r"` makes writes raise an error, and the parquet is only read.
</details>

## Open fixes

Done on 3 Oct 2026 (by Claude, at your request "finish the demo completely"; layout and naming only,
no behaviour change, the SciQ report gives the same numbers): `X` renamed to `x` (ruff N803/N806),
type hints on every function (mypy clean), test fixture seed 0 → 42 (CLAUDE.md §6.2), formatting.

| Still open | Fix |
|---|---|
| `check_manifest()` and `load_ids_and_cohorts()` (added Day 2) have no unit test; every demo run exercises them | A test with a temporary manifest |
| `check_manifest()` doesn't report *unlisted* files, unlike `prepare_data.py verify` | Add if needed |
| Spec §4.1 "within 1 step" wording vs measured 1.54 steps | Candidate gap entry in `SPEC_GAPS.md` (your decision) |
