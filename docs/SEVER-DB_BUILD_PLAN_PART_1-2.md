# SEVER-DB — Build Plan: Part 1 and Part 2

| | |
|---|---|
| **Document** | SEVER-DB build plan, Parts 1–2 |
| **Companions** | `SEVER-DB_PROJECT_OVERVIEW.md` (why, decisions, evaluation) · `SEVER-DB_SPECIFICATION.md` (normative behaviour and bytes) · `SEVER-DB_BUILD_PLAN_PART_3-4.md` (Parts 3–4) |
| **Status** | Proposed for review |
| **Covers** | The four-part structure; the freeze rule; engineering and testing standards for every part; the extension points; Part 1 (The Idea) and Part 2 (The Database) |

The specification remains the single source of truth for **what** the system does, down to the byte.
This plan decides **how** it is built: in which order, in which modules, how each piece is tested, and
what must be true before a piece is declared finished and frozen.

---

## Contents

0. [The four parts](#0-the-four-parts)
1. [Engineering standards (all parts)](#1-engineering-standards-all-parts)
2. [Testing standards (all parts)](#2-testing-standards-all-parts)
3. [Architecture and extension points](#3-architecture-and-extension-points)
4. [Part 1 — The Idea](#4-part-1--the-idea)
5. [Part 2 — The Database](#5-part-2--the-database)
6. [Appendix — templates](#6-appendix--templates)

---

## 0. The four parts

### 0.1 One claim per part

Each part adds **exactly one** new claim, and each part is built on the frozen parts before it.

| Part | Name | The one claim it adds | Built on |
|---|---|---|---|
| **1** | **The Idea** | Deleting a vector returns its group, bit for bit, to the state it would have had if the vector had never arrived. Averages and soft deletion cannot do this | — |
| **2** | **The Database** | That exactness survives a crash at any point, no acknowledged operation is lost, and a multi-group deletion is all-or-nothing | Part 1 |
| **3** | **The Receipt** | Every deletion yields a certificate that anyone can verify offline, with no database access | Parts 1–2 |
| **4** | **The Erasure** | After a deletion is acknowledged, nothing deleted can be recovered from raw storage; the complete system is evaluated against every pre-registered target | Parts 1–3 |

**Why this order.** Each part depends only on what came before it:

- The arithmetic (Part 1) is the idea itself, and it is the thing every later part protects.
- Durability (Part 2) is needed before receipts, because a certificate must commit atomically with
  the deletion it describes.
- Receipts (Part 3) come before erasure because encryption is the *outermost* wrapper: Part 4 encrypts
  whatever bytes Parts 1–3 store, so it must come last to avoid changing their formats.

This swaps the specification's phases P4 (keys) and P6 (certificates). The swap is recorded as a
decision (§3.5, DB-44).

### 0.2 Mapping to the specification and the overview

| Part | Spec components | Spec sections | Overview phases |
|---|---|---|---|
| 1 | C-7 (quantiser, ID scrambling only), C-8, C-9, C-10, C-15, C-18 (core model), C-19 (demo and trace harness) | §2–§8, §9.7 | P0, P1, index part of P5, P7 |
| 2 | C-1, C-2, C-3, C-4, C-5, C-12, C-13 (basic SDK), C-18 (durable oracle), C-19 (crash kit) | §12, §14 (except §14.5, §14.7), §15, §16.1, §17 | P3, storage part of P5, P8 |
| 3 | C-7 (rest), C-11, C-13 (backend crypto helpers), C-16, C-17, C-18 (certificate model) | §9, §10, §11, §16.2–16.3 | P2, P6 |
| 4 | C-6, C-7 (AEAD), C-13 (final SDK), C-19 (full), forensic scanner | §12.8–12.9, §13, §14.5, §14.7, §15.3–15.4, §15.8–15.9 | P4, P9 |

The optional gRPC server (C-14) is outside all four parts. It adds no claim (overview DB-38).

### 0.3 The freeze rule

Your requirement is that a finished part is never touched again. These rules make that enforceable
rather than a promise.

| Rule | Statement |
|---|---|
| **F-1 Freeze** | When a part passes its exit gate, every file it owns (Rust crates, Python packages, test suites, trace files, golden vectors, its section of this plan) is hashed into `freeze/PART-N.sha256`, and the commit is tagged `part-N-frozen`. |
| **F-2 Guard** | CI recomputes every freeze manifest on every commit. Any change to a frozen file fails the build. |
| **F-3 Extend, never edit** | A later part adds new crates and packages. It changes behaviour only through the extension points (§3.3) that an earlier part declared. |
| **F-4 Direction** | Code of part N may depend on parts ≤ N, never on a later part. An architecture test (§2.1, level L13) enforces this on the crate and package graph. |
| **F-5 Regression by reuse** | Every later part re-runs every earlier part's full test suite, unchanged, against the new build. A frozen suite is also a permanent regression suite. |
| **F-6 Errata, the only exception** | See below. |

**Errata (F-6).** No engineer can honestly promise that code will never need a fix: some bugs are
found late. So a defect in a frozen part is fixed only like this:

1. Record an entry `E-N` in `ERRATA.md`: the symptom, the root cause, and the part affected.
2. Commit a failing regression test **first**.
3. Make the smallest fix that turns it green. No features, no API changes, no format changes.
4. Re-run the frozen part's full exit gate, and the exit gate of every later part.
5. Write a new freeze manifest and tag it `part-N-frozen-eK`.

**Features never enter a frozen part.** If a later part needs something a frozen part cannot express
through its extension points, that is a design failure, and it is recorded as an erratum with a new
decision entry. The proof spikes (§3.4) exist to make that unlikely.

---

## 1. Engineering standards (all parts)

### 1.1 Modularity

- **One responsibility per crate or package.** The crate map is §3.2.
- **Functional core, imperative shell.** The index (Part 1) is pure and deterministic: no files, no
  clock, no randomness except the ID-scrambling key it is handed. I/O, time and entropy enter only
  through injected interfaces (`Vfs`, `Clock`, OS entropy) in the outer parts.
- **Plan, then apply.** Every mutation is computed by a pure `plan` step that returns a `ChangeSet`,
  then installed by an infallible `apply`. All validation happens in `plan`. This single rule is what
  lets Part 2 log a change before applying it, Part 3 build a certificate from it, and Part 4 rotate
  keys for it, all without editing Part 1 (§3.3, EP-3).
- **Minimal public APIs.** Everything is private unless another crate needs it. Test-only hooks live
  behind a `test-hooks` feature that is never enabled in measured builds.
- **No global mutable state.** The one exception is the secret-memory provider (EP-4), installed
  exactly once by a composition root at startup.
- **Composition roots.** Each part ships one small crate that wires the generic engine to that part's
  concrete extensions (`sever-p1`, `sever-p2`, `sever-p3`, and finally `sever-db`). Earlier roots
  remain buildable and tested forever; this is how F-5 works in practice.

### 1.2 Code quality

| Area | Rust | Python |
|---|---|---|
| Format | `rustfmt` | `ruff format` |
| Lint | `clippy -D warnings`, plus `clippy::unwrap_used`, `expect_used`, `panic`, `indexing_slicing` denied in library code | `ruff` with a strict rule set |
| Types | — | `mypy --strict` |
| Unsafe | `#![forbid(unsafe_code)]` everywhere except a listed set (SIMD kernels in Part 1; `mlock` in Part 4), each block with a `// SAFETY:` comment and run under Miri | — |
| Docs | `#![deny(missing_docs)]` on public items; doctests compile and run | Docstrings on public functions |
| Errors | Typed errors (`thiserror`). No error text contains a record ID, vector value, key, `r_t` or passage text (spec §17) | Typed exceptions mirroring the Rust errors |
| Dependencies | Pinned per spec §20; `cargo deny` for licences and advisories | Hash-pinned lockfile |

### 1.3 Workflow

- **Trunk-based development.** Short-lived branches; every change goes through a pull request, even
  when working alone, with the checklist in §6.1.
- **Conventional commit messages** (`feat:`, `fix:`, `test:`, `docs:`, `erratum:`).
- **Decisions.** Any design choice that is not already in the specification becomes a new `DB-N` entry
  in the overview, in the same commit as the code.
- **Specification first.** If writing code or a test reveals that the specification is ambiguous,
  stop, amend the specification and record a decision, then continue.
- **Run ledger.** Every exit-gate run and every experiment writes a ledger entry automatically
  (overview §13.3). A run that cannot write its entry does not start.

---

## 2. Testing standards (all parts)

### 2.1 Test levels

Every part uses every level that applies to it. Each part's test plan says what goes into each level.

| Level | Purpose | Tools | Lives in |
|---|---|---|---|
| **L1 Unit** | One function or module, in isolation | `cargo test`, `pytest` | Inside the crate or package |
| **L2 Property** | An invariant holds for all generated inputs | `proptest`, `hypothesis` | Inside the crate or package |
| **L3 Spec conformance** | Every normative requirement has a test; every spec table and example is a table-driven test (§2.2) | Custom `spec-trace` tool | `tests/spec/` |
| **L4 Differential** | Engine output equals the reference model's output, byte for byte | Trace files (§2.4) | `tests/differential/` |
| **L5 Model-based stateful** | Random *sequences* of operations keep engine and model in agreement | `proptest-state-machine`, `hypothesis` `RuleBasedStateMachine` | `tests/stateful/` |
| **L6 Metamorphic** | A relation between two runs holds (order independence, insert-then-delete is identity, and so on) | `proptest` | `tests/metamorphic/` |
| **L7 Contract** | Every implementation of an extension point passes that point's shared suite | Suites exported by the declaring crate (§3.4) | Declaring crate, run by every implementer |
| **L8 Integration** | Crates of one part, and each part with the parts below it, work together | `cargo test` workspace tests | `tests/integration/` |
| **L9 End-to-end** | Black-box scenarios through the CLI or SDK on real data, written as Given / When / Then | `pytest` driving the CLI and SDK | `tests/e2e/` |
| **L10 Fault and crash** | Behaviour under crashes, torn writes and failed `fsync` (Part 2 onward) | `SimVfs` crash campaigns | `tests/crash/` |
| **L11 Fuzz** | Parsers never crash or accept malformed input | `cargo-fuzz` | `fuzz/` |
| **L12 Mutation and sabotage** | The tests actually detect bugs | `cargo-mutants`, `mutmut`, the sabotage register (§2.6) | `tests/sabotage/` |
| **L13 Architecture** | Dependency direction, freeze manifests, verifier independence, "no I/O in the core" | `cargo metadata` checks, import-linter | `tests/architecture/` |
| **L14 Benchmark** | Cost measurement only; **never a gate** | `criterion`, `pytest-benchmark` | `benches/` |

**No flaky tests and no retries.** Concurrency is tested by deterministic scheduling (`loom` for the
lock protocol, and a deterministic scheduler for engine-level interleavings), and crashes by `SimVfs`.
Nothing relies on racing threads or randomly killed processes. Every random input comes from a
recorded seed, and a failing case is saved as a permanent regression file.

### 2.2 Specification-based testing

The specification is written as normative statements with **MUST**. Spec-based testing makes every one
of them a test, in five ways.

**1. Requirement IDs and a traceability matrix.**

- Every normative statement in the specification gets a stable ID, `SR-<section>-<n>`: every MUST
  or MUST NOT, and every numbered step, formula, byte layout, parser rejection rule, row of a
  normative table and definition (spec §0.1, overview DB-58). For example, `SR-4.1-3` is
  "`|norm − 1| ≤ 8·2^−23` MUST hold".
- The IDs, the requirement text and the part that owns each one are kept in `spec/requirements.yaml`.
  A script extracts candidates from the specification, so a new MUST cannot go unnoticed.
- Every test names the requirements it checks: `#[spec("SR-4.1-3")]` in Rust (a small attribute
  macro), `@pytest.mark.spec("SR-4.1-3")` in Python.
- `spec-trace` builds `docs/TRACE_PART_N.md` and **fails CI** if any requirement owned by a finished
  part has no test, or if a test names an unknown ID.

**2. Black-box test design from the specification.** Each part applies these techniques to the
sections it owns:

| Technique | Example from Part 1 |
|---|---|
| **Equivalence partitioning** | Record IDs (§3.2): valid (`doc0`, UUID), counter-shaped (`1`, `007`, `-3`, `+3`), empty, 257 bytes, invalid UTF-8, duplicate of a live ID |
| **Boundary values** | Norm exactly at ±8 ULPs and one ULP beyond; `|x̃| = 2^24 + 16`; holding area at 199, 200 and 201; the room test at `2kn = 3N − 1`, `3N` and `3N + 1`; group size at `10^6 − 1`, `10^6`, `10^6 + 1`; probe count `⌈0.25k⌉` for `k` mod 4 = 0, 1, 2, 3 |
| **Decision tables** | Routing (§7.3): in-distribution / out-of-distribution × spawned group with room exists / does not; deletion: present / absent × group / holding area |
| **State transitions** | The record lifecycle (§2.3) and the group lifecycle (created → non-empty → empty → non-empty) |

**3. Table-driven conformance.** Every table and worked example in the specification becomes data for
a test:

- the record-ID examples (§3.2) and the error table (§17);
- the byte layouts (§5.5, §6.3, §14), checked field by field at their offsets;
- every derived size in Appendix A, asserted against the code's constants, so that a code change that
  silently alters a size fails.

**4. An independent oracle written from the specification.** The Python reference model (C-18) is
written from the specification only, never from engine code. Its review checklist maps each model
function to the specification paragraph it implements.

**5. Golden vectors** (spec Appendix B) are generated once, committed, and checked by independent code
in each language.

### 2.3 The record lifecycle (state-transition model)

```
             insert (in-dist, or OOD with room)
   ABSENT ─────────────────────────────────────► IN_GROUP ──delete──► ABSENT
     │                                               ▲
     │ insert (OOD, no room)                         │ flush (200th holding insert)
     ▼                                               │
   HOLDING ──────────────────────────────────────────┘
     │
     └──delete──► ABSENT            (deleting an ABSENT record → AlreadyAbsent, no change)
```

Every arrow, and every non-arrow (for example "delete an absent record" and "search for a holding
record"), is at least one L1 test and one transition in the L5 state machine.

### 2.4 Differential testing through trace files

The Rust engine and the Python model never call each other. Instead:

1. The model (or the test harness) writes a **trace**: a JSON Lines file with one operation per line,
   and after each operation the expected result, together with the SHA-256 of the canonical blob of
   every touched group. At checkpoints the trace also records the full blob bytes and the top-10 and
   top-100 search results.
2. A Rust replayer runs the same operations and compares every value.
3. Traces are hashed in `tests/traces/MANIFEST.sha256` and, once their part is frozen, never change.

This keeps the two implementations independent, and it lets every later part replay Part 1's traces
through its own engine (F-5) without editing them.

### 2.5 Gates and measurements

Two kinds of target, never mixed:

| Kind | Meaning | If missed |
|---|---|---|
| **Gate** | A correctness or quality condition. A miss means a bug | The part cannot freeze. The failing run stays in the ledger; the bug is fixed and the full campaign re-run as a new entry |
| **Measure** | A pre-registered research measurement (for example overview T-5, T-6) or a cost | Reported exactly as found. **Never** a reason to change code or to rerun until it passes |

CI fails on a broken test or a missed gate, and never on a measurement.

### 2.6 Sabotage register (all parts)

A sabotage is a deliberately broken build. Each one MUST turn at least one test red, and the whole
register is re-run before any part freezes and before any published number. Each part owns the items
that concern its code. This register contains every item of overview §9.2 plus the phase-level
must-fail tests of overview §8.

| ID | Sabotage | Part |
|---|---|---|
| SB-1 | Flip one bit of a group sum | 1 |
| SB-2 | Skip the count decrement on deletion | 1 |
| SB-3 | Subtract twice on a retried deletion | 1 |
| SB-4 | Forget the locator update after a slot move | 1 |
| SB-5 | Keep a deleted vector in the search mirror | 1 |
| SB-6 | Skip empty groups when filling the probe budget | 1 |
| SB-7 | Route to "the most recently created group with room" | 1 |
| SB-8 | Put a vector in the holding area before checking spillover | 1 |
| SB-9 | Enable FMA contraction in the SIMD kernel | 1 |
| SB-10 | Average per-group Ledoit–Wolf fits instead of one pooled fit | 1 |
| SB-11 | Accept a WAL record with a bad CRC | 2 |
| SB-12 | Skip the directory `fsync` after a rename | 2 |
| SB-13 | Replay an uncommitted transaction | 2 |
| SB-14 | Retry a failed `fsync` | 2 |
| SB-15 | Apply a change to memory before its `COMMIT` is durable | 2 |
| SB-16 | Swap the order of the challenge preimage | 3 |
| SB-17 | Omit the deletion context from the challenge | 3 |
| SB-18 | Reuse a proof nonce | 3 |
| SB-19 | Accept a non-canonical point or scalar | 3 |
| SB-20 | Accept three of five cosignatures | 3 |
| SB-21 | Issue a certificate for a rolled-back deletion | 3 |
| SB-22 | Set `group_emptied_by_this_deletion` wrongly | 3 |
| SB-23 | Reduce the challenge from 32 bytes instead of 64 | 3 |
| SB-24 | Skip group-key rotation | 4 |
| SB-25 | Skip bucket-key rotation | 4 |
| SB-26 | Skip holding-area rotation on flush | 4 |
| SB-27 | Erase the old key before commit | 4 |
| SB-28 | Write a plaintext vector into the WAL | 4 |
| SB-29 | Write an unwrapped key to disk | 4 |
| SB-30 | Reuse an AEAD nonce | 4 |

Sabotages are built from the same source with a `sabotage-SB-N` feature flag, so the broken build
differs from the real one in exactly one place.

### 2.7 Test data

| Kind | What | Used for |
|---|---|---|
| **Synthetic** | Seeded, normalised vectors with controllable clusters; a "reference" distribution and a shifted "live" one, so drift and spawning can be forced | Fast L1, L2, L5, L6 tests with no downloads |
| **Small fixtures** | The same code run at a small dimension (for example `d = 16`, 4 frozen groups, spawn size 8) | Fast state-machine tests that reach flushes and empty groups quickly |
| **Full-size conformance** | `d = 384`, 128 frozen groups, spawn size 200 | L3, golden vectors, anything whose bytes the specification fixes |
| **Real slices** | `nq-10k` (a development slice), `nq-100k`, `nq-1m` from overview §10 | L4, L9, the demos and the evaluation |

The engine therefore handles any `d` that is a multiple of 8 and any number of frozen groups. The v1
configuration fixes `d = 384` and 128 groups (DB-49, §3.5).

Seeds are always the five overview seeds `[42, 123, 777, 2024, 9999]`, with sub-seeds derived as in
overview §10.6.

### 2.8 CI tiers

| Tier | Runs on | Contents |
|---|---|---|
| **Fast** | Every push | Format, lint, types, L1, bounded L2, L3 and `spec-trace`, golden vectors, L7, L13 including the freeze guard |
| **Extended** | Every merge to the main branch | L4 at `nq-10k` on five seeds, larger L5 and L6 runs, mutation testing of changed crates, a bounded fuzz budget, a small crash campaign (Part 2 onward) |
| **Full** | Before an exit gate, and before any published number | Every gate of the part, and every earlier part's full suite (F-5) |

### 2.9 Definition of done (every part)

A part is done, and may freeze, only when all of these hold:

- [ ] Every goal of the part is met, and every gate target passes in a **Full** CI run recorded in the
      run ledger.
- [ ] Every measurement target has been measured and recorded as found.
- [ ] The traceability matrix covers 100 % of the part's requirements.
- [ ] Every sabotage the part owns turns a test red.
- [ ] Every extension point the part declares has a contract suite, and a deliberately wrong
      implementation fails that suite.
- [ ] The proof spikes for the extension points pass (§3.4) and have been deleted.
- [ ] Every earlier part's full suite passes unchanged against this part's build (F-5).
- [ ] The demo runs from a clean clone with one documented command.
- [ ] The part's README, API docs and this plan's section agree with the code.
- [ ] Every open specification question found during the part is resolved by a decision entry.
- [ ] The freeze manifest is written, and the tag is created.

---

## 3. Architecture and extension points

### 3.1 Layering

```
 Part 4   sever-keys  sever-seal  sever-erasure  sever-platform   sever-scan     sever-db (final root)
             │           │  (EP-6)      │  (EP-7)       │ (EP-4)
 Part 3   sever-crypto  sever-commit (EP-1)  sever-log (EP-7)  sever-cert       verifier/  audit/
             │               │                   │
 Part 2   sever-vfs (EP-5)  sever-format  sever-wal  sever-appendstore (EP-8)  sever-checkpoint
                      sever-txn (declares EP-6, EP-7, EP-9)      sever-engine
             │
 Part 1   sever-types (declares EP-4)  sever-quant  sever-partition
          sever-index (declares EP-1, EP-2, EP-3)   sever-search
```

Arrows point down only. A crate at one level uses the crates beneath it through their public APIs, and
extends them only through the extension points they declared.

### 3.2 Crate and package map

| Part | Rust crates | Python packages | Composition root |
|---|---|---|---|
| 1 | `sever-types`, `sever-quant`, `sever-partition`, `sever-index`, `sever-search`, `sever-tracekit` | `sever_partition` (builder), `sever_refmodel_core`, `sever_testkit`, `sever_demo` | `sever-p1` and the `sever-demo` CLI |
| 2 | `sever-vfs`, `sever-format`, `sever-wal`, `sever-appendstore`, `sever-checkpoint`, `sever-txn`, `sever-engine`, `sever-crashkit`, `sever-py-p2` | `sever_refmodel_durable`, `sever_db_p2` (SDK module) | `sever-p2` and the `sever-db-p2` CLI |
| 3 | `sever-crypto`, `sever-commit`, `sever-log`, `sever-cert`, `sever-py-p3`; separate workspaces `verifier/` and `audit/` | `sever_refmodel_certs`, `sever_db_p3` | `sever-p3` |
| 4 | `sever-keys`, `sever-seal`, `sever-erasure`, `sever-platform`, `sever-scan`, `sever-py` | `sever_db` (final SDK), `sever_experiments`, `sever_report` | `sever-db` |

### 3.3 Extension points

These are the contracts that make freezing possible. Each is declared by the part that owns the code
it extends. Each ships a default implementation, so the declaring part is complete on its own, and a
contract suite (§3.4).

| ID | Declared in | Interface | What it lets later parts do | Default (declaring part) | Later implementations |
|---|---|---|---|---|---|
| **EP-1** | Part 1, `sever-index` | `GroupExtension` | Add per-group and per-record state that changes in lockstep with `S` and `n`, and gate deletions | `NoExtension` | Part 3: `CommitmentExtension` (`C_S`, `r_agg`, `C_t`, `r_t`) |
| **EP-2** | Part 1, `sever-index` | `IdScrambler` | Map a record ID to the 64-byte scrambled ID used everywhere below the API | `HmacSha512Scrambler` (spec §9.7; the only production implementation) | — (test-only fixed-key variant) |
| **EP-3** | Part 1, `sever-index` | `ChangeSet` returned by `plan`, consumed by `apply` | Log a change before applying it (Part 2), build a certificate from it (Part 3), rotate keys for it (Part 4) | — (a data type, not a trait) | Read by Parts 2–4 |
| **EP-4** | Part 1, `sever-types` | `SecretMemory` provider | Decide where secret buffers live | Heap with zeroize on drop | Part 4: `mlock`ed pages |
| **EP-5** | Part 2, `sever-vfs` | `Vfs` | All file I/O | `PosixVfs`, `SimVfs` | — |
| **EP-6** | Part 2, `sever-txn` | `Sealer` | Turn stored plaintext into stored bytes and back, per data kind, with a fixed overhead per kind | `PlaintextSealer` (no confidentiality) | Part 4: `AeadSealer` |
| **EP-7** | Part 2, `sever-txn` | `TxnParticipant` | Take part in every transaction: add WAL records and append-store bytes, act durably before commit (phase A) and after commit (phase C), replay, recover, check invariants | None registered | Part 3: `LogParticipant`; Part 4: `KeyRotationParticipant` |
| **EP-8** | Part 2, `sever-appendstore` | `AppendStore` | Append-only record stores (spec §14.8) | File-backed store | Used by Part 3 for leaves and certificates |
| **EP-9** | Part 2, `sever-txn` | `Clock` | Time for log checkpoints and key epochs | `SystemClock`, `SimClock` | Used by Part 3 |

Parts 3 and 4 declare their own extension points in the second plan (for example EP-10 `Witness`).

**What each extension point must be able to express.** These capability lists are normative for the
design review of the declaring part. Exact Rust signatures are fixed during that part's design review,
and then frozen.

**EP-1 `GroupExtension`** must be able to:

1. hold extra group state, split into a **public** part (stored in plaintext; Part 3's `C_S`) and a
   **secret** part (stored sealed with `S`; Part 3's `r_agg`);
2. hold a fixed-size **secret per record** (Part 3: `r_t` for every record, and the insert leaf
   index);
3. admit or reject an insert, given an extension-defined credential (Part 3: check `C_t` and the user
   signature);
4. update its state on every add and remove, in lockstep with `S` and `n`, inside the same `ChangeSet`;
5. check a removal against the record's stored secret, and refuse it as an integrity failure if they
   disagree (Part 3: the stored `x̃` and `r_t` must reproduce the logged `C_t`, otherwise
   `IntegrityViolation`); removal takes no credential, because the application backend authorises
   deletion (spec §3.3, overview DB-55);
6. read a record's secret when a flush moves it from the holding area into a new group (Part 3: fold
   `r_t` into `r_agg`; `has_rt` stays 1);
7. contribute the extension fields of the canonical blob, and its 6-byte magic (DB-47);
8. check its own invariants for a group (Part 3: INV-3);
9. decide whether a duplicate insert is a harmless retry (`DuplicateRecord { same_commitment }`).

**EP-3 `ChangeSet`** must carry, for every mutation:

- the pre-state and the post-state of every touched group (`S`, `n`, and the extension's public and
  secret state);
- every slot operation (put, move-last-into-gap, truncate) and every locator put and delete;
- every created group (from a flush), with its ID and centroid;
- the counters `N` and `k`, before and after;
- **departures**: every `(domain, scrambled_id)` that leaves a group or the holding area (Part 4 rotates
  exactly these domains);
- **arrivals**: every `(domain, scrambled_id)` that joins one;
- the outcome of each request (`Placement`, `Deleted`, `AlreadyAbsent`).

`plan` takes the index by shared reference and never mutates it. `apply` cannot fail: anything that
could fail has already failed in `plan`. A `ChangeSet` spanning many groups is how `delete_user` is one
atomic unit from Part 1 onward.

**EP-6 `Sealer`** must be able to seal and open each data kind of spec §13.2 (slot payload, passage
text, record-key envelope, bucket block, group accumulator), bound to the owner and version fields
the specification lists as associated data. It declares a fixed overhead per kind, so file layouts are
computable. `PlaintextSealer` has zero overhead and empty key envelopes; with `AeadSealer`, the layouts
come out exactly as in spec §14.3–§14.4.

**EP-7 `TxnParticipant`** hooks, in protocol order (§5.4):

| Hook | When | Part 3 uses it to | Part 4 uses it to |
|---|---|---|---|
| `pre_transaction` | Before planning; may request a separate committed transaction first | Create an on-demand log checkpoint (spec §15.3 step 3) | — |
| `prepare` | After `plan`, before any write | Build leaves, the proof and the certificate; list append-store bytes | Generate new keys; re-wrap bucket keys and survivor record keys; re-seal accumulators |
| `phase_a` | Durable side effects that must precede `COMMIT` | — | Write the new group key into the inactive key-file slot and `fsync` |
| `wal_records` | Inside the WAL transaction | `LOG_LEAF`, `CERT_REF`, `LOG_CHECKPOINT` records | New bucket blocks and key envelopes |
| `after_commit` | After `COMMIT` is durable and memory is applied (phase C) | — | Overwrite the old key slot with zeros and `fsync` |
| `replay` | During recovery, per committed participant record | Rebuild the log tree | Rebuild key versions |
| `recover` | After replay | Check INV-15 | Apply the key-file recovery rule (INV-14) |
| `check_invariants` | At startup, and at commit in debug builds | INV-15 | INV-12 to INV-14 |
| `on_drop_collection` | When a collection is dropped | — | Erase every group key of the collection |

Part 2 carries participant records in the WAL as an `EXTENSION` record type
(`u16be participant_id ‖ bytes`). It never interprets their contents.

### 3.4 Contract suites and proof spikes

**Contract suites.** Every extension point ships a contract suite in its declaring crate, behind a
`contract-tests` feature. Any implementation, including one written after the declaring part froze,
must pass it. For example, the EP-1 suite checks that add-then-remove restores the extension state
exactly, that a removal that fails the extension's integrity check is refused, and that the blob
fields are order-independent. This is how frozen code checks code written after it froze.

**Proof spikes.** An extension point that cannot express what a later part needs would force an edit
to a frozen part. So, before a part freezes, a **throwaway** prototype of each later user of its
extension points is written against them and must pass the contract suite:

| Before freezing | Spike | Proves |
|---|---|---|
| Part 1 | A minimal `CommitmentExtension` using the real ristretto255 library, and a stub "rotation" reader of `ChangeSet` departures | EP-1 and EP-3 can express Parts 3 and 4 |
| Part 2 | A minimal `AeadSealer`, a stub `LogParticipant` that appends a leaf atomically, and a stub `KeyRotationParticipant` with phases A and C | EP-6 and EP-7 can express Parts 3 and 4 |

Spikes are deleted after the gate. Their only output is the passing result, recorded in the ledger.

### 3.5 Specification amendments this plan needs

These are proposed decision entries for the overview's register. Each is spec-compatible in the final
system: with Parts 3 and 4 plugged in, the bytes come out exactly as the specification defines them.

| Proposed | Decision |
|---|---|
| **DB-44** | Build in four frozen parts with the freeze rule (§0.3). Erasure (spec phase P4) is built after certificates (spec phase P6), because encryption wraps the bytes that earlier parts define |
| **DB-45** | The index core uses plan/apply with a `ChangeSet`, and extension points EP-1 to EP-9. The WAL gains an `EXTENSION` record type for participant data |
| **DB-46** | The slot payload order becomes `u16be id_len ‖ id padded to 256 ‖ x̃ as d × i32be ‖ extension record secret`. With the commitment extension (41 bytes: `u64be insert_leaf_index ‖ u8 has_rt ‖ r_t`) it is still 1,835 bytes, and the slot is still 1,992 bytes. The group header gains a sealer-maintained `u64be seal_version` in place of `group_key_version` (the same bytes in the final system) |
| **DB-47** | The canonical group blob has an extension region between `S` and `member_count`, and its magic is chosen by the extension. With `NoExtension` the magic is `SEVERC` and the region is empty; with the commitment extension the magic is `SEVERG` and the region is `C_S ‖ r_agg`, which is byte-identical to spec §5.5 |
| **DB-48** | Every storage file records a `sealer_id`. A database written with `PlaintextSealer` is refused by an encrypting build, and the reverse. Part 2 alone makes **no** confidentiality claim; the ciphertext-only rule (INV-11) applies from Part 4 |
| **DB-49** | The code accepts any dimension that is a multiple of 8 and any number of frozen groups ≥ 1; the v1 configuration fixes 384 and 128. Small dimensions are used only by fast tests |
| **DB-50** | The `SecretMemory` provider is installed once, by the composition root, at startup |

**Status (7 October 2026).** All seven are accepted and recorded in overview §6.8: DB-44, DB-45, DB-47,
DB-49 and DB-50 on 4 October 2026; DB-46 and DB-48 on 7 October 2026, at Part 2's design review.

---

## 4. Part 1 — The Idea

### 4.1 Announcement

**What it is.** An in-memory library, a partition builder, a reference model and a demo. The library
stores vectors in groups with exact integer sums and counts, deletes them exactly, routes drifting data
into spawned groups, and searches.

**Why it exists.** This is the core insight. Every later part protects it: durability, receipts and
erasure are worthless if the arithmetic is not exact. Part 1 is also the part that shows a reviewer, in
one screen, why the idea matters.

**What Part 1 may claim, once its gates pass.** Within one process, every deletion returns the touched
group to a state that is byte-identical to the state built from its surviving members alone (sum,
count, canonical blob, member list). A float-average index and a soft-delete index both keep a
measurable trace of the deleted vector.

**What Part 1 does not claim.** Anything about crashes, files, receipts, encryption or erasure.

### 4.2 Goals

| ID | Goal |
|---|---|
| **P1-G1** | Exact arithmetic: normalisation check, Q24 quantiser, integer accumulators, exact removal (spec §4, §5) |
| **P1-G2** | The frozen partition: a Python builder with an independent Ledoit–Wolf oracle, and a Rust artefact importer (spec §6) |
| **P1-G3** | Routing: nearest frozen group, Mahalanobis drift test, spillover, holding area, flush into a spawned group (spec §7) |
| **P1-G4** | Search: IVF-flat with the pinned kernel; scalar and AVX2 bit-identical (spec §8) |
| **P1-G5** | The reference model, and trace-based differential testing that every later part reuses |
| **P1-G6** | The demo: stats before and after a deletion, the survivors check, and two ghost-carrying baselines |
| **P1-G7** | Extension points EP-1 to EP-4, with contract suites and passing proof spikes |

### 4.3 Scope

**In:** spec §3.2 (record-ID rules), §3.5 (cohorts), §4, §5 (with `C_S` and `r_agg` entering only
through EP-1 in Part 3), §6, §7, §8, §9.7 (ID scrambling). In-memory slot arrays with
swap-with-last removal and the locator (the semantics of §14.4, not its bytes). `delete_user` as one
multi-group `ChangeSet`. An `IndexConfig` switch `spawning_enabled` (default `true`): when `false`,
every vector goes to its nearest frozen group. It exists for the frozen-only control arm of overview
§10.7 (used in Part 4's EX-6) and for the whole-index twin test (§4.7, L6). Because Part 1 freezes, the
switch must exist here, even though its main user comes later. Appendix B golden vectors 5
(quantisation), 7 (spawn ID) and a `SEVERC` core blob vector.

**Out:** files and crashes (Part 2); commitments, signatures, log and certificates (Part 3); encryption
and keys (Part 4).

### 4.4 Modules

| Crate or package | Responsibility | Spec |
|---|---|---|
| `sever-types` | Record, group and collection IDs with validation; scrambled IDs; constants; core error types; `SecretBuf` and EP-4 | §2, §3.2, §17 (subset) |
| `sever-quant` | Normalisation check, Q24 quantisation, dequantisation to f64 and f32 | §4.1–4.3 |
| `sever-partition` | Parse and validate `partition.svp` (hash, `d`, finite precision matrix) | §6.3 |
| `sever-index` | Groups, accumulators, slots, locator, holding area, router, flush, capacity, `plan`/`apply`, `ChangeSet`, canonical blob, equivalence helper, invariant checks; declares EP-1, EP-2, EP-3 | §5, §7, §9.7 |
| `sever-search` | Float32 mirror, scalar and AVX2 kernels, IVF-flat search, top-k | §8 |
| `sever-tracekit` | Read, write and replay trace files | — |
| `sever-p1` | Composition root `Index<NoExtension>`; the `sever-demo` CLI | — |
| `sever_partition` (Python) | The builder, including the independent Ledoit–Wolf oracle | §6.2 |
| `sever_refmodel_core` (Python) | The slow, obviously correct model of §3–§8 | §3–§8 |
| `sever_testkit` (Python) | Synthetic data, dataset slices, seed derivation, trace writing | Overview §10 |
| `sever_demo` (Python) | Renders the demo's JSON output as tables and charts | — |

**Architecture rules for Part 1** (L13): `sever-index`, `sever-quant` and `sever-search` have no
dependency on `std::fs`, networking, time or any random-number crate. The only entropy in Part 1 is the
scrambling key, generated by the composition root and handed in.

### 4.5 Public surface (shape)

```rust
// sever-index — shape only; exact signatures are fixed at Part 1's design review, then frozen.
pub struct Index<E: GroupExtension, S: IdScrambler> { /* … */ }

impl<E: GroupExtension, S: IdScrambler> Index<E, S> {
    pub fn new(artefact: PartitionArtefact, cfg: IndexConfig, ext: E, scrambler: S) -> Result<Self>;

    pub fn plan_insert(&self, req: InsertRequest<E>) -> Result<ChangeSet<E>>;           // pure
    pub fn plan_delete(&self, req: DeleteRequest<E>) -> Result<ChangeSet<E>>;           // AlreadyAbsent is an outcome
    pub fn plan_delete_many(&self, reqs: Vec<DeleteRequest<E>>) -> Result<ChangeSet<E>>; // one atomic unit
    pub fn apply(&mut self, cs: ChangeSet<E>);                                          // infallible

    pub fn search(&self, query: &[f32], k: usize) -> Result<Vec<Hit>>;
    pub fn stats(&self) -> Stats;          // groups by kind, sizes, N, k, holding count, OOD rate

    #[cfg(feature = "test-hooks")]
    pub fn group_snapshot(&self, g: &GroupId) -> GroupSnapshot<E>;  // S, n, ext state, members, blob
}
```

In Part 1, `insert` and `delete` are convenience wrappers that call `plan` then `apply`.

### 4.6 Requirements owned by Part 1 (examples)

`spec/requirements.yaml` lists every requirement. The groups owned by Part 1 are:

| Area | Spec | Examples |
|---|---|---|
| Record IDs | §3.2 | 1–256 bytes; not a bare decimal integer; not live |
| Normalisation and quantisation | §4.1–4.3 | finite components; sequential f64 norm; tolerance; ties to even; `i32` bound |
| Accumulators and capacity | §4.4, §5.2–5.6 | all fields change together; hard cap; room test in exact integers; INV-5 at startup |
| Excision and idempotency | §5.4 | no markers; `AlreadyAbsent` changes nothing; empty groups persist |
| Canonical blob | §5.5 | layout; parser rejections; insertion-order independence; five-field equivalence helper |
| Partition | §6 | artefact hash and shape checks; builder oracle agreement |
| Routing | §7 | pure function; tie rules; spillover before holding; flush at exactly 200; spawn ID and centroid |
| Search | §8 | ranking and tie-breaks; probe budget counts empty groups; pinned kernel; deleted records never returned |
| Scrambling | §9.7 | HMAC-SHA-512 over `collection_id ‖ record_id` |

### 4.7 Test plan

**L1 Unit**

- Quantiser: half-step inputs round to even (golden vector 5); `|x̃| = 2^24 + 16` at the tolerance edge;
  NaN and infinity rejected.
- Norm tolerance at exactly ±8 ULPs, and one ULP outside, on both sides.
- Record-ID rules from the §3.2 table (equivalence classes in §2.2).
- Mahalanobis: `q < 0` raises `IntegrityViolation`, using a non-positive-definite fixture.
- The room test at the three boundary points (`2kn = 3N − 1`, `3N`, `3N + 1`).
- Spawn ID golden (vector 7); an ID collision raises `IntegrityViolation`.
- Blob parser rejects `member_count ≠ n`, unsorted IDs, duplicate IDs, empty IDs and trailing bytes.
- Kernel lane order and reduction order against a hand-computed 16-dimensional example.
- Probe count `⌈0.25k⌉` for `k` mod 4 = 0, 1, 2, 3.

**L2 Property**

- Insert then delete returns every field of the group to its prior value.
- For any set of members and any two insertion orders, the blobs are identical.
- Deletion is idempotent: a second delete returns `AlreadyAbsent` and the state hash is unchanged.
- `plan` never mutates: the state hash is equal before and after any `plan` call.
- Routing is pure: the same `(x̃, state)` always gives the same destination, including when group
  creation order differs (spec §7.7, tests 1–2).
- The accumulator bound: under the cap, no `|S_i|` exceeds `2^44`.

**L3 Spec conformance**

- `spec-trace` at 100 % for Part 1's requirements.
- Table-driven tests for §3.2 and the Part 1 rows of §17.
- Appendix A constants for arithmetic and search (the `x̃` bound, the `S` bound, probe counts)
  asserted against code constants.

**L4 Differential**

- Synthetic streams: 1,000 streams × 1,000 operations at the small fixture size.
- `nq-10k` on all five seeds: the blob hash of every touched group after every operation; full blobs
  and top-10 and top-100 results for all 3,452 queries after each deletion rung.
- `nq-100k` on all five seeds: the same comparison (the Part 1 portion of overview T-3).

**L5 Model-based stateful.** A state machine with the operations insert (in-distribution), insert
(out-of-distribution), delete, delete an absent record, re-insert a deleted ID, `delete_user` and
search, checked against `sever_refmodel_core` after every step. It runs at the small fixture size so
that flushes, spillover and empty groups occur often.

**L6 Metamorphic**

- **The survivors check.** After any sequence of deletions, every group equals the group built from its
  surviving members alone, on all core fields of the equivalence relation. This is the exact meaning of
  "as if never inserted" (spec §5.5). It is checked per group, because the index *shape* (which groups
  were spawned) legitimately depends on history (overview L-3, L-24).
- **The whole-index twin.** With spawning disabled (frozen-only configuration), an index that inserts
  everything and then deletes a set D is byte-identical to one that never inserted D.
- Permuting insertion order leaves every blob unchanged.
- Deleting a record, then re-inserting it, gives the same group state as never deleting it.

**L7 Contract.** The EP-1, EP-2 and EP-4 suites pass for `NoExtension`, `HmacSha512Scrambler` and the
heap provider. A deliberately wrong extension (for example, one whose `remove` is not the inverse of
`add`) fails the EP-1 suite. The proof spikes of §3.4 pass.

**L8 Integration**

- Builder to importer: the artefact built in Python loads in Rust, and Rust routing of every reference
  row matches the builder's labels and the model's drift decisions.
- The recall harness: brute force over the original floats against the engine.

**L9 End-to-end** (through the `sever-demo` CLI, on `nq-10k`):

| ID | Given | When | Then |
|---|---|---|---|
| E2E-1.1 | An index with 10,000 passages | One record is deleted | The touched group's blob equals the survivors-only blob; `N` falls by one; nothing else changes |
| E2E-1.2 | An index whose holding area holds 199 records | The 200th out-of-distribution record arrives | Exactly one spawned group appears, with 200 members and the spec §7.5 ID |
| E2E-1.3 | A record in the holding area | It is deleted | It is gone immediately; no accumulator changes |
| E2E-1.4 | A cohort spread over several groups | `delete_user` runs | Every touched group passes the survivors check; no other group changes |
| E2E-1.5 | A record already deleted | It is deleted again | `AlreadyAbsent`; the state hash is unchanged |
| E2E-1.6 | Any deleted record | Every one of the 3,452 queries runs | The record appears in no result |
| E2E-1.7 | Malformed inputs (every §17 case Part 1 owns) | They are submitted | A typed error whose text contains no ID, vector value or key |

**L11 Fuzz.** The artefact parser and the blob parser.

**L12 Mutation and sabotage.** SB-1 to SB-10 each turn a test red. `cargo-mutants` runs on
`sever-quant`, `sever-index` and `sever-search`, and `mutmut` on the model and builder. Every
surviving mutant is either killed with a new test or documented as equivalent.

**L13 Architecture.** The "no I/O, no clock, no RNG in the core" rule; the dependency direction.

**L14 Benchmarks** (descriptive only). `plan` and `apply` latency; search latency and throughput at
`nq-100k`.

### 4.8 Targets

| ID | Target | Kind |
|---|---|---|
| **P1-T1** | 0 exactness violations: every deletion in every L2, L4, L5 and L6 run passes the survivors check on every core field | Gate |
| **P1-T2** | 0 mismatches between engine and model: blob hashes after every operation, and top-10 and top-100 lists after every rung, on `nq-10k` and `nq-100k`, five seeds | Gate |
| **P1-T3** | 100 % identical blobs across 100 random insertion orders per tested member set | Gate |
| **P1-T4** | Scalar and AVX2 kernels bit-identical on 10^7 random pairs and on every query–vector pair of the differential runs | Gate |
| **P1-T5** | 0 deleted records returned by any search after deletion | Gate |
| **P1-T6** | Builder oracle agreement: shrinkage to 1e-12 and τ to 1e-9, all five seeds | Gate |
| **P1-T7** | Recall@10 of dequantised brute force against original-float brute force at `nq-100k` (overview T-6, first size) | Measure (pre-registered ≥ 0.999) |
| **P1-T8** | SB-1 to SB-10 each turn at least one test red | Gate |
| **P1-T9** | Traceability 100 % for Part 1's requirements | Gate |
| **P1-T10** | Line coverage ≥ 90 % and branch coverage ≥ 85 % on `sever-quant`, `sever-index` and `sever-search`; line coverage ≥ 90 % on the model and builder | Gate |
| **P1-T11** | Mutation score ≥ 85 % on the same crates, with every survivor triaged | Gate |
| **P1-T12** | 0 fuzz crashes in ≥ 10^8 executions per parser | Gate |
| **P1-T13** | Contract suites pass for every default implementation and fail for a deliberately wrong one; proof spikes pass | Gate |
| **P1-T14** | The ghost measurement: for the demo deletions, how far each baseline's group summary remains from the survivors-only summary | Measure (descriptive) |

### 4.9 The demo

One command, `sever-demo idea --data nq-10k --seed 42`, or `--data synthetic` for an offline demo.

1. **Build.** Load the partition, stream the passages, and print global stats: frozen and spawned
   groups, `N`, holding-area size, out-of-distribution rate.
2. **Pick a target.** Choose a cohort (all passages from one article title) and show the groups it
   touches.
3. **Before.** For each touched group: `n`, the SHA-256 of `S`, and the SHA-256 of the canonical blob.
4. **Delete** the cohort with `delete_user`.
5. **After.** The same columns, plus the SHA-256 of the blob rebuilt from the survivors alone, and a
   ✓ when they match.
6. **The ghost.** The same deletion in two baselines, run side by side:
   - a **soft-delete IVF** index: the record is still in its posting list, and the centroid still
     carries its contribution (distance from the survivors' mean is reported);
   - a **float running-mean** index that subtracts on deletion: its bits no longer match the
     survivors-only mean (the largest absolute difference is reported).
7. **Search.** A query that used to return a deleted passage no longer returns it.

Illustrative layout (the values are placeholders, not results):

```
group          n_before  n_after  blob_after (sha256)   survivors-only (sha256)  exact
frozen-0042      812      809     3f1a…c9e0             3f1a…c9e0                  ✓
spawn-9c1e…      231      230     77d0…12ab             77d0…12ab                  ✓

baseline         deleted record still stored   summary distance from survivors-only
soft-delete IVF  yes                           <measured>
float mean       no                            <measured, max abs diff>
SEVER (Part 1)   no                            0 (bit-identical)
```

The CLI also writes the whole run as JSON, which `sever_demo` renders as a one-page report with
charts.

### 4.10 Exit gate and freeze

Part 1 freezes when the definition of done (§2.9) holds, including every gate target (P1-T1 to P1-T6
and P1-T8 to P1-T13), the two measurements P1-T7 and P1-T14 recorded as found, the proof spikes passed and deleted, and the demo running from a clean
clone. Tag: `part-1-frozen`.

---

## 5. Part 2 — The Database

### 5.1 Announcement

**What it is.** A transactional, crash-safe storage engine wrapped around Part 1's frozen index. It
adds the file layer (`Vfs`, including the fault-injecting `SimVfs`), byte formats, the write-ahead log,
storage checkpoints, the transaction manager, recovery with a full invariant check, collections, the
Rust API and a Python SDK.

**Why it exists.** An exact index that forgets everything after a crash, or that half-applies a
multi-group deletion, is not a database. Parts 3 and 4 also need an atomic commit to hook into:
certificates and key rotations must commit together with the deletion they belong to.

**What Part 2 may claim, once its gates pass.** Part 1's exactness holds after a crash at any point of
any operation; no acknowledged operation is lost; `delete_user` is all-or-nothing; reads are
serializable.

**What Part 2 does not claim.** Confidentiality. Part 2 stores plaintext through `PlaintextSealer`, and
its databases are marked as plaintext (DB-48). It also claims nothing about receipts or erasure.

### 5.2 Goals

| ID | Goal |
|---|---|
| **P2-G1** | The file layer: `Vfs`, `PosixVfs`, and a seeded `SimVfs` that models the POSIX durability contract conservatively (spec §12.2) |
| **P2-G2** | Byte-exact, checksummed, versioned formats with strict parsers (spec §14, except §14.5 and §14.7) |
| **P2-G3** | The WAL and storage checkpoints (spec §12.3–12.4, §15.6) |
| **P2-G4** | The transaction manager: one writer, shared readers, the participant protocol (§5.4) (spec §12.5) |
| **P2-G5** | Recovery with the full invariant check (spec §15.7) |
| **P2-G6** | The engine API and collections (spec §16.1, §15.9 without the cryptographic erase), and the basic Python SDK |
| **P2-G7** | A reusable crash-campaign kit and the durable oracle |
| **P2-G8** | Extension points EP-5 to EP-9, with contract suites and passing proof spikes |

### 5.3 Scope

**In:** spec §12.1–12.7, the data-directory filesystem checks of §12.9, §14.1–14.4, §14.6, §14.8, §15.1,
§15.3 (without phases A and C and without the certificate, which arrive through EP-7), §15.5–15.7,
§15.9 (removing files), §16.1, §17.

**Out:** key-file checks, memory locking and swap checks (Part 4); certificates and the log (Part 3).

### 5.4 The transaction protocol

Part 2 defines the protocol once. Later parts only add participants to it.

```
 1  plan                 Part 1 computes a ChangeSet (pure; all validation here)
 2  prepare              each participant adds WAL records, append-store bytes and phase-A actions
 3  append stores        write their bytes; fsync
 4  phase A              each participant's durable pre-commit actions (Part 4: new key slot; fsync)
 5  WAL                  BEGIN, core records sealed by the Sealer, EXTENSION records, COUNTERS, COMMIT; fsync
                         ─── commit point ───
 6  apply                exclusive lock; install the ChangeSet; update the mirror; zero temporaries
 7  phase C              each participant's after_commit (Part 4: erase the old key slot; fsync)
 8  acknowledge          only now does the caller see success (spec §15.8)
```

**Recovery:** load the storage checkpoint; replay every transaction with a valid `COMMIT`, passing
`EXTENSION` records to their participants; call each participant's `recover`; run the full invariant
check; serve. Part 2 itself registers no participants.

### 5.5 Modules

| Crate or package | Responsibility | Spec |
|---|---|---|
| `sever-vfs` | EP-5; `PosixVfs`; `SimVfs` (drop unsynced writes, tear writes at any byte, reorder unsynced writes, fail any `fsync`, lose un-synced directory entries) | §12.2 |
| `sever-format` | Pages, group header, slot, WAL records, `MANIFEST`, checkpoint files, append-store records; strict parsers | §14 |
| `sever-wal` | Segments, transactions, torn-tail handling, replay | §12.3 |
| `sever-appendstore` | EP-8; payload store for passage text | §14.8 |
| `sever-checkpoint` | Atomic full images, `MANIFEST` install, WAL truncation | §12.4, §15.6 |
| `sever-txn` | EP-6, EP-7, EP-9; writer mutex and reader lock; the §5.4 protocol | §12.5, §15 |
| `sever-engine` | Generic `Engine<E, S, P>`; collections; recovery; INV-2 to INV-9; platform checks for the data directory | §12.7, §12.9, §15.7, §16.1, §21 |
| `sever-crashkit` | Crash-campaign driver on `SimVfs`: crash at every step, at byte offsets, at random points, and during recovery | Overview EX-1 |
| `sever-p2` | Composition root `Engine<NoExtension, PlaintextSealer, ()>`; the `sever-db-p2` CLI | — |
| `sever-py-p2` / `sever_db_p2` | PyO3 bindings and the Python SDK for the Part 2 API | §16.2 (without commitments) |
| `sever_refmodel_durable` (Python) | The durable oracle: which states are acceptable after a crash (below) | — |

**The durable oracle.** After a crash, let A be the operations that were acknowledged. The one
operation in flight may or may not have reached its commit point. The recovered state MUST equal
exactly one of two states computed by `sever_refmodel_core`: A applied, or A plus the in-flight
operation. It must never be anything in between, and a retried operation must behave as spec §15.1
and §15.4 say.

### 5.6 Requirements owned by Part 2 (examples)

| Area | Spec | Examples |
|---|---|---|
| Durability discipline | §12.7 | directory `fsync` after create, rename and unlink; abort on `fsync` error; no writes through `mmap`; CRC on every record |
| WAL | §12.3 | committed exactly when a valid `COMMIT` is durable; uncommitted and torn transactions discarded whole |
| Storage checkpoints | §12.4, §15.6 | an interrupted checkpoint leaves the previous one valid |
| Isolation | §12.5 | serializable; no retained snapshots; `delete_user` in one transaction |
| Recovery | §15.7 | the full invariant check, and refusal to serve on any violation |
| Formats | §14 | magic, version and CRC everywhere; layouts; strict rejection |
| API and errors | §16.1, §17 | typed errors; no leakage; `DuplicateRecord { same_commitment }` for retries |

### 5.7 Test plan

**L1 Unit.** Every format's encoder and parser; WAL segment rollover; the checkpoint steps; lock
behaviour; every §17 error Part 2 owns.

**L2 Property**

- Every format round-trips: `parse(encode(x)) = x`.
- Every single-bit flip in any stored record is detected.
- WAL replay is idempotent: replaying twice gives the same state as replaying once.

**L3 Spec conformance.** `spec-trace` at 100 % for Part 2's requirements; the layouts of §14.3, §14.4
and §14.6 checked by offset; Appendix A sizes for slots and headers asserted with the size
`PlaintextSealer` produces and with the sizes the spike `AeadSealer` produces.

**L4 Differential — regression by reuse.** Part 1's frozen traces replay unchanged through the Part 2
engine, once as they are and once with a close-and-reopen after every deletion rung. The results must
be identical.

**L5 Model-based stateful.** Part 1's state machine, plus the operations "crash at a random point",
"recover", "take a storage checkpoint" and "drop a collection", checked against the durable oracle.

**L6 Metamorphic.** Recovering from the WAL alone and recovering from checkpoint plus WAL give the same
state. Two collections never influence each other's blobs.

**L7 Contract**

- The EP-5 suite passes on `PosixVfs` (tmpfs and ext4) and on `SimVfs`. A deliberately non-durable
  backend (one that "loses" nothing) fails the crash-detection part of the suite.
- The EP-6 suite passes on `PlaintextSealer` and the spike `AeadSealer`.
- The EP-7 suite passes on the spike participants.
- EP-8 and EP-9 pass their suites.

**L8 Integration.** SDK to engine; engine to index (Part 1's public API only); collections isolation.

**L9 End-to-end** (through `sever-db-p2` and the SDK):

| ID | Given | When | Then |
|---|---|---|---|
| E2E-2.1 | A database with `nq-10k` loaded | It is closed and reopened | Every blob, count and search result is unchanged |
| E2E-2.2 | A `delete_user` spanning several groups in flight | The process is killed (`SIGKILL`) and restarted | Either every record is gone or none is; the invariant check passes |
| E2E-2.3 | An insert whose acknowledgement was lost | The application backend retries | `DuplicateRecord { same_commitment: true }`, which the SDK treats as success |
| E2E-2.4 | A deletion whose acknowledgement was lost | The application backend retries | `AlreadyAbsent` |
| E2E-2.5 | A `Vfs` that fails an `fsync` | Any write runs | The process aborts; the restart recovers a valid state |
| E2E-2.6 | A database on a disk image | The image is unmounted and remounted | The state is unchanged |
| E2E-2.7 | Two collections | One is dropped | The other is byte-for-byte unaffected |
| E2E-2.8 | Every malformed request | It is submitted through the SDK | A typed error with no leaked content |

E2E-2.2 is a demonstration on real processes. The **evidence** for crash safety comes from the
deterministic `SimVfs` campaign (L10), not from random kills.

**L10 Fault and crash.** The campaign follows overview EX-1, per seed:

1. **Generic records first.** The campaign runs on generic fixed-size records before any index code
   is involved, so each bug has one home (overview P3).
2. **Index records.** A 20,000-operation stream over 10,000 passages, with a crash:
   - at every protocol step boundary of every operation;
   - at every 512-byte offset of 200 sampled WAL writes;
   - at 1,000 random points;
   - **during recovery itself** (a double crash), to show that recovery is idempotent.
3. After each crash: recover, run the invariant check, and compare with the durable oracle.

**L11 Fuzz.** WAL records, `MANIFEST`, checkpoint files, append-store records.

**L12 Mutation and sabotage.** SB-11 to SB-15 each turn a test red. Mutation testing on `sever-wal`,
`sever-txn`, `sever-engine` and `sever-format`.

**L13 Architecture.** The freeze guard for Part 1; `sever-engine` uses `sever-index` only through its
public API.

**L14 Benchmarks** (descriptive). Bytes written and `fsync`s per operation; recovery time at
`nq-100k`; resident memory.

### 5.8 Targets

| ID | Target | Kind |
|---|---|---|
| **P2-T1** | Across the full crash campaign on five seeds: 0 exactness violations, 0 lost acknowledged operations, 0 corrupt recoveries, 0 startup refusals after an honest crash (overview T-1, without certificates) | Gate |
| **P2-T2** | 100 % of recovered states equal an oracle-allowed state byte for byte | Gate |
| **P2-T3** | 0 partial applications of `delete_user` at any crash point | Gate |
| **P2-T4** | 0 mixed-state reads across every explored interleaving | Gate |
| **P2-T5** | Part 1's full suite passes unchanged against the Part 2 engine, with and without restarts (F-5) | Gate |
| **P2-T6** | 100 % of single-bit flips detected; 0 fuzz crashes in ≥ 10^8 executions per parser | Gate |
| **P2-T7** | The EP-5 to EP-9 contract suites pass for every implementation and fail for deliberately wrong ones; proof spikes pass | Gate |
| **P2-T8** | SB-11 to SB-15 each turn at least one test red | Gate |
| **P2-T9** | Traceability 100 %; line coverage ≥ 90 % and branch coverage ≥ 85 %, and mutation score ≥ 85 %, on `sever-format`, `sever-wal`, `sever-txn` and `sever-engine` | Gate |
| **P2-T10** | The Part 1 freeze manifest is unchanged | Gate |
| **P2-T11** | Bytes written and `fsync`s per operation, recovery time and resident memory at `nq-100k` | Measure (descriptive) |

### 5.9 The demo

`sever-demo durable --data nq-10k --seed 42`:

1. Load 10,000 passages into a database on a disk image, and show the stats.
2. Start a `delete_user` over a cohort spanning several groups, with a crash injected by `SimVfs` at a
   chosen step (before the commit point, then again after it).
3. Recover, and show: the invariant check passing, the before and after stats, and all-or-nothing
   behaviour (every record deleted, or none).
4. Repeat with a real `SIGKILL` on the POSIX backend.
5. Show that Part 1's survivors check still holds for every touched group after recovery.

### 5.10 Exit gate and freeze

Part 2 freezes when the definition of done (§2.9) holds, including P2-T1 to P2-T10 as gates, P2-T11
measured and recorded, and the Part 2 proof spikes passed and deleted. Tag: `part-2-frozen`. Parts 3
and 4 are specified in `SEVER-DB_BUILD_PLAN_PART_3-4.md`.

---

## 6. Appendix — templates

### 6.1 Pull request checklist

- [ ] Which part does this change belong to? Is that part frozen? (If yes, this must be an erratum.)
- [ ] Which requirements (`SR-…`) does it implement or test? Is the traceability matrix still complete?
- [ ] Are new tests at every applicable level (L1–L13)?
- [ ] Does any sabotage now pass silently?
- [ ] Is any new design choice recorded as a `DB-N` entry?
- [ ] Do error messages avoid IDs, vectors, keys, `r_t` and text?
- [ ] Did the Fast CI tier pass?

### 6.2 Test naming

`<part>_<area>_<behaviour>`, for example `p1_index_delete_restores_survivors_state` or
`p2_wal_torn_tail_is_discarded`. The `#[spec(...)]` or `@pytest.mark.spec(...)` annotation carries the
requirement IDs.

### 6.3 Erratum entry

```
E-N  Part: <1–4>   Found by: <test or observation>
Symptom:        …
Root cause:     …
Regression test: <test name>, committed at <commit> before the fix
Fix:            <commit>; files changed: …
Gates re-run:   Part <N> … Part 4, ledger entries …
New freeze tag: part-N-frozen-eK
```
