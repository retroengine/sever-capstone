//! A Part 4 engine on simulated disks (the fixture partition, d = 16, spawn target 8).

use std::sync::Arc;

use sever_engine::{CollectionOptions, Engine, EngineConfig, FailurePolicy, InsertRequest};
use sever_index::NoExtension;
use sever_seal::{AeadSealer, KeyRing};
use sever_txn::TxnParticipant;
use sever_types::{CollectionId, Error};
use sever_vfs::{CrashPolicy, SimVfs};

use crate::KeyRotationParticipant;

pub const ARTEFACT: &[u8] = include_bytes!("../../../../golden/p1_partition_small.svp");

pub type Db = Engine<NoExtension, AeadSealer>;

pub fn vectors() -> Vec<Vec<f32>> {
    let doc: serde_json::Value =
        serde_json::from_str(include_str!("../../../../golden/p1_fixture_vectors.json")).unwrap();
    let mut out = Vec::new();
    for key in ["ref", "live"] {
        for h in doc[key].as_array().unwrap() {
            let h = h.as_str().unwrap();
            out.push(
                (0..h.len() / 8)
                    .map(|i| {
                        let b: Vec<u8> = (0..4)
                            .map(|j| {
                                u8::from_str_radix(&h[8 * i + 2 * j..8 * i + 2 * j + 2], 16)
                                    .unwrap()
                            })
                            .collect();
                        f32::from_le_bytes(b.try_into().unwrap())
                    })
                    .collect(),
            );
        }
    }
    out
}

pub fn cfg(checkpoint_every: u64) -> EngineConfig {
    EngineConfig {
        wal_segment_bytes: 256 * 1024,
        store_segment_bytes: 64 * 1024,
        checkpoint_every_wal_bytes: checkpoint_every,
        on_failure: FailurePolicy::Poison,
        config_hash: [5; 32],
    }
}

pub const OPTS: CollectionOptions = CollectionOptions {
    spawn_target: 8,
    spawning_enabled: true,
    store_passages: true,
};

#[derive(Clone)]
pub struct Disks {
    pub data: SimVfs,
    pub keys: SimVfs,
}

impl Disks {
    pub fn new() -> Self {
        Self {
            data: SimVfs::new(),
            keys: SimVfs::new(),
        }
    }
    pub fn restart(&self, p: CrashPolicy) {
        self.data.restart(p);
        self.keys.restart(p);
    }
    /// Opens (recovering) the engine; returns it and the ring its sealer and participant share.
    pub fn open(&self, checkpoint_every: u64) -> Result<(Db, Arc<KeyRing>), Error> {
        let ring = Arc::new(KeyRing::new());
        let participant: Box<dyn TxnParticipant<NoExtension>> =
            Box::new(KeyRotationParticipant::new(
                Arc::new(self.data.clone()),
                Arc::new(self.keys.clone()),
                Arc::clone(&ring),
                64 * 1024,
            ));
        let db = Engine::open(
            Arc::new(self.data.clone()),
            Arc::new(self.keys.clone()),
            AeadSealer::new(Arc::clone(&ring)),
            NoExtension,
            vec![participant],
            cfg(checkpoint_every),
        )?;
        Ok((db, ring))
    }
}

pub fn insert(db: &Db, cid: CollectionId, id: &str, v: &[f32]) -> Result<(), Error> {
    db.insert(
        cid,
        InsertRequest {
            record_id: id.to_owned(),
            vector: v.to_vec(),
            credential: (),
            passage: Some(format!("passage of {id}").into_bytes()),
        },
    )
    .map(|_| ())
}

/// `n` near-copies of `v` (each nudged in one coordinate and renormalised): they route together, so
/// a cohort of them in the holding area spawns a group (§7.5).
pub fn cohort(v: &[f32], n: usize) -> Vec<Vec<f32>> {
    (0..n)
        .map(|k| {
            let mut w: Vec<f64> = v.iter().map(|x| f64::from(*x)).collect();
            let at = k % w.len();
            w[at] += 1e-3 * (1.0 + k as f64);
            let norm = w.iter().map(|x| x * x).sum::<f64>().sqrt();
            w.iter().map(|x| (x / norm) as f32).collect()
        })
        .collect()
}

/// The index of a fixture vector that the router sends to the holding area.
pub fn holding_vector(db: &Db, cid: CollectionId) -> Vec<f32> {
    let vs = vectors();
    for (i, v) in vs.iter().enumerate().take(40) {
        if db.location(cid, &format!("r{i}")).as_deref() == Some("holding") {
            return v.clone();
        }
    }
    vs[0].clone()
}
