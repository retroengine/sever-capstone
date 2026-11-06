# Phase 1 inventory (working notes)

Made on 2026-11-01 at HEAD `4a03951` (branch `bughunt-2026-11`), working tree clean.
Every number below comes from a command run in this session ([RUN: …]).

## Skipped (never read)

`target/`, `.venv/`, `artefacts/`, `traces/`, `jobs/`, `datasets/` contents (only `PINS.json`,
`MANIFEST.sha256`, `processed/meta.json` may be read), `fuzz*/target`, `fuzz*/corpus`,
`fuzz*/artifacts`, `verifier/target`, `audit/target`, binaries.

## Size [RUN: `git ls-files` + line count, skipped dirs excluded]

| Kind | Files | Lines |
|---|---|---|
| Rust | 239 | 59,523 |
| Python | 203 | 37,113 |
| Python stubs (.pyi) | 3 | 234 |
| Patch (red/green proofs) | 413 | 5,229 |
| JSON | 119 | 26,594 |
| Markdown | 62 | 16,880 |
| YAML | 11 | 5,743 |
| Shell | 39 | 2,371 |
| TOML | 57 | 1,620 |
| JSONL | 2 | 625 |
| other | 69 | 26,498 |
| **total tracked** | **1,217** | |

Tracked files per top-level folder: tests 460, crates 237, python 121, results 94, studio 63,
scripts 53, docs 39, golden 23, verifier 21, audit 21, fuzz-p3 16, fuzz-p2 15, spec 8, fuzz 8,
fuzz-p4 7, parts 5, spikes 4, freeze 4, datasets 3, configs 2.

## Rust crates [RUN: `cargo metadata --no-deps`; part from crates/README.md, to confirm per crate]

