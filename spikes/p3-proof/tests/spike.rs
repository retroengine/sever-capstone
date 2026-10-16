//! The Part 3 proof spike (Build 3-4 §1.11), end to end: the Part 3 engine composed with an AEAD
//! sealer and a key-rotation participant beside `LogParticipant`, with no Part 3 file changed.

#![allow(clippy::unwrap_used, clippy::indexing_slicing)]

use std::sync::{Arc, Mutex};

use rand_core::{OsRng, RngCore};
use sever_cert::Certificate;
use sever_cert::participant::{LOG_PARTICIPANT_ID, LogParticipant, LogParts};
use sever_commit::{CommitmentExtension, InsertCredential, LeafLog};
use sever_crypto::{
    DeletionContext, Generators, KeyPair, Scalar, commit_record, encode_point, insert_message,
    verify,
};
use sever_engine::{
    CollectionOptions, DeleteOutcome, Engine, EngineConfig, FailurePolicy, InsertRequest,
};
use sever_log::checkpoint::LogCheckpoint;
use sever_log::keys::EpochSigner;
use sever_log::store::LogStoreConfig;
use sever_log::witness::{SimulatedWitness, Witness};
use sever_spike_p3_proof::{AeadSealer, Seen, Shared, StubRotation};
use sever_txn::SimClock;
use sever_vfs::{CrashPolicy, OpenMode, SimVfs, Vfs, VfsError, read_all};

const ARTEFACT: &[u8] = include_bytes!("../../../golden/p1_partition_small.svp");
const GENESIS: u64 = 1_790_000_000_000;

fn rows() -> Vec<Vec<f32>> {
    let doc: serde_json::Value =
        serde_json::from_str(include_str!("../../../golden/p1_fixture_vectors.json")).unwrap();
    doc["ref"]
        .as_array()
        .unwrap()
        .iter()
        .map(|h| {
            let b: Vec<u8> = (0..h.as_str().unwrap().len() / 2)
                .map(|i| u8::from_str_radix(&h.as_str().unwrap()[2 * i..2 * i + 2], 16).unwrap())
                .collect();
            b.chunks(4)
                .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
                .collect()
        })
        .collect()
}

/// Every file's bytes on a simulated disk.
fn all_bytes(v: &dyn Vfs, dir: &str, out: &mut Vec<u8>) {
    for name in v.list(dir).unwrap_or_default() {
        let path = if dir.is_empty() { name } else { format!("{dir}/{name}") };
        match v.open(&path, OpenMode::Existing) {
            Ok(f) => out.extend(read_all(f.as_ref()).unwrap()),
            Err(VfsError::IsADirectory) => all_bytes(v, &path, out),
            Err(_) => {}
        }
    }
}

type Db = Engine<CommitmentExtension, Shared>;

struct World {
    data: SimVfs,
    keys: SimVfs,
    gens: Arc<Generators>,
    operator: Vec<(u32, [u8; 32])>,
    sealer: Arc<AeadSealer>,
    seen: Arc<Mutex<Seen>>,
}

impl World {
    fn open(&self) -> Db {
        let mut op = EpochSigner::from_secrets(GENESIS, self.operator.clone());
        let ring = op.keyring().clone();
        let genesis = LogCheckpoint::genesis(&mut op).unwrap();
        let witnesses: Vec<Box<dyn Witness>> = (0..5u8)
            .map(|i| {
                Box::new(SimulatedWitness::new(i, GENESIS, ring.clone(), genesis))
                    as Box<dyn Witness>
            })
            .collect();
        let (participant, log) = LogParticipant::new(
            Arc::new(self.data.clone()),
            LogParts {
                gens: Arc::clone(&self.gens),
                clock: Arc::new(SimClock::new(GENESIS + 1_000)),
                operator: Box::new(op),
                witnesses,
                store: LogStoreConfig {
                    sealer_id: 1,
                    segment_bytes: 1 << 20,
                },
            },
        );
        let ext = CommitmentExtension::new(Arc::clone(&self.gens), log as Arc<dyn LeafLog>);
        Engine::open(
            Arc::new(self.data.clone()),
            Arc::new(self.keys.clone()),
            Shared(Arc::clone(&self.sealer)),
            ext,
            vec![
                Box::new(participant),
                Box::new(StubRotation(Arc::clone(&self.seen))),
            ],
            EngineConfig {
                on_failure: FailurePolicy::Poison,
                ..EngineConfig::default()
            },
        )
        .unwrap()
    }
}

