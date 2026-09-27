# Progress

Updated at the end of every session (CLAUDE.md §3.3). Newest session first in the log.

## Now

- **Phase:** P0 data complete (verify OK, 27 Sep 2026). Build plan Parts 1–4 adopted.
- **Current part:** Part 1 — The Idea (Build §4)
- **Current module:** `sever-types` (not started)
- **Next small step:** review Build §0–§4 and decide on the proposed decisions DB-44 … DB-50
  (Build §3.5). Then read spec §2, §3.2 and §17 and write `docs/notes/P1-sever-types.md` in your own
  words.
- **Blocked on:** nothing for Part 1 data. The P0 exit gate still needs the Python lockfile,
  `configs/experiments.yaml` and the Rust checks.

## Parts

| Part | Status | Tag | Notes |
|---|---|---|---|
| 1 The Idea | in progress | | Apply G-1 (seed mod 2^32) in the partition builder; settle G-5 before the first crate |
| 2 The Database | not started | | Starts when Part 1 is frozen |
| 3 The Receipt | not started | | Resolve G-3 (DB-51) and G-4 (genesis checkpoint) |
| 4 The Erasure | not started | | Apply G-2 |

## Part 1 modules (Build §4.4)

| Module | Status | Branch | Notes |
|---|---|---|---|
| P0 verify | done | — | SciQ passages restored by `build` (was corrupt); manifest committed (2c17fb8) |
| `sever-types` | not started | | §2, §3.2, §17 (subset); declares EP-4 |
| `sever-quant` | not started | | §4.1–4.3 |
| `sever_partition` (Python builder) | not started | | §6.2; independent Ledoit–Wolf oracle; G-1 |
| `sever-partition` (Rust importer) | not started | | §6.3 |
| `sever_refmodel_core` (Python) | not started | | §3–§8; written from the spec only |
| `sever-index` | not started | | §5, §7, §9.7; declares EP-1, EP-2, EP-3 |
| `sever-search` | not started | | §8; scalar and AVX2 bit-identical |
| `sever-tracekit`, `sever_testkit` | not started | | Trace files; synthetic data, slices, seeds |
| `sever-p1`, `sever-demo` CLI, `sever_demo` | not started | | Build §4.9 |
| Proof spikes | not started | | Build §3.4; deleted after the gate |

## Open questions

- What overwrote `sciq_reference/passages.parquet` at 19:35 UTC on 27 Sep? Not `build`; the
  writer was pyarrow 25.0.1.
- The build plan's proposed decisions DB-44 … DB-54 are not yet in the overview's decision register.
- G-5: the spec §19.2 layout differs from the Build §3.2 crate and package map.

## Session log

- **27 Sep 2026**: Build plan Parts 1–4 adopted as the plan of record, replacing the earlier S1–S17
  stage plan. CLAUDE.md, PROGRESS.md, SPEC_GAPS.md and TRACEABILITY.md updated to match.
- **27 Sep 2026**: Specification, overview and CLAUDE.md written. P0 encode running.
