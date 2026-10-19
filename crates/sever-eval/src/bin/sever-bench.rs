//! `sever-bench`: overview EX-7 (the cost of provable deletion) and EX-8 (scale), DB-54.
//!
//! ```text
//! sever-bench run --arm sever|noerase|softdelete --dir DIR --work WORK --artefact FILE
//!                 [--rungs N] [--queries N] --out FILE
//! ```
//!
//! Inputs in `WORK` (written by `sever_experiments`): `stream.f32` and `stream.jsonl` (the seed's
//! stream), `rung1.json` … (each a list of cohorts), `queries.f32`. The run inserts the stream,
//! deletes the first `N` rungs (one `delete_user` per cohort), runs `N` searches, takes a storage
//! checkpoint, closes, and reopens (recovery time). Both disks are counted ([`Counted`]); only the
//! engine call is timed (the client's commitment is made before the clock starts).
//!
//! Arms: `sever` is the measured build; `noerase` is the same binary built with feature
//! `noerase` (no key rotation, no key erase); `softdelete` is Part 2's engine with a durable
//! tombstone per deleted record (marks instead of excision, no receipts).

use std::collections::{BTreeSet, HashMap};
use std::fs::File;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::Arc;
use std::time::Instant;

use rand_core::{OsRng, RngCore};
use sever_commit::InsertCredential;
use sever_crypto::{KeyPair, Scalar, commit_record, encode_point, insert_message};
use sever_engine::{CollectionOptions, InsertRequest};
use sever_eval::{Counted, Counts, memory, percentile};
use sever_types::CollectionId;
use sever_vfs::{OpenMode, PosixVfs, Vfs};

type Fail = Box<dyn std::error::Error>;
const D: usize = 384;

struct Args(HashMap<String, String>);

impl Args {
    fn get(&self, k: &str) -> Result<&str, Fail> {
        Ok(self
            .0
            .get(k)
            .map(String::as_str)
            .ok_or(format!("--{k} is required"))?)
    }
    fn num(&self, k: &str, default: usize) -> Result<usize, Fail> {
        Ok(match self.0.get(k) {
            Some(v) => v.parse()?,
            None => default,
        })
    }
}

fn f32s(path: &Path) -> Result<Vec<f32>, Fail> {
    let mut raw = Vec::new();
    File::open(path)?.read_to_end(&mut raw)?;
    Ok(raw
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes(c.try_into().unwrap_or([0; 4])))
        .collect())
}

fn ids(work: &Path) -> Result<Vec<String>, Fail> {
    let mut out = Vec::new();
    for line in BufReader::new(File::open(work.join("stream.jsonl"))?).lines() {
        let j: serde_json::Value = serde_json::from_str(&line?)?;
        out.push(j.get("id").and_then(|x| x.as_str()).ok_or("id")?.to_owned());
    }
    Ok(out)
}

fn disk_bytes(dir: &Path) -> u64 {
    let mut total = 0;
    if let Ok(rd) = std::fs::read_dir(dir) {
        for e in rd.flatten() {
            match e.metadata() {
                Ok(m) if m.is_dir() => total += disk_bytes(&e.path()),
                Ok(m) => total += m.len(),
                Err(_) => {}
            }
        }
    }
    total
}

fn us(ns: &mut [u64], p: f64) -> f64 {
    percentile(ns, p) as f64 / 1000.0
}

fn stats(ns: &mut [u64]) -> serde_json::Value {
    let n = ns.len().max(1) as f64;
    let sum: u64 = ns.iter().sum();
    serde_json::json!({
        "n": ns.len(),
        "p50_us": us(ns, 50.0),
        "p99_us": us(ns, 99.0),
        "mean_us": sum as f64 / n / 1000.0,
        "per_second": if sum > 0 { ns.len() as f64 / (sum as f64 / 1e9) } else { 0.0 },
    })
}

fn per(c: &Counts, n: usize) -> serde_json::Value {
    let n = n.max(1) as f64;
    serde_json::json!({
        "bytes_per_op": c.total_bytes() as f64 / n,
        "fsyncs_per_op": c.fsyncs as f64 / n,
        "counts": c.to_json(),
    })
}

/// One arm's engine behind a common face (one value per run, so its size does not matter).
#[allow(clippy::large_enum_variant)]
enum Arm {
    Sever(sever_db::Db, CollectionId, KeyPair),
    Soft(sever_p2::Opened, CollectionId, Counted, BTreeSet<String>),
}

struct Disks {
    data: Counted,
    keys: Counted,
}

impl Disks {
    fn total(&self) -> Counts {
        let mut c = self.data.counts();
        let k = self.keys.counts();
        for (f, b) in k.bytes {
            *c.bytes.entry(format!("keys/{f}")).or_default() += b;
        }
        c.fsyncs += k.fsyncs;
        c
    }
}

