# Progress

Updated at the end of every session (CLAUDE.md §3.3). Newest session first in the log.

> **Draft written by Claude on 4 Oct 2026, for you to confirm** (CLAUDE.md §3.3): read it before
> committing and change anything that is not how you see it.

## Now

- **Phase:** P0 data complete (verify OK, 27 Sep 2026). Build plan Parts 1–4 adopted.
- **Current track:** Part 1 modules in Rust (Build §4.4), in coach mode. The review demo is finished
  and moved to `demo/` (self-contained: own `pyproject.toml`/`uv.lock`, tests, scripts, Docker image;
  data read from `../datasets`). G-5 closed by DB-56 (spec §19.2 = Build §3.2 map).
- **Decisions (4 Oct):** DB-44, 45, 47, 49, 50 accepted into Overview §6.8; new DB-57 (k-means seed
  mod 2^32, closes G-1), DB-58 (normative statements, closes G-6), DB-59 (`nq-10k` = first 10,000 rows
  of `nq-100k`, closes G-7). Open and needed soon: **G-8** (`WrongDimension` has no rule in §4.1;
  `sever-quant`), **G-10** (spawn size in small fixtures; `sever-index`).
- **Rust workspace:** `Cargo.toml` (lints of Build §1.2), `rust-toolchain.toml` 1.98.1, `clippy.toml`,
  `rustfmt.toml`, `deny.toml`; empty crate `crates/sever-types` (doc comment only). fmt, clippy
  `-D warnings` and `cargo test` pass.
- **Next small steps (`sever-types`, module loop CLAUDE.md §4):**
  1. Read: spec §2 (notation, constants), §3.2 (record IDs), §17 (errors, the subset Part 1 raises),
     Build §3.3 EP-4 (secret-memory provider).
  2. Explain back: write 5–10 lines in `docs/notes/P1-sever-types.md`, in your own words.
  3. Tests first (Build §4.7), then the code.
- **Blocked on:** nothing. The P0 exit gate still needs `configs/experiments.yaml` and the Rust checks
  (now possible: the workspace exists). `cargo-deny` is not installed yet.
- **Demo:** to run Docker under WSL, turn on Docker Desktop's WSL integration for this distro (the
  image is written but has not been built yet).

## Parts

| Part | Status | Tag | Notes |
|---|---|---|---|
| 1 The Idea | `sever-types` built; next `sever-quant`; demo prototype in `demo/` | | G-1 closed (DB-57), G-5 closed (DB-56). Open for Part 1: G-8 (`sever-quant`), G-10 (`sever-index`), G-11 (limit only) |
| 2 The Database | not started | | Starts when Part 1 is frozen |
| 3 The Receipt | **preview** built in the demo | | Commitments, proof of knowledge (§9.5), signed certificates (§11), offline verifier. Not built: transparency log, witnesses, insert signatures, Merlin nonces. Resolve G-3 (DB-51) and G-4 |
| 4 The Erasure | not started | | Apply G-2 |

## Demo track (DEMO_PLAN, 1–4 Oct; now in `demo/`, paths below relative to it)

| Piece | Status | Notes |
|---|---|---|
| Data checks, quantiser (Day 1) | done | Written by you; tidied 3 Oct (naming, types, seed 42, 2 tests added) |
| IDs, groups, index, partition, baselines, ledger, full run (Day 2) | done | Written by Claude (write mode); tests rewritten spec-driven (oracle) |
| Demo shell, runbook, slides, clean-clone check (Day 3) | done | 9 slides: https://claude.ai/artifact/5h7RoaX9KGdUkzSZ3zqWn1 |
| Part 3 preview (3 Oct) | done | libsodium 1.0.18 via ctypes; RFC 9496/9380/8032 vectors; independent verifier in `python/sever_verify` |
| Guided demo shell (3 Oct, evening) | done | `tour`/`next` (runbook order, same numbers), plain-words notes and hints, `help` in demo order, `explain`, `status`, `find`, `insert`; ledger lines say what they did (`summary`); full run ends with a claim → evidence table. Words in `python/sever_demo/guide.py`. Screenshots re-made |
| Tests | 233 pass | 38 must-fail; ruff and mypy clean. Re-checked after the move to `demo/` (4 Oct): 233 pass, smoke run PASS, rehearsal script runs in the shell |
| Five sentences (`P1-idea.md`) | **open (you)** | |
| Commit, re-run, tag `demo-v0` | **open** | |
| Rehearsals, Q&A aloud, screen recording | **open (you)** | Screenshots exist: `results/screens/01…14.svg` (scripted rehearsal) |

