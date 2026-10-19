//! The final composition on simulated disks (the fixture partition, d = 16, spawn target 8).
//! Certificates are checked by §11.3's steps written out (oracle A, as Part 3's root tests do);
//! the key file is read back through its own §14.7 decoder; the plaintext scan looks for the
//! bytes §13.2 and §12.3 forbid, with every generated key known through `key-export` (DB-54).

use std::collections::{BTreeMap, BTreeSet};
use std::sync::{Arc, Mutex, OnceLock};

use rand_core::{OsRng, RngCore};
use sever_cert::Certificate;
use sever_commit::InsertCredential;
use sever_crypto::{
    DeletionContext, KeyPair, Scalar, certificate_message, commit_record, cosign_message,
    decode_point, encode_point, insert_message, transition_holds, verify, verify_signature,
};
use sever_engine::{CollectionOptions, EngineConfig, FailurePolicy, InsertRequest};
use sever_keys::Domain;
use sever_keys::file::{KeyFile, SlotState};
use sever_log::checkpoint::THRESHOLD;
use sever_log::merkle::{leaf_hash, verify_inclusion};
use sever_spec::spec;
use sever_txn::SimClock;
use sever_types::{CollectionId, Error};
use sever_vfs::{CrashPolicy, FaultPlan, OpenMode, SimVfs, Vfs, read_all};

use super::*;

const ARTEFACT: &[u8] = include_bytes!("../../../golden/p1_partition_small.svp");
const D: usize = 16;
const T0: u64 = 1_790_000_000_000;
const OPTS: CollectionOptions = CollectionOptions {
    spawn_target: 8,
    spawning_enabled: true,
    store_passages: true,
};

