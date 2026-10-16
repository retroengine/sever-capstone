//! `sever-crashkit-p3`: the Part 3 gate kit's command line (driven by
//! `python -m sever_testkit_p3.gates`).
//!
//! ```text
//! sever-crashkit-p3 replay   --trace FILE --root DIR --mode plain|close|crash --out FILE
//! sever-crashkit-p3 campaign --oracle FILE --root DIR --out FILE --seed N [Part 2's settings]
//! sever-crashkit-p3 attacks  --root DIR --data nq-10k|synthetic --n N --out FILE
//! sever-crashkit-p3 measure  --root DIR --data nq-10k|synthetic --n N --out FILE
//! ```

use std::collections::HashMap;
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use sever_crashkit::campaign::Settings;
use sever_crashkit::oracle::Oracle;
use sever_crashkit::rows::{FixtureRows, NpyRows, Rows};
use sever_crashkit_p3::{attacks, campaign, measure, replay};
use sever_engine::EngineConfig;
use sever_tracekit::Npy;

fn args() -> (String, HashMap<String, String>) {
    let mut it = std::env::args().skip(1);
    let cmd = it.next().unwrap_or_default();
    let mut m = HashMap::new();
    while let Some(k) = it.next() {
        if let Some(name) = k.strip_prefix("--") {
            m.insert(name.to_owned(), it.next().unwrap_or_default());
        }
    }
    (cmd, m)
}

fn num(m: &HashMap<String, String>, k: &str, default: u64) -> Result<u64, String> {
    m.get(k)
        .map_or(Ok(default), |v| v.parse().map_err(|_| format!("--{k}")))
}

fn path(m: &HashMap<String, String>, k: &str) -> Result<PathBuf, String> {
    m.get(k)
        .map(PathBuf::from)
        .ok_or(format!("--{k} is required"))
}

/// The artefact, its dimension, spawn target and rows.
type Data = (Vec<u8>, usize, usize, Box<dyn Rows>);

/// The artefact, its dimension, spawn target and rows for `--data`.
fn data(root: &Path, which: &str, seed: u64) -> Result<Data, String> {
    if which == "synthetic" {
        let art =
            std::fs::read(root.join("golden/p1_partition_small.svp")).map_err(|e| e.to_string())?;
        let rows = FixtureRows::read(&root.join("golden/p1_fixture_vectors.json"))?;
        return Ok((art, 16, 8, Box::new(rows)));
    }
    let art = std::fs::read(root.join(format!("artefacts/partition-seed{seed}.svp")))
        .map_err(|e| e.to_string())?;
    let npy = Npy::open(&root.join("datasets/processed/nq_1m/embeddings.npy")).map_err(|e| e.0)?;
    Ok((art, 384, 200, Box::new(NpyRows(npy))))
}

fn real_main() -> Result<bool, String> {
    let (cmd, a) = args();
    let root = path(&a, "root")?;
    let out_path = path(&a, "out")?;
    let mut out = BufWriter::new(std::fs::File::create(&out_path).map_err(|e| e.to_string())?);
    let seed = num(&a, "seed", 42)?;
    let ok = match cmd.as_str() {
        "replay" => {
            let mode = a
                .get("mode")
                .and_then(|m| replay::Mode::parse(m))
                .ok_or("--mode plain|close|crash")?;
            let rep = replay::replay(&path(&a, "trace")?, &root, mode)?;
            writeln!(out, "{}", rep.to_json()).map_err(|e| e.to_string())?;
            rep.passed()
        }
        "campaign" => {
            let oracle = Oracle::read(&path(&a, "oracle")?)?;
            let h = &oracle.header;
            let (art, d, rows): (Vec<u8>, usize, Box<dyn Rows>) =
                match h.get("data").and_then(|x| x.as_str()) {
                    Some("synthetic") => {
                        let (art, d, _, r) = data(&root, "synthetic", seed)?;
                        (art, d, r)
                    }
                    _ => {
                        let (art, d, _, r) = data(&root, "nq-10k", seed)?;
                        (art, d, r)
                    }
                };
            let s = Settings {
                checkpoint_every: num(&a, "checkpoint-every", 4 << 20)?,
                wal_segment: num(&a, "wal-segment", 4 << 20)?,
                store_segment: num(&a, "store-segment", 1 << 20)?,
                spawn_target: num(
                    &a,
                    "spawn-target",
                    h.get("spawn_target")
                        .and_then(|x| x.as_u64())
                        .unwrap_or(200),
                )? as usize,
                offset_samples: num(&a, "offset-samples", 200)? as usize,
                random_points: num(&a, "random", 1_000)? as usize,
                double_every: num(&a, "double-every", 50)?,
                seed,
                step_every: num(&a, "step-every", 1)? as usize,
                limit_ops: a.get("limit-ops").and_then(|x| x.parse().ok()),
            };
            let sum = campaign::run(&oracle, rows.as_ref(), &art, d, &s, &mut out)?;
            sum.failures() == 0 && sum.skipped == 0
        }
        "attacks" | "measure" => {
            let which = a.get("data").map_or("nq-10k", String::as_str);
            let (art, d, spawn, rows) = data(&root, which, seed)?;
            let world = sever_crashkit_p3::world::World::new(d, EngineConfig::default(), 64 << 20)?;
            let n = num(&a, "n", 1_000)? as usize;
            if cmd == "attacks" {
                let (honest, attacked) =
                    attacks::write(&world, rows.as_ref(), &art, spawn, n, &mut out)?;
                eprintln!("{honest} honest certificates, {attacked} attacks");
                honest as usize == n
            } else {
                let v = measure::run(&world, rows.as_ref(), &art, n, 20)?;
                writeln!(out, "{v}").map_err(|e| e.to_string())?;
                true
            }
        }
        _ => return Err(format!("unknown command {cmd:?}")),
    };
    out.flush().map_err(|e| e.to_string())?;
    Ok(ok)
}

fn main() -> ExitCode {
    match real_main() {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::from(1),
        Err(e) => {
            eprintln!("sever-crashkit-p3: {e}");
            ExitCode::from(2)
        }
    }
}
