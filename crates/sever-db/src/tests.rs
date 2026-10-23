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
// IDs, passage text, r_t or unwrapped keys in the WAL); group keys only in KEYS, bucket and record
// keys only wrapped (§13.1); with sealer 1 the disk receives only ciphertext for secrets (§12.1)
#[spec("SR-12.3-4", "SR-13.2-8", "SR-21-11")]
#[spec("SR-14.8-3", "SR-12.1-1", "SR-13.1-1")]
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

/// Every WAL record on `disk`, in order, as `(txn_id, type)` (§14.6: segments start with a 32-byte
/// header, then whole records).
fn wal_records(disk: &SimVfs) -> Vec<(u64, sever_format::RecordType)> {
    let mut out = Vec::new();
    for (path, bytes) in files(disk) {
        if !path.starts_with("wal/") {
            continue;
        }
        let mut rest = &bytes[32..];
        while let sever_format::WalParse::Record(r, n) = sever_format::WalRecord::parse_next(rest) {
            out.push((r.txn_id, r.ty));
            rest = &rest[n..];
        }
    }
    out
}

// oracle: A §15.3 step 6 (phase B): "one WAL transaction holds the slot move and truncate, the
// locator updates, the new group header, the new bucket block, …, the delete leaf, the certificate
// reference and the counters; then COMMIT"
#[spec("SR-15.3-8")]
#[test]
fn p4_db_a_deletion_is_one_wal_transaction_with_every_record_of_phase_b() {
    use sever_format::RecordType as T;
    let disks = Disks::new();
    let user = KeyPair::generate();
    let mut w = Written::default();
    let (db, cid) = base(&disks, &user, &mut w);
    let before: BTreeSet<u64> = wal_records(&disks.data).iter().map(|(t, _)| *t).collect();
    cert(db.delete(cid, "record-id-01").unwrap());
    drop(db);
    let recs = wal_records(&disks.data);
    // The deletion's transaction: the new one that carries a certificate reference.
    let txn = recs
        .iter()
        .find(|(t, ty)| !before.contains(t) && *ty == T::CertRef)
        .map(|(t, _)| *t)
        .expect("a certificate reference was logged");
    let types: BTreeSet<T> = recs
        .iter()
        .filter(|(t, _)| *t == txn)
        .map(|(_, ty)| *ty)
        .collect();
    for need in [
        T::Begin,
        T::SlotTruncate,
        T::LocatorDel,
        T::GroupHeader,
        T::BucketBlock,
        T::LogLeaf,
        T::CertRef,
        T::Counters,
        T::Commit,
    ] {
        assert!(types.contains(&need), "{need:?} missing from {types:?}");
    }
}

// oracle: A §14 "sealer_id 1 is AES-256-GCM-SIV as in §13.2; the key file KEYS exists only with
// sealer 1"; B Part 2's plaintext engine (sealer 0) as the counter-example
#[spec("SR-14-3")]
#[test]
fn p4_db_sealer_1_is_aes_gcm_siv_and_only_it_has_a_key_file() {
    use sever_txn::sealer::Sealer;
    assert_eq!(AeadSealer::new(Arc::new(KeyRing::new())).sealer_id(), 1);
    let disks = Disks::new();
    let user = KeyPair::generate();
    let mut w = Written::default();
    let (db, _) = base(&disks, &user, &mut w);
    drop(db);
    let names: Vec<String> = files(&disks.keys).into_iter().map(|(p, _)| p).collect();
    assert!(names.iter().any(|p| p == "KEYS"), "{names:?}");
    // Part 2's engine (sealer 0) on fresh disks: no key file.
    let p2 = Disks::new();
    let e = sever_engine::Engine::open(
        Arc::new(p2.data.clone()),
        Arc::new(p2.keys.clone()),
        sever_txn::sealer::PlaintextSealer,
        sever_index::NoExtension,
        Vec::new(),
        EngineConfig {
            on_failure: FailurePolicy::Poison,
            ..EngineConfig::default()
        },
    )
    .unwrap();
    e.create_collection(ARTEFACT, OPTS).unwrap();
    drop(e);
    let p2_names: Vec<String> = files(&p2.keys).into_iter().map(|(p, _)| p).collect();
    assert!(!p2_names.iter().any(|p| p == "KEYS"), "{p2_names:?}");
}

