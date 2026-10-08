//! L1/L2/L10 tests of the WAL on `SimVfs` (spec §12.3).

use std::sync::Arc;

use proptest::prelude::*;
use sever_format::{RecordType, SegmentHeader};
use sever_spec::spec;
use sever_types::Error;
use sever_vfs::{CrashPolicy, FaultPlan, OpenMode, SimVfs, Vfs, read_all};

use super::*;

type Script = Vec<Vec<(RecordType, Vec<u8>)>>;

/// Transaction `i` of a script: `1 + i % 3` records of `size` bytes, each tagged with `i`.
fn txn(i: u8, size: usize) -> Vec<(RecordType, Vec<u8>)> {
    (0..1 + i % 3)
        .map(|j| {
            (
                RecordType::SlotTruncate,
                vec![i.wrapping_mul(7).wrapping_add(j); size],
            )
        })
        .collect()
}

fn script(n: u8, size: usize) -> Script {
    (0..n).map(|i| txn(i, size + usize::from(i) * 13)).collect()
}

fn cfg(segment_bytes: u64) -> WalConfig {
    WalConfig {
        sealer_id: 0,
        segment_bytes,
    }
}

/// A fresh database's WAL on a new simulated disk.
fn fresh(segment_bytes: u64) -> SimVfs {
    let v = SimVfs::new();
    Wal::create(Arc::new(v.clone()), cfg(segment_bytes), 1, 1).unwrap();
    v
}

fn open(v: &SimVfs, segment_bytes: u64) -> Result<(Wal, Vec<Txn>, RecoveryReport), Error> {
    Wal::recover(Arc::new(v.clone()), cfg(segment_bytes), 1, 1)
}

/// The payloads of recovered transactions, to compare with a script prefix.
fn contents(txns: &[Txn]) -> Script {
    txns.iter()
        .map(|t| {
            t.records
                .iter()
                .map(|r| (r.ty, r.payload.clone()))
                .collect()
        })
        .collect()
}

/// Runs `s` from the current state; returns how many commits were acknowledged.
fn run(v: &SimVfs, segment_bytes: u64, s: &Script) -> usize {
    let Ok((mut wal, _, _)) = open(v, segment_bytes) else {
        return 0;
    };
    let mut acked = 0;
    for t in s {
        if wal.commit(t).is_err() {
            break;
        }
        acked += 1;
    }
    acked
}

#[test]
// oracle: A §12.3 every committed transaction is recovered whole and in order; wal_seq counts BEGIN, records and COMMIT, by hand
#[spec("SR-12.3-2")]
fn p2_wal_commit_then_recover_round_trips_across_segments() {
    let seg = 600;
    let v = fresh(seg);
    let s = script(12, 40);
    assert_eq!(run(&v, seg, &s), 12);
    let (wal, txns, report) = open(&v, seg).unwrap();
    assert_eq!(contents(&txns), s);
    assert!(
        wal.segments().len() > 3,
        "the small segment size forced rollovers"
    );
    assert_eq!(report, RecoveryReport::default());
    let ids: Vec<u64> = txns.iter().map(|t| t.txn_id).collect();
    assert_eq!(ids, (1..=12).collect::<Vec<_>>());
    assert_eq!(wal.next_txn_id(), 13);
    let (mut live, _, _) = open(&fresh(seg), seg).unwrap();
    assert_eq!(live.appended(), 0);
    for t in &s {
        live.commit(t).unwrap();
    }
    assert_eq!(
        wal.appended(),
        live.appended(),
        "the checkpoint trigger survives a restart"
    );
    // wal_seq is continuous: BEGIN, records, COMMIT for every transaction.
    let records: u64 = s.iter().map(|t| t.len() as u64 + 2).sum();
    assert_eq!(wal.next_wal_seq(), 1 + records);
}

