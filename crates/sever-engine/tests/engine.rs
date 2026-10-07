//! L8/L10 tests of the engine on `SimVfs` (spec §12, §15, §16.1): restart, crash at every
//! operation of a mixed workload compared with a model index (Build §5.5's durable oracle, in
//! Rust), retries, collections, refusal to serve on a violated invariant, isolation, platform.

// Test code (clippy.toml allows these in #[test] functions; the helpers here are test code too).
#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::expect_used,
    clippy::panic
)]

use std::sync::{Arc, Mutex};

use sever_engine::hooks::CanonicalState;
use sever_engine::{
    CollectionOptions, DeleteOutcome, Engine, EngineConfig, FailurePolicy, InsertRequest,
    check_data_dir,
};
use sever_index::{DeleteRequest, HmacSha512Scrambler, Index, IndexConfig, NoExtension, Placement};
use sever_partition::PartitionArtefact;
use sever_spec::spec;
use sever_txn::{PlaintextSealer, Step};
use sever_types::{CollectionId, Error, GroupId};
use sever_vfs::{CrashPolicy, FaultPlan, OpenMode, SimVfs, Vfs};

const ARTEFACT: &[u8] = include_bytes!("../../../golden/p1_partition_small.svp");
type Db = Engine<NoExtension, PlaintextSealer>;

fn rows(key: &str) -> Vec<Vec<f32>> {
    let doc: serde_json::Value =
        serde_json::from_str(include_str!("../../../golden/p1_fixture_vectors.json")).unwrap();
    doc[key]
        .as_array()
        .unwrap()
        .iter()
        .map(|h| {
            let h = h.as_str().unwrap();
            (0..h.len() / 8)
                .map(|i| {
                    let b: Vec<u8> = (0..4)
                        .map(|j| {
                            u8::from_str_radix(&h[8 * i + 2 * j..8 * i + 2 * j + 2], 16).unwrap()
                        })
                        .collect();
                    f32::from_le_bytes(b.try_into().unwrap())
                })
                .collect()
        })
        .collect()
}

fn vectors() -> Vec<Vec<f32>> {
    let mut v = rows("ref");
    v.extend(rows("live"));
    v
}

fn cfg(checkpoint_every: u64) -> EngineConfig {
    EngineConfig {
        wal_segment_bytes: 64 * 1024,
        store_segment_bytes: 16 * 1024,
        checkpoint_every_wal_bytes: checkpoint_every,
        on_failure: FailurePolicy::Poison,
        config_hash: [5; 32],
    }
}

const OPTS: CollectionOptions = CollectionOptions {
    spawn_target: 8,
    spawning_enabled: true,
    store_passages: true,
};

/// A simulated data disk and key disk.
#[derive(Clone)]
struct Disks {
    data: SimVfs,
    keys: SimVfs,
}

impl Disks {
    fn new() -> Self {
        Self {
            data: SimVfs::new(),
            keys: SimVfs::new(),
        }
    }
    fn fork(&self) -> Self {
        Self {
            data: self.data.fork(),
            keys: self.keys.fork(),
        }
    }
    fn open(&self, checkpoint_every: u64) -> Result<Db, Error> {
        Engine::open(
            Arc::new(self.data.clone()),
            Arc::new(self.keys.clone()),
            PlaintextSealer,
            NoExtension,
            Vec::new(),
            cfg(checkpoint_every),
        )
    }
    fn restart(&self, p: CrashPolicy) {
        self.data.restart(p);
        self.keys.restart(p);
    }
    fn set_faults(&self, f: FaultPlan) {
        self.data.set_faults(f);
    }
}

#[derive(Clone, Debug)]
enum Op {
    Insert(String, usize, bool),
    Delete(String),
    DeleteUser(Vec<String>),
    Checkpoint,
}

