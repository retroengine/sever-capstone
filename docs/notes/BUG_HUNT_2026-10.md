# Bug hunt, October 2026

Branch `bughunt-2026-10`, based on `p4-fix-delete-checkpoint` (3de67e9). Worked in the worktree
`~/sever-db-bh` beside a second session (sever-db-37), which owns workstream 0 and the files it
changed (crates/sever-db, sever-py, sever-scan, sever-cert, sever-commit, demo-engine, the spec, the
overview, SPEC_GAPS, requirements.yaml, tests/proofs). Severity scale and rules: the owner's brief.

## Report

**1. The known bug (workstream 0, owned and fixed by sever-db-37).** Not an engine regression:
two tours on one work directory; the second wiped the first's open database (details below).
Fixed on `main` (3de67e9) by G-41, G-42, DB-101. While hunting I found a different critical
bug of the same kind of symptom, **BH-5**: a crash between a deletion's `COMMIT` and its phase C
store append, then a clean restart, made the final database refuse every startup (`INV-14`) and
lost the rotated domains' bucket blocks. Root cause `crates/sever-erasure/src/participant.rs:376`
(`replay` kept the WAL tail in memory only; §15.7 step 3 was silent, G-43). Present since the
participant was written (Part 4, module 3); the crash campaigns recover once and never checkpoint
and reopen. Red test 4f2f725 (`p4_db_a_checkpoint_after_recovery_keeps_every_rotated_key`), fix
449927f, proofs PR4-E22, PR4-E23; SR-15.7-4; DB-102.

