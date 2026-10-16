//! Tests of the composition root on simulated disks (Build 3-4 §1.8 L8): the §16.1 API, keys and
//! witness memory that survive restarts and epochs, and a crash at every VFS operation of a
//! deletion. Certificates are checked by the §11.3 steps written out here (oracle A).

use std::collections::BTreeSet;
use std::sync::Arc;

use rand_core::{OsRng, RngCore};
use sever_cert::Certificate;
use sever_commit::InsertCredential;
use sever_crypto::{
    DeletionContext, EPOCH_MS, KeyPair, Scalar, certificate_message, commit_record, cosign_message,
    decode_point, encode_point, insert_message, transition_holds, verify, verify_signature,
};
use sever_engine::{CollectionOptions, EngineConfig, FailurePolicy, InsertRequest};
use sever_index::Placement;
use sever_log::checkpoint::{LogCheckpoint, THRESHOLD};
use sever_log::leaf::delete_leaf;
use sever_log::merkle::{leaf_hash, verify_consistency, verify_inclusion};
use sever_log::witness::Refusal;
use sever_spec::spec;
use sever_txn::SimClock;
use sever_types::{CollectionId, Error};
use sever_vfs::{CrashPolicy, FaultPlan, SimVfs};

use super::*;

const ARTEFACT: &[u8] = include_bytes!("../../../golden/p1_partition_small.svp");
const D: usize = 16;
const T0: u64 = 1_790_000_000_000;
const OPTS: CollectionOptions = CollectionOptions {
    spawn_target: 8,
    spawning_enabled: true,
    store_passages: false,
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
            ..EngineConfig::default()
        };
        s.log_segment_bytes = 1 << 20;
        open_on(Arc::new(self.data.clone()), Arc::new(self.keys.clone()), s)
    }
    fn restart(&self, p: CrashPolicy) {
        self.data.restart(p);
        self.keys.restart(p);
    }
}

fn credential(db: &Db, user: &KeyPair, cid: CollectionId, v: &[f32]) -> InsertCredential {
    let x = sever_quant::quantise(v, D).unwrap();
    let mut wide = [0u8; 64];
    OsRng.fill_bytes(&mut wide);
    let r_t = Scalar::from_bytes_mod_order_wide(&wide);
    let c_t = encode_point(&commit_record(db.generators(), x.as_slice(), &r_t).unwrap());
    InsertCredential {
        collection_id: *cid.as_bytes(),
        c_t,
        r_t: r_t.to_bytes(),
        user_public_key: user.public(),
        signature: user.sign(&insert_message(cid.as_bytes(), &c_t)),
    }
}

fn insert(db: &Db, user: &KeyPair, cid: CollectionId, id: &str, v: &[f32]) -> (u64, Placement) {
    let req = InsertRequest {
        record_id: id.into(),
        vector: v.to_vec(),
        credential: credential(db, user, cid, v),
        passage: None,
    };
    db.insert(cid, req).unwrap()
}

