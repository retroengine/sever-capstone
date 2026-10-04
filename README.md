# SEVER-DB

A vector database with **provable deletion**: deleting a vector returns its group, bit for bit, to
the state it would have had if the vector had never arrived, and each deletion yields a receipt that
anyone can check without database access.

The design is in `docs/` (specification, overview, build plans). It is built in four parts, each
adding one claim and then frozen; the **current part is Part 1, The Idea**, as a Rust workspace
(Build §4.4). Where we are: `docs/PROGRESS.md`. Working rules for contributors and AI assistants:
`CLAUDE.md`.

The Python prototype shown at the 5 Oct 2026 review lives in [`demo/`](demo/README.md). It is
self-contained (own environment, tests and container) and nothing here depends on it.

## Layout (spec §19.2, Build §3.2)

| Path | What |
|---|---|
| `crates/` | Rust crates; Part 1: `sever-types` (started), then `sever-quant`, `sever-partition`, `sever-index`, `sever-search`, `sever-tracekit`, `sever-p1` |
| `Cargo.toml`, `rust-toolchain.toml`, `clippy.toml`, `rustfmt.toml`, `deny.toml` | Workspace, pinned toolchain (1.98.1), lint and licence policy (Build §1.2) |
| `pyproject.toml`, `uv.lock` | The Python environment for the partition builder (C-15) and the reference model (C-18), not written yet |
| `docs/` | Specification, overview, build plans, progress, spec gaps, traceability |
| `datasets/` | Data manifest and pins (the data files themselves are not in git) |
| `scripts/data-preparation/` | The P0 data tool |
| `demo/` | The review prototype (see its README) |

## Build and test (WSL, from the repo root)

```bash
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```