**2. Findings.** See the table under "Findings": BH-5 critical, fixed; BH-1, BH-6, BH-7 medium,
fixed (BH-7's Part 2 half: erratum E-4 proposed); BH-3, BH-4 low, fixed; BH-2 low, won't fix (frozen EP signature; INV-3 catches it at the next open).

**3. Coverage.** Done: workstream 0 (confirmed the peer's root cause from its evidence); 2
(G-39's refusal against every legitimate crash point, by reading; real-process SIGKILL loops;
compaction under crashes); 3 (verifier, auditor and witnesses read as an attacker, §9–§11); 5
(swallowed-error sweep of every non-frozen crate, §17 error text, lint and types); 6 (SDK edge
inputs); 8 (trace, oracle and proof checks for Parts 3–4; four new proofs run); 9 (`ci.sh`, freeze
lists and the F-2 guard, VM scripts read line by line, GitHub workflow). **Not done** (the owner
should know): workstream 1's section-by-section MUST inventory and the hand-checks of every byte
layout beyond §11 and §14.7; workstream 4 at scale (`demo.sh erase`, the forensic tests larger than
default); workstream 6's differential runs against C-18, the metamorphic laws and the fuzz targets;
workstream 7's CLIs, the other demos and every README command; workstream 8's `proofs run` for whole
parts, the sabotage builds (`full-checks`) and the flakiness double run; workstream 2's larger
SimVfs crash campaigns (sever-db-37 ran its own crash windows; see its report).

**4. End state** (bughunt-2026-10 at 3475ae0, worktree `~/sever-db-bh`, its own `.venv`):
- `scripts/ci.sh fast`: 36 of 36 PASS, exit 0 (run on d8c6064; 3475ae0 adds only
  `scripts/bughunt/`, ruff-clean).
- Part 4: `spec_trace check --part 4 --complete` 71/71; `oracle_check` 74/74 labelled tests, 0 on D
  alone; `proofs check` 92 proofs, 0 labels without one. Part 3: 106/106 traced.
- `proofs run --only`: PR4-E22, PR4-E23, PR4-E24 PROVEN (every named test went red).
- The 5,000-row tour (`sever_tour tour --rows 5000 --dev`): 24 of 24.
- SIGKILL loop on the fixed SDK: seeds 42, 123, 777 × 30 rounds, 0 refusals, 0 mismatches.
- Fuzzing: none run.

**Follow-up (21 Oct 2026, after the merge).** (a) Done: P4-T3 closes and reopens a copy after every
recovery (DB-104; `reopen_mismatches` 0 on the fixed build, 137 with PR4-E22's patch, ops
17,000–17,010 of seed 42). (b) E-4 and E-5, with E-6 (G-42 in Part 2), are applied together with E-3
after v1.0 (DB-103, L-28). Part 3's root took the G-42 guard (DB-103). BH-2: won't fix. Fuzz smoke
after the merge: 17 targets, 90 s each, 0 crashes. (c) and (d) below stand.

**5. For the owner.** (a) The P4 crash campaign (P4-T3) recovers once per crash point; adding a
storage checkpoint and a second open after each recovery would have caught BH-5. It changes a
pre-registered gate's procedure, so it is your call (a DB entry). (b) Errata E-4 and E-5 for
frozen Parts 1–2 (below). (c) Databases made before the fix that hit BH-5's window cannot be
repaired (the blocks are gone); the tour's are throwaway. (d) Nothing here blocks the VM run;
the fair runs for Parts 3 and 4 must run on the new code, since Part 4's owned files changed.

## Workstream 0: the known critical bug (owned by sever-db-37)

Root cause, as established by sever-db-37 and confirmed by its evidence (WAL `CollectionCreate`
cid `92996ed3…` against `9cbb602a…` in `state.json` and the checkpoint): two `demo.sh tour` runs
on one work directory. Run B's `Session.wipe()` deleted run A's open database; A kept writing to
unlinked inodes, read B's leaf file by path at its delete (`§15.3 insert leaf`, which
`.ok().flatten()` at `crates/sever-cert/src/participant.rs:130` had hidden), and its close wrote
checkpoint 2 and `MANIFEST` into B's tree (`§12.3 WAL shorter than the checkpoint`). Not a
regression since fa695dd. Fixes: G-41, G-42, DB-101 (commits 42cf9c2 … 0078fc5).

## Findings

| ID | Severity | § | Where | Status |
|---|---|---|---|---|
| BH-5 | **critical** | §15.6 step 4, §15.7 step 3, §13.4 (INV-14) | `crates/sever-erasure/src/participant.rs:376` (`replay`), `:386` (`recover`) | fixed (4f2f725 red, 449927f fix, PR4-E22; G-43, DB-102) |
| BH-1 | medium | Build §2.2, CLAUDE.md §6.2–6.3 | `python/sever_testkit/spec_trace.py:68` (frozen), `crates/sever-db/src/tests.rs:479`, `scripts/ci.sh` | fixed (05c2da5 red, 1e8e4b7 fix); frozen half: erratum candidate |
| BH-2 | low | §5 (lockstep), Build §1.1 | `crates/sever-commit/src/lib.rs:237,251` | won't fix: `add`/`remove` implement frozen Part 2's infallible extension point (apply cannot fail, Build §1.1); admission checks the dimension first, and INV-3 at the next open would catch a skipped update (21 Oct 2026) |
| BH-3 | low | §20.3 check 1 | `scripts/ci.sh:24-27` | fixed (bb4dc26) |
| BH-4 | low | Build §2.2 | `docs/TRACE_PART_3.md`, `docs/TEST_ORACLES_P4.md` | fixed (1e8e4b7) |
| BH-6 | medium | F-1, Build §0.3 | `scripts/freeze.sh:28-31` | fixed (96cbc0b) |
| BH-7 | medium | §3.2 rule 1, §17 | `python/sever_db/__init__.py:129`, `python/sever_db_p3/__init__.py`; frozen `python/sever_db_p2` | fixed for Parts 3–4 (4245c56, 7b45088 red; e22a495 fix); Part 2: erratum proposed (E-4) |

### BH-5: a crash after a deletion's COMMIT, then a clean restart, makes the database unopenable

**Symptom.** `Database.open` refuses with `IntegrityViolation: INV-14` on every startup, and the
rotated domains' bucket blocks are gone, so their records can never be decrypted again.

**Found by** a real-process SIGKILL loop on the final SDK (scratchpad `killloop.py`: d = 16 golden
fixture, spawn target 8, inserts, deletes, `delete_user`, checkpoints; the parent SIGKILLs the child
at random, retries the operation in flight, checks counts). Seed 42, 6 rounds: every round
recovered, then the final open refused. Evidence kept in `target/bh/kill-a-evidence` (worktree).

**Mechanism** (proved from the evidence, metadata only: `KEYS` slots parsed by hand from §14.7
with an independent CRC-32C, and the kind-1 records of the wrapped store and the WAL):

| Domain | KEYS slot version | Wrapped store, highest block |
|---|---|---|
| holding | 20 | 19 |
| spawn-a18a3b29b7ef70d1 | 14 | 13 |
| spawn-20d95fbcb02af92d | 11 | 10 |
| spawn-0f5903aa7fedeb33 | 8 | 8 |

1. A `delete_user` committed (WAL `COMMIT` durable, key file rotated in phase A); the SIGKILL came
   before `after_commit` appended the new bucket blocks to the wrapped-key store.
2. Recovery replayed the WAL tail: `KeyRotationParticipant::replay` merged the blocks into memory
   only and `recover` never wrote them to the store (`LogStore::replay`, by contrast, appends what it
   replays to its stores). The database served correctly.
3. The retry found the records gone (nothing rotated), and `close()` ran a storage checkpoint, which
   moved the WAL start past those records (§15.6 step 4): their only copy was gone.
4. Every later startup: store v, key file v+1, `recovery::plan` finds no slot at the active
   version, `INV-14`.

**Deterministic reproduction** (no real process):
`cargo test -p sever-db --lib -- p4_db_a_checkpoint_after_recovery_keeps_every_rotated_key`
on 4f2f725 → `disk 0 op 8 KeepAll: refused after the checkpoint: IntegrityViolation { invariant:
"INV-14" }`. Shortest sequence: create a collection, insert 6 records, delete one with a crash at
the data disk's 8th mutating operation (the wrapped-store append), restart, recover, storage
checkpoint, reopen.

**Why the suite missed it.** The crash test and the crash campaigns recover once and check; none
runs a storage checkpoint after a recovery and opens again. The fast tier, the P4 smoke and CI were
green.

**Fix** (449927f): `replay` stashes the participant's WAL values; `recover` loads the store, merges
each value, and appends to the store, durably, those newer than its own state (`Durable::newer`).
Spec §15.7 step 3 amended (G-43, SR-15.7-4, DB-102). Red proof PR4-E22.

**Not fixed, recommended:** the P4 crash campaign (`sever-crashkit-p4`) should run a storage
checkpoint and a second open after each recovery; that changes a pre-registered gate's procedure,
so it is the owner's call (Overview §3.4 forbids moving a threshold, not adding checks; a DB entry
would record it).