/// A deterministic mixed workload over the fixture vectors.
fn workload(seed: u64, n: usize) -> Vec<Op> {
    let mut x = seed;
    let mut next = || {
        x = x
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        (x >> 33) as usize
    };
    let mut live: Vec<String> = Vec::new();
    let mut ops = Vec::new();
    let mut id = 0;
    for _ in 0..n {
        let r = next() % 10;
        if r < 6 || live.len() < 3 {
            let name = format!("r{id}");
            id += 1;
            ops.push(Op::Insert(name.clone(), next() % 240, r % 2 == 0));
            live.push(name);
        } else if r < 8 {
            let i = next() % live.len();
            ops.push(Op::Delete(live.swap_remove(i)));
        } else if r < 9 {
            let k = 2 + next() % 4;
            let mut ids = Vec::new();
            for _ in 0..k.min(live.len()) {
                let i = next() % live.len();
                ids.push(live.swap_remove(i));
            }
            ids.push("never-inserted".into());
            ops.push(Op::DeleteUser(ids));
        } else {
            ops.push(Op::Checkpoint);
        }
    }
    ops
}

/// Runs `ops` on the engine; returns how many were acknowledged before a failure.
fn run(db: &Db, cid: CollectionId, ops: &[Op], vs: &[Vec<f32>]) -> usize {
    for (i, op) in ops.iter().enumerate() {
        let r = match op {
            Op::Insert(id, v, text) => db
                .insert(
                    cid,
                    InsertRequest {
                        record_id: id.clone(),
                        vector: vs[*v].clone(),
                        credential: (),
                        passage: text.then(|| format!("passage of {id}").into_bytes()),
                    },
                )
                .map(|_| ()),
            Op::Delete(id) => db.delete(cid, id).map(|_| ()),
            Op::DeleteUser(ids) => {
                let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
                db.delete_user(cid, &refs).map(|_| ())
            }
            Op::Checkpoint => db.storage_checkpoint_now(),
        };
        match r {
            Ok(()) => {}
            Err(Error::DurabilityFailure) => return i,
            Err(e) => panic!("op {i}: {e}"),
        }
    }
    ops.len()
}

/// The oracle: Part 1's index (proven equal to the reference model by P1-T2) with no storage.
fn model_states(ops: &[Op], vs: &[Vec<f32>]) -> Vec<CanonicalState> {
    let art = PartitionArtefact::parse(ARTEFACT).unwrap();
    let mut ix = Index::new(
        &art,
        IndexConfig {
            spawning_enabled: true,
            spawn_target: 8,
        },
        NoExtension,
        HmacSha512Scrambler::new(&[0; 64]),
        CollectionId::from_bytes([0; 16]),
    )
    .unwrap();
    let mut ids: Vec<String> = Vec::new();
    let state = |ix: &Index<NoExtension, HmacSha512Scrambler>, ids: &[String]| {
        let mut groups: Vec<(String, Vec<u8>)> = ix
            .group_ids()
            .into_iter()
            .filter_map(|g| ix.blob(&g).map(|b| (g.as_text(), b)))
            .collect();
        groups.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
        let mut holding: Vec<String> = ids
            .iter()
            .filter(|i| ix.location(i) == Some(GroupId::Holding))
            .cloned()
            .collect();
        holding.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
        holding.dedup();
        let s = ix.stats();
        CanonicalState {
            groups,
            holding,
            big_n: s.big_n,
            k: s.k,
        }
    };
    let mut out = vec![state(&ix, &ids)];
    for op in ops {
        match op {
            Op::Insert(id, v, _) => {
                ix.insert(sever_index::InsertRequest {
                    record_id: id.clone(),
                    vector: vs[*v].clone(),
                    credential: (),
                })
                .unwrap();
                ids.push(id.clone());
            }
            Op::Delete(id) => {
                ix.delete(DeleteRequest {
                    record_id: id.clone(),
                })
                .unwrap();
            }
            Op::DeleteUser(list) => {
                ix.delete_many(
                    list.iter()
                        .map(|i| DeleteRequest {
                            record_id: i.clone(),
                        })
                        .collect(),
                )
                .unwrap();
            }
            Op::Checkpoint => {}
        }
        out.push(state(&ix, &ids));
    }
    out
}

