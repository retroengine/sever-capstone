//! The rotation and erasure rules on the frozen engine (spec §13.3, §13.4, §15.3, §15.4, §15.9;
//! INV-12 … INV-14). Expected values are the spec's rules stated as properties of what is on disk
//! (oracle A): the key file read back slot by slot, and every ciphertext the WAL ever held read
//! back with the keys the database still holds (the rotation shadow model, Build 3-4 §2.8 L2).

use std::sync::{Arc, Mutex};

use sever_engine::DeleteOutcome;
use sever_keys::Domain;
use sever_keys::file::SlotState;
use sever_spec::spec;
use sever_txn::Step;
use sever_types::{CollectionId, Error};
use sever_vfs::{CrashPolicy, FaultPlan};

use super::harness::*;
use super::shadow::*;

/// Every record ID `populated` inserts.
fn ids() -> Vec<String> {
    (0..40)
        .map(|i| format!("r{i}"))
        .chain((0..12).map(|k| format!("c{k}")))
        .collect()
}

/// What the phase-order test saw: each step, with the key versions that survive a power cut there.
type Seen = Vec<(Step, Vec<u64>)>;

/// A database with 40 fixture records and a cohort of 12 that fills the holding area and spawns
/// a group (a flush); returns it, its ring and the collection.
fn populated(disks: &Disks) -> (Db, Arc<sever_seal::KeyRing>, CollectionId) {
    let (db, ring) = disks.open(1 << 30).unwrap();
    let cid = db.create_collection(ARTEFACT, OPTS).unwrap();
    for (i, v) in vectors().iter().take(40).enumerate() {
        insert(&db, cid, &format!("r{i}"), v).unwrap();
    }
    for (k, w) in cohort(&holding_vector(&db, cid), 12).iter().enumerate() {
        insert(&db, cid, &format!("c{k}"), w).unwrap();
    }
    (db, ring, cid)
}

/// A record of a frozen group with at least three members, and that group's domain.
fn victim(db: &Db, cid: CollectionId) -> (String, Domain) {
    let mut count = std::collections::BTreeMap::<String, Vec<String>>::new();
    for id in ids() {
        if let Some(g) = db.location(cid, &id) {
            count.entry(g).or_default().push(id);
        }
    }
    let (g, ids) = count
        .into_iter()
        .find(|(g, ids)| g.starts_with("frozen") && ids.len() >= 3)
        .unwrap();
    (ids[0].clone(), domain_of(cid, &g))
}

#[test]
// oracle: A §13.3 step 1 and §13.4: a departure moves the domain to version + 1; the new key is in
// the inactive slot; the old slot is zeros once the deletion returns
#[spec("SR-13.3-1", "SR-13.4-2", "SR-15.3-10", "SR-15.8-2")]
fn p4_erasure_a_deletion_rotates_its_domain_and_erases_the_old_key_before_returning() {
    let disks = Disks::new();
    let (db, ring, cid) = populated(&disks);
    let (id, d) = victim(&db, cid);
    let v = ring.active_versions()[&d];
    let before = slots_of(&disks.keys, &d);
    assert_eq!(before.iter().map(|s| s.2).collect::<Vec<_>>(), [v]);
    let (pair, active, _) = before[0];
    db.delete(cid, &id).unwrap();
    assert_eq!(ring.active_versions()[&d], v + 1);
    let after = slots_of(&disks.keys, &d);
    assert_eq!(
        after,
        [(pair, 1 - active, v + 1)],
        "the new key in the inactive slot only"
    );
    let slots = key_slots(&disks.keys);
    assert!(
        matches!(slots[pair as usize][active as usize], SlotState::Erased),
        "the old slot is 512 zero bytes"
    );
}

