//! The evaluation's measuring harness (overview EX-7, EX-8; DB-54). [`Counted`] wraps a disk and
//! counts what the engine writes: bytes per file family, `fsync`s, and the bytes of every WAL record
//! by type. `sever-bench` runs the three builds of EX-7 and the scale run of EX-8 through it.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, PoisonError};

use sever_format::{WalParse, WalRecord};
use sever_vfs::{OpenMode, Vfs, VfsError, VfsFile};

/// What the engine wrote through one [`Counted`] disk.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Counts {
    /// Bytes written, by the first path component (`wal`, `checkpoint`, `KEYS`, …).
    pub bytes: BTreeMap<String, u64>,
    /// `fsync` and `fsync_dir` calls.
    pub fsyncs: u64,
    /// Bytes of WAL records, by record type (`Debug` name), as appended.
    pub wal_by_type: BTreeMap<String, u64>,
}

impl Counts {
    /// Every byte written.
    pub fn total_bytes(&self) -> u64 {
        self.bytes.values().sum()
    }

    /// `self − before`, field by field.
    pub fn since(&self, before: &Counts) -> Counts {
        let sub = |a: &BTreeMap<String, u64>, b: &BTreeMap<String, u64>| {
            a.iter()
                .map(|(k, v)| (k.clone(), v.saturating_sub(b.get(k).copied().unwrap_or(0))))
                .filter(|(_, v)| *v > 0)
                .collect()
        };
        Counts {
            bytes: sub(&self.bytes, &before.bytes),
            fsyncs: self.fsyncs.saturating_sub(before.fsyncs),
            wal_by_type: sub(&self.wal_by_type, &before.wal_by_type),
        }
    }

    /// As JSON.
    pub fn to_json(&self) -> serde_json::Value {
        serde_json::json!({
            "bytes": self.bytes,
            "total_bytes": self.total_bytes(),
            "fsyncs": self.fsyncs,
            "wal_by_type": self.wal_by_type,
        })
    }
}

fn family(path: &str) -> String {
    path.split('/').next().unwrap_or(path).to_owned()
}

/// A disk that counts what is written to it.
#[derive(Clone)]
pub struct Counted {
    inner: Arc<dyn Vfs>,
    counts: Arc<Mutex<Counts>>,
}

impl Counted {
    /// Wraps `inner`.
    pub fn new(inner: Arc<dyn Vfs>) -> Self {
        Self {
            inner,
            counts: Arc::default(),
        }
    }

    /// The counts so far.
    pub fn counts(&self) -> Counts {
        self.counts
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()
    }

    fn add(&self, path: &str, data: &[u8]) {
        let mut c = self.counts.lock().unwrap_or_else(PoisonError::into_inner);
        *c.bytes.entry(family(path)).or_default() += data.len() as u64;
        if family(path) == "wal" {
            // Whole records are appended (a segment header is 32 bytes and not a record).
            let mut rest = data;
            while let WalParse::Record(r, n) = WalRecord::parse_next(rest) {
                *c.wal_by_type.entry(format!("{:?}", r.ty)).or_default() += n as u64;
                rest = rest.get(n..).unwrap_or_default();
            }
        }
    }

    fn sync(&self) {
        self.counts
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .fsyncs += 1;
    }
}

struct CountedFile {
    inner: Box<dyn VfsFile>,
    path: String,
    disk: Counted,
}

impl VfsFile for CountedFile {
    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, VfsError> {
        self.inner.read_at(offset, buf)
    }
    fn write_at(&mut self, offset: u64, data: &[u8]) -> Result<(), VfsError> {
        self.disk.add(&self.path, data);
        self.inner.write_at(offset, data)
    }
    fn append(&mut self, data: &[u8]) -> Result<u64, VfsError> {
        self.disk.add(&self.path, data);
        self.inner.append(data)
    }
    fn truncate(&mut self, len: u64) -> Result<(), VfsError> {
        self.inner.truncate(len)
    }
    fn len(&self) -> Result<u64, VfsError> {
        self.inner.len()
    }
    fn fsync(&mut self) -> Result<(), VfsError> {
        self.disk.sync();
        self.inner.fsync()
    }
}

impl Vfs for Counted {
    fn open(&self, path: &str, mode: OpenMode) -> Result<Box<dyn VfsFile>, VfsError> {
        Ok(Box::new(CountedFile {
            inner: self.inner.open(path, mode)?,
            path: path.to_owned(),
            disk: self.clone(),
        }))
    }
    fn fsync_dir(&self, dir: &str) -> Result<(), VfsError> {
        self.sync();
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

/// Percentile `p` (0–100) of `xs` by nearest rank; 0 for none.
pub fn percentile(xs: &mut [u64], p: f64) -> u64 {
    if xs.is_empty() {
        return 0;
    }
    xs.sort_unstable();
    let rank = ((p / 100.0) * xs.len() as f64).ceil() as usize;
    xs.get(rank.saturating_sub(1).min(xs.len() - 1))
        .copied()
        .unwrap_or(0)
}

/// The process's peak and current resident memory in bytes (`VmHWM`, `VmRSS`).
pub fn memory() -> (u64, u64) {
    let s = std::fs::read_to_string("/proc/self/status").unwrap_or_default();
    let kb = |key: &str| {
        s.lines()
            .find(|l| l.starts_with(key))
            .and_then(|l| l.split_whitespace().nth(1))
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(0)
            * 1024
    };
    (kb("VmHWM:"), kb("VmRSS:"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use sever_vfs::SimVfs;

    #[test]
    // oracle: A nearest-rank percentile (the definition), worked by hand
    fn p4_eval_percentile_is_nearest_rank() {
        let mut xs = vec![5, 1, 4, 2, 3];
        assert_eq!(percentile(&mut xs, 50.0), 3);
        assert_eq!(percentile(&mut xs, 99.0), 5);
        assert_eq!(percentile(&mut xs, 20.0), 1);
        assert_eq!(percentile(&mut [], 50.0), 0);
    }

    #[test]
    // oracle: D the counter echoes what was written through it
    fn p4_eval_counted_disk_counts_bytes_and_fsyncs_by_family() {
        let d = Counted::new(Arc::new(SimVfs::new()));
        d.create_dir("wal").unwrap();
        let mut f = d.open("wal/x", OpenMode::CreateNew).unwrap();
        f.append(&[0; 32]).unwrap();
        f.fsync().unwrap();
        let mut g = d.open("KEYS", OpenMode::CreateNew).unwrap();
        g.write_at(0, &[1; 10]).unwrap();
        d.fsync_dir("").unwrap();
        let c = d.counts();
        assert_eq!(c.bytes.get("wal"), Some(&32));
        assert_eq!(c.bytes.get("KEYS"), Some(&10));
        assert_eq!(c.fsyncs, 2);
        assert_eq!(c.since(&Counts::default()), c);
    }
}
