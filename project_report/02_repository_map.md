# 02 · Repository map

## In simple words

The repository holds one Rust workspace (the database itself, in `crates/`), two independent Rust
programs that check its receipts (`verifier/`, `audit/`), Python packages (the partition builder,
reference models, SDK wrappers and test kits), a desktop demo (`studio/`), and the documents and
evidence (specification, run ledger, results, freeze hashes). This map says what each folder and
package is for, in one or two plain lines.

> **Prerequisites.** What a crate, workspace and package are ([B06](background/B06_rust_and_python_for_this_project.md)).
> Glossary: [crate](16_glossary.md#crate), [workspace](16_glossary.md#workspace-cargo).

## The problem this solves

1,217 tracked files [RUN: inventory] are a lot to navigate. This map tells you where to look first.

## Top-level folders (tracked)

| Folder | Purpose |
|---|---|
| `crates/` | The Rust workspace: 35 crates — the database, earlier parts' roots and SDKs, test tooling |
| `verifier/` | `sever-verify`: offline certificate checker; own workspace, no engine code |
| `audit/` | `sever-audit`: log-export auditor; own workspace with copies of 9 verifier files |
| `python/` | Python packages: partition builder C-15, reference models, SDK wrappers, test kits, experiments, fair testing |
| `tests/` | Cross-cutting tests: architecture rules, end-to-end, errata, red/green proofs, sabotage runner, clean-room output |
| `docs/` | Specification, overview, build plans, progress, gaps, traceability, oracle and proof reports, run ledger |
| `results/` | 94 JSON result files written by gate runners (cited by the ledger) |
| `golden/` | 23 golden vectors from the spec, reference models and RFCs (never from the engine) |
| `spec/` | `requirements.yaml` (293 SR IDs), attack/fault registers for Parts 3–4, RFC texts |
| `configs/` | `experiments.yaml` (pre-registration, 27 Sep 2026) and `fair.yaml` (fair-testing settings) |
| `freeze/` | `PART-1…4.sha256`: hashes of every file each frozen part owns |
| `parts/` | One generated page per part (by `scripts/index.py`) |
| `scripts/` | CI, demos, fair testing, freeze, index generator, job queue, the v1.0 run kit (`scripts/hpc/`), bug-hunt helpers |
| `fuzz/`, `fuzz-p2/`, `fuzz-p3/`, `fuzz-p4/` | cargo-fuzz harnesses per part (own workspaces) |
| `spikes/p3-proof/` | Proof spike showing Part 4 plugs into Part 3 without edits |
| `studio/` | SEVER-DB Studio, PySide6 desktop demo with its own environment |
| `datasets/` | Only `PINS.json`, `MANIFEST.sha256`, `processed/meta.json` are tracked; data files are ignored |
| `.github/workflows/ci.yml` | GitHub CI: `scripts/ci.sh fast` on push/PR |
| `.cargo/config.toml` | Points PyO3 builds at `.venv/bin/python` |
| `.claude/settings.json` | Hook blocking edits to sealed/generated files (`scripts/hooks/guard-sealed.sh`) |
| root files | `Cargo.toml`/`Cargo.lock`, `rust-toolchain.toml`, `rustfmt.toml`, `clippy.toml`, `deny.toml`, `pyproject.toml`/`uv.lock`/`.python-version`, `README.md`, `CLAUDE.md`, `ERRATA.md` |

[RUN: `git ls-files | cut -d/ -f1 | sort -u`; DOC: _notes/repomap.md §1]

## Generated or untracked folders on disk (not in git; not read for this report)

`target/` (Cargo build output), `.venv/` (Python environment), `artefacts/` (built partition artefacts
`partition-seed{42,…}.svp`, ID export, demo reports), `traces/` (reference-model traces), `jobs/` (job
queue), `datasets/raw/` and `datasets/processed/` (data), `studio/work/`, fuzz corpora and artifacts,
`project_report/` (this report). Generated-but-tracked: `docs/RESULTS.md`, `parts/`, `tests/README.md`
(by `scripts/index.py`), `docs/TRACE_PART_*.md`, `docs/TEST_ORACLES_P*.md`, `docs/PROOFS_P*.md`,
`docs/RUN_LEDGER.jsonl`, `results/`, `docs/audit/`, `tests/cleanroom/` [CODE: .gitignore; scripts/index.py].

## Every Rust crate

| Crate | Part | Purpose |
|---|---|---|
| sever-types | 1 | IDs, constants, the 13 §17 errors, secret buffers (EP-4) |
| sever-quant | 1 | normalisation check and Q24 quantisation |
| sever-partition | 1 | parser/validator for `partition.svp` |
| sever-index | 1 | groups, exact `S`/`n`, routing, holding area, flush, plan/apply, canonical blob |
| sever-search | 1 | IVF-flat search, pinned scalar + AVX2 kernel |
| sever-p1 | 1 | Part 1 root, ghost baselines, `sever-demo idea` |
| sever-spec | 1 (tooling) | the `#[spec("SR-…")]` test-label macro |
| sever-tracekit | 1 (tooling) | replays reference-model traces through the engine |
| sever-vfs | 2 | all file I/O behind a trait: `PosixVfs`, crash-simulating `SimVfs` |
| sever-format | 2 | byte-exact, CRC-checked on-disk formats |
| sever-wal | 2 | write-ahead log, torn-tail rule, replay |
| sever-appendstore | 2 | append-only stores (passages; later log, certificates, wrapped keys) |
| sever-checkpoint | 2 | atomic storage checkpoints and MANIFEST install |
| sever-txn | 2 | sealer/participant/clock traits and the commit protocol |
| sever-engine | 2 | the storage engine with recovery and invariant checks |
| sever-p2, sever-py-p2 | 2 | Part 2 root (`sever-db-p2`, `sever-demo-p2`) and SDK |
| sever-crashkit | 2 (tooling) | crash campaigns on `SimVfs` |
| sever-crypto | 3 | generators, commitments, proof, nonces, signatures |
| sever-commit | 3 | keeps `C_S`, `r_agg`, `C_t` in lockstep with `S`, `n` (EP-1) |
| sever-log | 3 | RFC 9162 log, checkpoints, (simulated) witnesses |
| sever-cert | 3 | deletion certificates; the log as a transaction participant |
| sever-p3, sever-py-p3 | 3 | Part 3 root (`sever-db-p3`) and SDK |
| sever-crashkit-p3 | 3 (tooling) | crash campaign with certificates, attacks, measures |
| sever-keys | 4 | key memory, bucket function, two-slot key file, recovery rule |
| sever-seal | 4 | AES-256-GCM-SIV sealing, envelopes, bucket blocks, key ring |
| sever-erasure | 4 | key rotation in the deletion transaction (phases A and C), wrapped-key store |
| sever-platform | 4 | startup refusals (swap, hibernation, mlock, filesystems) |
| **sever-db** | 4 | **the final database** root and `sever-db` CLI |
| **sever-py** | 4 | **the final Python SDK** (`sever_db_native`) |
| sever-scan | 4 | forensic scanner `sever-scan`, Part 4 demo, EX-2 driver |
| sever-eval | 4 (tooling) | `sever-bench` for EX-7 and EX-8 |
| sever-crashkit-p4 | 4 (tooling) | Part 4 gate kit (both disks, torn key slots, key losses) |
| sever-explain | Studio helper (built after Part 4; not frozen) | explains routing and search with the engine's arithmetic (inspect build) |

[CODE: each Cargo.toml `description`; RUN: cargo metadata; DOC: crates/README.md]

## Every Python package (`python/`)

| Package | Purpose |
|---|---|
| sever_partition | C-15 partition builder: k-means, pooled Ledoit–Wolf, `τ`, independent oracle, `.svp` codec |
| sever_refmodel_core | C-18 reference model of Part 1, from the spec only |
| sever_refmodel_durable | crash-campaign oracle with a state digest (B-shared oracle) |
| sever_refmodel_certs | pure-Python ristretto255, Ed25519, XMD, Merkle, proofs, certificates, attacks, audit |
| sever_testkit, _p2, _p3, _p4 | seeds, synthetic data, traces, ledger, gate runners, spec-trace, oracle and proof checks, registers |
| sever_db, sever_db_p3, sever_db_p2 | SDK wrappers over the PyO3 modules (+ `.pyi` stubs) |
| sever_demo, sever_demo_p3 | Part 1 HTML report renderer; Part 3 receipt demo |
| sever_experiments | EX-2, EX-6, EX-7 orchestration |
| sever_fair | the clean-room fair-testing system |

## Important single files

`docs/SEVER-DB_SPECIFICATION.md` (normative, 2,055 lines), `docs/SEVER-DB_PROJECT_OVERVIEW.md` (decisions
DB-N, targets T-N, experiments EX-N, limits L-N), the two build plans, `docs/PROGRESS.md`,
`docs/SPEC_GAPS.md`, `docs/RUN_LEDGER.jsonl` (224 entries), `docs/SOUNDNESS.md` (proof argument),
`docs/FAIR_TESTING.md` (FT rules), `ERRATA.md`, `spec/requirements.yaml`, `configs/experiments.yaml`.

## Key points to remember

- Product: `crates/sever-db` + `crates/sever-py`; checkers: `verifier/`, `audit/`.
- Oracles: `python/sever_refmodel_*` and `golden/`.
- Evidence: `docs/RUN_LEDGER.jsonl` + `results/`; freezes in `freeze/`.

## Check your understanding

1. *Where is the final database's entry point?* — `crates/sever-db` (`src/bin/sever-db.rs`).
2. *Why are `verifier/` and `audit/` outside `crates/`?* — So they share no code with the engine.
3. *Where do golden values come from?* — The spec, reference models and RFCs.
