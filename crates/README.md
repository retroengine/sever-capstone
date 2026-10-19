# Crates

The Rust workspace, by part (Build §3.2; each part adds crates and never edits a frozen one, F-3).
Code of part N depends only on parts ≤ N (`tests/architecture`). Parts 1 and 2 are frozen
(`freeze/PART-1.sha256`, `PART-2.sha256`).

## The database (what ships)

| Crate | Part | What it does |
|---|---|---|
| `sever-types` | 1 | Record, group and collection IDs, constants, §17 errors, secret buffers (EP-4) |
| `sever-quant` | 1 | Normalisation check, Q24 quantisation and dequantisation (§4) |
| `sever-partition` | 1 | The partition artefact `partition.svp`: parser and checks (§6.3) |
| `sever-index` | 1 | Groups, exact accumulators, routing, holding area and flush, plan/apply (§5, §7) |
| `sever-search` | 1 | IVF-flat search with the pinned scalar and AVX2 kernels (§8) |
| `sever-vfs` | 2 | Every file operation (EP-5): `PosixVfs`, and `SimVfs` for crash tests (§12.2) |
| `sever-format` | 2 | Byte-exact, checksummed storage formats with strict parsers (§14) |
| `sever-wal` | 2 | The write-ahead log: segments, transactions, torn tails, replay (§12.3) |
| `sever-appendstore` | 2 | Append-only record stores, the payload store (EP-8, §14.8) |
| `sever-checkpoint` | 2 | Storage checkpoints: atomic images, MANIFEST install (§12.4, §15.6) |
| `sever-txn` | 2 | Sealer, transaction participant and clock interfaces; the commit protocol (§15) |
| `sever-engine` | 2 | The storage engine: collections, API, recovery with the invariant check (§16.1) |
| `sever-crypto` | 3 | Generators, commitments, proof of knowledge, nonces, signatures (§9) |
| `sever-commit` | 3 | `C_S`, `r_agg`, `C_t` kept in lockstep with `S` and `n` (EP-1, §5.3, §9.3–9.4) |
| `sever-log` | 3 | The RFC 9162 transparency log, checkpoints, witnesses (§10) |
| `sever-cert` | 3 | Deletion certificates; the log as a transaction participant (§10–§11) |
| `sever-keys` | 4 | Keys in secret memory, the bucket function, the two-slot key file (§13.1, §13.4, §14.7) |
| `sever-seal` | 4 | AES-256-GCM-SIV sealing, envelopes, bucket blocks, the key ring (EP-6, §13.2) |
| `sever-erasure` | 4 | Key rotation in the deletion transaction, phases A and C, the wrapped-key store (EP-7) |
| `sever-platform` | 4 | Startup refusals and memory hygiene: swap, hibernation, `mlock`, filesystems (§12.8–12.9) |
| **`sever-db`** | 4 | **The final database**: the composition root and the `sever-db` command-line tool |
| **`sever-py`** | 4 | **The final Python SDK** (`sever_db`, §16.2) |
| `sever-scan` | 4 | The forensic scanner `sever-scan` (§16.3, EX-2); the Part 4 demo; the EX-2 driver |

The certificate verifier and the auditor are separate workspaces that share no code with the
engine: [`../verifier`](../verifier), [`../audit`](../audit).

## Earlier parts' composition roots and SDKs (kept, frozen or soon frozen)

| Crate | Part | What it is |
|---|---|---|
| `sever-p1` | 1 | Part 1 root, the ghost baselines, `sever-demo idea` |
| `sever-p2`, `sever-py-p2` | 2 | Part 2 root and SDK (`sever_db_p2`), `sever-db-p2`, `sever-demo-p2` |
| `sever-p3`, `sever-py-p3` | 3 | Part 3 root and SDK (`sever_db_p3`), `sever-db-p3` (the receipt demo is `scripts/p3-demo.sh`) |

## Test and evaluation tooling (never shipped)

| Crate | Part | What it is |
|---|---|---|
| `sever-spec` | 1 | The `#[spec("SR-…")]` attribute read by spec-trace |
| `sever-tracekit` | 1 | Replays reference-model traces through the engine |
| `sever-crashkit` | 2 | The crash campaign on `SimVfs` (P2-T1 … T3) |
| `sever-crashkit-p3` | 3 | Part 3's gate kit: crash campaign with certificates, trace replay, attacks |
| `sever-crashkit-p4` | 4 | Part 4's gate kit: both disks, torn key slots, key losses, replay, attacks |
| `sever-eval` | 4 | `sever-bench`: EX-7's three builds and EX-8, on disks that count what is written |
