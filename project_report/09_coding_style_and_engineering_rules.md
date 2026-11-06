# 09 · Coding style and engineering rules

## In simple words

SEVER-DB follows strict, written rules so that its claims can be trusted: errors never leak secrets,
the core has no hidden sources of non-determinism, every rule in the spec is tagged on the tests that
check it, deliberately broken builds prove the tests work, and finished parts are frozen by hash. This
file lists the rules that are actually visible in the code, with real examples, and why each exists.

> **Prerequisites.** Rust crates, traits, `Result`, attributes and features
> ([B06](background/B06_rust_and_python_for_this_project.md)); sabotage and oracles
> ([B05](background/B05_software_testing_concepts.md)). Glossary: [freeze](16_glossary.md#freeze),
> [SR-x-n](16_glossary.md#sr-x-n-requirement-id), [plan/apply](16_glossary.md#plan--apply).

## The problem this solves

In a security project, a "small" style slip can break a claim: an error message that prints a record
ID leaks personal data; a hidden clock makes routing order-dependent; an `unwrap()` crashes the engine
mid-transaction. Rules enforced by tools catch these mechanically.

## The rules, with evidence

### 1. Crate organisation by part

One Rust workspace (`members = ["crates/*"]`, edition 2024, resolver 3, MSRV 1.85), plus separate
workspaces for the verifier, auditor and fuzzers [CODE: Cargo.toml:L5-L12]. Each part adds crates and
never edits a frozen one (F-3); code of part N depends only on parts ≤ N, checked by
`tests/architecture/test_architecture.py` [CODE: tests/architecture/test_architecture.py:L15-L215].
*Why:* a frozen part's evidence must stay valid (Build §0.3).

### 2. Lints set once for the whole workspace

```toml
[workspace.lints.rust]
unsafe_code = "forbid"
missing_docs = "deny"

[workspace.lints.clippy]
all = { level = "warn", priority = -1 }
unwrap_used = "deny"
expect_used = "deny"
panic = "deny"
indexing_slicing = "deny"
```
[CODE: Cargo.toml:L14-L25]. `clippy.toml` allows these only inside tests [CODE: clippy.toml].
`rustfmt.toml` sets `max_width = 100`, the same as ruff [CODE: rustfmt.toml]. *Why:* library code must
return typed errors instead of crashing, and every public item is documented.

### 3. `unsafe` confined to the SIMD kernel

Only `crates/sever-search/src/kernel.rs` has `#![allow(unsafe_code)]`; that crate sets `unsafe_code =
"deny"` instead of `forbid` for this one module [CODE: crates/sever-search/Cargo.toml:L25-L28;
RUN: `grep -rln "allow(unsafe_code)" crates verifier/src audit/src`]. Crypto crates add
`#![forbid(unsafe_code)]` themselves [CODE: crates/sever-crypto/src/lib.rs:L18]. *Why:* memory-safety
bugs are a classic way to leak secrets.

### 4. Typed errors with no secrets (§17)

```rust
pub enum Error {
    /// §4.1 fails: the vector does not have `d` components (see gap G-8).
    #[error("vector has the wrong dimension")]
    WrongDimension,
    ...
```
[CODE: crates/sever-types/src/error.rs:L33-L40]. 13 variants, one per row of spec §17; no variant
stores a record ID, vector value, key or `r_t`; a test asserts every message is fixed ASCII text
(`p1_types_error_messages_are_fixed_text`, error.rs:L160-L168). `IntegrityViolation` carries only a
static label such as `"INV-6 S equals the sum of members"`. *Why:* errors end up in logs, and logs are
not protected. Line-by-line: `#[derive(..., thiserror::Error)]` generates the `Display` text from each
`#[error("...")]` attribute; `///` lines are doc comments (required by `missing_docs`).

### 5. No I/O, clock or randomness in the core

The core crates `sever-types`, `sever-quant`, `sever-index`, `sever-search`, `sever-partition` must
not use `std::fs`, `std::net`, `std::time`, `std::env`, `OsRng`, `thread_rng`, nor depend on `rand`,
`getrandom`, `chrono`, `tokio`, … — enforced by regex and dependency-closure checks
[CODE: tests/architecture/test_architecture.py:L117 `p1_arch_core_has_no_io_clock_rng_or_fitting_dependency`].
The scrambling key is handed in by the composition root [CODE: crates/sever-p1/src/root.rs:L24-L36].
*Why:* routing must be a pure function of `(x̃, state)` (§7), and determinism makes differential
testing possible.

### 6. Plan, then apply

Every mutation is computed by a pure `plan_*` method returning a `ChangeSet`; `apply` cannot fail
[CODE: crates/sever-index/src/index.rs:L282-L353]. *Why:* a half-applied change would break exactness.

### 7. Sabotage feature flags

Each SB-N is a Cargo feature `sabotage-SB-N`; the broken branch is usually `if cfg!(feature = ...)`,
constant-folded away in the normal build, and occasionally a real `#[cfg]`/`#[cfg_attr]` (SB-9, SB-28,
SB-29) [CODE: crates/sever-index/src/index.rs:L832; crates/sever-search/src/kernel.rs:L79;
crates/sever-seal/src/sealer.rs:L81]. CI lints the code with `--all-features` so sabotage code stays
clean [CODE: scripts/ci.sh:L44]. *Why:* a test that never fails proves nothing (Overview §9.2).

### 8. Spec tagging and oracle declarations

```rust
    // no variant stores caller data, so every message is fixed text. The check
    // that a rejected ID never reaches the message is in `id.rs`.
    #[spec("SR-17-2")]
    #[test]
    fn p1_types_error_messages_are_fixed_text() {
```
[CODE: crates/sever-types/src/error.rs:L157-L161]. (Part 1 predates the oracle rule, which applies from
Part 2 on; later tests put a `// oracle: A §… ` comment directly above `#[spec(...)]`, CLAUDE.md §6.3.) `#[spec("SR-…")]` is a no-op attribute macro from
`sever-spec` that only validates the ID format [CODE: crates/sever-spec/src/lib.rs:L1-L35]; Python uses
`@pytest.mark.spec("SR-…")` and `@pytest.mark.oracle("A", "§…")` (markers registered in
`pyproject.toml`). Counts: 381 `#[spec(` in Rust, 83 `@pytest.mark.spec(` in Python, 370 `// oracle:`
comments (A 317, B 11, B-shared 19, C 11, D 12) [RUN: greps recorded in _notes/testing.md §2].
*Why:* every MUST in the spec must be guarded by a test that can fail (CLAUDE.md §6.3).

### 9. Naming and placement

Tests are named `p<part>_<area>_<behaviour>` (e.g. `p1_index_prop_insertion_order_independent`);
494 of 538 Rust tests in `crates/` follow it [RUN: _notes/testing.md §13]. Unit tests live next to the
code (`src/tests.rs`), integration tests in each crate's `tests/`, Python tests in each package's
`tests/`, cross-cutting suites in `tests/`. (The planned `tests/spec/`, `tests/differential/`, … and
`benches/` folders do not exist — see [14](14_status_gaps_and_pending.md).)

### 10. `§` comments in code

Code cites the spec rule it implements, e.g. `// §4.1 step 0 (DB-60): the dimension, before anything is
read.` [CODE: crates/sever-quant/src/lib.rs:L25]. *Why:* a reviewer can check each line against the spec.

### 11. Determinism rules

Python runs with `PYTHONHASHSEED=0` (recorded in every ledger entry, field `pythonhashseed`); the five
seeds 42, 123, 777, 2024, 9999 are used only for data order, synthetic data and k-means; sub-seeds are
`SHA-256(u64be(seed) ‖ label)[0:8]` [CODE: python/sever_testkit/seeds.py:L9-L23]. Floating-point
summation orders are pinned (sequential loops in Rust, `np.cumsum(...)[..., -1]` in Python, never
`np.sum` or `@`) [CODE: python/sever_partition/arith.py:L1-L6; DOC: CLAUDE.md §7]. *Why:* the engine and
the reference model must agree bit for bit.

### 12. Pinned versions and licences

Crypto crates are `=`-pinned (`curve25519-dalek =4.1.3`, …); `cargo deny` allows only MIT, Apache-2.0
(and its LLVM exception, DB-71), BSD-3-Clause, Unicode-3.0, and denies unknown registries and git
sources [CODE: deny.toml]. CI also checks there is exactly one copy of each crypto crate
(`cargo tree -d`) [CODE: scripts/ci.sh].

### 13. The freeze rule (F-1, F-2, F-6)

Each finished part's files are hashed into `freeze/PART-N.sha256`: Part 1 81 files, Part 2 250,
Part 3 342, Part 4 191 [RUN: `wc -l freeze/*.sha256`]. The Fast CI tier runs `sha256sum -c` on all four
(`freeze-guard`), so any edit to a frozen file fails CI [CODE: scripts/ci.sh]. The only way to change a
frozen part is an erratum: failing regression test first, smallest fix, re-run later gates, new tag
`part-N-frozen-eK` (E-1 and E-2 did this) [DOC: CLAUDE.md §4.1; ERRATA.md].

### 14. Python quality

ruff (rules E, F, W, I, B, UP, SIM, RUF, N, PT; line length 100) and `mypy --strict` over `python/`
[CODE: pyproject.toml `[tool.ruff]`, `[tool.mypy]`]. `import-linter` and `mutmut` are installed dev
tools; no gate uses `mutmut` [DOC: _notes/testing.md §6].

## Everyday analogy

*Analogy:* These rules are like a hospital's surgical checklist: boring, mechanical, and the reason
mistakes are rare. *Where it stops:* a checklist catches known failure modes; it does not replace an
independent reviewer (hence fair testing, [10](10_testing_methodology.md)).

## Key points to remember

- Workspace-wide lints forbid `unsafe` (except one SIMD file), `unwrap`, `expect`, `panic`, unchecked indexing.
- Errors are typed and carry no caller data.
- The core is pure: no I/O, clock or randomness.
- Tests carry `SR-…` IDs and declare their oracle.
- Frozen parts are protected by SHA-256 manifests checked in CI.

## Check your understanding

1. *Why is `unwrap()` denied in library code?* — It panics; the engine must return typed errors.
2. *How does CI notice an edit to Part 1?* — `freeze-guard` runs `sha256sum -c freeze/PART-1.sha256`.
3. *Why must the core have no clock?* — Routing must depend only on the vector and state.
4. *What does `#[spec("SR-17-2")]` do at run time?* — Nothing; it is a label read by the trace tool.
5. *Why pin `curve25519-dalek` exactly?* — The verifier and engine must use the same audited version, and golden vectors depend on it.
