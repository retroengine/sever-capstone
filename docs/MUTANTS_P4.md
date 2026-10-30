# Part 4 mutation survivors (P4-T10)

P4-T10 (Build 3-4 §2.10) asks for a mutation score of at least 90 % over `sever-keys`, `sever-seal`
and `sever-erasure`, with **every surviving mutant triaged** here; `gates p4-mutants` fails if a
survivor's text is missing from this file. The text of each survivor is
`path:line:col: replacement`.

Where the numbers come from (DB-114): the first laptop run (30 Oct 2026, commit 7c445b5) scored
sever-keys 0.907, sever-seal 0.779 and sever-erasure 0.765, with 71 survivors untriaged. Eight of the
survivors counted were mutants that hit the 300 s limit while the machine ran other work. The fixes:
tests from the spec for the ring's stage and recovery (`sever-seal`), the records' `newer` rule, the
store's byte count, `parse_wal`, abort, INV-14, the compaction threshold (`sever-erasure`) and the
key type and key file (`sever-keys`); none carries an `SR-` label, so none needs a red proof. The
survivors below are those still alive in a run of the three crates' own tests after these changes;
the gate also runs the tests of `sever-db` and `sever-scan`, which may kill more. Timeouts of the
first run are listed too, in case they recur.

## Equivalent: a capacity hint

`ENTRY` (`records.rs:30`) only sizes the `Vec::with_capacity` of `envelopes_value`; a wrong value changes no byte of the encoding, and `parse` reads its length from the count field.

```
crates/sever-erasure/src/records.rs:30:29: replace + with -
crates/sever-erasure/src/records.rs:30:29: replace + with *
crates/sever-erasure/src/records.rs:30:25: replace + with -
crates/sever-erasure/src/records.rs:30:25: replace + with *
```

## Equivalent: ties between equal versions

`Durable::merge` replaces an entry when the stored version is lower; at an equal version the two entries are the same envelope or block (a version names its content, §14.8), so `<` and `<=` give the same state.

```
crates/sever-erasure/src/records.rs:170:67: replace < with <=
crates/sever-erasure/src/records.rs:177:74: replace < with <=
```

## Equivalent: the store's key counter

`WrappedStore::append` numbers each value with `next_key`; the store orders entries by their position in the file, never by that number (`next_key *= 1` repeats key 0 and the store accepts it), so no read of the store depends on it.

```
crates/sever-erasure/src/store.rs:157:27: replace += with *=
```

## Equivalent in the measured build: feature switches

`cfg!(feature = "noerase")` and `cfg!(feature = "sabotage-SB-24")` are false in the build the gate measures; replacing the guard with `false` leaves that build unchanged. The sabotage build is tested by its own must-fail test (SB-24).

```
crates/sever-seal/src/ring.rs:243:32: replace match guard cfg!(feature = "noerase") with false
crates/sever-seal/src/ring.rs:251:36: replace match guard cfg!(feature = "sabotage-SB-24") with false
```

## Equivalent: a tie in the store's envelope versions

`load_envelope` keeps the store's entry when its version is higher than the one held; at an equal version both entries are the same envelope (§14.8), so `<` and `<=` agree.

```
crates/sever-seal/src/ring.rs:547:37: replace < with <=
```

## Equivalent: the sealer's own ID

`AeadSealer::sealer_id` is read only by the engine, which compares it with the ID it stored; the spec fixes the value 1 in the file header, which Part 2's header tests cover from the engine side (sever-db), not this crate's.

```
crates/sever-seal/src/sealer.rs:54:9: replace <impl Sealer for AeadSealer>::sealer_id -> u16 with 1
```

## Diagnostic output only: `Debug`

`Debug` of `SlotRecord` prints nothing secret by design (§12.8, §17); the redaction tests accept any output that lacks the key bytes, so an empty output is also accepted.

```
crates/sever-keys/src/file.rs:71:9: replace <impl core::fmt::Debug for SlotRecord>::fmt -> core::fmt::Result with Ok(Default::default())
```

## Test hook: the export sink

