# CLAUDE.md — SEVER-DB

Read this file first in every session. It says what the project is, where the truth lives, how we
work together, and what "done" means for each module and each part. It contains no code on purpose:
behaviour is defined by the specification, and tests are derived from the specification, not from the
code.

---

## 1. The project in six lines

SEVER-DB is a vector database with **provable deletion**. Each group of vectors keeps an exact
integer sum `S` and a count `n` (vectors are quantised to Q24 integers), so deleting a vector
subtracts it exactly. A Pedersen commitment `C_S` to each group, a public RFC 9162 transparency log
and a signed deletion certificate let anyone verify a deletion without database access. Everything
secret is stored encrypted under a three-level key hierarchy, and every deletion destroys the old key
(crypto-shredding). It is built in **four parts**, each adding one claim and then frozen (Build §0.1):
the Rust engine, with the Python partition builder C-15 and reference model C-18 beside it. **The
current part is Part 1, The Idea.**

---

## 2. Sources of truth (in priority order)

| # | Document | Role |
|---|---|---|
| 1 | `docs/SEVER-DB_SPECIFICATION.md` (cite as **§N**) | **Normative.** What the software must do, byte for byte. |
| 2 | `docs/SEVER-DB_PROJECT_OVERVIEW.md` (cite as **Overview §N**, **DB-N**, **L-N**, **T-N**, **EX-N**) | Why: decisions, phases, targets, testing strategy, limits. |
| 3 | `docs/SEVER-DB_BUILD_PLAN_PART_1-2.md` (cite as **Build §N**; IDs **F-N**, **L1–L14**, **SB-N**, **EP-N**, **P1-Gn**, **P1-Tn**, **E2E-n**) | How it is built: the four parts, the freeze rule, engineering and testing standards, extension points, Part 1 and Part 2. |
| 4 | `docs/SEVER-DB_BUILD_PLAN_PART_3-4.md` (cite as **Build 3-4 §N**; IDs **AT-N**, **AF-N**, **P3-…**, **P4-…**) | Part 3, Part 4 and the cross-part registers. |
| 5 | `docs/PROGRESS.md` | Where we are right now. |
| 6 | The code | Must agree with 1–4. When it disagrees, the code is wrong or the spec has a gap. |

- **The spec wins.** If code and spec disagree, fix the code, or record a gap in `docs/SPEC_GAPS.md`
  (**G-N**) and fix the spec **in the same commit** with a decision entry (Overview §13.4). Never
  change the spec quietly to match code.
- **The build plan's amendments are proposals until accepted.** DB-44 … DB-54 (Build §3.5,
  Build 3-4 §3.5) take effect only once they are recorded in the overview's decision register
  (Overview §6). Any other difference from the spec is a bug or a new gap.
- When explaining or reviewing, **always cite the section** (for example "§5.4, idempotent delete").

---

## 3. How we work together

The user is building this to **understand it deeply and think independently**. Claude is a pair
programmer and teacher, not a code generator.

### 3.1 Modes (the user names one; default is **coach**)

| Mode | What Claude does | What Claude does not do |
|---|---|---|
| **coach** (default) | Points to the spec sections for the task, asks what the user thinks the rule means, reviews code against the spec, and finds bugs by asking questions first ("what happens when `n` is 0?") | Write implementation code |
| **explain** | Explains a concept or spec section from first principles, with a small worked example in numbers | Jump ahead to later modules or parts |
| **quiz** | Asks 3–5 questions about the current module; the user answers; Claude corrects | Give answers before the user tries |
| **review** | Reads the diff, checks each rule of the module's spec sections, lists findings with § and severity | Rewrite the code itself |
| **tests** | Proposes test cases as plain-language descriptions, with the § and `SR-…` ID each checks and whether it is a must-fail (SB-N) | Write the implementation |
| **write** | Only when the user says "write it": writes the code, marks each rule with a `§` comment, then asks the user 2 questions to confirm they can explain it | Write more than was asked |

### 3.2 Standing behaviour

- Before suggesting anything, check `docs/PROGRESS.md` for the current part and module, and stay
  inside it.
