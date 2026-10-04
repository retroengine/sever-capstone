# `ledger.py` and `baselines.py`: the run record and "the ghost"

> **Location (4 Oct 2026):** this demo now lives in `demo/` and runs on its own (`demo/README.md`). Paths below are relative to `demo/`; the spec, `CLAUDE.md`, `docs/PROGRESS.md` and `datasets/` are at the repository root (`../`).

Files: [python/sever_demo/ledger.py](../../python/sever_demo/ledger.py),
[python/sever_demo/baselines.py](../../python/sever_demo/baselines.py). Tests:
[tests/test_ledger.py](../../tests/test_ledger.py), [tests/test_baselines.py](../../tests/test_baselines.py).
Written by Claude (write mode, 2 Oct).

## Ledger: one line

Every run appends one JSON line to `docs/RUN_LEDGER.jsonl`, written by code, never edited.

- `open_ledger()` opens in **append mode before the run starts**. If it can't, the run doesn't start
  (Overview §13.3).
- `append()` writes `json.dumps(sort_keys=True)` + newline, then flushes. Sorted keys make the bytes
  independent of the order fields were added.
- Fields: `ts_utc`, `ts_ist`, `command`, `git_commit`, `git_dirty`, `seed`,
  `dataset_manifest_sha256`, `platform`, `sabotage`, `rows_loaded`, `k_groups`, `outcome`
  (`PASS` / `FAIL` / `ERROR`), `counts`, `timings_s`, `total_s`, `result_file`, `result_sha256`.
- The full results go to `results/p1-demo-<time>.json`; the ledger stores its SHA-256.
- On a crash the entry is still written, with `ERROR` and only the error's *type* (§17).

**Why commit it?** The git commit time is independent evidence of when the runs happened. And
`git_dirty: true` honestly marks a run made with uncommitted code.

Tests: two runs → two lines, line 1's bytes unchanged; key order doesn't change the bytes; a ledger path
that is a directory stops the run (`IsADirectoryError`).

## Baselines: one line

Run two common ways of deleting on the same group, and show that they leave a trace. SEVER doesn't.

| Method | Delete does | Leaves |
|---|---|---|
| SEVER | `S −= x̃`, `n −= 1`, remove member | nothing: `S` equals the survivors' sum, difference **0** |
| float32 running mean | `m = (m·n − x) / (n − 1)` | rounding error: not bit-identical to the mean built without the record |
| soft delete | flag the record | the record itself, and its full share of the summary |

`ghost_report()` inserts a group's real vectors in their real order, deletes the cohort's ones, and
measures: SEVER's max difference, float32 max difference vs the exact float64 mean, whether float32 is
bit-identical to the same method built from survivors only, float32 error after 1, 10, 100 and 1,000
delete/re-insert cycles, and soft delete's L2 distance.

**Honesty rule (DEMO_PLAN §5.7):** the float error is tiny (around 1e-7). The claim is "not
bit-identical", not "huge", and not "it grows" (the full run showed no growth). Soft delete is the big one: the record is still there.

Measured (full run, a group of 161,376, 7 deleted): SEVER **0**; float32 2.0e-7, not bit-identical, **flat** over 1,000 cycles (did not grow); soft delete 2.0e-5 L2 with all 7 records still stored. Details: [P1-demo-run.md](P1-demo-run.md).

## Trap questions

**1. "Can't someone edit the ledger file by hand?"**
<details><summary>Answer</summary>
Yes, locally. But each line is committed, so an edit shows up in `git diff`, and each line holds the
SHA-256 of its results file. It's evidence, not tamper-proof storage. Tamper-evidence comes in Part 3
(transparency log).
</details>

**2. "The float error is 1e-7. Who cares?"**
<details><summary>Answer</summary>
The claim isn't size, it's *exactness*: after deleting, the state must be byte-for-byte what it would have
been. A float summary can't prove that, so no certificate could be built on it. (Don't claim it grows: over
1,000 cycles it stayed at about 2e-7.)
</details>

**3. "Why is soft delete's error so much bigger than the float error?"**
<details><summary>Answer</summary>
Soft delete never removes the vector at all. The summary still contains 100% of the deleted record. The
float method removes almost all of it, but not exactly.
</details>
