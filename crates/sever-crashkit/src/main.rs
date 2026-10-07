//! `sever-crashkit`: run a crash campaign (overview EX-1; Build §5.7 L10).
//!
//! ```text
//! sever-crashkit generic --seed 42 --steps 2000 --out results/p2-generic-seed42.jsonl
//! sever-crashkit campaign --oracle traces/p2-oracle-nq-10k-seed42.jsonl --root . \
//!     --out results/p2-crash-nq-10k-seed42.jsonl [--seed 42] [--offset-samples 200]
//!     [--random 1000] [--double-every 50] [--step-every 1] [--limit-ops N] [--resume 1]
//! sever-crashkit replay-p1 --trace traces/p1-nq-10k-seed42.jsonl --root . --mode plain|close|crash \
//!     --out results/p2-replay-....json
//! sever-crashkit measure --trace traces/p1-nq-100k-seed42.jsonl --root . --out FILE [--work DIR]
//! ```
//! The oracle header names the artefact, the vectors and the spawn target. The results are
//! checked by `python -m sever_refmodel_durable.oracle check ORACLE RESULTS`.

use std::collections::HashMap;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use sever_crashkit::campaign::{self, Settings};
use sever_crashkit::rows::{FixtureRows, NpyRows, Rows};
use sever_crashkit::{Oracle, generic, replay};

fn args() -> (String, HashMap<String, String>) {
    let mut it = std::env::args().skip(1);
    let cmd = it.next().unwrap_or_default();
    let mut map = HashMap::new();
    while let Some(k) = it.next() {
        if let Some(name) = k.strip_prefix("--") {
            map.insert(name.to_owned(), it.next().unwrap_or_default());
        }
    }
    (cmd, map)
}

fn num(map: &HashMap<String, String>, k: &str, default: u64) -> Result<u64, String> {
    map.get(k).map_or(Ok(default), |v| {
        v.parse().map_err(|_| format!("--{k}: not a number"))
    })
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
/// written), with the same settings, or refuse.
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
    let f = std::fs::OpenOptions::new()
        .write(true)
        .open(out_path)
        .map_err(|e| e.to_string())?;
    if f.metadata().map_err(|e| e.to_string())?.len() < len {
        return Err("--resume: the results file is shorter than its saved progress".into());
    }
    f.set_len(len).map_err(|e| e.to_string())?;
    let mut f = f;
    std::io::Seek::seek(&mut f, std::io::SeekFrom::End(0)).map_err(|e| e.to_string())?;
    eprintln!(
        "resuming after operation {} ({} bytes of results kept)",
        p.done, len
    );
    Ok((f, Some(p)))
}

