//! `sever-vfs`: the storage I/O layer (Part 2, Build §5.5; spec §12.2).
//!
//! Every read and write of the storage engine goes through the [`Vfs`] trait (EP-5, Build §3.3).
//! Two backends: [`PosixVfs`] (real files) and [`SimVfs`] (in memory, seeded), which models the
//! POSIX durability contract conservatively: only `fsync`ed data and `fsync_dir`ed directory
//! entries are sure to survive a simulated crash. All crash tests run on `SimVfs`, so they are
//! deterministic.
//!
//! Paths are relative to the backend's root, `/`-separated, and checked strictly
//! ([`check_path`]); the root directory itself is the empty path `""`. Errors carry no path or
//! file content (§17).

pub mod durable;
pub mod posix;
pub mod rng;
pub mod sim;

#[cfg(any(test, feature = "contract-tests"))]
pub mod contract;

#[cfg(test)]
mod sim_tests;

pub use posix::PosixVfs;
pub use sim::{CrashPolicy, FaultPlan, SimStats, SimVfs};

use core::fmt;

/// How [`Vfs::open`] treats a missing or existing file.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OpenMode {
    /// The file must exist.
    Existing,
    /// Open the file, creating it empty if it does not exist.
    Create,
    /// Create the file; it must not exist.
    CreateNew,
}

/// The operation an [`VfsError::Io`] came from (fixed text, never a path).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum VfsOp {
    /// [`Vfs::open`].
    Open,
    /// [`VfsFile::read_at`].
    Read,
    /// [`VfsFile::write_at`] or [`VfsFile::append`].
    Write,
    /// [`VfsFile::truncate`].
    Truncate,
    /// [`VfsFile::len`].
    Len,
    /// [`VfsFile::fsync`].
    Fsync,
    /// [`Vfs::fsync_dir`].
    FsyncDir,
    /// [`Vfs::rename`].
    Rename,
    /// [`Vfs::unlink`].
    Unlink,
    /// [`Vfs::list`].
    List,
    /// [`Vfs::create_dir`].
    CreateDir,
    /// [`Vfs::remove_dir`].
    RemoveDir,
}

/// Every error a [`Vfs`] returns. No variant carries a path or file content (§17).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum VfsError {
    /// The path, or one of its parent directories, does not exist.
    NotFound,
    /// The path already exists ([`OpenMode::CreateNew`], [`Vfs::create_dir`]).
    AlreadyExists,
    /// A file was found where a directory was needed.
    NotADirectory,
    /// A directory was found where a file was needed.
    IsADirectory,
    /// [`Vfs::remove_dir`] on a directory that still has entries.
    DirectoryNotEmpty,
    /// The path is not a valid relative path ([`check_path`]), or a rename would move a directory
    /// into itself.
    InvalidPath,
    /// [`SimVfs`] only: the simulated process has crashed. Nothing more reaches the disk until
    /// the simulation restarts, and every handle from before the crash stays dead.
    Crashed,
    /// Any other failure of `op`, including an injected `fsync` failure. After an `fsync` or
    /// `fsync_dir` failure the caller MUST abort and never retry (spec §12.7).
    Io {
        /// The failed operation.
        op: VfsOp,
        /// The operating system's error kind.
        kind: std::io::ErrorKind,
    },
}

impl fmt::Display for VfsError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotFound => f.write_str("not found"),
            Self::AlreadyExists => f.write_str("already exists"),
            Self::NotADirectory => f.write_str("not a directory"),
            Self::IsADirectory => f.write_str("is a directory"),
            Self::DirectoryNotEmpty => f.write_str("directory not empty"),
            Self::InvalidPath => f.write_str("invalid path"),
            Self::Crashed => f.write_str("simulated crash"),
            Self::Io { op, kind } => write!(f, "{op:?} failed: {kind}"),
        }
    }
}

impl std::error::Error for VfsError {}

/// An open file. Reads and writes take explicit offsets; there is no file position.
pub trait VfsFile: Send {
    /// Reads up to `buf.len()` bytes at `offset`. Returns fewer only at the end of the file
    /// (0 at or past the end).
    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, VfsError>;
    /// Writes all of `data` at `offset`, extending the file (with zero bytes in any gap).
    fn write_at(&mut self, offset: u64, data: &[u8]) -> Result<(), VfsError>;
    /// Writes all of `data` at the current end of the file; returns the offset it was written at.
    fn append(&mut self, data: &[u8]) -> Result<u64, VfsError>;
    /// Sets the file length to `len`, cutting or extending with zero bytes.
    fn truncate(&mut self, len: u64) -> Result<(), VfsError>;
    /// The current file length.
    fn len(&self) -> Result<u64, VfsError>;
    /// True when the file is empty.
    fn is_empty(&self) -> Result<bool, VfsError> {
        Ok(self.len()? == 0)
    }
    /// Makes the file's data durable. On error the caller MUST abort (spec §12.7).
    fn fsync(&mut self) -> Result<(), VfsError>;
}

