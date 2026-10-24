//! `sever-demo-p4 erase`: Part 4's demo (Build 3-4 §2.11), on simulated disks laid out as one
//! image (every file padded to 4 KiB). The forensic run on a real ext4 image is EX-2.
//!
//! 1. Positive control: before any deletion the scanner recovers a chosen record's vector from
//!    the image through the keys it carves (it can see).
//! 2. One person's records are deleted (`delete_user`); each certificate is checked (§11.3).
//! 3. Checkpoint, shut down, scan: no finding.
//! 4. The leak, made visible: built with `--features demo-sb24` (group-key rotation skipped,
//!    SB-24) the same scan decrypts two versions of the group's accumulator and prints the deleted
//!    vector, reconstructed as `S_pre − S_post`, next to the original (Build 3-4 §2.11 step 4).
//! 5. Crash between COMMIT and phase C: on restart recovery erases the old key; a new scan is
//!    clean.

use std::sync::Arc;

use rand_core::{OsRng, RngCore};
use sever_cert::Certificate;
use sever_commit::InsertCredential;
use sever_crypto::{
    DeletionContext, KeyPair, Scalar, certificate_message, commit_record, encode_point,
    insert_message, verify, verify_signature,
};
use sever_db::{Db, Deleted, Settings, open_on};
use sever_engine::{CollectionOptions, EngineConfig, FailurePolicy, InsertRequest};
use sever_index::IdScrambler;
use sever_scan::{Report, Target, Targets, scan_bytes};
use sever_txn::SimClock;
use sever_types::{CollectionId, RecordId};
use sever_vfs::{CrashPolicy, FaultPlan, OpenMode, SimVfs, Vfs, read_all};

const ARTEFACT: &[u8] = include_bytes!("../../../../golden/p1_partition_small.svp");
const VECTORS: &str = include_str!("../../../../golden/p1_fixture_vectors.json");
const D: usize = 16;

type Fail = Box<dyn std::error::Error>;

fn rows() -> Result<Vec<Vec<f32>>, Fail> {
    let doc: serde_json::Value = serde_json::from_str(VECTORS)?;
    let mut out = Vec::new();
    for h in doc.get("ref").and_then(|r| r.as_array()).ok_or("fixture")? {
        let h = h.as_str().ok_or("fixture")?;
        let mut v = Vec::new();
        for i in 0..h.len() / 8 {
            let mut b = [0u8; 4];
            for (j, x) in b.iter_mut().enumerate() {
                *x = u8::from_str_radix(h.get(8 * i + 2 * j..8 * i + 2 * j + 2).ok_or("hex")?, 16)?;
            }
            v.push(f32::from_le_bytes(b));
        }
        out.push(v);
    }
    Ok(out)
}

struct Disks {
    data: SimVfs,
    keys: SimVfs,
}

impl Disks {
    fn open(&self) -> Result<Db, Fail> {
        let mut s = Settings::new(D);
        s.clock = Arc::new(SimClock::new(1_790_000_000_000));
        s.engine = EngineConfig {
            on_failure: FailurePolicy::Poison,
            ..EngineConfig::default()
        };
        s.log_segment_bytes = 1 << 20;
        s.wrapped_segment_bytes = 1 << 20;
        Ok(open_on(
            Arc::new(self.data.clone()),
            Arc::new(self.keys.clone()),
            s,
        )?)
    }

    fn image(&self) -> Result<Vec<u8>, Fail> {
        fn walk(v: &SimVfs, dir: &str, img: &mut Vec<u8>) -> Result<(), Fail> {
            for name in v.list(dir)? {
                let path = if dir.is_empty() {
                    name
                } else {
                    format!("{dir}/{name}")
                };
                match v.open(&path, OpenMode::Existing) {
                    Ok(f) => {
                        img.extend_from_slice(&read_all(f.as_ref())?);
                        img.resize(img.len().div_ceil(4096) * 4096, 0);
                    }
                    Err(_) => walk(v, &path, img)?,
                }
            }
            Ok(())
        }
        let mut img = Vec::new();
        walk(&self.data, "", &mut img)?;
        walk(&self.keys, "", &mut img)?;
        Ok(img)
    }
}

struct Record {
    id: String,
    x: Vec<i32>,
    v: Vec<f32>,
    passage: Vec<u8>,
    r_t: [u8; 32],
}

