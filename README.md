# SEVER-DB

A vector database with **provable deletion**.

Most vector databases "delete" by hiding a record: the vector stays in the index, and every summary
built from it (a centroid, a running mean) keeps its trace. SEVER-DB keeps each group of vectors as an
**exact integer sum `S` and count `n`** (vectors are quantised to Q24 integers), so deleting a vector
subtracts it exactly. The group returns, bit for bit, to the state it would have had if the vector had
never arrived. Later parts add a Pedersen commitment to each group and a signed, publicly verifiable
deletion certificate, and crypto-shredding of everything deleted.

It is built in **four parts**. Each part adds one claim, is tested against its own gates, and is then
frozen (Build §0.1):

| Part | The claim it adds | Status |
|---|---|---|
| **1 The Idea** | Deleting a vector returns its group, bit for bit, to the never-inserted state | **Built; gates being recorded** (see [Part 1 results](#part-1-results)) |
| 2 The Database | Exactness survives a crash at any point; multi-group deletion is all-or-nothing | Starts when Part 1 is frozen |
| 3 The Receipt | Every deletion yields a certificate anyone can verify offline | Not started (a preview exists in `demo/`) |
| 4 The Erasure | Nothing deleted can be recovered from raw storage | Not started |

Where things stand in detail: [`docs/PROGRESS.md`](docs/PROGRESS.md). Working rules for contributors
and AI assistants: [`CLAUDE.md`](CLAUDE.md).

---

## Quick start

Everything runs under WSL2 (Ubuntu) or Linux, from the repository root.

```bash
# 1. Toolchains: Rust is pinned by rust-toolchain.toml (1.98.1); Python 3.13 by uv.
uv sync --locked

# 2. The offline demo: no data needed (golden fixture, d = 16, 4 frozen groups, spawn size 8)
scripts/p1-demo.sh --data synthetic

# 3. The fast test tier (format, lint, types, unit/property/stateful tests, spec-trace, L13)
scripts/ci.sh fast
```

The real-data demo needs the P0 data in `datasets/` (not in git; pinned by `datasets/PINS.json`,
verified by `datasets/MANIFEST.sha256`):

```bash
(cd datasets && sha256sum -c MANIFEST.sha256)   # 9 files, all OK
scripts/p1-demo.sh --data nq-10k --seed 42      # builds what is missing, runs, renders the report
```

### What the demo shows (Build §4.9)

`sever-demo idea` streams 10,000 Natural Questions passages into an index over a partition fitted on
SciQ, picks one article's passages (a *cohort*), deletes them with one `delete_user`, and checks:

1. every touched group's canonical blob is **byte-identical** to the blob of a group rebuilt from its
   surviving members' original vectors alone;
2. every other group is unchanged, `N` falls by exactly the cohort's size, and deleting again is
   `AlreadyAbsent` with the state unchanged;
3. no search (all 3,452 real queries, plus each deleted vector's own) returns a deleted passage;
4. **the ghost**: the same deletion in a soft-delete IVF index (the record is still stored and its
   centroid still carries it) and in a float running-mean index (its mean no longer matches the
   survivors-only mean bit for bit), side by side with SEVER's distance of exactly 0.

It prints tables and writes `artefacts/demo/idea-<data>-seed<seed>.json` plus an HTML report page.

---

## Part 1 results

Every number below comes from the run ledger, [`docs/RUN_LEDGER.jsonl`](docs/RUN_LEDGER.jsonl)
(append-only, written by the gate runners, never by hand), with the full result in `results/`.

| Target (Build §4.8) | What | Result |
|---|---|---|
| P1-T1 | 0 exactness violations (survivors check on every core field) | nq-10k: 43,562 checks, 0 failures; synthetic L4: 275,114 checks, 0 failures |
| P1-T2 | 0 engine/model mismatches, nq-10k and nq-100k, five seeds | nq-10k: **PASS**, 10.6 M values, 0 mismatches · nq-100k: see ledger |
| P1-T3 | identical blobs across insertion orders | property tests (proptest, ≥ 256 orders) |
| P1-T4 | scalar and AVX2 kernels bit-identical | 10^7 random pairs; nq-10k: 508 M pairs, 0 mismatches |
| P1-T5 | 0 deleted records returned by search | nq-10k five seeds: 0 |
| P1-T6 | builder oracle agreement (shrinkage 1e-12, τ 1e-9), five seeds | PASS (largest differences 2e-17 and 1.4e-14) |
| P1-T7 | Recall@10, dequantised vs float brute force, nq-100k (measure, target ≥ 0.999) | **1.000** |
| P1-T8 | SB-1 … SB-10 each turn a test red | `tests/sabotage/run.sh`: all ten red |
| P1-T9 | traceability 100 % of Part 1's requirements | 70 / 70 (`docs/TRACE_PART_1.md`) |
| P1-T10 | coverage: Rust lines ≥ 90 %, branches ≥ 85 %; Python lines ≥ 90 % | see ledger (`gates p1-coverage`) |
| P1-T11 | mutation score ≥ 85 %, every survivor triaged | see ledger and `docs/MUTANTS_P1.md` |
| P1-T12 | 0 fuzz crashes in ≥ 10^8 executions per parser | see ledger (`gates p1-fuzz`); one real bug found and fixed (below) |
| P1-T13 | contract suites pass for every default and fail for a wrong one; proof spikes | PASS (spikes recorded, then deleted, Build §3.4) |
| P1-T14 | the ghost (measure) | nq-10k seed 42: soft-delete IVF 5.0e-3, float mean 1.9e-8, SEVER 0 |

**Bugs found by the test suite on the way** (each fixed with a regression test): the artefact parser
reserved memory from an untrusted header before checking the file length (found by fuzzing: an
88-byte file claimed 5 GB); `apply` could drop the holding area's records on a malformed flush
(found by the forged-change-set tests).

---

## How it is tested

The specification is the source of truth; tests are written from it, not from the code.

- **Requirement IDs.** Every normative statement has an ID `SR-<section>-<n>` in
  [`spec/requirements.yaml`](spec/requirements.yaml). Rust tests name them with `#[spec("SR-…")]`
  (crate `sever-spec`), Python tests with `@pytest.mark.spec("SR-…")`.
  `python -m sever_testkit.spec_trace` builds the matrix and fails on an untraced requirement.
- **An independent oracle.** The reference model `sever_refmodel_core` (Python, written from the spec
  only) runs every stream and writes a **trace**; the Rust replayer `sever-tracekit` runs the same
  operations through the engine and compares every value: placements, outcomes, the SHA-256 of every
  touched group after every operation, and all groups, stats and top-100 search results at each
  deletion rung. After every deletion it also rebuilds each touched group from its survivors and
  compares bytes, and it scores every query–vector pair with both kernels.
- **Levels L1–L14** (Build §2.1): unit, property (proptest, Hypothesis), spec conformance,
  differential (nq-10k/nq-100k, 1,000 synthetic streams), model-based stateful (Hypothesis
  sequences replayed by the engine), metamorphic (survivors check, whole-index twin), contract suites
  for the extension points, integration, end-to-end (E2E-1.1 … 1.7), fuzzing (cargo-fuzz), mutation
  (cargo-mutants), sabotage, architecture (no I/O, clock or randomness in the core; dependency
  direction; `unsafe` only in the SIMD kernel).
- **Sabotage.** Each SB-N builds the code with exactly one deliberate bug (`--features sabotage-SB-N`);
  `tests/sabotage/run.sh` checks that every one turns a test red.
- **Gates vs measures.** A missed gate is a bug. A measure is recorded as found and never a reason to
  change code or rerun. Every run is in the ledger, including the aborted ones.

### Commands

| Purpose | Command |
|---|---|
| Fast tier | `scripts/ci.sh fast` |
| Fast + Full-tier checks (ignored tests, slow tests, sabotage, MSRV 1.85, cargo deny, docs) | `scripts/ci.sh full-checks` |
| P1-T2/T5 (+T1, T4) differential gate | `PYTHONPATH=python uv run python -m sever_testkit.gates p1-differential --data nq-10k --all-seeds --jobs 5` |
| L4 synthetic streams | `… gates p1-synthetic --streams 1000 --ops 1000 --jobs 3` |
| P1-T7 measure | `… gates p1-quant-recall --data nq-100k` |
| P1-T10 coverage | `… gates p1-coverage` |
| P1-T12 fuzzing | `… gates p1-fuzz --runs 100000000` |
| Build the partition artefacts | `PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_partition.build --all-seeds` |
| One demo | `scripts/p1-demo.sh --data nq-10k --seed 42` |

Run Python with `PYTHONHASHSEED=0`. Memory: an `nq-100k` model process needs about 2.3 GB; on an
8 GB machine run at most two at once (`--jobs 2`) and nothing else heavy beside them.

---

## Layout (spec §19.2, Build §3.2)

| Path | What |
|---|---|
| `crates/sever-types` | Record, group and collection IDs; constants (§2.2); every §17 error; `SecretBuf` and EP-4 |
| `crates/sever-quant` | Normalisation check, Q24 quantisation (ties to even), dequantisation (§4) |
| `crates/sever-partition` | Parser and checks for the partition artefact `partition.svp` (§6.3) |
| `crates/sever-index` | Groups, exact accumulators, routing and drift test, holding area and flush, `plan`/`apply` with `ChangeSet`, canonical blob, invariants; declares EP-1, EP-2, EP-3 (§5, §7, §9.7) |
| `crates/sever-search` | IVF-flat search over the float32 mirror; pinned scalar and AVX2 kernels (§8) |
| `crates/sever-tracekit` | Trace replayer: the engine against the reference model |
| `crates/sever-p1` | Composition root (OS entropy for the scrambling key), ghost baselines, `sever-demo` CLI |
| `crates/sever-spec` | The `#[spec("SR-…")]` test attribute |
| `python/sever_partition` | Partition builder C-15 with an independent Ledoit–Wolf oracle (§6.2) |
| `python/sever_refmodel_core` | Reference model C-18 (§3–§8) |
| `python/sever_testkit` | Seeds, synthetic data, slices, traces, streams, run ledger, gate runners, `spec_trace` |
| `python/sever_demo` | HTML report for the demo |
| `tests/architecture`, `tests/sabotage` | L13 rules; the sabotage register runner |
| `fuzz/` | cargo-fuzz targets and committed seeds (separate workspace, nightly) |
| `golden/` | Golden vectors (spec Appendix B) and regression inputs; changed only with a recorded reason |
| `spec/requirements.yaml` | The requirement catalogue |
| `configs/experiments.yaml` | The pre-registration (Overview §3.4, §12) |
| `docs/` | Specification, overview, build plans, progress, spec gaps, traceability, run ledger |
| `datasets/` | Data pins and manifest (the data files are not in git) |
| `scripts/` | `ci.sh` (CI tiers), `p1-demo.sh`, the P0 data tool |
| `demo/` | The 5 Oct 2026 review prototype: self-contained, nothing here depends on it |

Generated, not in git: `artefacts/` (partition artefacts, ID export, demo reports), `traces/`,
`results/` scratch, `target/`.

## Documents

| Document | Role |
|---|---|
| [`docs/SEVER-DB_SPECIFICATION.md`](docs/SEVER-DB_SPECIFICATION.md) | **Normative**: what the software must do, byte for byte (cite as §N) |
| [`docs/SEVER-DB_PROJECT_OVERVIEW.md`](docs/SEVER-DB_PROJECT_OVERVIEW.md) | Why: decisions (DB-N), targets, testing strategy, limits |
| [`docs/SEVER-DB_BUILD_PLAN_PART_1-2.md`](docs/SEVER-DB_BUILD_PLAN_PART_1-2.md), [`…PART_3-4.md`](docs/SEVER-DB_BUILD_PLAN_PART_3-4.md) | How it is built: parts, freeze rule, test plans, gates |
| [`docs/SPEC_GAPS.md`](docs/SPEC_GAPS.md) | Every place the spec was unclear, and the decision that closed it |
| [`docs/TRACE_PART_1.md`](docs/TRACE_PART_1.md) | Requirement → test matrix (generated) |

## Data and licences

The corpora are BeIR/NQ (CC BY-SA 3.0) and SciQ (CC BY-NC 3.0), embedded with
`sentence-transformers/all-MiniLM-L6-v2`; exact revisions in `datasets/PINS.json` and
`configs/experiments.yaml`. Rust dependencies are checked with `cargo deny` (`deny.toml`).
