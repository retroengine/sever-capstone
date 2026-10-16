//! L8 tests of `LogParticipant` inside the Part 2 engine (Build 3-4 §1.8): inserts append their
//! leaves, deletions return certificates that the §11.3 steps (written out here) accept, a
//! `delete_user` chains its certificates, everything survives restarts and crashes, and too few
//! witnesses stop a deletion. Expected values come from the spec (oracle A).

// Test code (clippy.toml allows these in #[test] functions; the helpers here are test code too).
#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::expect_used,
    clippy::panic
)]

use std::sync::Arc;

use rand_core::{OsRng, RngCore};
use sever_cert::Certificate;
use sever_cert::participant::{
    LOG_PARTICIPANT_ID, LogHandle, LogParticipant, LogParts, due_checkpoints,
};
use sever_commit::{CommitmentExtension, InsertCredential, LeafLog};
use sever_crypto::{
    DeletionContext, Generators, KeyPair, Scalar, certificate_message, commit_record,
    cosign_message, decode_point, encode_point, insert_message, transition_holds, verify,
    verify_signature,
};
use sever_engine::{
    CollectionOptions, DeleteOutcome, Engine, EngineConfig, FailurePolicy, InsertRequest,
};
use sever_index::Placement;
use sever_log::checkpoint::{CHECKPOINT_EVERY, LogCheckpoint, THRESHOLD};
use sever_log::keys::{EpochSigner, Keyring};
use sever_log::leaf::{InsertLeaf, Placement as LeafPlacement, delete_leaf};
use sever_log::merkle::{leaf_hash, verify_inclusion};
use sever_log::store::LogStoreConfig;
use sever_log::witness::{SimulatedWitness, Witness};
use sever_spec::spec;
use sever_txn::{PlaintextSealer, SimClock, TxnKind};
use sever_types::{CollectionId, Error, GroupId};
use sever_vfs::{CrashPolicy, FaultPlan, SimVfs};

const ARTEFACT: &[u8] = include_bytes!("../../../golden/p1_partition_small.svp");
const D: usize = 16;
const GENESIS: u64 = 1_790_000_000_000;
const OPTS: CollectionOptions = CollectionOptions {
    spawn_target: 8,
    spawning_enabled: true,
    store_passages: false,
};

type Db = Engine<CommitmentExtension, PlaintextSealer>;

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

/// The disks, the operator's and the user's keys (from the OS), and how many witnesses honour
/// the operator: a database the tests reopen as often as they like.
struct World {
    data: SimVfs,
    keys: SimVfs,
    gens: Arc<Generators>,
    operator: Vec<(u32, [u8; 32])>,
    user: KeyPair,
    clock: Arc<SimClock>,
    honest_witnesses: usize,
}

struct Open {
    db: Db,
    log: Arc<LogHandle>,
}

fn secret() -> [u8; 32] {
    let mut s = [0u8; 32];
    OsRng.fill_bytes(&mut s);
    s
}

impl World {
    fn new() -> Self {
        Self {
            data: SimVfs::new(),
            keys: SimVfs::new(),
            gens: Arc::new(Generators::derive(D).unwrap()),
            operator: (0..3).map(|e| (e, secret())).collect(),
            user: KeyPair::generate(),
            clock: Arc::new(SimClock::new(GENESIS + 1_000)),
            honest_witnesses: 5,
        }
    }

