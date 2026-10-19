//! §12.6 and §15.3 step 7 on the final engine: a deletion releases the old keys only as zeros,
//! and removes the record's mirror entry. A test `SecretMemory` provider is installed as the
//! process's provider (DB-50) before any secret exists; this binary holds one test, so nothing
//! else allocates from it.

#![allow(clippy::unwrap_used, clippy::indexing_slicing)]

use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

use rand_core::{OsRng, RngCore};
use sever_commit::InsertCredential;
use sever_crypto::{KeyPair, Scalar, commit_record, encode_point, insert_message};
use sever_db::{Deleted, Settings, open_on};
use sever_engine::{CollectionOptions, EngineConfig, FailurePolicy, InsertRequest};
use sever_spec::spec;
use sever_txn::SimClock;
use sever_types::{SecretMemory, SecretRegion, install_provider};
use sever_vfs::SimVfs;

const ARTEFACT: &[u8] = include_bytes!("../../../golden/p1_partition_small.svp");
const VECTORS: &str = include_str!("../../../golden/p1_fixture_vectors.json");
const D: usize = 16;

#[derive(Default)]
struct Counts {
    released: AtomicUsize,
    released_dirty: AtomicUsize,
}

struct Auditing(Arc<Counts>);

struct Region(Vec<u8>, Arc<Counts>);

impl SecretRegion for Region {
    fn bytes(&self) -> &[u8] {
        &self.0
    }
    fn bytes_mut(&mut self) -> &mut [u8] {
        &mut self.0
    }
}

impl Drop for Region {
    fn drop(&mut self) {
        self.1.released.fetch_add(1, Ordering::SeqCst);
        if self.0.iter().any(|&b| b != 0) {
            self.1.released_dirty.fetch_add(1, Ordering::SeqCst);
        }
    }
}

impl SecretMemory for Auditing {
    fn allocate(&self, len: usize) -> Box<dyn SecretRegion> {
        Box::new(Region(vec![0; len], Arc::clone(&self.0)))
    }
}

fn rows() -> Vec<Vec<f32>> {
    let doc: serde_json::Value = serde_json::from_str(VECTORS).unwrap();
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
                    f32::from_le_bytes([b[0], b[1], b[2], b[3]])
                })
                .collect()
        })
        .collect()
}

// oracle: A §12.6 "Deleting a record overwrites its mirror entry, its record ID bytes and every
// decrypted buffer with zeros before the deletion is acknowledged" and §15.3 step 7 ("remove the
// mirror entry, and zero the old keys …"); the deleted record must not be found again (INV-9)
#[spec("SR-12.6-3", "SR-15.3-9")]
#[test]
fn p4_db_a_deletion_releases_its_old_keys_as_zeros_and_removes_the_mirror_entry() {
    let counts = Arc::new(Counts::default());
    assert!(install_provider(Box::new(Auditing(Arc::clone(&counts)))).is_ok());
    let mut s = Settings::new(D);
    s.clock = Arc::new(SimClock::new(1_790_000_000_000));
    s.engine = EngineConfig {
        on_failure: FailurePolicy::Poison,
        ..EngineConfig::default()
    };
    let db = open_on(Arc::new(SimVfs::new()), Arc::new(SimVfs::new()), s).unwrap();
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
    let user = KeyPair::generate();
    let rows = rows();
    for (i, v) in rows.iter().take(6).enumerate() {
        let x = sever_quant::quantise(v, D).unwrap();
        let mut wide = [0u8; 64];
        OsRng.fill_bytes(&mut wide);
        let r_t = Scalar::from_bytes_mod_order_wide(&wide);
        let c_t = encode_point(&commit_record(db.generators(), x.as_slice(), &r_t).unwrap());
        db.insert(
            cid,
            InsertRequest {
                record_id: format!("record-{i}"),
                vector: v.clone(),
                credential: InsertCredential {
                    collection_id: *cid.as_bytes(),
                    c_t,
                    r_t: r_t.to_bytes(),
                    user_public_key: user.public(),
                    signature: user.sign(&insert_message(cid.as_bytes(), &c_t)),
                },
                passage: Some(b"a passage that must not outlive its record".to_vec()),
            },
        )
        .unwrap();
    }
    let hits = db.engine.search(cid, &rows[2], 3).unwrap();
    assert!(
        hits.iter().any(|h| h.record_id == "record-2"),
        "found before"
    );
    let before = counts.released.load(Ordering::SeqCst);
    assert!(matches!(
        db.delete(cid, "record-2").unwrap(),
        Deleted::Deleted { .. }
    ));
    // The rotation retired the group's old key and the bucket's old key: released, as zeros.
    assert!(
        counts.released.load(Ordering::SeqCst) > before,
        "old keys released"
    );
    assert_eq!(counts.released_dirty.load(Ordering::SeqCst), 0);
    let hits = db.engine.search(cid, &rows[2], 6).unwrap();
    assert!(
        hits.iter().all(|h| h.record_id != "record-2"),
        "the mirror entry is gone"
    );
    drop(db);
    assert_eq!(counts.released_dirty.load(Ordering::SeqCst), 0);
}