| Crate | Path | Part | Rust files / lines | Internal deps | External deps (Cargo.toml req) | Features |
|---|---|---|---|---|---|---|
| sever-types | crates/sever-types | 1 | 6 / 1,159 | — | thiserror ^2, zeroize =1.9.0 | contract-tests |
| sever-quant | crates/sever-quant | 1 | 1 / 386 | types | — | — |
| sever-partition | crates/sever-partition | 1 | 1 / 337 | types | sha2 =0.10.9 | — |
| sever-index | crates/sever-index | 1 | 9 / 3,161 | partition, quant, types | hmac =0.12.1, sha2 | contract-tests, sabotage-SB-1…5, SB-7, SB-8, test-hooks |
| sever-search | crates/sever-search | 1 | 3 / 485 | index, quant, types | — | sabotage-SB-6, SB-9 |
| sever-p1 | crates/sever-p1 | 1 | 7 / 1,752 | index, partition, quant, search, types | rand_core, serde, serde_json, sha2, zeroize | — |
| sever-spec | crates/sever-spec | 1 (tooling) | 1 / 40 | — | — | — |
| sever-tracekit | crates/sever-tracekit | 1 (tooling) | 2 / 487 | index, partition, quant, search, types | serde_json, sha2 | — |
| sever-vfs | crates/sever-vfs | 2 | 8 / 2,669 | — | — | contract-tests, sabotage-SB-12, SB-14 |
| sever-format | crates/sever-format | 2 | 13 / 4,075 | types | crc32c =0.6.8 | sabotage-SB-11 |
| sever-wal | crates/sever-wal | 2 | 2 / 1,205 | format, types, vfs | — | sabotage-SB-13 |
| sever-appendstore | crates/sever-appendstore | 2 | 3 / 590 | format, types, vfs | — | contract-tests |
| sever-checkpoint | crates/sever-checkpoint | 2 | 2 / 535 | format, types, vfs | — | — |
| sever-txn | crates/sever-txn | 2 | 11 / 2,824 | appendstore, format, index, quant, types, vfs, wal | zeroize | contract-tests, sabotage-SB-15 |
| sever-engine | crates/sever-engine | 2 | 8 / 2,652 | appendstore, checkpoint, format, index, partition, quant, search, txn, types, vfs, wal | rand_core, rustix ^1.1, zeroize | test-hooks |
| sever-p2 | crates/sever-p2 | 2 | 5 / 950 | engine, index, p1, partition, txn, types, vfs | serde_json, sha2 | demo |
| sever-py-p2 | crates/sever-py-p2 | 2 | 1 / 322 | engine, p2, types | pyo3 =0.29.2 | — |
| sever-crashkit | crates/sever-crashkit | 2 (tooling) | 9 / 2,091 | engine, format, index, tracekit, txn, types, vfs, wal | serde_json, sha2 | — |
| sever-crypto | crates/sever-crypto | 3 | 10 / 2,006 | — | curve25519-dalek =4.1.3, ed25519-dalek =2.2.0, merlin =3.0.0, rand_core =0.6.4, sha2, zeroize | sabotage-SB-16…19, SB-23 |
| sever-commit | crates/sever-commit | 3 | 2 / 908 | crypto, index, quant, txn, types | sha2, zeroize | memo-checks |
| sever-log | crates/sever-log | 3 | 9 / 2,805 | appendstore, crypto, format, types, vfs | sha2 | contract-tests, sabotage-SB-20 |
| sever-cert | crates/sever-cert | 3 | 6 / 2,740 | commit, crypto, format, index, log, txn, types, vfs | — | sabotage-SB-22 |
| sever-p3 | crates/sever-p3 | 3 | 6 / 2,203 | cert, commit, crypto, engine, format, index, log, p2, partition, quant, txn, types, vfs | rand_core, serde_json, sha2, zeroize | sabotage-SB-21 |
| sever-py-p3 | crates/sever-py-p3 | 3 | 1 / 628 | commit, crypto, engine, log, p3, quant, types | pyo3, rand_core, zeroize | — |
| sever-crashkit-p3 | crates/sever-crashkit-p3 | 3 (tooling) | 10 / 2,477 | (15 internal) | rand_core, serde_json, sha2 | — |
| sever-keys | crates/sever-keys | 4 | 4 / 1,087 | types, vfs | crc32c, rand_core, zeroize | key-export |
| sever-seal | crates/sever-seal | 4 | 7 / 1,629 | format, keys, txn, types | aes =0.8.4, aes-gcm-siv =0.11.1, rand_core, zeroize | noerase, sabotage-SB-24, SB-28, SB-29, SB-30 |
| sever-erasure | crates/sever-erasure | 4 | 11 / 2,699 | appendstore, format, index, keys, seal, txn, types, vfs | sha2 | noerase, sabotage-SB-25, SB-26, SB-27 |
| sever-platform | crates/sever-platform | 4 | 9 / 1,181 | types | rustix ^1.1, thiserror ^2 | — |
| sever-db | crates/sever-db | 4 | 6 / 2,403 | cert, commit, crypto, engine, erasure, format, index, log, p3, partition, platform, quant, seal, txn, types, vfs | rand_core, serde_json, sha2, zeroize | inspect, noerase |
| sever-py | crates/sever-py | 4 | 1 / 775 | commit, crypto, db, engine, explain, log, platform, quant, types | pyo3, rand_core, zeroize | inspect |
| sever-scan | crates/sever-scan | 4 | 5 / 2,085 | (15 internal) | rand_core, serde_json | demo, demo-sb24, forensics |
| sever-eval | crates/sever-eval | 4 (tooling) | 2 / 623 | commit, crypto, db, engine, format, p2, quant, types, vfs | rand_core, serde_json | noerase |
| sever-crashkit-p4 | crates/sever-crashkit-p4 | 4 (tooling) | 11 / 2,944 | (19 internal) | rand_core, serde_json, sha2 | — |
| sever-explain | crates/sever-explain | 4 (Studio helper; to confirm) | 2 / 271 | index, partition, quant, search, types | — | — |

Separate workspaces (own `[workspace]`, own Cargo.lock):

