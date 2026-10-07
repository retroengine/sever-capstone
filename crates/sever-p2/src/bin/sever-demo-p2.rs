//! `sever-demo-p2`: Part 2's demo (Build §5.9).
//!
//! ```text
//! sever-demo-p2 durable --data nq-10k|synthetic [--seed 42] [--root .] [--work DIR] [--out FILE]
//! ```
//! (`child-delete-user` is the demo's own child process for the `SIGKILL` step.)

// `serde_json::Value` indexing returns `Null` for a missing key and never panics; it is the only
// indexing here.
#![allow(clippy::indexing_slicing)]

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::ExitCode;

use sever_p2::demo;

fn main() -> ExitCode {
    let mut it = std::env::args().skip(1);
    let cmd = it.next().unwrap_or_default();
    let mut a: HashMap<String, String> = HashMap::new();
    while let Some(k) = it.next() {
        if let Some(n) = k.strip_prefix("--") {
            a.insert(n.to_owned(), it.next().unwrap_or_default());
        }
    }
    let get = |k: &str, d: &str| a.get(k).cloned().unwrap_or_else(|| d.to_owned());
    let r = match cmd.as_str() {
        "durable" => {
            let root = PathBuf::from(get("root", "."));
            let data = get("data", "nq-10k");
            let seed: u64 = get("seed", "42").parse().unwrap_or(42);
            let work = PathBuf::from(get("work", "artefacts/demo"));
            let out = a.get("out").map_or_else(
                || work.join(format!("durable-{data}-seed{seed}.json")),
                PathBuf::from,
            );
            demo::durable(&root, &data, seed, &work).and_then(|report| {
                std::fs::create_dir_all(&work).map_err(|e| demo::DemoError(e.to_string()))?;
                let ok =
                    report["all_or_nothing"] == true && report["commit_point_respected"] == true;
                std::fs::write(&out, format!("{report:#}\n"))
                    .map_err(|e| demo::DemoError(e.to_string()))?;
                println!("report: {}", out.display());
                if ok {
                    Ok(())
                } else {
                    Err(demo::DemoError("the demo found a partial deletion".into()))
                }
            })
        }
        "child-delete-user" => {
            let ids: Vec<String> = serde_json::from_str(&get("ids", "[]")).unwrap_or_default();
            match sever_p2::parse_cid(&get("cid", "")) {
                Some(cid) => demo::child_delete_user(
                    PathBuf::from(get("data", "")),
                    PathBuf::from(get("keys", "")),
                    cid,
                    ids,
                    &get("pause-at", "wal"),
                ),
                None => Err(demo::DemoError("--cid".into())),
            }
        }
        _ => Err(demo::DemoError(
            "usage: sever-demo-p2 durable --data nq-10k|synthetic [--seed S]".into(),
        )),
    };
    match r {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("sever-demo-p2: {}", e.0);
            ExitCode::FAILURE
        }
    }
}
