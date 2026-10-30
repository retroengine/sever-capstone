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

`AeadSealer::ring` hands out the shared ring; the engine's tests read it through the engine. (`KeyRotationParticipant::durable` is now killed by `p4_erasure_recovery_loads_the_store_into_the_merged_state`.)

```
crates/sever-seal/src/sealer.rs:40:9: replace AeadSealer::ring -> &Arc<KeyRing> with Box::leak(Box::new(Arc::new(Default::default())))
```

## Real test gap: the compaction boundary

`maybe_compact` starts a compaction when the store holds the minimum and more than four times its live bytes (§14.8). `p4_erasure_compaction_waits_for_four_times_the_live_bytes` now kills the factor's mutants (`167:32`, `167:49`). The exact boundaries are still open: a store exactly at the minimum (`167:26`), and the 16-byte per-value overhead in the live total (`164`), which moves the factor by a few percent. Each would need a test that lands a store exactly on the boundary. Risk: low (it changes when compaction runs, never what the store means).

```
crates/sever-erasure/src/participant.rs:164:60: replace + with -
crates/sever-erasure/src/participant.rs:167:26: replace < with <=
crates/sever-erasure/src/participant.rs:167:26: replace < with ==
```

## Real test gap: `prepare`'s justification set

Correction (interactive review): `participant.rs:254` (`holding`) and `:256` (`||`) feed only `skip_buckets = cfg!(feature = "sabotage-SB-25") || (cfg!(feature = "sabotage-SB-26") && holding)`. Both `cfg!` are false in the measured build, so either mutation leaves `skip_buckets` false: **equivalent in the measured build** (a sabotage switch written as `cfg!` rather than `#[cfg]`, which DB-114's exclusion rule does not cover; the rule is not widened after the Part 4 result).

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

## Killed by the new tests (listed so a chance survival is still triaged)

These survived the 30 October run and are killed by tests added since (each checked by applying the mutation by hand). If one survives a rerun by chance, it is a test gap of the kind its group above describes.

```
crates/sever-erasure/src/participant.rs:121:9: replace KeyRotationParticipant::durable -> &Durable with Box::leak(Box::new(Default::default()))
crates/sever-erasure/src/participant.rs:167:32: replace || with &&
crates/sever-erasure/src/participant.rs:167:49: replace <= with >
crates/sever-erasure/src/participant.rs:116:9: replace KeyRotationParticipant::ring -> &Arc<KeyRing> with Box::leak(Box::new(Arc::new(Default::default())))
crates/sever-erasure/src/participant.rs:32:38: replace << with >>
crates/sever-erasure/src/participant.rs:78:9: replace <impl core::fmt::Debug for KeyRotationParticipant>::fmt -> core::fmt::Result with Ok(Default::default())
crates/sever-erasure/src/participant.rs:325:9: replace <impl TxnParticipant<E> for KeyRotationParticipant>::abort with ()
crates/sever-erasure/src/participant.rs:442:9: replace <impl TxnParticipant<E> for KeyRotationParticipant>::check_invariants -> Result<(), Error> with Ok(())
crates/sever-erasure/src/participant.rs:461:9: delete match arm RecordType::BucketBlock
crates/sever-erasure/src/participant.rs:465:16: replace match guard r.payload.get(..2) == Some(&KEY_PARTICIPANT_ID.to_be_bytes()[..]) with true
crates/sever-erasure/src/participant.rs:465:16: replace match guard r.payload.get(..2) == Some(&KEY_PARTICIPANT_ID.to_be_bytes()[..]) with false
crates/sever-erasure/src/records.rs:155:9: replace Durable::newer -> bool with true
crates/sever-erasure/src/records.rs:156:89: replace < with <=
crates/sever-erasure/src/records.rs:160:48: replace < with ==
crates/sever-erasure/src/records.rs:160:48: replace < with >
crates/sever-erasure/src/records.rs:160:48: replace < with <=
crates/sever-erasure/src/records.rs:162:33: delete !
crates/sever-erasure/src/store.rs:115:9: replace <impl core::fmt::Debug for WrappedStore>::fmt -> core::fmt::Result with Ok(Default::default())
crates/sever-erasure/src/store.rs:176:45: replace + with *
crates/sever-keys/src/lib.rs:94:9: replace <impl Zeroize for Key>::zeroize with ()
crates/sever-keys/src/lib.rs:111:9: replace <impl fmt::Debug for Key>::fmt -> fmt::Result with Ok(Default::default())
crates/sever-keys/src/file.rs:241:9: replace KeyFile::path -> &str with ""
crates/sever-keys/src/file.rs:241:9: replace KeyFile::path -> &str with "xyzzy"
crates/sever-seal/src/ring.rs:69:9: replace Stage::is_empty -> bool with true
crates/sever-seal/src/ring.rs:69:9: replace Stage::is_empty -> bool with false
crates/sever-seal/src/ring.rs:74:13: replace && with ||
crates/sever-seal/src/ring.rs:73:13: replace && with ||
crates/sever-seal/src/ring.rs:72:13: replace && with ||
crates/sever-seal/src/ring.rs:71:13: replace && with ||
crates/sever-seal/src/ring.rs:70:13: replace && with ||
crates/sever-seal/src/ring.rs:127:9: replace <impl core::fmt::Debug for KeyRing>::fmt -> core::fmt::Result with Ok(Default::default())
crates/sever-seal/src/ring.rs:338:47: replace && with ||
crates/sever-seal/src/ring.rs:338:42: replace == with !=
crates/sever-seal/src/ring.rs:338:63: replace == with !=
crates/sever-seal/src/ring.rs:393:9: replace KeyRing::retain_stage with ()
crates/sever-seal/src/ring.rs:405:9: replace KeyRing::drop_collection with ()
crates/sever-seal/src/ring.rs:458:9: replace KeyRing::stage_is_empty -> bool with false
crates/sever-seal/src/ring.rs:458:9: replace KeyRing::stage_is_empty -> bool with true
crates/sever-seal/src/ring.rs:505:45: replace == with !=
crates/sever-seal/src/ring.rs:511:64: replace != with ==
crates/sever-seal/src/ring.rs:512:62: replace != with ==
crates/sever-seal/src/ring.rs:547:37: replace < with ==
crates/sever-seal/src/ring.rs:547:37: replace < with >
crates/sever-seal/src/ring.rs:555:9: replace KeyRing::finish_recovery with ()
```