#[test]
// oracle: A §12.3 committed exactly when COMMIT is durable, §15.8: recovered = the acknowledged prefix, or that plus the one in flight
#[spec("SR-12.3-2", "SR-12.3-3")]
fn p2_wal_crash_at_every_operation_keeps_exactly_the_acknowledged_transactions() {
    let seg = 500;
    let base = fresh(seg);
    let s = script(6, 60);
    let dry = base.fork();
    dry.set_faults(FaultPlan::default());
    assert_eq!(run(&dry, seg, &s), 6);
    let ops = dry.ops_since_plan();
    assert!(ops > 20);
    for k in 1..=ops {
        for policy in [
            CrashPolicy::DropAll,
            CrashPolicy::KeepAll,
            CrashPolicy::Random(k),
        ] {
            let v = base.fork();
            v.set_faults(FaultPlan {
                crash_at_op: Some(k),
                tear_bytes: 9,
                ..FaultPlan::default()
            });
            let acked = run(&v, seg, &s);
            assert!(v.is_crashed());
            v.restart(policy);
            let (mut wal, txns, _) = open(&v, seg).unwrap();
            let got = contents(&txns);
            assert!(
                got == s[..acked] || got == s[..(acked + 1).min(s.len())],
                "k = {k}, {policy:?}: {} recovered, {acked} acknowledged",
                got.len()
            );
            // The tail was cut: a new transaction lands right after the last committed one.
            let more = txn(200, 30);
            wal.commit(&more).unwrap();
            let (_, again, _) = open(&v, seg).unwrap();
            let mut want = got.clone();
            want.push(more);
            assert_eq!(contents(&again), want, "k = {k}, {policy:?}");
        }
    }
}

#[test]
// oracle: A §12.3 a torn tail is discarded whole; cut bytes by hand from the 25-byte framing of §14.6
#[spec("SR-12.3-3")]
fn p2_wal_crash_at_every_512_byte_offset_of_a_large_write() {
    let seg = DEFAULT_SEGMENT_BYTES;
    let base = fresh(seg);
    let first = vec![txn(1, 100)];
    assert_eq!(run(&base, seg, &first), 1);
    // One transaction of about 6 KB, written with a single append.
    let big = vec![vec![(RecordType::SlotPut, vec![0xab; 6_000])]];
    // Its append is the first mutating operation of the next run (recovery writes nothing).
    for tear in (0..=6_100).step_by(512) {
        let v = base.fork();
        v.set_faults(FaultPlan {
            crash_at_op: Some(1),
            tear_bytes: tear,
            ..FaultPlan::default()
        });
        assert_eq!(run(&v, seg, &big), 0);
        v.restart(CrashPolicy::KeepAll);
        let (_, txns, report) = open(&v, seg).unwrap();
        assert_eq!(contents(&txns), first, "tear at {tear}");
        assert_eq!(report.truncated_bytes, tear.min(6_000 + 25 * 3) as u64);
    }
}

#[test]
// oracle: D metamorphic: recovery after a crashed recovery equals recovery of the same disk
#[spec("SR-12.3-3")]
fn p2_wal_a_crash_during_recovery_changes_nothing() {
    let seg = 400;
    let base = fresh(seg);
    let s = script(5, 50);
    let dry = base.fork();
    dry.set_faults(FaultPlan::default());
    run(&dry, seg, &s);
    let ops = dry.ops_since_plan();
    for k in (1..=ops).step_by(3) {
        let v = base.fork();
        v.set_faults(FaultPlan {
            crash_at_op: Some(k),
            tear_bytes: 30,
            ..FaultPlan::default()
        });
        run(&v, seg, &s);
        v.restart(CrashPolicy::KeepAll);
        let reference = v.fork();
        let (_, want, _) = open(&reference, seg).unwrap();
        let rec_dry = v.fork();
        rec_dry.set_faults(FaultPlan::default());
        open(&rec_dry, seg).unwrap();
        for j in 1..=rec_dry.ops_since_plan() {
            for policy in [CrashPolicy::DropAll, CrashPolicy::Random(j)] {
                let w = v.fork();
                w.set_faults(FaultPlan {
                    crash_at_op: Some(j),
                    ..FaultPlan::default()
                });
                assert!(open(&w, seg).is_err(), "recovery crashed");
                w.restart(policy);
                let (_, got, _) = open(&w, seg).unwrap();
                assert_eq!(got, want, "k = {k}, j = {j}, {policy:?}");
            }
        }
    }
}

