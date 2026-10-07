//! Fault injection for the end-to-end tests (E2E-2.5, Build §5.7 L9): a `Vfs` whose n-th `fsync`
//! (file or directory) fails. Compiled only with the test-only `demo` feature; the CLI turns it on
//! with `SEVER_TEST_FAIL_FSYNC_AT=n`. With `FailurePolicy::Abort` the process then aborts (§12.7).

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use sever_vfs::{OpenMode, Vfs, VfsError, VfsFile, VfsOp};

/// Wraps a `Vfs`; the `fail_at`-th sync (counting from 1) fails.
pub struct FailingVfs {
    inner: Arc<dyn Vfs>,
    count: Arc<AtomicU64>,
    fail_at: u64,
}

impl FailingVfs {
    /// Wraps `inner`.
    pub fn new(inner: Arc<dyn Vfs>, fail_at: u64) -> Self {
        Self {
            inner,
            count: Arc::new(AtomicU64::new(0)),
            fail_at,
        }
    }
}

fn fail(count: &AtomicU64, at: u64, op: VfsOp) -> Result<(), VfsError> {
    if count.fetch_add(1, Ordering::SeqCst) + 1 == at {
        Err(VfsError::Io {
            op,
            kind: std::io::ErrorKind::Other,
        })
    } else {
        Ok(())
    }
}

struct FailingFile {
    inner: Box<dyn VfsFile>,
    count: Arc<AtomicU64>,
    fail_at: u64,
}

impl VfsFile for FailingFile {
    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, VfsError> {
        self.inner.read_at(offset, buf)
    }
    fn write_at(&mut self, offset: u64, data: &[u8]) -> Result<(), VfsError> {
        self.inner.write_at(offset, data)
    }
    fn append(&mut self, data: &[u8]) -> Result<u64, VfsError> {
        self.inner.append(data)
    }
    fn truncate(&mut self, len: u64) -> Result<(), VfsError> {
        self.inner.truncate(len)
    }
    fn len(&self) -> Result<u64, VfsError> {
        self.inner.len()
    }
    fn fsync(&mut self) -> Result<(), VfsError> {
        fail(&self.count, self.fail_at, VfsOp::Fsync)?;
        self.inner.fsync()
    }
}

impl Vfs for FailingVfs {
    fn open(&self, path: &str, mode: OpenMode) -> Result<Box<dyn VfsFile>, VfsError> {
        Ok(Box::new(FailingFile {
            inner: self.inner.open(path, mode)?,
            count: Arc::clone(&self.count),
            fail_at: self.fail_at,
        }))
    }
    fn fsync_dir(&self, dir: &str) -> Result<(), VfsError> {
        fail(&self.count, self.fail_at, VfsOp::FsyncDir)?;
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
