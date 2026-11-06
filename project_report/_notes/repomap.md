# Repository map

Written 2026-11-01, HEAD 4a03951 (branch bughunt-2026-11). Read-only inspection (ls, git ls-files, head, grep). `[CODE]` = seen in source/config, `[DOC]` = a claim in a document, `[INFERRED]` = my reading, `[NOT FOUND]`.
Sizes from the earlier inventory [DOC: project_report/_notes/inventory.md]: 1,217 tracked files; Rust 239 files / 59,523 lines; Python 203 / 37,113.

## 1. Top-level folders

Tracked (from `git ls-files | cut -d/ -f1`): `.cargo .claude .github audit clippy.toml configs crates datasets deny.toml docs freeze fuzz fuzz-p2 fuzz-p3 fuzz-p4 golden parts python results rust-toolchain.toml rustfmt.toml scripts spec spikes studio tests verifier` plus root files `.gitignore .python-version CLAUDE.md Cargo.lock Cargo.toml ERRATA.md README.md pyproject.toml uv.lock`.

| Folder | Plain purpose | Git state |
|---|---|---|
| `crates/` | The Rust workspace: 35 crates (section 2). The database and its test tooling | tracked |
| `verifier/` | Separate Rust workspace: `sever-verify`, checks one deletion certificate offline; shares no code with the engine [CODE: verifier/Cargo.toml, src/{cert,merkle,posk,xmd,gens,anchors,verify,main}.rs] | tracked; `verifier/target`, `verifier/fuzz/{corpus,artifacts,target}` ignored |
| `audit/` | Separate Rust workspace: `sever-audit`, audits a log export plus held certificates (own copy of the crypto files) | tracked; `audit/target` etc. ignored |
| `python/` | The Python packages (section 3): SDK wrappers, partition builder C-15, reference models C-18, testkits, fair-testing system | tracked |
| `studio/` | SEVER-DB Studio, PySide6 desktop demo with its own venv (DB-106); `studio/work/` (databases, keys, receipts, model) is ignored | tracked except work/ |
| `tests/` | Cross-cutting tests and proofs (section 7) | tracked |
| `docs/` | Spec, overview, build plans, progress, generated evidence (section 4) | tracked |
| `scripts/` | CI, fair testing, freeze, index generator, HPC run kit, bug-hunt helpers (section 5) | tracked |
| `configs/` | `experiments.yaml` (pre-registered seeds/datasets, fixed 27 Sep 2026, "never changed afterwards") and `fair.yaml` (pre-registered fair-testing settings: tester opus, judge sonnet, planter sonnet, fixer opus; FT-8) [CODE: head of each] | tracked |
| `spec/` | `requirements.yaml` (every MUST as `SR-<section>-<n>`), `registers_p3.yaml`, `registers_p4.yaml`, `rfc/` (rfc8032, rfc8452, rfc9162, rfc9380, rfc9496 text) | tracked |
| `golden/` | Frozen golden vectors from the spec/reference model/RFCs: `p1_*` (partition .svp, fixture vectors, quant half-steps, scramble, core blob, spawn id), `p2_oracle_small.jsonl`, `p3_*` (generators, commitments, certificates, merkle_7, posk, attacks, audit, full blob, RFC 8032/9380/9496 vectors), `p4_rfc8452_aes256gcmsiv.json` | tracked (`!golden/**` un-ignores) |
| `freeze/` | `PART-1..4.sha256`: hashes of every file each frozen part owns (F-1) | tracked |
| `parts/` | One generated page per part (code, tests, results, reports) | tracked, GENERATED |
| `results/` | 94 JSON result files from gate/measure/fair runs (e.g. `p3-crash-nq-10k-*.json`, `fair-*-p4-*.json`) | tracked; protected from edits by hook [DOC: CLAUDE.md 6.4] |
| `fuzz/ fuzz-p2/ fuzz-p3/ fuzz-p4/` | cargo-fuzz harnesses per part (own Cargo workspace): P1 `artefact_parse`, `blob_parse`; P2 `wal_record`, `manifest`, `checkpoint_file`, `store_record`; P3 `certificate`, `log_record`, `witnessed`, `placement`; P4 `key_slot`, `wrapped_value`, `bucket_block`, `envelope`, `scan_targets` [CODE: Cargo.toml [[bin]] lists]. Committed `seeds/`; `corpus/ artifacts/ target/` ignored | tracked (small) |
| `spikes/p3-proof/` | Throwaway proof spike before Part 3 froze (AEAD sealer + key-rotation participant beside LogParticipant); only output is a ledger entry [CODE: spikes/p3-proof/Cargo.toml:1-4] | tracked; its target ignored |
| `datasets/` | Pinned data: tracked `PINS.json`, `MANIFEST.sha256`, `processed/meta.json` (3 files); ignored `raw/` (nq, nq_qrels, sciq) and `processed/` (nq_1m, nq_queries, sciq_reference) [CODE: .gitignore; ls] | mostly ignored |
| `.cargo/` | `config.toml`: sets `PYO3_PYTHON=.venv/bin/python` (relative) for PyO3 builds | tracked |
| `.claude/` | `settings.json`: PreToolUse hook on Edit/Write/MultiEdit/NotebookEdit runs `scripts/hooks/guard-sealed.sh` (blocks edits to sealed/generated files) [CODE: .claude/settings.json] | tracked |
| `.github/workflows/ci.yml` | CI: on push/PR, ubuntu-24.04, rust 1.98.1, uv, `uv sync --locked`, `scripts/ci.sh fast` (Fast tier only; Full gates run locally because the data is not in git) [CODE] | tracked |
| root config | `rust-toolchain.toml` (1.98.1), `rustfmt.toml`, `clippy.toml`, `deny.toml` (cargo-deny), `Cargo.toml/lock` workspace, `pyproject.toml/uv.lock/.python-version` (3.13) | tracked |
| `ERRATA.md` | Fixes to frozen parts (E-N); Part 2 has E-1, E-2 [DOC: README.md] | tracked |