/// A database with one collection and six records in frozen groups.
fn base(disks: &Disks, user: &KeyPair) -> (Db, CollectionId) {
    let db = disks.open().unwrap();
    let cid = db.create_collection(ARTEFACT, OPTS).unwrap();
    for (i, v) in rows().iter().take(6).enumerate() {
        insert(&db, user, cid, &format!("rec-{i}"), v);
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
fn accept(a: &Anchors, gens: &sever_crypto::Generators, bytes: &[u8]) -> Certificate {
    let c = Certificate::parse(bytes, a.d).unwrap();
    let key = a
        .operator
        .get(c.key_period)
        .expect("step 2: the epoch is in the anchors");
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
    assert!(cp.verify(&a.operator), "step 3: the checkpoint's epoch key");
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

#[test]
// oracle: A §16.1 (insert returns database_lsn; delete returns the certificate; certificate, latest_log_checkpoint, inclusion and consistency proofs); §11.3 steps written out
#[spec("SR-15.1-5", "SR-15.3-6")]
fn p3_root_the_section_16_1_api() {
    let disks = Disks::new();
    let user = KeyPair::generate();
    let db = disks.open().unwrap();
    let cid = db.create_collection(ARTEFACT, OPTS).unwrap();
    let vs = rows();
    for (i, v) in vs.iter().take(4).enumerate() {
        assert_eq!(
            insert(&db, &user, cid, &format!("r{i}"), v).0,
            i as u64,
            "database_lsn = leaf index"
        );
    }
    let (lsn, bytes) = cert(db.delete(cid, "r1").unwrap());
    assert_eq!(lsn, 4);
    let c = accept(&db.anchors(), db.generators(), &bytes);
    assert_eq!(c.database_lsn, lsn);
    assert_eq!(db.certificate(lsn), Ok(Some(bytes.clone())));
    assert_eq!(db.certificate(3), Ok(None), "leaf 3 is an insert leaf");
    assert_eq!(db.delete(cid, "r1"), Ok(Deleted::AlreadyAbsent));
    let latest = db.latest_log_checkpoint().unwrap();
    assert_eq!(
        latest.checkpoint.tree_size, 4,
        "the on-demand checkpoint before the deletion"
    );
    let path = db.inclusion_proof(1, 4).unwrap().unwrap();
    assert_eq!(path, c.inclusion.path);
    let root5 = db.log.with(|l| l.tree().root(5)).unwrap().unwrap();
    assert_eq!(
        db.log.with(|l| l.tree().leaf(4)),
        Some(Some(leaf_hash(&delete_leaf(&bytes))))
    );
    let proof = db.consistency_proof(4, 5).unwrap().unwrap();
    assert!(verify_consistency(
        4,
        5,
        &latest.checkpoint.root,
        &root5,
        &proof
    ));
    let json: serde_json::Value = serde_json::from_str(&db.anchors().to_json()).unwrap();
    assert_eq!(json["d"], 16);
    assert_eq!(json["witnesses"].as_array().unwrap().len(), 5);
    assert!(json["operator"]["0"].is_string());
}

#[test]
// oracle: A §9.8 "Old public keys stay resolvable forever, so a certificate signed in an earlier epoch keeps verifying after later epochs begin"; 90-day epochs from the creation time
#[spec("SR-9.8-6", "SR-9.8-5")]
fn p3_root_keys_survive_restarts_and_epochs() {
    let disks = Disks::new();
    let user = KeyPair::generate();
    let (db, cid) = base(&disks, &user);
    let (_, first) = cert(db.delete(cid, "rec-0").unwrap());
    let a0 = db.anchors();
    drop(db); // no close: a crash right after the acknowledgement
    disks.restart(CrashPolicy::DropAll);
    disks.clock.advance(EPOCH_MS);
    let db = disks.open().unwrap();
    let (_, second) = cert(db.delete(cid, "rec-1").unwrap());
    let a1 = db.anchors();
    let (c1, c2) = (
        accept(&a1, db.generators(), &first),
        accept(&a1, db.generators(), &second),
    );
    assert_eq!((c1.key_period, c2.key_period), (0, 1));
    assert_eq!(
        a1.operator.get(0),
        a0.operator.get(0),
        "epoch 0's key is the same after the restart"
    );
    for (i, r) in a0.witnesses.iter().enumerate() {
        for (e, k) in r.iter() {
            assert_eq!(a1.witnesses[i].get(*e), Some(k), "witness {i} kept its key");
        }
    }
    // An older verifier (anchors from before epoch 1) does not know the new key (E2E-3.7).
    assert!(a0.operator.get(1).is_none());
    db.engine.close().unwrap();
    disks.restart(CrashPolicy::DropAll);
    let db = disks.open().unwrap();
    accept(&db.anchors(), db.generators(), &first);
    // k_scramble survived the SECRETS rewrites: the same IDs still find their records.
    assert!(matches!(
        db.delete(cid, "rec-2"),
        Ok(Deleted::Deleted { .. })
    ));
}

#[test]
// oracle: A §10.4 "Each witness remembers the last log checkpoint it cosigned … and only then cosigns"
#[spec("SR-10.4-1")]
fn p3_root_witnesses_remember_what_they_cosigned_across_restarts() {
    let disks = Disks::new();
    let user = KeyPair::generate();
    let (db, cid) = base(&disks, &user);
    cert(db.delete(cid, "rec-0").unwrap());
    let latest = db.latest_log_checkpoint().unwrap().checkpoint;
    drop(db);
    disks.restart(CrashPolicy::DropAll);
    let keys: Arc<dyn sever_vfs::Vfs> = Arc::new(disks.keys.clone());
    let mut op = OperatorStore::load(Arc::clone(&keys), T0, None).unwrap();
    let mut ws = witnesses::load(Arc::clone(&keys), op.genesis_ms(), op.published()).unwrap();
    for w in &ws {
        assert_eq!(*w.last(), latest, "witness {} remembers", w.index());
    }
    // A checkpoint of the same size with another root, honestly signed, is a fork.
    let fork = LogCheckpoint::sign(&mut op, latest.tree_size, [7; 32], T0 + 10).unwrap();
    assert_eq!(ws[0].cosign(&fork, &[], T0 + 10), Err(Refusal::Fork));
}

#[test]
// oracle: A §15.3 step 6 and the §15.4 crash table: no certificate for a rolled-back deletion, no orphaned leaf; acknowledged certificates are retrievable (SB-21)
#[spec("SR-15.3-5")]
fn p3_root_a_crash_anywhere_in_a_deletion_leaves_no_certificate_alone() {
    let disks = Disks::new();
    let user = KeyPair::generate();
    let (db, cid) = base(&disks, &user);
    let n0 = db.engine.stats(cid).unwrap().big_n;
    drop(db);
    let dry = disks.fork();
    let db = dry.open().unwrap();
    dry.data.set_faults(FaultPlan::default());
    dry.keys.set_faults(FaultPlan::default());
    db.delete(cid, "rec-3").unwrap();
    let ops = dry.data.ops_since_plan();
    drop(db);
    assert!(ops >= 8, "{ops} operations");
    for k in 1..=ops {
        for p in [
            CrashPolicy::DropAll,
            CrashPolicy::KeepAll,
            CrashPolicy::Random(k),
        ] {
            let t = disks.fork();
            let db = t.open().unwrap();
            t.data.set_faults(FaultPlan {
                crash_at_op: Some(k),
                tear_bytes: 5,
                ..FaultPlan::default()
            });
            let acked = db.delete(cid, "rec-3").is_ok();
            drop(db);
            t.restart(p);
            let db = t.open().unwrap();
            let n = db.engine.stats(cid).unwrap().big_n;
            let size = db.log.with(|l| l.tree().size()).unwrap();
            let c = db.certificate(6).unwrap();
            if n == n0 {
                assert!(!acked, "op {k} {p:?}");
                assert_eq!(size, 6, "op {k} {p:?}: no delete leaf");
                assert!(
                    c.is_none(),
                    "op {k} {p:?}: no certificate for a rolled-back deletion"
                );
            } else {
                assert_eq!(n, n0 - 1);
                assert_eq!(size, 7);
                accept(
                    &db.anchors(),
                    db.generators(),
                    &c.expect("the committed deletion's certificate"),
                );
            }
        }
    }
}

#[test]
// oracle: A §15.1 steps 1–2: the signature is verified over DST_INSERT ‖ collection_id ‖ C_t of the collection inserted into; one signed for another collection fails (BadUserSignature, §17)
#[spec("SR-15.1-3")]
fn p3_root_a_credential_signed_for_another_collection_is_refused() {
    let disks = Disks::new();
    let user = KeyPair::generate();
    let db = disks.open().unwrap();
    let a = db.create_collection(ARTEFACT, OPTS).unwrap();
    let b = db.create_collection(ARTEFACT, OPTS).unwrap();
    let v = &rows()[0];
    let req = InsertRequest {
        record_id: "r".into(),
        vector: v.clone(),
        credential: credential(&db, &user, a, v),
        passage: None,
    };
    assert_eq!(db.insert(b, req).map(|_| ()), Err(Error::BadUserSignature));
    assert_eq!(db.engine.stats(b).unwrap().big_n, 0, "nothing inserted");
    // The same credential is accepted by the collection it was signed for.
    insert(&db, &user, a, "r", v);
}

#[test]
fn p3_root_refuses_an_artefact_of_another_dimension() {
    let disks = Disks::new();
    let mut s = Settings::new(384);
    s.clock = disks.clock.clone();
    let db = open_on(
        Arc::new(disks.data.clone()),
        Arc::new(disks.keys.clone()),
        s,
    )
    .unwrap();
    assert_eq!(
        db.create_collection(ARTEFACT, OPTS),
        Err(Error::WrongDimension)
    );
}

#[test]
// oracle: A §14.1 "SECRETS … (mode 0600)"; the witnesses' keys beside it (DB-83)
#[spec("SR-14.1-1")]
fn p3_root_on_real_files_keeps_secrets_private() {
    use std::os::unix::fs::PermissionsExt;
    let d = std::path::Path::new(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../target/p3-tests"
    ))
    .join(format!("files-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    let mut o = OpenOptions::new(d.join("data"), d.join("keys"));
    o.d = D;
    o.on_failure = FailurePolicy::Poison;
    let opened = open(&o).unwrap();
    let user = KeyPair::generate();
    let cid = opened.db.create_collection(ARTEFACT, OPTS).unwrap();
    let vs = rows();
    insert(&opened.db, &user, cid, "a", &vs[0]);
    insert(&opened.db, &user, cid, "b", &vs[1]);
    cert(opened.db.delete(cid, "a").unwrap());
    drop(opened);
    let opened = open(&o).unwrap();
    for f in [keys::SECRETS, witnesses::WITNESS_FILE] {
        let mode = std::fs::metadata(d.join("keys").join(f))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(mode & 0o777, 0o600, "{f}");
    }
    assert!(matches!(
        opened.db.delete(cid, "b"),
        Ok(Deleted::Deleted { .. })
    ));
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
// oracle: A DB-86 export (§10.5, §11.3 as amended): leaf i is the insert leaf or 0x02 ‖ certificate (§10.2), its placement the group Part 1's frozen routing returned (C), every checkpoint as checkpoint ‖ u8 count ‖ cosignatures (§11.1 tag 7, §11.2)
#[spec("SR-10.5-3")]
fn p3_root_the_log_export_for_an_auditor() {
    let disks = Disks::new();
    let user = KeyPair::generate();
    let db = disks.open().unwrap();
    let cid = db.create_collection(ARTEFACT, OPTS).unwrap();
    let mut groups = Vec::new();
    for (i, v) in rows().iter().take(3).enumerate() {
        let (_, p) = insert(&db, &user, cid, &format!("r{i}"), v);
        groups.push(match p {
            Placement::Frozen(g) | Placement::Spawned(g) => g.as_text(),
            Placement::Holding => "holding".into(),
        });
    }
    let (lsn, bytes) = cert(db.delete(cid, "r1").unwrap());
    groups.push(groups[1].clone());
    let e: serde_json::Value = serde_json::from_str(&db.export_log().unwrap()).unwrap();
    let leaves = e["leaves"].as_array().unwrap();
    assert_eq!(leaves.len(), 4);
    let mut want = "02".to_owned();
    want.extend(bytes.iter().map(|b| format!("{b:02x}")));
    assert_eq!(leaves[lsn as usize], want.as_str());
    assert_eq!(leaves[0].as_str().unwrap().len(), 2 * 209);
    assert!(leaves[0].as_str().unwrap().starts_with("01"));
    let placed: Vec<&str> = e["placements"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| p["group"].as_str().unwrap())
        .collect();
    assert_eq!(placed, groups);
    assert!(e["placements"][0]["flush"].is_null());
    let cps = e["checkpoints"].as_array().unwrap();
    let last = db.latest_log_checkpoint().unwrap();
    let hex: String = last.to_bytes().iter().map(|b| format!("{b:02x}")).collect();
    assert_eq!(cps.last().unwrap().as_str(), Some(hex.as_str()));
    assert_eq!(
        cps[0].as_str().unwrap().len(),
        2 * (116 + 1),
        "the genesis, uncosigned"
    );
}

#[test]
// oracle: A §9.8 "In v1 the five witnesses are simulated by the project, and their keys live in the test harness" (DB-53, DB-83: the key directory's WITNESSES file)
#[spec("SR-9.8-8")]
fn p3_root_five_simulated_witnesses_with_harness_keys() {
    let disks = Disks::new();
    let user = KeyPair::generate();
    let (db, cid) = base(&disks, &user);
    cert(db.delete(cid, "rec-0").unwrap());
    let a = db.anchors();
    assert_eq!(a.witnesses.len(), 5, "five witnesses");
    for (i, ring) in a.witnesses.iter().enumerate() {
        assert!(ring.get(0).is_some(), "witness {i} has an epoch-0 key");
    }
    let held = sever_vfs::read_all(
        disks
            .keys
            .open(witnesses::WITNESS_FILE, sever_vfs::OpenMode::Existing)
            .unwrap()
            .as_ref(),
    )
    .unwrap();
    assert_eq!(
        &held[..8],
        b"SVDBWITN",
        "their keys live in the key directory"
    );
    assert_eq!(held[8 + 2 + 8], 5, "one entry per witness");
}