/// A new database with one collection.
fn base() -> (Disks, CollectionId) {
    let disks = Disks::new();
    let db = disks.open(1 << 30).unwrap();
    let cid = db.create_collection(ARTEFACT, OPTS).unwrap();
    (disks, cid)
}

#[test]
#[spec("SR-15.7-1", "SR-12.4-1")]
fn p2_engine_state_survives_close_and_reopen() {
    let (disks, cid) = base();
    let vs = vectors();
    let ops = workload(42, 80);
    let db = disks.open(1 << 30).unwrap();
    assert_eq!(run(&db, cid, &ops, &vs), ops.len());
    let before = db.canonical_state(cid).unwrap();
    let hits = db.search(cid, &vs[3], 10).unwrap();
    assert_eq!(
        before,
        model_states(&ops, &vs).pop().unwrap(),
        "engine = model"
    );
    db.close().unwrap();
    disks.restart(CrashPolicy::DropAll);
    let db = disks.open(1 << 30).unwrap();
    assert_eq!(db.canonical_state(cid).unwrap(), before);
    assert_eq!(db.search(cid, &vs[3], 10).unwrap(), hits);
    assert_eq!(db.collections(), vec![cid]);
}

#[test]
#[spec("SR-15.7-1", "SR-12.3-2", "SR-12.3-3", "SR-12.4-2")]
fn p2_engine_crash_at_every_operation_recovers_an_oracle_state() {
    let vs = vectors();
    let (disks, cid) = base();
    let ops = workload(7, 40);
    let want = model_states(&ops, &vs);
    // A small checkpoint threshold, so checkpoints happen inside the workload too.
    let every = 20_000;
    let dry = disks.fork();
    dry.set_faults(FaultPlan::default());
    {
        let db = dry.open(every).unwrap();
        assert_eq!(run(&db, cid, &ops, &vs), ops.len());
    }
    let total = dry.data.ops_since_plan();
    assert!(total > 100, "{total} operations");
    let mut double = 0;
    for k in 1..=total {
        for policy in [
            CrashPolicy::DropAll,
            CrashPolicy::KeepAll,
            CrashPolicy::Random(k),
        ] {
            let d = disks.fork();
            d.set_faults(FaultPlan {
                crash_at_op: Some(k),
                tear_bytes: (k as usize * 37) % 700,
                ..FaultPlan::default()
            });
            let acked = {
                let db = d.open(every).unwrap();
                run(&db, cid, &ops, &vs)
            };
            assert!(acked < ops.len(), "k = {k}: the crash happened");
            d.restart(policy);
            let got = d.open(every).unwrap().canonical_state(cid).unwrap();
            assert!(
                got == want[acked] || got == want[acked + 1],
                "k = {k}, {policy:?}: recovered state is neither {acked} nor {} ops",
                acked + 1
            );
            // Now and then, crash again during recovery itself (recovery is idempotent).
            if k % 7 == 0 && policy == CrashPolicy::KeepAll {
                let again = disks.fork();
                again.set_faults(FaultPlan {
                    crash_at_op: Some(k),
                    ..FaultPlan::default()
                });
                {
                    let db = again.open(every).unwrap();
                    run(&db, cid, &ops, &vs);
                }
                again.restart(CrashPolicy::KeepAll);
                let first = again.fork();
                let expected = first.open(every).unwrap().canonical_state(cid).unwrap();
                again.set_faults(FaultPlan {
                    crash_at_op: Some(1 + k % 3),
                    ..FaultPlan::default()
                });
                let _ = again.open(every);
                again.restart(CrashPolicy::Random(k));
                let got = again.open(every).unwrap().canonical_state(cid).unwrap();
                assert_eq!(got, expected, "k = {k}: double crash");
                double += 1;
            }
        }
    }
    assert!(double > 10);
}

