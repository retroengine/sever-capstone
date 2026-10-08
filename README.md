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
| **1 The Idea** | Deleting a vector returns its group, bit for bit, to the never-inserted state | **Done**: every gate passed on 6 Oct 2026; frozen as `part-1-frozen` (see [Part 1 results](#part-1-results)) |
| **2 The Database** | Exactness survives a crash at any point; multi-group deletion is all-or-nothing | **In progress**: built; gates running (see [Part 2](#part-2-the-database)) |
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

## Part 2: The Database

Part 2 puts Part 1's frozen index behind a storage engine (Build §5): a write-ahead log (WAL),
paged storage checkpoints, a payload store for passage text, a transaction protocol with an explicit
commit point, and recovery that refuses to serve a state that breaks any invariant (spec §12, §14,
§15, §16.1, §17). Nothing is encrypted yet: Part 2 stores plaintext through `PlaintextSealer`, marks
the database as plaintext, and makes **no confidentiality claim** (DB-48); Part 4 adds encryption.

### Using it

```bash
scripts/p2-demo.sh --data synthetic            # offline demo (Build §5.9)
scripts/p2-demo.sh --data nq-10k --seed 42     # the same on 10,000 real passages
```

The demo runs one multi-group `delete_user` and crashes it twice, once just before its commit point
and once just after, first on a simulated disk and then with a real `SIGKILL` of a child process.
After every recovery the invariant check passes, the deletion is all or nothing (nothing before the
commit point, everything after it), and Part 1's survivors check holds for every touched group.

The command-line tool prints one JSON line per command (errors are typed §17 kinds and carry no
record ID, vector value or key):

```bash
cargo build --release -p sever-p2
B=target/release/sever-db-p2; D="--data /path/db --keys /path/keys"   # data on ext4 or XFS
$B create $D --artefact golden/p1_partition_small.svp --spawn-target 8   # -> {"cid": "..."}
$B insert $D --cid <cid> --id doc-1 --vector '[0.25, ...]' --passage 'text'
$B delete-user $D --cid <cid> --ids '["doc-1", "doc-2"]'                 # one transaction
$B search $D --cid <cid> --vector '[...]' --k 10
$B verify $D                                                             # recovery + invariant check
```

The Python SDK (PyO3; build it once after every `uv sync` with
`uv run --no-sync maturin develop --release --uv -m crates/sever-py-p2/Cargo.toml`):

```python
from sever_db_p2 import Database
with Database.open("/path/db", "/path/keys") as db:
    cid = db.create_collection("artefacts/partition-seed42.svp")
    db.insert(cid, "doc-1", vector, passage=b"text")      # vector: float32, unit length, d = 384
    db.delete_user(cid, ["doc-1", "doc-2"])                 # ["deleted", "absent"], all or nothing
    db.search(cid, query, k=10)                             # [(record_id, score), ...]
```

A retried insert of the same record with the same vector is a success (`receipt.retried`); a retried
deletion is `"absent"` (§15.1, §15.4). A failed `fsync` aborts the process (§12.7): the next start
recovers.

### Part 2 results

From the run ledger, as for Part 1.

| Target (Build §5.8) | What | Result |
|---|---|---|
| P2-T1…T3 | crash at every VFS operation of 20,000 operations, every 512-byte offset of 200 WAL writes, 1,000 random points, crashes during recovery; five seeds on nq-10k: 0 exactness violations, 0 lost acknowledged operations, 0 corrupt recoveries, 100 % oracle-allowed states, 0 partial `delete_user` | **PASS**: 5 seeds; 343,837 crash points (every VFS operation 321,689, every 512-byte WAL offset 17,148, random 5,000; 6,874 also crashed during recovery) and 28,707 generic-record points; 0 failures of any kind |
| P2-T4 | a reader at every protocol step sees the state before or after, never a mix | engine test (in `gates p2-checks`) |
| P2-T5 | Part 1's traces through the Part 2 engine, plain / close / crash after every rung | **PASS**: 5 seeds × 3 modes on nq-10k, 0 mismatches |
| P2-T6 | 0 fuzz crashes in 10^8 executions per parser | **PASS**: `wal_record`, `manifest`, `checkpoint_file`, `store_record` |
| P2-T7 | contract suites pass and fail for wrong implementations; proof spikes | **PASS** (spikes: AES-GCM-SIV sealer, log and key-rotation participants; recorded, then deleted) |
| P2-T8 | SB-1 … SB-15 each turn a test red | **PASS** |
| P2-T9 | traceability 100 %; lines ≥ 90 %, branches ≥ 85 %, mutation score ≥ 85 % | traceability 46 / 46; coverage **PASS** (lines 94.8 %, branches 86.7 %); mutants: exploratory 652 / 713 = 91.4 %, every survivor triaged in [`docs/MUTANTS_P2.md`](docs/MUTANTS_P2.md); gate run in the ledger |
| P2-T10 | the Part 1 freeze manifest is unchanged | checked by every CI run |
| P2-T11 | bytes and fsyncs per operation, recovery time, memory at nq-100k (measure) | recorded: ≈ 1 fsync per operation; insert 8.1 KB, single delete 14.2 KB, multi-record `delete_user` 24.6 KB written per operation (header and slot after-images in the WAL); recovery 0.05 s from a checkpoint, 0.85 s replaying the WAL since the last automatic checkpoint; peak resident memory 1.09 GB (146,215 operations) |

**Bugs found by the test suite on the way:** recovery silently dropped a damaged committed record in
the newest WAL segment as if it were a torn tail; it now refuses to serve (§12.3).

---

## Part 1 results

Every number below comes from the run ledger, [`docs/RUN_LEDGER.jsonl`](docs/RUN_LEDGER.jsonl)
(append-only, written by the gate runners, never by hand), with the full result in `results/`.

| Target (Build §4.8) | What | Result |
|---|---|---|
| P1-T1 | 0 exactness violations (survivors check on every core field) | **PASS**: nq-100k 427,455 checks, nq-10k 43,562, synthetic L4 275,114; 0 failures |
| P1-T2 | 0 engine/model mismatches, nq-10k and nq-100k, five seeds | **PASS**: nq-10k 10.6 M values, nq-100k 12.4 M values; 0 mismatches |
| P1-T3 | identical blobs across insertion orders | property tests (proptest, ≥ 256 orders) |
| P1-T4 | scalar and AVX2 kernels bit-identical | **PASS**: 10^7 random pairs; nq-10k 508 M and nq-100k 2.25 B real pairs, 0 mismatches |
| P1-T5 | 0 deleted records returned by search | **PASS**: 0, on nq-10k and nq-100k, five seeds each |
| P1-T6 | builder oracle agreement (shrinkage 1e-12, τ 1e-9), five seeds | PASS (largest differences 2e-17 and 1.4e-14) |
| P1-T7 | Recall@10, dequantised vs float brute force, nq-100k (measure, target ≥ 0.999) | **1.000** |
| P1-T8 | SB-1 … SB-10 each turn a test red | **PASS**: all ten red (`gates p1-checks`, with MSRV 1.85, cargo deny, docs, all 17 steps) |
| P1-T9 | traceability 100 % of Part 1's requirements | 70 / 70 (`docs/TRACE_PART_1.md`) |
| P1-T10 | coverage: Rust lines ≥ 90 %, branches ≥ 85 %; Python lines ≥ 90 % | **PASS**: Rust 95.9 % lines, 87.0 % branches; Python 98.8 % |
| P1-T11 | mutation score ≥ 85 %, every survivor triaged | **PASS**: 325 / 347 caught (93.7 %); 22 survivors, each triaged in [`docs/MUTANTS_P1.md`](docs/MUTANTS_P1.md) |
| P1-T12 | 0 fuzz crashes in ≥ 10^8 executions per parser | **PASS**: 10^8 each for `artefact_parse` and `blob_parse`; an earlier run found one real bug, fixed (below) |
| P1-T13 | contract suites pass for every default and fail for a wrong one; proof spikes | PASS (spikes recorded, then deleted, Build §3.4) |
| P1-T14 | the ghost (measure) | nq-10k seed 42: soft-delete IVF 5.0e-3, float mean 1.9e-8, SEVER 0 |

**Bugs found by the test suite on the way** (each fixed with a regression test): the artefact parser
reserved memory from an untrusted header before checking the file length (found by fuzzing: an
88-byte file claimed 5 GB); `apply` could drop the holding area's records on a malformed flush
(found by the forged-change-set tests).

**Definition of done (Build §2.9):** the demo runs from a clean clone with one command
(`scripts/p1-demo.sh`, checked on 6 Oct 2026: the report and the rebuilt partition artefact were
identical to the working copy's, apart from timing), and every Part 1 file is hashed into
[`freeze/PART-1.sha256`](freeze/PART-1.sha256), which CI checks on every run (F-1, F-2).

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
| P1-T11 mutation (worktree of the commit, survivors checked against `docs/MUTANTS_P1.md`) | `… gates p1-mutants --jobs 2` |
| P1-T8 and the rest of the Full-tier checks | `… gates p1-checks` |
| P1-T12 fuzzing | `… gates p1-fuzz --runs 100000000` |
| Build the partition artefacts | `PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_partition.build --all-seeds` |
| One demo | `scripts/p1-demo.sh --data nq-10k --seed 42` |

Run Python with `PYTHONHASHSEED=0`. Memory: an `nq-100k` model process needs about 2.3 GB; with
WSL's default 8 GB run at most two at once (`--jobs 2`), with 10 GB (`memory=10GB` in
`%UserProfile%\.wslconfig`) three, and nothing else heavy beside them.

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