| Package | Path | Lines | Deps |
|---|---|---|---|
| sever-verify | verifier/ | 14 files / 1,891 | curve25519-dalek =4.1.3, sha2 =0.10.9, ed25519-dalek =2.2.0, serde_json 1; dev: sever-spec (attribute only) |
| sever-audit | audit/ | 14 / 1,630 | same as verifier |
| sever-fuzz | fuzz/ | 2 / 55 | libfuzzer-sys 0.4 + partition, index, quant, types (targets artefact_parse, blob_parse) |
| sever-fuzz-p2 | fuzz-p2/ | 4 / 97 | format, types (wal_record, manifest, checkpoint_file, store_record) |
| sever-fuzz-p3 | fuzz-p3/ | 4 / 65 | cert, log, format (certificate, log_record, witnessed, …) |
| sever-fuzz-p4 | fuzz-p4/ | 5 / 81 | keys, seal, erasure, scan (key_slot, wrapped_value, bucket_block, …) |
| sever-spike-p3-proof | spikes/p3-proof | 2 / 520 | txn, types, commit, aes-gcm-siv, zeroize, rand_core |

SB-10 is not a Cargo feature: to look for it in Python (mustfail marker).

## Python packages (python/) [RUN: line count]

| Package | .py files / lines |
|---|---|
| sever_partition (C-15) | 7 / 682 |
| sever_refmodel_core (C-18) | 4 / 1,030 |
| sever_refmodel_durable | 4 / 394 |
| sever_refmodel_certs | 19 / 2,644 |
| sever_testkit | 11 / 1,500 |
| sever_testkit_p2 | 8 / 1,694 |
| sever_testkit_p3 | 12 / 2,361 |
| sever_testkit_p4 | 11 / 1,510 |
| sever_db (final SDK wrapper) | 3 / 681 |
| sever_db_p2 | 3 / 219 |
| sever_db_p3 | 3 / 634 |
| sever_demo | 3 / 383 |
| sever_demo_p3 | 4 / 309 |
| sever_experiments | 6 / 906 |
| sever_fair | 12 / 2,686 |

Studio: `studio/` 63 tracked files (own pyproject/uv.lock).

## Toolchain pins

- Rust `rust-toolchain.toml`: channel 1.98.1, components rustfmt, clippy. MSRV `rust-version = "1.85"`
  (Cargo.toml, "spec §20.1 (zeroize 1.9.0)"). Edition 2024, resolver 3.
- Workspace lints: `unsafe_code = "forbid"`, `missing_docs = "deny"`, clippy `unwrap_used`,
  `expect_used`, `panic`, `indexing_slicing` = deny.
- Python `==3.13.*` (`.python-version` 3.13); deps numpy 2.5.*, scikit-learn 1.9.*, pyarrow 25.0.*,
  faiss-cpu >=1.15.1; dev: pytest, pytest-cov, hypothesis, ruff, mypy, import-linter, mutmut,
  pytest-benchmark, pyyaml, maturin 1.15.*.
- `deny.toml`: licences MIT, Apache-2.0, Apache-2.0 WITH LLVM-exception (DB-71), BSD-3-Clause,
  Unicode-3.0; yanked deny; unknown registry/git deny; wildcards deny.

Locked versions [RUN: parse Cargo.lock / uv.lock]: aes 0.8.4, aes-gcm-siv 0.11.1, crc32c 0.6.8,
curve25519-dalek 4.1.3, digest 0.10.7, ed25519-dalek 2.2.0, getrandom 0.2.17, hmac 0.12.1,
merlin 3.0.0, proptest 1.6.0, pyo3 0.29.2, rand_core 0.6.4, rustix 1.1.5, serde 1.0.229,
serde_json 1.0.151, sha2 0.10.9, subtle 2.6.1, thiserror 2.0.21, zeroize 1.9.0.
Python: numpy 2.5.3, scikit-learn 1.9.1, pyarrow 25.0.1, faiss-cpu 1.15.1, pytest 9.1.1,
pytest-cov 7.1.0, hypothesis 6.168.2, ruff 0.16.9, mypy 2.3.1, maturin 1.15.0, mutmut 3.8.0,
import-linter 2.15, pyyaml 6.0.3.

## Git [RUN: git log / git tag]