    /// Opens the engine with a fresh log participant and fresh simulated witnesses (a witness
    /// that does not honour the operator trusts no operator key, so it refuses every checkpoint).
    fn open(&self) -> Result<Open, Error> {
        let mut op = EpochSigner::from_secrets(GENESIS, self.operator.clone());
        let operator_ring = op.keyring().clone();
        let genesis = LogCheckpoint::genesis(&mut op).unwrap();
        let witnesses: Vec<Box<dyn Witness>> = (0..5u8)
            .map(|i| {
                let ring = if usize::from(i) < self.honest_witnesses {
                    operator_ring.clone()
                } else {
                    Keyring::new()
                };
                Box::new(SimulatedWitness::new(i, GENESIS, ring, genesis)) as Box<dyn Witness>
            })
            .collect();
        let (participant, log) = LogParticipant::new(
            Arc::new(self.data.clone()),
            LogParts {
                gens: Arc::clone(&self.gens),
                clock: self.clock.clone(),
                operator: Box::new(op),
                witnesses,
                store: LogStoreConfig {
                    sealer_id: 0,
                    segment_bytes: 1 << 20,
                },
            },
        );
        let ext =
            CommitmentExtension::new(Arc::clone(&self.gens), Arc::clone(&log) as Arc<dyn LeafLog>);
        let db = Engine::open(
            Arc::new(self.data.clone()),
            Arc::new(self.keys.clone()),
            PlaintextSealer,
            ext,
            vec![Box::new(participant)],
            EngineConfig {
                on_failure: FailurePolicy::Poison,
                ..EngineConfig::default()
            },
        )?;
        Ok(Open { db, log })
    }

    /// What the SDK does (§16.2): quantise, draw `r_t` from the OS, compute `C_t`, sign.
    fn credential(&self, cid: CollectionId, v: &[f32]) -> InsertCredential {
        let x = sever_quant::quantise(v, D).unwrap();
        let mut wide = [0u8; 64];
        OsRng.fill_bytes(&mut wide);
        let r_t = Scalar::from_bytes_mod_order_wide(&wide);
        let c_t = encode_point(&commit_record(&self.gens, x.as_slice(), &r_t).unwrap());
        InsertCredential {
            collection_id: *cid.as_bytes(),
            c_t,
            r_t: r_t.to_bytes(),
            user_public_key: self.user.public(),
            signature: self.user.sign(&insert_message(cid.as_bytes(), &c_t)),
        }
    }

    fn insert(&self, o: &Open, cid: CollectionId, id: &str, v: &[f32]) -> Placement {
        o.db.insert(
            cid,
            InsertRequest {
                record_id: id.into(),
                vector: v.to_vec(),
                credential: self.credential(cid, v),
                passage: None,
            },
        )
        .unwrap()
        .placement
    }
}

/// The certificate in a deletion's outputs.
fn cert_of(out: &DeleteOutcome) -> Vec<u8> {
    let DeleteOutcome::Deleted { outputs } = out else {
        panic!("not deleted")
    };
    assert_eq!(outputs.len(), 1);
    assert_eq!(outputs[0].0, LOG_PARTICIPANT_ID);
    outputs[0].1.clone()
}

/// §11.3 steps 1–8, written out from the spec, against the anchors of `o`.
fn accept(o: &Open, gens: &Generators, bytes: &[u8]) -> Certificate {
    accept_with(&o.log.anchors(), gens, bytes)
}

/// §11.3 steps 1–8 against given anchors (the operator's keys, each witness's keys).
fn accept_with(anchors: &(Keyring, Vec<Keyring>), gens: &Generators, bytes: &[u8]) -> Certificate {
    let (operator_ring, witness_rings) = anchors;
    let c = Certificate::parse(bytes, D).unwrap(); // step 1 (the layout)
    assert_ne!(c.c_t, [0; 32], "step 1: C_t is not the identity");
    let key = operator_ring.get(c.key_period).unwrap(); // step 2
    let body = &bytes[..bytes.len() - 69];
    verify_signature(key, &certificate_message(body), &c.operator_signature).unwrap();
    let inc = &c.inclusion; // step 3
    let leaf = inc.leaf;
    assert_eq!(
        (
            leaf.collection_id,
            leaf.scrambled_id,
            leaf.c_t,
            leaf.user_signature
        ),
        (c.collection_id, c.scrambled_id, c.c_t, c.user_signature)
    );
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
    assert!(cp.verify(operator_ring));
    let mut good = std::collections::BTreeSet::new(); // step 4
    for s in &c.cosignatures {
        let ring = &witness_rings[usize::from(s.witness_index)];
        let k = ring.get(s.witness_epoch).unwrap();
        if verify_signature(k, &cosign_message(&cp.message()), &s.signature).is_ok() {
            good.insert(s.witness_index);
        }
    }
    assert!(
        good.len() >= THRESHOLD,
        "step 4: {} distinct witnesses",
        good.len()
    );
    assert!(c.database_lsn > inc.leaf_index, "step 5");
    if let Some(g) = &c.group {
        // step 6
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
        assert_eq!(g.emptied, g.c_s_post == [0; 32]);
    }
    c
}