#[test]
#[spec("SR-15.1-2", "SR-3.2-3")]
fn p2_engine_insert_retry_is_a_duplicate_with_the_same_commitment() {
    let (disks, cid) = base();
    let db = disks.open(1 << 30).unwrap();
    let v = rows("ref")[0].clone();
    let req = |v: Vec<f32>| InsertRequest {
        record_id: "doc-1".into(),
        vector: v,
        credential: (),
        passage: None,
    };
    db.insert(cid, req(v.clone())).unwrap();
    assert_eq!(
        db.insert(cid, req(v)),
        Err(Error::DuplicateRecord {
            same_commitment: true
        })
    );
    assert_eq!(
        db.insert(cid, req(rows("ref")[1].clone())),
        Err(Error::DuplicateRecord {
            same_commitment: false
        })
    );
}

#[test]
#[spec("SR-15.4-1", "SR-5.4-2")]
fn p2_engine_delete_retry_is_already_absent() {
    let (disks, cid) = base();
    let db = disks.open(1 << 30).unwrap();
    db.insert(
        cid,
        InsertRequest {
            record_id: "doc".into(),
            vector: rows("ref")[0].clone(),
            credential: (),
            passage: Some(b"text".to_vec()),
        },
    )
    .unwrap();
    assert_eq!(db.passage(cid, "doc").unwrap(), Some(b"text".to_vec()));
    assert!(matches!(
        db.delete(cid, "doc").unwrap(),
        DeleteOutcome::Deleted { .. }
    ));
    assert_eq!(db.delete(cid, "doc").unwrap(), DeleteOutcome::AlreadyAbsent);
    assert_eq!(db.passage(cid, "doc").unwrap(), None);
}

#[test]
#[spec("SR-16.1-1", "SR-15.9-1")]
fn p2_engine_collections_are_isolated_and_drop_leaves_the_other_untouched() {
    let (disks, a) = base();
    let db = disks.open(1 << 30).unwrap();
    let b = db.create_collection(ARTEFACT, OPTS).unwrap();
    assert_ne!(a, b);
    let vs = vectors();
    run(&db, a, &workload(1, 30), &vs);
    let a_state = db.canonical_state(a).unwrap();
    run(&db, b, &workload(2, 30), &vs);
    assert_eq!(
        db.canonical_state(a).unwrap(),
        a_state,
        "b's writes do not touch a"
    );
    db.drop_collection(b).unwrap();
    assert_eq!(db.canonical_state(a).unwrap(), a_state);
    assert_eq!(db.stats(b).err(), Some(Error::UnknownCollection));
    assert_eq!(db.drop_collection(b).err(), Some(Error::UnknownCollection));
    db.close().unwrap();
    disks.restart(CrashPolicy::DropAll);
    let db = disks.open(1 << 30).unwrap();
    assert_eq!(db.collections(), vec![a]);
    assert_eq!(db.canonical_state(a).unwrap(), a_state);
}

#[test]
#[spec("SR-15.7-2")]
fn p2_engine_refuses_to_serve_on_a_violated_invariant() {
    let (disks, cid) = base();
    {
        let db = disks.open(1 << 30).unwrap();
        run(&db, cid, &workload(3, 20), &vectors());
        db.close().unwrap();
    }
    // Change one stored vector component in the current checkpoint and write the checkpoint
    // again, so every CRC and format check passes: only the invariant check can see it (INV-6).
    let layout = sever_format::Layout::plain(16);
    let m = sever_checkpoint::read_manifest(&disks.data, 0)
        .unwrap()
        .unwrap();
    let (mut meta, mut img) = sever_checkpoint::load(&disks.data, &m, &|_| layout).unwrap();
    let coll = img.collections.values_mut().next().unwrap();
    let g = coll
        .groups
        .iter_mut()
        .find(|g| !g.slots.is_empty())
        .unwrap();
    let mut p = sever_format::SlotPayload::parse(&g.slots[0].sealed_payload, &layout).unwrap();
    p.x[0] ^= 1;
    g.slots[0].sealed_payload = p.encode(&layout).unwrap();
    meta.checkpoint_id += 1;
    sever_checkpoint::write(&disks.data, 0, &img, &meta, &|_| layout).unwrap();
    match disks.open(1 << 30) {
        Err(Error::IntegrityViolation { invariant }) => {
            assert!(
                invariant.contains("INV-6") || invariant.contains("§9.7"),
                "{invariant}"
            )
        }
        other => panic!("served a corrupt database: {other:?}"),
    }
}

