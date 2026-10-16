//! Tests of the log's durable side. Expected values: the §14.6 record layouts written out by hand
//! (oracle A), RFC 9162 roots recomputed from the leaves (oracle A, §10.1), and Part 2's frozen
//! EP-7 contract suite, which crashes at every VFS operation (oracle C).

use std::sync::Arc;

use sever_appendstore::StoreRef;
use sever_format::{RecordType, WalRecord};
use sever_index::NoExtension;
use sever_spec::spec;
use sever_txn::contract::{ProbedParticipant, ep7_participant_contract};
use sever_txn::{TxnDraft, TxnKind, TxnParticipant};
use sever_types::{Error, GroupId};
use sever_vfs::{CrashPolicy, SimVfs, Vfs};

use crate::checkpoint::{Cosignature, LogCheckpoint};
use crate::leaf::{InsertLeaf, PLACEMENT_LEN, Placement, delete_leaf};
use crate::merkle::{MerkleTree, empty_root, leaf_hash};
use crate::store::*;

const CFG: LogStoreConfig = LogStoreConfig {
    sealer_id: 0,
    segment_bytes: 600, // small, so the stores roll over to new segments
};

fn genesis() -> Witnessed {
    Witnessed {
        checkpoint: LogCheckpoint {
            tree_size: 0,
            root: empty_root(),
            timestamp_ms: 7,
            epoch: 0,
            operator_signature: [0xA5; 64],
        },
        cosignatures: vec![],
    }
}

fn leaf(k: u8) -> InsertLeaf {
    InsertLeaf {
        collection_id: [k; 16],
        scrambled_id: [k.wrapping_add(1); 64],
        c_t: [k.wrapping_add(2); 32],
        user_public_key: [k.wrapping_add(3); 32],
        user_signature: [k.wrapping_add(4); 64],
    }
}

fn cert(k: u8) -> Vec<u8> {
    vec![k; 100 + usize::from(k)]
}

/// Where leaf `k` lands: frozen group `k` (inserts) or the holding area (deletions).
fn at(k: u8) -> Placement {
    Placement {
        group: GroupId::frozen(u16::from(k)).unwrap(),
        flush: None,
    }
}

fn holding() -> Placement {
    Placement {
        group: GroupId::Holding,
        flush: None,
    }
}

/// `text` zero-padded to 32 bytes (the stored form of a group ID, §13.2).
fn padded(text: &str) -> Vec<u8> {
    let mut v = text.as_bytes().to_vec();
    v.resize(32, 0);
    v
}

fn witnessed(size: u64, root: [u8; 32]) -> Witnessed {
    Witnessed {
        checkpoint: LogCheckpoint {
            tree_size: size,
            root,
            timestamp_ms: 1000 + size,
            epoch: 0,
            operator_signature: [0x5A; 64],
        },
        cosignatures: (0..4)
            .map(|i| Cosignature {
                witness_index: i,
                witness_epoch: 0,
                signature: [i; 64],
            })
            .collect(),
    }
}

fn open(v: &SimVfs) -> LogStore {
    LogStore::open(Arc::new(v.clone()), CFG, &genesis()).unwrap()
}

fn wal(records: &[LogRecord]) -> Vec<WalRecord> {
    records
        .iter()
        .enumerate()
        .map(|(i, r)| {
            let (ty, payload) = r.encode();
            WalRecord {
                ty,
                wal_seq: i as u64,
                txn_id: 1,
                payload,
            }
        })
        .collect()
}