fn rows() -> Vec<Vec<f32>> {
    let doc: serde_json::Value =
        serde_json::from_str(include_str!("../../../golden/p1_fixture_vectors.json")).unwrap();
    doc["ref"]
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

fn gens() -> Arc<Generators> {
    static G: OnceLock<Arc<Generators>> = OnceLock::new();
    Arc::clone(G.get_or_init(|| Arc::new(Generators::derive(D).unwrap())))
}

struct Disks {
    data: SimVfs,
    keys: SimVfs,
    clock: Arc<SimClock>,
}

impl Disks {
    fn new() -> Self {
        Self {
            data: SimVfs::new(),
            keys: SimVfs::new(),
            clock: Arc::new(SimClock::new(T0)),
        }
    }
    fn fork(&self) -> Self {
        Self {
            data: self.data.fork(),
            keys: self.keys.fork(),
            clock: Arc::clone(&self.clock),
        }
    }
    fn open(&self) -> Result<Db, Error> {
        let mut s = Settings::new(D);
        s.clock = self.clock.clone();
        s.engine = EngineConfig {
            on_failure: FailurePolicy::Poison,
            checkpoint_every_wal_bytes: 1 << 40, // nothing truncated: the scan sees every byte
            ..EngineConfig::default()
        };
        s.log_segment_bytes = 1 << 20;
        s.wrapped_segment_bytes = 1 << 20;
        s.generators = Some(gens());
        open_on(Arc::new(self.data.clone()), Arc::new(self.keys.clone()), s)
    }
    fn restart(&self, p: CrashPolicy) {
        self.data.restart(p);
        self.keys.restart(p);
    }
}

/// What a test inserted: each record's quantised vector, `r_t`, passage and ID.
#[derive(Default)]
struct Written {
    x: Vec<Vec<i32>>,
    r_t: Vec<[u8; 32]>,
    passages: Vec<Vec<u8>>,
    ids: Vec<String>,
}

fn passage(id: &str) -> Vec<u8> {
    format!("the passage text of {id}, long enough to scan for in 32-byte windows").into_bytes()
}

fn insert(db: &Db, user: &KeyPair, cid: CollectionId, id: &str, v: &[f32], w: &mut Written) {
    let x = sever_quant::quantise(v, D).unwrap();
    let mut wide = [0u8; 64];
    OsRng.fill_bytes(&mut wide);
    let r_t = Scalar::from_bytes_mod_order_wide(&wide);
    let c_t = encode_point(&commit_record(db.generators(), x.as_slice(), &r_t).unwrap());
    let credential = InsertCredential {
        collection_id: *cid.as_bytes(),
        c_t,
        r_t: r_t.to_bytes(),
        user_public_key: user.public(),
        signature: user.sign(&insert_message(cid.as_bytes(), &c_t)),
    };
    let text = passage(id);
    db.insert(
        cid,
        InsertRequest {
            record_id: id.into(),
            vector: v.to_vec(),
            credential,
            passage: Some(text.clone()),
        },
    )
    .unwrap();
    w.x.push(x.as_slice().to_vec());
    w.r_t.push(r_t.to_bytes());
    w.passages.push(text);
    w.ids.push(id.to_owned());
}

/// A database with one collection and six records in frozen groups.
fn base(disks: &Disks, user: &KeyPair, w: &mut Written) -> (Db, CollectionId) {
    let db = disks.open().unwrap();
    let cid = db.create_collection(ARTEFACT, OPTS).unwrap();
    for (i, v) in rows().iter().take(6).enumerate() {
        insert(&db, user, cid, &format!("record-id-{i:02}"), v, w);
    }
    (db, cid)
}

fn cert(d: Deleted) -> (u64, Vec<u8>) {
    match d {
        Deleted::Deleted {
            database_lsn,
            certificate,
        } => (database_lsn, certificate),
        Deleted::AlreadyAbsent => panic!("not deleted"),
    }
}

/// §11.3 steps 1–8, written out, against `a`.
fn accept(a: &Anchors, gens: &Generators, bytes: &[u8]) -> Certificate {
    let c = Certificate::parse(bytes, a.d).unwrap();
    let key = a.operator.get(c.key_period).expect("step 2");
    verify_signature(
        key,
        &certificate_message(&bytes[..bytes.len() - 69]),
        &c.operator_signature,
    )
    .unwrap();
    let inc = &c.inclusion;
    let leaf = inc.leaf;
    assert_eq!((leaf.c_t, leaf.scrambled_id), (c.c_t, c.scrambled_id));
    verify_signature(
        &leaf.user_public_key,
        &insert_message(&leaf.collection_id, &leaf.c_t),
        &leaf.user_signature,
    )
    .unwrap();
    let cp = inc.checkpoint;
    assert!(verify_inclusion(
        &leaf_hash(&leaf.to_bytes()),
        inc.leaf_index,
        cp.tree_size,
        &inc.path,
        &cp.root
    ));
    assert!(cp.verify(&a.operator), "step 3");
    let good: BTreeSet<u8> = c
        .cosignatures
        .iter()
        .filter(|s| {
            a.witnesses
                .get(usize::from(s.witness_index))
                .and_then(|r| r.get(s.witness_epoch))
                .is_some_and(|k| {
                    verify_signature(k, &cosign_message(&cp.message()), &s.signature).is_ok()
                })
        })
        .map(|s| s.witness_index)
        .collect();
    assert!(good.len() >= THRESHOLD, "step 4");
    assert!(c.database_lsn > inc.leaf_index, "step 5");
    if let Some(g) = &c.group {
        let (pre, post) = (
            decode_point(&g.c_s_pre).unwrap(),
            decode_point(&g.c_s_post).unwrap(),
        );
        assert!(transition_holds(
            &post,
            &decode_point(&c.c_t).unwrap(),
            &pre
        ));
        let ctx = DeletionContext {
            c_s_pre: g.c_s_pre,
            c_t: c.c_t,
            scrambled_id: c.scrambled_id,
            database_lsn: c.database_lsn,
            collection_id: c.collection_id,
        };
        verify(gens, &g.c_s_post, &ctx, &g.proof).unwrap();
    }
    c
}

/// The domain of a group named by its text form (`Engine::location`).
fn domain_of(cid: CollectionId, text: &str) -> Domain {
    let mut group_id = [0u8; 32];
    group_id[..text.len()].copy_from_slice(text.as_bytes());
    Domain {
        collection_id: *cid.as_bytes(),
        group_id,
    }
}

/// Every valid slot of the key file, by domain: `[(pair, slot, version)]`, read by a fresh open
/// on a copy of the key disk.
fn slots(keys: &SimVfs) -> BTreeMap<Domain, Vec<(u64, u8, u64)>> {
    let (_, all) = KeyFile::open(Arc::new(keys.fork()), sever_platform::KEYS_FILE).unwrap();
    let mut out: BTreeMap<Domain, Vec<(u64, u8, u64)>> = BTreeMap::new();
    for (pair, two) in (0u64..).zip(all) {
        for (slot, s) in (0u8..).zip(two) {
            if let SlotState::Valid(r) = s {
                out.entry(r.domain)
                    .or_default()
                    .push((pair, slot, r.key_version));
            }
        }
    }
    out
}

// oracle: A §16.1 (insert returns database_lsn; delete returns the certificate, retrievable by
// database_lsn) and §11.3 steps written out, on the encrypted engine with both participants
#[spec("SR-15.1-7")]
#[test]
fn p4_db_deletions_yield_verifiable_certificates_on_the_encrypted_engine() {
    let disks = Disks::new();
    let user = KeyPair::generate();
    let mut w = Written::default();
    let (db, cid) = base(&disks, &user, &mut w);
    for id in &w.ids {
        // §15.1 steps 4–5: the passage reads back through the record key.
        assert_eq!(
            db.engine.passage(cid, id).unwrap().as_deref(),
            Some(passage(id).as_slice())
        );
    }
    let (lsn, c) = cert(db.delete(cid, "record-id-03").unwrap());
    let parsed = accept(&db.anchors(), db.generators(), &c);
    assert_eq!(parsed.database_lsn, lsn);
    assert_eq!(db.certificate(lsn).unwrap(), Some(c.clone()));
    assert_eq!(
        db.delete(cid, "record-id-03").unwrap(),
        Deleted::AlreadyAbsent
    );
    drop(db);
    let db = disks.open().unwrap();
    assert_eq!(db.certificate(lsn).unwrap(), Some(c));
    assert_eq!(db.engine.stats(cid).unwrap().big_n, 5);
    assert_eq!(db.engine.passage(cid, "record-id-03").unwrap(), None);
}

// oracle: A §15.3 delete_user "phase A writes one new key per affected domain, phase B commits one
// transaction, phase C erases one old key per affected domain"; the key file read back by §14.7
#[spec("SR-15.3-11")]
#[test]
fn p4_db_delete_user_rotates_and_erases_one_key_per_affected_domain() {
    let disks = Disks::new();
    let user = KeyPair::generate();
    let mut w = Written::default();
    let (db, cid) = base(&disks, &user, &mut w);
    let ids = [
        "record-id-00",
        "record-id-02",
        "record-id-04",
        "record-id-05",
    ];
    let domains: BTreeSet<Domain> = ids
        .iter()
        .map(|id| domain_of(cid, &db.engine.location(cid, id).unwrap()))
        .collect();
    assert!(domains.len() >= 2, "the records span several groups");
    let before = slots(&disks.keys);
    let out = db.delete_user(cid, &ids).unwrap();
    assert_eq!(out.len(), ids.len());
    for o in out {
        accept(&db.anchors(), db.generators(), &cert(o).1);
    }
    let after = slots(&disks.keys);
    for d in &domains {
        let old = &before[d];
        assert_eq!(old.len(), 1, "one active slot before");
        let new = after.get(d).map(Vec::as_slice).unwrap_or_default();
        if new.is_empty() {
            continue; // the domain emptied and was dropped with its slots
        }
        assert_eq!(
            new.len(),
            1,
            "one key per domain after: the old one is erased"
        );
        assert_eq!(new[0].2, old[0].2 + 1, "exactly one rotation per domain");
    }
    // Domains the deletion did not touch keep their key.
    for (d, s) in &before {
        if !domains.contains(d) {
            assert_eq!(after.get(d), Some(s));
        }
    }
}

// oracle: A §15.4 crash table with every participant (Build 3-4 §2.8 L8): after a crash anywhere
// in a deletion, on either disk, recovery gives the acknowledged state, a certificate exactly when
// the deletion committed, every live record readable, and one key slot for the record's domain
#[spec("SR-15.4-3", "SR-15.4-4", "SR-15.4-5", "SR-15.4-6")]
#[test]
fn p4_db_a_crash_anywhere_in_a_deletion_on_either_disk_recovers_cleanly() {
    let disks = Disks::new();
    let user = KeyPair::generate();
    let mut w = Written::default();
    let (db, cid) = base(&disks, &user, &mut w);
    let n0 = db.engine.stats(cid).unwrap().big_n;
    let size0 = db.log.with(|l| l.tree().size()).unwrap();
    let victim = "record-id-03";
    let d = domain_of(cid, &db.engine.location(cid, victim).unwrap());
    let v0 = slots(&disks.keys)[&d][0].2;
    drop(db);
    // Count each disk's mutating operations in one uninterrupted deletion.
    let dry = disks.fork();
    let db = dry.open().unwrap();
    dry.data.set_faults(FaultPlan::default());
    dry.keys.set_faults(FaultPlan::default());
    db.delete(cid, victim).unwrap();
    let ops = [dry.data.ops_since_plan(), dry.keys.ops_since_plan()];
    // §15.4 row 5: once acknowledged, the deletion has already erased its old key (no restart).
    let live: Vec<u64> = slots(&dry.keys)[&d].iter().map(|s| s.2).collect();
    assert_eq!(live, [v0 + 1], "the old key outlived the acknowledgement");
    drop(db);
    assert!(ops[0] >= 8 && ops[1] >= 2, "{ops:?} operations");
    for (disk, n_ops) in [0usize, 1].into_iter().zip(ops) {
        for k in 1..=n_ops {
            for p in [
                CrashPolicy::DropAll,
                CrashPolicy::KeepAll,
                CrashPolicy::Random(k),
            ] {
                let t = disks.fork();
                let db = t.open().unwrap();
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
                let acked = db.delete(cid, victim).is_ok();
                drop(db);
                let at = format!("disk {disk} op {k} {p:?}");
                if acked {
                    // §15.4 row 5: an acknowledged deletion has already erased its old key.
                    let live: Vec<u64> = slots(&t.keys)[&d].iter().map(|s| s.2).collect();
                    assert_eq!(
                        live,
                        [v0 + 1],
                        "{at}: the old key outlived the acknowledgement"
                    );
                }
                t.restart(p);
                let db = t
                    .open()
                    .unwrap_or_else(|e| panic!("{at}: recovery refused: {e:?}"));
                let n = db.engine.stats(cid).unwrap().big_n;
                let size = db.log.with(|l| l.tree().size()).unwrap();
                let c = db.certificate(size0).unwrap();
                let held = &slots(&t.keys)[&d];
                assert_eq!(
                    held.len(),
                    1,
                    "{at}: one slot for the domain after recovery"
                );
                if n == n0 {
                    assert!(!acked, "{at}: an acknowledged deletion was lost");
                    assert_eq!(size, size0, "{at}: no delete leaf");
                    assert!(
                        c.is_none(),
                        "{at}: no certificate for a rolled-back deletion"
                    );
                    assert_eq!(held[0].2, v0, "{at}: the old key stays");
                } else {
                    assert_eq!(n, n0 - 1, "{at}");
                    assert_eq!(size, size0 + 1, "{at}");
                    accept(&db.anchors(), db.generators(), &c.expect("its certificate"));
                    assert_eq!(held[0].2, v0 + 1, "{at}: only the new key remains");
                }
                for id in w.ids.iter().filter(|id| *id != victim || n == n0) {
                    assert!(
                        db.engine.passage(cid, id).unwrap().is_some(),
                        "{at}: {id} unreadable"
                    );
                }
            }
        }
    }
}

/// Every file of a disk, with its bytes.
fn files(v: &SimVfs) -> Vec<(String, Vec<u8>)> {
    fn walk(v: &SimVfs, dir: &str, out: &mut Vec<(String, Vec<u8>)>) {
        for name in v.list(dir).unwrap() {
            let path = if dir.is_empty() {
                name
            } else {
                format!("{dir}/{name}")
            };
            match v.open(&path, OpenMode::Existing) {
                Ok(f) => out.push((path, read_all(f.as_ref()).unwrap())),
                Err(_) => walk(v, &path, out),
            }
        }
    }
    let mut out = Vec::new();
    walk(v, "", &mut out);
    out
}

fn contains(hay: &[u8], needle: &[u8]) -> bool {
    !needle.is_empty() && hay.windows(needle.len()).any(|w| w == needle)
}

/// Every key generated in this test binary (DB-54 `key-export`).
fn exported() -> &'static Mutex<Vec<Vec<u8>>> {
    static K: OnceLock<&'static Mutex<Vec<Vec<u8>>>> = OnceLock::new();
    K.get_or_init(|| {
        let keys: &'static Mutex<Vec<Vec<u8>>> = Box::leak(Box::default());
        sever_keys::export::set_sink(Box::new(move |k| {
            if let Ok(mut v) = keys.lock() {
                v.push(k.to_vec());
            }
        }));
        keys
    })
}

