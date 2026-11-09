# SEVER-DB

A vector database with **provable deletion**.

Most vector databases "delete" by hiding a record: the vector stays in the index, and every summary
built from it (a centroid, a running mean) keeps its trace. SEVER-DB keeps each group of vectors as an
**exact integer sum `S` and count `n`** (vectors are quantised to Q24 integers), so deleting a vector
subtracts it exactly. The group returns, bit for bit, to the state it would have had if the vector had
never arrived. Later parts add a Pedersen commitment to each group and a signed, publicly verifiable
deletion certificate, and crypto-shredding of everything deleted.

It is built in **four parts**. Each part adds one claim, is tested against its own gates, and is then
frozen (Build §0.1):

| Part | The claim it adds | Status |
|---|---|---|
| **1 The Idea** | Deleting a vector returns its group, bit for bit, to the never-inserted state | **Done**: every gate passed on 6 Oct 2026; frozen as `part-1-frozen` (see [Part 1 results](#part-1-results)) |
| **2 The Database** | Exactness survives a crash at any point; multi-group deletion is all-or-nothing | **Done**: every gate passed on 8 Oct 2026, then an independent test audit; frozen, now as `part-2-frozen-e2` after errata E-1 and E-2 (see [Part 2](#part-2-the-database)) |
| **3 The Receipt** | Every deletion yields a certificate anyone can verify offline | **Done**: every gate passed in the v1.0 laptop run (29–31 Oct 2026); checks, coverage, spikes and attacks reran on the final commit (1 Nov); fair-testing PASS; frozen as `part-3-frozen` on 1 Nov 2026 (DB-116, DB-117, DB-120; see [Part 3](#part-3-the-receipt)) |
| **4 The Erasure** | Nothing deleted can be recovered from raw storage | **Done**: every gate passed (P4-T10 mutants PASS on 1 Nov); fair-testing PASS; frozen as `part-4-frozen` = `v1.0.0` on 1 Nov 2026. Target T-5 (search stability) was **missed**. The EX-8 measure (10^6 vectors) was **not run to completion**: it needs more memory than the laptop has, and it has no result (DB-114, DB-120; see [Part 4](#part-4-the-erasure)) |

**Each part has its own page** with its code, tests, results and reports: [`parts/`](parts/README.md).
Every test: [`tests/README.md`](tests/README.md). Every result: [`docs/RESULTS.md`](docs/RESULTS.md).
A map of all the documents: [`docs/README.md`](docs/README.md).

Where things stand in detail: [`docs/PROGRESS.md`](docs/PROGRESS.md). Working rules for contributors
and AI assistants: [`CLAUDE.md`](CLAUDE.md).

**Authorship.** All of SEVER-DB was produced by AI (Claude) sessions directed by the owner: the
specification, the engine, the reference models, the tests, the gate runs and the documents.
The independent checks are AI too: fresh clean-room sessions that see only the spec (fair testing).
Every number below was checked against the raw result files and the run ledger on 9 Nov 2026 (DB-120).

## Use the database

The final database is `sever-db` (Rust) with the Python SDK `sever_db`. Vectors are 384 float32
values of unit length (`all-MiniLM-L6-v2` embeddings); record IDs are 1–256 characters and not a
bare number. The data and key directories must be on ext4 or XFS; keep the key directory private
and backed up apart from the data (losing it makes the data unreadable: that is the erasure).

```bash
uv sync --locked
uv run --no-sync maturin develop --release --uv -m crates/sever-py/Cargo.toml   # the SDK, once
```

```python
from sever_db import Database, UserKey, prepare_insert

# The account key: keep user.secret_bytes(); reload it with UserKey.from_secret_bytes(...).
user = UserKey.generate()
with Database.open("/home/me/mydb/data", "/home/me/mydb/keys") as db:
    cid = db.create_collection("artefacts/partition-seed42.svp")  # once; keep the cid
    db.insert(cid, prepare_insert(cid, "note-1", vector, user), passage=b"text")
    hits = db.search(cid, query, k=10)  # [(record_id, distance), ...]
    deletion = db.delete(cid, "note-1")  # deletion.certificate: the receipt
    db.delete_user(cid, ["note-2", "note-3"])  # one person's records, all or nothing
    anchors = db.anchors()  # what a verifier needs (JSON)
```

**See it working first:** [SEVER-DB Studio](studio/README.md) is a desktop app that shows every
feature on real passages: a map of the groups, your own records, the holding area, deletion with
receipts checked offline, crashes, the forensic scan and the evidence (`studio/studio.sh setup`,
`prepare`, then `run`).

Anyone can check a receipt offline, without the database:
`verifier/target/release/sever-verify deletion.cert --anchors anchors.json` (build it with
`cd verifier && cargo build --release`). The same operations are on the command line
(`cargo build --release -p sever-db`; the commands are listed under [Part 4](#part-4-the-erasure)).

Startup refuses unencrypted swap, hibernation, memory that cannot be locked (`ulimit -l unlimited`),
and filesystems that do not overwrite in place (§12.8–12.9). On a development machine such as WSL,
`Database.open(..., allow_unsafe_memory=True)` overrides the memory checks; every override used is
reported in `db.startup`.

---

## Quick start

Everything runs under WSL2 (Ubuntu) or Linux, from the repository root.

```bash
# 1. Toolchains: Rust is pinned by rust-toolchain.toml (1.98.1); Python 3.13 by uv.
uv sync --locked

# 2. The offline demo: no data needed (golden fixture, d = 16, 4 frozen groups, spawn size 8)
scripts/p1-demo.sh --data synthetic

# 3. The fast test tier (format, lint, types, unit/property/stateful tests, spec-trace, L13)
scripts/ci.sh fast
```

The real-data demo needs the P0 data in `datasets/` (not in git; pinned by `datasets/PINS.json`,
verified by `datasets/MANIFEST.sha256`):

```bash
(cd datasets && sha256sum -c MANIFEST.sha256)   # 9 files, all OK
scripts/p1-demo.sh --data nq-10k --seed 42      # builds what is missing, runs, renders the report
```

### What the demo shows (Build §4.9)

`sever-demo idea` streams 10,000 Natural Questions passages into an index over a partition fitted on
SciQ, picks one article's passages (a *cohort*), deletes them with one `delete_user`, and checks:

1. every touched group's canonical blob is **byte-identical** to the blob of a group rebuilt from its
   surviving members' original vectors alone;
2. every other group is unchanged, `N` falls by exactly the cohort's size, and deleting again is
   `AlreadyAbsent` with the state unchanged;
3. no search (all 3,452 real queries, plus each deleted vector's own) returns a deleted passage;
4. **the ghost**: the same deletion in a soft-delete IVF index (the record is still stored and its
   centroid still carries it) and in a float running-mean index (its mean no longer matches the
   survivors-only mean bit for bit), side by side with SEVER's distance of exactly 0.

It prints tables and writes `artefacts/demo/idea-<data>-seed<seed>.json` plus an HTML report page.

---

## Part 1 results

Every number below comes from the run ledger, [`docs/RUN_LEDGER.jsonl`](docs/RUN_LEDGER.jsonl)
(append-only, written by the gate runners, never by hand), with the full result in `results/`.

| Target (Build §4.8) | What | Result |
|---|---|---|
| P1-T1 | 0 exactness violations (survivors check on every core field) | **PASS**: nq-100k 427,455 checks, nq-10k 43,562, synthetic L4 275,114; 0 failures |
| P1-T2 | 0 engine/model mismatches, nq-10k and nq-100k, five seeds | **PASS**: nq-10k 10.6 M values, nq-100k 12.4 M values; 0 mismatches |
| P1-T3 | identical blobs across insertion orders | property tests (proptest, ≥ 256 orders) |
| P1-T4 | scalar and AVX2 kernels bit-identical | **PASS**: 10^7 random pairs; nq-10k 508 M and nq-100k 2.25 B real pairs, 0 mismatches |
| P1-T5 | 0 deleted records returned by search | **PASS**: 0, on nq-10k and nq-100k, five seeds each |
| P1-T6 | builder oracle agreement (shrinkage 1e-12, τ 1e-9), five seeds | PASS (largest differences 2e-17 and 1.4e-14) |
| P1-T7 | Recall@10, dequantised vs float brute force, nq-100k (measure, target ≥ 0.999) | **1.000** |
| P1-T8 | SB-1 … SB-10 each turn a test red | **PASS**: all ten red (`gates p1-checks`, with MSRV 1.85, cargo deny, docs, all 17 steps) |
| P1-T9 | traceability 100 % of Part 1's requirements | 70 / 70 (`docs/TRACE_PART_1.md`) |
| P1-T10 | coverage: Rust lines ≥ 90 %, branches ≥ 85 %; Python lines ≥ 90 % | **PASS**: Rust 95.9 % lines, 87.0 % branches; Python 98.8 % |
| P1-T11 | mutation score ≥ 85 %, every survivor triaged | **PASS**: 325 / 347 caught (93.7 %); 22 survivors, each triaged in [`docs/MUTANTS_P1.md`](docs/MUTANTS_P1.md) |
| P1-T12 | 0 fuzz crashes in ≥ 10^8 executions per parser | **PASS**: 10^8 each for `artefact_parse` and `blob_parse`; an earlier run found one real bug, fixed (below) |
| P1-T13 | contract suites pass for every default and fail for a wrong one; proof spikes | PASS (spikes recorded, then deleted, Build §3.4) |
| P1-T14 | the ghost (measure) | nq-10k seed 42: soft-delete IVF 5.0e-3, float mean 1.9e-8, SEVER 0 |

**Bugs found by the test suite on the way** (each fixed with a regression test): the artefact parser
reserved memory from an untrusted header before checking the file length (found by fuzzing: an
88-byte file claimed 5 GB); `apply` could drop the holding area's records on a malformed flush
(found by the forged-change-set tests).

**Definition of done (Build §2.9):** the demo runs from a clean clone with one command
(`scripts/p1-demo.sh`, checked on 6 Oct 2026: the report and the rebuilt partition artefact were
identical to the working copy's, apart from timing), and every Part 1 file is hashed into
[`freeze/PART-1.sha256`](freeze/PART-1.sha256), which CI checks on every run (F-1, F-2).

---

## Part 2: The Database

Part 2 puts Part 1's frozen index behind a storage engine (Build §5): a write-ahead log (WAL),
paged storage checkpoints, a payload store for passage text, a transaction protocol with an explicit
commit point, and recovery that refuses to serve a state that breaks any invariant (spec §12, §14,
§15, §16.1, §17). Nothing is encrypted yet: Part 2 stores plaintext through `PlaintextSealer`, marks
the database as plaintext, and makes **no confidentiality claim** (DB-48); Part 4 adds encryption.

### Using it

```bash
scripts/p2-demo.sh --data synthetic            # offline demo (Build §5.9)
scripts/p2-demo.sh --data nq-10k --seed 42     # the same on 10,000 real passages
```

The demo runs one multi-group `delete_user` and crashes it twice, once just before its commit point
and once just after, first on a simulated disk and then with a real `SIGKILL` of a child process.
After every recovery the invariant check passes, the deletion is all or nothing (nothing before the
commit point, everything after it), and Part 1's survivors check holds for every touched group.

The command-line tool prints one JSON line per command (errors are typed §17 kinds and carry no
record ID, vector value or key):

```bash
cargo build --release -p sever-p2
B=target/release/sever-db-p2; D="--data /path/db --keys /path/keys"   # data on ext4 or XFS
$B create $D --artefact golden/p1_partition_small.svp --spawn-target 8   # -> {"cid": "..."}
$B insert $D --cid <cid> --id doc-1 --vector '[0.25, ...]' --passage 'text'
$B delete-user $D --cid <cid> --ids '["doc-1", "doc-2"]'                 # one transaction
$B search $D --cid <cid> --vector '[...]' --k 10
$B verify $D                                                             # recovery + invariant check
```

The Python SDK (PyO3; build it once after every `uv sync` with
`uv run --no-sync maturin develop --release --uv -m crates/sever-py-p2/Cargo.toml`):

```python
from sever_db_p2 import Database

with Database.open("/path/db", "/path/keys") as db:
    cid = db.create_collection("artefacts/partition-seed42.svp")
    db.insert(cid, "doc-1", vector, passage=b"text")  # vector: float32, unit length, d = 384
    db.delete_user(cid, ["doc-1", "doc-2"])  # ["deleted", "absent"], all or nothing
    db.search(cid, query, k=10)  # [(record_id, score), ...]
```

A retried insert of the same record with the same vector is a success (`receipt.retried`); a retried
deletion is `"absent"` (§15.1, §15.4). A failed `fsync` aborts the process (§12.7): the next start
recovers.

### Part 2 results

From the run ledger, as for Part 1.

| Target (Build §5.8) | What | Result |
|---|---|---|
| P2-T1…T3 | crash at every VFS operation of 20,000 operations, every 512-byte offset of 200 WAL writes, 1,000 random points, crashes during recovery; five seeds on nq-10k: 0 exactness violations, 0 lost acknowledged operations, 0 corrupt recoveries, 100 % oracle-allowed states, 0 partial `delete_user` | **PASS**: 5 seeds; 343,837 crash points (every VFS operation 321,689, every 512-byte WAL offset 17,148, random 5,000; 6,874 also crashed during recovery) and 28,707 generic-record points; 0 failures of any kind |
| P2-T4 | a reader at every protocol step sees the state before or after, never a mix | **PASS** (engine test, now asserting the reader ran at all seven steps; `gates p2-checks`) |
| P2-T5 | Part 1's traces through the Part 2 engine, plain / close / crash after every rung | **PASS**: 5 seeds × 3 modes on nq-10k, 0 mismatches |
| P2-T6 | 0 fuzz crashes in 10^8 executions per parser | **PASS**: `wal_record`, `manifest`, `checkpoint_file`, `store_record` |
| P2-T7 | contract suites pass and fail for wrong implementations; proof spikes | **PASS** (spikes: AES-GCM-SIV sealer, log and key-rotation participants; recorded, then deleted) |
| P2-T8 | SB-1 … SB-15 each turn a test red | **PASS** |
| P2-T9 | traceability 100 %; lines ≥ 90 %, branches ≥ 85 %, mutation score ≥ 85 % | traceability 46 / 46; coverage **PASS** (lines 94.8 %, branches 86.7 %); mutants **PASS**: 652 / 713 = 91.4 %, all 60 survivors triaged in [`docs/MUTANTS_P2.md`](docs/MUTANTS_P2.md) |
| P2-T10 | the Part 1 freeze manifest is unchanged | **PASS** (`gates p2-checks` after the test audit: all 21 Full-tier steps, including E2E-2.1…2.8, the oracle and proof checks, MSRV 1.85, cargo deny, docs) |
| P2-T11 | bytes and fsyncs per operation, recovery time, memory at nq-100k (measure) | recorded: ≈ 1 fsync per operation; insert 8.1 KB, single delete 14.2 KB, multi-record `delete_user` 24.6 KB written per operation (header and slot after-images in the WAL); recovery 0.05 s from a checkpoint, 0.85 s replaying the WAL since the last automatic checkpoint; peak resident memory 1.09 GB (146,215 operations) |

**Bugs found by the test suite on the way:** recovery silently dropped a damaged committed record in
the newest WAL segment as if it were a torn tail; it now refuses to serve (§12.3). The engine core
(`sever-engine`, `sever-txn`'s protocol, `sever-wal`, `sever-checkpoint`, `sever-appendstore`) has
changed only in tests since the crash gate's commit (682bfac).

**Test audit (CLAUDE.md §6.3):** every one of the 126 SR-labelled Part 2 tests declares where its
expected value comes from (118 from the spec by hand, none from the code alone:
[`docs/TEST_ORACLES_P2.md`](docs/TEST_ORACLES_P2.md)), and every label has a proof anyone can re-run:
a patch that breaks the rule and turns the test red ([`docs/PROOFS_P2.md`](docs/PROOFS_P2.md): 211 of
211 hold; `python -m sever_testkit_p2.proofs run`). The audit closed two spec gaps (G-18, G-19 →
DB-72), and added tests for one writer at a time (§12.5) and for the SDK forwarding vectors unchanged
(§4.2). Every Part 2 file, its proofs included, is hashed into
[`freeze/PART-2.sha256`](freeze/PART-2.sha256).

---

## Part 3: The Receipt

Part 3 adds the claim that every deletion yields a certificate anyone can verify offline (Build 3-4
§1; spec §9, §10, §11, §16.2). Each group keeps a Pedersen commitment `C_S`; every insert and every
deletion is a leaf of an RFC 9162 transparency log whose checkpoints are signed by the operator and
cosigned by four of five witnesses (simulated in v1); a deletion returns a signed certificate with a
proof that the group's new commitment is the old one minus the record's. Still plaintext (DB-48).

### Using it

The command-line tool prints one JSON line per command (§17 errors carry no record ID, vector value,
key or `r_t`). It plays the application backend for `insert` (§3.3):

```bash
cargo build --release -p sever-p3
B=target/release/sever-db-p3; D="--data /path/db --keys /path/keys --d 16"
$B user-key --out /path/user.key                                         # an account key (0600)
$B create $D --artefact golden/p1_partition_small.svp --spawn-target 8   # -> {"cid": "..."}
$B insert $D --cid <cid> --id doc-1 --vector '[...]' --user-key /path/user.key   # -> database_lsn
$B delete $D --cid <cid> --id doc-1        # -> {"outcome": "deleted", "database_lsn", "certificate"}
$B certificate $D --lsn <database_lsn>     # the same certificate, later
$B anchors $D --out anchors.json           # the verifier's trust anchors (§11.3)
```

The Python SDK runs on the application backend (§16.2; build it once after every `uv sync` with
`uv run --no-sync maturin develop --release --uv -m crates/sever-py-p3/Cargo.toml`):

```python
from sever_db_p3 import Database, UserKey, prepare_insert

user = UserKey.generate()  # once per account; keep user.secret_bytes() in the backend's key store
with Database.open("/path/db", "/path/keys", d=384) as db:
    cid = db.create_collection("artefacts/partition-seed42.svp")
    req = prepare_insert(cid, "doc-1", vector, user)  # quantise, draw r_t, compute C_t, sign
    receipt = db.insert(cid, req)  # receipt.database_lsn; retry with the same req
    deletion = db.delete(cid, "doc-1")  # no r_t argument; deletion.certificate (bytes)
    anchors = db.anchors()  # JSON for the verifier
```

Nothing in the SDK accepts a random generator, seed or nonce: any extra argument raises
`SeededNonceForbidden` (§16.2, DB-84). `r_t` cannot be read from a request.

Anyone can then check a certificate offline with the verifier, a separate workspace that shares no
code with the engine (§11.3, DB-85):

```bash
(cd verifier && cargo build --release)
verifier/target/release/sever-verify deletion.cert --anchors anchors.json
# {"accepted": true, "deletion_kind": 0, "database_lsn": 7, ...}  or
# {"accepted": false, "step": 6, "reason": "the proof of knowledge does not verify"}
```

With log access, the auditor checks what no certificate can: that each deletion leaf is where its
certificate says, that each group's certificates chain (every `C_S_pre` is the sum of the group's
members' `C_t`), and that the checkpoints are consistent (§11.3, DB-86):

```bash
$B export-log $D --out export.json        # or db.export_log() in the SDK
(cd audit && cargo build --release)
audit/target/release/sever-audit export.json --anchors anchors.json --certificate deletion.cert
# {"leaves": 20, "checkpoints": 4, "findings": []}
```

### Part 3 results

The pre-registered gates (Build 3-4 §1.9) ran once, at full size, on the owner's laptop (Intel
Core Ultra 5 226V, 8 cores, 16 GB; WSL2, Ubuntu 26.04), not on the college HPC that was planned
(DB-111, DB-113). Each figure comes from the run ledger and its result file. The ledger line is
in brackets.

| Target | What | Result |
|---|---|---|
| P3-T4 (T-1 with certificates) | Crash at every protocol step of 20,000 operations, at WAL byte offsets, at random points and during recovery; nq-10k, five seeds | **PASS** [L144]: 938,129 crash points, 192,964 certificates checked, 0 failures, 0 bad certificates. This ran on 7c445b5, before the 1 Nov integrity fixes; those fixes only add refusals of damaged stores (DB-116, DB-120) |
| P3-T5 (T-3) | Part 1's nq-100k traces, five seeds, five fields and the certificate arithmetic against the model | **PASS** [L148]: 450,056 certificates, 12,880,102 checks, 0 mismatches (on 7c445b5) |
| P3-T1, P3-T2 (T-4) | 1,000 honest certificates per seed, and every attack of AT-1 … AT-20 on each; five seeds | **PASS** on the final commit [L206]: 5,000 accepted, 226,410 attacks rejected. The first runs failed. The verifier accepted 3 forgeries in L103 (a generator bug, AT-14) and 3 in L119 (AT-2: an emptied group's proof verifies under any context, G-34). The generator was changed in response, so the attack set changed after those failures |
| P3-T9 coverage | Lines: sever-crypto and verifier ≥ 95 %, the others ≥ 90 % | **PASS** on the final commit [L200]: crypto 95.4 %, verifier 96.3 %, commit 91.6 %, log 93.1 %, cert 95.9 % |
| P3-T9 mutants | Score ≥ 90 % (crypto, verifier), ≥ 85 % (cert, log); every survivor triaged | **PASS** [L158]: cert 85.2 %, crypto 93.4 %, log 89.1 %, verifier 97.3 % (code of 11f00f2) |
| P3-T10 | Fuzzing, 10^8 executions per parser | **PASS** [L162]: 6 parsers, 0 crashes (on 7c445b5) |
| P3-T3, T6–T8, T11, T12 | `scripts/ci.sh full-checks` | **PASS** on the final commit [L196]: 42 steps |
| P3-T13 (measure) | Proof and verification time, certificate size (d = 384) | Recorded [L182]: prove 15.8 ms, verify 2.7 ms (medians); certificate 1,197–13,645 bytes |
| Fair testing | Clean-room tests from the spec only | **PASS**, run `20261101T134211Z-p3-bb4bac5e` [L215]: 180 tests, 0 failing. Four earlier runs failed |

**Found on the way:** the verifier was right where the spec was not. An emptied group's proof
verifies under any context, so §9.5's "cannot be replayed" was false in exactly that case (G-34,
DB-95); the attack generator's donor now never empties its group.

---

## Part 4: The Erasure

Part 4 encrypts everything secret under a three-level key hierarchy (group, bucket and record keys;
AES-256-GCM-SIV), and every deletion rotates the keys the record was under and overwrites the old
key in the key file before it is acknowledged (crypto-shredding; spec §12.8–12.9, §13, §14.5,
§14.7, §15.3–15.4, §15.8–15.9). Startup refuses unsafe platforms: unencrypted swap, hibernation,
memory that cannot be locked, filesystems that do not overwrite in place (§12.8–12.9), unless a
recorded development override is given.

### Using it

```bash
cargo build --release -p sever-db
B=target/release/sever-db; D="--data /path/db --keys /path/keys"   # ulimit -l unlimited, ext4 or XFS
$B user-key --out /path/user.key
$B create $D --artefact artefacts/partition-seed42.svp                   # -> {"cid": "..."}
$B insert $D --cid <cid> --id doc-1 --vector '[...]' --user-key /path/user.key --passage 'text'
$B delete-user $D --cid <cid> --ids '["doc-1"]'      # certificates; old keys erased before this returns
$B anchors $D --out anchors.json                     # verify certificates with sever-verify, as in Part 3
```

`--allow-unsafe-memory` and `--allow-unsafe-fs` are for development only; each one used is reported
and recorded. The final SDK is `sever_db` (build it with
`uv run --no-sync maturin develop --release --uv -m crates/sever-py/Cargo.toml`); it has Part 3's API
plus `Database.open(..., allow_unsafe_memory=...)` and the `startup` report.

The demo (Build 3-4 §2.11) shows the erasure on simulated disks laid out as one image: the scanner
recovers a live record (it can see), a person's records are deleted with verified certificates, the
scan finds nothing, the SB-24 build (group-key rotation skipped) leaks the deleted vector, and a
crash between commit and key erase is finished by recovery:

```bash
scripts/demo-p4.sh
```

The forensic scanner reads a raw disk image for anything deleted: `target/release/sever-scan IMAGE
--targets targets.json` (§16.3, overview EX-2).

### Part 4 results

These come from the same laptop run, with figures from the run ledger. To fit the owner's two days,
some steps were scoped down (DB-113). P4-T3 crashes one 300-operation window per seed, and EX-2,
EX-6 and P4-T9's replay run at nq-10k instead of the pre-registered nq-100k.

| Target | What | Result |
|---|---|---|
| P4-T1, P4-T2 (T-2) | Raw 16 GiB image scanned after the ingest and after each of five deletion rungs; planted controls; sabotage builds; nq-10k, five seeds | **PASS** [L159]: 0 findings in 30 of 30 scans, every planted control found, and every sabotage build found (924 … 65,738 findings). This ran on 7c445b5, before the 1 Nov integrity fixes, which change no write or erase path (DB-120). A live-record control recovered 0 of 20 records at rungs 1–3 |
| P4-T3 (T-1, final build) | Crash points on both disks, torn key-slot writes, active-key losses. Window A: operations 17,694–17,993, seeds 42, 123, 777. Window B: 18,700–18,999, seeds 2024, 9999 | **PASS** [L164, L192]: 45,635 and 16,965 crash points, 0 failures, 500 of 500 key losses refused, 0 stale key slots, 0 unreadable records (on 7c445b5 and 9e11156). On the final commit, window A was started again and stopped by the owner after 94–98 of its 300 operations per seed: 14,784 crash points, 0 failures, no result file (per-point records in `traces/`, DB-120) |
| P4-T9 (T-3, T-4) | Replay against the model, and attacks, on the final build | **PASS** on the final commit [L210, L208]: 0 mismatches in 10,693,787 checks; 5,000 honest accepted, 226,410 attacks rejected |
| P4-T10 | Coverage ≥ 95 %, mutants ≥ 90 %, fuzzing 10^8, SB-24 … SB-30 | **PASS**: coverage keys 98.1 %, seal 96.1 %, erasure 95.6 % [L202]; mutants erasure 90.4 %, keys 97.7 %, seal 95.9 % [L220]; 5 parsers, 0 crashes [L153]; sabotage inside `p4-checks` [L198]; traceability 69 of 69 (`docs/TRACE_PART_4.md`); proof report 79 of 79 (`docs/PROOFS_P4.md`, run on 19 Oct and not rerun since) |
| P4-T12 (T-5, measure) | Std of Recall@10 over five deletion rungs ≤ 0.005 per seed (nq-10k) | **Missed on all five seeds** [L161]: 0.0079–0.0130. Welch t-test against soft-delete IVF: t = −9.57, p = 0.00015, so SEVER-DB's drift is lower. TOST (Δ 0.005): p = 0.997, so equivalence is not shown. Rebuilding the IVF index drifts less (mean 0.0083 against SEVER-DB's 0.0109). SEVER-DB's ground truth leaves out its own holding-area records, while the FAISS arms score all live records |
| P4-T13 (T-6, measure) | Recall@10 of the dequantised vectors at nq-1m | **1.0** (target ≥ 0.999) [L180] |
| P4-T14 (EX-7, measure) | The cost of erasure: `sever` against `noerase` and `softdelete` | Recorded [L184, L186]. At nq-100k (one seed) a delete call took 109 ms (p50) and 505 ms (p99). That is 7.6 deletes/s, against 741/s for a tombstone delete, with 39.5 KB written per deleted record |
| P4-T15 (EX-8, measure) | Memory and recovery at 10^6 vectors | **Not run to completion**: it needs more memory than the laptop has, and it recorded no result (DB-114, DB-120). Appendix A's ≈ 3.8 GB is a prediction, not a measurement |
| Fair testing | Clean-room tests from the spec only | **PASS**, run `20261101T192712Z-p4-36291aec` [L224]: 101 tests, 0 failing. Four earlier runs failed |
| Test suite | `cargo test --workspace`; `uv run --no-sync pytest -q -m "not slow" --ignore=tests/cleanroom` (the kept clean-room suites run in their own processes, `scripts/ci.sh`) | pass. Python: 271 passed on 9 Nov 2026. Rust: inside `p4-checks` [L198] |

**Bugs found on the way** (each fixed with a regression test first): recovery refused to start
after a crash that tore the last record of the wrapped-key store (found by the crash campaign);
compaction removed `wrapped.old` while a file in it was still open, which FUSE and NFS refuse (found
by EX-2 on a `fuse2fs` image).

---

## The evaluation, and running every gate

Overview §11 and Build 3-4 §2.9: EX-1 … EX-8, pre-registered in
[`configs/experiments.yaml`](configs/experiments.yaml). Runners: `python -m sever_testkit_p4.gates`
(`p4-crash`, `p4-replay`, `p4-attacks`, `p4-forensics`, `p4-checks`, `p4-coverage`, `p4-mutants`,
`p4-fuzz`; measures `p4-ex6`, `p4-quant-recall`, `p4-ex7`, `p4-ex8`) over `python/sever_experiments`:
EX-2 on a `fuse2fs`-mounted ext4 image (`sever-ex2`), EX-6's four arms (the engine, frozen-only, FAISS
soft-delete and rebuild IVF), EX-7's three builds (`sever-db`, `sever-db-noerase`, `sever-softdelete`
through `sever-bench`) and EX-8 at nq-1m.

The run was planned for the college HPC (DB-111). The HPC became unavailable, so the one v1.0 run
was on the owner's laptop through the same scripts, with some steps scoped to fit (DB-113; WSL2,
Ubuntu 26.04). The HPC guide is kept as written: [`scripts/hpc/HPC_GUIDE.md`](scripts/hpc/HPC_GUIDE.md):

```bash
bash scripts/hpc/discover.sh             # read-only machine report
bash scripts/hpc/windows.sh              # .wslconfig (cores-2, RAM-8 GB, swap=0), keep-alive, no sleep
sudo bash scripts/hpc/root-setup.sh      # the owner: packages, memory lock, linger; then wsl --shutdown
bash scripts/hpc/fetch-data.sh && bash scripts/hpc/setup.sh && bash scripts/hpc/check.sh
bash scripts/hpc/install.sh              # systemd user units: run, watchdog, backup, alerts
bash scripts/hpc/drills.sh               # failure drills on a mock run; all must pass
bash scripts/hpc/launch.sh start real    # the run, as sever-hpc@real; status: scripts/hpc/status.sh
```

---

## How it is tested

The specification is the source of truth; tests are written from it, not from the code.

- **Requirement IDs.** Every normative statement has an ID `SR-<section>-<n>` in
  [`spec/requirements.yaml`](spec/requirements.yaml). Rust tests name them with `#[spec("SR-…")]`
  (crate `sever-spec`), Python tests with `@pytest.mark.spec("SR-…")`.
  `python -m sever_testkit.spec_trace` builds the matrix and fails on an untraced requirement.
- **An independent oracle.** The reference model `sever_refmodel_core` (Python, written from the spec
  only) runs every stream and writes a **trace**; the Rust replayer `sever-tracekit` runs the same
  operations through the engine and compares every value: placements, outcomes, the SHA-256 of every
  touched group after every operation, and all groups, stats and top-100 search results at each
  deletion rung. After every deletion it also rebuilds each touched group from its survivors and
  compares bytes, and it scores every query–vector pair with both kernels.
- **Levels L1–L14** (Build §2.1): unit, property (proptest, Hypothesis), spec conformance,
  differential (nq-10k/nq-100k, 1,000 synthetic streams), model-based stateful (Hypothesis
  sequences replayed by the engine), metamorphic (survivors check, whole-index twin), contract suites
  for the extension points, integration, end-to-end (E2E-1.1 … 1.7), fuzzing (cargo-fuzz), mutation
  (cargo-mutants), sabotage, architecture (no I/O, clock or randomness in the core; dependency
  direction; `unsafe` only in the SIMD kernel).
- **Sabotage.** Each SB-N builds the code with exactly one deliberate bug (`--features sabotage-SB-N`);
  `tests/sabotage/run.sh` checks that every one turns a test red.
- **Gates vs measures.** A missed gate is a bug. A measure is recorded as found and never a reason to
  change code or rerun. Every run is in the ledger, including the aborted ones.
- **Fair testing** ([`docs/FAIR_TESTING.md`](docs/FAIR_TESTING.md), `scripts/fair.sh`). One author
  wrote the engine and its tests, so every part is also tested by fresh AI sessions in a `bwrap`
  clean room that holds only the spec and the public API: tests written against a sealed engine and
  hashed before the real engine answers, failures judged by a different model, planted bugs taken
  from the part's cargo-mutants gate (DB-75), a random audit of the suite's expected values, and guarded red-first
  fixes. A part freezes only after a PASS on its exact files.

### Commands

| Purpose | Command |
|---|---|
| Fast tier | `scripts/ci.sh fast` |
| Fast + Full-tier checks (ignored tests, slow tests, sabotage, MSRV 1.85, cargo deny, docs) | `scripts/ci.sh full-checks` |
| P1-T2/T5 (+T1, T4) differential gate | `PYTHONPATH=python uv run python -m sever_testkit.gates p1-differential --data nq-10k --all-seeds --jobs 5` |
| L4 synthetic streams | `… gates p1-synthetic --streams 1000 --ops 1000 --jobs 3` |
| P1-T7 measure | `… gates p1-quant-recall --data nq-100k` |
| P1-T10 coverage | `… gates p1-coverage` |
| P1-T11 mutation (worktree of the commit, survivors checked against `docs/MUTANTS_P1.md`) | `… gates p1-mutants --jobs 2` |
| P1-T8 and the rest of the Full-tier checks | `… gates p1-checks` |
| P1-T12 fuzzing | `… gates p1-fuzz --runs 100000000` |
| Build the partition artefacts | `PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_partition.build --all-seeds` |
| One demo | `scripts/p1-demo.sh --data nq-10k --seed 42` |

Run Python with `PYTHONHASHSEED=0`. Memory: an `nq-100k` model process needs about 2.3 GB; with
WSL's default 8 GB run at most two at once (`--jobs 2`), with 10 GB (`memory=10GB` in
`%UserProfile%\.wslconfig`) three, and nothing else heavy beside them.

---

## Layout (spec §19.2, Build §3.2)

```text
crates/          the Rust workspace: the database, earlier parts' roots, test tooling  → crates/README.md
python/          partition builder, reference models, SDKs, test kits, gate runners, the evaluation
verifier/ audit/ the certificate verifier and the log auditor (separate workspaces, no engine code)
tests/           architecture rules, sabotage runner, end-to-end, errata, red proofs, fair-testing output  → tests/README.md
fuzz/ fuzz-p2/ fuzz-p3/ fuzz-p4/   cargo-fuzz targets, one workspace per part (nightly)
spikes/          Part 3's proof spike (a gate)
golden/ spec/ configs/ datasets/   golden vectors, requirements and registers, pre-registration, data pins
docs/            specification, overview, build plans, gaps, progress, evidence, guides  → docs/README.md
results/         gate and measure results (written by the runners, cited by docs/RUN_LEDGER.jsonl)
scripts/         CI tiers, demos, fair testing, freeze, job queue, the HPC gate run (scripts/hpc/)
freeze/          hashes of the frozen parts' files (F-1)
parts/           one page per part: its code, tests, results, reports (generated, DB-115)  → parts/README.md
studio/          SEVER-DB Studio, the desktop demo of every feature (DB-106)  → studio/README.md
```

Rust unit tests live next to the code they test (`src/tests.rs`), integration tests in each crate's
`tests/`, Python tests in each package's `tests/`; the cross-cutting suites are in `tests/`. Parts 1
and 2 are frozen in place, so this layout is final (no re-layout is planned, DB-112).

Generated, not in git: `artefacts/` (partition artefacts, ID export, demo reports), `traces/`,
`jobs/`, `target/`.

## Documents

| Document | Role |
|---|---|
| [`docs/SEVER-DB_SPECIFICATION.md`](docs/SEVER-DB_SPECIFICATION.md) | **Normative**: what the software must do, byte for byte (cite as §N) |
| [`docs/SEVER-DB_PROJECT_OVERVIEW.md`](docs/SEVER-DB_PROJECT_OVERVIEW.md) | Why: decisions (DB-N), targets, testing strategy, limits |
| [`docs/SEVER-DB_BUILD_PLAN_PART_1-2.md`](docs/SEVER-DB_BUILD_PLAN_PART_1-2.md), [`…PART_3-4.md`](docs/SEVER-DB_BUILD_PLAN_PART_3-4.md) | How it is built: parts, freeze rule, test plans, gates |
| [`docs/SPEC_GAPS.md`](docs/SPEC_GAPS.md) | Every place the spec was unclear, and the decision that closed it |
| [`docs/TRACE_PART_1.md`](docs/TRACE_PART_1.md) … [`TRACE_PART_4.md`](docs/TRACE_PART_4.md) | Requirement → test matrices (generated) |
| [`docs/README.md`](docs/README.md) | A map of every document, and the generated part, test and result indexes |

## Data and licences

The corpora are BeIR/NQ (CC BY-SA 3.0) and SciQ (CC BY-NC 3.0), embedded with
`sentence-transformers/all-MiniLM-L6-v2`; exact revisions in `datasets/PINS.json` and
`configs/experiments.yaml`. Rust dependencies are checked with `cargo deny` (`deny.toml`).