#[test]
fn p3_spike_part_4_plugs_in_without_touching_part_3() {
    let mut s = [0u8; 32];
    OsRng.fill_bytes(&mut s);
    let w = World {
        data: SimVfs::new(),
        keys: SimVfs::new(),
        gens: Arc::new(Generators::derive(16).unwrap()),
        operator: vec![(0, s)],
        sealer: Arc::new(AeadSealer::default()),
        seen: Arc::default(),
    };
    let user = KeyPair::generate();
    let db = w.open();
    let cid = db
        .create_collection(
            ARTEFACT,
            CollectionOptions {
                spawn_target: 8,
                spawning_enabled: true,
                store_passages: true,
            },
        )
        .unwrap();
    let mut r_ts = Vec::new();
    for (i, v) in rows().iter().take(6).enumerate() {
        let x = sever_quant::quantise(v, 16).unwrap();
        let mut wide = [0u8; 64];
        OsRng.fill_bytes(&mut wide);
        let r = Scalar::from_bytes_mod_order_wide(&wide);
        let c_t = encode_point(&commit_record(&w.gens, x.as_slice(), &r).unwrap());
        r_ts.push(r.to_bytes());
        db.insert(
            cid,
            InsertRequest {
                record_id: format!("r{i}"),
                vector: v.clone(),
                credential: InsertCredential {
                    collection_id: *cid.as_bytes(),
                    c_t,
                    r_t: r.to_bytes(),
                    user_public_key: user.public(),
                    signature: user.sign(&insert_message(cid.as_bytes(), &c_t)),
                },
                passage: Some(b"text".to_vec()),
            },
        )
        .unwrap();
    }
    // A deletion: the certificate comes from LogParticipant, the departures reach the rotation
    // stub, and phases A and C run around the commit.
    let outs = db.delete_user(cid, &["r1", "r2"]).unwrap();
    for o in &outs {
        let DeleteOutcome::Deleted { outputs } = o else {
            panic!("not deleted")
        };
        let cert = &outputs.iter().find(|(p, _)| *p == LOG_PARTICIPANT_ID).unwrap().1;
        let c = Certificate::parse(cert, 16).unwrap();
        if let Some(g) = &c.group {
            let ctx = DeletionContext {
                c_s_pre: g.c_s_pre,
                c_t: c.c_t,
                scrambled_id: c.scrambled_id,
                database_lsn: c.database_lsn,
                collection_id: c.collection_id,
            };
            verify(&w.gens, &g.c_s_post, &ctx, &g.proof).unwrap();
        }
    }
    {
        let seen = w.seen.lock().unwrap();
        assert_eq!(seen.departures.last().map(Vec::len), Some(2), "two departures");
        assert!(seen.phase_a >= 1 && seen.phase_c >= 1);
    }
    // The secrets are sealed: no r_t appears in plaintext on the data disk.
    let mut disk = Vec::new();
    all_bytes(&w.data, "", &mut disk);
    for r in &r_ts {
        assert!(!disk.windows(32).any(|win| win == r), "an r_t is on disk in plaintext");
    }
    // A crash and a recovery with the same sealer keys.
    let n = db.stats(cid).unwrap().big_n;
    drop(db);
    w.data.restart(CrashPolicy::DropAll);
    w.keys.restart(CrashPolicy::DropAll);
    let db = w.open();
    assert_eq!(db.stats(cid).unwrap().big_n, n);
    assert!(matches!(
        db.delete(cid, "r3").unwrap(),
        DeleteOutcome::Deleted { .. }
    ));
}
