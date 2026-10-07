//! `sever-db-p2`: Part 2's command-line tool (Build §5.5). Every command opens the database
//! (recovery and the full invariant check run first), does one thing, prints one JSON line, and
//! closes. Errors print `{"error": "<§17 kind>"}` and exit 1; no message carries an ID, a vector
//! value or a key (§17).
//!
//! ```text
//! sever-db-p2 <command> --data DIR --keys DIR [--allow-unsafe-fs] [--config FILE] ...
//!   create      --artefact FILE [--spawn-target N] [--frozen-only] [--no-passages]
//!   load        --cid HEX --slice nq-10k|nq-100k|synthetic [--root DIR] [--seed S] [--limit N]
//!   insert      --cid HEX --id ID --vector JSON [--passage TEXT]
//!   delete      --cid HEX --id ID
//!   delete-user --cid HEX --ids JSON
//!   search      --cid HEX --vector JSON [--k N]
//!   stats       --cid HEX
//!   drop        --cid HEX
//!   checkpoint | verify
//! ```

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::ExitCode;

use serde_json::{Value, json};
use sever_engine::{CollectionOptions, DeleteOutcome, InsertRequest};
use sever_p2::{OpenOptions, P2Engine, cid_hex, open, parse_cid};
use sever_types::Error;

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

fn stats_json(db: &P2Engine, cid: sever_types::CollectionId) -> Result<Value, Error> {
    let s = db.stats(cid)?;
    Ok(
        json!({"frozen": s.frozen, "spawned": s.spawned, "N": s.big_n, "k": s.k,
        "holding": s.holding, "checkpoint_id": s.checkpoint_id}),
    )
}

fn run(cmd: &str, a: &Args) -> Result<Result<Value, Error>, String> {
    let mut o = OpenOptions::new(PathBuf::from(a.get("data")?), PathBuf::from(a.get("keys")?));
    o.allow_unsafe_fs = a.flag("allow-unsafe-fs");
    o.config_file = a.0.get("config").map(PathBuf::from);
    let opened = match open(&o) {
        Ok(x) => x,
        Err(e) => return Ok(Err(e)),
    };
    let db = &opened.engine;
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
        "load" => {
            let root = PathBuf::from(a.0.get("root").map_or(".", String::as_str));
            let slice = a.get("slice")?;
            let ds = match slice {
                "synthetic" => sever_p1::data::load_synthetic(&root),
                s => sever_p1::data::load_nq(
                    &root,
                    s,
                    a.0.get("seed").map_or(Ok(42), |x| x.parse().map_err(|_| "--seed"))?,
                ),
            }
            .map_err(|e| e.0)?;
            let limit = a
                .0
                .get("limit")
                .map_or(Ok(ds.ids.len()), |x| x.parse().map_err(|_| "--limit"))?;
            let c = cid()?;
            let mut r = Ok(());
            for (i, id) in ds.ids.iter().enumerate().take(limit) {
                let v = ds.vector(i).ok_or("vector")?.to_vec();
                r = db
                    .insert(
                        c,
                        InsertRequest {
                            record_id: id.clone(),
                            vector: v,
                            credential: (),
                            passage: None,
                        },
                    )
                    .map(|_| ());
                if r.is_err() {
                    break;
                }
            }
            r.and_then(|()| stats_json(db, c))
        }
        "insert" => db
            .insert(
                cid()?,
                InsertRequest {
                    record_id: a.get("id")?.to_owned(),
                    vector: vector(a)?,
                    credential: (),
                    passage: a.0.get("passage").map(|p| p.clone().into_bytes()),
                },
            )
            .map(|r| json!({"placement": format!("{:?}", r.placement)})),
        "delete" => db.delete(cid()?, a.get("id")?).map(|o| {
            json!({"outcome": if o == DeleteOutcome::AlreadyAbsent { "absent" } else { "deleted" }})
        }),
        "delete-user" => {
            let ids: Vec<String> =
                serde_json::from_str(a.get("ids")?).map_err(|_| "--ids: a JSON list of strings")?;
            let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
            db.delete_user(cid()?, &refs).map(|outs| {
                json!({"outcomes": outs.iter().map(|o| if *o == DeleteOutcome::AlreadyAbsent {
                    "absent" } else { "deleted" }).collect::<Vec<_>>()})
            })
        }
        "search" => {
            let k = a
                .0
                .get("k")
                .map_or(Ok(10), |x| x.parse().map_err(|_| "--k"))?;
            db.search(cid()?, &vector(a)?, k).map(|hits| {
                json!({"hits": hits.iter().map(|h| json!([h.record_id, h.score])).collect::<Vec<_>>()})
            })
        }
        "stats" => stats_json(db, cid()?),
        "drop" => db.drop_collection(cid()?).map(|()| json!({"dropped": true})),
        "checkpoint" => db.storage_checkpoint_now().map(|()| json!({"checkpoint": true})),
        "verify" => Ok(json!({
            "ok": true,
            "collections": db.collections().iter().map(cid_hex).collect::<Vec<_>>(),
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
            eprintln!("sever-db-p2: {usage}");
            ExitCode::from(2)
        }
    }
}
