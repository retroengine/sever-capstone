//! The main line's own crash points (DB-88). A [`SnapVfs`] wraps the main line's data disk: before
//! every mutating VFS operation it forks both disks, and keeps the fork when the operation was
//! counted. A crash during the `k`-th operation with no torn bytes leaves the disks exactly as the
//! fork before it (`SimVfs`: the crashing operation does not complete; only a write's leading
//! `tear_bytes` reach the page cache), so the campaign restarts that fork instead of reopening the
//! base and running the operation again up to `k`. `campaign --compare-methods` runs both ways at
//! every such point and counts every difference.

use std::sync::{Arc, Mutex, PoisonError};

use sever_vfs::{OpenMode, SimVfs, Vfs, VfsError, VfsFile};

use crate::world::Disks;

struct Shared {
    data: SimVfs,
    keys: SimVfs,
    on: Mutex<bool>,
    snaps: Mutex<Vec<Disks>>,
}

impl Shared {
    fn guard<T>(&self, f: impl FnOnce() -> T) -> T {
        if !*self.on.lock().unwrap_or_else(PoisonError::into_inner) {
            return f();
        }
        let before = self.data.ops_since_plan();
        let pre = Disks {
            data: self.data.fork(),
            keys: self.keys.fork(),
        };
        let r = f();
        if self.data.ops_since_plan() > before {
            self.snaps
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .push(pre);
        }
        r
    }
}

/// The main line's data disk, snapshotting before each mutating operation while switched on.
#[derive(Clone)]
pub struct SnapVfs(Arc<Shared>);

impl SnapVfs {
    /// Wraps `disks.data`; each fork also copies `disks.keys`.
    pub fn new(disks: &Disks) -> Self {
        Self(Arc::new(Shared {
            data: disks.data.clone(),
            keys: disks.keys.clone(),
            on: Mutex::new(false),
            snaps: Mutex::new(Vec::new()),
        }))
    }

    /// Starts (or stops) taking snapshots; drops the ones taken so far.
    pub fn record(&self, on: bool) {
        *self.0.on.lock().unwrap_or_else(PoisonError::into_inner) = on;
        self.0
            .snaps
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clear();
    }

    /// The snapshots since [`SnapVfs::record`]: entry `k - 1` is the disks before the `k`-th
    /// mutating operation.
    pub fn take(&self) -> Vec<Disks> {
        std::mem::take(&mut *self.0.snaps.lock().unwrap_or_else(PoisonError::into_inner))
    }
}

struct SnapFile {
    inner: Box<dyn VfsFile>,
    shared: Arc<Shared>,
}

impl VfsFile for SnapFile {
    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, VfsError> {
        self.inner.read_at(offset, buf)
    }
    fn write_at(&mut self, offset: u64, data: &[u8]) -> Result<(), VfsError> {
        let inner = &mut self.inner;
        self.shared.guard(|| inner.write_at(offset, data))
    }
    fn append(&mut self, data: &[u8]) -> Result<u64, VfsError> {
        let inner = &mut self.inner;
        self.shared.guard(|| inner.append(data))
    }
    fn truncate(&mut self, len: u64) -> Result<(), VfsError> {
        let inner = &mut self.inner;
        self.shared.guard(|| inner.truncate(len))
    }
    fn len(&self) -> Result<u64, VfsError> {
        self.inner.len()
    }
    fn fsync(&mut self) -> Result<(), VfsError> {
        let inner = &mut self.inner;
        self.shared.guard(|| inner.fsync())
    }
}

impl Vfs for SnapVfs {
    fn open(&self, path: &str, mode: OpenMode) -> Result<Box<dyn VfsFile>, VfsError> {
        let inner = match mode {
            OpenMode::Existing => self.0.data.open(path, mode)?,
            _ => self.0.guard(|| self.0.data.open(path, mode))?,
        };
        Ok(Box::new(SnapFile {
            inner,
            shared: Arc::clone(&self.0),
        }))
    }
    fn fsync_dir(&self, dir: &str) -> Result<(), VfsError> {
        self.0.guard(|| self.0.data.fsync_dir(dir))
    }
    fn rename(&self, from: &str, to: &str) -> Result<(), VfsError> {
        self.0.guard(|| self.0.data.rename(from, to))
    }
    fn unlink(&self, path: &str) -> Result<(), VfsError> {
        self.0.guard(|| self.0.data.unlink(path))
    }
    fn list(&self, dir: &str) -> Result<Vec<String>, VfsError> {
        self.0.data.list(dir)
    }
    fn create_dir(&self, path: &str) -> Result<(), VfsError> {
        self.0.guard(|| self.0.data.create_dir(path))
    }
    fn remove_dir(&self, path: &str) -> Result<(), VfsError> {
        self.0.guard(|| self.0.data.remove_dir(path))
    }
}

/// Every file of `vfs` with its length, in path order (`--compare-methods`).
pub fn listing(vfs: &dyn Vfs) -> Vec<(String, u64)> {
    let mut out = Vec::new();
    let mut dirs = vec![String::new()];
    while let Some(dir) = dirs.pop() {
        let Ok(names) = vfs.list(&dir) else { continue };
        for name in names {
            let path = if dir.is_empty() {
                name
            } else {
                format!("{dir}/{name}")
            };
            match vfs.open(&path, OpenMode::Existing) {
                Ok(f) => out.push((path, f.len().unwrap_or(u64::MAX))),
                Err(_) => dirs.push(path),
            }
        }
    }
    out.sort();
    out
}