// SB-13 must turn this red.
#[test]
// oracle: A §12.3 a transaction without a valid COMMIT is discarded whole; records written by hand
#[spec("SR-12.3-3")]
fn p2_wal_uncommitted_transaction_is_never_replayed() {
    let seg = DEFAULT_SEGMENT_BYTES;
    let v = fresh(seg);
    run(&v, seg, &vec![txn(1, 10)]);
    let (wal, _, _) = open(&v, seg).unwrap();
    let (next_seq, next_txn) = (wal.next_wal_seq(), wal.next_txn_id());
    drop(wal);
    // A transaction whose COMMIT never reached the disk: BEGIN and a record, durable.
    let mut f = v.open(&segment_path(1), OpenMode::Existing).unwrap();
    let begin = WalRecord {
        ty: RecordType::Begin,
        wal_seq: next_seq,
        txn_id: next_txn,
        payload: vec![],
    };
    let body = WalRecord {
        ty: RecordType::SlotTruncate,
        wal_seq: next_seq + 1,
        txn_id: next_txn,
        payload: vec![1, 2, 3],
    };
    f.append(&begin.encode()).unwrap();
    f.append(&body.encode()).unwrap();
    f.fsync().unwrap();
    let (wal, txns, report) = open(&v, seg).unwrap();
    assert_eq!(txns.len(), 1, "only the committed transaction");
    assert!(report.discarded_txn);
    assert_eq!(
        wal.next_wal_seq(),
        next_seq,
        "the discarded positions are reused"
    );
    assert_eq!(wal.next_txn_id(), next_txn);
}

#[test]
fn p2_wal_failure_poisons_the_log() {
    let seg = DEFAULT_SEGMENT_BYTES;
    let v = fresh(seg);
    let (mut wal, _, _) = open(&v, seg).unwrap();
    v.set_faults(FaultPlan {
        fail_sync_at: Some(1),
        ..FaultPlan::default()
    });
    assert_eq!(wal.commit(&txn(1, 5)), Err(Error::DurabilityFailure));
    assert_eq!(
        wal.commit(&txn(2, 5)),
        Err(Error::DurabilityFailure),
        "no retry"
    );
    v.restart(CrashPolicy::KeepAll);
    let (_, txns, _) = open(&v, seg).unwrap();
    assert!(
        txns.is_empty(),
        "the failed fsync lost the transaction, as Linux would"
    );
}

#[test]
fn p2_wal_rejects_a_record_larger_than_a_segment_before_writing() {
    let v = fresh(1_000);
    let (mut wal, _, _) = open(&v, 1_000).unwrap();
    v.reset_stats();
    assert!(
        wal.commit(&[(RecordType::SlotPut, vec![0; 1_000])])
            .is_err()
    );
    assert_eq!(v.stats().bytes_written, 0);
}

#[test]
// oracle: A §15.6 step 4 a segment is covered when the next one starts at or before the checkpoint position; worked out from the segment list
#[spec("SR-15.6-4")]
fn p2_wal_remove_covered_deletes_whole_segments_only() {
    let seg = 300;
    let v = fresh(seg);
    let s = script(10, 40);
    run(&v, seg, &s);
    let (mut wal, txns, _) = open(&v, seg).unwrap();
    let before = wal.segments().to_vec();
    // A checkpoint always covers whole transactions: cut at the BEGIN of transaction 6.
    let mid = txns[5].records[0].wal_seq - 1;
    let covered = (0..before.len() - 1)
        .take_while(|&i| before[i + 1].1 <= mid)
        .count();
    assert!(covered > 0);
    let removed = wal.remove_covered(mid).unwrap();
    assert_eq!(removed, covered as u64);
    assert_eq!(wal.segments(), &before[covered..]);
    v.restart(CrashPolicy::DropAll);
    let (_, after, _) = Wal::recover(Arc::new(v.clone()), cfg(seg), mid, 1).unwrap();
    let kept: Vec<&Txn> = txns
        .iter()
        .filter(|t| t.records[0].wal_seq >= mid)
        .collect();
    assert_eq!(after.iter().collect::<Vec<_>>(), kept);
}