#[test]
// oracle: A §13.4 INV-13 / §15.3 steps 5–8: the new key is durable before the COMMIT; the old key
// is still on disk at the COMMIT and erased only after it
#[spec("SR-13.4-1", "SR-15.3-7", "SR-21-13")]
fn p4_erasure_the_new_key_is_durable_before_the_commit_and_the_old_one_outlives_it() {
    let disks = Disks::new();
    let (db, ring, cid) = populated(&disks);
    let (id, d) = victim(&db, cid);
    let v = ring.active_versions()[&d];
    let seen: Arc<Mutex<Seen>> = Arc::default();
    let (keys, log) = (disks.keys.clone(), Arc::clone(&seen));
    db.set_step_hook(Some(Box::new(move |s: Step| {
        if matches!(s, Step::PhaseA | Step::Committed) {
            // What survives a power cut now: a copy of the key disk, unsynced writes dropped.
            let copy = keys.fork();
            copy.restart(CrashPolicy::DropAll);
            let mut vs: Vec<u64> = slots_of(&copy, &d).iter().map(|x| x.2).collect();
            vs.sort_unstable();
            log.lock().unwrap().push((s, vs));
        }
    })));
    db.delete(cid, &id).unwrap();
    db.set_step_hook(None);
    let seen = seen.lock().unwrap().clone();
    assert_eq!(
        seen,
        [
            (Step::PhaseA, vec![v, v + 1]),
            (Step::Committed, vec![v, v + 1])
        ],
        "phase A made v + 1 durable; at the COMMIT the old key v is still there"
    );
}

#[test]
// oracle: A INV-12 (§13.3, §21): after a deletion, the domain's current keys open only the newest
// accumulator and never the departed record's key, wherever the WAL logged it
#[spec("SR-13.3-2", "SR-21-12")]
fn p4_erasure_rotation_shadow_model_current_keys_open_nothing_from_before_the_departure() {
    let disks = Disks::new();
    let (db, ring, cid) = populated(&disks);
    let (id, d) = victim(&db, cid);
    let (gone_sid, _) = {
        // The departed record is the one whose envelopes stop opening; record every member first.
        let log = logged(&disks.data, &d);
        let (_, recs) = openable(&ring, &d, &log);
        let members: Vec<[u8; 64]> = recs.keys().copied().collect();
        db.delete(cid, &id).unwrap();
        let (_, after) = openable(&ring, &d, &logged(&disks.data, &d));
        let gone: Vec<[u8; 64]> = members
            .iter()
            .filter(|m| !after.contains_key(*m))
            .copied()
            .collect();
        assert_eq!(
            gone.len(),
            1,
            "exactly the departed record's key became unreachable"
        );
        (gone[0], members.len())
    };
    let log = logged(&disks.data, &d);
    let (acc, recs) = openable(&ring, &d, &log);
    let v = ring.active_versions()[&d];
    assert_eq!(
        acc,
        [v],
        "only the accumulator sealed after the departure opens"
    );
    assert!(!recs.contains_key(&gone_sid));
    // Every survivor still opens (through its slot or its re-wrapped envelope).
    for rid in ids() {
        if rid != id && db.location(cid, &rid).as_deref().map(|g| domain_of(cid, g)) == Some(d) {
            assert!(
                db.passage(cid, &rid).unwrap().is_some(),
                "{rid} still readable"
            );
        }
    }
}

#[test]
// oracle: A §13.3 (a flush out of the holding area is a departure) and §15.2 (the new group gets
// fresh keys): after a flush the holding area's current keys open none of the moved records
#[spec("SR-13.3-1", "SR-15.2-3", "SR-21-12")]
fn p4_erasure_a_flush_rotates_the_holding_area_and_spawns_fresh_domains() {
    let disks = Disks::new();
    let (db, ring, cid) = populated(&disks);
    let holding = domain_of(cid, "holding");
    let versions = ring.active_versions();
    let spawned: Vec<&Domain> = versions
        .keys()
        .filter(|d| d.collection_id == *cid.as_bytes() && d.group_id.starts_with(b"spawn"))
        .collect();
    assert!(!spawned.is_empty(), "the cohort flushed the holding area");
    assert!(
        versions[&holding] >= 2,
        "every flush rotated the holding area"
    );
    for d in &spawned {
        assert_eq!(
            slots_of(&disks.keys, d).len(),
            1,
            "a spawned group has one key slot"
        );
    }
    // The records that left the holding area: their holding envelopes open under no current key.
    let log = logged(&disks.data, &holding);
    let (_, recs) = openable(&ring, &holding, &log);
    let still_held: usize = ids()
        .iter()
        .filter(|id| db.location(cid, id).as_deref() == Some("holding"))
        .count();
    assert_eq!(
        recs.len(),
        still_held,
        "only records still in the holding area open there"
    );
}