fn open_arm(arm: &str, dir: &Path, artefact: Option<&[u8]>) -> Result<(Arm, Disks), Fail> {
    let data_dir = dir.join("data");
    let key_dir = dir.join("keys");
    std::fs::create_dir_all(&data_dir)?;
    std::fs::create_dir_all(&key_dir)?;
    let opts = CollectionOptions {
        spawn_target: 200,
        spawning_enabled: true,
        store_passages: false,
    };
    match arm {
        "sever" | "noerase" => {
            if (arm == "noerase") != cfg!(feature = "noerase") {
                return Err("this binary is not built for that arm (feature noerase)".into());
            }
            let disks = Disks {
                data: Counted::new(Arc::new(PosixVfs::new(&data_dir)?)),
                keys: Counted::new(Arc::new(PosixVfs::new(&key_dir)?)),
            };
            let db = sever_db::open_on(
                Arc::new(disks.data.clone()),
                Arc::new(disks.keys.clone()),
                sever_db::Settings::new(D),
            )?;
            let cid = match artefact {
                Some(a) => db.create_collection(a, opts)?,
                None => *db.engine.collections().first().ok_or("no collection")?,
            };
            Ok((Arm::Sever(db, cid, KeyPair::generate()), disks))
        }
        "softdelete" => {
            let keys = Counted::new(Arc::new(PosixVfs::new(&key_dir)?));
            let mut o = sever_p2::OpenOptions::new(&data_dir, &key_dir);
            o.allow_unsafe_fs = true;
            let holder: Arc<std::sync::Mutex<Option<Counted>>> = Arc::default();
            let h2 = Arc::clone(&holder);
            let opened = sever_p2::open_wrapped(&o, &move |v: Arc<dyn Vfs>| {
                let c = Counted::new(v);
                if let Ok(mut h) = h2.lock() {
                    *h = Some(c.clone());
                }
                Arc::new(c) as Arc<dyn Vfs>
            })?;
            let data = holder
                .lock()
                .map_err(|_| "lock")?
                .clone()
                .ok_or("no data disk")?;
            let cid = match artefact {
                Some(a) => opened.engine.create_collection(a, opts)?,
                None => *opened.engine.collections().first().ok_or("no collection")?,
            };
            let mut tomb = BTreeSet::new();
            if let Ok(f) = data.open("tombstones", OpenMode::Existing) {
                let len = f.len()? as usize;
                let mut buf = vec![0u8; len];
                f.read_at(0, &mut buf)?;
                tomb = String::from_utf8_lossy(&buf)
                    .lines()
                    .map(str::to_owned)
                    .collect();
            }
            Ok((
                Arm::Soft(opened, cid, data.clone(), tomb),
                Disks { data, keys },
            ))
        }
        _ => Err("--arm sever|noerase|softdelete".into()),
    }
}