#[test]
fn p2_wal_recovery_rejects_foreign_files_and_wrong_sealer() {
    let v = fresh(DEFAULT_SEGMENT_BYTES);
    v.open("wal/notes.txt", OpenMode::CreateNew).unwrap();
    assert_eq!(
        open(&v, DEFAULT_SEGMENT_BYTES).err(),
        Some(bad("§12.3 WAL file name"))
    );
    let v = fresh(DEFAULT_SEGMENT_BYTES);
    assert_eq!(
        Wal::recover(Arc::new(v.clone()), WalConfig::new(1), 1, 1).err(),
        Some(bad("DB-48 sealer_id"))
    );
}

#[test]
fn p2_wal_a_hole_inside_the_log_is_an_integrity_violation() {
    let seg = 300;
    let v = fresh(seg);
    run(&v, seg, &script(6, 40));
    // Flip a byte inside the first (not the newest) segment.
    let mut f = v.open(&segment_path(1), OpenMode::Existing).unwrap();
    let mut b = [0u8; 1];
    f.read_at(40, &mut b).unwrap();
    f.write_at(40, &[b[0] ^ 1]).unwrap();
    assert_eq!(open(&v, seg).err(), Some(bad("§12.3 hole inside the log")));
}

#[test]
fn p2_wal_a_torn_newest_segment_header_is_discarded() {
    let seg = DEFAULT_SEGMENT_BYTES;
    let v = fresh(seg);
    run(&v, seg, &vec![txn(1, 10)]);
    // Segment 2 created by a rollover that crashed before its header was written.
    let mut f = v.open(&segment_path(2), OpenMode::CreateNew).unwrap();
    f.write_at(0, &[0x53; 10]).unwrap();
    let (wal, txns, report) = open(&v, seg).unwrap();
    assert_eq!(txns.len(), 1);
    assert_eq!(report.removed_segments, 1);
    assert_eq!(wal.segments().len(), 1);
    assert_eq!(v.list(WAL_DIR).unwrap(), [format!("{:020}.wal", 1)]);
    let _ = SegmentHeader::LEN;
    let _ = read_all;
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(128))]

    // Any workload, any crash point, any tear, any policy: the recovered transactions are the
    // acknowledged ones, possibly plus the one in flight, whole (§12.3).
    #[test]
    // oracle: A §12.3 and §15.8 recovered = the acknowledged prefix, or that plus the one in flight
    #[spec("SR-12.3-2", "SR-12.3-3")]
    fn p2_wal_prop_recovery_is_acknowledged_prefix(
        n in 1u8..8,
        size in 1usize..200,
        seg in prop::sample::select(vec![256u64, 700, 4_096, DEFAULT_SEGMENT_BYTES]),
        crash in 1u64..60,
        tear in 0usize..400,
        seed in any::<u64>(),
    ) {
        let s = script(n, size);
        let v = fresh(seg.max(size as u64 * 4 + 200));
        let seg = seg.max(size as u64 * 4 + 200);
        v.set_faults(FaultPlan { crash_at_op: Some(crash), tear_bytes: tear, ..FaultPlan::default() });
        let acked = run(&v, seg, &s);
        v.restart(CrashPolicy::Random(seed));
        let (_, txns, _) = open(&v, seg).unwrap();
        let got = contents(&txns);
        prop_assert!(got == s[..acked] || got == s[..(acked + 1).min(s.len())]);
    }
}