/// A database with one collection and `n` records; the placements in insert order.
fn base(w: &World, n: usize) -> (Open, CollectionId, Vec<(String, Placement)>) {
    let o = w.open().unwrap();
    let cid = o.db.create_collection(ARTEFACT, OPTS).unwrap();
    let vs = rows("ref");
    let placed = (0..n)
        .map(|i| {
            let id = format!("rec-{i:02}");
            let p = w.insert(&o, cid, &id, &vs[i]);
            (id, p)
        })
        .collect();
    (o, cid, placed)
}

fn in_group(placed: &[(String, Placement)]) -> Vec<String> {
    placed
        .iter()
        .filter(|(_, p)| !matches!(p, Placement::Holding))
        .map(|(id, _)| id.clone())
        .collect()
}

#[test]
// oracle: A §10.2 insert leaf layout; §15.1 step 6 every insert appends its leaf; step 9 returns database_lsn, the leaf's index (§10.2)
#[spec("SR-10.2-1", "SR-15.1-4", "SR-15.1-5")]
fn p3_log_txn_every_insert_appends_its_insert_leaf() {
    let w = World::new();
    let (o, cid, placed) = base(&w, 6);
    let size = o.log.with(|l| l.tree().size()).unwrap();
    assert_eq!(size, 6, "one leaf per insert, in order");
    let v = &rows("ref")[50];
    let receipt =
        o.db.insert(
            cid,
            InsertRequest {
                record_id: "seventh".into(),
                vector: v.clone(),
                credential: w.credential(cid, v),
                passage: None,
            },
        )
        .unwrap();
    assert_eq!(
        receipt.outputs,
        vec![(LOG_PARTICIPANT_ID, 6u64.to_be_bytes().to_vec())]
    );
    for (i, _) in placed.iter().enumerate() {
        let leaf: InsertLeaf = o
            .log
            .with(|l| l.insert_leaf(i as u64))
            .unwrap()
            .unwrap()
            .unwrap();
        assert_eq!(leaf.collection_id, *cid.as_bytes());
        assert_eq!(leaf.user_public_key, w.user.public());
        verify_signature(
            &w.user.public(),
            &insert_message(cid.as_bytes(), &leaf.c_t),
            &leaf.user_signature,
        )
        .unwrap();
        assert_eq!(
            o.log.with(|l| l.tree().leaf(i as u64)),
            Some(Some(leaf_hash(&leaf.to_bytes())))
        );
    }
}

#[test]
// oracle: A §11.3 steps 1–8 written out in the test; §15.3 steps 3–4, 9: a witnessed checkpoint covering the insert leaf, database_lsn = the next leaf index, the certificate acknowledged; §10.2 the delete leaf is 0x02 ‖ certificate
#[spec("SR-15.3-4", "SR-15.3-6", "SR-10.3-3", "SR-10.2-2", "SR-10.2-3")]
fn p3_log_txn_a_deletion_returns_a_certificate_section_11_3_accepts() {
    let w = World::new();
    let (o, cid, placed) = base(&w, 6);
    let victim = in_group(&placed).remove(0);
    let bytes = cert_of(&o.db.delete(cid, &victim).unwrap());
    let c = accept(&o, &w.gens, &bytes);
    assert_eq!(
        c.database_lsn, 6,
        "the next leaf index: six inserts came first"
    );
    assert_eq!(
        c.inclusion.checkpoint.tree_size, 6,
        "an on-demand checkpoint covers every leaf"
    );
    assert!(c.group.is_some());
    let delete = o
        .log
        .with(|l| (l.tree().leaf(6), l.certificate(6)))
        .unwrap();
    assert_eq!(delete.0, Some(leaf_hash(&delete_leaf(&bytes))));
    assert_eq!(delete.1, Ok(Some(bytes)));
    // A retried deletion is AlreadyAbsent and appends nothing (§10.2: none for AlreadyAbsent).
    assert_eq!(
        o.db.delete(cid, &victim).unwrap(),
        DeleteOutcome::AlreadyAbsent
    );
    assert_eq!(o.log.with(|l| l.tree().size()), Some(7));
}

