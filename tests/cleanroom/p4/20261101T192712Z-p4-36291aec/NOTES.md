# Candidate spec gaps (Part 4 clean-room tests)

Places where the specification does not decide a behaviour I wanted to test. None of these is a
test; where a test touches the area, it asserts only what the spec does decide.

## Startup and platform (§12.8, §12.9, §15.7)

1. **§12.9 `ENGINE.lock` contention: which error?** §12.9 says the lock is "taken exclusively (one
   process per data directory)" but neither §12.9 nor §17 names the error a second process gets
   (`PlatformUnsafe`? `IntegrityViolation`? an untyped I/O error?). §17 "Every error is typed" does
   not map it to a row. `test_engine_lock_is_exclusive_across_processes` only asserts that the open fails.
   The spec also does not say whether a second open *in the same process* must fail (it matters for
   `flock` vs `fcntl` locking).
2. **§12.8 which check is reported first, and what its message names.** On a machine where swap is
   unencrypted *and* `mlock` fails, the spec names the mlock refusal ("§12.8 mlock") and the core-dump
   refusal ("§12.8 core dumps") but gives no name for the swap and hibernation refusals and no order.
   The tests assert the type `PlatformUnsafe` only.
3. **§12.8 / API `startup` report format.** "Each one used is reported and recorded" — the spec does
   not define the strings in `startup[0]`, whether swap and mlock count as one override or two, or
   whether an override that was given but not needed is listed. The tests compare counts between two
   opens instead of naming entries.
4. **§12.9 order of the data-directory and key-directory checks**, and whether the data-directory
   check also applies when `allow_unsafe_memory` fails first. Not decided.
5. **§12.9 key directory on tmpfs while `KEYS` already exists on ext4 elsewhere** (a moved key
   directory): §12.9 says "Before KEYS exists, the key directory's attribute decides" but not whether
   the check runs on the file or on the directory once it exists.
6. **§12.9 "Linux x86-64"** cannot be tested from a single Linux x86-64 host.

## Key file (§13.4, §14.7)

7. **Initial `key_version`** of a new domain (0 or 1) is not stated in §13.3 or §14.7; tests use
   relative versions (`v + 1`).
8. **Initial contents of a new pair's inactive slot.** §14.7 says an *erased* slot is 512 zero bytes;
   it does not say the second slot of a freshly appended pair is written as zeros (the tests assume the
   at-rest shape "one valid slot, one zero slot" once no operation is in flight).
9. **Which slot (0 or 1) a new domain's first key goes into.** Not stated.
10. **Order of domains at collection creation.** §14.7 says pairs are appended "in creation order", but
    §6/§15 do not say whether the holding area is created before or after the frozen groups. The tests
    compare sets.
11. **A corrupt `KEYS` header** (bad magic, bad CRC, wrong version). §14.7 says the header is "written
    once ... and never rewritten"; §14.9's "Every parser rejects ..." lists the data-directory files but
    not `KEYS`. Whether the engine refuses (and with which error) is not decided.
12. **A full pair of zeros appended to `KEYS`** (a pair belonging to no domain): §13.4 erases slots of
    no domain, but whether the pair count may exceed the domain count, and whether such a pair index is
    then skipped ("never reused") for the next domain, is not stated.
13. **A valid slot whose `domain_index` differs from its pair position**, or a slot naming a domain of
    another collection placed in a live domain's pair. §14.7 says "A slot names its domain, so recovery
    maps slots to domains directly" but not what happens when the name and the position disagree.
14. **Two valid slots for one domain with the *same* version** (both CRC-valid, different keys).
    §13.4 assumes versions differ.
15. **`KEYS` missing for a database that holds no collection.** Is that a fresh key file (create) or
    a refusal? §13.4 only covers domains with an active version.

## Deletion (§15.3, §15.4, §15.8)

16. **`delete` / `delete_user` with an ID that breaks §3.2 rules 1–2** (empty, 257 bytes, `"123"`).
    §3.2 says the rules are "checked on every insert"; for a deletion it is not said whether the result
    is `InvalidRecordId` or `AlreadyAbsent`. Only the SDK-side UTF-8 rule is tested.
17. **`delete_user` with an empty list.** One empty transaction, no-op, or error? Not stated.
18. **`delete_user` and log checkpoints:** §15.3 step 3 creates an on-demand log checkpoint "as its own
    committed transaction" before a deletion; for `delete_user` it is not said whether this happens once
    per list or per record, nor whether a crash after that checkpoint transaction but before phase B
    is distinguishable (it is not a leaf, so lsn arithmetic is unaffected).
19. **§15.4 crash during phase A** (a torn *new* slot written into the inactive position) is covered by
    the torn-slot row only for phase C; the table implies the same handling but does not say so.
20. **§15.8 "memory no longer contains the record, its keys or the old accumulator"** and §12.6 zeroing
    cannot be observed through the public interface (no memory introspection); only the INV-9 search
    consequence is tested.

## Drop collection (§15.9)

21. **Files of a dropped collection.** §15.9 says "delete its files", but in the §14.1 layout most
    stores are shared by all collections; which files are deleted, and whether the wrapped-key store
    compaction is immediate, is not decided.
22. **Re-creating a collection after a drop**: new pairs are appended (§14.7 "never reused"), so the
    key file only grows; no bound or compaction is stated.

## Errors and SDK (§16.2, §17)

23. **`DuplicateRecord` argument shape.** §17 gives `DuplicateRecord { same_commitment }`; the SDK
    reads it from `e.args[0]`, which the spec does not define. Tests assert the type only.
24. **`GroupCapacityExceeded`** needs 10^6 records in a group (§5.6); not reachable in a test's time.
    **`DurabilityFailure`** needs a failing `fsync` (§12.7: the process aborts); not producible through
    the public interface on ext4. **`CommitmentMismatch`** needs a tampered `C_t`, but `InsertRequest`
    is opaque. These rows of §17 are not tested.
25. **Message of a later call after the engine stopped serving.** §17 gives
    "`§17 the engine stopped serving`" for later calls, but does not say whether the *first* failing
    call after a `§12.9 data directory replaced` detection carries that check's name or the generic one.
    The test checks the first call's name and only the type afterwards.
26. **Record ID regex and Unicode / newline**: §3.2's `^[+-]?[0-9]+$` is interpreted with `[0-9]` as
    ASCII and `$` as end of string. Under some regex dialects `$` also matches before a trailing newline
    (`"12\n"` would then be rejected) and `[0-9]` stays ASCII; the spec does not pin the dialect. The
    tests avoid trailing newlines and use Arabic-Indic digits as an accepted ID.
27. **`Database.open` with a `d` different from the stored database's `d`.** Not decided.

## Command-line tool (§16.3, Part 4 API)

28. **The `sever-db` CLI's argument grammar** (where `--allow-unsafe-memory` goes, whether there is a
    single-record `delete`, a `search`, or a `--d` flag) and its **exit codes and output format** are not
    in the spec; §16.3 lists only `sever-partition`, `sever-verify`, `sever-audit` and `sever-scan`.
    The crash tests use only the commands shown in the Part 4 API notes, put the override after the
    subcommand's own options, expect exit 0 for a completed run, and use v1's default `d = 384`.
29. **`sever-scan`** (§16.3, SR-16.3-3) takes a raw disk image and a targets file whose format is not
    specified; the sandbox has no disk image tooling, so it is not tested.