// SB-11 must turn this red too: a damaged committed record is never mistaken for a torn tail.
#[test]
// oracle: A §12.7 every record has a CRC-32C; §12.3 only a tail may be discarded, so damage before valid records is refused; offset by hand
#[spec("SR-12.7-4", "SR-12.3-3")]
fn p2_wal_a_damaged_committed_record_is_refused_not_dropped() {
    let seg = DEFAULT_SEGMENT_BYTES;
    let v = fresh(seg);
    run(&v, seg, &script(6, 50));
    // Flip one payload byte of the second transaction, in the newest (only) segment.
    let mut f = v.open(&segment_path(1), OpenMode::Existing).unwrap();
    // Transaction 1: BEGIN (25), one record of 50 + 25, COMMIT (25). Transaction 2: BEGIN (25),
    // then its first record: 21 bytes of framing before the payload. Flip a payload byte.
    let at = (SegmentHeader::LEN + 25 + 75 + 25 + 25 + 21 + 10) as u64;
    let mut b = [0u8; 1];
    f.read_at(at, &mut b).unwrap();
    f.write_at(at, &[b[0] ^ 0x40]).unwrap();
    assert_eq!(
        open(&v, seg).err(),
        Some(bad("§12.3 corrupt record inside the log"))
    );
}

// ----- §12.3 recovery rules on hand-written logs -----
// The records below are written byte for byte after a fresh segment's header, so each test
// breaks exactly one rule of §12.3: a transaction is BEGIN, change records, COMMIT; wal_seq is
// contiguous across segments; transaction IDs increase; nothing past the last COMMIT is kept.

fn raw(ty: RecordType, wal_seq: u64, txn_id: u64) -> Vec<u8> {
    sever_format::WalRecord {
        ty,
        wal_seq,
        txn_id,
        payload: vec![0x11; 9],
    }
    .encode()
}

/// A fresh log whose first segment holds exactly `recs` (wal_seq from 1).
fn log_of(recs: &[(RecordType, u64)]) -> SimVfs {
    let v = fresh(DEFAULT_SEGMENT_BYTES);
    let mut f = v.open(&segment_path(1), OpenMode::Existing).unwrap();
    for (i, (ty, txn)) in recs.iter().enumerate() {
        f.append(&raw(*ty, i as u64 + 1, *txn)).unwrap();
    }
    v
}

use RecordType::{Begin as B, Commit as C, SlotPut as P};

#[test]
// oracle: A §12.3 BEGIN, change records, COMMIT; log written by hand
#[spec("SR-12.3-2")]
fn p2_wal_hand_written_log_with_two_transactions_recovers_both() {
    let v = log_of(&[(B, 1), (P, 1), (C, 1), (B, 2), (P, 2), (P, 2), (C, 2)]);
    let (wal, txns, report) = open(&v, DEFAULT_SEGMENT_BYTES).unwrap();
    assert_eq!(
        txns.iter()
            .map(|t| (t.txn_id, t.records.len()))
            .collect::<Vec<_>>(),
        [(1, 1), (2, 2)]
    );
    assert_eq!((wal.next_wal_seq(), wal.next_txn_id()), (8, 3));
    assert_eq!(report, RecoveryReport::default());
}

#[test]
// oracle: A §12.3 a transaction is a BEGIN, change records and a COMMIT; logs written by hand
#[spec("SR-12.3-2")]
fn p2_wal_refuses_a_broken_transaction_structure() {
    let bad_logs: [&[(RecordType, u64)]; 4] = [
        &[(P, 1)],                 // a change record outside a transaction
        &[(C, 1)],                 // COMMIT without BEGIN
        &[(B, 1), (B, 2)],         // BEGIN inside a transaction
        &[(B, 1), (P, 2), (C, 1)], // a record of another transaction
    ];
    for recs in bad_logs {
        assert_eq!(
            open(&log_of(recs), DEFAULT_SEGMENT_BYTES).err(),
            Some(bad("§12.3 transaction structure")),
            "{recs:?}"
        );
    }
    assert_eq!(
        open(&log_of(&[(B, 1), (C, 2)]), DEFAULT_SEGMENT_BYTES).err(),
        Some(bad("§12.3 transaction structure")),
        "COMMIT of another transaction"
    );
}