`export::set_sink` and `export::emit` are the sink Part 4's forensic test reads keys through; no code in the measured build calls `emit` (the sink is unset), so replacing either with `()` changes nothing in a run without the sink. P4-T1 reads the sink through the forensic test, outside this crate's test set.

```
crates/sever-keys/src/lib.rs:37:9: replace export::set_sink with ()
crates/sever-keys/src/lib.rs:43:9: replace export::emit with ()
```

## Zeroizing a bucket key

`BucketKey::zeroize` is called on drop; the heap bytes are gone afterwards and a test cannot read them without unsafe code (forbidden, §12.8). The forensic gate P4-T1 scans raw storage and memory images for the old bytes.

```
crates/sever-seal/src/block.rs:36:9: replace <impl zeroize::Zeroize for BucketKey>::zeroize with ()
```

## Defensive checks the API cannot trip

`check_header`'s `&&` (`file.rs:93`) joins four tests of the header, each also made by the header's own CRC; `slot_offset` (`file.rs:300`) refuses an index or half outside the file, and every caller passes a pair it has just appended or read. The other callers are the key slots of the key file, whose bounds are tested through the public `write_slot` and `erase_slot`.

```
crates/sever-keys/src/file.rs:93:9: replace && with ||
crates/sever-keys/src/file.rs:300:32: replace || with &&
```

## Accessors reached only through the engine

`KeyRotationParticipant::durable` and `AeadSealer::ring` hand out the participant's merged state and the shared ring; the contract digest and the engine's tests read them, and the in-crate tests need a full engine recovery with a key slot to give `durable` a non-empty state (INV-14 refuses a bare block).

```
crates/sever-erasure/src/participant.rs:121:9: replace KeyRotationParticipant::durable -> &Durable with Box::leak(Box::new(Default::default()))
crates/sever-seal/src/sealer.rs:40:9: replace AeadSealer::ring -> &Arc<KeyRing> with Box::leak(Box::new(Arc::new(Default::default())))
```

## Real test gap: the compaction boundary

`maybe_compact` starts a compaction when the store holds the minimum and more than four times its live bytes (§14.8). The new test shows the minimum and the factor matter (below the minimum nothing compacts, above it the store shrinks), but not the exact boundary: a size equal to the minimum, or the 16-byte per-value overhead in the live total (`164`), would need a test that lands a store exactly on the boundary.

```
crates/sever-erasure/src/participant.rs:164:60: replace + with -
crates/sever-erasure/src/participant.rs:167:32: replace || with &&
crates/sever-erasure/src/participant.rs:167:49: replace <= with >
crates/sever-erasure/src/participant.rs:167:26: replace < with <=
```

## Real test gap: `prepare`'s justification set

`prepare` (`participant.rs:254`, `256`) decides which staged keys the transaction justifies (`retain_stage`). The effect shows only when a planning attempt fails after staging and the next transaction reuses the ring; the crash campaign (P4-T3) exercises this, the in-crate tests do not.

```
crates/sever-erasure/src/participant.rs:254:28: replace == with !=
crates/sever-erasure/src/participant.rs:256:50: replace || with &&
```

## Other

Timeouts of the first run and survivors not yet grouped.

```
crates/sever-keys/src/file.rs:38:25: replace + with *
crates/sever-seal/src/ring.rs:520:9: replace KeyRing::discard with ()
crates/sever-seal/src/ring.rs:582:9: replace KeyRing::committed_block -> Result<(u64, Vec<u8>), Error> with Ok((0, vec![1]))
crates/sever-seal/src/ring.rs:582:9: replace KeyRing::committed_block -> Result<(u64, Vec<u8>), Error> with Ok((1, vec![]))
crates/sever-seal/src/ring.rs:582:9: replace KeyRing::committed_block -> Result<(u64, Vec<u8>), Error> with Ok((1, vec![0]))
crates/sever-seal/src/ring.rs:582:9: replace KeyRing::committed_block -> Result<(u64, Vec<u8>), Error> with Ok((1, vec![1]))
```