Untracked / generated / ignored folders that exist on disk:
| Folder | What | Ignored? |
|---|---|---|
| `target/` | Cargo build output (19 GB here); also `target/demo-sb24` for the SB-24 demo | `/target/` ignored |
| `.venv/` | Project Python env made by `uv sync` | ignored (`.venv/`, `.venv-*/`) |
| `artefacts/` | Built partition artefacts `partition-seed{42,123,777,2024,9999}.{svp,json}`, `nq_1m.ids.jsonl`, `demo/` outputs | `/artefacts/` ignored |
| `traces/` | Reference-model trace files; hashes committed in `tests/traces/MANIFEST.sha256` [DOC: CLAUDE.md 5] (note: `tests/traces/` was not seen in `ls tests`; [NOT FOUND] on disk this session) | `/traces/` ignored |
| `jobs/` | Crash-safe job queue dirs `queue running done failed logs` used by `scripts/jobq.sh` | `/jobs/` ignored |
| `project_report/` | This report work (`_notes`, `background`, `research`) | untracked (git status `??`) |
| `src/practise-rust/` | personal practice code, ignored by name | ignored, not present |
Other ignore rules [CODE: .gitignore]: `__pycache__/ *.pyc .pytest_cache/ .benchmarks/ _selftest/ *.cert *.key studio/work/ .coverage .DS_Store .vscode/ .idea/`; cargo-fuzz corpora/artifacts/targets for every fuzz dir. Also ignored: `datasets/raw/`, `datasets/processed/**` except `meta.json` and `*_shards/`.

## 2. Rust crates (crates/, 35 + README.md)

Source: `crates/README.md` [DOC] and each Cargo.toml `description` [CODE]. Rule: code of part N depends only on parts <= N (`tests/architecture`) [DOC: crates/README.md]. Part 1 and 2 are frozen; Parts 3 and 4 frozen at v1.0.0 per latest commits [DOC: git log: "freeze: Part 4 ... v1.0.0"].