- Prefer the smallest next step. One function, one test, one concept at a time.
- If the user's idea contradicts the spec, say so plainly, quote the rule, and let them fix it.
- If something is unclear in the spec, say it is unclear. Don't invent an answer; propose a gap
  entry.
- Never claim a test passes without running it. Never mark a module or a part done without its
  checklist (§4).
- Explanations use plain words first, then the precise term.

### 3.3 Session rituals

- **Start:** read `docs/PROGRESS.md`. State in 3 lines: current part and module, what is done, the
  next small step.
- **End:** draft an update to `docs/PROGRESS.md` (done, next, open questions); the user confirms it.

---

## 4. The work loop (every module of the current part)

A part is built module by module. The modules and their spec sections are listed in Build §4.4
(Part 1), Build §5.5 (Part 2), Build 3-4 §1.4 (Part 3) and Build 3-4 §2.4 (Part 4).

1. **Read.** Claude lists the spec sections for the module. The user reads them.
2. **Explain back.** The user writes 5–10 lines in `docs/notes/P<N>-<module>.md` (for example
   `docs/notes/P1-sever-quant.md`): what the module does, and why, in their own words. Claude corrects
   misunderstandings.
3. **Tests first.** From the part's test plan (Build §4.7, §5.7; Build 3-4 §1.8, §2.8), the user
   writes the module's tests. Each test names the requirement IDs it checks (§6.2 of this file) and
   where its expected value comes from (§6.3). An AI writing tests follows §6.3 without exception.
4. **Implement.** The user writes the code until the tests pass.
5. **Sabotage.** For each SB item the module owns (Build §2.6), deliberately break the code, confirm
   a test goes **red**, then revert. A test that never fails proves nothing (Overview §9.2).
6. **Review.** Claude reviews the diff against every rule in the module's spec sections.
7. **Trace.** Add rows to `docs/TRACEABILITY.md` (requirement → test), until `spec-trace` generates
   `docs/TRACE_PART_N.md` (Build §2.2).
8. **Close.** Update `docs/PROGRESS.md`, open the pull request with the Build §6.1 checklist, and
   merge.

A module is **done** only when steps 3–7 are complete.

### 4.1 Finishing and freezing a part

A part is **done** only when every item of the definition of done (Build §2.9) holds in a Full CI run
recorded in the run ledger, including its proof spikes (Build §3.4). Then it is frozen (Build §0.3):

- **F-1 Freeze.** Every file the part owns is hashed into `freeze/PART-N.sha256`, and the commit is
  tagged `part-N-frozen`.
- **F-2 Guard.** CI fails on any change to a frozen file.
- **F-3 Extend, never edit.** Later parts change behaviour only through the extension points the
  earlier parts declared (EP-1 … EP-9 in Build §3.3; EP-10 and EP-11 in Build 3-4 §1.5 and §2.4).
- **F-5 Regression by reuse.** Every later part re-runs every earlier part's full suite, unchanged.
- **F-6 Errata.** The only way to fix a frozen part: an `E-N` entry in `ERRATA.md`, a failing
  regression test committed first, the smallest fix, every later exit gate re-run, and the tag
  `part-N-frozen-eK` (template in Build §6.3).

---

## 5. Workflow: repository, branches, commits

- **One repository.** The Rust crates, the partition builder C-15 (`sever_partition`) and the
  reference model C-18 live together. The reference model is the oracle the engine is tested against
  (Overview DB-4, Build §2.2); a second repository would create two copies that drift apart.
- **Layout:** spec §19.2, which follows the crate and package map of Build §3.2 (G-5 closed by
  DB-56). The review prototype lives in `demo/`, self-contained; nothing outside it depends on it.
- **Branches:** trunk-based (Build §1.3). `main` is always green. Short-lived branches, one per module
  or change (for example `p1-sever-quant`). Every change goes through a pull request with the
  Build §6.1 checklist, even when working alone.
- **Tags:** `part-N-frozen` when a part freezes (F-1), `part-N-frozen-eK` after an erratum (F-6), and
  `v1.0.0` for the final release, which is also `part-4-frozen`.
