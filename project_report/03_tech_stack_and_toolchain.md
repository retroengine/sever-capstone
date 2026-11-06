# 03 · Technology stack and toolchain

## In simple words

SEVER-DB's engine is written in **Rust** (fast, memory-safe), its builders, reference models and test
kits in **Python**, and the two meet through **PyO3**. Every version is pinned in lock files so that a
build in a year gives the same bytes. This file lists every important dependency with its locked
version and why it is used.

> **Prerequisites.** [B06](background/B06_rust_and_python_for_this_project.md). Glossary:
> [lock file](16_glossary.md#lock-file), [MSRV](16_glossary.md#msrv).

## The problem this solves

Cryptographic and bit-exact results depend on exact library versions; golden vectors computed with one
version of a curve library must match the next build. Pinning removes "works on my machine".

## Languages and toolchains

| Item | Version | Source |
|---|---|---|
| Rust toolchain | 1.98.1 (+ rustfmt, clippy) | [CODE: rust-toolchain.toml] |
| Rust MSRV (minimum supported) | 1.85, edition 2024, resolver 3 | [CODE: Cargo.toml:L5-L12] |
| Python | 3.13 (`requires-python = "==3.13.*"`; `.python-version` 3.13); ledger platform shows 3.13.14 | [CODE: pyproject.toml; DATA: ledger line 224] |
| Environment manager | **uv** (`uv sync --locked`; `link-mode = "copy"`) | [CODE: pyproject.toml `[tool.uv]`] |
| OS | WSL2 / Linux x86-64 (kernel 6.6.114.1-microsoft-standard-WSL2 in the ledger) | [DATA: ledger line 224] |

## Rust dependencies (locked versions from `Cargo.lock`)

| Crate | Version | What it is (one sentence) | Used in |
|---|---|---|---|
| curve25519-dalek | 4.1.3 | Elliptic-curve library providing the ristretto255 group | sever-crypto, verifier, audit |
| ed25519-dalek | 2.2.0 | Ed25519 signatures (`verify_strict`) | sever-crypto, verifier, audit |
| merlin | 3.0.0 | Transcript construction for hedged proof nonces | sever-crypto |
| sha2 | 0.10.9 | SHA-256 / SHA-512 hashes | many |
| hmac | 0.12.1 | HMAC for scrambled record IDs | sever-index |
| aes-gcm-siv | 0.11.1 | AES-256-GCM-SIV authenticated encryption | sever-seal |
| aes | 0.8.4 | AES block cipher, pinned with `zeroize` so key schedules are wiped | sever-seal |
| crc32c | 0.6.8 | CRC-32C checksums | sever-format, sever-keys |
| zeroize | 1.9.0 | Wipes secrets from memory on drop | many |
| rand_core | 0.6.4 (getrandom 0.2.17) | OS random number source (`OsRng`) | crypto, roots, SDKs |
| rustix | 1.1.5 | Safe wrappers for Linux system calls (`mlockall`, `statfs`, `flock`) | sever-platform, sever-engine |
| thiserror | 2.0.21 | Derives error `Display` text | sever-types, sever-platform |
| serde / serde_json | 1.0.229 / 1.0.151 | JSON for CLIs, anchors, traces | roots, tooling, verifier |
| pyo3 | 0.29.2 (`abi3-py313`) | Rust ↔ Python bindings | sever-py, sever-py-p2, sever-py-p3 |
| proptest | 1.6.0 (dev) | Property-based testing | engine, index, search, … |
| libfuzzer-sys | 0.4 (fuzz workspaces) | libFuzzer bindings for cargo-fuzz | fuzz*/ |

[RUN: parse of Cargo.lock; CODE: crates/*/Cargo.toml]. Crypto crates are pinned with `=` (spec §20.1).

## Python dependencies (locked versions from `uv.lock`)

| Package | Version | What it is | Used for |
|---|---|---|---|
| numpy | 2.5.3 | Arrays and linear algebra | builder, models, experiments |
| scikit-learn | 1.9.1 | Machine-learning library (`KMeans`, `LedoitWolf`) | partition builder C-15 |
| pyarrow | 25.0.1 | Parquet/Arrow I/O | dataset slices |
| faiss-cpu | 1.15.1 | Meta's similarity-search library | EX-6 baselines (soft-delete and rebuild IVF) |
| pytest / pytest-cov | 9.1.1 / 7.1.0 | Test runner / coverage | all Python tests |
| hypothesis | 6.168.2 | Property-based / stateful testing | L2, L5 tests |
| ruff | 0.16.9 | Linter and formatter | CI |
| mypy | 2.3.1 | Static type checker (`--strict`) | CI |
| maturin | 1.15.0 | Builds PyO3 extension modules | SDK builds |
| mutmut | 3.8.0 | Python mutation testing (installed; no gate uses it) | — |
| import-linter | 2.15 | Python import-layering checks | architecture |
| pyyaml | 6.0.3 | YAML parsing | registers, requirements |

[RUN: parse of uv.lock]. **sentence-transformers is not a dependency of this environment**: embeddings
were made once, in the separate P0 environment, with `sentence-transformers/all-MiniLM-L6-v2`
(revision pinned in `datasets/PINS.json`) [DOC: CLAUDE.md §8; README.md L487-L489]. Studio uses
`onnxruntime` + `tokenizers` to run the same encoder [CODE: studio/pyproject.toml].

## Development tools

| Tool | One sentence | Where |
|---|---|---|
| cargo-fuzz | Runs libFuzzer against Rust functions to find crashes | fuzz*/, gates `p*-fuzz` |
| cargo-mutants | Makes small code changes and checks the tests notice | gates `p*-mutants`, docs/MUTANTS_P*.md |
| cargo-deny | Checks licences, advisories and dependency sources | deny.toml, `ci.sh full-checks` |
| cargo-llvm-cov, pytest-cov | Measure which lines and branches the tests run | gates `p*-coverage` [CODE: python/sever_testkit*/gates.py (`cargo llvm-cov`)] |
| bwrap (bubblewrap) | Linux sandbox used for the fair-testing clean room | python/sever_fair/sandbox.py |
| fuse2fs | User-space ext4 driver; mounts an image file for EX-2 | scripts/demo-p4.sh, EX-2 |
| systemd user units | Run long gates unattended (job queue, OOM guard) | scripts/*.service, scripts/hpc/units |


## Key points to remember

- Rust 1.98.1 (MSRV 1.85), Python 3.13 via uv.
- Crypto: curve25519-dalek 4.1.3, ed25519-dalek 2.2.0, merlin 3.0.0, aes-gcm-siv 0.11.1, sha2 0.10.9.
- PyO3 0.29.2 + maturin 1.15.0 for the SDKs.
- Embeddings come from all-MiniLM-L6-v2, computed once in a separate P0 environment.

## Check your understanding

1. *Why pin crypto crates with `=`?* — Golden vectors and the independent verifier depend on the exact version.
2. *What is FAISS used for here?* — Baseline arms in EX-6, not the engine.
3. *Which tool builds the Python SDK?* — maturin (over PyO3).