#[test]
// oracle: A §14.6 (LOG_LEAF, LOG_CHECKPOINT, CERT_REF payloads; DB-81: the leaf index first), bytes written out by hand
#[spec("SR-14.6-4")]
fn p3_log_store_wal_records_have_the_section_14_6_layout() {
    let l = leaf(1);
    let h = leaf_hash(&l.to_bytes());
    let (ty, p) = LogRecord::Leaf {
        index: 0x0102,
        hash: h,
        placement: at(3),
        insert: Some(l.to_bytes()),
    }
    .encode();
    let mut want = vec![0, 0, 0, 0, 0, 0, 1, 2];
    want.extend_from_slice(&h);
    want.extend(padded("frozen-0003"));
    want.extend([0; 32]);
    want.extend_from_slice(&l.to_bytes());
    assert_eq!((ty, p.len()), (RecordType::LogLeaf, 8 + 32 + 64 + 209));
    assert_eq!(p, want);
    let (_, p) = LogRecord::Leaf {
        index: 3,
        hash: h,
        placement: holding(),
        insert: None,
    }
    .encode();
    assert_eq!(p.len(), 104, "a delete leaf's record carries no leaf bytes");
    let (ty, p) = LogRecord::CertRef {
        lsn: 9,
        at: StoreRef {
            segment: 2,
            offset: 0x10,
            len: 0x0304,
        },
        sha256: [0xCC; 32],
    }
    .encode();
    let mut want = vec![0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 0, 0, 2];
    want.extend_from_slice(&[0, 0, 0, 0, 0, 0, 0, 0x10, 0, 0, 3, 4]);
    want.extend_from_slice(&[0xCC; 32]);
    assert_eq!((ty, p), (RecordType::CertRef, want));
    let w = witnessed(5, [0x77; 32]);
    let (ty, p) = LogRecord::Checkpoint(w.clone()).encode();
    assert_eq!(ty, RecordType::LogCheckpoint);
    assert_eq!(p.len(), 116 + 1 + 4 * 69);
    assert_eq!(&p[..116], &w.checkpoint.to_bytes());
    assert_eq!(p[116], 4);
    assert_eq!(&p[117..117 + 69], &w.cosignatures[0].to_bytes());
    for r in [
        LogRecord::Checkpoint(w),
        LogRecord::Leaf {
            index: 3,
            hash: h,
            placement: holding(),
            insert: None,
        },
    ] {
        assert_eq!(LogRecord::decode(&wal(std::slice::from_ref(&r))[0]), Ok(r));
    }
}

/// Commits three insert leaves, a deletion and a checkpoint; returns the expected tree.
fn workload(s: &mut LogStore) -> MerkleTree {
    let mut want = MerkleTree::new();
    for k in 0..3 {
        s.stage_insert(&leaf(k), at(k)).unwrap();
        s.sync().unwrap();
        s.commit().unwrap();
        want.push(&leaf(k).to_bytes());
    }
    s.stage_checkpoint(witnessed(3, want.root(3).unwrap()))
        .unwrap();
    s.commit().unwrap();
    s.stage_delete(3, &cert(3), at(1)).unwrap();
    s.sync().unwrap();
    s.commit().unwrap();
    want.push(&delete_leaf(&cert(3)));
    want
}

#[test]
// oracle: A §10.1 (RFC 9162 roots of the leaves), §14.8 (certificates and insert leaves are public store records), §10.5, INV-15
#[spec("SR-14.8-2")]
fn p3_log_store_committed_state_survives_a_restart() {
    let v = SimVfs::new();
    let mut s = open(&v);
    let want = workload(&mut s);
    assert_eq!(s.tree().root(4), want.root(4));
    drop(s);
    v.restart(CrashPolicy::DropAll);
    let s = open(&v);
    assert_eq!(s.tree().size(), 4);
    assert_eq!(s.tree().root(4), want.root(4));
    for k in 0..3 {
        assert_eq!(s.insert_leaf(u64::from(k)), Ok(Some(leaf(k))));
    }
    assert_eq!(s.insert_leaf(3), Ok(None), "leaf 3 is a delete leaf");
    assert_eq!(s.certificate(3), Ok(Some(cert(3))));
    assert_eq!(s.certificate(2), Ok(None));
    let sizes: Vec<u64> = s
        .checkpoints()
        .iter()
        .map(|w| w.checkpoint.tree_size)
        .collect();
    assert_eq!(sizes, [0, 3], "the genesis, then the checkpoint at 3");
    assert_eq!(s.check_invariants(), Ok(()));
}