#[test]
// oracle: A §15.3 "delete_user does steps 1–4 for every record in list order. Each certificate is built on the state left by the previous one, so consecutive certificates chain"; §11.3 step 7 holding-area certificates
#[spec("SR-15.3-4")]
fn p3_log_txn_delete_user_certificates_chain() {
    let w = World::new();
    let (o, cid, placed) = base(&w, 12);
    let grouped = in_group(&placed);
    // Two records of one group (the first group that holds two), then a holding-area record.
    let mut by_group: std::collections::BTreeMap<String, Vec<String>> = Default::default();
    for (id, p) in &placed {
        if let Placement::Frozen(g) | Placement::Spawned(g) = p {
            by_group.entry(g.as_text()).or_default().push(id.clone());
        }
    }
    let pair = by_group
        .values()
        .find(|v| v.len() >= 2)
        .expect("a group with two records")
        .clone();
    assert!(!grouped.is_empty());
    // A "live" fixture vector lands in the holding area (no flush: fewer than 8 there).
    assert_eq!(
        w.insert(&o, cid, "held", &rows("live")[0]),
        Placement::Holding
    );
    let list = [pair[0].as_str(), "never-inserted", pair[1].as_str(), "held"];
    let outs = o.db.delete_user(cid, &list).unwrap();
    assert_eq!(outs[1], DeleteOutcome::AlreadyAbsent);
    let c1 = accept(&o, &w.gens, &cert_of(&outs[0]));
    let c2 = accept(&o, &w.gens, &cert_of(&outs[2]));
    assert_eq!(c2.database_lsn, c1.database_lsn + 1);
    assert_eq!(
        c2.group.as_ref().unwrap().c_s_pre,
        c1.group.as_ref().unwrap().c_s_post,
        "C_S_pre of the second is C_S_post of the first"
    );
    let ch = accept(&o, &w.gens, &cert_of(&outs[3]));
    assert!(ch.group.is_none());
    assert_eq!(ch.deletion_kind(), 1);
    assert_eq!(ch.database_lsn, c2.database_lsn + 1);
}

#[test]
// oracle: A §14.8 certificates and insert leaves are append-store records; §15.4 "the certificate is retrievable by database_lsn"; §12.4 a storage checkpoint truncates the WAL
#[spec("SR-14.8-2")]
fn p3_log_txn_certificates_survive_restarts_and_storage_checkpoints() {
    let w = World::new();
    let (o, cid, placed) = base(&w, 8);
    let ids = in_group(&placed);
    let first = cert_of(&o.db.delete(cid, &ids[0]).unwrap());
    o.db.close().unwrap(); // a storage checkpoint: the WAL no longer holds the log's records
    w.data.restart(CrashPolicy::DropAll);
    w.keys.restart(CrashPolicy::DropAll);
    let o = w.open().unwrap();
    assert_eq!(
        o.log.with(|l| l.certificate(8)),
        Some(Ok(Some(first.clone())))
    );
    let second = cert_of(&o.db.delete(cid, &ids[1]).unwrap());
    let c = accept(&o, &w.gens, &second);
    assert_eq!(c.database_lsn, 9, "after the checkpointed deletion at 8");
    drop(o); // no storage checkpoint: recovery replays the WAL tail
    w.data.restart(CrashPolicy::DropAll);
    w.keys.restart(CrashPolicy::DropAll);
    let o = w.open().unwrap();
    assert_eq!(o.log.with(|l| l.certificate(8)), Some(Ok(Some(first))));
    assert_eq!(o.log.with(|l| l.certificate(9)), Some(Ok(Some(second))));
    assert_eq!(o.log.with(|l| l.check_invariants()), Some(Ok(())));
}