#[test]
fn p2_wal_refuses_transaction_ids_that_do_not_increase() {
    let v = log_of(&[(B, 2), (C, 2), (B, 2), (C, 2)]);
    assert_eq!(
        open(&v, DEFAULT_SEGMENT_BYTES).err(),
        Some(bad("§12.3 transaction order"))
    );
    // Below the floor the checkpoint gives (the next transaction ID it recorded).
    let v = log_of(&[(B, 1), (C, 1)]);
    assert_eq!(
        Wal::recover(Arc::new(v), cfg(DEFAULT_SEGMENT_BYTES), 1, 5).err(),
        Some(bad("§12.3 transaction order"))
    );
}

#[test]
// oracle: A §12.3 an open transaction at the tail is discarded whole, never repaired
#[spec("SR-12.3-3")]
fn p2_wal_an_open_transaction_at_the_tail_is_discarded_and_cut() {
    let v = log_of(&[(B, 1), (P, 1), (C, 1), (B, 2), (P, 2)]);
    let (wal, txns, report) = open(&v, DEFAULT_SEGMENT_BYTES).unwrap();
    assert_eq!(txns.len(), 1);
    assert!(report.discarded_txn);
    assert_eq!(report.truncated_bytes, 2 * raw(P, 0, 0).len() as u64);
    assert_eq!(
        wal.next_wal_seq(),
        4,
        "the cut records' wal_seqs are reused"
    );
    // The cut is on disk: a new transaction lands right after transaction 1.
    drop(wal);
    let (mut wal, _, _) = open(&v, DEFAULT_SEGMENT_BYTES).unwrap();
    wal.commit(&txn(9, 4)).unwrap();
    let (_, again, _) = open(&v, DEFAULT_SEGMENT_BYTES).unwrap();
    assert_eq!(again.iter().map(|t| t.txn_id).collect::<Vec<_>>(), [1, 2]);
}

#[test]
// oracle: A §12.3 nothing past the last valid COMMIT is kept
#[spec("SR-12.3-3")]
fn p2_wal_a_tail_record_with_the_wrong_wal_seq_is_a_torn_tail() {
    let v = log_of(&[(B, 1), (P, 1), (C, 1)]);
    let mut f = v.open(&segment_path(1), OpenMode::Existing).unwrap();
    f.append(&raw(B, 9, 2)).unwrap(); // valid CRC, but wal_seq 9 where 4 is due
    let (_, txns, report) = open(&v, DEFAULT_SEGMENT_BYTES).unwrap();
    assert_eq!(txns.len(), 1);
    assert!(report.truncated_bytes > 0);
}

#[test]
// oracle: A §15.6 step 3 and §15.7 replay starts at the first WAL position the MANIFEST names
#[spec("SR-15.7-1")]
fn p2_wal_recovery_starts_at_the_checkpoint_s_wal_position() {
    let v = log_of(&[(B, 1), (P, 1), (C, 1), (B, 2), (P, 2), (C, 2)]);
    let (wal, txns, _) =
        Wal::recover(Arc::new(v.clone()), cfg(DEFAULT_SEGMENT_BYTES), 4, 2).unwrap();
    assert_eq!(
        txns.iter().map(|t| t.txn_id).collect::<Vec<_>>(),
        [2],
        "transaction 1 is covered"
    );
    assert_eq!(
        wal.appended(),
        3 * raw(P, 0, 0).len() as u64,
        "bytes from the position on"
    );
    // A position the log does not reach, or one before its first segment, is refused.
    assert_eq!(
        Wal::recover(Arc::new(v.clone()), cfg(DEFAULT_SEGMENT_BYTES), 50, 1).err(),
        Some(bad("§12.3 WAL shorter than the checkpoint"))
    );
    assert_eq!(
        Wal::recover(Arc::new(v), cfg(DEFAULT_SEGMENT_BYTES), 0, 1).err(),
        Some(bad("§12.3 WAL position missing"))
    );
}

