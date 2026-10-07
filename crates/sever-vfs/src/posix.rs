//! `PosixVfs` (spec §12.2): real files under a root directory.
//!
//! Positional reads and writes (`pread`, `pwrite`) and `fsync` only. Nothing is memory-mapped: a
//! failed write through a mapping kills the process with a signal instead of returning an error
//! (§12.7). An `fsync` error is returned once, and the caller aborts (§12.7); this layer never
//! retries one.

use std::fs::{self, File, OpenOptions};
use std::io::{self, ErrorKind};
use std::os::unix::fs::FileExt;
use std::path::{Path, PathBuf};

use crate::{OpenMode, Vfs, VfsError, VfsFile, VfsOp, check_path};

/// Real files under `root`.
#[derive(Clone, Debug)]
pub struct PosixVfs {
    root: PathBuf,
}

impl PosixVfs {
    /// A backend rooted at the existing directory `root`.
    pub fn new(root: impl Into<PathBuf>) -> Result<Self, VfsError> {
        let root = root.into();
        match fs::metadata(&root) {
            Ok(m) if m.is_dir() => Ok(Self { root }),
            Ok(_) => Err(VfsError::NotADirectory),
            Err(e) => Err(map_err(VfsOp::Open, &e)),
        }
    }

    /// The root directory.
    pub fn root(&self) -> &Path {
        &self.root
    }

    fn resolve(&self, path: &str) -> Result<PathBuf, VfsError> {
        let mut p = self.root.clone();
        for c in check_path(path)? {
            p.push(c);
        }
        Ok(p)
    }
}

fn map_err(op: VfsOp, e: &io::Error) -> VfsError {
    match e.kind() {
        ErrorKind::NotFound => VfsError::NotFound,
        ErrorKind::AlreadyExists => VfsError::AlreadyExists,
        ErrorKind::NotADirectory => VfsError::NotADirectory,
        ErrorKind::IsADirectory => VfsError::IsADirectory,
        ErrorKind::DirectoryNotEmpty => VfsError::DirectoryNotEmpty,
        kind => VfsError::Io { op, kind },
    }
}

impl Vfs for PosixVfs {
    fn open(&self, path: &str, mode: OpenMode) -> Result<Box<dyn VfsFile>, VfsError> {
        if path.is_empty() {
            return Err(VfsError::IsADirectory);
        }
        let p = self.resolve(path)?;
        let mut o = OpenOptions::new();
        o.read(true).write(true);
        match mode {
            OpenMode::Existing => {}
            OpenMode::Create => {
                o.create(true);
            }
            OpenMode::CreateNew => {
                o.create_new(true);
            }
        }
        let file = o.open(&p).map_err(|e| map_err(VfsOp::Open, &e))?;
        // Opening a directory read-write fails with EISDIR on Linux; checked anyway so that the
        // contract holds on every POSIX system.
        let meta = file.metadata().map_err(|e| map_err(VfsOp::Open, &e))?;
        if meta.is_dir() {
            return Err(VfsError::IsADirectory);
        }
        Ok(Box::new(PosixFile { file }))
    }

    fn fsync_dir(&self, dir: &str) -> Result<(), VfsError> {
        let p = self.resolve(dir)?;
        let d = File::open(&p).map_err(|e| map_err(VfsOp::FsyncDir, &e))?;
        d.sync_all().map_err(|e| VfsError::Io {
            op: VfsOp::FsyncDir,
            kind: e.kind(),
        })
    }

    fn rename(&self, from: &str, to: &str) -> Result<(), VfsError> {
        let (f, t) = (check_path(from)?, check_path(to)?);
        if f.is_empty() || t.is_empty() || t.starts_with(&f) {
            return Err(VfsError::InvalidPath);
        }
        let (pf, pt) = (self.resolve(from)?, self.resolve(to)?);
        // The contract replaces files only; a directory never replaces an existing entry.
        let from_meta = fs::symlink_metadata(&pf).map_err(|e| map_err(VfsOp::Rename, &e))?;
        match fs::symlink_metadata(&pt) {
            Ok(m) if from_meta.is_dir() || m.is_dir() => {
                return Err(if m.is_dir() {
                    VfsError::IsADirectory
                } else {
                    VfsError::AlreadyExists
                });
            }
            _ => {}
        }
        fs::rename(&pf, &pt).map_err(|e| map_err(VfsOp::Rename, &e))
    }

