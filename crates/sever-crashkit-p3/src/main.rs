//! `sever-crashkit-p3`: the Part 3 gate kit's command line (driven by
//! `python -m sever_testkit_p3.gates`).
//!
//! ```text
//! sever-crashkit-p3 replay   --trace FILE --root DIR --mode plain|close|crash --out FILE
//! sever-crashkit-p3 campaign --oracle FILE --root DIR --out FILE --seed N [Part 2's settings]
//!                            [--crash-from N] [--method snapshot|replay|compare]
//!                            [--compare-every N] [--resume 1]
//! sever-crashkit-p3 attacks  --root DIR --data nq-10k|synthetic --n N --out FILE
//! sever-crashkit-p3 measure  --root DIR --data nq-10k|synthetic --n N --out FILE
//! ```

use std::collections::HashMap;
use std::fs::File;
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

fn progress_path(out: &Path) -> PathBuf {
    let mut p = out.as_os_str().to_owned();
    p.push(".progress");
    PathBuf::from(p)
}

/// Every argument except `--resume`, sorted: a run resumes only with identical settings.
fn fingerprint(a: &HashMap<String, String>) -> String {
    let mut v: Vec<String> = a
        .iter()
        .filter(|(k, _)| k.as_str() != "resume")
        .map(|(k, v)| format!("--{k}={v}"))
        .collect();
    v.sort();
    v.join(" ")
}

/// Write to a temporary file, fsync it, rename it over `path`, fsync the directory.
fn write_atomically(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let tmp = path.with_extension("progress.tmp");
    let mut f = File::create(&tmp).map_err(|e| e.to_string())?;
    f.write_all(bytes).map_err(|e| e.to_string())?;
    f.sync_all().map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, path).map_err(|e| e.to_string())?;
    if let Some(dir) = path.parent() {
        File::open(dir)
            .and_then(|d| d.sync_all())
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Opens an interrupted campaign's results for appending: cut back to the end recorded with the
/// last saved progress (anything after it is from operations whose crash points were not all
/// written), with the same settings, or refuse (Part 2's `sever-crashkit` does the same).
fn resume_out(
    out_path: &Path,
    a: &HashMap<String, String>,
) -> Result<(File, Option<campaign::Progress>), String> {
    let text = std::fs::read_to_string(progress_path(out_path))
        .map_err(|_| "--resume: no progress file (start the run again without --resume)")?;
    let doc: serde_json::Value =
        serde_json::from_str(&text).map_err(|e| format!("progress file: {e}"))?;
    if doc.get("args").and_then(serde_json::Value::as_str) != Some(fingerprint(a).as_str()) {
        return Err("--resume: the settings differ from the interrupted run's".into());
    }
    let p = doc
        .get("progress")
        .and_then(campaign::Progress::from_json)
        .ok_or("progress file: progress")?;
    let len = doc
        .get("out_len")
        .and_then(serde_json::Value::as_u64)
        .ok_or("progress file: out_len")?;
    let mut f = std::fs::OpenOptions::new()
        .write(true)
        .open(out_path)
        .map_err(|e| e.to_string())?;
    if f.metadata().map_err(|e| e.to_string())?.len() < len {
        return Err("--resume: the results file is shorter than its saved progress".into());
    }
    f.set_len(len).map_err(|e| e.to_string())?;
    std::io::Seek::seek(&mut f, std::io::SeekFrom::End(0)).map_err(|e| e.to_string())?;
    eprintln!(
        "resuming after operation {} ({} bytes of results kept)",
        p.done, len
    );
    Ok((f, Some(p)))
}

fn real_main() -> Result<bool, String> {
    let (cmd, a) = args();
    let root = path(&a, "root")?;
    let out_path = path(&a, "out")?;
    // `campaign --resume` continues an interrupted run (see `resume_out`); everything else
    // starts a fresh results file.
    let (file, resume) = if cmd == "campaign" && a.contains_key("resume") {
        resume_out(&out_path, &a)?
    } else {
        (File::create(&out_path).map_err(|e| e.to_string())?, None)
    };
    let sync_file = file.try_clone().map_err(|e| e.to_string())?;
    let mut out = BufWriter::new(file);
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
            let which = match h.get("data").and_then(|x| x.as_str()) {
                Some("synthetic") => "synthetic",
                _ => "nq-10k",
            };
            let (art, _, _, rows) = data(&root, which, seed)?;
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
            let from = num(&a, "crash-from", 0)? as usize;
            let method =
                campaign::Method::parse(a.get("method").map_or("snapshot", String::as_str))
                    .ok_or("--method snapshot|replay|compare")?;
            let every = num(&a, "compare-every", 0)? as usize;
            let points = campaign::Points {
                crash_from: from,
                method,
                compare_every: every,
            };
            let progress_file = progress_path(&out_path);
            let args_fp = fingerprint(&a);
            let mut save = |p: &campaign::Progress, out: &mut dyn Write| -> Result<(), String> {
                // The results up to here are on disk before the progress that names them.
                out.flush().map_err(|e| e.to_string())?;
                sync_file.sync_all().map_err(|e| e.to_string())?;
                let len = sync_file.metadata().map_err(|e| e.to_string())?.len();
                let doc = serde_json::json!({"args": args_fp, "progress": p.to_json(),
                    "out_len": len});
                write_atomically(&progress_file, doc.to_string().as_bytes())
            };
            let ck = campaign::Checkpointing {
                from: resume,
                every: campaign::PROGRESS_EVERY,
                save: &mut save,
            };
            let sum = campaign::run(&oracle, rows.as_ref(), &art, &s, points, &mut out, ck)?;
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
