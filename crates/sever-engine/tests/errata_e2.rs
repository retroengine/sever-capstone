//! Erratum E-2 (ERRATA.md): the engine never called EP-7's `pre_transaction`, so a participant
//! could not have a transaction of its own committed before the operation's (Build §3.3 EP-7: "may
//! request a separate committed transaction first"; spec §15.3 step 3: the on-demand log
//! checkpoint, "as its own committed transaction"). Found while building Part 3's
//! `LogParticipant` (Build 3-4 §1.5).

// Test code (clippy.toml allows these in #[test] functions; the helpers here are test code too).
#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::expect_used,
    clippy::panic
)]

use std::sync::{Arc, Mutex};

use sever_engine::{
    CollectionOptions, DeleteOutcome, Engine, EngineConfig, FailurePolicy, InsertRequest,
};
use sever_format::{RecordType, WalRecord};
use sever_index::NoExtension;
use sever_spec::spec;
use sever_txn::{PlaintextSealer, PreTxn, TxnDraft, TxnKind, TxnParticipant};
use sever_types::{CollectionId, Error};
use sever_vfs::{CrashPolicy, SimVfs};

const ARTEFACT: &[u8] = include_bytes!("../../../golden/p1_partition_small.svp");
const ID: u16 = 0x7E02;
const OPTS: CollectionOptions = CollectionOptions {
    spawn_target: 8,
    spawning_enabled: true,
    store_passages: false,
};

type Log = Arc<Mutex<Vec<String>>>;

/// Asks for a pre-transaction before every deletion and adds one record to every transaction;
/// writes down each call (and each replayed record with its transaction ID).
struct Asker {
    log: Log,
    fail_prepare: bool,
}

fn record(tag: &[u8]) -> (RecordType, Vec<u8>) {
    let mut p = ID.to_be_bytes().to_vec();
    p.extend_from_slice(tag);
    (RecordType::Extension, p)
}

impl TxnParticipant<NoExtension> for Asker {
    fn id(&self) -> u16 {
        ID
    }
    fn pre_transaction(
        &mut self,
        kind: TxnKind,
        _c: &CollectionId,
    ) -> Result<Option<PreTxn>, Error> {
        self.log.lock().unwrap().push(format!("pre {kind:?}"));
        Ok((kind == TxnKind::Delete).then(|| PreTxn {
            records: vec![record(b"pre")],
        }))
    }
    fn prepare(&mut self, d: &mut TxnDraft<'_, NoExtension>) -> Result<(), Error> {
        self.log.lock().unwrap().push("prepare".into());
        d.participant_records.push(record(b"main"));
        if self.fail_prepare {
            return Err(Error::IntegrityViolation { invariant: "test" });
        }
        Ok(())
    }
    fn after_commit(&mut self) -> Result<(), Error> {
        self.log.lock().unwrap().push("after_commit".into());
        Ok(())
    }
    fn abort(&mut self) {
        self.log.lock().unwrap().push("abort".into());
    }
    fn replay(&mut self, r: &WalRecord) -> Result<(), Error> {
        let tag = String::from_utf8_lossy(&r.payload[2..]).into_owned();
        self.log
            .lock()
            .unwrap()
            .push(format!("replay {tag} txn {}", r.txn_id));
        Ok(())
    }
}

struct Disks {
    data: SimVfs,
    keys: SimVfs,
}

impl Disks {
    fn open(&self, log: &Log, fail_prepare: bool) -> Engine<NoExtension, PlaintextSealer> {
        let asker = Asker {
            log: Arc::clone(log),
            fail_prepare,
        };
        Engine::open(
            Arc::new(self.data.clone()),
            Arc::new(self.keys.clone()),
            PlaintextSealer,
            NoExtension,
            vec![Box::new(asker)],
            EngineConfig {
                on_failure: FailurePolicy::Poison,
                ..EngineConfig::default()
            },
        )
        .unwrap()
    }
}

fn unit(i: usize) -> Vec<f32> {
    let mut v = vec![0.0; 16]; // the small artefact has d = 16
    v[i % 16] = 1.0;
    v
}

fn insert(db: &Engine<NoExtension, PlaintextSealer>, cid: CollectionId, id: &str, i: usize) {
    db.insert(
        cid,
        InsertRequest {
            record_id: id.into(),
            vector: unit(i),
            credential: (),
            passage: None,
        },
    )
    .unwrap();
}

fn take(log: &Log) -> Vec<String> {
    std::mem::take(&mut *log.lock().unwrap())
}

/// The transaction IDs of the replayed records tagged `tag`.
fn replayed(log: &[String], tag: &str) -> Vec<u64> {
    log.iter()
        .filter_map(|l| l.strip_prefix(&format!("replay {tag} txn ")))
        .map(|t| t.parse().unwrap())
        .collect()
}

#[test]
// oracle: A §15.3 steps 1–4 (step 3: "create one first, as its own committed transaction"; step 1: an absent record touches nothing); Build §3.3 EP-7 pre_transaction
#[spec("SR-15.3-3")]
fn p2_errata_e2_a_pre_transaction_commits_on_its_own_before_the_deletion() {
    let disks = Disks {
        data: SimVfs::new(),
        keys: SimVfs::new(),
    };
    let log: Log = Arc::default();
    let db = disks.open(&log, false);
    let cid = db.create_collection(ARTEFACT, OPTS).unwrap();
    insert(&db, cid, "a", 0);
    insert(&db, cid, "b", 1);
    take(&log);

    // An absent record touches nothing: no pre-transaction either (§15.3 step 1).
    assert_eq!(db.delete(cid, "zz").unwrap(), DeleteOutcome::AlreadyAbsent);
    assert!(take(&log).is_empty(), "nothing called for an absent record");

    // A deletion: its pre-transaction is committed (and confirmed) before the deletion is prepared.
    assert!(matches!(
        db.delete(cid, "a").unwrap(),
        DeleteOutcome::Deleted { .. }
    ));
    assert_eq!(
        take(&log),
        ["pre Delete", "after_commit", "prepare", "after_commit"]
    );
    db.close().unwrap();
    disks.data.restart(CrashPolicy::DropAll);
    disks.keys.restart(CrashPolicy::DropAll);

    // The pre-transaction stands alone even if the deletion that asked for it never commits.
    let db = disks.open(&log, true);
    take(&log);
    assert!(db.delete(cid, "b").is_err());
    assert_eq!(
        take(&log),
        ["pre Delete", "after_commit", "prepare", "abort"]
    );
    drop(db);
    disks.data.restart(CrashPolicy::DropAll);
    disks.keys.restart(CrashPolicy::DropAll);
    let db = disks.open(&log, false);
    let replay = take(&log);
    let (pre, main) = (replayed(&replay, "pre"), replayed(&replay, "main"));
    assert_eq!(pre.len(), 2, "both pre-transactions committed: {replay:?}");
    assert_eq!(
        main.len(),
        4,
        "create, two inserts, one deletion: {replay:?}"
    );
    let delete_txn = main[3];
    assert!(
        pre[0] < delete_txn,
        "the first pre-transaction precedes its deletion"
    );
    assert!(
        !main.contains(&pre[0]) && !main.contains(&pre[1]),
        "each is its own transaction"
    );
    assert!(
        pre[1] > delete_txn,
        "the second outlived its failed deletion"
    );
    assert!(
        matches!(db.delete(cid, "b").unwrap(), DeleteOutcome::Deleted { .. }),
        "b is still live"
    );
}