/// Crash `disks` at `step` of the deletion of a victim; returns the disks after the restart, the
/// victim and its domain with its version before the deletion.
fn crash_delete_at(step: Step, policy: CrashPolicy) -> (Disks, String, Domain, u64) {
    let disks = Disks::new();
    let (db, ring, cid) = populated(&disks);
    let (id, d) = victim(&db, cid);
    let v = ring.active_versions()[&d];
    let crash = disks.clone();
    db.set_step_hook(Some(Box::new(move |s: Step| {
        if s == step {
            crash.data.crash();
            crash.keys.crash();
        }
    })));
    let r = db.delete(cid, &id);
    // After phase C nothing is left to fail: the process dies before the caller hears back.
    assert_eq!(r.is_err(), step != Step::PhaseC);
    drop(db);
    disks.restart(policy);
    (disks, id, d, v)
}

fn cid_of(db: &Db) -> CollectionId {
    db.collections()[0]
}

#[test]
// oracle: A §15.4 row 1: before phase A the state is unchanged, the old key present, a retry safe
#[spec("SR-15.4-2")]
fn p4_erasure_crash_table_row_1_crash_before_phase_a() {
    let (disks, id, d, v) = crash_delete_at(Step::StoresSynced, CrashPolicy::DropAll);
    let (db, _) = disks.open(1 << 30).unwrap();
    let cid = cid_of(&db);
    assert!(db.location(cid, &id).is_some(), "unchanged");
    assert_eq!(
        slots_of(&disks.keys, &d)
            .iter()
            .map(|s| s.2)
            .collect::<Vec<_>>(),
        [v]
    );
    assert!(matches!(
        db.delete(cid, &id).unwrap(),
        DeleteOutcome::Deleted { .. }
    ));
}

#[test]
// oracle: A §15.4 row 2: after phase A and before the COMMIT, the new slot is an orphan that
// recovery erases; the state is unchanged and a retry is safe
#[spec("SR-15.4-3", "SR-13.4-3")]
fn p4_erasure_crash_table_row_2_crash_after_phase_a_before_the_commit() {
    let (disks, id, d, v) = crash_delete_at(Step::WalWriting, CrashPolicy::KeepAll);
    let (db, _) = disks.open(1 << 30).unwrap();
    let cid = cid_of(&db);
    assert!(db.location(cid, &id).is_some(), "unchanged");
    assert_eq!(
        slots_of(&disks.keys, &d)
            .iter()
            .map(|s| s.2)
            .collect::<Vec<_>>(),
        [v],
        "the orphan v + 1 is erased"
    );
    assert!(matches!(
        db.delete(cid, &id).unwrap(),
        DeleteOutcome::Deleted { .. }
    ));
}

#[test]
// oracle: A §15.4 row 3 (E2E-4.3): after the COMMIT and before phase C, the record is deleted and
// recovery erases the old key; a retry returns AlreadyAbsent
#[spec("SR-15.4-4", "SR-13.4-3")]
fn p4_erasure_crash_table_row_3_crash_after_the_commit_before_phase_c() {
    let (disks, id, d, v) = crash_delete_at(Step::Applied, CrashPolicy::KeepAll);
    let (db, _) = disks.open(1 << 30).unwrap();
    let cid = cid_of(&db);
    assert!(db.location(cid, &id).is_none(), "deleted");
    assert_eq!(
        slots_of(&disks.keys, &d)
            .iter()
            .map(|s| s.2)
            .collect::<Vec<_>>(),
        [v + 1],
        "recovery erased the old key"
    );
    assert_eq!(db.delete(cid, &id).unwrap(), DeleteOutcome::AlreadyAbsent);
}