### BH-1: a multi-line `#[spec(…)]` is invisible to every trace and proof checker

The tracer, `oracle_check` and `proofs check` read the attribute one line at a time
(`python/sever_testkit/spec_trace.py:68`, `python/sever_testkit_p2/oracle_check.py:118`; both
frozen). rustfmt split `p4_db_no_forbidden_plaintext_reaches_either_disk`'s attribute over eight
lines, so its six labels, INV-11 and §13.2 (Part 4's claim), count as untraced and escape the
oracle and red-proof checks. CI misses it because `scripts/ci.sh` runs `spec-trace-p3` and
`spec-trace-p4` without `--complete`.

Reproduction:

```
$ PYTHONHASHSEED=0 PYTHONPATH=python .venv/bin/python -m sever_testkit_p4.spec_trace check --part 4 --complete; echo $?
Part 4: 64/70 requirements traced; untraced: 6
1
```

Untraced: SR-12.3-4, SR-12.1-1, SR-13.1-1, SR-13.2-8, SR-14.8-3, SR-21-11. Part 3 is 106/106.
Three more multi-line attributes sit in frozen parts (`crates/sever-crashkit/tests/small.rs:34`,
`crates/sever-p1/tests/e2e_idea.rs:200`, `python/sever_testkit/tests/test_stateful.py:64`). Their
parts pass `--complete` through other tests, but those labels were never checked by the oracle or
red-proof checks (erratum candidate for the owner, below).

### BH-6: Part 4's golden file was in no part's freeze list

`golden/p4_rfc8452_aes256gcmsiv.json` matched none of the lists in `scripts/freeze.sh` (Parts 1–3
own `golden/p1_*`, `p2_*`, `p3_*`; Part 4 owned none), so freezing Part 4 would have left its RFC
8452 vectors unguarded by F-2. Reproduction: `comm -23 <(git ls-files | sort) <(for n in 1 2 3 4;
do scripts/freeze.sh list $n | awk '{print $2}'; done | sort -u)` listed it. Fixed: `'golden/p4_*'`
in Part 4's list (DB-102 item 3). Also unowned, in frozen Part 2: `python/sever_db_p2_native.pyi`
(the stub of Part 2's SDK); a list change for a frozen part needs an erratum (E-5 below).

### BH-7: a record ID with no UTF-8 encoding raises `UnicodeEncodeError`, which holds the ID

A Python `str` with a lone surrogate (`"id-\udc80"`) reached PyO3's `str` conversion and raised
`UnicodeEncodeError: 'utf-8' codec can't encode character '\udc80' in position 3`, an untyped
error that quotes part of the record ID (§17: typed, never containing a record ID; §3.2 rule 1: a
record ID is UTF-8). The engine has `InvalidRecordIdReason::NotUtf8` but the SDK never reached it.
Fixed in the SDKs of Parts 3 and 4 (`_rid` before `prepare_insert`, `delete`, `delete_user`):
`InvalidRecordId("invalid record id: not valid UTF-8")`, raised `from None`. Tests:
`test_p4_sdk_a_record_id_that_is_not_utf8_is_invalid_record_id`,
`test_p3_sdk_a_record_id_that_is_not_utf8_is_invalid_record_id` (red before, green after).
Part 2's frozen SDK behaves the same (checked: `insert` and `delete` both raise
`UnicodeEncodeError` quoting the character): erratum E-4.

### BH-2: `add`/`remove` skip the commitment update when `record_commitment` fails

`crates/sever-commit/src/lib.rs:237,251` use `if let Ok(c_t) = …`. If `record_commitment` ever
failed at apply time, `S` and `n` would move and `C_S`, `r_agg` would not, with no signal (§5:
the four change together). Admission checks the dimension first, so this is reachable only through
a bug; apply cannot return an error (Build §1.1). Classified low by both sessions. Unconfirmed as
reachable.

### BH-3: the §20.3 check 1 step passes if `cargo tree` fails, and skips `audit/`

`no_duplicate_crypto_deps` pipes `cargo tree -d … 2>/dev/null` into `grep`; a failing
`cargo tree` prints nothing and the step passes. `audit/` (its own workspace with curve25519-dalek)
is not checked for duplicates, only for the pin (`dalek_pinned`).

## Erratum proposals for the owner (frozen Parts 1–2; Build §6.3 template, not applied)

Renumbered E-4 and E-5 on 21 Oct 2026 (E-2 and E-3 were taken); with G-42 in Part 2 as E-6, they are applied together with E-3 after v1.0 (DB-103, L-28).

- **E-4 (Part 2, low).** *Defect:* `sever_db_p2` lets a `str` with no UTF-8 encoding reach the
  native module, which raises `UnicodeEncodeError` quoting the character (§3.2 rule 1, §17).
  *Failing test first:* the BH-7 test against `sever_db_p2`. *Smallest fix:* the same `_rid`
  check in `python/sever_db_p2/__init__.py` (`insert`, `delete`, `delete_user`). *Re-run:* Part 2's
  Python suite, then every later exit gate. *Tag:* `part-2-frozen-e2`.
- **E-5 (Parts 1–2, low, tooling).** *Defect:* the frozen tracer (`sever_testkit/spec_trace.py`)
  and Part 2's `oracle_check` read `#[spec(…)]` one line at a time, so a split attribute is invisible
  to them (BH-1); three such attributes are in frozen files (`sever-crashkit/tests/small.rs:34`,
  `sever-p1/tests/e2e_idea.rs:200`, `sever_testkit/tests/test_stateful.py:64`), whose labels the
  oracle and proof checks never saw. Also `python/sever_db_p2_native.pyi` is in no freeze list.
  *Fix:* a multi-line-aware scan (or one-line attributes in those three files) and the stub in
  Part 2's list. *Re-run:* every part's `oracle_check` and `proofs check`; new red proofs for any
  label that becomes visible. The guard of DB-102 keeps every file that can still change safe
  meanwhile.

## Checked and clean

- Workstream 3, verifier (`verifier/src`): §11.1 parser (tag order, lengths, trailer, trailing
  bytes, tag 11/12 values), §11.3 steps 1–8 in order, canonical decoding of every point and scalar
  (`decompress`, `from_canonical_bytes`), `C_t` ≠ identity, distinct witnesses (threshold 4),
  RFC 9162 §2.1.3.2 inclusion verification, §9.5 challenge preimage (231 bytes) and verification
  equation, §9.8 messages (65, 66, 83 bytes), every DST string against §2.3. No forgery path found.
  Note: anchors without `gdigest` skip the DB-85 comparison.
- Workstream 2, G-39's refusal (`crates/sever-log/src/store.rs:718`): checked against an aborted
  transaction, a crash between `COMMIT` and the hash append, a storage checkpoint that empties the
  WAL, a multi-leaf `delete_user`, and leafless transactions; hashes join only in phase C after a
  durable `COMMIT`, so no legitimate crash leaves `tree.size() > last replayed + 1`.
- Workstream 5: `ruff check`, `ruff format --check` (root), `mypy python` clean on 3de67e9.
- Workstream 2, real processes: `killloop.py` (SIGKILL at random moments, retry of the operation in
  flight, counts against the journal, final delete of every live record) on the fixed SDK: seeds
  42, 123, 777 × 30 rounds, 0 refusals, 0 mismatches, every final delete `deleted`, store empty.
- Workstream 8, scale path: wrapped-key store compaction under crashes
  (`p4_erasure_a_crash_anywhere_in_a_compacting_deletion_recovers_and_reopens`: every operation of
  a compacting deletion on both disks, DropAll and KeepAll, then a checkpoint and a reopen); green,
  with red proofs PR4-E23 (G-43) and PR4-E24 (the interrupted-swap rule of `WrappedStore::open`).
  Note: the test needed a clean close after each setup round, or the WAL masked a broken store.
- Workstream 3: witness memory persists (`WITNESSES`, written by `durable::replace_file`, so not
  torn); log checkpoints cover committed leaves only (`pre()` uses the committed tree size), so a
  rolled-back transaction cannot make a witness see a fork.
- Workstream 6, SDK edge inputs (`edges.py`): IDs of 1, 256 (also 128 × `é`) and 257 bytes, empty,
  `123`, `+5`, `-0`, `007` refused; `12a`, ` 12`, `12\n`, `1.5`, `١٢٣` (U+0661…) accepted, as
  SR-3.2-2's notes say; NaN and inf `NonFinite`; 0.9 and zero vectors `NotNormalised`; d = 17
  `WrongDimension`; unknown and malformed collection IDs `UnknownCollection`; deleting every record
  leaves N = 0 and reopens; use after close raises a `SeverError`. Only BH-7 failed.
- Workstream 9: `scripts/vm/setup.sh` and `run-all.sh` read line by line: data, artefact and trace
  paths, CLI flags and the resume rule (`rc=0` last line) match the repo; `traces/` is ignored.
  Freeze guard: PART-1 (81 files) and PART-2 (250 files) verify; Part 2's list equals its manifest.