fn insert(db: &Db, cid: CollectionId, user: &KeyPair, id: &str, v: &[f32]) -> Result<Record, Fail> {
    let x = sever_quant::quantise(v, D)?;
    let mut wide = [0u8; 64];
    OsRng.fill_bytes(&mut wide);
    let r_t = Scalar::from_bytes_mod_order_wide(&wide);
    let c_t = encode_point(
        &commit_record(db.generators(), x.as_slice(), &r_t).map_err(|_| "commitment")?,
    );
    let passage = format!("{id}: a private note that must not survive its deletion").into_bytes();
    db.insert(
        cid,
        InsertRequest {
            record_id: id.to_owned(),
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
    )?;
    Ok(Record {
        id: id.to_owned(),
        x: x.as_slice().to_vec(),
        v: v.to_vec(),
        passage,
        r_t: r_t.to_bytes(),
    })
}

/// §11.3 steps 1 and 7: the operator's signature and the deletion proof.
fn check(db: &Db, bytes: &[u8]) -> Result<Certificate, Fail> {
    let a = db.anchors();
    let c = Certificate::parse(bytes, a.d).map_err(|_| "certificate does not parse")?;
    let key = a
        .operator
        .get(c.key_period)
        .ok_or("no operator key for the epoch")?;
    let signed = bytes.get(..bytes.len().saturating_sub(69)).ok_or("short")?;
    verify_signature(key, &certificate_message(signed), &c.operator_signature)
        .map_err(|_| "operator signature")?;
    if let Some(g) = &c.group {
        let ctx = DeletionContext {
            c_s_pre: g.c_s_pre,
            c_t: c.c_t,
            scrambled_id: c.scrambled_id,
            database_lsn: c.database_lsn,
            collection_id: c.collection_id,
        };
        verify(db.generators(), &g.c_s_post, &ctx, &g.proof).map_err(|_| "deletion proof")?;
    }
    Ok(c)
}

fn target(disks: &Disks, cid: CollectionId, r: &Record) -> Result<Target, Fail> {
    let secrets = read_all(disks.keys.open("SECRETS", OpenMode::Existing)?.as_ref())?;
    let k =
        sever_format::Secrets::parse(&secrets, sever_format::SEALER_AES_GCM_SIV)?.k_scramble()?;
    let sid = sever_index::HmacSha512Scrambler::new(&k).scramble(&cid, &RecordId::new(&r.id)?);
    Ok(Target {
        sid: sid.as_bytes().to_vec(),
        x: r.x.clone(),
        vector: r.v.clone(),
        passage: r.passage.clone(),
        r_t: Some(r.r_t),
    })
}

fn rec(recs: &[Record], i: usize) -> Result<&Record, Fail> {
    Ok(recs.get(i).ok_or("record")?)
}

fn show(r: &Report) -> String {
    let c = r.counts();
    if c.is_empty() {
        "0 findings".into()
    } else {
        format!(
            "{} findings: {}",
            r.findings.len(),
            c.iter()
                .map(|(k, n)| format!("{n} {k}"))
                .collect::<Vec<_>>()
                .join(", ")
        )
    }
}

fn main() -> Result<(), Fail> {
    let sabotaged = cfg!(feature = "demo-sb24");
    println!(
        "SEVER-DB Part 4: the erasure{}\n",
        if sabotaged {
            " (SB-24 build: group-key rotation skipped)"
        } else {
            ""
        }
    );
    let disks = Disks {
        data: SimVfs::new(),
        keys: SimVfs::new(),
    };
    let db = disks.open()?;
    let cid = db.create_collection(
        ARTEFACT,
        CollectionOptions {
            spawn_target: 8,
            spawning_enabled: true,
            store_passages: true,
        },
    )?;
    let alice = KeyPair::generate();
    let mut recs = Vec::new();
    for (i, v) in rows()?.iter().take(6).enumerate() {
        recs.push(insert(&db, cid, &alice, &format!("note-{i}"), v)?);
    }
    let person = ["note-1", "note-4"];
    println!("Inserted 6 records (encrypted, d = {D}); the person to forget owns {person:?}.");

    // 1. Positive control.
    let before = Targets {
        d: D,
        deleted: vec![],
        controls: vec![target(&disks, cid, rec(&recs, 1)?)?],
        retired_keys: vec![],
    };
    db.engine.storage_checkpoint_now()?;
    let r = scan_bytes(&disks.image()?, before);
    println!(
        "\n1. Positive control: the scanner {} note-1's vector on the image ({} records, {} key slots carved).",
        if r.controls_recovered == [true] {
            "RECOVERS"
        } else {
            "does NOT recover"
        },
        r.records,
        r.key_slots
    );

    // 2. Delete the person.
    let out = db.delete_user(cid, &person)?;
    println!("\n2. delete_user {person:?}:");
    for o in out {
        if let Deleted::Deleted {
            database_lsn,
            certificate,
        } = o
        {
            let c = check(&db, &certificate)?;
            println!(
                "   certificate {} bytes, database_lsn {database_lsn}: operator signature and deletion proof verify (C_S {}).",
                certificate.len(),
                if c.group.is_some() {
                    "pre → post"
                } else {
                    "of the holding area"
                }
            );
        }
    }

    // 3. Checkpoint, shut down, scan.
    db.engine.storage_checkpoint_now()?;
    drop(db);
    let after = Targets {
        d: D,
        deleted: vec![
            target(&disks, cid, rec(&recs, 1)?)?,
            target(&disks, cid, rec(&recs, 4)?)?,
        ],
        controls: vec![target(&disks, cid, rec(&recs, 0)?)?],
        retired_keys: vec![],
    };
    let r = scan_bytes(&disks.image()?, after.clone());
    println!(
        "\n3. Checkpoint, shut down, scan the image for the deleted records: {} (control note-0 {}).",
        show(&r),
        if r.controls_recovered == [true] {
            "still recovered"
        } else {
            "NOT recovered"
        }
    );
    let names = ["note-1", "note-4"];
    if sabotaged {
        println!(
            "\n4. The leak, made visible: with group-key rotation skipped the live key still opens the\n   accumulator from before the deletion. S_pre − S_post is the deleted vector (§5):"
        );
        for x in &r.reconstructions {
            let (name, orig) = match (names.get(x.target), after.deleted.get(x.target)) {
                (Some(n), Some(t)) => (*n, &t.x),
                _ => continue,
            };
            let same =
                orig.len() == x.x.len() && orig.iter().zip(&x.x).all(|(a, b)| i64::from(*a) == *b);
            println!(
                "   {name}  S_pre − S_post (n {} → {}) = {:?}",
                x.n_pre, x.n_post, x.x
            );
            println!(
                "   {name}  original x̃                  = {orig:?}  {}",
                if same { "IDENTICAL" } else { "differs" }
            );
        }
        if r.reconstructions.is_empty() {
            println!("   (no two versions of a group's accumulator opened: nothing rebuilt)");
        }
    } else {
        println!(
            "\n4. The leak, made visible: here no two versions of any group's accumulator open, so the\n   scan rebuilds {} deleted vectors. Run `scripts/demo-p4.sh` (it builds the SB-24 variant,\n   group-key rotation skipped) to see S_pre − S_post printed next to the original.",
            r.reconstructions.len()
        );
    }

    // 5. A crash between COMMIT and phase C.
    let db = disks.open()?;
    let dry = Disks {
        data: disks.data.fork(),
        keys: disks.keys.fork(),
    };
    let ddb = dry.open()?;
    dry.keys.set_faults(FaultPlan::default());
    ddb.delete(cid, "note-2")?;
    let keys_ops = dry.keys.ops_since_plan();
    drop(ddb);
    drop(db);
    let db = disks.open()?;
    // The deletion's last key-disk operations are phase C's overwrite of the old slot and its
    // fsync: crash at the overwrite.
    disks.keys.set_faults(FaultPlan {
        crash_at_op: Some(keys_ops.saturating_sub(1)),
        ..FaultPlan::default()
    });
    let acked = db.delete(cid, "note-2").is_ok();
    drop(db);
    disks.data.restart(CrashPolicy::KeepAll);
    disks.keys.restart(CrashPolicy::KeepAll);
    let db = disks.open()?;
    let n = db.engine.stats(cid)?.big_n;
    db.engine.storage_checkpoint_now()?;
    drop(db);
    let mut crashed = after;
    crashed.deleted.push(target(&disks, cid, rec(&recs, 2)?)?);
    let r = scan_bytes(&disks.image()?, crashed);
    println!(
        "\n5. Crash during phase C (after COMMIT, acknowledged: {acked}); on restart {} records remain and\n   recovery erased the old key. New scan: {}.",
        n,
        show(&r)
    );
    Ok(())
}
