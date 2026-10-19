# Part 1 walkthrough: the code, the tests, and everything we did

Written on 6 Oct 2026, the day Part 1 was frozen (tag `part-1-frozen`). Part 1 was built in write
mode: Claude wrote the code while you directed it. This document is the "learn after" half: it walks
through every piece in plain words first, then with the exact terms and the spec sections (§N) the
code implements.

How to read it: sections 1–3 are the big picture, so read them first. Sections 4–9 walk through the
code one crate or package at a time, in the order data flows through the system. Sections 10–13 cover
how we proved it works, what went wrong on the way, and what is next. Section 14 is a glossary, and
section 15 has questions to check your own understanding.

---

## Contents

1. [The idea in plain words](#1-the-idea-in-plain-words)
2. [The rules we work under](#2-the-rules-we-work-under)
3. [What we did, day by day](#3-what-we-did-day-by-day)
4. [The repository map](#4-the-repository-map)
5. [The architecture in one picture](#5-the-architecture-in-one-picture)
6. [Walkthrough: the foundation (`sever-types`, `sever-quant`)](#6-walkthrough-the-foundation)
7. [Walkthrough: the partition (Python builder, Rust importer)](#7-walkthrough-the-partition)
8. [Walkthrough: the index (`sever-index`)](#8-walkthrough-the-index)
9. [Walkthrough: search, the reference model, the demo](#9-walkthrough-search-the-reference-model-the-demo)
10. [How we proved it: the testing system](#10-how-we-proved-it-the-testing-system)
11. [The gates and their results](#11-the-gates-and-their-results)
12. [Bugs, failures and lessons](#12-bugs-failures-and-lessons)
13. [Run ledger, CI, freeze, git](#13-run-ledger-ci-freeze-git)
14. [Glossary](#14-glossary)
15. [Check yourself](#15-check-yourself)

---

## 1. The idea in plain words

### 1.1 The problem

A vector database stores **embeddings**: lists of numbers (384 of them here) that a model computes
from a passage of text. Similar passages get similar vectors. To search fast, the database puts
vectors into **groups** (clusters) and keeps a summary of each group, usually its average (the
**centroid**). A search first finds the closest groups and then looks only inside those.

Now someone asks for their data to be deleted. Typical databases do one of two things:

- **Tombstone** it: mark the record "deleted" but leave it in place. The group's average still
  includes it. The person's vector still shapes the index: a **ghost**.
- **Subtract** it from a running floating-point average. This looks right but is not exact.
  Floating-point addition rounds, so `(a + b) − b` is often not `a`. In float32,
  `(0.1 + 10,000,000) − 10,000,000 = 0`, not 0.1. A trace of the deleted vector stays in the low bits.

So the question SEVER-DB answers is: **after you delete a vector, is the index exactly as if that
vector had never been inserted?** Not approximately. Bit for bit.

### 1.2 The answer of Part 1

Part 1's claim (CLAUDE.md §6.1): *deleting a vector returns its group, bit for bit, to the state it
would have had if the vector had never arrived.*

It works in three steps:

1. **Turn floats into integers once, at the door (quantisation, §4.2).** Each component `x_i` becomes
   the integer `x̃_i = round_half_to_even(x_i · 2^24)`. This is called **Q24**: 24 fractional bits.
   From then on, the database only adds and subtracts integers.
2. **Keep an exact integer sum per group.** Each group stores `S` (one `i64` per dimension) and `n`
   (how many members). Insert: `S += x̃`, `n += 1`. Delete: `S −= x̃`, `n −= 1` (§5.3).
3. **Integer addition is exact and order-free.** `(a + b) − b = a` always, for integers that don't
   overflow, and the spec proves they can't: at most 10^6 members, each `|x̃_i| ≤ 2^24 + 16`, so
   `|S_i| < 2^44`, far inside `i64` (Appendix A). So after a deletion, `S` is exactly the sum of the
   survivors.

### 1.3 A worked example in numbers

Three 2-D vectors in one group (unit vectors, so they pass the normalisation check):

| Vector | float32 value | Q24 integers `x̃` |
|---|---|---|
| a | (0.6, 0.8) | (10,066,330, 13,421,773) |
| b | (0.8, −0.6) | (13,421,773, −10,066,330) |
| c | (−0.28, 0.96) | (−4,697,620, 16,106,127) |

`S = a + b + c = (18,790,483, 19,461,570)`, `n = 3`.

Delete `b`: `S − b = (5,368,710, 29,527,900)`, `n = 2`. A group built from `a` and `c` alone has
`S = (5,368,710, 29,527,900)`. **Identical.**

Now do the same with a float32 running mean, as many systems do: insert a, b, c updating the mean,
then remove b. The result is `(0.16000006, 0.87999994)`. The true mean of the survivors is
`(0.16000001, 0.88)`. It's off by about `5 × 10^−8`: that is the ghost. Our demo measures exactly this
on real data (P1-T14): float running mean `1.9 × 10^−8`, tombstone IVF `5.0 × 10^−3`, SEVER `0`.

### 1.4 Why not just recompute the average from scratch?

You could, for one small group. But the spec's later parts need more than a correct average: Part 3
publishes a **commitment** to each group's exact sum (a Pedersen commitment `C_S`) so that anyone can
verify a deletion without database access. A commitment over a float sum would be meaningless. An exact
integer sum is the foundation everything else is built on.

### 1.5 What the rounding costs

Quantising loses a tiny bit of precision (at most half of `2^−24 ≈ 6 × 10^−8` per component). Does
that hurt search quality? We measured it (P1-T7): on 100,000 real passages, Recall@10 of search over
the quantised vectors, compared with the original floats, is **1.000** (the target was ≥ 0.999).
Quantisation costs nothing measurable.

---

## 2. The rules we work under

### 2.1 The documents (CLAUDE.md §2)

| Document | What it is | How we cite it |
|---|---|---|
| `docs/SEVER-DB_SPECIFICATION.md` | **Normative.** What the software must do, byte for byte. Every "MUST" has an ID `SR-<section>-<n>` in `spec/requirements.yaml`. | §N |
| `docs/SEVER-DB_PROJECT_OVERVIEW.md` | Why: decisions (DB-N), targets (T-N), limits, experiments. | Overview §N, DB-N |
| `docs/SEVER-DB_BUILD_PLAN_PART_1-2.md` | How it is built: parts, freeze rule, test levels, extension points, gates. | Build §N, P1-Tn, SB-N, EP-N |
| `docs/PROGRESS.md` | Where we are now. | — |
| The code | Must agree with the above. If it disagrees, the code is wrong or the spec has a gap. | — |

**The spec wins.** When the spec was unclear, we did not guess. We recorded a **gap** (`G-N` in
`docs/SPEC_GAPS.md`), fixed the spec text, and added a **decision** (`DB-N` in the overview), all in
one commit. Part 1 closed G-1 and G-5 … G-12 this way (DB-56 … DB-64). Examples:

- **G-8 → DB-60:** the spec's §4.1 check had no explicit "right number of components?" step. We added
  step 0, the dimension check, before anything else.
- **G-10 → DB-62:** the spawn size (200) is a runtime value, so tests can use 8 on small fixtures.
- **G-11 → DB-63:** at most 10,000 frozen groups, because group IDs are `frozen-NNNN` (4 digits).

### 2.2 The four parts and the freeze (Build §0)

The project is built in four parts. Each adds exactly one claim and is then **frozen**:

| Part | Claim |
|---|---|
| **1 The Idea** (done) | Deletion is exact, bit for bit |
| 2 The Database | Exactness survives crashes; multi-group deletion is all-or-nothing |
| 3 The Receipt | Every deletion yields a certificate anyone can verify offline |
| 4 The Erasure | Nothing deleted can be recovered from raw storage |

**Freezing** (F-1 … F-6) means: every file Part 1 owns is hashed into `freeze/PART-1.sha256`, CI fails
if any of them changes (F-2), and later parts may only *extend* Part 1 through the **extension
points** it declared (F-3), never edit it. The only way to fix a frozen part is a formal erratum
(F-6). This is why Part 1's design puts so much care into extension points: they are the only doors
later parts can use.

### 2.3 Rules for the code (CLAUDE.md §7, Build §1)

- **Plan, then apply.** Every change is computed by a pure `plan` function that returns a description
  of the change (a `ChangeSet`), and installed by `apply`, which **cannot fail**. All validation happens
  in `plan`. Why: Part 2 will write the `ChangeSet` to a log *before* applying it. If `apply` could
  fail halfway, a crash could leave a half-applied state.
- **The core is pure.** `sever-index`, `sever-quant` and `sever-search` read no files, no clock and no
  random numbers. The only secret input (the scrambling key) is handed in from outside. This makes
  every behaviour reproducible and testable.
- **No panics in library code.** `unwrap`, `expect`, `panic!` and unchecked indexing (`v[i]`) are
  denied by the linter (`Cargo.toml`, `[workspace.lints.clippy]`). Every failure is a typed error.
- **No `unsafe`** except where listed (the AVX2 kernel), with a `SAFETY:` note on every block.
- **Errors never leak data** (§17): no record ID, vector value, key or text in any error message.
- **Seeds only for data order, synthetic data and k-means.** Keys and IDs come from the operating
  system's random generator (CSPRNG). "Never pass a seed into proof or key generation."
- **Float sums in a pinned order.** Floating-point addition is not associative, so the Rust engine
  and the Python model must add in exactly the same order to produce the same bits (§7.1, §7.2,
  §8.2). In Python that means `np.cumsum(...)[..., -1]`, which adds sequentially; `np.sum` and `@` do
  not.

### 2.4 How we work (CLAUDE.md §3, your memory rules)

- The default mode is "coach", but for Part 1 you set a temporary rule: **build first, learn after**.
  Claude wrote everything, and this document is the learning half.
- **You commit everything.** Since 6 Oct, Claude never runs `git commit`, `tag`, `merge` or `push`, and
  no Claude attribution appears in the log. Claude hands you the commands.

---

## 3. What we did, day by day

### 27 Sep: P0, data and documents

- You wrote the specification, overview and build plan, and CLAUDE.md.
- **P0 data:** the reference corpus (SciQ, encoded to 384-dimension vectors with
  `all-MiniLM-L6-v2`) and the live corpus (1 million Natural Questions passages, `nq_1m`) plus 3,452
  queries. Everything is pinned in `datasets/PINS.json` and checked by `datasets/MANIFEST.sha256`
  (SHA-256 of every file). The data is never edited again (CLAUDE.md §8).

### 1–3 Oct: the review demo

A self-contained prototype in `demo/` (its own environment) to try the ideas: data checks, quantiser,
index, baselines, and a Part 3 preview with commitments and an offline verifier. It is not part of the
engine and nothing depends on it (DB-56).

### 4 Oct: the core, in one day

In order (each a commit):

1. Accepted Part 1 decisions, closed early gaps, set up the Rust workspace with strict lints and
   toolchain 1.98.1.
2. **`sever-types`**: IDs, errors, secret buffers.
3. **`sever-quant`**: the normalisation check and Q24.
4. **Partition**: Python builder (k-means + Ledoit–Wolf + τ) with an independent oracle, and the Rust
   parser for its file.
5. **Reference model** (Python): the whole Part 1 behaviour, written from the spec only.
6. **`sever-index`** and **`sever-search`**: the engine.
7. **`sever-tracekit`** and **`sever_testkit`**: differential testing, the run ledger, gate runners.
8. Moved the project from the Windows drive to the WSL Linux filesystem (`~/sever-db`), which made
   builds and tests much faster.

### 5 Oct: the composition root, the demo, the test levels

- `sever-p1`: composition root, ghost baselines, `sever-demo idea`, and the HTML report.
- `#[spec]` attribute and `spec-trace` (traceability), architecture tests (L13), fuzz targets (L11),
  stateful tests (L5), the synthetic stream gate, proof spikes (Pedersen commitments on ristretto255
  pass EP-1; then deleted as the build plan requires).
- Recorded gates: nq-10k differential (5 seeds), P1-T7 recall, L4 synthetic.
- Bugs found and fixed: the artefact parser allocating gigabytes from a malicious header (fuzzing),
  and `apply` losing records on a malformed flush (forged change-set tests).
- Dependency pins for spec §20.3 check 1 (no duplicate crypto crate versions).
- Several long runs were lost to the out-of-memory killer and to WSL restarts when the laptop slept.
  All were recorded in the ledger as aborted.

### 6 Oct: closing gaps, gates, freeze

- Closed G-9 … G-12 (DB-61 … DB-64); made the AVX2 kernel build on the minimum Rust version 1.85.
- **Mutation testing:** triaged the survivors, added tests that kill the real gaps, and documented the
  rest in `docs/MUTANTS_P1.md`.
- CI scripts, the freeze script, the one-command demo, `configs/experiments.yaml`, and a full README.
- **You took over git**, rewrote history to remove the co-author lines, and renamed the branch to
  `main`. `docs/COMMIT_MAP.txt` maps old hashes (still cited in the ledger) to the new ones.
- Recorded every remaining gate on clean commits (section 11), gave WSL 10 GB, ran nq-100k with three
  seeds in parallel, then **froze Part 1** and tagged `part-1-frozen`.

---

## 4. The repository map

```text
sever-db/
├── Cargo.toml, rust-toolchain.toml, clippy.toml, rustfmt.toml, deny.toml   Rust workspace + rules
├── pyproject.toml, uv.lock, .python-version                                Python environment (uv)
├── CLAUDE.md, README.md
├── crates/                              ── Rust ──
│   ├── sever-types/        vocabulary: IDs, constants, errors, SecretBuf (EP-4)
│   ├── sever-quant/        §4: normalisation check, Q24 quantise / dequantise
│   ├── sever-partition/    §6.3: parse + validate the partition artefact file
│   ├── sever-index/        §5, §7, §9.7: groups, routing, flush, plan/apply (EP-1, EP-2, EP-3)
│   ├── sever-search/       §8: IVF search, scalar + AVX2 kernels
│   ├── sever-spec/         #[spec("SR-…")] attribute for traceability
│   ├── sever-tracekit/     replays Python traces through the Rust engine and compares
│   └── sever-p1/           composition root, ghost baselines, sever-demo binary, E2E tests
├── python/                              ── Python ──
│   ├── sever_partition/    C-15: the partition builder (k-means, Ledoit–Wolf, τ) + its oracle
│   ├── sever_refmodel_core/ C-18: the reference model, Part 1's oracle
│   ├── sever_testkit/      traces, synthetic streams, slices, seeds, run ledger, gate runners
│   └── sever_demo/         renders the demo's JSON report as an HTML page
├── tests/
│   ├── architecture/       L13 rules (dependencies, no I/O in the core, unsafe allow-list…)
│   └── sabotage/run.sh     L12: builds each SB-N bug and checks a test goes red
├── fuzz/                   L11: cargo-fuzz targets and seed inputs (separate workspace)
├── golden/                 frozen reference files (small artefact, fixture vectors, blobs)
├── spec/requirements.yaml  every MUST of the spec with its SR-ID
├── configs/experiments.yaml the pre-registered experiment plan (Overview §12)
├── scripts/                ci.sh, freeze.sh, p1-demo.sh, data preparation
├── freeze/PART-1.sha256    the freeze manifest (81 files)
├── docs/                   spec, overview, build plans, progress, gaps, traceability,
│                           RUN_LEDGER.jsonl, MUTANTS_P1.md, COMMIT_MAP.txt, this file
├── results/                write-once result files of gate runs (cited by the ledger)
├── datasets/               P0 data (only PINS, MANIFEST, meta.json are in git)
├── artefacts/              built files (partition .svp, ID export, demo reports); not in git
├── traces/                 trace files and logs of runs; not in git
└── demo/                   the self-contained review prototype (not part of the engine)
```

Size: about 7,000 lines of Rust and 3,500 of Python for Part 1, including tests. 108 Rust tests
(3 of them slow, marked `#[ignore]`, run in the Full tier), 90 Python tests, 70 requirement IDs traced.

---

## 5. The architecture in one picture

### 5.1 Who depends on whom

```text
                         sever-types   (IDs, errors, constants, SecretBuf)
                              ▲
                ┌─────────────┼──────────────┐
           sever-quant   sever-partition     │
                ▲             ▲              │
                └──────┬──────┘              │
                  sever-index  ◄─────────────┘     (EP-1 GroupExtension, EP-2 IdScrambler,
                       ▲                               EP-3 ChangeSet)
                  sever-search
                       ▲
          ┌────────────┴────────────┐
     sever-p1 (composition root)   sever-tracekit (test tooling)
     reads files, OS randomness    reads traces, compares with Python

  Python, side by side, sharing no code with Rust:
     sever_partition (C-15 builder) ──writes──► partition.svp ──read by──► sever-partition
     sever_refmodel_core (C-18 model) ──writes──► trace.jsonl ──replayed by──► sever-tracekit
```

The arrows only point **inward** (toward `sever-types`) and only to the same or earlier parts. The
architecture tests (L13) check this on every CI run.

### 5.2 Pure core, impure edge

The **composition root** (`sever-p1/src/root.rs`) is the one place that touches the outside world on
the engine's behalf. It asks the OS for 64 random bytes (the scrambling key) and 16 random bytes (the
collection ID), builds the index, and hands them in. Everything inside the core is a pure function
of its inputs. That is why the same trace replayed twice gives the same bytes, and why the Rust engine
can be compared value by value with a Python model.

### 5.3 Plan, then apply

```text
   request ──► plan(&self, req) ──► ChangeSet  ──► apply(&mut self, cs)
               (pure: reads only;                 (cannot fail; installs
                every check here;                  exactly what the plan
                may return Error)                  described)
```

A `ChangeSet` lists everything a mutation does: new groups, each touched group's state before and
after, slot operations, locator operations, the counters `N` and `k` before and after, which records
arrived and departed, and one outcome per request. Part 2 will log it, Part 3 will build certificates
from it, and Part 4 will rotate keys from its departures, all without editing Part 1 (EP-3).

### 5.4 The extension points Part 1 declares

| EP | Where | Trait / type | Part 1 default | Later |
|---|---|---|---|---|
| EP-1 | `sever-index/src/ext.rs` | `GroupExtension`: extra per-group and per-record state that changes in lockstep with `S` and `n` | `NoExtension` (no extra state) | Part 3: commitments `C_S`, `r_agg`, `C_t`, `r_t` |
| EP-2 | `sever-index/src/scramble.rs` | `IdScrambler`: record ID → 64-byte scrambled ID | `HmacSha512Scrambler` | — |
| EP-3 | `sever-index/src/changeset.rs` | `ChangeSet` with public fields | — | Part 2 log, Part 3 certificate, Part 4 key rotation |
| EP-4 | `sever-types/src/secret.rs` | `SecretMemory`: where secret bytes live | `HeapProvider` (zeroed on drop) | Part 4: `mlock`ed pages |

Each one has a **contract suite** (`contract.rs`): a set of checks any implementation must pass, for
example "add then remove restores the state exactly" and "the order of adds doesn't matter". Before
freezing, we proved the doors fit with **proof spikes** (Build §3.4): a throwaway Pedersen-commitment
extension on ristretto255 passed EP-1's contract, and a throwaway rotation reader consumed EP-3. Both
were then deleted, as the plan requires.

---

## 6. Walkthrough: the foundation

### 6.1 `sever-types`: the vocabulary

Every other crate speaks in these types. Files: `crates/sever-types/src/`.

**`constants.rs`: the numbers of §2.2.** `DIMENSION_V1 = 384`, `FRACTIONAL_BITS = 24`,
`SCALE = 2^24`, `NORM_TOLERANCE = 8 · 2^−23` (8 float32 ULPs at 1.0), `FROZEN_GROUPS_V1 = 128`,
`MAX_GROUP_MEMBERS = 1,000,000`, `SPAWN_TARGET_SIZE = 200`, `CAPACITY_MULTIPLIER = (3, 2)`,
`PROBE_COVERAGE = (1, 4)`. Ratios are stored as integer pairs, so tests like "has room" are exact
integer arithmetic, never floats. The tests check the Appendix A bounds: the largest `|x̃_i|` is
`2^24 + 16`, and 10^6 of them sum to less than `2^44`, which leaves 19 bits of headroom in `i64`.

**`id.rs`: identifiers.**

- `RecordId`: 1–256 bytes of UTF-8, and **not** a bare integer like `"123"` or `"-7"` (§3.2 rule 2,
  checked with a full match of `^[+-]?[0-9]+$`, ASCII digits only). Why forbid integers? Integer IDs
  usually come from a counter, and a counter leaks insertion order. IDs sort by raw UTF-8 bytes. Its
  `Debug` prints only the length, so an ID can never slip into a log. Its bytes are zeroed when it is
  dropped (§12.6).
- `GroupId`: three kinds. `frozen-0042` (from the partition), `spawn-` + 16 hex characters (created by
  a flush), and `holding` (the waiting area). They order by their text bytes, which is what the
  tie-breaks in §7.3 and §8.1 need.
- `CollectionId` (16 bytes) and `ScrambledId` (64 bytes, see EP-2).

**`error.rs`: every error of §17.** One enum variant per row of the §17 table, *including the ones
only later parts raise*. That is deliberate: the enum is frozen, so Part 3 must not have to add a
variant. Messages are fixed text. `IntegrityViolation { invariant: "INV-6" }` names the broken rule,
never a value.

**`secret.rs`: `SecretBuf` and EP-4.** A byte buffer for secrets (like the scrambling key) that
overwrites itself with zeros before it is freed. Where the memory comes from is decided by a
**provider** installed once at startup. Part 1 uses the heap; Part 4 will lock the pages so they never
get swapped to disk.

### 6.2 `sever-quant`: the only door from floats to integers

File: `crates/sever-quant/src/lib.rs`. This is §4.1–4.3 in about 150 lines.

**`check_normalised(x, d)`, §4.1**, in the spec's step order:

0. exactly `d` components, else `WrongDimension` (step 0 added by DB-60);
1. every component finite (no NaN or infinity), else `NonFinite`;
2. `norm = sqrt(Σ x_i²)` computed in float64, **summed sequentially from i = 0**;
3. `|norm − 1| ≤ 8 · 2^−23`, else `NotNormalised`.

The engine **checks** normalisation but never **performs** it. If a client sends an unnormalised
vector, that is the client's bug, and silently fixing it would hide the bug.

Why is the sum exact enough to compare across languages? Converting f32 to f64 is exact, and squaring a
24-bit significand fits in f64's 53 bits, so the only roundings are the additions. Done in the same
order, Rust and Python get the same bits.

**`quantise(x, d)`, §4.2:** runs the check, then `round_half_to_even(f64(x_i) · 2^24)` per
component, stored as `i32`. **Round half to even** ("banker's rounding"): 2.5 → 2, 3.5 → 4. It has no
bias up or down. Multiplying by a power of two is exact, so the rounding is the only inexact step.
After the check, `|x̃_i| ≤ 2^24 + 16 < 2^31`, so it fits `i32`. `try_from` turns an impossible
overflow into an error instead of a silently wrapped value.

`QVec` is the quantised vector type. **The only way to make one from floats is `quantise`** (INV-1:
no bypass). `QVec::from_stored` exists for Part 2, which will read vectors back from disk, and it
re-checks the dimension and the bound. Its `Debug` hides the values.

**Dequantise, §4.3:** `x̂_i = x̃_i / 2^24`. In f64 this is exact. In f32 it is exact whenever
`|x̃_i| ≤ 2^24`. Routing uses the f64 form; search uses the f32 form (the **mirror**, below).

Example: `0.1` in float32 is `0.100000001490116…`; times `2^24` gives `1,677,721.625`, which rounds to
`1,677,722`. `0.6` gives exactly `10,066,330.0`, so no rounding is needed.

---

## 7. Walkthrough: the partition

### 7.1 What a partition is and why it is frozen

The 128 **frozen groups** come from a clustering of the reference corpus (SciQ), computed **offline**
by Python and saved as a file, `partition.svp`. The engine never fits a model: it only imports the
file (§6.1). Why freeze the clusters? If the centroids moved as data arrived, a record's group would
depend on what else had arrived, and "as if never inserted" would be impossible to define. Fixed
centroids make routing a pure function of the vector.

### 7.2 The builder, C-15 (`python/sever_partition/build.py`)

`build()` follows §6.2 steps 1–7:

1. Check every reference row (§4.1), then **quantise and dequantise**. Every later step uses the same
   `x̂` the engine will see.
2. **k-means** with 128 clusters (scikit-learn, `k-means++`, 10 restarts, seed derived from the run
   seed as `sub_seed(seed, "kmeans") mod 2^32`, DB-57). It runs on one thread so reruns are
   bit-identical.
3. **Residuals**: each row minus its own centroid.
4. **One pooled Ledoit–Wolf covariance** of all residuals. Ledoit–Wolf "shrinks" the sample covariance
   toward a multiple of the identity, which keeps it invertible and stable in 384 dimensions.
5. **Precision matrix** `P = Σ⁻¹` by Cholesky factorisation.
6. **The drift threshold τ**: for every reference row, its Mahalanobis distance to its own centroid;
   τ is the 99th percentile. A new vector farther than τ from its nearest centroid is **out of
   distribution**.
7. **The independent oracle** (`lw_oracle.py`): Ledoit–Wolf re-implemented in plain NumPy from the
   2004 paper, sharing no code with scikit-learn. The builder **refuses to write** the file unless the
   two agree on the shrinkage to `1e-12` and on τ to `1e-9`. That agreement is gate P1-T6.

**Mahalanobis distance** (§7.2), in plain words: the ordinary distance, but measured in units of how
spread out the data normally is in each direction. A step along a direction where the data rarely
varies counts for more. Formula: `δ = x̂ − μ`, `d_M = sqrt(δᵀ P δ)`, summed in a pinned order.

**Sabotage SB-10** lives here: with `SEVER_SABOTAGE=SB-10`, step 4 averages one Ledoit–Wolf fit per
group instead of one pooled fit. The oracle must then refuse the artefact, and it does.

### 7.3 The file format (§6.3) and the Rust importer (`crates/sever-partition`)

```text
"SVDBPART" ‖ u16 version=1 ‖ u16 d ‖ u16 k_frozen ‖ u64 seed ‖ f64 τ ‖ f64 shrinkage ‖ u64 m
‖ 32-byte sha256_reference ‖ u16 encoder_len ‖ encoder ‖ f64 × k·d centroids ‖ f64 × d·d precision
‖ 32-byte SHA-256 of everything before it
```

Everything is big-endian and fixed-width (§0.2). `PartitionArtefact::parse(bytes)` works like this:

1. **Hash first.** Recompute SHA-256 of the body and compare it with the last 32 bytes. Nothing in a
   corrupted file is trusted.
2. Read with a `Reader` whose every read is bounds-checked (`take`, `checked_add`). No indexing that
   could panic.
3. Validate: magic, version, `d` a positive multiple of 8 (the kernel needs it), `1 ≤ k ≤ 10,000`,
   no trailing bytes, precision and centroids finite, τ finite and ≥ 0.
4. Any failure → `IntegrityViolation` naming the check (DB-64).

**The fuzz bug (section 12):** `f64s(n)` used to reserve memory for `n` values *before* checking the
file had that many bytes. The hash is not a secret, so an attacker can craft a valid-hash file whose
header claims `k·d` in the billions. The fuzzer found an 88-byte file that asked for 5 GB. The fix
checks `remaining ≥ n · 8` first. The regression test is
`p1_partition_huge_header_is_refused_without_allocating`.

The Python side has its own encoder and decoder (`artefact.py`), and a test checks that the Rust parser
reads the Python builder's golden file field for field (L8, builder to importer).

---

## 8. Walkthrough: the index

This is the heart of Part 1: `crates/sever-index/src/`, mainly `index.rs` (900 lines).

### 8.1 The data structures

```rust
struct Group<E> {
    id: GroupId,               // frozen-NNNN, spawn-…, or holding
    kind: GroupKind,           // Frozen | Spawned | Holding
    centroid: Vec<f64>,        // fixed forever once created
    state: GroupState<E>,      // S (i64 × d), n, extension public + secret state
    slots: Vec<Slot<E>>,       // the members: scrambled ID, record ID, x̃, extension secret
    mirror_ids: Vec<RecordId>, // float32 search copy, row for row with `slots`
    mirror: Vec<f32>,          // x̂ as f32, d values per member (§12.6)
}

struct Index<E, S> {
    groups: Vec<Group<E>>,     // frozen in label order, then spawned in creation order
    holding: Group<E>,         // the holding area
    locator: HashMap<ScrambledId, (GroupId, usize)>,  // where each live record is
    big_n: u64,                // N: records in frozen + spawned groups (not holding)
    …config, d, τ, P, collection_id, extension, scrambler
}
```

- **Slots** are the source of truth: the exact `x̃` of each member.
- **The mirror** is a float32 copy for fast search. It is derived, kept in lockstep, and wiped on
  deletion.
- **The locator** finds a record in O(1) by its **scrambled ID**. Below the API, records are named
  only by `HMAC-SHA-512(k_scramble, collection_id ‖ record_id)` (§9.7, EP-2). Why? Later parts store
  and publish data (logs, certificates). Without the key, a scrambled ID reveals nothing about the
  record ID, not even whether two collections hold the same one.

### 8.2 Three kinds of group (§5.1)

| Kind | Created by | Has `S`, `n` | Searchable |
|---|---|---|---|
| **Frozen** (128) | the partition artefact | yes | yes |
| **Spawned** | a flush of the holding area | yes | yes |
| **Holding** (1) | always exists | **no** | **no** |

### 8.3 Routing: where does a new vector go? (§7, `route`)

A pure function of `(x̃, current state)`: no clock, no counter, no "latest group".

1. Dequantise to f64. Find the **nearest frozen centroid** (squared distance, sequential sum). On a
   tie, the lower label wins (strict `<`).
2. If spawning is disabled → that frozen group. (This is the "frozen-only" control arm of the
   experiments.)
3. If the Mahalanobis distance to that centroid is `≤ τ` → **in distribution** → that frozen group.
4. Otherwise it is **out of distribution** (drift). Try **spillover**: the nearest *spawned* group
   that still **has room**. Ties go to the smaller group-ID bytes.
5. No spawned group with room → **the holding area**.

**"Has room"** (§5.6): `2·k·n < 3·N`, in exact integers (u128, so no overflow). In plain words: a group
may hold up to 1.5× the average group size. This stops one spawned group from swallowing every
drifting vector.

With the nq data, about 88% of passages are out of distribution for the SciQ partition. That's by
design: the experiment is about drift. So most nq records end up in spawned groups.

### 8.4 Insert (`plan_insert`, §15.1 order of checks)

1. `quantise` (§4.1–4.2): wrong dimension, non-finite, not normalised → error.
2. `RecordId::new` (§3.2 rules 1–2) → `InvalidRecordId`.
3. Scramble the ID; **not already live** (rule 3), else `DuplicateRecord { same_commitment }`.
   `same_commitment` tells the client whether this is a harmless retry of the same vector.
4. The extension admits it (Part 3 will check the commitment and signature here).
5. Route.
6. Destination is the **holding area**: if this insert brings it to exactly `spawn_target` (200) → a
   **flush** in the same plan (below); otherwise just put it there.
7. Destination is a **group**: if `n + 1 > 1,000,000` → `GroupCapacityExceeded` (INV-4). Otherwise
   **join**: `S += x̃`, `n += 1`, extension `add`, `N += 1`, put the slot.

### 8.5 The flush: creating a spawned group (§7.4–7.5)

When the 200th out-of-distribution record arrives with no room anywhere, the 199 waiting records plus
the new one become **exactly one** new group, in the same plan:

- **Its ID** is `spawn-` + the first 16 hex characters of
  `SHA-256( for each founder ID, ascending by bytes: u16be(len) ‖ id )`. The ID depends only on *who*
  the founders are, not on when the flush happened.
- An ID collision with an existing group → refused (`IntegrityViolation`), before anything changes.
- `S` = sum of the founders, `n = 200`.
- **Centroid** `μ_i = (S_i / 2^24) / n`, computed **once** from the exact sum, then frozen forever.
- The change set says: create the group, put the new slot into holding, then `DrainInto` (move every
  holding slot, in order, to the new group), locator updates for all 200, `N += 200`, `k += 1`.

### 8.6 Delete (`plan_delete`, §5.4)

1. An ID that breaks §3.2 rules 1–2 can never be live → `AlreadyAbsent` (an outcome, not an error).
2. Scramble and look it up in the locator. Not found → `AlreadyAbsent`. **Deleting twice changes
   nothing** (idempotent, §5.4).
3. The extension checks the stored record is consistent (`check_removal`; Part 3 will verify its
   commitment here).
4. If it is in a group (not holding): `S −= x̃`, `n −= 1`, extension `remove`, `N −= 1`.
5. **Swap-with-last** (§14.4): move the group's last slot into the hole, update that record's
   locator entry, then truncate. This is **physical excision**: there is no "deleted" flag, and the
   record is gone from the slot array.
6. Remove the locator entry, record the departure, and output `Deleted { from: group }`.

`plan_delete_many` (the API's `delete_user`, §3.5) deletes a list as **one atomic change set**. Each
step sees the state the previous step left. Part 2 will make it all-or-nothing on disk.

### 8.7 The `Draft`: planning several steps without touching the index

`plan` takes `&self`, so it cannot change the index. But a `delete_user` of 50 records, or a flush, must
see the effects of earlier steps in the same plan. The `Draft` is a **pure overlay**:

- `lens`: the slot count of each touched group as the plan has left it;
- `moved`: which slot positions now hold which record (`SlotRef::Base` = still the index's original
  slot, `SlotRef::New` = a slot created in this plan);
- `locator`: overlay entries (`Some(position)` or `None` = deleted in this plan);
- `cs`: the `ChangeSet` being built.

Lookups check the overlay first, then fall back to the real index. At the end, `finish()` returns the
change set, and the index itself is unchanged until `apply`.

### 8.8 Apply: infallible installation

`apply(cs)` installs in a fixed order: create new groups → set each touched group's state to its
`after` → run slot operations (`Put` also appends the mirror row; `MoveLast` swaps slots and mirror
rows; `Truncate` **overwrites the removed mirror rows with zeros** and then shrinks; `DrainInto` moves
holding slots) → locator operations → set `N`.

"Infallible" doesn't mean "trusting". Every index access is checked and skipped if out of range, so
even a forged or malformed change set cannot panic. One forged-change-set test found a real bug: a
`DrainInto` to a missing group used to take the holding slots and then drop them. Now it checks the
destination exists first.

### 8.9 The canonical blob and five-field equivalence (§5.5)

How do you *compare* two groups exactly? The **canonical blob** is a byte string that fully describes
a group, generated on demand:

```text
magic "SEVERC" ‖ u16 version=1 ‖ u16 d ‖ u64 n ‖ i64 × d S ‖ extension region (empty in Part 1)
‖ u64 member_count ‖ per member, sorted by ID bytes: u16 id_len ‖ id ‖ i64 × d x̃
```

Members are sorted, so the blob **does not depend on insertion order** (gate P1-T3 checks this with
hundreds of random orders). The strict parser `parse_blob` rejects every malformed form: wrong magic or
version, `member_count ≠ n`, an empty ID, unsorted or duplicate IDs, trailing bytes, or truncation.

**Five-field equivalence** (`assert_state_equivalent`): two group snapshots are equivalent only if
**all five** match: (1) `S`, (2) `n`, (3) the extension's public state (`C_S` from Part 3), (4) the
blob, (5) the sorted member-ID list. Never fewer. Each field can be corrupted on its own in tests, to
prove each one is really compared.

**The survivors check** (Build §4.7 L6) is the central test of Part 1: after deletions, for each
touched group, build a *fresh* group from its surviving members alone (re-quantising each one from its
original float row), and require the two blobs to be identical. That is the claim, tested literally.

### 8.10 The invariants (§21, `check_invariants`)

| Invariant | Meaning |
|---|---|
| INV-4 | every group has `n ≤ 1,000,000` |
| INV-5 | `⌊1.5 · N / k⌋ ≤ 1,000,000` (the room rule can always be satisfied) |
| INV-6 | `n` equals the number of slots, and `S` equals the exact sum of the slots |
| INV-7 | the locator and the slots correspond exactly, one to one |
| INV-8 | `N` equals the sum of `n` over all groups |
| INV-9 | the mirror matches the slots row for row (IDs and length) |

Any failure is `IntegrityViolation`, and the engine stops serving. Tests corrupt each invariant one at
a time (through forged change sets) and check the right name comes back.

### 8.11 Where the sabotage switches live

Each SB item is a one-line deliberate bug behind a feature flag, so the broken build differs from the
real one in exactly one place (Build §2.6):

| SB | Bug | Where |
|---|---|---|
| SB-1 | flip one bit of a group sum on every deletion | `apply` |
| SB-2 | skip `n −= 1` on deletion | `Draft::subtract` |
| SB-3 | a retried deletion subtracts again | `Draft::delete` |
| SB-4 | forget the locator update after a slot move | `Draft::delete` |
| SB-5 | keep the deleted vector in the search mirror | `apply` (`Truncate`) |
| SB-6 | skip empty groups when filling the probe budget | `sever-search` |
| SB-7 | spill into the most recently created group with room | `route` |
| SB-8 | send drift to the holding area before trying spillover | `route` |
| SB-9 | let the SIMD kernel use fused multiply-add | `sever-search` kernel |
| SB-10 | average per-group covariance fits | Python builder |

`tests/sabotage/run.sh` builds each one and passes only if **at least one test goes red**. A test
suite that stays green with a bug inside proves nothing.

---

## 9. Walkthrough: search, the reference model, the demo

### 9.1 `sever-search`: IVF-flat search (§8)

`search(index, query, k)`:

1. Check the query (§4.1).
2. **Rank** every frozen and spawned group by `(distance to centroid, group-ID bytes)`.
3. **Probe** the closest `p = ⌈0.25 · k_groups⌉` groups. Empty groups count toward the budget (SB-6
   breaks this).
4. **Score** every member of every probed group with the pinned kernel.
5. Sort by `(score, record-ID bytes)` and return the best `k`.

Search is approximate (it only looks in a quarter of the groups), but **deletion is exact**: a
deleted record's mirror row is gone, so it can never be returned (gate P1-T5).

### 9.2 The kernel (`kernel.rs`, §8.2)

The score is the squared Euclidean distance in float32, in a **pinned** order: 8 lanes `L_0 … L_7`,
component `i` goes to lane `i mod 8`, each step `t = q_i − x_i; L_j += t·t` (multiply and add as
**separate** operations), then `((L0+L1)+(L2+L3)) + ((L4+L5)+(L6+L7))`.

Why so strict? Float addition depends on order. Pinning the order makes the scalar version, the AVX2
version and the Python model produce **identical bits**. The AVX2 version holds the 8 lanes in one
256-bit register, which is exactly the scalar layout, so it is fast *and* identical.

**FMA (fused multiply-add)** computes `a·b + c` with a single rounding. That is more accurate but
*different*, so it is forbidden (SB-9 turns it on to prove the tests notice). Gate P1-T4 compared
2.25 billion real query–vector pairs, scalar against AVX2: 0 mismatches.

This is the one place with `unsafe` (CPU intrinsics). Every block carries a `SAFETY:` note, the CPU
feature is detected at runtime, and the architecture test allows `unsafe` only here.

### 9.3 The reference model, C-18 (`python/sever_refmodel_core/model.py`)

A complete second implementation of Part 1 in Python, **written from the spec only, never from the
engine code** (CLAUDE.md §7). Its `RefIndex` has `insert`, `delete`, `delete_user`, `search`, `blob`,
`stats` and `check_invariants`. It uses Python `int` for sums (unbounded, so overflow can never hide
a bug) and the pinned float orders (`np.cumsum` for sequential sums, an 8-lane kernel).

Why write everything twice? If two independent implementations of the spec agree on 12 million values,
both are very likely right, and if they disagree, one of them, or the spec, has a bug. This is the
**oracle** (Overview DB-4).

### 9.4 Differential testing: traces (Build §2.4)

The two implementations never call each other. Instead:

```text
  Python model ──runs a stream──► trace.jsonl ──► sever-tracekit (Rust) ──► report: compared,
  (sever_testkit.traces)          one JSON line     replays every op         mismatches, …
                                  per operation     and compares every value
```

**The stream** (Overview §10.7–10.8): insert every corpus row in a seed-derived order; group the
passages into **cohorts** (one per article title, standing for "one user's data"); then delete
cohorts in cumulative **rungs** of 10, 25, 50, 75 and 90%, each cohort with one `delete_user`.

**The trace records**, after every operation: the placement or outcome or error, and the SHA-256 of
every touched group's blob. At each rung **checkpoint**: the stats, every group's blob hash, and the
top-100 results for every query (3,452 queries).

**The replay** (`sever-tracekit/src/lib.rs`) runs the same operations through the Rust index and
compares all of it. On top of that it runs two extra checks on every touched group and every query:

- the **survivors check** (P1-T1);
- the **kernel check** (P1-T4): every scored pair, scalar against dispatched AVX2.

For nq-100k, one seed is 146,221 operations, about 2.48 million compared values, about 85,500
survivors checks, and about 450 million kernel pairs.

### 9.5 `sever-p1`: the composition root and the demo

- `root.rs`: `new_index(artefact, cfg)` gets the key and collection ID from the OS (`OsRng`), wipes the
  key copy from its stack frame (`Zeroizing`), and builds `Index<NoExtension, HmacSha512Scrambler>`.
- `data.rs`: loads nq slices (IDs and cohorts from `artefacts/nq_1m.ids.jsonl`, whose header hash is
  checked against the manifest) or the synthetic fixture, and reads `.npy` vector files.
- `ghost.rs`: the two baselines. `SoftDeleteIvf` (tombstones; the centroid keeps everything ever
  inserted) and `RunningMeanIndex` (float32 running mean, subtract on delete). They get the **same
  group membership** as SEVER, so only the deletion mechanism differs.
- `demo.rs` and `bin/sever-demo.rs`: `sever-demo idea` (Build §4.9) builds an index from 10,000
  passages, picks a target cohort, deletes it, and reports the following:
  - every touched group's `n`, `S` hash and blob hash before and after;
  - that each equals its survivors-only rebuild;
  - that the 167 untouched groups are unchanged;
  - that a second delete is `AlreadyAbsent` and changes nothing;
  - the ghost of each baseline;
  - that no search returns a deleted record.
- `python/sever_demo/render.py` turns the JSON report into one HTML page.

The nq-10k, seed-42 run: 10,000 records, 128 frozen groups + 43 spawned, `N = 9,821`, 179 in holding,
87.8% out of distribution. The target cohort "Culture of Australia" had 4 records in 4 groups. Of the
3,452 queries, 17 returned one of those records before the deletion and 0 after.

One command does it all, from a clean clone: `scripts/p1-demo.sh` (it builds the missing artefacts
first).

---

## 10. How we proved it: the testing system

### 10.1 The test levels (Build §2.1) and where ours live

| Level | What it means | In Part 1 |
|---|---|---|
| L1 Unit | one function | `#[test]`s in every crate; `pytest` files in each package |
| L2 Property | holds for all generated inputs | `proptest` (Rust), `hypothesis` (Python): round trips, order independence |
| L3 Spec conformance | every MUST has a test | `#[spec("SR-…")]` on tests + `spec_trace`; 70 / 70 (P1-T9) |
| L4 Differential | engine = model, byte for byte | traces: nq-10k, nq-100k (5 seeds each), 1,000 synthetic streams |
| L5 Model-based stateful | random operation *sequences* agree | `python/sever_testkit/tests/test_stateful.py` (Hypothesis state machine) |
| L6 Metamorphic | a relation between two runs holds | order independence, insert-then-delete = identity, survivors check |
| L7 Contract | every EP implementation passes its suite | `contract.rs` in `sever-types` and `sever-index` |
| L8 Integration | crates together | Rust parser reads the Python builder's file; index + search |
| L9 End-to-end | black-box scenarios | `crates/sever-p1/tests/e2e_idea.rs`, E2E-1.1 … 1.7 |
| L10 Crash | — | Part 2 onward |
| L11 Fuzz | parsers never crash | `fuzz/`: `artefact_parse`, `blob_parse` |
| L12 Mutation + sabotage | tests detect bugs | `cargo-mutants`; `tests/sabotage/run.sh` |
| L13 Architecture | structure rules | `tests/architecture/test_architecture.py` |
| L14 Benchmark | never a gate | — |

### 10.2 Traceability (`#[spec]`, `spec_trace`, P1-T9)

Every MUST in the spec has an ID in `spec/requirements.yaml` (70 belong to Part 1). Every test names
the IDs it checks: `#[spec("SR-4.1-3")]` in Rust (the `sever-spec` crate; the attribute changes
nothing, but a malformed ID won't compile) and `@pytest.mark.spec("SR-4.1-3")` in Python.
`python -m sever_testkit.spec_trace check --complete` fails if any Part 1 ID has no test, and it writes
`docs/TRACE_PART_1.md`.

### 10.3 Fuzzing (L11, P1-T12)

`cargo-fuzz` throws millions of mutated byte strings at the two parsers that read untrusted bytes. The
`artefact_parse` target also re-hashes the mutated input, so the fuzzer can get past the SHA-256 check
and test the field parsing. `blob_parse` checks that an accepted blob obeys the §5.5
rules and, when its members are valid records, re-encodes to exactly the same bytes. The gate needs 10^8 runs per parser with 0 crashes. The first run found the allocation
bug in section 12, and the final run passed.

### 10.4 Mutation testing (L12, P1-T11)

`cargo-mutants` makes thousands of small changes to the code, one at a time (`<` → `<=`, `+` → `-`,
"return `true`"), and runs the tests on each. If the tests still pass, the mutant **survived**: either
the tests are missing something, or the change makes no difference. The gate needs ≥ 85% caught and
**every survivor explained**. Result: 325 of 347 caught (93.7%).

The triage (`docs/MUTANTS_P1.md`) found three real test gaps, and we fixed them with new tests:

- the `k` counter in a flush's change set was never checked;
- `QVec::dim` had no test at all;
- INV-5 was never checked on an index large enough to matter.

The remaining 22 survivors are each explained:

- **sabotage-only** code (behind a feature flag that is off);
- **equivalent** changes (e.g. `<` → `<=` on group IDs that can never be equal);
- **unreachable** at Part 1 sizes (e.g. INV-5 needs more than 2.6 million records);
- **host-equivalent** (AVX2 detection forced to `true` on a machine that has AVX2).

One is a note for Part 2: two inserts into one group in one change set.

### 10.5 Coverage (P1-T10)

Lines and branches executed by the tests: Rust 95.9% of lines and 87.0% of branches (targets 90% and
85%), Python 98.8% (target 90%). Measured with `cargo llvm-cov` (nightly, for branches) and
`coverage.py`.

### 10.6 Architecture tests (L13)

`tests/architecture/test_architecture.py` reads `cargo metadata` and the source:

- the core crates have no file, clock or random-number dependency or call;
- dependencies point only inward and to earlier parts;
- `unsafe` appears only where listed;
- no Rust code fits a partition;
- the Python packages respect their layering (`sever_testkit.seeds` is a standard-library-only leaf).

### 10.7 Determinism

No flaky tests and no retries. Python always runs with `PYTHONHASHSEED=0`. Every random input comes
from a recorded seed (the five overview seeds `[42, 123, 777, 2024, 9999]`, with sub-seeds derived as
`SHA-256(u64be(seed) ‖ label)`). A failing random case is saved as a permanent regression file (the
`proptest-regressions/` files).

---

## 11. The gates and their results

A **gate** must pass, and missing one is a bug. A **measure** is recorded as found and never rerun
until it looks good (Build §2.5). All of these are in `docs/RUN_LEDGER.jsonl`, with full results in
`results/`.

| ID | What | Result |
|---|---|---|
| P1-T1 | 0 exactness violations (survivors check) | **PASS**: 427,455 checks on nq-100k, 43,562 on nq-10k, 275,114 on 1,000 synthetic streams; 0 failures |
| P1-T2 | engine = model, nq-10k and nq-100k, 5 seeds | **PASS**: 10.6 M + 12.4 M values, 0 mismatches |
| P1-T3 | identical blobs across insertion orders | **PASS**: property tests, hundreds of orders per set |
| P1-T4 | scalar = AVX2 kernel, bit for bit | **PASS**: 10^7 random pairs; 508 M (nq-10k) + 2.25 B (nq-100k) real pairs, 0 mismatches |
| P1-T5 | no deleted record ever returned | **PASS**: 0 on both slices, all seeds |
| P1-T6 | builder = independent oracle | **PASS**: largest differences 2e-17 (shrinkage) and 1.4e-14 (τ), 5 seeds |
| P1-T7 | quantisation cost: Recall@10, nq-100k (measure, target ≥ 0.999) | **1.000** |
| P1-T8 | every sabotage SB-1 … SB-10 turns a test red | **PASS**: all 10 |
| P1-T9 | traceability | **PASS**: 70 / 70 |
| P1-T10 | coverage | **PASS**: 95.9% / 87.0% / 98.8% |
| P1-T11 | mutation score ≥ 85%, survivors triaged | **PASS**: 93.7%, 22 triaged |
| P1-T12 | fuzzing, 10^8 runs per parser | **PASS** (the first run found a real bug, fixed) |
| P1-T13 | contract suites + proof spikes | **PASS** |
| P1-T14 | the ghost (measure) | SEVER 0; float mean 1.9e-8; tombstone IVF 5.0e-3 |

Plus the definition of done (Build §2.9): the demo runs from a **clean clone** with one command. We
checked this on 6 Oct, and the report was identical to the working copy's apart from timing.

---

## 12. Bugs, failures and lessons

**Real bugs the tests found in the engine:**

1. **Artefact parser allocation** (fuzzing): it trusted the header's size before checking the file
   length. Lesson: the hash proves the file wasn't damaged by accident, not that it is honest. Parse
   untrusted input as if it were hostile.
2. **`apply` losing records** (forged change sets): a `DrainInto` to a missing group emptied the
   holding area into nowhere. Lesson: "cannot fail" must also mean "cannot lose data on bad input".

**Process failures, and what changed:**

| What happened | Fix |
|---|---|
| proptest 1.11 pulled in a second major version of `rand` and `getrandom` (spec §20.3 forbids duplicate crypto crates) | pinned `proptest ~1.6` without default features; dropped the Rust Parquet reader |
| nq-100k, fuzz and mutants together exceeded RAM; the out-of-memory killer struck | one heavy job at a time; later gave WSL 10 GB |
| the laptop slept and WSL restarted, killing long runs | the ledger records every run as "started" first, so aborts are visible, never hidden |
| `cargo-mutants` copied the 4 GB `datasets/` into the small `/tmp` | run it in a git worktree (tracked files only) with its own temp directory |
| `cargo-mutants` by default only ran the mutated crate's tests | `--test-package` for every crate whose tests apply |
| the full-checks gate failed: `run.sh` lacked its executable bit (committed from Windows) | `chmod +x`; the FAIL stays in the ledger, the fixed run passed |
| a sabotage build saved its failing proptest case into a frozen crate's files | the sabotage runner now restores those files on exit |
| a wait loop using `pgrep -f` matched its own command line | look up exact process IDs instead |

**Rules we kept even when it cost time:**

- **Never rerun until it passes.** Each failure was understood and fixed, and the FAIL entry stays in
  the ledger next to the later PASS.
- **Never move a target after seeing a result.**
- **Gates run on clean commits** (`git_dirty: false`), so every number points at exact code.

---

## 13. Run ledger, CI, freeze, git

**The run ledger** (`docs/RUN_LEDGER.jsonl`) is append-only and written only by the gate runners
(`python -m sever_testkit.gates …`), never by hand. Each run writes a "started" line first, then a
final line. Each line records:

- the time and the command;
- the commit and whether the tree was dirty (and which paths);
- the dataset manifest hash and the platform (CPU flags, swap, WSL);
- `PYTHONHASHSEED`;
- the outcome, and the result file with its SHA-256.

After the history rewrite, older hashes are mapped to new ones in `docs/COMMIT_MAP.txt`. The code trees
are byte-identical.

**The gate runners** (`python/sever_testkit/gates.py`): `p1-differential`, `p1-quant-recall`,
`p1-synthetic`, `p1-spikes`, `p1-fuzz`, `p1-coverage`, `p1-mutants`, `p1-checks`.

**CI** (`scripts/ci.sh`, Build §2.8):

- `fast`, on every push (also `.github/workflows/ci.yml`): format, lint, sabotage builds lint, tests,
  ruff, mypy, Python tests, `spec-trace`, the crypto-duplicate check and the **freeze guard**.
- `full-checks`: everything in `fast`, plus the slow and ignored tests, the sabotage register, a build
  on minimum Rust 1.85, `cargo deny` (licences, advisories) and `cargo doc` with warnings as errors.

**The freeze** (`scripts/freeze.sh 1`) hashes the 81 files Part 1 owns into `freeze/PART-1.sha256`.
These are the 8 crates, the 4 Python packages, the fuzz targets and the golden `p1_*` files. The freeze
guard in CI fails on any change to them, and we checked that it goes red when a frozen file is edited.
Note that `sever_testkit` is frozen too, so Part 2's gate runners go in new modules.

**Git:** trunk-based on `main`, conventional commit messages (`feat:`, `fix:`, `test:`, `docs:`,
`chore:`), tag `part-1-frozen`, backed up to your private GitHub remote.

---

## 14. Glossary

| Term | Meaning |
|---|---|
| **Embedding / vector** | the list of 384 numbers a model computes for a passage |
| **Normalised** | length (norm) 1; checked within 8 float32 ULPs, never fixed by the engine |
| **ULP** | "unit in the last place": the gap between neighbouring floats |
| **Q24 / quantise** | `x̃ = round_half_to_even(x · 2^24)`, an integer per component |
| **Dequantise** | `x̂ = x̃ / 2^24` |
| **`S`, `n`** | a group's exact integer sum and member count |
| **`N`, `k`** | records in frozen + spawned groups; number of frozen + spawned groups |
| **Frozen / spawned / holding** | the three kinds of group (§5.1) |
| **Partition / artefact** | the 128 frozen centroids, precision matrix and τ, in `partition.svp` |
| **Mahalanobis distance** | distance scaled by how spread the data is in each direction |
| **τ (tau)** | the drift threshold: the 99th percentile of reference distances |
| **Out of distribution (drift)** | farther than τ from the nearest frozen centroid |
| **Spillover** | putting a drifting vector into the nearest spawned group with room |
| **Flush** | turning 200 waiting records into one new spawned group |
| **Canonical blob** | the exact byte description of a group, independent of insertion order |
| **Five-field equivalence** | `S`, `n`, extension public state, blob, member IDs: all equal |
| **Survivors check** | a group after deletions = a fresh group of its survivors |
| **Ghost** | what a deleted record leaves behind in a baseline's summary |
| **Scrambled ID** | `HMAC-SHA-512(key, collection_id ‖ record_id)`, the only name below the API |
| **Locator** | map from scrambled ID to `(group, slot)` |
| **Mirror** | float32 copy of a group's vectors, used by search |
| **Plan / apply / ChangeSet** | pure planning, infallible installation, the description in between |
| **Extension point (EP)** | a declared door later parts plug into without editing frozen code |
| **Contract suite** | checks every implementation of an EP must pass |
| **Proof spike** | a throwaway implementation that proves an EP really fits, then deleted |
| **Composition root** | the one place that wires the parts and supplies OS entropy |
| **Reference model / oracle** | the independent Python implementation the engine is compared against |
| **Trace / replay** | the model's recorded run, replayed and compared by Rust |
| **Gate / measure** | must-pass check / number recorded as found |
| **Sabotage (SB)** | a deliberate one-place bug that a test must catch |
| **Mutant** | an automatic small code change used to test the tests |
| **Fuzzing** | feeding random bytes to parsers to find crashes |
| **IVF** | inverted file index: search only the nearest groups |
| **AVX2 / FMA** | x86 vector instructions / fused multiply-add (forbidden here) |
| **Freeze / freeze guard** | hashing a part's files / CI failing if they change |
| **Run ledger** | append-only record of every gate run |

---

## 15. Check yourself

Try to answer these from memory, then check against the code (CLAUDE.md coach style).

1. Why does `(a + b) − b = a` hold for `S` but not for a float32 running mean? What bound makes the
   `i64` sum safe, and where is it checked?
2. What happens if a client sends a vector with norm 1.001? Where exactly, and why doesn't the engine
   just normalise it?
3. Why are the frozen centroids never updated? What would break if they were?
4. Walk an out-of-distribution insert through `route` when one spawned group exists and has room. Now
   when it is full. Now when 199 records are already in holding.
5. Why is the spawned group's ID computed from the sorted founder IDs, rather than from a counter or
   the time?
6. In a delete, why "swap with last, then truncate" instead of leaving a hole with a flag?
7. `plan` takes `&self`. How does a `delete_user` of 10 records in the same group see its own earlier
   steps?
8. Why must `apply` be infallible? What does Part 2 need from that?
9. Why are blob members sorted by ID bytes? Which gate would fail if they weren't?
10. Why must the scalar and AVX2 kernels use separate multiply and add? Which sabotage item tests it?
11. How can a Python model and a Rust engine produce *identical* float bits? Name two places where the
    order is pinned.
12. Of the 22 surviving mutants, pick one "unreachable" and one "equivalent" one, and explain why each
    is harmless.
13. What does the freeze guard protect, and how would you fix a real bug in a frozen file (F-6)?