#[test]
// oracle: A §6.3 "create_collection MUST verify … d …; a failed check is rejected with IntegrityViolation naming the check, never a value" (DB-64); WrongDimension is §4.1 step 0's, for an input vector (§17)
#[spec("SR-6.3-3")]
fn p4_db_refuses_an_artefact_of_another_dimension() {
    let disks = Disks::new();
    let mut s = Settings::new(384);
    s.clock = disks.clock.clone();
    let db = open_on(
        Arc::new(disks.data.clone()),
        Arc::new(disks.keys.clone()),
        s,
    )
    .unwrap();
    assert!(matches!(
        db.create_collection(ARTEFACT, OPTS),
        Err(Error::IntegrityViolation { .. })
    ));
}

/// A fresh real directory for `open` (the platform's filesystem checks are not under test here).
fn real_dir(name: &str) -> std::path::PathBuf {
    let dir = std::env::temp_dir().join(format!("sever-db-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn real_options(dir: &std::path::Path) -> OpenOptions {
    let mut o = OpenOptions::new(dir.join("data"), dir.join("keys"));
    o.d = D;
    o.overrides = Overrides {
        allow_unsafe_memory: true,
        allow_unsafe_fs: true,
    };
    o.on_failure = FailurePolicy::Poison;
    o
}

/// The bytes a checkpoint leaves: `MANIFEST` and the names under `checkpoint/`.
fn checkpoint_state(dir: &std::path::Path) -> (Vec<u8>, Vec<std::ffi::OsString>) {
    let data = dir.join("data");
    let mut names: Vec<_> = std::fs::read_dir(data.join("checkpoint"))
        .unwrap()
        .map(|e| e.unwrap().file_name())
        .collect();
    names.sort();
    (std::fs::read(data.join("MANIFEST")).unwrap(), names)
}

#[test]
// oracle: A §17 "IntegrityViolation … the engine stops serving": no later call is served, and closing writes no storage checkpoint over the state the violation was found in
#[spec("SR-17-8")]
fn p4_db_after_an_integrity_violation_the_database_stops_serving() {
    let dir = real_dir("stops-serving");
    let opened = open(&real_options(&dir)).unwrap();
    let user = KeyPair::generate();
    let mut w = Written::default();
    let cid = opened.db.create_collection(ARTEFACT, OPTS).unwrap();
    for (i, v) in rows().iter().take(3).enumerate() {
        insert(&opened.db, &user, cid, &format!("rec-{i}"), v, &mut w);
    }
    // The leaf store loses its records under the open database: the delete finds an invariant
    // broken (§17 IntegrityViolation).
    let leaves = dir.join("data/log/leaves/00000000000000000001.store");
    std::fs::OpenOptions::new()
        .write(true)
        .open(&leaves)
        .unwrap()
        .set_len(16)
        .unwrap();
    assert!(matches!(
        opened.serve(|db| db.delete(cid, "rec-0")),
        Err(Error::IntegrityViolation { .. })
    ));
    let before = checkpoint_state(&dir);
    assert!(matches!(
        opened.serve(|db| db.engine.stats(cid)),
        Err(Error::IntegrityViolation { .. })
    ));
    assert!(
        opened.close().is_err(),
        "no clean shutdown after a violation"
    );
    assert_eq!(checkpoint_state(&dir), before, "closing wrote a checkpoint");
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
// oracle: A §12.9 (G-42) "Before each call and before the closing storage checkpoint, the engine checks that data/ENGINE.lock is still the file it locked; otherwise the call fails with IntegrityViolation and nothing more is written to the data directory"; §12.3 the directory's own database still recovers
#[spec("SR-12.9-5")]
fn p4_db_refuses_to_write_into_a_replaced_data_directory() {
    let dir = real_dir("replaced");
    let first = open(&real_options(&dir)).unwrap();
    let user = KeyPair::generate();
    let mut w = Written::default();
    let cid = first.db.create_collection(ARTEFACT, OPTS).unwrap();
    insert(&first.db, &user, cid, "rec-0", &rows()[0], &mut w);
    // Another process wipes the directory and creates its own database there (two tours on one
    // work directory, 20 Oct 2026).
    std::fs::remove_dir_all(&dir).unwrap();
    std::fs::create_dir_all(&dir).unwrap();
    let second = open(&real_options(&dir)).unwrap();
    let other = second.db.create_collection(ARTEFACT, OPTS).unwrap();
    second.close().unwrap();
    let before = checkpoint_state(&dir);
    match first.serve(|db| db.delete(cid, "rec-0")) {
        Err(Error::IntegrityViolation { invariant }) => {
            assert_eq!(invariant, "§12.9 data directory replaced");
        }
        other => panic!("not refused: {other:?}"),
    }
    assert!(
        first.close().is_err(),
        "closing wrote into another database"
    );
    assert_eq!(checkpoint_state(&dir), before);
    let again = open(&real_options(&dir)).unwrap();
    assert_eq!(again.db.engine.collections(), vec![other]);
    drop(again);
    std::fs::remove_dir_all(&dir).unwrap();
}

// oracle: A §15.6 step 4 and §15.7 step 3 (G-43): a storage checkpoint deletes only the WAL its
// state covers, so after a crash anywhere in a deletion, a recovery, a storage checkpoint and a
// clean reopen give the same acknowledged state, every live record readable and one key slot for
// the record's domain at the version recovery found (INV-14, §13.4)
#[spec("SR-15.7-4")]
#[test]
fn p4_db_a_checkpoint_after_recovery_keeps_every_rotated_key() {
    let disks = Disks::new();
    let user = KeyPair::generate();
    let mut w = Written::default();
    let (db, cid) = base(&disks, &user, &mut w);
    let victim = "record-id-03";
    let d = domain_of(cid, &db.engine.location(cid, victim).unwrap());
    drop(db);
    let dry = disks.fork();
    let db = dry.open().unwrap();
    dry.data.set_faults(FaultPlan::default());
    dry.keys.set_faults(FaultPlan::default());
    db.delete(cid, victim).unwrap();
    let ops = [dry.data.ops_since_plan(), dry.keys.ops_since_plan()];
    drop(db);
    for (disk, n_ops) in [0usize, 1].into_iter().zip(ops) {
        for k in 1..=n_ops {
            for p in [CrashPolicy::DropAll, CrashPolicy::KeepAll] {
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
                let _ = db.delete(cid, victim);
                drop(db);
                let at = format!("disk {disk} op {k} {p:?}");
                t.restart(p);
                let db = t
                    .open()
                    .unwrap_or_else(|e| panic!("{at}: recovery refused: {e:?}"));
                let n = db.engine.stats(cid).unwrap().big_n;
                let version = slots(&t.keys)[&d][0].2;
                db.engine.storage_checkpoint_now().unwrap();
                drop(db);
                let db = t
                    .open()
                    .unwrap_or_else(|e| panic!("{at}: refused after the checkpoint: {e:?}"));
                assert_eq!(db.engine.stats(cid).unwrap().big_n, n, "{at}");
                let held: Vec<u64> = slots(&t.keys)[&d].iter().map(|s| s.2).collect();
                assert_eq!(held, [version], "{at}: one slot at the recovered version");
                for id in w.ids.iter().filter(|id| *id != victim || n == 6) {
                    assert!(
                        db.engine.passage(cid, id).unwrap().is_some(),
                        "{at}: {id} unreadable"
                    );
                }
            }
        }
    }
}

/// DB-107: the `inspect` build's events. Expected values come from the spec (§5.3, §7.5, §7.6,
/// §13.2) and from the engine's own state through the `test-hooks` snapshot, never from the
/// participant.
#[cfg(feature = "inspect")]
mod inspect_events {
    use super::*;
    use crate::inspect::Event;
    use sever_types::GroupId;

    /// A direction far from every frozen centroid of the small artefact: a flush needs eight.
    fn far(seed: u64) -> Vec<f32> {
        let mut x = seed
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        let mut v: Vec<f64> = (0..D)
            .map(|_| {
                x ^= x << 13;
                x ^= x >> 7;
                x ^= x << 17;
                (x >> 11) as f64 / (1u64 << 53) as f64 * 2.0 - 1.0
            })
            .collect();
        let norm = v.iter().map(|a| a * a).sum::<f64>().sqrt();
        v.iter_mut().for_each(|a| *a /= norm);
        v.iter().map(|a| *a as f32).collect()
    }

    fn events(db: &Db) -> Vec<Event> {
        db.inspect.since(0)
    }

    // oracle: A §7.5 μ_i = ((f64)S_i / 2^24) / n over the founding cohort
    #[test]
    fn p4_inspect_a_flush_reports_the_centroid_of_its_founders() {
        let disks = Disks::new();
        let user = KeyPair::generate();
        let mut w = Written::default();
        let (db, cid) = base(&disks, &user, &mut w);
        let mut waiting: Vec<Vec<i32>> = Vec::new();
        let mut seed = 1;
        let created = loop {
            let before = events(&db).len();
            let v = far(seed);
            insert(&db, &user, cid, &format!("far-{seed:03}"), &v, &mut w);
            seed += 1;
            let e = &events(&db)[before];
            if let Some(c) = e.created.first() {
                waiting.push(w.x.last().unwrap().clone());
                break c.clone();
            }
            if e.outcomes == ["placed holding"] {
                waiting.push(w.x.last().unwrap().clone());
            }
            assert!(seed < 500, "no flush");
        };
        assert_eq!(waiting.len(), OPTS.spawn_target);
        let n = waiting.len() as f64;
        for (i, mu) in created.1.iter().enumerate() {
            let s: i64 = waiting.iter().map(|x| i64::from(x[i])).sum();
            assert_eq!(
                mu.to_bits(),
                ((s as f64 / 16_777_216.0) / n).to_bits(),
                "μ_{i}"
            );
        }
    }

    // oracle: A §5.3 (n ± 1 per record), §7.6 (N ± 1 for a group); C_S after equals the
    // engine's own snapshot (test-hooks)
    #[test]
    fn p4_inspect_each_change_moves_n_and_the_counters_by_one_record() {
        let disks = Disks::new();
        let user = KeyPair::generate();
        let mut w = Written::default();
        let (db, cid) = base(&disks, &user, &mut w);
        let e = events(&db);
        let ins = e.last().unwrap();
        assert_eq!(ins.kind, "insert");
        assert_eq!(ins.groups.len(), 1);
        let g = &ins.groups[0];
        assert_eq!(g.n_after, g.n_before + 1);
        assert_eq!(ins.counters_after.0, ins.counters_before.0 + 1);
        let snap = db
            .engine
            .group_snapshot(cid, &GroupId::parse(&g.group).unwrap())
            .unwrap();
        assert_eq!(g.c_s_after, encode_point(&snap.ext_public.0));
        assert_eq!(snap.n, g.n_after);
        let before = e.len();
        cert(db.delete(cid, &w.ids[0]).unwrap());
        let del = &events(&db)[before];
        assert_eq!(del.kind, "delete");
        assert_eq!(del.groups[0].n_after + 1, del.groups[0].n_before);
        assert_eq!(del.counters_after.0 + 1, del.counters_before.0);
        assert_eq!(del.outcomes.len(), 1);
        assert!(del.outcomes[0].starts_with("deleted from "));
    }

    // oracle: A §5.4 an absent delete changes no group and creates none
    #[test]
    fn p4_inspect_a_refused_or_absent_request_reports_nothing_new() {
        let disks = Disks::new();
        let user = KeyPair::generate();
        let mut w = Written::default();
        let (db, cid) = base(&disks, &user, &mut w);
        cert(db.delete(cid, &w.ids[1]).unwrap());
        let n = events(&db).len();
        assert!(matches!(
            db.delete(cid, &w.ids[1]).unwrap(),
            Deleted::AlreadyAbsent
        ));
        assert!(events(&db).len() <= n + 1);
        assert!(
            events(&db)[n..]
                .iter()
                .all(|e| e.groups.is_empty() && e.created.is_empty())
        );
    }

    // oracle: A §13.2 (what may be plaintext) and §17: every event of a session, searched byte
    // by byte for each record's ID, x̃, r_t and text and each group's S and r_agg, in binary and
    // as decimal lists (a leak through a debug print)
    #[test]
    fn p4_inspect_events_hold_no_secret() {
        let disks = Disks::new();
        let user = KeyPair::generate();
        let mut w = Written::default();
        let (db, cid) = base(&disks, &user, &mut w);
        for seed in 1..40 {
            insert(
                &db,
                &user,
                cid,
                &format!("far-{seed:03}"),
                &far(seed),
                &mut w,
            );
        }
        cert(db.delete(cid, &w.ids[2]).unwrap());
        let mut blob: Vec<u8> = Vec::new();
        for e in events(&db) {
            blob.extend(format!("{e:?}").as_bytes());
            for (g, c) in &e.created {
                blob.extend(g.as_bytes());
                c.iter().for_each(|m| blob.extend(m.to_be_bytes()));
            }
            for g in &e.groups {
                blob.extend(g.c_s_before);
                blob.extend(g.c_s_after);
                blob.extend(g.n_before.to_be_bytes());
            }
            for (_, s) in e.arrivals.iter().chain(&e.departures) {
                blob.extend(s);
            }
        }
        let found = |needle: &[u8]| blob.windows(needle.len()).any(|win| win == needle);
        for (i, id) in w.ids.iter().enumerate() {
            assert!(!found(id.as_bytes()), "record ID {i}");
            assert!(!found(&w.r_t[i]), "r_t {i}");
            assert!(!found(&w.passages[i][..32]), "text {i}");
            let xq: Vec<u8> = w.x[i][..4].iter().flat_map(|v| v.to_be_bytes()).collect();
            let xl: Vec<u8> = w.x[i][..4].iter().flat_map(|v| v.to_le_bytes()).collect();
            assert!(!found(&xq) && !found(&xl), "x̃ {i}");
            let xd = format!("{}, {}", w.x[i][0], w.x[i][1]);
            assert!(!found(xd.as_bytes()), "x̃ {i} as text");
        }
        let groups: BTreeSet<String> = events(&db)
            .iter()
            .flat_map(|e| e.groups.iter().map(|g| g.group.clone()))
            .collect();
        for g in groups {
            let snap = db
                .engine
                .group_snapshot(cid, &GroupId::parse(&g).unwrap())
                .unwrap();
            if snap.n == 0 {
                continue;
            }
            let s: Vec<u8> = snap.s[..2].iter().flat_map(|v| v.to_be_bytes()).collect();
            assert!(!found(&s), "S of {g}");
            let sd = format!("{}, {}", snap.s[0], snap.s[1]);
            assert!(!found(sd.as_bytes()), "S of {g} as text");
            let at = 6 + 2 + 2 + 8 + 8 * D + 32; // §5.5: … S ‖ C_S ‖ r_agg
            assert!(!found(&snap.blob[at..at + 32]), "r_agg of {g}");
        }
    }
}