fn run(a: &Args) -> Result<serde_json::Value, Fail> {
    let arm = a.get("arm")?;
    let dir = PathBuf::from(a.get("dir")?);
    let work = PathBuf::from(a.get("work")?);
    let rungs = a.num("rungs", 5)?;
    let nq = a.num("queries", 1000)?;
    let artefact = std::fs::read(a.get("artefact")?)?;
    let v = f32s(&work.join("stream.f32"))?;
    let ids = ids(&work)?;
    let (mut eng, disks) = open_arm(arm, &dir, Some(&artefact))?;

    // Inserts.
    let mut ins_ns = Vec::with_capacity(ids.len());
    let before = disks.total();
    let mut refused = 0u64;
    for (i, id) in ids.iter().enumerate() {
        let x = v.get(i * D..(i + 1) * D).ok_or("row")?.to_vec();
        let ok = match &mut eng {
            Arm::Sever(db, cid, user) => {
                let q = sever_quant::quantise(&x, D)?;
                let mut wide = [0u8; 64];
                OsRng.fill_bytes(&mut wide);
                let r_t = Scalar::from_bytes_mod_order_wide(&wide);
                let c_t = encode_point(
                    &commit_record(db.generators(), q.as_slice(), &r_t).map_err(|_| "commit")?,
                );
                let req = InsertRequest {
                    record_id: id.clone(),
                    vector: x,
                    credential: InsertCredential {
                        collection_id: *cid.as_bytes(),
                        c_t,
                        r_t: r_t.to_bytes(),
                        user_public_key: user.public(),
                        signature: user.sign(&insert_message(cid.as_bytes(), &c_t)),
                    },
                    passage: None,
                };
                let t = Instant::now();
                let r = db.insert(*cid, req);
                ins_ns.push(t.elapsed().as_nanos() as u64);
                r.is_ok()
            }
            Arm::Soft(o, cid, _, _) => {
                let req = InsertRequest {
                    record_id: id.clone(),
                    vector: x,
                    credential: (),
                    passage: None,
                };
                let t = Instant::now();
                let r = o.engine.insert(*cid, req);
                ins_ns.push(t.elapsed().as_nanos() as u64);
                r.is_ok()
            }
        };
        refused += u64::from(!ok);
    }
    let ins_counts = disks.total().since(&before);
    let (peak_after_load, rss_after_load) = memory();

    // Deletions: one call per cohort.
    let mut del_ns = Vec::new();
    let mut records = 0usize;
    let mut cert_bytes = Vec::new();
    let before = disks.total();
    for j in 1..=rungs {
        let cohorts: Vec<Vec<String>> = serde_json::from_str(&std::fs::read_to_string(
            work.join(format!("rung{j}.json")),
        )?)?;
        for c in &cohorts {
            let refs: Vec<&str> = c.iter().map(String::as_str).collect();
            let t = Instant::now();
            match &mut eng {
                Arm::Sever(db, cid, _) => {
                    for o in db.delete_user(*cid, &refs)? {
                        if let sever_db::Deleted::Deleted { certificate, .. } = o {
                            records += 1;
                            cert_bytes.push(certificate.len() as u64);
                        }
                    }
                }
                Arm::Soft(_, _, data, tomb) => {
                    // A durable mark per record; the vectors stay where they are.
                    let mut f = data.open("tombstones", OpenMode::Create)?;
                    let mut line = String::new();
                    for r in &refs {
                        if tomb.insert((*r).to_owned()) {
                            records += 1;
                            line.push_str(r);
                            line.push('\n');
                        }
                    }
                    f.append(line.as_bytes())?;
                    f.fsync()?;
                }
            }
            del_ns.push(t.elapsed().as_nanos() as u64);
        }
    }
    let del_counts = disks.total().since(&before);

    // Searches.
    let queries = f32s(&work.join("queries.f32")).unwrap_or_default();
    let mut q_ns = Vec::new();
    for q in queries.chunks_exact(D).take(nq) {
        let t = Instant::now();
        match &eng {
            Arm::Sever(db, cid, _) => {
                db.engine.search(*cid, q, 10)?;
            }
            Arm::Soft(o, cid, _, tomb) => {
                // Over-fetch, then drop marked records (a soft delete filters at query time).
                let hits = o.engine.search(*cid, q, 10 + tomb.len().min(1000))?;
                let _kept = hits
                    .iter()
                    .filter(|h| !tomb.contains(&h.record_id))
                    .take(10)
                    .count();
            }
        }
        q_ns.push(t.elapsed().as_nanos() as u64);
    }
    let (peak, rss) = memory();

    // Close (storage checkpoint), then reopen: recovery time.
    match eng {
        Arm::Sever(db, _, _) => {
            db.engine.storage_checkpoint_now()?;
            drop(db);
        }
        Arm::Soft(o, _, _, _) => {
            o.engine.storage_checkpoint_now()?;
            drop(o);
        }
    }
    let disk = disk_bytes(&dir);
    let t = Instant::now();
    let (reopened, _) = open_arm(arm, &dir, None)?;
    let reopen_s = t.elapsed().as_secs_f64();
    drop(reopened);

    cert_bytes.sort_unstable();
    let n_ins = ids.len();
    Ok(serde_json::json!({
        "arm": arm,
        "records": n_ins,
        "refused_inserts": refused,
        "insert": {"latency": stats(&mut ins_ns), "per_op": per(&ins_counts, n_ins)},
        "delete": {
            "calls": del_ns.len(),
            "records": records,
            "latency_per_call": stats(&mut del_ns),
            "per_record": per(&del_counts, records),
        },
        "certificate_bytes": {
            "n": cert_bytes.len(),
            "mean": if cert_bytes.is_empty() { 0.0 } else { cert_bytes.iter().sum::<u64>() as f64 / cert_bytes.len() as f64 },
            "max": cert_bytes.last().copied().unwrap_or(0),
        },
        "search": stats(&mut q_ns),
        "memory": {"peak_after_load": peak_after_load, "rss_after_load": rss_after_load, "peak": peak, "rss": rss},
        "disk_bytes": disk,
        "reopen_seconds": reopen_s,
    }))
}

fn main() -> ExitCode {
    let mut it = std::env::args().skip(1);
    let cmd = it.next().unwrap_or_default();
    let mut m = HashMap::new();
    let mut it = it.peekable();
    while let Some(k) = it.next() {
        if let Some(name) = k.strip_prefix("--") {
            let v = match it.peek() {
                Some(n) if !n.starts_with("--") => it.next().unwrap_or_default(),
                _ => String::new(),
            };
            m.insert(name.to_owned(), v);
        }
    }
    let a = Args(m);
    let r = match cmd.as_str() {
        "run" => run(&a).and_then(|j| {
            std::fs::write(a.get("out")?, serde_json::to_string_pretty(&j)?)?;
            Ok(())
        }),
        _ => Err("usage: sever-bench run --arm sever|noerase|softdelete ...".into()),
    };
    match r {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("sever-bench: {e}");
            ExitCode::FAILURE
        }
    }
}