#[test]
// oracle: A §15.4 row 4: a crash tearing the phase-C overwrite leaves a slot that fails its CRC;
// it is treated as absent and erased again; the record is deleted
#[spec("SR-15.4-5", "SR-14.7-3")]
fn p4_erasure_crash_table_row_4_a_torn_phase_c_overwrite() {
    let disks = Disks::new();
    let (db, ring, cid) = populated(&disks);
    let (id, d) = victim(&db, cid);
    let v = ring.active_versions()[&d];
    let (pair, active, _) = slots_of(&disks.keys, &d)[0];
    let keys = disks.keys.clone();
    db.set_step_hook(Some(Box::new(move |s: Step| {
        if s == Step::Applied {
            // The next key-disk write is phase C's overwrite: 100 of its 512 bytes land.
            keys.set_faults(FaultPlan {
                crash_at_op: Some(1),
                tear_bytes: 100,
                ..FaultPlan::default()
            });
        }
    })));
    assert!(db.delete(cid, &id).is_err());
    drop(db);
    disks.restart(CrashPolicy::KeepAll);
    assert!(
        matches!(
            key_slots(&disks.keys)[pair as usize][active as usize],
            SlotState::Torn
        ),
        "the overwrite was torn"
    );
    let (db, _) = disks.open(1 << 30).unwrap();
    assert!(db.location(cid, &id).is_none(), "deleted");
    assert!(matches!(
        key_slots(&disks.keys)[pair as usize][active as usize],
        SlotState::Erased
    ));
    assert_eq!(
        slots_of(&disks.keys, &d)
            .iter()
            .map(|s| s.2)
            .collect::<Vec<_>>(),
        [v + 1]
    );
    assert_eq!(db.delete(cid, &id).unwrap(), DeleteOutcome::AlreadyAbsent);
}

#[test]
// oracle: A §15.4 row 5: after phase C and before the acknowledgement, deleted; the old key gone
#[spec("SR-15.4-6")]
fn p4_erasure_crash_table_row_5_crash_after_phase_c_before_the_acknowledgement() {
    let (disks, id, d, v) = crash_delete_at(Step::PhaseC, CrashPolicy::DropAll);
    assert_eq!(
        slots_of(&disks.keys, &d)
            .iter()
            .map(|s| s.2)
            .collect::<Vec<_>>(),
        [v + 1],
        "the old key was already gone before the restart"
    );
    let (db, _) = disks.open(1 << 30).unwrap();
    let cid = cid_of(&db);
    assert!(db.location(cid, &id).is_none());
    assert_eq!(db.delete(cid, &id).unwrap(), DeleteOutcome::AlreadyAbsent);
}

#[test]
// oracle: A §15.9 (DB-90, G-26; E2E-4.4): the drop commits first; every key slot of the collection is
// erased in phase C, and a crash in between is finished by the recovery rule
#[spec("SR-15.9-2")]
fn p4_erasure_drop_collection_erases_every_key_after_its_commit() {
    for crash in [false, true] {
        let disks = Disks::new();
        let (db, ring, cid) = populated(&disks);
        let domains: Vec<Domain> = ring.active_versions().into_keys().collect();
        let at_commit: Arc<Mutex<usize>> = Arc::default();
        let (keys, n, c) = (disks.keys.clone(), Arc::clone(&at_commit), disks.clone());
        let ds = domains.clone();
        db.set_step_hook(Some(Box::new(move |s: Step| {
            if s == Step::Committed {
                *n.lock().unwrap() = ds.iter().map(|d| slots_of(&keys, d).len()).sum();
                if crash {
                    c.data.crash();
                    c.keys.crash();
                }
            }
        })));
        let r = db.drop_collection(cid);
        assert_eq!(r.is_err(), crash);
        assert_eq!(
            *at_commit.lock().unwrap(),
            domains.len(),
            "no key erased before the COMMIT"
        );
        drop(db);
        if crash {
            disks.restart(CrashPolicy::KeepAll);
            let (db, _) = disks.open(1 << 30).unwrap();
            assert!(db.collections().is_empty());
        }
        for d in &domains {
            assert!(
                slots_of(&disks.keys, d).is_empty(),
                "crash = {crash}: a key survived"
            );
        }
    }
}