#[test]
#[spec("SR-12.7-2")]
fn p2_engine_failed_fsync_poisons_and_restart_recovers() {
    let (disks, cid) = base();
    let db = disks.open(1 << 30).unwrap();
    let v = rows("ref")[0].clone();
    disks.set_faults(FaultPlan {
        fail_sync_at: Some(1),
        ..FaultPlan::default()
    });
    let r = db.insert(
        cid,
        InsertRequest {
            record_id: "x".into(),
            vector: v.clone(),
            credential: (),
            passage: None,
        },
    );
    assert_eq!(r.err(), Some(Error::DurabilityFailure));
    assert!(db.is_poisoned());
    assert_eq!(db.search(cid, &v, 3).err(), Some(Error::DurabilityFailure));
    drop(db);
    disks.restart(CrashPolicy::KeepAll);
    let db = disks.open(1 << 30).unwrap();
    assert_eq!(
        db.location(cid, "x"),
        None,
        "the failed insert was never acknowledged"
    );
}

#[test]
#[spec("SR-12.5-1", "SR-12.5-2")]
fn p2_engine_a_reader_at_every_protocol_step_sees_before_or_after() {
    let (disks, cid) = base();
    let db = Arc::new(disks.open(1 << 30).unwrap());
    let vs = vectors();
    run(&db, cid, &workload(9, 30), &vs);
    let seen: Arc<Mutex<Vec<(Step, CanonicalState)>>> = Arc::new(Mutex::new(Vec::new()));
    let weak = Arc::downgrade(&db);
    let log = Arc::clone(&seen);
    db.set_step_hook(Some(Box::new(move |s| {
        if let Some(db) = weak.upgrade() {
            log.lock()
                .unwrap()
                .push((s, db.canonical_state(cid).unwrap()));
        }
    })));
    let renamed = |op: Op| match op {
        Op::Insert(id, v, t) => Op::Insert(format!("b-{id}"), v, t),
        Op::Delete(id) => Op::Delete(format!("b-{id}")),
        Op::DeleteUser(ids) => Op::DeleteUser(ids.into_iter().map(|i| format!("b-{i}")).collect()),
        Op::Checkpoint => Op::Checkpoint,
    };
    for op in workload(10, 15).into_iter().map(renamed) {
        let before = db.canonical_state(cid).unwrap();
        seen.lock().unwrap().clear();
        run(&db, cid, std::slice::from_ref(&op), &vs);
        let after = db.canonical_state(cid).unwrap();
        for (step, state) in seen.lock().unwrap().iter() {
            let applied = matches!(step, Step::Applied | Step::PhaseC);
            let want = if applied { &after } else { &before };
            assert_eq!(state, want, "{op:?} at {step:?}: a mixed or early state");
        }
    }
    db.set_step_hook(None);
}

