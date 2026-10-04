# `demo.py`: the full-data acceptance run (DEMO_PLAN §6.2)

> **Location (4 Oct 2026):** this demo now lives in `demo/` and runs on its own (`demo/README.md`). Paths below are relative to `demo/`; the spec, `CLAUDE.md`, `docs/PROGRESS.md` and `datasets/` are at the repository root (`../`).

File: [python/sever_demo/demo.py](../../python/sever_demo/demo.py). Written by Claude (write mode, 2 Oct).

```
PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_demo.demo --seed 42
```

## What it does, in order

1. Re-hash the 9 files in `datasets/MANIFEST.sha256` (Phase 0 proof). Stop on any mismatch.
2. Norm check (§4.1) on SciQ and NQ. Stop on any failure. **Check, never fix.**
3. ID check (§3.2) on every NQ ID. Stop on any rejection.
4. Fit 128 centroids on SciQ (cached), quantise NQ (cached in `~/.cache/sever/`), route, insert all
   rows in the `stream` sub-seed order.
5. `delete_user` on the first 10 cohorts (Wikipedia titles) in `cohort-order` sub-seed order.
6. Survivors check on every touched group; every untouched group's blob hash must be unchanged; retry the
   first cohort → all `AlreadyAbsent`, groups unchanged.
7. Ghost table on the largest touched group.
8. 2,000 seeded random operations (delete, delete-absent, re-insert). Cheap check (`S` against a fresh sum,
   `n` against the member count) after each; full survivors check every 50 ops and on every group at
   the end.
9. With commitments (default): every certificate written to `results/certs/<run>/`, all checked by the
   independent verifier in its own process; 10 copies with one bit flipped must all be rejected.
10. Write `results/p1-demo-<time>.json` and one ledger line. PASS only if every count is 0 and every
   certificate check passed.

## Results of the full run with the Part 3 preview (2 Oct 2026, 21:50 UTC = 3 Oct 03:20 IST)

Result file `results/p1-demo-2026-10-02T215008Z.json`; certificates in
`results/certs/2026-10-02T215008Z/` (git-ignored). Seed 42, 1,000,000 rows, k = 128, commitments on.
**`git_dirty: true`** (not committed yet): re-run after committing.

| Step | Result |
|---|---|
| Manifest, norms, IDs | 0 mismatches, 0 failures, 0 rejected |
| Commitments | 1,000,000 blinding values from the OS; 128 group commitments in 9.4 s |
| `delete_user` | 10 cohorts → 85 records from 23 groups |
| Survivors check | **23 / 23 groups pass all 5 fields** (S, n, members, C_S, blob) |
| Untouched groups | **0 of 105** changed |
| Stress | 2,000 ops (827 delete, 390 delete-absent, 783 re-insert), 2,155 checks, **0 mismatches**; final full check on 92 groups: 0 failures |
| Certificates | **912 issued, 912 accepted** by the separate verifier process; 12,676 bytes each |
| Forged copies | **10 of 10 rejected** |
| **Outcome** | **PASS**, 771.1 s (stress 464 s, certificates 88 s) |

Ghost table and the float error: unchanged from the run below (same data, same seed).

## Results of the first full run, without commitments (2 Oct 2026, 20:21 UTC = 3 Oct 01:51 IST)

Ledger line 3; result file `results/p1-demo-2026-10-02T202108Z.json`. Seed 42, 1,000,000 rows, k = 128.
**`git_dirty: true`**: the code wasn't committed yet. Re-run after committing so the ledger points to
the exact code.

| Step | Result |
|---|---|
| Manifest | 9 files, **0 mismatches** |
| Norms | SciQ 13,679 + NQ 1,000,000 rows, **0 failures**, worst 1.836e-7 |
| IDs | 1,000,000, **0 rejected**, all unique |
| Group sizes | min **74**, median **2,252**, max **161,376**, 0 empty |
| `delete_user` | 10 cohorts → **85 records** from **23 groups** |
| Survivors check | **23 / 23** groups pass all 4 fields (incl. groups of 153,305 and 161,369) |
| Untouched groups | **0 of 105** changed |
| Retry | all `AlreadyAbsent`, groups unchanged |
| Stress | 2,000 ops (827 delete, 390 delete-absent, 783 re-insert); **2,155 checks, 0 mismatches**; final full check on 92 groups: 0 failures |
| **Outcome** | **PASS**, 475.7 s total |

Time: manifest 61 s and norms 63 s (both reading `/mnt/c`), build 32 s, stress 267 s (big groups make
the full checks slow).

### The ghost table (group 118: 161,376 members, 7 deleted)

| Method | Deleted record still stored | Summary vs survivors-only | Bit-identical? |
|---|---|---|---|
| SEVER (integer `S`) | no | **0** | **yes** |
| float32 running mean | no | 2.004e-7 max abs | no |
| soft delete | yes (7) | 2.031e-5 L2 | no |

float32 error after N delete/re-insert cycles: 1 → 2.00e-7, 10 → 1.99e-7, 100 → 2.00e-7,
1,000 → 1.99e-7.

## Findings to say honestly

1. **The float error did not grow** over 1,000 cycles on this group: it stayed at about 2e-7. DEMO_PLAN
   §5.7 expected "the error accumulates"; this run does not show that. Say: *not bit-identical, and
   ~2e-7 off*. Don't claim growth.
2. **Soft delete's distance is small here (2e-5)** because 7 records out of 161,376 barely move a mean.
   The real point of soft delete is column 2: the 7 records are still stored.
3. **Groups are very uneven** (74 to 161,376): SciQ centroids on NQ data. One group holds 16% of the
   corpus. Exactness is unaffected; cost isn't. Part 1's drift test and spawning exist for this.
4. **Smoke and sabotage runs** (ledger lines 1-2, 50,000 rows): smoke **PASS** (220 ops, 254 checks);
   `--sabotage SB-2` **FAIL** with 140 mismatches, as required.

## Trap questions

**1. "Your float error is 2e-7. Isn't that good enough?"**
<details><summary>Answer</summary>
For search, probably. For *proving* deletion, no: the claim is that the state is exactly what it would be
without the record. Only an exact value can be committed to and checked by someone else (Part 3).
</details>

**2. "Only 85 records were deleted. Is that a real test?"**
<details><summary>Answer</summary>
85 deletions over 23 groups, plus 2,000 stress operations with 2,155 checks over 92 groups, on the full
1M index, including the two biggest groups. More deletions would cost time, not add a new kind of check.
The unit stress test does a full check after every one of 2,000 operations.
</details>

**3. "Why does the run stop if one row fails the norm check?"**
<details><summary>Answer</summary>
§4.1 says every insert is checked, with no bypass. A bad row can't be inserted, so the run would be
measuring something other than the spec. Report, don't fix.
</details>

**4. "Why does the ledger say `git_dirty: true`?"**
<details><summary>Answer</summary>
The code wasn't committed when it ran. That's honest, but weak evidence. The fix is to commit and re-run;
the new line will point to the exact commit.
</details>