#[test]
// oracle: A §14.8, §14.4 (DB-91): with the WAL truncated by storage checkpoints, survivors of a
// rotated bucket open through the wrapped-key store after a restart
#[spec("SR-14.8-4", "SR-14.4-6")]
fn p4_erasure_survivors_open_through_the_wrapped_key_store_after_checkpoints() {
    let disks = Disks::new();
    let (db, _) = disks.open(16 * 1024).unwrap();
    let cid = db.create_collection(ARTEFACT, OPTS).unwrap();
    let vs = vectors();
    for (i, v) in vs.iter().take(40).enumerate() {
        insert(&db, cid, &format!("r{i}"), v).unwrap();
    }
    // A group of 100 (more members than buckets, so deletions leave survivors in rotated buckets).
    let ids: Vec<String> = (0..100).map(|k| format!("c{k}")).collect();
    for (id, w) in ids.iter().zip(cohort(&holding_vector(&db, cid), 100)) {
        insert(&db, cid, id, &w).unwrap();
    }
    for id in ids.iter().step_by(5) {
        db.delete(cid, id).unwrap();
    }
    db.storage_checkpoint_now().unwrap();
    let want: Vec<Option<Vec<u8>>> = ids.iter().map(|id| db.passage(cid, id).unwrap()).collect();
    let state = db.canonical_state(cid).unwrap();
    db.close().unwrap();
    let (_, values) =
        crate::store::WrappedStore::open(Arc::new(disks.data.fork()), 64 * 1024).unwrap();
    assert!(
        values
            .iter()
            .any(|v| v.first() == Some(&crate::records::KIND_ENVELOPES)),
        "re-wrapped envelopes reached the store"
    );
    let (db, _) = disks.open(16 * 1024).unwrap();
    assert_eq!(db.canonical_state(cid).unwrap(), state);
    for (id, w) in ids.iter().zip(&want) {
        assert_eq!(&db.passage(cid, id).unwrap(), w, "{id}");
    }
}

#[test]
// oracle: A §14.8: once the store holds four times its live bytes it is rewritten with its live
// entries only, and everything still opens after a restart
#[spec("SR-14.8-5")]
fn p4_erasure_the_wrapped_key_store_is_compacted() {
    let disks = Disks::new();
    let ring = Arc::new(sever_seal::KeyRing::new());
    let open = |ring: &Arc<sever_seal::KeyRing>| {
        let p: Box<dyn sever_txn::TxnParticipant<sever_index::NoExtension>> = Box::new(
            crate::KeyRotationParticipant::new(
                Arc::new(disks.data.clone()),
                Arc::new(disks.keys.clone()),
                Arc::clone(ring),
                64 * 1024,
            )
            .with_compaction_at(32 * 1024),
        );
        sever_engine::Engine::open(
            Arc::new(disks.data.clone()),
            Arc::new(disks.keys.clone()),
            sever_seal::AeadSealer::new(Arc::clone(ring)),
            sever_index::NoExtension,
            vec![p],
            cfg(1 << 30),
        )
        .unwrap()
    };
    let db = open(&ring);
    let cid = db.create_collection(ARTEFACT, OPTS).unwrap();
    let vs = vectors();
    for (i, v) in vs.iter().take(30).enumerate() {
        insert(&db, cid, &format!("r{i}"), v).unwrap();
    }
    let mut most = 0u64;
    for round in 0..40 {
        let id = format!("r{}", round % 30);
        db.delete(cid, &id).unwrap();
        insert(&db, cid, &id, &vs[round % 30]).unwrap();
        let (_, bytes) = crate::store::WrappedStore::open(Arc::new(disks.data.fork()), 64 * 1024)
            .map(|(s, _)| ((), s.bytes()))
            .unwrap();
        most = most.max(bytes);
    }
    // Without compaction 40 rounds grow the store to about 200 KB; with it, it stays near four times
    // its live bytes (about 90 KB).
    assert!(most < 128 * 1024, "the store stayed bounded ({most} bytes)");
    let state = db.canonical_state(cid).unwrap();
    db.close().unwrap();
    let db = open(&Arc::new(sever_seal::KeyRing::new()));
    assert_eq!(db.canonical_state(cid).unwrap(), state);
    for i in 0..30 {
        assert!(db.passage(cid, &format!("r{i}")).unwrap().is_some());
    }
}

/// A closed database and one of its domains' key slot, for the key-file faults.
fn closed_with_slot() -> (Disks, Domain, u64, u8, u64) {
    let disks = Disks::new();
    let (db, ring, cid) = populated(&disks);
    let (id, d) = victim(&db, cid);
    db.delete(cid, &id).unwrap();
    let v = ring.active_versions()[&d];
    db.close().unwrap();
    let (pair, slot, _) = slots_of(&disks.keys, &d)[0];
    (disks, d, pair, slot, v)
}

fn write_keys(disks: &Disks, at: u64, bytes: &[u8]) {
    use sever_vfs::{OpenMode, Vfs};
    let mut f = disks
        .keys
        .open(crate::KEYS_PATH, OpenMode::Existing)
        .unwrap();
    f.write_at(at, bytes).unwrap();
    f.fsync().unwrap();
}