#[test]
// oracle: A §14.6 "Unreferenced bytes after a crash are ignored and overwritten"; §15.3 crash table: no certificate for a rolled-back deletion
#[spec("SR-15.3-5")]
fn p3_log_store_uncommitted_bytes_never_join_the_log() {
    let v = SimVfs::new();
    let mut s = open(&v);
    workload(&mut s);
    // A deletion whose bytes are durable but whose COMMIT never happened, then a crash.
    s.stage_delete(4, &cert(9), at(9)).unwrap();
    s.stage_insert(&leaf(9), at(9)).unwrap();
    s.sync().unwrap();
    drop(s);
    v.restart(CrashPolicy::KeepAll);
    let mut s = open(&v);
    assert_eq!(s.tree().size(), 4);
    assert_eq!(s.certificate(4), Ok(None));
    assert_eq!(s.insert_leaf(5), Ok(None));
    // The next transaction reuses index 4, and its entries win.
    s.stage_insert(&leaf(7), at(7)).unwrap();
    s.sync().unwrap();
    s.commit().unwrap();
    drop(s);
    v.restart(CrashPolicy::DropAll);
    let s = open(&v);
    assert_eq!(s.tree().size(), 5);
    assert_eq!(s.insert_leaf(4), Ok(Some(leaf(7))));
    assert_eq!(
        s.certificate(4),
        Ok(None),
        "the uncommitted certificate at 4 stays ignored"
    );
    assert_eq!(s.check_invariants(), Ok(()));
    // An aborted transaction is forgotten in memory too.
    let mut s = s;
    s.stage_insert(&leaf(8), at(8)).unwrap();
    s.abort();
    assert_eq!(s.next_index(), 5);
}

#[test]
// oracle: A §12.3 recovery replays committed records; §14.6 the WAL carries the log's records verbatim
#[spec("SR-14.6-4")]
fn p3_log_store_replay_restores_what_phase_c_never_wrote() {
    let v = SimVfs::new();
    let mut s = open(&v);
    let mut want = workload(&mut s);
    // Committed in the WAL, but the crash comes before phase C: only the WAL has it.
    let mut recs = vec![s.stage_insert(&leaf(5), at(5)).unwrap().1];
    recs.extend(s.stage_delete(5, &cert(5), holding()).unwrap());
    s.sync().unwrap();
    drop(s);
    want.push(&leaf(5).to_bytes());
    want.push(&delete_leaf(&cert(5)));
    let root6 = want.root(6).unwrap();
    v.restart(CrashPolicy::DropAll);
    let mut s = open(&v);
    assert_eq!(s.tree().size(), 4);
    let mut all = recs.clone();
    all.push(LogRecord::Checkpoint(witnessed(6, root6)));
    for r in wal(&all) {
        s.replay(&r).unwrap();
    }
    s.recover().unwrap();
    assert_eq!(s.tree().root(6), Some(root6));
    assert_eq!(s.certificate(5), Ok(Some(cert(5))));
    // Replaying again (a second crash during recovery) changes nothing.
    drop(s);
    v.restart(CrashPolicy::DropAll);
    let mut s = open(&v);
    for r in wal(&all) {
        s.replay(&r).unwrap();
    }
    s.recover().unwrap();
    assert_eq!((s.tree().size(), s.tree().root(6)), (6, Some(root6)));
    // A replayed leaf that differs from the committed one is refused.
    let wrong = LogRecord::Leaf {
        index: 0,
        hash: [0; 32],
        placement: holding(),
        insert: None,
    };
    assert!(matches!(
        s.replay(&wal(&[wrong])[0]),
        Err(Error::IntegrityViolation { .. })
    ));
}

#[test]
// oracle: A §21 INV-15 "The log root at every log-checkpoint size equals that checkpoint's root"
#[spec("SR-21-15")]
fn p3_log_store_a_checkpoint_root_that_differs_from_the_tree_is_refused() {
    let v = SimVfs::new();
    let mut s = open(&v);
    workload(&mut s);
    s.stage_checkpoint(witnessed(4, [0xEE; 32])).unwrap();
    s.commit().unwrap();
    assert!(matches!(
        s.check_invariants(),
        Err(Error::IntegrityViolation { .. })
    ));
    drop(s);
    let mut s = open(&v);
    assert!(s.recover().is_err(), "recovery refuses the log too");
    assert!(
        s.stage_checkpoint(witnessed(3, [1; 32])).is_err(),
        "sizes never shrink"
    );
    assert!(
        s.stage_checkpoint(witnessed(9, [1; 32])).is_err(),
        "only committed leaves"
    );
}