#[test]
// oracle: A §12.3 a committed transaction is never silently lost, so a missing segment is refused; §14.9 a wrong segment header is refused
#[spec("SR-12.3-2")]
fn p2_wal_refuses_a_missing_middle_segment_or_a_bad_older_header() {
    let seg = 300;
    let v = fresh(seg);
    run(&v, seg, &script(8, 40));
    let n = v.list(WAL_DIR).unwrap().len();
    assert!(n >= 3, "{n} segments");
    let gap = v.fork();
    gap.unlink(&segment_path(2)).unwrap();
    assert_eq!(open(&gap, seg).err(), Some(bad("§12.3 segment sequence")));
    let hdr = v.fork();
    let mut f = hdr.open(&segment_path(1), OpenMode::Existing).unwrap();
    f.write_at(0, &[0; 4]).unwrap();
    assert_eq!(open(&hdr, seg).err(), Some(bad("§12.3 segment header")));
}

#[test]
// oracle: A §14.9 segments are named wal/<segment_seq, 20 digits>.wal
#[spec("SR-14.9-1")]
fn p2_wal_refuses_segment_names_that_are_not_20_digits() {
    for name in [
        "0000000000000000000a.wal",
        "0000000000000000001.wal",
        "1.wal",
    ] {
        let v = fresh(DEFAULT_SEGMENT_BYTES);
        v.open(&format!("{WAL_DIR}/{name}"), OpenMode::CreateNew)
            .unwrap();
        assert_eq!(
            open(&v, DEFAULT_SEGMENT_BYTES).err(),
            Some(bad("§12.3 WAL file name")),
            "{name}"
        );
    }
}

// ----- gaps found by mutation testing (P2-T9 triage) -----

#[test]
fn p2_wal_default_segment_is_64_mib() {
    // §12.3 / §14 layout: "Segment files wal/<seq>.wal, 64 MiB each".
    assert_eq!(DEFAULT_SEGMENT_BYTES, 64 * 1024 * 1024);
    assert_eq!(WalConfig::new(0).segment_bytes, 64 * 1024 * 1024);
}

#[test]
// oracle: A §14.9 32-byte header + §14.6 25-byte framing; §12.3 the committed record is kept
#[spec("SR-12.3-2")]
fn p2_wal_a_record_filling_a_whole_segment_fits() {
    // The largest record is a segment minus its 32-byte header: exactly that size is accepted
    // and recovered; one byte more is refused before anything is written.
    let seg = 4096;
    let v = fresh(seg);
    let (mut wal, _, _) = open(&v, seg).unwrap();
    let max_payload = seg as usize - 32 - 25;
    wal.commit(&[(RecordType::SlotTruncate, vec![7; max_payload])])
        .unwrap();
    assert!(
        wal.commit(&[(RecordType::SlotTruncate, vec![7; max_payload + 1])])
            .is_err()
    );
    drop(wal);
    let (_, txns, _) = open(&v, seg).unwrap();
    assert_eq!(txns.len(), 1);
    assert_eq!(txns[0].records[0].payload.len(), max_payload);
}

