//! `sever-db-p3`: Part 3's command-line tool (Build 3-4 §1.4). Every command opens the database
//! (recovery, the generator self-check and the full invariant check run first), does one thing,
//! prints one JSON line, and closes. Errors print `{"error": "<§17 kind>"}` and exit 1; no message
//! carries an ID, a vector value or a key (§17).
//!
//! `insert` plays the application backend (§3.3): it quantises, draws `r_t` from the OS, computes
//! `C_t` and signs with the account key in `--user-key` (made by `user-key`), as the SDK's
//! `prepare_insert` does (§16.2).
//!
//! ```text
//! sever-db-p3 <command> --data DIR --keys DIR [--d N] [--allow-unsafe-fs] [--config FILE] ...
//!   create        --artefact FILE [--spawn-target N] [--frozen-only] [--no-passages]
//!   user-key      --out FILE                      (a new account key, mode 0600; no database)
//!   insert        --cid HEX --id ID --vector JSON --user-key FILE [--passage TEXT]
//!   delete        --cid HEX --id ID
//!   delete-user   --cid HEX --ids JSON
//!   certificate   --lsn N
//!   anchors       [--out FILE]                    (the verifier's trust anchors, §11.3)
//!   export-log    [--out FILE]                    (the committed log for an auditor, DB-86)
//!   latest-checkpoint | search --cid HEX --vector JSON [--k N] | stats --cid HEX
//!   drop --cid HEX | checkpoint | verify
//! ```

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::ExitCode;

use rand_core::{OsRng, RngCore};
use serde_json::{Value, json};
use sever_commit::InsertCredential;
use sever_crypto::{KeyPair, Scalar, commit_record, encode_point, insert_message};
use sever_engine::{CollectionOptions, InsertRequest};
use sever_p3::{Db, Deleted, OpenOptions, cid_hex, open, parse_cid};
use sever_types::{CollectionId, Error};
use zeroize::Zeroizing;

struct Args(HashMap<String, String>);

impl Args {
    fn get(&self, k: &str) -> Result<&str, String> {
        self.0
            .get(k)
            .map(String::as_str)
            .ok_or(format!("--{k} is required"))
    }
    fn flag(&self, k: &str) -> bool {
        self.0.contains_key(k)
    }
}

fn parse() -> (String, Args) {
    let mut it = std::env::args().skip(1).peekable();
    let cmd = it.next().unwrap_or_default();
    let mut m = HashMap::new();
    while let Some(k) = it.next() {
        if let Some(name) = k.strip_prefix("--") {
            let v = match it.peek() {
                Some(next) if !next.starts_with("--") => it.next().unwrap_or_default(),
                _ => String::new(),
            };
            m.insert(name.to_owned(), v);
        }
    }
    (cmd, Args(m))
}

fn error_kind(e: &Error) -> String {
    match e {
        Error::WrongDimension => "WrongDimension".into(),
        Error::NonFinite => "NonFinite".into(),
        Error::NotNormalised => "NotNormalised".into(),
        Error::InvalidRecordId(_) => "InvalidRecordId".into(),
        Error::DuplicateRecord { same_commitment } => {
            format!("DuplicateRecord(same_commitment={same_commitment})")
        }
        Error::CommitmentMismatch => "CommitmentMismatch".into(),
        Error::BadUserSignature => "BadUserSignature".into(),
        Error::GroupCapacityExceeded => "GroupCapacityExceeded".into(),
        Error::UnknownCollection => "UnknownCollection".into(),
        Error::SeededNonceForbidden => "SeededNonceForbidden".into(),
        Error::PlatformUnsafe { .. } => "PlatformUnsafe".into(),
        Error::IntegrityViolation { .. } => "IntegrityViolation".into(),
        Error::DurabilityFailure => "DurabilityFailure".into(),
    }
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn unhex32(s: &str) -> Option<[u8; 32]> {
    let s = s.trim();
    if s.len() != 64 {
        return None;
    }
    let mut out = [0u8; 32];
    for (i, b) in out.iter_mut().enumerate() {
        *b = u8::from_str_radix(s.get(2 * i..2 * i + 2)?, 16).ok()?;
    }
    Some(out)
}

fn vector(a: &Args) -> Result<Vec<f32>, String> {
    let v: Value = serde_json::from_str(a.get("vector")?).map_err(|_| "--vector: not JSON")?;
    v.as_array()
        .ok_or("--vector: not an array")?
        .iter()
        .map(|x| {
            x.as_f64()
                .map(|f| f as f32)
                .ok_or("--vector: not a number".into())
        })
        .collect()
}

fn write_private(path: &str, text: &str) -> Result<(), String> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    let mut f = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .map_err(|e| e.to_string())?;
    f.write_all(text.as_bytes()).map_err(|e| e.to_string())?;
    f.sync_all().map_err(|e| e.to_string())
}