## Part 1 modules (Build §4.4, after the review)

| Module | Status | Branch | Notes |
|---|---|---|---|
| P0 verify | done | — | SciQ passages restored by `build` (was corrupt); manifest committed (2c17fb8) |
| `sever-types` | **built** (write mode, 4 Oct); review open | `p1-sever-types` | IDs, constants, all §17 errors, `SecretBuf` + EP-4 with contract suite; 25 tests (3 property); 2 manual sabotages went red, then reverted. Your two check questions are open |
| `sever-quant` | not started | | §4.1–4.3 (Python prototype exists: `sever_demo/quant.py`) |
| `sever_partition` (Python builder) | not started | | §6.2; independent Ledoit–Wolf oracle; G-1 |
| `sever-partition` (Rust importer) | not started | | §6.3 |
| `sever_refmodel_core` (Python) | not started | | §3–§8; written from the spec only (the demo's `demo/tests/spec_oracle.py` is a start) |
| `sever-index` | not started | | §5, §7, §9.7; declares EP-1, EP-2, EP-3 |
| `sever-search` | not started | | §8; scalar and AVX2 bit-identical |
| `sever-tracekit`, `sever_testkit` | not started | | Trace files; synthetic data, slices, seeds |
| `sever-p1`, `sever-demo` CLI, `sever_demo` | prototype | | `demo/python/sever_demo` is the demo version, not the Build §4.9 deliverable |
| Proof spikes | not started | | Build §3.4; deleted after the gate |

## Open questions

- What overwrote `sciq_reference/passages.parquet` at 19:35 UTC on 27 Sep? Not `build`; the
  writer was pyarrow 25.0.1.
- The build plan's proposed decisions DB-44 … DB-54 are not yet in the overview's decision register.
- CLAUDE.md §7 names a top-level `verifier/` (C-16, Part 3); the demo's Python verifier is
  `demo/python/sever_verify`, a prototype only.
- Spec §4.1 says correct data lands "within 1 ULP"; measured worst row is 1.54 ULPs (candidate gap).
- The routing groups are very uneven (74 to 161,376 members): SciQ centroids on NQ data.
- The float32 ghost measured flat (2e-7) over 1,000 cycles, not growing: keep claims to "not
  bit-identical".

## Session log

- **4 Oct 2026**: demo moved to `demo/` and made self-contained (own env and lock, scripts work from
  any directory, `SEVER_DATASETS` data root, git stamp for the container, Dockerfile + compose). Root
  env trimmed to Part 1 packages. G-5 closed: spec §19.2 amended, DB-56. Rust workspace scaffolded
  with an empty `sever-types`. Checks: demo 233 tests (38 must-fail), ruff/mypy clean, smoke run PASS,
  rehearsal script in the shell as expected; cargo fmt/clippy/test pass. Docker build not run (WSL
  integration off).
- **3 Oct 2026 (evening)**: demo shell made guided and self-explaining (tour, notes, explain, status,
  find, insert, clearer verify / ledger / errors); full run prints a claim → evidence table; ledger
  lines carry a plain `summary`. 233 tests. Screenshots re-made from `scripts/rehearsal.txt`.
- **3 Oct 2026**: Part 3 preview added (commitments, proof of knowledge, certificates, offline
  verifier; libsodium via ctypes). Full run PASS: 5 of 5 fields, 912/912 certificates, 10/10 forgeries
  rejected. Python code arranged under `python/`; Day 1 tidy-up; README, runbook, slides (9), Q&A
  21–28 added. Clean-clone check passes on the working tree (216 tests, smoke PASS).
- **2 Oct 2026**: Day 2 and Day 3 of the demo plan built in write mode: IDs, groups, index, partition,
  baselines, ledger, full run (PASS on 1M, 0 mismatches), tests rewritten spec-driven, demo shell,
  runbook, slides, fast environment (`scripts/demo.sh`).
- **1 Oct 2026**: Day 1: data checks (0 norm failures on all three sets) and the Q24 quantiser, with
  tests; notes reorganised into `docs/notes/`.
- **27 Sep 2026**: Build plan Parts 1–4 adopted as the plan of record, replacing the earlier S1–S17
  stage plan. CLAUDE.md, PROGRESS.md, SPEC_GAPS.md and TRACEABILITY.md updated to match.
- **27 Sep 2026**: Specification, overview and CLAUDE.md written. P0 encode running.