#[test]
// oracle: A §15.3 step 6 and the §15.4 crash table: the delete leaf and the certificate commit with the state change; no certificate for a rolled-back deletion, no orphaned leaf
#[spec("SR-15.3-5")]
fn p3_log_txn_a_crash_anywhere_in_a_deletion_is_all_or_nothing() {
    let w = World::new();
    let (o, cid, placed) = base(&w, 6);
    let victim = in_group(&placed).remove(0);
    let before = o.db.stats(cid).unwrap().big_n;
    drop(o);
    // Count the VFS operations of one deletion, then crash at each one in turn.
    let dry = World {
        data: w.data.fork(),
        keys: w.keys.fork(),
        ..World::new_like(&w)
    };
    let od = dry.open().unwrap();
    dry.data.set_faults(FaultPlan::default());
    od.db.delete(cid, &victim).unwrap();
    let ops = dry.data.ops_since_plan();
    drop(od);
    assert!(ops >= 8, "{ops} operations");
    for k in 1..=ops {
        for policy in [
            CrashPolicy::DropAll,
            CrashPolicy::KeepAll,
            CrashPolicy::Random(k),
        ] {
            let t = World {
                data: w.data.fork(),
                keys: w.keys.fork(),
                ..World::new_like(&w)
            };
            let ot = t.open().unwrap();
            t.data.set_faults(FaultPlan {
                crash_at_op: Some(k),
                tear_bytes: 5,
                ..FaultPlan::default()
            });
            let r = ot.db.delete(cid, &victim);
            // The simulated witnesses' keys live in memory (module 6 keeps them): take the anchors
            // the deletion was certified under before the crash.
            let anchors = ot.log.anchors();
            drop(ot);
            t.data.restart(policy);
            t.keys.restart(policy);
            let ot = t.open().unwrap();
            let n = ot.db.stats(cid).unwrap().big_n;
            let (size, cert) = ot
                .log
                .with(|l| (l.tree().size(), l.certificate(6)))
                .unwrap();
            if n == before {
                assert!(r.is_err(), "op {k}: the deletion was not acknowledged");
                assert_eq!(
                    (size, cert),
                    (6, Ok(None)),
                    "op {k}: no leaf, no certificate"
                );
            } else {
                assert_eq!(n, before - 1, "op {k}");
                let bytes = cert
                    .unwrap()
                    .expect("op {k}: the certificate of a committed deletion");
                assert_eq!(size, 7);
                accept_with(&anchors, &w.gens, &bytes);
            }
            assert_eq!(ot.log.with(|l| l.check_invariants()), Some(Ok(())));
        }
    }
}

impl World {
    /// Another world on the same keys (for forked disks).
    fn new_like(w: &World) -> World {
        World {
            data: SimVfs::new(),
            keys: SimVfs::new(),
            gens: Arc::clone(&w.gens),
            operator: w.operator.clone(),
            user: KeyPair::generate(), // unused: no inserts on forks
            clock: Arc::clone(&w.clock),
            honest_witnesses: w.honest_witnesses,
        }
    }
}

#[test]
// oracle: A §10.4 "A log checkpoint with at least four valid cosignatures is witnessed"; §15.3 step 3: a deletion needs a witnessed checkpoint
#[spec("SR-10.4-2", "SR-10.3-3")]
fn p3_log_txn_a_deletion_needs_four_witnesses() {
    let mut w = World::new();
    w.honest_witnesses = 4;
    let (o, cid, placed) = base(&w, 6);
    let ids = in_group(&placed);
    let c = accept(&o, &w.gens, &cert_of(&o.db.delete(cid, &ids[0]).unwrap()));
    assert_eq!(
        c.cosignatures.len(),
        4,
        "the refusing witness signed nothing"
    );
    drop(o);
    w.honest_witnesses = 3;
    let o = w.open().unwrap();
    w.insert(&o, cid, "late", &rows("ref")[0]); // a leaf no witnessed checkpoint covers
    let n = o.db.stats(cid).unwrap().big_n;
    assert!(matches!(
        o.db.delete(cid, &ids[1]),
        Err(Error::IntegrityViolation { .. })
    ));
    assert_eq!(o.db.stats(cid).unwrap().big_n, n, "nothing changed");
}

