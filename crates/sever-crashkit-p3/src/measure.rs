//! P3-T13 (a measure, recorded as found; Build 3-4 §1.9): proof time, verification time (the
//! engine's §9.5 verifier) and certificate size, at the database's dimension.

use std::time::Instant;

use rand_core::{OsRng, RngCore};
use serde_json::{Value, json};
use sever_crypto::{
    DeletionContext, Scalar, StrictProofRng, commit_group, encode_point, prove, verify,
};
use sever_p3::Deleted;

use crate::world::{Disks, World};

fn median(mut v: Vec<f64>) -> f64 {
    v.sort_by(f64::total_cmp);
    v.get(v.len() / 2).copied().unwrap_or(f64::NAN)
}

/// `n` proofs of random group states: prove and verify times (ms, median and max), then
/// `deletions` real deletions through the engine: their certificate sizes.
pub fn run(
    world: &World,
    rows: &dyn sever_crashkit::rows::Rows,
    artefact: &[u8],
    n: usize,
    deletions: usize,
) -> Result<Value, String> {
    let g = &world.gens;
    let d = g.d();
    let (mut tp, mut tv) = (Vec::new(), Vec::new());
    for _ in 0..n {
        let s: Vec<i64> = (0..d).map(|_| (OsRng.next_u64() >> 24) as i64).collect();
        let mut w = [0u8; 64];
        OsRng.fill_bytes(&mut w);
        let r = Scalar::from_bytes_mod_order_wide(&w);
        let ctx = DeletionContext {
            c_s_pre: [1; 32],
            c_t: [2; 32],
            scrambled_id: [3; 64],
            database_lsn: 7,
            collection_id: [4; 16],
        };
        let c = encode_point(&commit_group(g, &s, &r).map_err(|e| format!("{e:?}"))?);
        let t0 = Instant::now();
        let p = prove(g, &s, &r, &ctx, &mut StrictProofRng::new()).map_err(|e| format!("{e:?}"))?;
        tp.push(t0.elapsed().as_secs_f64() * 1e3);
        let bytes = p.to_bytes();
        let t1 = Instant::now();
        verify(g, &c, &ctx, &bytes).map_err(|e| format!("{e:?}"))?;
        tv.push(t1.elapsed().as_secs_f64() * 1e3);
    }
    let disks = Disks::new();
    let db = world.open(&disks).map_err(|e| e.to_string())?;
    let cid = db
        .create_collection(
            artefact,
            sever_engine::CollectionOptions {
                spawn_target: 200,
                spawning_enabled: true,
                store_passages: false,
            },
        )
        .map_err(|e| e.to_string())?;
    let mut ids = Vec::new();
    for i in 0..deletions * 4 {
        let v = rows.row(i)?;
        let cred = world.credential(cid, &v).map_err(|e| e.to_string())?;
        let id = format!("m{i}");
        if db
            .insert(
                cid,
                sever_engine::InsertRequest {
                    record_id: id.clone(),
                    vector: v,
                    credential: cred.credential(),
                    passage: None,
                },
            )
            .is_ok()
        {
            ids.push(id);
        }
    }
    let (mut sizes, mut tdel) = (Vec::new(), Vec::new());
    for id in ids.iter().step_by(4).take(deletions) {
        let t0 = Instant::now();
        if let Ok(Deleted::Deleted { certificate, .. }) = db.delete(cid, id) {
            tdel.push(t0.elapsed().as_secs_f64() * 1e3);
            sizes.push(certificate.len());
        }
    }
    let max = |v: &[f64]| v.iter().copied().fold(f64::NAN, f64::max);
    Ok(json!({
        "d": d, "proofs": n,
        "prove_ms": {"median": median(tp.clone()), "max": max(&tp)},
        "verify_ms": {"median": median(tv.clone()), "max": max(&tv)},
        "deletions": sizes.len(),
        "delete_ms_simvfs": {"median": median(tdel.clone()), "max": max(&tdel)},
        "certificate_bytes": {"min": sizes.iter().min(), "max": sizes.iter().max(),
            "predicted_group_d384": 14_093},
    }))
}