fn slot_at(pair: u64, slot: u8) -> u64 {
    4_096 + 1_024 * pair + 512 * u64::from(slot)
}

#[test]
// oracle: A §13.4 INV-14 (E2E-4.7, KF-1, KF-2): a domain whose active slot is torn or removed
// refuses to start
#[spec("SR-13.4-3", "SR-21-14")]
fn p4_erasure_startup_refuses_a_missing_or_torn_active_key_slot() {
    for torn in [true, false] {
        let (disks, _, pair, slot, _) = closed_with_slot();
        if torn {
            write_keys(&disks, slot_at(pair, slot) + 40, &[0xFF]);
        } else {
            write_keys(&disks, slot_at(pair, slot), &[0u8; 512]);
        }
        assert!(
            matches!(
                disks.open(1 << 30),
                Err(Error::IntegrityViolation {
                    invariant: "INV-14"
                })
            ),
            "torn = {torn}"
        );
    }
}

#[test]
// oracle: A §13.4 INV-14 (KF-3, KF-4, KF-5): an orphan in the inactive slot, a torn inactive slot
// and a pair of no domain are erased at startup, which then serves
#[spec("SR-13.4-3")]
fn p4_erasure_startup_erases_orphans_torn_inactive_slots_and_unclaimed_pairs() {
    use sever_keys::file::{SlotRecord, encode_slot};
    let (disks, d, pair, slot, v) = closed_with_slot();
    // KF-3: a valid key at another version in the inactive slot.
    let orphan = encode_slot(&SlotRecord {
        domain_index: pair,
        key_version: v + 7,
        domain: d,
        key: sever_keys::Key::generate(),
    });
    write_keys(&disks, slot_at(pair, 1 - slot), orphan.as_bytes());
    // KF-5: a pair at the end that names a domain that does not exist.
    let pairs = key_slots(&disks.keys).len() as u64;
    let ghost = Domain {
        collection_id: [0xAB; 16],
        group_id: [0xCD; 32],
    };
    let ghost_slot = encode_slot(&SlotRecord {
        domain_index: pairs,
        key_version: 1,
        domain: ghost,
        key: sever_keys::Key::generate(),
    });
    write_keys(&disks, slot_at(pairs, 0), ghost_slot.as_bytes());
    write_keys(&disks, slot_at(pairs, 1), &[0x11; 512]); // KF-4 style torn junk
    let (db, _) = disks.open(1 << 30).unwrap();
    assert_eq!(
        slots_of(&disks.keys, &d)
            .iter()
            .map(|s| s.2)
            .collect::<Vec<_>>(),
        [v]
    );
    assert!(slots_of(&disks.keys, &ghost).is_empty());
    let slots = key_slots(&disks.keys);
    assert!(matches!(slots[pairs as usize][1], SlotState::Erased));
    assert!(!db.collections().is_empty());
}

#[test]
// oracle: A §13.4 (KF-6): a crash during recovery's erasure leaves the next start to erase again
#[spec("SR-13.4-3", "SR-21-13")]
fn p4_erasure_a_crash_during_recovery_erasure_is_finished_by_the_next_start() {
    let (disks, d, pair, slot, v) = closed_with_slot();
    use sever_keys::file::{SlotRecord, encode_slot};
    let orphan = encode_slot(&SlotRecord {
        domain_index: pair,
        key_version: v + 1,
        domain: d,
        key: sever_keys::Key::generate(),
    });
    write_keys(&disks, slot_at(pair, 1 - slot), orphan.as_bytes());
    disks.keys.set_faults(FaultPlan {
        crash_at_op: Some(1),
        ..FaultPlan::default()
    });
    assert!(
        disks.open(1 << 30).is_err(),
        "the crash hit recovery's first erase"
    );
    disks.restart(CrashPolicy::KeepAll);
    let (db, _) = disks.open(1 << 30).unwrap();
    assert_eq!(
        slots_of(&disks.keys, &d)
            .iter()
            .map(|s| s.2)
            .collect::<Vec<_>>(),
        [v]
    );
    assert!(!db.collections().is_empty());
}

/// A copy of both disks.
fn fork(d: &Disks) -> Disks {
    Disks {
        data: d.data.fork(),
        keys: d.keys.fork(),
    }
}

