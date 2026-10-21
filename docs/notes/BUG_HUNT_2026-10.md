# Bug hunt, October 2026

Branch `bughunt-2026-10`, based on `p4-fix-delete-checkpoint` (3de67e9). Worked in the worktree
`~/sever-db-bh` beside a second session (sever-db-37), which owns workstream 0 and the files it
changed (crates/sever-db, sever-py, sever-scan, sever-cert, sever-commit, demo-engine, the spec, the
overview, SPEC_GAPS, requirements.yaml, tests/proofs). Severity scale and rules: the owner's brief.

## Report

(Filled in at the end.)

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
| BH-1 | medium | Build §2.2, CLAUDE.md §6.2–6.3 | `python/sever_testkit/spec_trace.py:68` (frozen), `crates/sever-db/src/tests.rs:479`, `scripts/ci.sh` | open |
| BH-2 | low | §5 (lockstep), Build §1.1 | `crates/sever-commit/src/lib.rs:237,251` | open |
| BH-3 | low | §20.3 check 1 | `scripts/ci.sh:24-27` | open |

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