#[test]
// oracle: A §14.9 segment header and its segment_seq; §12.3 no committed transaction dropped
#[spec("SR-12.3-2")]
fn p2_wal_refuses_a_bad_header_in_a_middle_segment() {
    let seg = 300;
    let v = fresh(seg);
    run(&v, seg, &script(8, 40));
    assert!(v.list(WAL_DIR).unwrap().len() >= 3);
    // Only the newest segment may have a torn header (it was being created at the crash).
    let mut f = v.open(&segment_path(2), OpenMode::Existing).unwrap();
    f.write_at(0, &[0; 4]).unwrap();
    assert_eq!(open(&v, seg).err(), Some(bad("§12.3 segment header")));
    // A valid header naming another segment number is just as wrong.
    let v = fresh(seg);
    run(&v, seg, &script(8, 40));
    let mut f = v.open(&segment_path(1), OpenMode::Existing).unwrap();
    let wrong = sever_format::SegmentHeader {
        sealer_id: 0,
        segment_seq: 9,
        first_wal_seq: 1,
    };
    f.write_at(0, &wrong.encode()).unwrap();
    assert_eq!(open(&v, seg).err(), Some(bad("§12.3 segment header")));
}

#[test]
// oracle: A §12.3 never repaired; §14.6 wal_seq positions follow one another
#[spec("SR-12.3-3")]
fn p2_wal_a_whole_transaction_with_wrong_wal_seqs_at_the_tail_is_refused() {
    // wal_seq is contiguous. CRC-valid records whose wal_seqs skip ahead cannot be a torn append
    // (a torn write leaves nothing valid after it): the log is damaged, and recovery refuses
    // rather than guess, never replaying them.
    let v = log_of(&[(B, 1), (P, 1), (C, 1)]);
    let mut f = v.open(&segment_path(1), OpenMode::Existing).unwrap();
    for (i, ty) in [B, P, C].into_iter().enumerate() {
        f.append(&raw(ty, 9 + i as u64, 2)).unwrap();
    }
    assert_eq!(
        open(&v, DEFAULT_SEGMENT_BYTES).err(),
        Some(bad("§12.3 corrupt record inside the log"))
    );
}

#[test]
// oracle: A §12.3 a transaction is one BEGIN, change records, one COMMIT
#[spec("SR-12.3-2")]
fn p2_wal_a_begin_repeated_inside_its_transaction_is_refused() {
    let v = log_of(&[(B, 1), (B, 1), (C, 1)]);
    assert_eq!(
        open(&v, DEFAULT_SEGMENT_BYTES).err(),
        Some(bad("§12.3 transaction structure"))
    );
}

#[test]
fn p2_wal_recovery_reports_the_segments_it_removes() {
    let seg = 300;
    // Covered segments (every record below the checkpoint's position) are removed and counted.
    let v = fresh(seg);
    run(&v, seg, &script(8, 40));
    let before = v.list(WAL_DIR).unwrap().len() as u64;
    let (wal, _, _) = open(&v, seg).unwrap();
    // A checkpoint taken now covers every record: its position is the next wal_seq.
    let all = wal.next_wal_seq();
    drop(wal);
    let (wal, txns, report) = Wal::recover(Arc::new(v.clone()), cfg(seg), all, 1).unwrap();
    assert!(txns.is_empty());
    assert_eq!(report.removed_segments, before - 1);
    assert_eq!(wal.segments().len(), 1);
    assert_eq!(v.list(WAL_DIR).unwrap().len(), 1);
    // Segments after the last complete transaction are removed and counted too.
    let v = fresh(seg);
    run(&v, seg, &script(3, 40));
    let n = v.list(WAL_DIR).unwrap().len() as u64;
    let next = n + 1;
    let (w, _, _) = open(&v, seg).unwrap();
    let h = sever_format::SegmentHeader {
        sealer_id: 0,
        segment_seq: next,
        first_wal_seq: w.next_wal_seq(),
    };
    drop(w);
    let mut f = v.open(&segment_path(next), OpenMode::CreateNew).unwrap();
    f.append(&h.encode()).unwrap();
    f.append(&raw(B, h.first_wal_seq, 99)).unwrap(); // an open transaction only
    let (_, _, report) = open(&v, seg).unwrap();
    assert_eq!(report.removed_segments, 1);
    assert_eq!(v.list(WAL_DIR).unwrap().len() as u64, n);
}
