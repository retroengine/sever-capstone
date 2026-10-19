//! One process, two disks: when the process crashes during an operation on one disk, it stops
//! writing to the other too. A [`Linked`] disk crashes itself before any mutating operation once
//! its partner has crashed, so a replayed crash on the key disk leaves the data disk exactly where
//! the process was (the snapshot method's model), and the other way round.

use sever_vfs::{OpenMode, SimVfs, Vfs, VfsError, VfsFile};

/// `me`, crashing as soon as `other` has.
#[derive(Clone)]
pub struct Linked {
    me: SimVfs,
    other: SimVfs,
}

impl Linked {
    /// `me`, linked to `other`.
    pub fn new(me: &SimVfs, other: &SimVfs) -> Self {
        Self {
            me: me.clone(),
            other: other.clone(),
        }
    }
}

fn follow(me: &SimVfs, other: &SimVfs) {
    if other.is_crashed() && !me.is_crashed() {
        me.crash();
    }
}

struct LinkedFile {
    inner: Box<dyn VfsFile>,
    me: SimVfs,
    other: SimVfs,
}

impl VfsFile for LinkedFile {
    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, VfsError> {
        self.inner.read_at(offset, buf)
    }
    fn write_at(&mut self, offset: u64, data: &[u8]) -> Result<(), VfsError> {
        follow(&self.me, &self.other);
        self.inner.write_at(offset, data)
    }
    fn append(&mut self, data: &[u8]) -> Result<u64, VfsError> {
        follow(&self.me, &self.other);
        self.inner.append(data)
    }
    fn truncate(&mut self, len: u64) -> Result<(), VfsError> {
        follow(&self.me, &self.other);
        self.inner.truncate(len)
    }
    fn len(&self) -> Result<u64, VfsError> {
        self.inner.len()
    }
    fn fsync(&mut self) -> Result<(), VfsError> {
        follow(&self.me, &self.other);
        self.inner.fsync()
    }
}

impl Vfs for Linked {
    fn open(&self, path: &str, mode: OpenMode) -> Result<Box<dyn VfsFile>, VfsError> {
        if mode != OpenMode::Existing {
            follow(&self.me, &self.other);
        }
        Ok(Box::new(LinkedFile {
            inner: self.me.open(path, mode)?,
            me: self.me.clone(),
            other: self.other.clone(),
        }))
    }
    fn fsync_dir(&self, dir: &str) -> Result<(), VfsError> {
        follow(&self.me, &self.other);
        self.me.fsync_dir(dir)
    }
    fn rename(&self, from: &str, to: &str) -> Result<(), VfsError> {
        follow(&self.me, &self.other);
        self.me.rename(from, to)
    }
    fn unlink(&self, path: &str) -> Result<(), VfsError> {
        follow(&self.me, &self.other);
        self.me.unlink(path)
    }
    fn list(&self, dir: &str) -> Result<Vec<String>, VfsError> {
        self.me.list(dir)
    }
    fn create_dir(&self, path: &str) -> Result<(), VfsError> {
        follow(&self.me, &self.other);
        self.me.create_dir(path)
    }
    fn remove_dir(&self, path: &str) -> Result<(), VfsError> {
        follow(&self.me, &self.other);
        self.me.remove_dir(path)
    }
}