| Crate | Part | Purpose |
|---|---|---|
| sever-types | 1 | Record/group/collection IDs, constants, the spec-17 `Error` enum (all 13 variants), secret buffers (EP-4) |
| sever-quant | 1 | Normalisation check, Q24 quantise/dequantise (4.1-4.3) |
| sever-partition | 1 | Parser/validator for partition artefact `partition.svp` (6.3) |
| sever-index | 1 | Groups, exact integer accumulators S/n, routing, holding area, flush, plan/apply (5, 7, 9.7); has SB-1..5,7,8 sabotage features |
| sever-search | 1 | IVF-flat search, pinned 8-lane kernel, scalar + AVX2 (8) |
| sever-p1 | 1 | Part 1 composition root, ghost baselines, `sever-demo idea` |
| sever-spec | 1 tooling | `#[spec("SR-...")]` attribute read by spec-trace |
| sever-tracekit | 1 tooling | Replays reference-model traces through the engine; bin `sever-tracekit` |
| sever-vfs | 2 | All file operations behind a `Vfs` trait (EP-5): `PosixVfs` and crash-simulating `SimVfs` (12.2) |
| sever-format | 2 | Byte-exact checksummed storage formats with strict parsers (14); crc32c |
| sever-wal | 2 | Write-ahead log: segments, txns, torn tails, replay (12.3) |
| sever-appendstore | 2 | Append-only record stores, the passage payload store (EP-8, 14.8) |
| sever-checkpoint | 2 | Atomic storage checkpoints, MANIFEST install (12.4, 15.6) |
| sever-txn | 2 | Sealer/participant/clock traits (EP-6/7/9), change sets, commit protocol (15) |
| sever-engine | 2 | The storage engine: collections, API, recovery with invariant check (16.1) |
| sever-p2 | 2 | Part 2 root `Engine<NoExtension, PlaintextSealer>`, bins `sever-db-p2`, `sever-demo-p2` |
| sever-py-p2 | 2 | PyO3 module `sever_db_p2_native` |
| sever-crashkit | 2 tooling | Crash campaign driver on SimVfs (EX-1); bin `sever-crashkit` |
| sever-crypto | 3 | Generators, scalar map, Pedersen commitments, proof of knowledge, nonces, Ed25519 signatures (4.5, 9) |
| sever-commit | 3 | EP-1: keeps C_S, r_agg, C_t in lockstep with S and n (5.3, 9.3-9.4) |
| sever-log | 3 | RFC 9162 transparency log: tree, proofs, checkpoints, witnesses (10) |
| sever-cert | 3 | Deletion certificates (TLV, strict parser, operator signing by epoch); log as a transaction participant (10-11) |
| sever-p3 | 3 | Part 3 root `Engine<CommitmentExtension, PlaintextSealer, (LogParticipant)>`, operator keys, simulated witnesses, bin `sever-db-p3` |
| sever-py-p3 | 3 | PyO3 module `sever_db_p3_native` |
| sever-crashkit-p3 | 3 tooling | Part 3 gate kit: crash campaign with certificates, trace replay, attacks, measures |
| sever-keys | 4 | Keys in secret memory, bucket function, two-slot key file and recovery rule (13.1, 13.4, 14.7) |
| sever-seal | 4 | AES-256-GCM-SIV sealing (EP-6 AeadSealer), envelopes, bucket blocks, key ring (13.2) |
| sever-erasure | 4 | EP-7 KeyRotationParticipant: rotation inside the deletion transaction, phases A and C, wrapped-key store |
| sever-platform | 4 | Startup refusals (swap, hibernation, mlock, filesystem) and memory hygiene (12.8-12.9) |
| sever-db | 4 | THE final database: composition root `Engine<CommitmentExtension, AeadSealer, (LogParticipant, KeyRotationParticipant)>` + bin `sever-db`; has an `inspect` feature (events, DB-107) |
| sever-py | 4 | PyO3 module `sever_db_native` = final SDK; feature `inspect` adds events/passage/Explainer |
| sever-explain | 4 (Studio) | Why a record routed where it did / which groups a search opens, using the engine's own arithmetic (DB-108); inspect build only |
| sever-scan | 4 | Forensic scanner lib + bins `sever-scan`, `sever-demo-p4` (feature demo), `sever-ex2` (feature forensics) |
| sever-crashkit-p4 | 4 tooling | Part 4 gate kit: both disks, torn key slots, key losses, replay, attacks |
| sever-eval | 4 tooling | `sever-bench` for EX-7/EX-8 on byte-counting disks |
(`sever-py` is absent from crates/README's "Part" column in places but present in the table; the README table does not list `sever-explain` [DOC: crates/README.md]; descriptions come from Cargo.toml.)

Workspaces outside crates/: `verifier/` (crate `sever-verify`, lib name `sever_verify`), `audit/` (`sever-audit`), `fuzz*` (cargo-fuzz), `spikes/p3-proof` (`sever-spike-p3-proof`).

## 3. Python packages (python/)

Each has `tests/` beside it. Run with `PYTHONPATH=python` [DOC: CLAUDE.md 9].
| Package | Part | Purpose / key files |
|---|---|---|
| `sever_db` | 4 | Final SDK wrapper over `sever_db_native` (`__init__.py`) + `sever_db_native.pyi` |
| `sever_db_p3` | 3 | Part 3 SDK wrapper + `sever_db_p3_native.pyi` |
| `sever_db_p2` | 2 | Part 2 SDK wrapper + `sever_db_p2_native.pyi` |
| `sever_partition` | 1 | C-15 partition builder (`build.py`, `artefact.py` .svp codec, `arith.py`, `lw_oracle.py` Ledoit-Wolf oracle); CLI `python -m sever_partition.build [--seed N\|--all-seeds]` |
| `sever_refmodel_core` | 1 | C-18 reference model for Part 1 (`model.py`), written from spec only |
| `sever_refmodel_durable` | 2 | Durable oracle for crash testing (`oracle.py`); a "B-shared" oracle [DOC: CLAUDE.md 6.3] |
| `sever_refmodel_certs` | 3 | Pure-Python reference of the certificate arithmetic: `ristretto.py ed25519.py xmd.py merkle.py posk.py cert.py group.py attacks.py audit.py golden.py spec.py` |
| `sever_testkit` | 1 | Seeds, synthetic data, dataset slices, traces, ledger, gates, spec-trace (`gates.py ledger.py seeds.py slices.py spec_trace.py streams.py synthetic.py traces.py`) |
| `sever_testkit_p2` | 2 | Part 2 gate runners (`gates.py`), `oracle_check.py`, `proofs.py` (red/green proofs runner), `spec_trace.py` |
| `sever_testkit_p3` | 3 | Part 3 enforcement + gates + `registers.py`, `rfc_vectors.py` |
| `sever_testkit_p4` | 4 | Part 4 enforcement + gates + `registers.py`, `rfc_vectors.py` |
| `sever_experiments` | 4 | Evaluation experiments on the final build: `ex2.py` (forensics orchestration), `ex6.py`, `ex7.py` |
| `sever_fair` | 2-4 | Automated fair-testing system (FT-1..FT-10): `pipeline.py room.py sandbox.py agent.py checks.py fix.py report.py config.py prompts/` (e.g. `escape.md fix_code.md fix_gap.md`), driven by `scripts/fair.sh` |
| `sever_demo` | 1 | Renders Part 1 demo JSON to HTML (`render.py`) |
| `sever_demo_p3` | 3 | Part 3 receipt demo (`receipt.py`) |
| `sever_db_native.pyi`, `sever_db_p2_native.pyi`, `sever_db_p3_native.pyi` | - | Type stubs for the three PyO3 modules |
Native extension modules (`sever_db_native` etc.) are built by maturin from crates/sever-py*, not stored in python/.

## 4. docs/

| File | Role |
|---|---|
| `SEVER-DB_SPECIFICATION.md` (2,055 lines) | Normative spec (cite section N) |
| `SEVER-DB_PROJECT_OVERVIEW.md` | Why: decisions DB-N, targets T-N, experiments EX-N, limits L-N |
| `SEVER-DB_BUILD_PLAN_PART_1-2.md`, `..._PART_3-4.md` | How: parts, freeze rule, test plans, gates (Build and Build 3-4 sections) |
| `PROGRESS.md` | Where the project stands now; `archive/PROGRESS_HISTORY.md` older |
| `SPEC_GAPS.md` | G-N gaps and the decisions that closed them |
| `TRACEABILITY.md` | requirement -> test rows (hand-kept input) |
| `TRACE_PART_1..4.md` | spec-trace output: requirements with tests |
| `TEST_ORACLES_P2..P4.md` | `oracle_check report` output (oracle A/B/B-shared/C/D per test) |
| `PROOFS_P2..P4.md` | Output of `proofs run`: red/green proof patches applied in throwaway worktrees |
| `MUTANTS_P1..P4.md` | cargo-mutants triage per part |
| `SOUNDNESS.md` | Soundness notes (not read in detail) |
| `FAIR_TESTING.md` | The clean-room fair-testing rules FT-1..FT-10 |
| `RESULTS.md` | GENERATED index of results (header "Generated by scripts/index.py") |
| `RUN_LEDGER.jsonl` | Append-only ledger of gate runs (224 lines), written by gate runners |
| `COMMIT_MAP.txt` | commit map (not read) |
| `README.md` | Map of all docs |
| `SEVER-DB_documentation_prompt.md` | The task prompt for this report |
| `audit/FAIRNESS_P2..P4(.DRY).md` | Fairness-run reports (6 files) - produced by fair.sh, not to be edited |
| `guides/PART_1_WALKTHROUGH.md`, `guides/TEAM_HANDBOOK.md` | Guides |
| `notes/BUG_HUNT_2026-10.md`, `BUG_HUNT_2026-11.md` | Bug-hunt notes |
| `plans/2026-10-23-v1-then-demo.md` | The one plan: v1.0, then Studio company demo |

## 5. scripts/

| Script | One line |
|---|---|
| `ci.sh` | CI tiers: `fast` (format, lint, types, L1, bounded L2, L3 + spec-trace, ...) and `full-checks` [CODE: arms :93-94] |
| `fair.sh` | Fair testing driver: `doctor`, `run N`, `cycle`, `resume`, `fix`, `dry-run`, `check` (bwrap clean room) |
| `freeze.sh` | F-1: hash a part's owned files into `freeze/PART-N.sha256`; refuses without a fair PASS (FT-10) |
| `index.py` | Generates `parts/*/README.md`, `parts/README.md`, `tests/README.md`, `docs/RESULTS.md` (`--check` finds stale) |
| `p1-demo.sh`, `p2-demo.sh`, `p3-demo.sh`, `demo-p4.sh` | One-command demos per part (section interfaces.md 3) |
| `jobq.sh` | Crash-safe job queue for long gates (uses `jobs/`) |
| `oomguard.sh` | Memory guard (checks every 5 s), systemd user service |
| `sever-jobq.service`, `sever-oomguard.service`, `sever-sidejobs.service` | systemd user units for the above |
| `hooks/guard-sealed.sh` | PreToolUse hook blocking edits to sealed/generated files (FT-3, FT-9, FT-10) |
| `data-preparation/prepare_data.py` (+requirements.txt) | P0: pin, download, build and encode datasets once |
| `bughunt/{blocks,edges,keyslots,killloop}.py` | Bug-hunt helpers: bucket-block metadata, edge inputs via SDK, key-slot metadata, SIGKILL loop (BH-5) |
| `ops/{p4-interim.sh,side-job.sh,sidejobs.sh,progress.py}` | Part 4 interim crash campaign; side-job runner/service; read-only gate progress |
| `hpc/` (HPC_GUIDE.md, LAPTOP_RUN.md, 21 shell scripts, `units/` systemd units) | The v1.0 gate-run kit (DB-111, DB-113): `discover check setup install windows root-setup owner-sudo fetch-data preflight run-all steps launch status watchdog backup on-exit drills mock-step laptop-env rerun-final lib` |

## 6. Generated vs hand-written; ignored

GENERATED, do not edit [CODE: scripts/index.py:25 HEADER; head of each file]: `docs/RESULTS.md`, `parts/README.md`, `parts/{1-the-idea,2-the-database,3-the-receipt,4-the-erasure}/README.md`, `tests/README.md` (header seen at top of tests/README.md). Written by `python3 scripts/index.py`. Other tool-written (not hand-edited): `docs/TRACE_PART_*.md`, `docs/TEST_ORACLES_P*.md`, `docs/PROOFS_P*.md`, `docs/RUN_LEDGER.jsonl`, `results/*`, `docs/audit/*`, `tests/cleanroom/*` [DOC: CLAUDE.md 6.3-6.4]. Frozen: `freeze/PART-1..4.sha256` list files that CI forbids changing [DOC: CLAUDE.md 4.1].
Ignored (not in git): target, .venv, artefacts, traces, jobs, datasets raw/processed, studio/work, keys/certs, fuzz corpora, pycache.

## 7. tests/

Cross-cutting tests (crate and package unit tests live inside crates/ and python/*/tests):
| Folder | Contents |
|---|---|
| `tests/architecture/` | `test_architecture.py` (P1), `_p2`, `_p3`, `test_key_export.py`, `test_p4_pins.py`: dependency-direction and pin checks |
| `tests/e2e/test_p2_e2e.py`, `tests/e2e_p3/test_p3_e2e.py` | End-to-end tests through the SDKs |
| `tests/errata/test_p2_e1_sdk_threads.py` | Regression test for erratum E-1 (SDK deadlock) |
| `tests/proofs/{p2,p3,p4,inspect,scan}/` | Red/green proof patches (413 `.patch` files tracked overall; `MANIFEST.yaml` + `PR-Axx.patch`) consumed by `proofs run` |
| `tests/sabotage/run.sh` | Runner for SB sabotage builds (feature `sabotage-SB-N`) |
| `tests/cleanroom/{p3,p4}/<run-id>/` | Output of fair-testing clean-room sessions (tests written by a fresh tester); do not edit |
| `tests/README.md` | GENERATED: every test by part (e.g. Part 1: 116 Rust + 57 Python) |
`tests/traces/` (MANIFEST.sha256 of traces) is documented in CLAUDE.md but [NOT FOUND] in `ls tests` this session.
