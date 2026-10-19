//! The scanner on a real database written to simulated disks, laid out as one image (each file
//! padded to 4 KiB, as a filesystem would place it). Expected outcomes come from Build 3-4 §2.8
//! Forensics: planted secrets are found every time, live records are recovered through the
//! carved keys (the scanner can see), and nothing of a deleted record is found (oracle A).

use std::sync::{Arc, Mutex, OnceLock};

use rand_core::{OsRng, RngCore};
use sever_commit::InsertCredential;
use sever_crypto::{KeyPair, Scalar, commit_record, encode_point, insert_message};
use sever_db::{Deleted, Settings, open_on};
use sever_engine::{CollectionOptions, EngineConfig, FailurePolicy, InsertRequest};
use sever_index::IdScrambler;
use sever_spec::spec;
use sever_txn::SimClock;
use sever_types::RecordId;
use sever_vfs::{OpenMode, SimVfs, Vfs, read_all};

use super::*;

const ARTEFACT: &[u8] = include_bytes!("../../../golden/p1_partition_small.svp");
const D: usize = 16;

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

/// Every fixture vector, `ref` then `live`.
fn all_vectors() -> Vec<Vec<f32>> {
    let doc: serde_json::Value =
        serde_json::from_str(include_str!("../../../golden/p1_fixture_vectors.json")).unwrap();
    ["ref", "live"]
        .iter()
        .flat_map(|k| doc[*k].as_array().unwrap().clone())
        .map(|h| {
            let h = h.as_str().unwrap().to_owned();
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

/// `n` near-copies of `v` (each nudged in one coordinate and renormalised): they route together,
/// so a cohort of them in the holding area spawns a group (§7.5).
fn cohort(v: &[f32], n: usize) -> Vec<Vec<f32>> {
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

/// Every key generated in this test binary (DB-54 `key-export`).
fn exported() -> &'static Mutex<Vec<[u8; 32]>> {
    static K: OnceLock<&'static Mutex<Vec<[u8; 32]>>> = OnceLock::new();
    K.get_or_init(|| {
        let keys: &'static Mutex<Vec<[u8; 32]>> = Box::leak(Box::default());
        sever_keys::export::set_sink(Box::new(move |k| {
            if let (Ok(mut v), Ok(k)) = (keys.lock(), <[u8; 32]>::try_from(k)) {
                v.push(k);
            }
        }));
        keys
    })
}

fn files(v: &SimVfs, dir: &str, out: &mut Vec<(String, Vec<u8>)>) {
    for name in v.list(dir).unwrap() {
        let path = if dir.is_empty() {
            name
        } else {
            format!("{dir}/{name}")
        };
        match v.open(&path, OpenMode::Existing) {
            Ok(f) => out.push((path, read_all(f.as_ref()).unwrap())),
            Err(_) => files(v, &path, out),
        }
    }
}

/// The two disks as one image: every file padded to 4 KiB.
fn image(data: &SimVfs, keys: &SimVfs) -> Vec<u8> {
    let mut all = Vec::new();
    files(data, "", &mut all);
    files(keys, "", &mut all);
    let mut img = Vec::new();
    for (_, b) in all {
        img.extend_from_slice(&b);
        img.resize(img.len().div_ceil(4096) * 4096, 0);
    }
    img
}

struct World {
    targets: Targets,
    image: Vec<u8>,
}

/// Six records with passages, then a holding-area cohort that flushes into a new group;
/// records 1 and 4 deleted (one by `delete_user`) and one flushed cohort member, 0 and 3 the
/// controls. The scrambled IDs come from §9.7 with the database's own `k_scramble`.
fn world() -> World {
    world_with(false)
}

/// [`world`], with a storage checkpoint before the shutdown when `checkpoint` (§15.6: the WAL
/// segments it covers are deleted, so the image holds the checkpoint and the stores only).
fn world_with(checkpoint: bool) -> World {
    let keys_seen = exported();
    let (data, keys) = (SimVfs::new(), SimVfs::new());
    let mut s = Settings::new(D);
    s.clock = Arc::new(SimClock::new(1_790_000_000_000));
    s.engine = EngineConfig {
        on_failure: FailurePolicy::Poison,
        checkpoint_every_wal_bytes: 1 << 40,
        ..EngineConfig::default()
    };
    s.log_segment_bytes = 1 << 20;
    s.wrapped_segment_bytes = 1 << 20;
    let db = open_on(Arc::new(data.clone()), Arc::new(keys.clone()), s).unwrap();
    let opts = CollectionOptions {
        spawn_target: 8,
        spawning_enabled: true,
        store_passages: true,
    };
    let cid = db.create_collection(ARTEFACT, opts).unwrap();
    let user = KeyPair::generate();
    type Rec = (String, Vec<i32>, Vec<f32>, Vec<u8>, [u8; 32]);
    let mut recs: Vec<Rec> = Vec::new();
    let insert = |recs: &mut Vec<Rec>, id: String, v: &[f32]| {
        let x = sever_quant::quantise(v, D).unwrap();
        let mut wide = [0u8; 64];
        OsRng.fill_bytes(&mut wide);
        let r_t = Scalar::from_bytes_mod_order_wide(&wide);
        let c_t = encode_point(&commit_record(db.generators(), x.as_slice(), &r_t).unwrap());
        let passage =
            format!("the passage of {id}, private text that erasure must destroy").into_bytes();
        db.insert(
            cid,
            InsertRequest {
                record_id: id.clone(),
                vector: v.to_vec(),
                credential: InsertCredential {
                    collection_id: *cid.as_bytes(),
                    c_t,
                    r_t: r_t.to_bytes(),
                    user_public_key: user.public(),
                    signature: user.sign(&insert_message(cid.as_bytes(), &c_t)),
                },
                passage: Some(passage.clone()),
            },
        )
        .unwrap();
        recs.push((
            id,
            x.as_slice().to_vec(),
            v.to_vec(),
            passage,
            r_t.to_bytes(),
        ));
    };
    for (i, v) in rows().iter().take(6).enumerate() {
        insert(&mut recs, format!("doc-{i}"), v);
    }
    // A record routed to the holding area, then a cohort of its near-copies: the holding area
    // flushes into a new group (a departure from the holding area, SB-26).
    let mut flushed = None;
    for (i, v) in all_vectors().iter().enumerate() {
        let id = format!("probe-{i}");
        insert(&mut recs, id.clone(), v);
        if db.engine.location(cid, &id).as_deref() == Some("holding") {
            for (k, w) in cohort(v, 12).iter().enumerate() {
                insert(&mut recs, format!("near-{k}"), w);
            }
            let first = recs.len() - 13; // the probe, then its cohort
            flushed = (first..recs.len())
                .find(|&j| db.engine.location(cid, &recs[j].0).as_deref() != Some("holding"));
            break;
        }
    }
    let flushed = flushed.expect("the holding area flushed a record into a new group");
    assert!(matches!(
        db.delete(cid, "doc-1").unwrap(),
        Deleted::Deleted { .. }
    ));
    db.delete_user(cid, &["doc-4"]).unwrap();
    let flushed_id = recs[flushed].0.clone();
    assert!(matches!(
        db.delete(cid, &flushed_id).unwrap(),
        Deleted::Deleted { .. }
    ));
    let live: Vec<[u8; 32]> = db
        .key_ring()
        .active_versions()
        .iter()
        .filter_map(|(d, v)| db.key_ring().group_key(d, *v).ok())
        .filter_map(|k| <[u8; 32]>::try_from(k.as_bytes()).ok())
        .collect();
    if checkpoint {
        db.engine.storage_checkpoint_now().unwrap();
    }
    drop(db);
    let secrets = read_all(keys.open("SECRETS", OpenMode::Existing).unwrap().as_ref()).unwrap();
    let k = sever_format::Secrets::parse(&secrets, sever_format::SEALER_AES_GCM_SIV)
        .unwrap()
        .k_scramble()
        .unwrap();
    let scrambler = sever_index::HmacSha512Scrambler::new(&k);
    let target = |i: usize| {
        let (id, x, v, p, r) = &recs[i];
        Target {
            sid: scrambler
                .scramble(&cid, &RecordId::new(id).unwrap())
                .as_bytes()
                .to_vec(),
            x: x.clone(),
            vector: v.clone(),
            passage: p.clone(),
            r_t: Some(*r),
        }
    };
    let retired: Vec<[u8; 32]> = keys_seen
        .lock()
        .unwrap()
        .iter()
        .filter(|k| !live.contains(k))
        .copied()
        .collect();
    World {
        targets: Targets {
            d: D,
            deleted: vec![target(1), target(4), target(flushed)],
            controls: vec![target(0), target(3)],
            retired_keys: retired,
        },
        image: image(&data, &keys),
    }
}

// oracle: A Build 3-4 §2.8 Forensics (the scanner recovers live records through the carved keys;
// after deletion nothing of the deleted record opens: INV-12, every ciphertext the current keys
// open was written after the last departure; random nonces never repeat, §13.2)
#[spec("SR-16.3-3", "SR-21-12", "SR-13.2-1")]
#[test]
fn p4_scan_recovers_live_records_and_finds_nothing_deleted() {
    let w = world();
    let r = scan_bytes(&w.image, w.targets);
    assert!(
        r.records > 20 && r.key_slots >= 2 && r.envelopes > 0,
        "{}",
        r.to_json()
    );
    assert_eq!(
        r.controls_recovered,
        vec![true, true],
        "the scanner can see: {}",
        r.to_json()
    );
    assert!(r.findings.is_empty(), "{}", r.to_json());
}

// oracle: A Build 3-4 §2.8 Forensics (positive controls: "the scanner can see") on an image taken
// after a storage checkpoint, when the WAL that wrote the live records is gone (§15.6) and the
// current keys, blocks and envelopes live in the key file, the checkpoint and the stores (§14.8)
#[spec("SR-16.3-3")]
#[test]
fn p4_scan_recovers_live_records_from_a_checkpointed_image() {
    let w = world_with(true);
    let r = scan_bytes(&w.image, w.targets);
    assert_eq!(
        r.controls_recovered,
        vec![true, true],
        "the scanner can see: {}",
        r.to_json()
    );
    assert!(r.findings.is_empty(), "{}", r.to_json());
}

// oracle: A Build 3-4 §2.8 Forensics "Positive controls. Planted secrets are found 100 % of the
// time"
#[spec("SR-16.3-3")]
#[test]
fn p4_scan_finds_every_planted_secret() {
    let w = world();
    let mut img = w.image.clone();
    let t = &w.targets.deleted[0];
    let mut plant = |bytes: Vec<u8>| {
        img.extend_from_slice(&[0x5a; 13]); // odd offsets: no alignment is assumed
        img.extend_from_slice(&bytes);
    };
    plant(t.x[..8].iter().flat_map(|c| c.to_be_bytes()).collect());
    plant(
        t.x[..4]
            .iter()
            .flat_map(|c| i64::from(*c).to_le_bytes())
            .collect(),
    );
    plant(t.vector[..8].iter().flat_map(|c| c.to_le_bytes()).collect());
    plant(t.passage[5..40].to_vec());
    plant(t.r_t.unwrap().to_vec());
    plant(w.targets.retired_keys[0].to_vec());
    let r = scan_bytes(&img, w.targets.clone());
    let kinds: BTreeSet<Kind> = r.findings.iter().map(|f| f.kind).collect();
    for k in [
        Kind::PlaintextVector,
        Kind::WidenedVector,
        Kind::FloatVector,
        Kind::PassageText,
        Kind::RecordScalar,
        Kind::RetiredKey,
    ] {
        assert!(kinds.contains(&k), "{k:?} not found: {}", r.to_json());
    }
    // Chunked scanning finds the same as one pass, across chunk boundaries.
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../target/scan-test");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join(format!("img-{}", std::process::id()));
    std::fs::write(&path, &img).unwrap();
    let chunked = scan_file(&path, w.targets, 4096).unwrap();
    std::fs::remove_file(&path).unwrap();
    assert_eq!(chunked.findings.len(), r.findings.len());
    assert_eq!(chunked.controls_recovered, r.controls_recovered);
}