// oracle: A §13.2 "Plaintext on disk is limited to n and group sizes, C_S, centroids, scrambled_ids,
// log leaves and certificates, group IDs and key versions" and §12.3 (no plaintext vectors, record
// IDs, passage text, r_t or unwrapped keys in the WAL); group keys only in KEYS (§13.1)
#[spec("SR-12.3-4", "SR-13.2-8", "SR-21-11", "SR-14.8-3")]
#[test]
fn p4_db_no_forbidden_plaintext_reaches_either_disk() {
    let keys_seen = exported();
    let disks = Disks::new();
    let user = KeyPair::generate();
    let mut w = Written::default();
    let (db, cid) = base(&disks, &user, &mut w);
    cert(db.delete(cid, "record-id-01").unwrap());
    db.delete_user(cid, &["record-id-04"]).unwrap();
    let live_group_keys: Vec<Vec<u8>> = db
        .key_ring()
        .active_versions()
        .iter()
        .filter_map(|(d, v)| db.key_ring().group_key(d, *v).ok())
        .map(|k| k.as_bytes().to_vec())
        .collect();
    drop(db);
    let all: Vec<(String, Vec<u8>)> = files(&disks.data)
        .into_iter()
        .map(|(p, b)| (format!("data/{p}"), b))
        .chain(
            files(&disks.keys)
                .into_iter()
                .map(|(p, b)| (format!("keys/{p}"), b)),
        )
        .collect();
    assert!(all.iter().any(|(p, _)| p.starts_with("data/wal")));
    let mut found = Vec::new();
    for (i, x) in w.x.iter().enumerate() {
        let le: Vec<u8> = x[..8].iter().flat_map(|c| c.to_le_bytes()).collect();
        let be: Vec<u8> = x[..8].iter().flat_map(|c| c.to_be_bytes()).collect();
        for (path, b) in &all {
            if contains(b, &le) || contains(b, &be) {
                found.push(format!("x̃ of record {i} in {path}"));
            }
            if contains(b, &w.r_t[i]) {
                found.push(format!("r_t of record {i} in {path}"));
            }
            if contains(b, &w.passages[i][..32]) {
                found.push(format!("passage of record {i} in {path}"));
            }
            if contains(b, w.ids[i].as_bytes()) {
                found.push(format!("record ID {i} in {path}"));
            }
        }
    }
    let generated = keys_seen.lock().unwrap().clone();
    assert!(generated.len() > 64, "keys were exported");
    for k in &generated {
        for (path, b) in &all {
            if contains(b, k) && !(path == "keys/KEYS" && live_group_keys.contains(k)) {
                found.push(format!("a key in the clear in {path}"));
            }
        }
    }
    assert!(found.is_empty(), "forbidden plaintext: {found:?}");
}