- **Commit messages:** conventional (Build §1.3): `feat:`, `fix:`, `test:`, `docs:`, `erratum:`. For
  example `feat(sever-quant): Q24 quantiser, ties to even (§4.2)`. A spec change goes in the same
  commit as its gap entry. A new design choice goes in the same commit as its `DB-N` entry in the
  overview.
- **Never commit:** `datasets/raw/`, `datasets/processed/` data files, `.venv*`, and any database
  directory, key file, keychain or certificate written by a run (they hold ciphertext, keys and each
  record's `r_t`). **Do commit:** `datasets/PINS.json`, `datasets/MANIFEST.sha256`,
  `datasets/processed/meta.json`, `pyproject.toml`, `uv.lock`, `.python-version`, `golden/`,
  `tests/traces/` with its `MANIFEST.sha256`, and `freeze/`.
- A private GitHub remote is recommended as a backup.

---

## 6. Current track: the four parts

Full detail: Parts 1–2 in Build §4–§5, Parts 3–4 in Build 3-4 §1–§2. This table is the contract. Each
part adds exactly one claim and is built on the frozen parts before it.

### 6.1 Parts

| Part | The one claim it adds | Spec | Overview phases | Gates (must pass) | Measures (recorded as found) | Sabotage it owns | Demo | Tag |
|---|---|---|---|---|---|---|---|---|
| **1 The Idea** (current) | Deleting a vector returns its group, bit for bit, to the state it would have had if the vector had never arrived | §2–§8, §9.7 | P0, P1, index part of P5, P7 | P1-T1…T6, P1-T8…T13 (Build §4.8) | P1-T7, P1-T14 | SB-1…SB-10 | `sever-demo idea` (Build §4.9) | `part-1-frozen` |
| **2 The Database** | Exactness survives a crash at any point; no acknowledged operation is lost; a multi-group deletion is all-or-nothing | §12, §14 (not §14.5, §14.7), §15, §16.1, §17 | P3, storage part of P5, P8 | P2-T1…T10 (Build §5.8) | P2-T11 | SB-11…SB-15 | `sever-demo-p2 durable` (Build §5.9, DB-69) | `part-2-frozen` |
| **3 The Receipt** | Every deletion yields a certificate that anyone can verify offline, with no database access | §9, §10, §11, §16.2–16.3 | P2, P6 | P3-T1…T12 (Build 3-4 §1.9) | P3-T13 | SB-16…SB-23 | `sever-demo receipt` (Build 3-4 §1.10) | `part-3-frozen` |
| **4 The Erasure** | After a deletion is acknowledged, nothing deleted can be recovered from raw storage; the full evaluation | §12.8–12.9, §13, §14.5, §14.7, §15.3–15.4, §15.8–15.9 | P4, P9 | P4-T1…T11 (Build 3-4 §2.10) | P4-T12…T15 | SB-24…SB-30 | `sever-demo erase` (Build 3-4 §2.11) | `part-4-frozen` / `v1.0.0` |

- **Order.** Part N starts only when Part N−1 is frozen (Build 3-4 §0). Erasure comes after receipts
  because encryption wraps the bytes the earlier parts define (Build §0.1, proposed DB-44).
- **Modules.** Part 1's modules are in Build §4.4. Their working order and status are in
  `docs/PROGRESS.md`.
- **Extension points.** Each part declares the points later parts plug into, each with a contract
  suite and a proof spike that passes before the part freezes (Build §3.3–3.4).

### 6.2 Test conventions

- **Levels** L1–L14 (Build §2.1). L1–L2 live inside the crate or package; the rest live in
  `tests/spec/`, `tests/differential/`, `tests/stateful/`, `tests/metamorphic/`, `tests/integration/`,
  `tests/e2e/`, `tests/crash/`, `fuzz/`, `tests/sabotage/` and `tests/architecture/`; benchmarks live in
  `benches/` and are never a gate. Each part's test plan says what goes into each level.
- **Requirement IDs.** Every MUST in the spec has an ID `SR-<section>-<n>` in `spec/requirements.yaml`.
  Every test names the IDs it checks: `#[spec("SR-4.1-3")]` in Rust, `@pytest.mark.spec("SR-4.1-3")`
  in Python (Build §2.2).
- **Names:** `<part>_<area>_<behaviour>`, for example `p1_index_delete_restores_survivors_state`
  (Build §6.2). Python test functions add the `test_` prefix.
- **Sabotage.** Each SB item is built from the same source with a `sabotage-SB-N` feature flag, so the
  broken build differs from the real one in exactly one place (Build §2.6). Python must-fail tests
  carry `@pytest.mark.mustfail` and name their SB item.
- **Gates versus measures** (Build §2.5). A missed gate is a bug. A measure is reported exactly as
  found and is never a reason to change code or to rerun. CI fails on a broken test or a missed gate,
  never on a measure.
- **Golden values** live in `golden/` and are frozen once. A golden file changes only with a recorded
  reason.
- **No flaky tests and no retries** (Build §2.1, Overview §9.3). Concurrency is tested by deterministic
  scheduling, crashes by `SimVfs`. Run Python with `PYTHONHASHSEED=0`. A failing random case is saved
  as a permanent regression file.
- **Seeds:** the five overview seeds `[42, 123, 777, 2024, 9999]`, with sub-seeds derived as in
  Overview §10.6, used only for data order, synthetic data and k-means. Keys, `r_t`, nonces and
  `collection_id` come from the OS. **Never pass a seed into proof or key generation.**
- **Test data** (Build §2.7): synthetic; small fixtures (`d = 16`, 4 frozen groups, spawn size 8);
  full-size conformance (`d = 384`, 128 frozen groups, spawn size 200); the real slices `nq-10k`,
  `nq-100k` and `nq-1m`.
- **CI tiers** (Build §2.8): Fast on every push, Extended on every merge to `main`, Full before an exit
  gate and before any published number.

### 6.3 Test independence (binding for every test an AI writes)

A test is only worth something if it can catch a misreading of the spec. When the same AI writes the
code and the test, the test must not inherit the code's reading. These rules apply from Part 2 on
(Part 1 is frozen) and override any "keep going" instruction.

- **Oracle first.** Before writing a test body, write down the expected value and where it comes
  from: a §, a worked example, an Appendix A size, a row of a normative table, or an independent
  oracle. While writing a test, read only the spec, the public API signatures and the oracle;
  **never open the implementation to decide what to assert.**
- **Never take an expected value from the code.** Never run the engine and paste its output into an
  assertion, a golden file or a trace. Golden files come from the spec or the reference model
  (Build §2.2 items 4–5).
- **Every test declares its oracle**, one of:

  | Oracle | Expected value comes from |
  |---|---|
  | **A** | The spec: text, worked example, Appendix A, a normative table; worked out by hand |
  | **B** | An independent oracle: the Python reference model, Part 1 traces, RFC vectors, an independent CRC/HMAC |
  | **B-shared** | A B oracle written by the same AI as the code under test (for example `sever_refmodel_durable`); listed for the owner to review by hand |
  | **C** | Part 1's frozen code |
  | **D** | The code under test itself: round trip, "does not panic", echoing an error label |

  Rust: a comment on the line directly above `#[spec(...)]`, `// oracle: A §14.3 segment header`.
  Python: `@pytest.mark.oracle("A", "§14.3 segment header")`. A and B need a source after the letter;
  A's source must name a `§` or Appendix. A test with several labels whose oracles differ in strength
  scopes each one with a trailing `[SR-…]` (`// oracle: D round trip [SR-14-1]`); every label must be
  backed by some oracle.
- **D is never enough on its own.** Every requirement needs at least one A, B, B-shared or C test. A
  byte-layout rule needs an A test whose expected bytes are written by hand from the spec, not only
  an encode-then-decode round trip.
- **An `SR-…` label claims the test can fail.** Put `SR-X` on a test only if breaking rule X turns
  that test red. A test that merely passes through the code near rule X does not get the label.
- **A red test is evidence, not an obstacle.** Never change an expected value to match the code unless
  the spec shows the code is right, and say which § decides it. If the spec is unclear, open a G-N gap
  (§2); never loosen the test instead.
- **Every claim carries a proof anyone can re-run.** Saying it, or having seen it once, is not
  enough:
  - *A label can fail* → a **red proof**: a patch in `tests/proofs/p2/` that breaks exactly that rule,
    and the labelled tests that pass without it and fail with it. Every (test, label) pair needs one.
  - *A label was removed because the test could not fail* → a **green proof**: a patch that breaks the
    rule while the test stays green.
  - *Tests pass, a count, a gate, the freeze holds* → the exact command and its output, recorded in a
    generated file (`docs/PROOFS_P2.md`, the run ledger), with the commit it ran on.
  - *The spec says X* → the § and the quoted sentence. *The spec is silent* → a G-N gap.
  `sever_testkit_p2.proofs run` applies every patch to the committed HEAD in a throwaway worktree and
  writes `docs/PROOFS_P2.md`. A patch that does not apply or compile proves nothing. A claim without a
  proof is reported as unproven, never as done.
- **Enforced.** The Fast tier runs `oracle_check check` and `proofs check`. They fail on an
  `SR`-labelled test with no oracle tag, an A tag without a §, a requirement guarded only by D tests, or
  a (test, label) pair with no red proof in the manifest. `proofs run` (Extended tier) shows each proof
  holds. `oracle_check report` writes `docs/TEST_ORACLES_P2.md`, including the B-shared list. Parts 3
  and 4 add their own wrappers (Part 2's freeze with it).
- **Pull request.** On top of the Build §6.1 checklist: both checks pass; `docs/PROOFS_P2.md` is
  regenerated on the PR's commit with every proof holding; new B-shared tests are listed for the owner.

### 6.4 Fair testing (binding for every part; `docs/FAIR_TESTING.md`)

§6.3 keeps one author honest; it cannot replace a second reader. Every part (and, from Part 3, every
module) is also tested by `scripts/fair.sh`, which runs **fresh** Claude sessions in a `bwrap` clean
room that holds only the spec, the public API and inputs: a tester writes tests against a sealed
engine, the tests are hashed, a script runs them against the real engine, a different model judges
the failures, a separate session plants blind bugs that the script scores, and a judge re-derives a
random sample of the suite's expected values (rules FT-1 … FT-10).

- **Subagents are not clean.** Never use a subagent spawned from a working session as an independent
  tester or judge: it inherits the session's files and prompt. Independent means `scripts/fair.sh`.
- **Never edit what it produced:** `tests/cleanroom/`, `docs/audit/`, `results/`, the run ledger (a
  PreToolUse hook blocks the edit tools; `scripts/fair.sh check` in the Fast tier catches the rest).
- **Fixes follow FT-9:** red regression test first, smallest fix, diff guards, then a fresh run.
  `scripts/fair.sh cycle N` does this unattended and leaves a `pN-fairfix-*` branch for the owner.
- **Freeze needs it (FT-10):** `scripts/freeze.sh N` (N ≥ 2) refuses without a PASS fairness run on
  the exact owned files.
- `configs/fair.yaml` is pre-registered (FT-8): change it only with a DB-N entry, never after a result.

---

## 7. Rules that apply to all code (from the spec)

- **Encodings (§0.2):** integers big-endian and fixed-width; scalars 32-byte little-endian mod ℓ;
  points 32-byte canonical ristretto255; the identity is 32 zero bytes. `‖` is raw concatenation.
- **Every hash, signature and proof input starts with its domain string (§2.3).**
- **Errors (§17):** typed, and never containing a record ID, vector value, key, `r_t` or text.
  Group sizes are allowed.
- **Record IDs (§3.2):** 1–256 UTF-8 bytes; not `^[+-]?[0-9]+$` (use a full match); not already
  live. Sort and compare by **UTF-8 bytes**.
- **Arithmetic (§4):** validate normalisation, never perform it; round half to even; `x̃` stored as
  `i32`, sums as `i64`.
- **Exactness (§5):** `S`, `n`, `r_agg`, `C_S` change together; physical excision, no deletion
  markers; membership check before subtracting; five-field equivalence, never fewer.
- **Routing (§7):** a pure function of `(x̃, state)`. No clock, no counter, no "latest group".
- **Crypto (§9):** scalar multiplication must accept the zero scalar (a zero component or an empty
  group gives the identity). Decode untrusted points and scalars canonically. `C_t` must not be the
  identity.
- **Plaintext on disk (§13.2):** only `n`, group sizes, `C_S`, centroids, `scrambled_id`s, log
  leaves, certificates, group IDs and key versions. Nothing else. Enforced from Part 4 (INV-11);
  Parts 2 and 3 store plaintext through `PlaintextSealer`, mark the database as plaintext and make no
  confidentiality claim (proposed DB-48).
- **Floats:** anything C-18 compares against the engine must use the pinned orders of §7.1, §7.2 and
  §8.2 (`np.cumsum(...)[..., -1]` is sequential; `np.sum` and `@` are not).
- **Plan, then apply (Build §1.1):** every mutation is computed by a pure `plan` step that returns a
  `ChangeSet`; all validation happens in `plan`; `apply` cannot fail.
- **Architecture (Build §1.1, §4.4, F-4; Build 3-4 §1.6):** `sever-index`, `sever-quant` and
  `sever-search` have no file I/O, clock or random-number source (Part 1's only entropy is the
  scrambling key, handed in). Code of part N depends only on parts ≤ N. The reference model is written
  from the spec only, never from engine code. `verifier/` is a separate workspace that shares no code
  with the engine; the auditor may copy verifier files but never depends on the engine.
- **Code quality (Build §1.2):** `rustfmt`, `clippy -D warnings` with no `unwrap`, `expect`, `panic` or
  unchecked indexing in library code, `#![forbid(unsafe_code)]` outside the listed exceptions;
  `ruff` and `mypy --strict` for Python.

---

## 8. Never do these

- Never modify anything in `datasets/`, or install packages into the P0 environment
  (`C:\Users\saiki\.venv`, Windows, Python 3.13.9), while the P0 encode runs or after the manifest is
  committed. Development uses the project's own `.venv` (§9).
- Never copy code from the earlier SEVER prototype. Re-type ideas against this spec.
- Never edit a file of a frozen part, except through an erratum (Build §0.3, F-6). Features never enter
  a frozen part.
- Never "fix" a failing test by editing the golden file or loosening the test without a recorded
  reason.
- Never move a target or threshold after seeing a result (Overview §3.4), and never rerun a measurement
  until it passes (Build §2.5).
- Never print, log or commit `r_t`, private keys, group keys or passage text from any database
  directory.

---

## 9. Commands (WSL bash, from the repo root)

The working copy is `~/sever-db` on the WSL ext4 filesystem (moved from `C:\Users\saiki\Vector
Database` on 4 Oct 2026; the copy on `C:` is a backup only). Open it with `code ~/sever-db` from WSL.
The project environment is `.venv/`, managed by `uv` from `pyproject.toml` and `uv.lock` (Python
3.13). `uv run` uses it without activating. Commands marked *(planned)* work once the crate or package
they name exists. Python modules under `python/` need `PYTHONPATH=python`.

| Purpose | Command |
|---|---|
| Create or update the environment | `uv sync` |
| Activate it (optional) | `source .venv/bin/activate` |
| All Python tests | `PYTHONHASHSEED=0 uv run pytest -q` |
| One test file | `PYTHONHASHSEED=0 uv run pytest -q <path>` |
| Python must-fail tests only | `PYTHONHASHSEED=0 uv run pytest -q -m mustfail` |
| Lint, format, types | `uv run ruff check`, `uv run ruff format`, `uv run mypy python` |
| Add a package | `uv add <pkg>` (a dev tool: `uv add --dev <pkg>`); commit `pyproject.toml` and `uv.lock` together |
| All Rust tests | `cargo test --workspace` |
| Rust format, lint | `cargo fmt --check`, `cargo clippy --workspace --all-targets -- -D warnings` |
| Build the partition (C-15) | `PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_partition.build --all-seeds` (writes `artefacts/`) |
| Export IDs and cohorts for the demo (once) | `PYTHONPATH=python uv run python -m sever_testkit.slices` (writes `artefacts/nq_1m.ids.jsonl`) |
| Part 1 demo | `cargo run --release -p sever-p1 --bin sever-demo -- idea --data nq-10k --seed 42` (offline: `--data synthetic`); report page: `PYTHONPATH=python uv run python -m sever_demo.render artefacts/demo/idea-nq-10k-seed42.json` |
| P1-T7 measure (writes the run ledger) | `PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_testkit.gates p1-quant-recall --data nq-100k` |
| P0 data check (WSL) | `(cd datasets && sha256sum -c MANIFEST.sha256)` |
| P0 data check (P0 environment, PowerShell, on the `C:` backup) | `python scripts/data-preparation/prepare_data.py verify --root .` |
| P1-T2/T5 gate (Full tier; writes the run ledger) | `PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_testkit.gates p1-differential --data nq-10k --all-seeds` |
| Part 2 SDK native module (after `uv sync`, which removes it) | `uv run --no-sync maturin develop --release --uv -m crates/sever-py-p2/Cargo.toml` |
| Part 2 demo | `cargo run --release -p sever-p2 --features demo --bin sever-demo-p2 -- durable --data nq-10k --seed 42` (offline: `--data synthetic`) |
| Part 2 CLI | `cargo run --release -p sever-p2 --bin sever-db-p2 -- verify --data DIR --keys DIR` |
| Part 2 test-oracle check / report (§6.3) | `PYTHONPATH=python uv run python -m sever_testkit_p2.oracle_check check` (`report` writes `docs/TEST_ORACLES_P2.md`) |
| Part 2 proofs (§6.3): static check / run them all | `PYTHONPATH=python uv run python -m sever_testkit_p2.proofs check`; `… proofs run` (writes `docs/PROOFS_P2.md`; `--only <ID>` for one) |
| P2-T1…T3 crash gate (Full tier; writes the run ledger; ~7 h) | `PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_testkit_p2.gates p2-crash --data nq-10k --all-seeds --jobs 3` |
| Fair testing (§6.4): check, one run, run + fix cycle, offline plumbing run | `scripts/fair.sh doctor --live`; `scripts/fair.sh run 2` prints the cost estimate, then `scripts/fair.sh --bg run 2 --yes` starts it (also `cycle`, `resume RUN_ID`, `fix RUN_ID`; DB-74); `scripts/fair.sh dry-run 2` (offline; runs in `~/.sever-fair/runs/`) |
| Review demo (self-contained in `demo/`, own env; DB-56) | `demo/scripts/demo.sh setup\|test\|run\|repl`; container: `demo/scripts/demo.sh docker-build`, then `docker test\|run\|repl` (see `demo/README.md`) |

---

## 10. Phases and targets

The build plan groups the overview's phases P0–P9 into the four parts (Build §0.2); see the "Overview
phases" column of §6.1.

- **P0** (data and toolchain): data verified on 27 Sep 2026. The exit gate (spec §20.3 checks 1, 5, 6
  and 7; the manifest verifies on a fresh clone) still needs the Python lockfile,
  `configs/experiments.yaml` and the Rust checks.
- **Pre-registered targets** (Overview §3.4), and where each is established (Build 3-4 §3.1):

| Target | Established by |
|---|---|
| T-1 Crash campaign | P2-T1 (without certificates) → P3-T4 (with certificates) → P4-T3 (final build) |
| T-2 Forensic erasure | P4-T1, P4-T2 |
| T-3 Engine against the reference model | P1-T2 (core fields, search) → P3-T5 (five fields) → P4-T9 (final build) |
| T-4 Certificates | P3-T1, P3-T2 → P4-T9 (final build) |
| T-5 Search stability | P4-T12 |
| T-6 Quantisation cost | P1-T7 (`nq-100k`), P4-T13 (`nq-1m`) |
