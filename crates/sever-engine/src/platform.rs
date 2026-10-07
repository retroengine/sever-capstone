//! Platform checks at startup for the data directory (spec §12.9; Part 2 scope: the key-file and
//! memory checks of §12.8 are Part 4's).
//!
//! - Linux x86-64.
//! - The data directory is on ext4 or XFS. Development and tests may set
//!   `allow_unsafe_fs` (owner decision of 7 October 2026, like §12.8's `allow_unsafe_memory`); the
//!   override is reported so every run ledger entry can record it.
//! - `ENGINE.lock` is taken exclusively: one process per data directory.

use std::fs::{File, OpenOptions};
use std::path::Path;

use rustix::fs::{FlockOperation, flock, statfs};
use sever_types::Error;

/// `statfs` magic of ext2/3/4.
pub const EXT4_SUPER_MAGIC: i64 = 0xEF53;
/// `statfs` magic of XFS.
pub const XFS_SUPER_MAGIC: i64 = 0x5846_5342;

/// The lock file.
pub const LOCK_FILE: &str = "ENGINE.lock";

fn unsafe_platform(check: &'static str) -> Error {
    Error::PlatformUnsafe { check }
}

/// What the platform checks found.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PlatformReport {
    /// The data directory's filesystem is ext4 or XFS.
    pub data_fs_ok: bool,
    /// The check was overridden (`allow_unsafe_fs`); recorded in every ledger entry.
    pub overridden: bool,
}

/// §12.9: Linux x86-64, and the data directory on ext4 or XFS (unless `allow_unsafe_fs`).
pub fn check_data_dir(dir: &Path, allow_unsafe_fs: bool) -> Result<PlatformReport, Error> {
    if !(cfg!(target_os = "linux") && cfg!(target_arch = "x86_64")) {
        return Err(unsafe_platform("§12.9 Linux x86-64"));
    }
    let fs = statfs(dir).map_err(|_| unsafe_platform("§12.9 data directory"))?;
    #[allow(clippy::useless_conversion)]
    // f_type is i64 on x86-64 glibc, a different type elsewhere
    let ty = i64::from(fs.f_type);
    let ok = ty == EXT4_SUPER_MAGIC || ty == XFS_SUPER_MAGIC;
    if !ok && !allow_unsafe_fs {
        return Err(unsafe_platform("§12.9 data filesystem not ext4 or XFS"));
    }
    Ok(PlatformReport {
        data_fs_ok: ok,
        overridden: !ok,
    })
}

/// `ENGINE.lock`, held exclusively for the engine's lifetime (§12.9). Released when dropped or
/// when the process dies.
#[derive(Debug)]
pub struct EngineLock {
    _file: File,
}

impl EngineLock {
    /// Takes the lock in `dir`, or fails at once if another process holds it.
    pub fn acquire(dir: &Path) -> Result<Self, Error> {
        let file = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(dir.join(LOCK_FILE))
            .map_err(|_| unsafe_platform("§12.9 ENGINE.lock"))?;
        flock(&file, FlockOperation::NonBlockingLockExclusive)
            .map_err(|_| unsafe_platform("§12.9 ENGINE.lock held by another process"))?;
        Ok(Self { _file: file })
    }
}