/// EP-5 (Build §3.3; spec §12.2): every file operation of the storage engine.
///
/// The list is spec §12.2's (`open`, `read_at`, `write_at`, `append`, `fsync`, `fsync_dir`,
/// `rename`, `unlink`, `truncate`, `list`; the file-level ones are on [`VfsFile`]), plus
/// `create_dir` and `remove_dir`, which storage checkpoints need (§15.6).
pub trait Vfs: Send + Sync {
    /// Opens the file at `path` for reading and writing.
    fn open(&self, path: &str, mode: OpenMode) -> Result<Box<dyn VfsFile>, VfsError>;
    /// Makes the entries of directory `dir` durable (creations, renames, unlinks in it).
    /// On error the caller MUST abort (spec §12.7).
    fn fsync_dir(&self, dir: &str) -> Result<(), VfsError>;
    /// Renames `from` to `to`, atomically replacing a file at `to`.
    fn rename(&self, from: &str, to: &str) -> Result<(), VfsError>;
    /// Removes the file at `path`.
    fn unlink(&self, path: &str) -> Result<(), VfsError>;
    /// The names in directory `dir`, ascending by bytes.
    fn list(&self, dir: &str) -> Result<Vec<String>, VfsError>;
    /// Creates the directory `path`; its parent must exist.
    fn create_dir(&self, path: &str) -> Result<(), VfsError>;
    /// Removes the empty directory `path`.
    fn remove_dir(&self, path: &str) -> Result<(), VfsError>;
}

/// Checks a relative path and returns its components. `""` is the root and has none.
///
/// Rejected: a leading or trailing `/`, an empty component (`a//b`), `.` and `..`, and NUL bytes.
pub fn check_path(path: &str) -> Result<Vec<&str>, VfsError> {
    if path.is_empty() {
        return Ok(Vec::new());
    }
    let parts: Vec<&str> = path.split('/').collect();
    let ok = parts
        .iter()
        .all(|c| !c.is_empty() && *c != "." && *c != ".." && !c.contains('\0'));
    if ok {
        Ok(parts)
    } else {
        Err(VfsError::InvalidPath)
    }
}

/// Reads the whole file.
pub fn read_all(file: &dyn VfsFile) -> Result<Vec<u8>, VfsError> {
    let len = usize::try_from(file.len()?).map_err(|_| VfsError::Io {
        op: VfsOp::Read,
        kind: std::io::ErrorKind::OutOfMemory,
    })?;
    let mut buf = vec![0u8; len];
    let got = file.read_at(0, &mut buf)?;
    buf.truncate(got);
    Ok(buf)
}

/// Reads exactly `buf.len()` bytes at `offset`; a short file is [`VfsError::Io`] with
/// [`std::io::ErrorKind::UnexpectedEof`].
pub fn read_exact_at(file: &dyn VfsFile, offset: u64, buf: &mut [u8]) -> Result<(), VfsError> {
    if file.read_at(offset, buf)? == buf.len() {
        Ok(())
    } else {
        Err(VfsError::Io {
            op: VfsOp::Read,
            kind: std::io::ErrorKind::UnexpectedEof,
        })
    }
}

/// The parent directory of `path` (`""` for a top-level name). `path` must be valid.
pub fn parent(path: &str) -> &str {
    path.rsplit_once('/').map_or("", |(dir, _)| dir)
}

#[cfg(test)]
mod tests {
    use super::*;
    use sever_spec::spec;

    #[test]
    #[spec("SR-12.2-1")]
    fn p2_vfs_paths_are_checked_strictly() {
        assert_eq!(check_path(""), Ok(vec![]));
        assert_eq!(check_path("MANIFEST"), Ok(vec!["MANIFEST"]));
        assert_eq!(
            check_path("checkpoint/7.tmp/meta.bin"),
            Ok(vec!["checkpoint", "7.tmp", "meta.bin"])
        );
        for bad in ["/abs", "a/", "a//b", ".", "..", "a/../b", "a/./b", "nul\0"] {
            assert_eq!(check_path(bad), Err(VfsError::InvalidPath), "{bad:?}");
        }
    }

    #[test]
    fn p2_vfs_parent_of_paths() {
        assert_eq!(parent("MANIFEST"), "");
        assert_eq!(parent("wal/1.wal"), "wal");
        assert_eq!(parent("checkpoint/7/meta.bin"), "checkpoint/7");
    }

    #[test]
    #[spec("SR-17-2")]
    fn p2_vfs_errors_carry_no_path() {
        let all = [
            VfsError::NotFound,
            VfsError::AlreadyExists,
            VfsError::NotADirectory,
            VfsError::IsADirectory,
            VfsError::DirectoryNotEmpty,
            VfsError::InvalidPath,
            VfsError::Crashed,
            VfsError::Io {
                op: VfsOp::Fsync,
                kind: std::io::ErrorKind::Other,
            },
        ];
        for e in all {
            let text = e.to_string();
            assert!(!text.contains('/'), "{text}");
        }
    }
}