/// What `prepare_insert` does (§16.2): quantise, draw `r_t` from the OS, compute `C_t`, sign.
fn credential(
    db: &Db,
    user: &KeyPair,
    cid: CollectionId,
    v: &[f32],
) -> Result<InsertCredential, Error> {
    let x = sever_quant::quantise(v, db.d())?;
    let mut wide = Zeroizing::new([0u8; 64]);
    OsRng.fill_bytes(wide.as_mut());
    let r_t = Scalar::from_bytes_mod_order_wide(&wide);
    let c_t = encode_point(
        &commit_record(db.generators(), x.as_slice(), &r_t).map_err(|_| Error::WrongDimension)?,
    );
    Ok(InsertCredential {
        collection_id: *cid.as_bytes(),
        c_t,
        r_t: r_t.to_bytes(),
        user_public_key: user.public(),
        signature: user.sign(&insert_message(cid.as_bytes(), &c_t)),
    })
}

fn outcome_json(d: &Deleted) -> Value {
    match d {
        Deleted::AlreadyAbsent => json!({"outcome": "absent"}),
        Deleted::Deleted {
            database_lsn,
            certificate,
        } => {
            json!({"outcome": "deleted", "database_lsn": database_lsn, "certificate": hex(certificate)})
        }
    }
}

fn stats_json(db: &Db, cid: CollectionId) -> Result<Value, Error> {
    let s = db.engine.stats(cid)?;
    Ok(
        json!({"frozen": s.frozen, "spawned": s.spawned, "N": s.big_n, "k": s.k,
        "holding": s.holding, "checkpoint_id": s.checkpoint_id}),
    )
}