    fn unlink(&self, path: &str) -> Result<(), VfsError> {
        if path.is_empty() {
            return Err(VfsError::IsADirectory);
        }
        let p = self.resolve(path)?;
        let meta = fs::symlink_metadata(&p).map_err(|e| map_err(VfsOp::Unlink, &e))?;
        if meta.is_dir() {
            return Err(VfsError::IsADirectory);
        }
        fs::remove_file(&p).map_err(|e| map_err(VfsOp::Unlink, &e))
    }

    fn list(&self, dir: &str) -> Result<Vec<String>, VfsError> {
        let p = self.resolve(dir)?;
        let mut names = Vec::new();
        for entry in fs::read_dir(&p).map_err(|e| map_err(VfsOp::List, &e))? {
            let entry = entry.map_err(|e| map_err(VfsOp::List, &e))?;
            // A name that is not UTF-8 was not written through this layer; skip it.
            if let Ok(name) = entry.file_name().into_string() {
                names.push(name);
            }
        }
        names.sort_unstable_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
        Ok(names)
    }

    fn create_dir(&self, path: &str) -> Result<(), VfsError> {
        if path.is_empty() {
            return Err(VfsError::AlreadyExists);
        }
        let p = self.resolve(path)?;
        fs::create_dir(&p).map_err(|e| map_err(VfsOp::CreateDir, &e))
    }

    fn remove_dir(&self, path: &str) -> Result<(), VfsError> {
        if path.is_empty() {
            return Err(VfsError::InvalidPath);
        }
        let p = self.resolve(path)?;
        let meta = fs::symlink_metadata(&p).map_err(|e| map_err(VfsOp::RemoveDir, &e))?;
        if !meta.is_dir() {
            return Err(VfsError::NotADirectory);
        }
        fs::remove_dir(&p).map_err(|e| map_err(VfsOp::RemoveDir, &e))
    }
}

struct PosixFile {
    file: File,
}

impl VfsFile for PosixFile {
    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, VfsError> {
        let mut done = 0usize;
        while let Some(rest) = buf.get_mut(done..) {
            if rest.is_empty() {
                break;
            }
            match self.file.read_at(rest, offset + done as u64) {
                Ok(0) => break,
                Ok(n) => done += n,
                Err(e) if e.kind() == ErrorKind::Interrupted => {}
                Err(e) => return Err(map_err(VfsOp::Read, &e)),
            }
        }
        Ok(done)
    }

    fn write_at(&mut self, offset: u64, data: &[u8]) -> Result<(), VfsError> {
        self.file
            .write_all_at(data, offset)
            .map_err(|e| map_err(VfsOp::Write, &e))
    }

    fn append(&mut self, data: &[u8]) -> Result<u64, VfsError> {
        // One writer per file (§12.5), so the length cannot change between the two calls.
        let end = self.len()?;
        self.write_at(end, data)?;
        Ok(end)
    }

    fn truncate(&mut self, len: u64) -> Result<(), VfsError> {
        self.file
            .set_len(len)
            .map_err(|e| map_err(VfsOp::Truncate, &e))
    }

    fn len(&self) -> Result<u64, VfsError> {
        self.file
            .metadata()
            .map(|m| m.len())
            .map_err(|e| map_err(VfsOp::Len, &e))
    }

    fn fsync(&mut self) -> Result<(), VfsError> {
        self.file.sync_all().map_err(|e| VfsError::Io {
            op: VfsOp::Fsync,
            kind: e.kind(),
        })
    }
}
