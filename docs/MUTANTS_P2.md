# Part 2 mutation survivors (P2-T9)

P2-T9 (Build §5.8) asks for a mutation score of at least 85 % over `sever-format`, `sever-wal`,
`sever-txn` and `sever-engine`, with **every surviving mutant triaged** here; `gates p2-mutants`
fails if a survivor's text is missing from this file. Tests come from those four crates plus
`sever-checkpoint` and `sever-appendstore`.

Exploratory runs (not gate runs; the gate run is in the ledger):

| Run | Tests | Missed | Score (caught / tested) |
|---|---|---|---|
| 7 Oct, before the coverage tests | as committed then | 130 | 582 / 713 = 81.6 % |
| 7 Oct ~23:25 UTC, HEAD then + coverage tests | + refusal, paged, stream, WAL, contract tests | 83 | 629 / 713 = 88.2 % |
| 8 Oct, 4913bd9 + triage tests | + the tests below | 60 | 652 / 713 = 91.4 % |

Tests added for this triage (each from a spec rule or a Build §3.4 contract rule): the P2-T4 test
now asserts the reader ran at all seven protocol steps; `p2_engine_checkpoints_itself_after_enough_wal`
bounds the checkpoint frequency; `p2_engine_passage_records_carry_increasing_sequence_numbers`
(§14.8); group sizes sum to N (INV-8); the 64 MiB default segment and a record filling a whole
segment (§12.3); a bad middle segment header; skipped `wal_seq`s refused; a repeated BEGIN;
removed-segment counts; field-size guards (§14.3, §14.4); a no-op SLOT_TRUNCATE; EP-6 binding of
each owner field (scrambled ID, group, n, key version); an EP-7 participant that writes only after
the commit point (refusing or silently resetting), which only a contract that really crashes sees.

The one timeout (`engine.rs:247: replace >= with < in maybe_checkpoint`, a checkpoint after every
transaction) is counted as not caught in the score.

## Equivalent: diagnostic output only

A `Debug` implementation replaced by one that prints nothing. Debug output is never part of the stored format or a result; the redaction tests check only that no ID, vector or key appears, which an empty output also satisfies.

```
crates/sever-engine/src/engine.rs:78:9: replace <impl core::fmt::Debug for Engine<E, S>>::fmt -> core::fmt::Result with Ok(Default::default())
crates/sever-format/src/file.rs:185:9: replace <impl core::fmt::Debug for Secrets>::fmt -> core::fmt::Result with Ok(Default::default())
crates/sever-format/src/slot.rs:23:9: replace <impl core::fmt::Debug for SlotBytes>::fmt -> core::fmt::Result with Ok(Default::default())
crates/sever-format/src/slot.rs:84:9: replace <impl core::fmt::Debug for SlotPayload>::fmt -> core::fmt::Result with Ok(Default::default())
crates/sever-format/src/store.rs:20:9: replace <impl core::fmt::Debug for StoreRecord>::fmt -> core::fmt::Result with Ok(Default::default())
crates/sever-format/src/wal.rs:118:9: replace <impl core::fmt::Debug for WalRecord>::fmt -> core::fmt::Result with Ok(Default::default())
crates/sever-format/src/wal.rs:304:9: replace <impl core::fmt::Debug for CoreRecord>::fmt -> core::fmt::Result with Ok(Default::default())
crates/sever-txn/src/participant.rs:49:9: replace <impl core::fmt::Debug for TxnDraft<'_, E>>::fmt -> core::fmt::Result with Ok(Default::default())
crates/sever-wal/src/lib.rs:110:9: replace <impl core::fmt::Debug for Wal>::fmt -> core::fmt::Result with Ok(Default::default())
```

## Equivalent: same value

`NoExtension` already encodes to empty vectors, the default `owned_types` is already empty, and `PlaintextSealer::sealer_id` is already 0 (DB-48).

```
crates/sever-txn/src/ext.rs:50:9: replace <impl StoredExtension for NoExtension>::encode_public -> Vec<u8> with vec![]
crates/sever-txn/src/ext.rs:56:9: replace <impl StoredExtension for NoExtension>::encode_group_secret -> Vec<u8> with vec![]
crates/sever-txn/src/ext.rs:62:9: replace <impl StoredExtension for NoExtension>::encode_record_secret -> Vec<u8> with vec![]
crates/sever-txn/src/participant.rs:74:9: replace TxnParticipant::owned_types -> &[RecordType] with Vec::leak(Vec::new())
crates/sever-txn/src/sealer.rs:115:9: replace <impl Sealer for PlaintextSealer>::sealer_id -> u16 with 0
```

