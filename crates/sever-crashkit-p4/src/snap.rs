//! The main line's own crash points (DB-88), on **both** disks (Part 4: phases A and C write the
//! key file). A [`SnapVfs`] wraps one of the main line's disks; the data and key wrappers share
//! one record of every mutating operation, in order: which disk, and its index on that disk.
//! While snapshots are on, both disks are forked before each operation. A crash during the
//! `k`-th operation with no torn bytes leaves the disks exactly as the fork before it (`SimVfs`:
//! the crashing operation does not complete; only a write's leading `tear_bytes` reach the page
//! cache), so the campaign restarts that fork instead of reopening the base and running the
//! operation again up to `k`. The record maps `k` to the disk and index a replay must crash.

use std::sync::{Arc, Mutex, PoisonError};

use sever_vfs::{OpenMode, SimVfs, Vfs, VfsError, VfsFile};

use crate::world::Disks;

/// Which disk an operation touched.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Disk {
    /// The data directory.
    Data,
    /// The key directory.
    Keys,
}

/// One mutating operation of the main line.
pub struct Point {
    /// The disks before it (when snapshots were on).
    pub disks: Option<Disks>,
    /// The disk it touched.
    pub disk: Disk,
    /// Its 1-based index among that disk's operations (the `FaultPlan::crash_at_op` to crash it).
    pub local: u64,
}

struct Shared {
    data: SimVfs,
    keys: SimVfs,
    /// `(track, snapshots)`.
    on: Mutex<(bool, bool)>,
    points: Mutex<Vec<Point>>,
}

impl Shared {
    fn guard<T>(&self, which: Disk, f: impl FnOnce() -> T) -> T {
        let (track, snap) = *self.on.lock().unwrap_or_else(PoisonError::into_inner);
        if !track {
            return f();
        }
        let disk = match which {
            Disk::Data => &self.data,
            Disk::Keys => &self.keys,
        };
        let before = disk.ops_since_plan();
        let pre = snap.then(|| Disks {
            data: self.data.fork(),
            keys: self.keys.fork(),
        });
        let r = f();
        let after = disk.ops_since_plan();
        if after > before {
            self.points
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .push(Point {
                    disks: pre,
                    disk: which,
                    local: after,
                });
        }
        r
    }
}

/// One of the main line's disks, recording (and snapshotting) before each mutating operation.
#[derive(Clone)]
pub struct SnapVfs {
    shared: Arc<Shared>,
    which: Disk,
}

impl SnapVfs {
    /// Wraps `disks.data`; [`SnapVfs::keys`] gives the key disk's wrapper.
    pub fn new(disks: &Disks) -> Self {
        Self {
            shared: Arc::new(Shared {
                data: disks.data.clone(),
                keys: disks.keys.clone(),
                on: Mutex::new((false, false)),
                points: Mutex::new(Vec::new()),
            }),
            which: Disk::Data,
        }
    }

    /// The key disk's wrapper, sharing this one's record.
    pub fn keys(&self) -> Self {
        Self {
            shared: Arc::clone(&self.shared),
            which: Disk::Keys,
        }
    }

    fn disk(&self) -> &SimVfs {
        match self.which {
            Disk::Data => &self.shared.data,
            Disk::Keys => &self.shared.keys,
        }
    }

    /// Starts (or stops) recording operations, and taking snapshots; drops what was recorded.
    pub fn record(&self, track: bool, snapshots: bool) {
        *self
            .shared
            .on
            .lock()
            .unwrap_or_else(PoisonError::into_inner) = (track, snapshots);
        self.shared
            .points
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clear();
    }

    /// The operations since [`SnapVfs::record`], in order: entry `k - 1` is the `k`-th.
    pub fn take(&self) -> Vec<Point> {
        std::mem::take(
            &mut *self
                .shared
                .points
                .lock()
                .unwrap_or_else(PoisonError::into_inner),
        )
    }
}

struct SnapFile {
    inner: Box<dyn VfsFile>,
    shared: Arc<Shared>,
    which: Disk,
}

impl VfsFile for SnapFile {
    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, VfsError> {
        self.inner.read_at(offset, buf)
    }
    fn write_at(&mut self, offset: u64, data: &[u8]) -> Result<(), VfsError> {
        let inner = &mut self.inner;
        self.shared
            .guard(self.which, || inner.write_at(offset, data))
    }
    fn append(&mut self, data: &[u8]) -> Result<u64, VfsError> {
        let inner = &mut self.inner;
        self.shared.guard(self.which, || inner.append(data))
    }
    fn truncate(&mut self, len: u64) -> Result<(), VfsError> {
        let inner = &mut self.inner;
        self.shared.guard(self.which, || inner.truncate(len))
    }
    fn len(&self) -> Result<u64, VfsError> {
        self.inner.len()
    }
    fn fsync(&mut self) -> Result<(), VfsError> {
        let inner = &mut self.inner;
        self.shared.guard(self.which, || inner.fsync())
    }
}

impl Vfs for SnapVfs {
    fn open(&self, path: &str, mode: OpenMode) -> Result<Box<dyn VfsFile>, VfsError> {
        let inner = match mode {
            OpenMode::Existing => self.disk().open(path, mode)?,
            _ => self
                .shared
                .guard(self.which, || self.disk().open(path, mode))?,
        };
        Ok(Box::new(SnapFile {
            inner,
            shared: Arc::clone(&self.shared),
            which: self.which,
        }))
    }
    fn fsync_dir(&self, dir: &str) -> Result<(), VfsError> {
        self.shared.guard(self.which, || self.disk().fsync_dir(dir))
    }
    fn rename(&self, from: &str, to: &str) -> Result<(), VfsError> {
        self.shared
            .guard(self.which, || self.disk().rename(from, to))
    }
    fn unlink(&self, path: &str) -> Result<(), VfsError> {
        self.shared.guard(self.which, || self.disk().unlink(path))
    }
    fn list(&self, dir: &str) -> Result<Vec<String>, VfsError> {
        self.disk().list(dir)
    }
    fn create_dir(&self, path: &str) -> Result<(), VfsError> {
        self.shared
            .guard(self.which, || self.disk().create_dir(path))
    }
    fn remove_dir(&self, path: &str) -> Result<(), VfsError> {
        self.shared
            .guard(self.which, || self.disk().remove_dir(path))
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
