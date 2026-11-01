# Part 3 clean-room testing — candidate gaps

Places where the specification does not decide a behaviour I wanted to test. None of these became
a test assertion; where a test touches the area it only asserts what the spec does decide.

## Validation and errors

1. **Order of checks split between SDK and engine (§4.1, §16.2).** §4.1 orders the checks
   (dimension, then finite, then norm), but §16.2 says `prepare_insert` "takes the dimension from
   the vector's length", so the SDK cannot check step 0. A vector of the wrong length that is also
   non-finite or not normalised (for example `[]` or `[NaN] + 14 zeros` at d = 16) may be refused
   by the SDK with `NonFinite` / `NotNormalised` before the engine could say `WrongDimension`. The
   spec does not say which error the caller gets. (The ordering test therefore goes through
   `search`, which the engine checks itself, §8.1.)
2. **`$` in the record-ID pattern (§3.2 rule 2).** `^[+-]?[0-9]+$` is not said to be a full match
   with no trailing-newline allowance. In several regex dialects (Python `re`, PCRE) `$` also
   matches before a final `\n`, so `"12\n"` is rejected there and accepted under a strict full
   match (Rust `regex`). Undecided.
3. **Record-ID rules on delete (§3.2, §15.3, §17).** The rules are "checked on every insert";
   §15.3 step 1 only looks up the `scrambled_id`. Whether `delete(cid, "123")`, `delete(cid, "")`
   or a 300-byte ID raises `InvalidRecordId` or returns `AlreadyAbsent` is not decided.
4. **Error for a held `ENGINE.lock` (§12.9, §17).** "taken exclusively" — but §17's table has no
   row for a second opener, so the error type is not decided. The test only checks that the second
   process fails and the holder is unaffected.
5. **Reopening with another `d` (§2.2, §14.9, §16.1).** Opening a database written at d = 16 with
   `d = 384` is not given an error or a behaviour.
6. **`DuplicateRecord { same_commitment }` in Python (§16.2, §17).** How the flag reaches Python
   is not specified (the SDK reads `args[0]`); the tests only assert the SDK's documented outcome.
7. **`SeededNonceForbidden` for `create_collection` (§16.2, §3.1).** §16.2: "every SDK function
   that draws randomness or leads to a proof raises it for any argument beyond its documented
   ones". `create_collection` draws a random `collection_id` (§3.1), yet the SDK signature has no
   catch-all, so an extra argument gives `TypeError`. Whether "draws randomness" covers randomness
   drawn by the engine on the SDK's behalf (create, open) is not decided.
8. **Stopping after an artefact `IntegrityViolation` (§6.3, §17).** §17 says *every*
   `IntegrityViolation` stops the engine serving, which includes a bad artefact file handed to
   `create_collection` (an input error, not damaged state). The test follows the letter of §17;
   if that is not the intent, the spec should carve it out.

## Log, checkpoints and certificates

9. **Which checkpoint tag 6 uses (§10.3, §11.2, §15.3 step 3).** A witnessed checkpoint covering
   every leaf is guaranteed before a deletion, but the certificate is not required to use *that*
   one (any earlier witnessed checkpoint covering the insert leaf would also verify). Tests assert
   only `leaf_index < tree_size ≤ database_lsn`, plus the latest checkpoint's size.
10. **On-demand checkpoint inside `delete_user` (§15.3, §10.3, DB-82).** `delete_user` "does steps
    1–4 for every record in list order", and step 3 creates a checkpoint "if a witnessed log
    checkpoint does not cover every leaf". From the second record on, the first record's delete
    leaf is not covered, but it is not committed either (one transaction), and checkpoints cover
    committed leaves only. The spec does not say that step 3 is evaluated once per call.
11. **Genesis cosignatures (§10.3, §10.4).** Witnesses "remember" genesis, but whether
    `latest_log_checkpoint()` on a new database carries cosignatures (and how many) is not stated.
12. **Range of `inclusion_proof` (§10.1, §16.1).** §10.1 states the valid range for consistency
    proofs only (G-50). For inclusion, "out of range" (SDK docstring) is not defined in the spec;
    tests use `leaf_index < tree_size ≤ log size` and `[]` for a one-leaf tree (RFC 9162).
13. **`certificate(lsn)` for a non-deletion leaf (§15.4, §16.1).** §16.1 returns
    `Result<Vec<u8>>`; only the SDK docstring says `None`. The Rust-level behaviour for an insert
    leaf or a future index is not in the spec.
14. **Silent loss after damage (§12.3, §14.8 vs §15.8).** A store's damaged last record is "dropped
    as" a torn append, and a WAL transaction whose `COMMIT` is damaged is discarded, so after
    on-disk damage an acknowledged deletion's certificate (or the deletion itself) may vanish
    without an error, though §15.8 promised durability. The corruption tests accept that only for
    the last store record; the spec should state exactly what may vanish.
15. **Epoch transitions (§9.8).** Nothing in the public interface moves the clock across a 90-day
    epoch, so "a key of a later epoch is listed from its first use" (§11.3) and old-epoch
    verification after rotation cannot be tested from outside.

## CLI and SDK surface

16. **CLI output and exit codes (§16.3, API doc).** `sever-db-p3` is not in §16.3's table; only the
    API doc describes it. Exit codes, the shape of an error line, and the certificate's text
    encoding in JSON (hex or base64) are not specified. Tests decode either and assert only that
    no record ID leaks.
17. **`stats()` keys and `export_log()` schema (§16.1, §11.3 DB-86).** Contents are listed loosely
    ("group counts, sizes, N, k, memory, disk"; "every leaf, ... placement, ... checkpoint") with
    no field names, so `N`, `k` (§7.6) and the export cannot be checked directly.
18. **Spawn target wording (§7.4 vs §2.2 / DB-62).** §7.4 says a flush happens at "exactly 200";
    the collection option `spawn_target` (DB-62) changes it. The tests assume the flush happens at
    the configured target, which only DB-62 implies.

## Not reachable through the public interface (no test possible)

- `CommitmentMismatch` (§9.3, §15.1 step 2): `InsertRequest` is built by `prepare_insert` and
  cannot be altered, and the CLI prepares its own requests.
- `GroupCapacityExceeded` (§5.6): needs 10^6 members in one group.
- `DurabilityFailure` (§12.7): needs an `fsync` failure.
- The delete-time `C_t` integrity check (§15.3 step 2, E2E-3.5): needs a test-hooks build to alter
  a stored `r_t`.
- `sever-verify` and `sever-audit` (§16.3) are not in this sandbox; the tests use a clean-room
  §11.3 verifier written from the spec (`tests/sevlib.py`) instead.
- Part 4 rows of the crash table (§15.4 phases A and C, key slots): Part 3 has no key file.