/// The engine over `d` with compaction from 32 KiB (as the compaction test).
fn open_compacting(d: &Disks) -> Result<Db, Error> {
    let ring = Arc::new(sever_seal::KeyRing::new());
    let p: Box<dyn sever_txn::TxnParticipant<sever_index::NoExtension>> = Box::new(
        crate::KeyRotationParticipant::new(
            Arc::new(d.data.clone()),
            Arc::new(d.keys.clone()),
            Arc::clone(&ring),
            64 * 1024,
        )
        .with_compaction_at(32 * 1024),
    );
    sever_engine::Engine::open(
        Arc::new(d.data.clone()),
        Arc::new(d.keys.clone()),
        sever_seal::AeadSealer::new(ring),
        sever_index::NoExtension,
        vec![p],
        cfg(1 << 30),
    )
}

fn store_bytes(d: &Disks) -> u64 {
    crate::store::WrappedStore::open(Arc::new(d.data.fork()), 64 * 1024)
        .map(|(s, _)| s.bytes())
        .unwrap()
}

#[test]
// oracle: A §14.8 (compaction rewrites the store with its live entries), §15.4 and §15.7 step 3
// (G-43): a crash anywhere in a deletion that compacts the store, on either disk, recovers; every
// other record's passage opens; and a storage checkpoint then a clean reopen give the same state
#[spec("SR-14.8-5", "SR-15.7-4")]
fn p4_erasure_a_crash_anywhere_in_a_compacting_deletion_recovers_and_reopens() {
    let disks = Disks::new();
    let db = open_compacting(&disks).unwrap();
    let cid = db.create_collection(ARTEFACT, OPTS).unwrap();
    let vs = vectors();
    for (i, v) in vs.iter().take(30).enumerate() {
        insert(&db, cid, &format!("r{i}"), v).unwrap();
    }
    // Each round ends with a clean close (a storage checkpoint), so the WAL holds only the
    // compacting deletion and the store is the only record of the earlier blocks.
    db.close().unwrap();
    // Find the first deletion that compacts the store; every round before it runs on `disks`.
    let mut found = None;
    for round in 0..60 {
        let id = format!("r{}", round % 30);
        let dry = fork(&disks);
        let before = store_bytes(&dry);
        let db = open_compacting(&dry).unwrap();
        dry.data.set_faults(FaultPlan::default());
        dry.keys.set_faults(FaultPlan::default());
        db.delete(cid, &id).unwrap();
        let ops = [dry.data.ops_since_plan(), dry.keys.ops_since_plan()];
        drop(db);
        if store_bytes(&dry) < before {
            found = Some((id, ops));
            break;
        }
        let db = open_compacting(&disks).unwrap();
        db.delete(cid, &id).unwrap();
        insert(&db, cid, &id, &vs[round % 30]).unwrap();
        db.close().unwrap();
    }
    let (victim, ops) = found.expect("a deletion compacts the store within 60 rounds");
    for (disk, n_ops) in [0usize, 1].into_iter().zip(ops) {
        for k in 1..=n_ops {
            for p in [CrashPolicy::DropAll, CrashPolicy::KeepAll] {
                let t = fork(&disks);
                let db = open_compacting(&t).unwrap();
                let plan = FaultPlan {
                    crash_at_op: Some(k),
                    tear_bytes: 5,
                    ..FaultPlan::default()
                };
                if disk == 0 {
                    t.data.set_faults(plan);
                } else {
                    t.keys.set_faults(plan);
                }
                let _ = db.delete(cid, &victim);
                drop(db);
                let at = format!("disk {disk} op {k} {p:?}");
                t.restart(p);
                let db =
                    open_compacting(&t).unwrap_or_else(|e| panic!("{at}: recovery refused: {e:?}"));
                let state = db.canonical_state(cid).unwrap();
                let gone = db.location(cid, &victim).is_none();
                db.storage_checkpoint_now().unwrap();
                drop(db);
                let db = open_compacting(&t)
                    .unwrap_or_else(|e| panic!("{at}: refused after the checkpoint: {e:?}"));
                assert_eq!(db.canonical_state(cid).unwrap(), state, "{at}");
                for i in 0..30 {
                    let id = format!("r{i}");
                    if id != victim || !gone {
                        assert!(
                            db.passage(cid, &id).unwrap().is_some(),
                            "{at}: {id} unreadable"
                        );
                    }
                }
            }
        }
    }
}