#[test]
// oracle: A §10.3 "whenever tree_size reaches a multiple of 10,000 (both leaf types count), and on demand before a deletion"; DB-80, DB-82
#[spec("SR-10.3-2", "SR-10.3-3")]
fn p3_log_txn_due_checkpoints_follow_section_10_3() {
    let e = CHECKPOINT_EVERY;
    assert_eq!(e, 10_000);
    assert_eq!(
        due_checkpoints(0, 0, 9_999, TxnKind::Insert),
        Vec::<u64>::new()
    );
    assert_eq!(due_checkpoints(0, 0, 10_000, TxnKind::Insert), [10_000]);
    assert_eq!(
        due_checkpoints(0, 0, 20_003, TxnKind::Insert),
        [10_000, 20_000]
    );
    assert_eq!(
        due_checkpoints(10_000, 10_000, 10_003, TxnKind::Insert),
        Vec::<u64>::new()
    );
    assert_eq!(
        due_checkpoints(10_000, 10_000, 10_003, TxnKind::Delete),
        [10_003]
    );
    assert_eq!(
        due_checkpoints(10_003, 10_003, 10_003, TxnKind::Delete),
        Vec::<u64>::new()
    );
    assert_eq!(
        due_checkpoints(9_990, 9_990, 10_000, TxnKind::Delete),
        [10_000]
    );
    assert_eq!(
        due_checkpoints(10_000, 0, 10_000, TxnKind::Delete),
        [10_000],
        "covered, but not witnessed"
    );
    assert_eq!(
        due_checkpoints(0, 0, 5, TxnKind::CreateCollection),
        Vec::<u64>::new()
    );
}

fn group_of(p: &Placement) -> GroupId {
    match p {
        Placement::Frozen(g) | Placement::Spawned(g) => *g,
        Placement::Holding => GroupId::Holding,
    }
}

#[test]
// oracle: C the placement Part 1's frozen routing returns for each insert (§7.3, §15.2 flush at the spawn target); A DB-86: each leaf's placement is the group its record joined or left, and a flush names the group it created
#[spec("SR-10.5-3")]
fn p3_log_txn_every_leaf_records_its_placement() {
    let w = World::new();
    let (o, cid, placed) = base(&w, 6);
    let mut want: Vec<LeafPlacement> = placed
        .iter()
        .map(|(_, p)| LeafPlacement {
            group: group_of(p),
            flush: None,
        })
        .collect();
    // "Live" fixture vectors go to the holding area; the eighth one flushes it (spawn target 8).
    let mut spawned = None;
    for (i, v) in rows("live").iter().take(8).enumerate() {
        let p = w.insert(&o, cid, &format!("live-{i}"), v);
        let flush = match p {
            Placement::Spawned(g) => {
                spawned = Some(g);
                Some(g)
            }
            _ => None,
        };
        want.push(LeafPlacement {
            group: group_of(&p),
            flush,
        });
    }
    let spawned = spawned.expect("the eighth holding insert flushes");
    assert_eq!(want.last().unwrap().group, spawned);
    assert!(matches!(
        w.insert(&o, cid, "held", &rows("live")[8]),
        Placement::Holding
    ));
    want.push(LeafPlacement {
        group: GroupId::Holding,
        flush: None,
    });
    // Deletions: a frozen-group record, a founder of the spawned group, the held record.
    let frozen = placed
        .iter()
        .find(|(_, p)| matches!(p, Placement::Frozen(_)))
        .unwrap();
    for (id, g) in [
        (frozen.0.as_str(), group_of(&frozen.1)),
        ("live-3", spawned),
        ("held", GroupId::Holding),
    ] {
        let out = o.db.delete(cid, id).unwrap();
        accept(&o, &w.gens, &cert_of(&out));
        want.push(LeafPlacement {
            group: g,
            flush: None,
        });
    }
    let e = o.log.with(|l| l.export()).unwrap().unwrap();
    assert_eq!(e.placements, want);
    assert_eq!(e.leaves.len(), want.len());
    // It survives a restart.
    drop(o);
    let o = w.open().unwrap();
    assert_eq!(
        o.log.with(|l| l.export()).unwrap().unwrap().placements,
        want
    );
}