## Equivalent in Part 2: a size that is 0 with no extension and the plaintext sealer (reachable in Parts 3–4)

`seal_overhead`, `envelope`, the extension fields and `seal_version` are all 0 or empty in Part 2 (DB-46, DB-48), so `+`/`-` of them, or dropping the field, cannot change a byte. Part 3's commitment extension (32 + 32 + 41 bytes) and Part 4's AES-GCM-SIV sealer (28-byte overhead, 60-byte envelope, rotating `seal_version`) make them reachable; the Appendix A size assertions of the P2-T7 spike and those parts' own tests must kill them.

```
crates/sever-format/src/group.rs:62:38: replace + with - in GroupHeader::encode
crates/sever-format/src/group.rs:113:38: replace + with - in GroupHeader::read
crates/sever-format/src/slot.rs:31:66: replace + with - in SlotBytes::encode
crates/sever-format/src/slot.rs:56:40: replace + with - in SlotBytes::read
crates/sever-format/src/slot.rs:58:42: replace - with + in SlotBytes::read
crates/sever-txn/src/records.rs:275:45: delete field envelope from struct SlotBytes expression in changeset_records
crates/sever-txn/src/records.rs:375:17: delete field seal_version from struct GroupHeader expression in changeset_records
```

## Unreachable in Part 2: participant outputs and the commit position

