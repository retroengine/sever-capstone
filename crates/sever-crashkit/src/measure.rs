//! P2-T11 (a measure, Build §2.5: reported exactly as found, never a gate): bytes written and
//! `fsync`s per operation, recovery time and resident memory, on real files (`PosixVfs`) with the
//! production configuration, running the operations of a Part 1 trace (`nq-100k`).
//!
//! A counting wrapper sits between the engine and the disk; nothing else differs from a real run.

#![allow(clippy::indexing_slicing)] // serde_json::Value indexing only: returns Null, never panics

use std::collections::BTreeMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;

use serde_json::{Value, json};
use sever_engine::{CollectionOptions, Engine, EngineConfig, FailurePolicy, InsertRequest};
use sever_index::NoExtension;
use sever_tracekit::Npy;
use sever_txn::PlaintextSealer;
use sever_vfs::{OpenMode, PosixVfs, Vfs, VfsError, VfsFile};

#[derive(Default)]
struct Counters {
    bytes: AtomicU64,
    fsyncs: AtomicU64,
}

impl Counters {
    fn get(&self) -> (u64, u64) {
        (
            self.bytes.load(Ordering::SeqCst),
            self.fsyncs.load(Ordering::SeqCst),
        )
    }
}

struct Counting {
    inner: Arc<dyn Vfs>,
    c: Arc<Counters>,
}

struct CountingFile {
    inner: Box<dyn VfsFile>,
    c: Arc<Counters>,
}

impl VfsFile for CountingFile {
    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, VfsError> {
        self.inner.read_at(offset, buf)
    }
    fn write_at(&mut self, offset: u64, data: &[u8]) -> Result<(), VfsError> {
        self.c.bytes.fetch_add(data.len() as u64, Ordering::SeqCst);
        self.inner.write_at(offset, data)
    }
    fn append(&mut self, data: &[u8]) -> Result<u64, VfsError> {
        self.c.bytes.fetch_add(data.len() as u64, Ordering::SeqCst);
        self.inner.append(data)
    }
    fn truncate(&mut self, len: u64) -> Result<(), VfsError> {
        self.inner.truncate(len)
    }
    fn len(&self) -> Result<u64, VfsError> {
        self.inner.len()
    }
    fn fsync(&mut self) -> Result<(), VfsError> {
        self.c.fsyncs.fetch_add(1, Ordering::SeqCst);
        self.inner.fsync()
    }
}

impl Vfs for Counting {
    fn open(&self, path: &str, mode: OpenMode) -> Result<Box<dyn VfsFile>, VfsError> {
        Ok(Box::new(CountingFile {
            inner: self.inner.open(path, mode)?,
            c: Arc::clone(&self.c),
        }))
    }
    fn fsync_dir(&self, dir: &str) -> Result<(), VfsError> {
        self.c.fsyncs.fetch_add(1, Ordering::SeqCst);
        self.inner.fsync_dir(dir)
    }
    fn rename(&self, from: &str, to: &str) -> Result<(), VfsError> {
        self.inner.rename(from, to)
    }
    fn unlink(&self, path: &str) -> Result<(), VfsError> {
        self.inner.unlink(path)
    }
    fn list(&self, dir: &str) -> Result<Vec<String>, VfsError> {
        self.inner.list(dir)
    }
    fn create_dir(&self, path: &str) -> Result<(), VfsError> {
        self.inner.create_dir(path)
    }
    fn remove_dir(&self, path: &str) -> Result<(), VfsError> {
        self.inner.remove_dir(path)
    }
}

type Db = Engine<NoExtension, PlaintextSealer>;

/// Peak and current resident memory (kB) from `/proc/self/status`.
fn memory_kb() -> Value {
    let s = std::fs::read_to_string("/proc/self/status").unwrap_or_default();
    let field = |k: &str| {
        s.lines()
            .find(|l| l.starts_with(k))
            .and_then(|l| l.split_whitespace().nth(1))
            .and_then(|v| v.parse::<u64>().ok())
    };
    json!({"VmHWM_kb": field("VmHWM:"), "VmRSS_kb": field("VmRSS:")})
}

#[derive(Default)]
struct Kind {
    ops: u64,
    bytes: u64,
    fsyncs: u64,
    seconds: f64,
}