fn real_main() -> Result<bool, String> {
    let (cmd, a) = args();
    let out_path = PathBuf::from(a.get("out").ok_or("--out is required")?);
    if let Some(dir) = out_path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    // `campaign --resume` continues an interrupted run (see `resume_out`); everything else
    // starts a fresh results file.
    let resuming = cmd == "campaign" && a.contains_key("resume");
    let (file, resume) = if resuming {
        resume_out(&out_path, &a)?
    } else {
        (File::create(&out_path).map_err(|e| e.to_string())?, None)
    };
    let sync_file = file.try_clone().map_err(|e| e.to_string())?;
    let mut out = BufWriter::new(file);
    let ok = match cmd.as_str() {
        "generic" => {
            let s = generic::run(
                num(&a, "seed", 42)?,
                num(&a, "steps", 2_000)? as usize,
                &mut out,
            )?;
            let line = serde_json::json!({"t": "summary", "points": s.points,
                "wrong_states": s.wrong_states, "refusals": s.refusals});
            writeln!(out, "{line}").map_err(|e| e.to_string())?;
            println!("{line}");
            s.wrong_states == 0 && s.refusals == 0 && s.points > 0
        }
        "campaign" => {
            let root = PathBuf::from(a.get("root").map_or(".", String::as_str));
            let oracle = Oracle::read(Path::new(a.get("oracle").ok_or("--oracle is required")?))?;
            let h = &oracle.header;
            let field = |k: &str| {
                h.get(k)
                    .and_then(serde_json::Value::as_str)
                    .map(str::to_owned)
                    .ok_or(format!("oracle header has no {k}"))
            };
            let artefact =
                std::fs::read(root.join(field("artefact")?)).map_err(|e| e.to_string())?;
            let vectors = root.join(field("vectors")?);
            let rows: Box<dyn Rows> = if vectors.extension().is_some_and(|e| e == "json") {
                Box::new(FixtureRows::read(&vectors)?)
            } else {
                Box::new(NpyRows(
                    sever_tracekit::Npy::open(&vectors).map_err(|e| e.0)?,
                ))
            };
            let spawn_target = h
                .get("spawn_target")
                .and_then(serde_json::Value::as_u64)
                .ok_or("oracle header has no spawn_target")?;
            let s = Settings {
                checkpoint_every: num(&a, "checkpoint-every", 4 << 20)?,
                wal_segment: num(&a, "wal-segment", 4 << 20)?,
                store_segment: num(&a, "store-segment", 1 << 20)?,
                spawn_target: spawn_target as usize,
                offset_samples: num(&a, "offset-samples", 200)? as usize,
                random_points: num(&a, "random", 1_000)? as usize,
                double_every: num(&a, "double-every", 50)?,
                seed: num(&a, "seed", 42)?,
                step_every: num(&a, "step-every", 1)? as usize,
                limit_ops: a.get("limit-ops").and_then(|v| v.parse().ok()),
            };
            let progress_path = progress_path(&out_path);
            let fingerprint = fingerprint(&a);
            let mut save = |p: &campaign::Progress, w: &mut dyn Write| -> Result<(), String> {
                // Results first, durably; then the progress that points at their end.
                w.flush().map_err(|e| e.to_string())?;
                sync_file.sync_data().map_err(|e| e.to_string())?;
                let len = sync_file.metadata().map_err(|e| e.to_string())?.len();
                let doc = serde_json::json!({"progress": p.to_json(), "out_len": len,
                    "args": fingerprint});
                write_atomically(&progress_path, doc.to_string().as_bytes())
            };
            let ck = campaign::Checkpointing {
                from: resume,
                every: campaign::PROGRESS_EVERY,
                save: &mut save,
            };
            let sum = campaign::run_resumable(&oracle, rows.as_ref(), &artefact, &s, &mut out, ck)?;
            println!("{sum:?}");
            sum.failures() == 0
        }
        "replay-p1" => {
            let root = PathBuf::from(a.get("root").map_or(".", String::as_str));
            let trace = PathBuf::from(a.get("trace").ok_or("--trace is required")?);
            let mode = replay::Mode::parse(a.get("mode").map_or("plain", String::as_str))
                .ok_or("--mode plain|close|crash")?;
            let r = replay::replay(&trace, &root, mode)?;
            let line = serde_json::json!({"t": "summary", "mode": format!("{mode:?}"),
                "ops": r.ops, "checks": r.checks, "mismatches": r.mismatches, "reopens": r.reopens,
                "reopen_state_changed": r.reopen_state_changed,
                "survivors_checked": r.survivors_checked, "survivors_failed": r.survivors_failed,
                "deleted_returned": r.deleted_returned, "first": r.first, "passed": r.passed()});
            writeln!(out, "{line}").map_err(|e| e.to_string())?;
            println!("{line}");
            r.passed()
        }
        "measure" => {
            // P2-T11, a measure: the result is written whatever it is.
            let root = PathBuf::from(a.get("root").map_or(".", String::as_str));
            let trace = PathBuf::from(a.get("trace").ok_or("--trace is required")?);
            let work = PathBuf::from(a.get("work").map_or("target/measure-p2", String::as_str));
            let r = sever_crashkit::measure::run(&trace, &root, &work)?;
            writeln!(out, "{r}").map_err(|e| e.to_string())?;
            println!("{r}");
            true
        }
        _ => {
            return Err(
                "usage: sever-crashkit generic|campaign|replay-p1|measure --out FILE ...".into(),
            );
        }
    };
    out.flush().map_err(|e| e.to_string())?;
    Ok(ok)
}

fn main() -> ExitCode {
    match real_main() {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::FAILURE,
        Err(e) => {
            eprintln!("sever-crashkit: {e}");
            ExitCode::from(2)
        }
    }
}