#[test]
fn p3_log_store_a_half_created_log_is_created_again() {
    let v = SimVfs::new();
    let vfs: Arc<dyn Vfs> = Arc::new(v.clone());
    sever_vfs::durable::create_dir(vfs.as_ref(), LOG_DIR).unwrap();
    sever_vfs::durable::create_dir(vfs.as_ref(), LEAVES_DIR).unwrap();
    let s = open(&v);
    assert_eq!(s.checkpoints(), &[genesis()]);
    assert_eq!(s.tree().size(), 0);
}

/// Part 2's EP-7 contract drives a participant without a change set: this one stages an insert
/// leaf in each insert transaction, and in each delete transaction a delete leaf with its
/// certificate and a checkpoint of the committed tree.
/// `None` when the store could not be opened (the contract crashes during its creation too).
struct Probe(Option<LogStore>);

impl Probe {
    fn s(&mut self) -> Result<&mut LogStore, Error> {
        self.0.as_mut().ok_or(Error::DurabilityFailure)
    }
}

impl TxnParticipant<NoExtension> for Probe {
    fn id(&self) -> u16 {
        3
    }
    fn owned_types(&self) -> &[RecordType] {
        &[
            RecordType::LogLeaf,
            RecordType::LogCheckpoint,
            RecordType::CertRef,
        ]
    }
    fn prepare(&mut self, d: &mut TxnDraft<'_, NoExtension>) -> Result<(), Error> {
        let s = self.s()?;
        let k = u8::try_from(s.next_index()).unwrap_or(0);
        let mut recs = Vec::new();
        if d.kind == TxnKind::Insert {
            recs.push(s.stage_insert(&leaf(k), at(k))?.1);
        } else {
            let size = s.tree().size();
            let root = s.tree().root(size).unwrap_or_default();
            recs.push(s.stage_checkpoint(witnessed(size, root))?);
            recs.extend(s.stage_delete(s.next_index(), &cert(k), holding())?);
        }
        d.participant_records
            .extend(recs.iter().map(LogRecord::encode));
        Ok(())
    }
    fn sync_stores(&mut self) -> Result<(), Error> {
        self.s()?.sync()
    }
    fn abort(&mut self) {
        if let Ok(s) = self.s() {
            s.abort();
        }
    }
    fn after_commit(&mut self) -> Result<(), Error> {
        self.s()?.commit()
    }
    fn replay(&mut self, r: &WalRecord) -> Result<(), Error> {
        self.s()?.replay(r)
    }
    fn recover(&mut self) -> Result<(), Error> {
        self.s()?.recover()
    }
    fn check_invariants(&self) -> Result<(), Error> {
        self.0
            .as_ref()
            .map_or(Err(Error::DurabilityFailure), LogStore::check_invariants)
    }
}

impl ProbedParticipant for Probe {
    fn digest(&self) -> Vec<u8> {
        let Some(s) = &self.0 else {
            return b"not open".to_vec();
        };
        let n = s.tree().size();
        let mut d = n.to_be_bytes().to_vec();
        d.extend_from_slice(&s.tree().root(n).unwrap_or_default());
        for i in 0..n {
            d.extend(s.certificate(i).ok().flatten().unwrap_or_default());
            d.extend(
                s.insert_leaf(i)
                    .ok()
                    .flatten()
                    .map(|l| l.to_bytes().to_vec())
                    .unwrap_or_default(),
            );
        }
        for w in s.checkpoints() {
            d.extend(w.to_bytes());
        }
        for p in s.export().map(|e| e.placements).unwrap_or_default() {
            d.extend(p.to_bytes());
        }
        d
    }
}