/// Runs the trace's operations; returns the measures. `work` is emptied first and removed after.
pub fn run(trace: &Path, root: &Path, work: &Path) -> Result<Value, String> {
    let file = File::open(trace).map_err(|e| format!("{}: {e}", trace.display()))?;
    let mut lines = BufReader::new(file).lines();
    let header: Value = match lines.next() {
        Some(Ok(l)) => serde_json::from_str(&l).map_err(|e| format!("header: {e}"))?,
        _ => return Err("empty trace".into()),
    };
    let s = |k: &str| {
        header[k]
            .as_str()
            .map(str::to_owned)
            .ok_or(format!("header.{k}"))
    };
    let art = std::fs::read(root.join(s("artefact")?)).map_err(|e| format!("artefact: {e}"))?;
    let vectors = Npy::open(&root.join(s("vectors")?)).map_err(|e| e.0)?;

    let _ = std::fs::remove_dir_all(work);
    for d in ["data", "keys"] {
        std::fs::create_dir_all(work.join(d)).map_err(|e| e.to_string())?;
    }
    let c = Arc::new(Counters::default());
    let disk = |d: &str| -> Result<Arc<dyn Vfs>, String> {
        Ok(Arc::new(Counting {
            inner: Arc::new(PosixVfs::new(work.join(d)).map_err(|e| e.to_string())?),
            c: Arc::clone(&c),
        }))
    };
    let cfg = EngineConfig {
        on_failure: FailurePolicy::Poison,
        ..EngineConfig::default()
    };
    let open = || -> Result<Db, String> {
        Engine::open(
            disk("data")?,
            disk("keys")?,
            PlaintextSealer,
            NoExtension,
            Vec::new(),
            cfg.clone(),
        )
        .map_err(|e| format!("open: {e}"))
    };
    let db = open()?;
    let cid = db
        .create_collection(
            &art,
            CollectionOptions {
                spawn_target: header["spawn_target"].as_u64().unwrap_or(200) as usize,
                spawning_enabled: header["spawning"].as_bool().unwrap_or(true),
                store_passages: false,
            },
        )
        .map_err(|e| format!("create_collection: {e}"))?;

    let mut kinds: BTreeMap<&'static str, Kind> = BTreeMap::new();
    let t_all = Instant::now();
    for line in lines {
        let line = line.map_err(|e| format!("read: {e}"))?;
        let op: Value = serde_json::from_str(&line).map_err(|e| format!("line: {e}"))?;
        let before = c.get();
        let t = Instant::now();
        let kind = match op["t"].as_str() {
            Some("i") => {
                let row = op["row"].as_u64().unwrap_or(0) as usize;
                let req = InsertRequest {
                    record_id: op["id"].as_str().unwrap_or_default().to_owned(),
                    vector: vectors.row(row).map_err(|e| e.0)?,
                    credential: (),
                    passage: None,
                };
                // A rejected insert (the trace's expected errors) writes nothing; counted apart.
                if db.insert(cid, req).is_ok() {
                    "insert"
                } else {
                    "insert_rejected"
                }
            }
            Some("d") => {
                let ids: Vec<String> = op["ids"]
                    .as_array()
                    .map(|a| {
                        a.iter()
                            .filter_map(|v| v.as_str().map(str::to_owned))
                            .collect()
                    })
                    .unwrap_or_default();
                let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
                db.delete_user(cid, &refs)
                    .map_err(|e| format!("delete_user: {e}"))?;
                if ids.len() == 1 {
                    "delete_one"
                } else {
                    "delete_user_many"
                }
            }
            _ => continue, // rung lines: searches, not writes
        };
        let after = c.get();
        let k = kinds.entry(kind).or_default();
        k.ops += 1;
        k.bytes += after.0 - before.0;
        k.fsyncs += after.1 - before.1;
        k.seconds += t.elapsed().as_secs_f64();
    }
    let run_seconds = t_all.elapsed().as_secs_f64();
    let stats = db.stats(cid).map_err(|e| e.to_string())?;
    let mem_loaded = memory_kb();

    // Recovery from the WAL alone: the process "dies" (no close) and the engine reopens.
    drop(db);
    let t = Instant::now();
    let db = open()?;
    let wal_recovery = t.elapsed().as_secs_f64();
    // A storage checkpoint, then recovery from the checkpoint alone.
    let before = c.get();
    let t = Instant::now();
    db.storage_checkpoint_now().map_err(|e| e.to_string())?;
    let ck_seconds = t.elapsed().as_secs_f64();
    let after = c.get();
    drop(db);
    let t = Instant::now();
    let db = open()?;
    let ck_recovery = t.elapsed().as_secs_f64();
    drop(db);
    let mem_end = memory_kb();
    let _ = std::fs::remove_dir_all(work);

    let per = |k: &Kind| {
        let n = k.ops.max(1) as f64;
        json!({"ops": k.ops, "bytes_per_op": k.bytes as f64 / n, "fsyncs_per_op": k.fsyncs as f64 / n,
               "ms_per_op": 1000.0 * k.seconds / n})
    };
    Ok(json!({
        "measure": "P2-T11", "trace": trace.display().to_string(),
        "config": {"wal_segment_bytes": cfg.wal_segment_bytes,
                   "checkpoint_every_wal_bytes": cfg.checkpoint_every_wal_bytes},
        "per_kind": kinds.iter().map(|(k, v)| (k.to_string(), per(v))).collect::<BTreeMap<_, _>>(),
        "run_seconds": run_seconds,
        "final_stats": {"N": stats.big_n, "k": stats.k, "holding": stats.holding, "spawned": stats.spawned},
        "storage_checkpoint": {"bytes": after.0 - before.0, "fsyncs": after.1 - before.1, "seconds": ck_seconds},
        "recovery_seconds": {"wal_only": wal_recovery, "checkpoint_only": ck_recovery},
        "memory_after_load": mem_loaded, "memory_end": mem_end,
    }))
}