fn run(cmd: &str, a: &Args) -> Result<Result<Value, Error>, String> {
    if cmd == "user-key" {
        let mut s = Zeroizing::new([0u8; 32]);
        OsRng.fill_bytes(s.as_mut());
        let k = KeyPair::from_secret(&s);
        write_private(a.get("out")?, &hex(s.as_ref()))?;
        return Ok(Ok(json!({"user_public_key": hex(&k.public())})));
    }
    let mut o = OpenOptions::new(PathBuf::from(a.get("data")?), PathBuf::from(a.get("keys")?));
    o.d =
        a.0.get("d")
            .map_or(Ok(384), |x| x.parse().map_err(|_| "--d"))?;
    o.allow_unsafe_fs = a.flag("allow-unsafe-fs");
    o.config_file = a.0.get("config").map(PathBuf::from);
    let opened = match open(&o) {
        Ok(x) => x,
        Err(e) => return Ok(Err(e)),
    };
    let db = &opened.db;
    let cid = || parse_cid(a.get("cid")?).ok_or("--cid: 32 hex characters".to_owned());
    Ok(match cmd {
        "create" => {
            let art = std::fs::read(a.get("artefact")?).map_err(|e| e.to_string())?;
            let opts = CollectionOptions {
                spawn_target: a
                    .0
                    .get("spawn-target")
                    .map_or(Ok(200), |s| s.parse().map_err(|_| "--spawn-target"))?,
                spawning_enabled: !a.flag("frozen-only"),
                store_passages: !a.flag("no-passages"),
            };
            db.create_collection(&art, opts)
                .map(|c| json!({"cid": cid_hex(&c)}))
        }
        "insert" => {
            let secret = Zeroizing::new(
                unhex32(&std::fs::read_to_string(a.get("user-key")?).map_err(|e| e.to_string())?)
                    .ok_or("--user-key: 64 hex characters")?,
            );
            let user = KeyPair::from_secret(&secret);
            let c = cid()?;
            let v = vector(a)?;
            credential(db, &user, c, &v).and_then(|credential| {
                db.insert(
                    c,
                    InsertRequest {
                        record_id: a
                            .get("id")
                            .map_err(|_| Error::UnknownCollection)?
                            .to_owned(),
                        vector: v,
                        credential,
                        passage: a.0.get("passage").map(|p| p.clone().into_bytes()),
                    },
                )
                .map(|(lsn, p)| json!({"database_lsn": lsn, "placement": sever_p3::placement_text(&p)}))
            })
        }
        "delete" => db.delete(cid()?, a.get("id")?).map(|d| outcome_json(&d)),
        "delete-user" => {
            let ids: Vec<String> =
                serde_json::from_str(a.get("ids")?).map_err(|_| "--ids: a JSON list of strings")?;
            let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
            db.delete_user(cid()?, &refs)
                .map(|outs| json!({"outcomes": outs.iter().map(outcome_json).collect::<Vec<_>>()}))
        }
        "certificate" => {
            let lsn: u64 = a.get("lsn")?.parse().map_err(|_| "--lsn")?;
            db.certificate(lsn)
                .map(|c| json!({"database_lsn": lsn, "certificate": c.as_deref().map(hex)}))
        }
        "anchors" => {
            let text = db.anchors().to_json();
            if let Some(path) = a.0.get("out") {
                std::fs::write(path, &text).map_err(|e| e.to_string())?;
            }
            serde_json::from_str(&text)
                .map_err(|e| e.to_string())
                .map(Ok)?
        }
        "export-log" => match db.export_log() {
            Ok(text) => match a.0.get("out") {
                Some(path) => {
                    std::fs::write(path, &text).map_err(|e| e.to_string())?;
                    let v: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
                    Ok(
                        json!({"leaves": v.get("leaves").and_then(Value::as_array).map_or(0, Vec::len), "out": path}),
                    )
                }
                None => Ok(serde_json::from_str::<Value>(&text).map_err(|e| e.to_string())?),
            },
            Err(e) => Err(e),
        },
        "latest-checkpoint" => db.latest_log_checkpoint().map(|w| {
            let c = w.checkpoint;
            json!({"tree_size": c.tree_size, "root": hex(&c.root), "timestamp_ms": c.timestamp_ms,
                   "epoch": c.epoch, "cosignatures": w.cosignatures.len()})
        }),
        "search" => {
            let k =
                a.0.get("k")
                    .map_or(Ok(10), |x| x.parse().map_err(|_| "--k"))?;
            db.engine.search(cid()?, &vector(a)?, k).map(|hits| {
                json!({"hits": hits.iter().map(|h| json!([h.record_id, h.score])).collect::<Vec<_>>()})
            })
        }
        "stats" => stats_json(db, cid()?),
        "drop" => db
            .engine
            .drop_collection(cid()?)
            .map(|()| json!({"dropped": true})),
        "checkpoint" => db
            .engine
            .storage_checkpoint_now()
            .map(|()| json!({"checkpoint": true})),
        "verify" => Ok(json!({
            "ok": true,
            "collections": db.engine.collections().iter().map(cid_hex).collect::<Vec<_>>(),
            "platform_overridden": opened.platform.overridden,
        })),
        _ => return Err(format!("unknown command {cmd:?}")),
    })
}

fn main() -> ExitCode {
    let (cmd, a) = parse();
    match run(&cmd, &a) {
        Ok(Ok(v)) => {
            println!("{v}");
            ExitCode::SUCCESS
        }
        Ok(Err(e)) => {
            println!("{}", json!({"error": error_kind(&e)}));
            ExitCode::from(1)
        }
        Err(usage) => {
            eprintln!("sever-db-p3: {usage}");
            ExitCode::from(2)
        }
    }
}