#[test]
// oracle: C Part 2's frozen EP-7 contract (Build §3.4): a crash at every VFS operation of five transactions, three crash policies
#[spec("SR-14.8-2", "SR-15.3-5")]
fn p3_log_store_passes_the_frozen_ep7_contract() {
    let make = |vfs: Arc<dyn Vfs>| -> Box<dyn ProbedParticipant> {
        Box::new(Probe(LogStore::open(vfs, CFG, &genesis()).ok()))
    };
    assert_eq!(ep7_participant_contract(&make), Ok(()));
}

#[test]
// oracle: A DB-86 placement layout (§10.5, §14.6 as amended): group (32, zero-padded text, §13.2) ‖ the group a flush created (32, or zeros), written out by hand
#[spec("SR-10.5-3", "SR-14.6-4")]
fn p3_log_store_placement_layout_and_strict_parse() {
    let p = Placement {
        group: GroupId::Holding,
        flush: Some(GroupId::Spawned([0xab; 8])),
    };
    let mut want = padded("holding");
    want.extend(padded("spawn-abababababababab"));
    assert_eq!((PLACEMENT_LEN, p.to_bytes().to_vec()), (64, want.clone()));
    assert_eq!(Placement::parse(&want), Ok(p));
    let mut f = padded("frozen-0012");
    f.extend([0; 32]);
    assert_eq!(
        Placement::parse(&f).map(|p| p.group),
        Ok(GroupId::frozen(12).unwrap())
    );
    // Refused: a non-canonical ID, bytes after the padding, a flush into a frozen group or the
    // holding area, a missing group, the wrong length.
    for bad in [
        [padded("frozen-12"), vec![0; 32]].concat(),
        [padded("holding"), vec![0; 31], vec![1]].concat(),
        [padded("holding\0x"), vec![0; 32]].concat(),
        [padded("holding"), padded("frozen-0001")].concat(),
        [padded("holding"), padded("holding")].concat(),
        [vec![0; 32], vec![0; 32]].concat(),
        want[..63].to_vec(),
    ] {
        assert!(Placement::parse(&bad).is_err(), "{bad:?}");
    }
}

#[test]
// oracle: A DB-86 (§10.5 as amended): every committed leaf's hash entry carries its placement; the export holds every leaf (insert leaf bytes, or 0x02 ‖ certificate, §10.2), its placement and every checkpoint; committed state only, restored from the WAL after a crash (§12.3)
#[spec("SR-10.5-3")]
fn p3_log_store_export_holds_every_leaf_with_its_placement() {
    let v = SimVfs::new();
    let mut s = open(&v);
    workload(&mut s);
    let flush = Placement {
        group: GroupId::Spawned([7; 8]),
        flush: Some(GroupId::Spawned([7; 8])),
    };
    // Committed in the WAL only (the crash comes before phase C), plus an uncommitted leaf.
    let rec = s.stage_insert(&leaf(4), flush).unwrap().1;
    s.sync().unwrap();
    drop(s);
    v.restart(CrashPolicy::DropAll);
    let mut s = open(&v);
    s.replay(&wal(&[rec])[0]).unwrap();
    s.recover().unwrap();
    s.stage_insert(&leaf(9), at(9)).unwrap();
    s.sync().unwrap(); // never committed
    drop(s);
    v.restart(CrashPolicy::KeepAll);
    let e = open(&v).export().unwrap();
    let leaves: Vec<Vec<u8>> = vec![
        leaf(0).to_bytes().to_vec(),
        leaf(1).to_bytes().to_vec(),
        leaf(2).to_bytes().to_vec(),
        delete_leaf(&cert(3)),
        leaf(4).to_bytes().to_vec(),
    ];
    assert_eq!(e.leaves, leaves);
    assert_eq!(e.placements, [at(0), at(1), at(2), at(1), flush]);
    let sizes: Vec<u64> = e
        .checkpoints
        .iter()
        .map(|w| w.checkpoint.tree_size)
        .collect();
    assert_eq!(sizes, [0, 3]);
}