- 430 commits, first 2026-09-27 (`86d8402`), last 2026-11-01 (`4a03951`).
- Kinds: feat 94, docs 90, test 80, fix 74, chore 49, perf 3, ci 3, freeze 2, erratum 2.
- Busy days: 7 Oct (43), 8 Oct (47), 19 Oct (38), 23 Oct (43), 15 Oct (34).
- Tags: `part-1-frozen` b1d4576 (2026-10-06); `part-2-frozen-e1` 7729302 (2026-10-15);
  `part-2-frozen-e2` a244264 (2026-10-15); `pre-tidy` 7c3c313 (2026-10-31); `part-3-frozen`
  a304014 (2026-11-01); `part-4-frozen` = `v1.0.0` 7942c1d (2026-11-01). No plain `part-2-frozen` tag.
- Branches: bughunt-2026-11 (current), laptop-final-run, main, studio-raw; origin/main, origin/studio-raw.

## Run ledger [RUN: parse docs/RUN_LEDGER.jsonl]

224 JSON lines, 2026-10-04T15:23:37Z … 2026-11-01T19:51:45Z. Common fields: `utc`, `gate` or
`measure`, `command`, `commit`, `run_commit`, `outcome` (started / PASS / FAIL / aborted / RECORDED /
measured / DRY), `platform`, `pythonhashseed`, `dataset_manifest_sha256`, `git_dirty`,
`dirty_paths`; optional `data`, `seeds`, `result_file`, `result_sha256`, `summary`, `runs`,
`targets`, `scores`, `untriaged`, `rust_lines`, `rust_branches`, `python_lines`, `owned_sha256`,
`seal_digest`, `run_id`, `part`, `module`, `reason`, `resume_of`.

Outcome counts per gate/measure (non-"started"): see results notes. Fair testing 35 rows
(20 started, 4 DRY, 9 FAIL, 2 PASS).

## Running term list (feeds the glossary)

Q24, x̃, S, n, r_t, r_agg, C_t, C_S, C_S_pre, cid, LSN, group, frozen group, spawned group, spawn,
spawn target, holding area, flush, canonical blob, partition artefact (.svp), centroid, IVF,
nprobe, Recall@10, ghost, cohort, scrambled_id, collection_id, plan/apply, ChangeSet, WAL, segment,
torn tail, checkpoint, MANIFEST, payload store, append store, sealer, PlaintextSealer, fsync,
fsync_dir, SimVfs, PosixVfs, VFS, participant, commit point, recovery, invariant check,
IntegrityViolation, ristretto255, Pedersen commitment, generator G/H, proof of knowledge (PoK),
Schnorr, Merlin transcript, Ed25519, verify_strict, RFC 9162, Merkle tree, leaf, inclusion proof,
consistency proof, checkpoint (log), witness, cosignature, 4-of-5, anchors, deletion certificate,
sever-verify, sever-audit, AES-256-GCM-SIV, AEAD, nonce, key hierarchy, group/bucket/record key,
wrapped key, key slot, crypto-shredding, key rotation, mlock, swap, hibernation, sever-scan,
forensic scan, fuse2fs, gate, measure, interim check, oracle (A/B/B-shared/C/D), red proof, green
proof, sabotage build, mutant, fuzz target, crash point, contract suite, extension point (EP-N),
freeze, erratum, fair testing, clean room, bwrap, SR-x-n, DB-N, G-N, SB-N, AT-N, AF-N, EX-N, T-N,
L-N, L1–L14, F-1…F-6, E-1/E-2, BH-N, P*-T*, E2E-*, FT-N, INV-N.

## Running prerequisite list

Bytes/endianness, files and fsync, processes and memory, swap/hibernation, SIMD/AVX2, vectors and
dot product, cosine/L2 distance, fixed vs floating point, modular arithmetic, groups (intuition),
embeddings, nearest-neighbour search, k-means, IVF, recall, CRUD, soft/hard delete, transactions,
atomicity, WAL, checkpoints, crash recovery, hashes, HMAC, AEAD, nonces, key wrapping, signatures,
elliptic curves, commitments, ZK proofs (intuition), Merkle trees, transparency logs, unit /
property / differential / metamorphic tests, fuzzing, mutation testing, coverage, test oracles,
Rust basics, Cargo workspaces, Python + uv, PyO3/maturin, git, Linux/WSL2, GDPR Art. 17, DPDP Act.