#[test]
#[spec("SR-12.9-1", "SR-12.9-2")]
fn p2_engine_platform_checks() {
    let target = std::path::Path::new(env!("CARGO_TARGET_TMPDIR"));
    assert!(!check_data_dir(target, false).unwrap().overridden, "ext4");
    let shm = std::path::Path::new("/dev/shm");
    assert!(matches!(
        check_data_dir(shm, false),
        Err(Error::PlatformUnsafe { .. })
    ));
    assert!(check_data_dir(shm, true).unwrap().overridden);
    let dir = target.join(format!("lock-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let first = sever_engine::EngineLock::acquire(&dir).unwrap();
    assert!(matches!(
        sever_engine::EngineLock::acquire(&dir),
        Err(Error::PlatformUnsafe { .. })
    ));
    drop(first);
    sever_engine::EngineLock::acquire(&dir).unwrap();
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn p2_engine_refuses_a_data_directory_with_foreign_files() {
    let disks = Disks::new();
    disks.data.open("notes.txt", OpenMode::CreateNew).unwrap();
    assert!(matches!(
        disks.open(1 << 30),
        Err(Error::IntegrityViolation { .. })
    ));
}

#[test]
fn p2_engine_a_half_created_database_is_cleared_and_created_again() {
    let disks = Disks::new();
    let dry = disks.fork();
    dry.set_faults(FaultPlan::default());
    dry.open(1 << 30).unwrap();
    for k in 1..dry.data.ops_since_plan() {
        let d = disks.fork();
        d.set_faults(FaultPlan {
            crash_at_op: Some(k),
            ..FaultPlan::default()
        });
        assert!(d.open(1 << 30).is_err());
        d.restart(CrashPolicy::Random(k));
        let db = d.open(1 << 30).unwrap();
        assert!(db.collections().is_empty(), "k = {k}");
    }
}

#[test]
#[spec("SR-17-2")]
fn p2_engine_unknown_collection_and_bad_requests_are_typed() {
    let (disks, cid) = base();
    let db = disks.open(1 << 30).unwrap();
    let other = CollectionId::from_bytes([9; 16]);
    assert_eq!(
        db.search(other, &rows("ref")[0], 3).err(),
        Some(Error::UnknownCollection)
    );
    let bad = |id: &str, v: Vec<f32>| {
        db.insert(
            cid,
            InsertRequest {
                record_id: id.into(),
                vector: v,
                credential: (),
                passage: None,
            },
        )
        .err()
        .unwrap()
    };
    assert_eq!(bad("ok", vec![0.5; 3]), Error::WrongDimension);
    assert!(
        !bad("12345", rows("ref")[0].clone())
            .to_string()
            .contains("12345")
    );
    assert!(matches!(
        bad("12345", rows("ref")[0].clone()),
        Error::InvalidRecordId(_)
    ));
    assert_eq!(bad("ok", vec![1.0; 16]), Error::NotNormalised);
    assert!(db.create_collection(&ARTEFACT[..100], OPTS).is_err());
    let _ = Placement::Holding;
}

/// A database written by the engine, then one stored fact changed in its checkpoint, which is
/// written again with valid CRCs: only the startup invariant check (§12.4, §21) can see it.
fn open_tampered(f: impl FnOnce(&mut sever_format::CollectionImage)) -> Result<Db, Error> {
    let (disks, cid) = base();
    {
        let db = disks.open(1 << 30).unwrap();
        run(&db, cid, &workload(3, 60), &vectors());
        db.close().unwrap();
    }
    let layout = sever_format::Layout::plain(16);
    let m = sever_checkpoint::read_manifest(&disks.data, 0)
        .unwrap()
        .unwrap();
    let (mut meta, mut img) = sever_checkpoint::load(&disks.data, &m, &|_| layout).unwrap();
    f(img.collections.get_mut(&cid).unwrap());
    meta.checkpoint_id += 1;
    sever_checkpoint::write(&disks.data, 0, &img, &meta, &|_| layout).unwrap();
    disks.open(1 << 30)
}

fn refused_for(r: Result<Db, Error>, rule: &str) {
    match r {
        Err(Error::IntegrityViolation { invariant }) => {
            assert!(
                invariant.contains(rule),
                "refused for {invariant}, not {rule}"
            )
        }
        Err(e) => panic!("refused with {e:?}, not IntegrityViolation({rule})"),
        Ok(_) => panic!("served a database that breaks {rule}"),
    }
}

fn holding(c: &mut sever_format::CollectionImage) -> &mut sever_format::GroupImage {
    c.groups
        .iter_mut()
        .find(|g| g.header.group_id == GroupId::Holding)
        .unwrap()
}

#[test]
#[spec("SR-15.7-2")]
fn p2_engine_refuses_groups_out_of_order() {
    // §5.1: frozen groups in label order, then the holding area, then spawned groups.
    refused_for(open_tampered(|c| c.groups.swap(0, 4)), "§5.1 group order");
    refused_for(open_tampered(|c| c.groups.swap(0, 1)), "§5.1 frozen group");
}

#[test]
#[spec("SR-15.7-2")]
fn p2_engine_refuses_a_frozen_centroid_that_differs_from_the_artefact() {
    refused_for(
        open_tampered(|c| {
            c.groups[2].header.centroid[5] =
                f64::from_bits(c.groups[2].header.centroid[5].to_bits() ^ 1)
        }),
        "§5.1 frozen group",
    );
}

#[test]
#[spec("SR-15.7-2")]
fn p2_engine_refuses_a_missing_holding_area() {
    refused_for(
        open_tampered(|c| {
            c.groups.truncate(4);
            c.locator
                .retain(|_, (g, _)| g.as_text().starts_with("frozen"));
        }),
        "§5.1 holding area missing",
    );
}

#[test]
#[spec("SR-15.7-2")]
fn p2_engine_refuses_n_that_differs_from_the_slot_count() {
    refused_for(open_tampered(|c| c.groups[1].header.n += 1), "INV-6");
}

#[test]
#[spec("SR-15.7-2")]
fn p2_engine_refuses_a_slot_whose_scrambled_id_is_not_its_record_s() {
    refused_for(
        open_tampered(|c| {
            let g = c.groups.iter_mut().find(|g| !g.slots.is_empty()).unwrap();
            let old = g.slots[0].scrambled_id;
            let new = sever_types::ScrambledId::from_bytes([0xee; 64]);
            g.slots[0].scrambled_id = new;
            let at = c.locator.remove(&old).unwrap();
            c.locator.insert(new, at);
            if let Some(p) = c.payload_refs.remove(&old) {
                c.payload_refs.insert(new, p);
            }
        }),
        "§9.7 scrambled ID",
    );
}

#[test]
#[spec("SR-15.7-2")]
fn p2_engine_refuses_two_live_records_with_one_id() {
    // §3.2 rule 3: the same record in a frozen group and again in the holding area.
    refused_for(
        open_tampered(|c| {
            let slot = c
                .groups
                .iter()
                .find(|g| g.header.group_id != GroupId::Holding && !g.slots.is_empty())
                .unwrap()
                .slots[0]
                .clone();
            let h = holding(c);
            h.slots.push(slot);
            h.header.n += 1;
        }),
        "§3.2 one live record per ID",
    );
}

#[test]
#[spec("SR-15.7-2")]
fn p2_engine_refuses_a_locator_that_differs_from_the_slots() {
    refused_for(
        open_tampered(|c| {
            let k = *c.locator.keys().next().unwrap();
            c.locator.remove(&k);
            c.payload_refs.remove(&k);
        }),
        "INV-7",
    );
}

#[test]
#[spec("SR-15.7-2")]
fn p2_engine_refuses_counters_that_differ_from_the_groups() {
    refused_for(open_tampered(|c| c.big_n += 1), "INV-8");
    refused_for(open_tampered(|c| c.k += 1), "INV-8");
}

#[test]
#[spec("SR-15.7-2")]
fn p2_engine_refuses_a_collection_whose_artefact_hash_differs() {
    refused_for(open_tampered(|c| c.meta.artefact_sha256[0] ^= 1), "§6.3");
}

#[test]
#[spec("SR-15.7-2")]
fn p2_engine_refuses_a_passage_of_a_record_that_is_not_live() {
    refused_for(
        open_tampered(|c| {
            let any = *c
                .payload_refs
                .values()
                .next()
                .expect("the workload stores passages");
            c.payload_refs
                .insert(sever_types::ScrambledId::from_bytes([0xab; 64]), any);
        }),
        "§14.8",
    );
}