`delete_user` routes participant outputs (Part 3's certificates) to their requests, and `commit_wal_seq` is reported for Part 3's `database_lsn`; no Part 2 participant produces an output or reads the position, so no Part 2 test can observe either. Part 3's certificate tests (P3-T1, P3-T2) cover both.

```
crates/sever-engine/src/engine.rs:470:52: replace == with != in Engine<E, S>::delete_user
crates/sever-wal/src/lib.rs:225:33: replace - with + in Wal::write_txn
crates/sever-wal/src/lib.rs:225:33: replace - with / in Wal::write_txn
```

## Contract-suite internals (EP-6/EP-7 test support)

Inside the contract suites themselves. Payload patterns (`i * 7 % 251`, `len % 7`, `i % 256`) only need to differ between calls, which every variant still does; the transaction kind alternation in `drive` is ignored by the test participants; `tear_bytes` only changes how much of an interrupted write lands (torn writes are tested at every 512-byte offset by P2-T1); `< TXNS` vs `<= TXNS` only indexes past the end, where `get` returns `None` either way. The probe adapter `Shared` forwards every hook: a broken forward makes a *correct* participant fail the suite (loudly), never lets a wrong one pass; Parts 3 and 4 run real participants that use `sync_stores`, `phase_a` and `abort` through it, as the deleted P2-T7 spikes did.

```
crates/sever-txn/src/contract.rs:63:56: replace % with / in ep6_sealer_contract
crates/sever-txn/src/contract.rs:63:56: replace % with + in ep6_sealer_contract
crates/sever-txn/src/contract.rs:63:52: replace * with / in ep6_sealer_contract
crates/sever-txn/src/contract.rs:63:52: replace * with + in ep6_sealer_contract
crates/sever-txn/src/contract.rs:89:51: replace + with * in ep6_sealer_contract
crates/sever-txn/src/contract.rs:89:47: replace % with + in ep6_sealer_contract
crates/sever-txn/src/contract.rs:89:47: replace % with / in ep6_sealer_contract
crates/sever-txn/src/contract.rs:118:49: replace % with + in ep6_sealer_contract
crates/sever-txn/src/contract.rs:118:49: replace % with / in ep6_sealer_contract
crates/sever-txn/src/contract.rs:189:9: replace <impl TxnParticipant<NoExtension> for Shared>::id -> u16 with 0
crates/sever-txn/src/contract.rs:189:9: replace <impl TxnParticipant<NoExtension> for Shared>::id -> u16 with 1
crates/sever-txn/src/contract.rs:196:9: replace <impl TxnParticipant<NoExtension> for Shared>::pre_transaction -> core::result::Result<Option<crate::PreTxn>, sever_types::Error> with Ok(None)
crates/sever-txn/src/contract.rs:205:9: replace <impl TxnParticipant<NoExtension> for Shared>::sync_stores -> core::result::Result<(), sever_types::Error> with Ok(())
crates/sever-txn/src/contract.rs:208:9: replace <impl TxnParticipant<NoExtension> for Shared>::phase_a -> core::result::Result<(), sever_types::Error> with Ok(())
crates/sever-txn/src/contract.rs:211:9: replace <impl TxnParticipant<NoExtension> for Shared>::abort with ()
crates/sever-txn/src/contract.rs:234:28: replace == with != in drive
crates/sever-txn/src/contract.rs:234:24: replace % with / in drive
crates/sever-txn/src/contract.rs:234:24: replace % with + in drive
crates/sever-txn/src/contract.rs:321:17: delete field tear_bytes from struct FaultPlan expression in ep7_participant_contract
crates/sever-txn/src/contract.rs:328:27: replace < with <= in ep7_participant_contract
```

## Durability of directory entries after unlinking covered segments

After deleting covered WAL segments the directory is fsynced only if something was removed. The mutants sync in more or fewer cases. A lost unlink only leaves a covered segment behind, which recovery removes again (`p2_wal_recovery_reports_the_segments_it_removes`); a `while len > 1` vs `>= 1` loop is equivalent because the body needs a second segment.

```
crates/sever-wal/src/lib.rs:246:35: replace > with >= in Wal::remove_covered
crates/sever-wal/src/lib.rs:255:20: replace > with == in Wal::remove_covered
crates/sever-wal/src/lib.rs:255:20: replace > with < in Wal::remove_covered
crates/sever-wal/src/lib.rs:255:20: replace > with >= in Wal::remove_covered
crates/sever-wal/src/lib.rs:413:36: replace > with < in Wal::recover
```

## Where a record lands (segment rollover boundary)

`>` vs `>=` and `+` vs `*` in the rollover test move a record into the next segment earlier than necessary. Recovery reads across segments, so the committed transactions are the same; only file sizes change (64 MiB is a maximum, not an exact size).

```
crates/sever-wal/src/lib.rs:206:62: replace > with >= in Wal::write_txn
crates/sever-wal/src/lib.rs:206:42: replace + with * in Wal::write_txn
```

## Candidate filter before a CRC check (torn-tail detection)

`valid_record_after` filters candidate offsets (type byte, a plausible `wal_seq` window) before the CRC-checked parse that decides. Weakening the filter only lets more candidates reach the CRC check; the one semantic case, an older CRC-valid record past a torn tail, cannot occur: segments are append-only and recovery truncates before the next append, so no stale bytes follow the end of the log.

```
crates/sever-wal/src/lib.rs:460:13: replace && with || in valid_record_after
crates/sever-wal/src/lib.rs:459:48: replace && with || in valid_record_after
crates/sever-wal/src/lib.rs:459:53: replace < with <= in valid_record_after
```

## Defence in depth / unreachable guard

`n > MAX_GROUP_MEMBERS` is checked after `n == slot count`, so it needs 10^6 slots in a group to reach (INV-4 is enforced and tested in Part 1). The `S` check's `||` → `&&` leaves INV-6 to Part 1's `check_invariants`, which recovery runs next and which still refuses (`p2_engine_refuses_to_serve_on_a_violated_invariant`).

```
crates/sever-engine/src/recovery.rs:228:23: replace > with == in rebuild_collection
crates/sever-engine/src/recovery.rs:228:23: replace > with >= in rebuild_collection
crates/sever-engine/src/recovery.rs:251:29: replace || with && in rebuild_collection
```

## Equivalent on the only supported platform

`linux && x86_64` vs `linux || x86_64` differ only off Linux/x86-64, where Part 2 is not built (spec §12.8; the CI and every gate run on Linux x86-64).

```
crates/sever-engine/src/platform.rs:39:36: replace && with || in check_data_dir
```

## Equivalent: change-set overlay of a flush

Inside a flush the moved slots go to a new spawned group, whose base index is always 0, and the overlay and length map are only read again by a later change to the same group in the same change set, which Part 1 never produces; the SLOT_PUT records themselves use the unmutated index.

```
crates/sever-txn/src/records.rs:282:47: replace + with * in changeset_records
crates/sever-txn/src/records.rs:293:39: replace + with * in changeset_records
```
