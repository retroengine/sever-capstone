# `partition.py`: 128 frozen groups (§6.2 steps 1-2) and routing (§7.1)

> **Location (4 Oct 2026):** this demo now lives in `demo/` and runs on its own (`demo/README.md`). Paths below are relative to `demo/`; the spec, `CLAUDE.md`, `docs/PROGRESS.md` and `datasets/` are at the repository root (`../`).

File: [python/sever_demo/partition.py](../../python/sever_demo/partition.py). Tests:
[tests/test_partition.py](../../tests/test_partition.py). Written by Claude (write mode, 2 Oct).

## One line

Fit 128 group centres on SciQ once with k-means, then send every NQ vector to its nearest centre.

## Why

- **Fixed groups** mean a deletion touches exactly one group, so checking that one group is enough.
  Re-clustering would move every vector and every group would change.
- **Fitted on SciQ, not NQ**: the groups must come from public data with no user data in it (§6.1).

## How it works

- `sub_seed(seed, label)`: first 8 bytes of `SHA-256(u64be(seed) ‖ label)` (Overview §10.6). Labels:
  `kmeans`, `stream` (insert order), `cohort-order`; the demo adds `check`, `ghost`, `stress`.
- `kmeans_seed(seed) = sub_seed(seed, b"kmeans") mod 2^32`: scikit-learn refuses seeds ≥ 2^32 (**gap G-1**).
- `fit_centroids(x_ref, seed)`: quantise then dequantise SciQ (step 1, so the fit uses exactly what the
  engine routes), then `KMeans(128, k-means++, n_init=10, max_iter=300, tol=1e-4, lloyd)` (step 2).
- `route(q, centroids)`: dequantise a chunk of 20,000 rows to float64, compute
  `‖x‖² − 2·x·μ + ‖μ‖²` for all 128 centres at once, take `argmin` (first minimum → smaller label).

## Decisions

| Decision | Why | Spec |
|---|---|---|
| Route with matrix products, not §7.1's sequential sum | 1M × 128 distances in seconds. Honest cost: a near-tie could go another way than the Rust engine. Exactness doesn't depend on *which* group | §7.1 |
| Labels computed once for all rows | Routing is a pure function of `(x̃, centroids)`; no clock, no counter | §7 |
| Caches in `~/.cache/sever/`, names include the source's manifest hash | Changed data can't reuse an old cache; nothing is written in `datasets/` | CLAUDE.md §8 |
| Steps 3–7 (Ledoit–Wolf, drift threshold) not built | Demo is frozen-only (`spawning_enabled = false`) | Build §4.3 |

## Measured (full run, seed 42)

Full run: min **74**, median **2,252**, max **161,376** members (16% of the corpus in one group), 0 empty. Smoke run (50,000 rows): the largest group held
7,962 (16%), smallest 1. Groups are very uneven because SciQ (science questions) and NQ (Wikipedia)
are different kinds of text.

## Tests (`tests/test_partition.py`, 5 items)

`sub_seed` matches the formula written out by hand; `kmeans_seed` < 2^32 for all five seeds; ties go
to the smaller label (an exactly equidistant case); the fast route equals a slow §7.1 sequential loop
on 300 rows; k-means with the same seed gives identical centroids twice.

## Trap questions

**1. "Why not fit the groups on NQ itself? They'd be more even."**
<details><summary>Answer</summary>
NQ is the "user" data. Centres fitted on it would carry every user's influence, so after a deletion the
centres themselves would be a ghost, and removing it would mean re-fitting everything. SciQ is public
and never deleted, so the centres never need to change (§6.1).
</details>

**2. "Your routing isn't the spec's sequential sum. Doesn't that break exactness?"**
<details><summary>Answer</summary>
No. Exactness is about one group's sum before and after a delete. Which group a vector lands in only
needs to be the same every time for the same vector, and it is (pure function). Agreement with Rust
routing is a Part 1 engine requirement, not a demo claim.
</details>

**3. "What's gap G-1?"**
<details><summary>Answer</summary>
The overview derives a 64-bit k-means seed, but scikit-learn accepts only seeds below 2^32 and crashes.
Fix used: take it mod 2^32. The spec still needs a decision entry for it.
</details>

## Open fixes

- Record G-1's decision in the overview (DB-N) and close it in `SPEC_GAPS.md`.
- Group-size imbalance: record it as a finding; Part 1's drift test and spawning are what fix it.
