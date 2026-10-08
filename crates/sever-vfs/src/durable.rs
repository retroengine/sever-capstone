//! The durability discipline of spec §12.7, in one place for every caller:
//!
//! - every file creation, rename or unlink is followed by `fsync` of the containing directory;
//! - an `fsync` error is returned once and never retried (the caller aborts), because after a
//!   failure the kernel may already have dropped the dirty pages.

use crate::{OpenMode, Vfs, VfsError, VfsFile, parent};

/// `fsync` a file. Never retried (§12.7).
pub fn sync(file: &mut dyn VfsFile) -> Result<(), VfsError> {
    let first = file.fsync();
    // SB-14: retry a failed fsync (the retry "succeeds" without saving the lost pages).
    if cfg!(feature = "sabotage-SB-14") && first.is_err() {
        return file.fsync();
    }
    first
}

/// `fsync` a directory. Never retried (§12.7).
pub fn sync_dir(vfs: &dyn Vfs, dir: &str) -> Result<(), VfsError> {
    let first = vfs.fsync_dir(dir);
    if cfg!(feature = "sabotage-SB-14") && first.is_err() {
        return vfs.fsync_dir(dir);
    }
    first
}

/// Creates a new file and makes its directory entry durable (§12.7). The file is empty.
pub fn create(vfs: &dyn Vfs, path: &str) -> Result<Box<dyn VfsFile>, VfsError> {
    let f = vfs.open(path, OpenMode::CreateNew)?;
    sync_dir(vfs, parent(path))?;
    Ok(f)
}

/// Creates a directory and makes its entry durable (§12.7).
pub fn create_dir(vfs: &dyn Vfs, path: &str) -> Result<(), VfsError> {
    vfs.create_dir(path)?;
    sync_dir(vfs, parent(path))
}

/// Renames and makes the new entry (and the removal of the old one) durable (§12.7).
pub fn rename(vfs: &dyn Vfs, from: &str, to: &str) -> Result<(), VfsError> {
    vfs.rename(from, to)?;
    // SB-12: skip the directory fsync after a rename.
    if cfg!(feature = "sabotage-SB-12") {
        return Ok(());
    }
    sync_dir(vfs, parent(to))?;
    if parent(from) != parent(to) {
        sync_dir(vfs, parent(from))?;
    }
    Ok(())
}

/// Unlinks a file and makes the removal durable (§12.7).
pub fn unlink(vfs: &dyn Vfs, path: &str) -> Result<(), VfsError> {
    vfs.unlink(path)?;
    sync_dir(vfs, parent(path))
}

/// Removes an empty directory and makes the removal durable (§12.7).
pub fn remove_dir(vfs: &dyn Vfs, path: &str) -> Result<(), VfsError> {
    vfs.remove_dir(path)?;
    sync_dir(vfs, parent(path))
}

/// Writes a whole new file atomically: `<path>.tmp`, `fsync`, rename onto `path`, directory
/// `fsync` (§15.6 step 3, the `MANIFEST` install). A crash leaves either the old file or the new
/// one, never a mix.
pub fn replace_file(vfs: &dyn Vfs, path: &str, bytes: &[u8]) -> Result<(), VfsError> {
    let tmp = format!("{path}.tmp");
    // A leftover from an earlier interrupted install is garbage.
    match vfs.unlink(&tmp) {
        Ok(()) | Err(VfsError::NotFound) => {}
        Err(e) => return Err(e),
    }
    let mut f = vfs.open(&tmp, OpenMode::CreateNew)?;
    f.write_at(0, bytes)?;
    sync(f.as_mut())?;
    drop(f);
    rename(vfs, &tmp, path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{CrashPolicy, FaultPlan, SimVfs, read_all};
    use sever_spec::spec;

    // SB-14 must turn this red.
    #[test]
    // oracle: A §12.7 a failed fsync reaches the caller and is never retried (exactly one fsync)
    #[spec("SR-12.7-2")]
    fn p2_vfs_failed_fsync_is_reported_never_retried() {
        let v = SimVfs::new();
        let mut f = create(&v, "f").unwrap();
        f.write_at(0, b"data").unwrap();
        v.set_faults(FaultPlan {
            fail_sync_at: Some(1),
            ..FaultPlan::default()
        });
        assert!(sync(f.as_mut()).is_err(), "the failure reaches the caller");
        assert_eq!(v.stats().fsyncs, 1, "exactly one file fsync: no retry");
    }

    #[test]
    // oracle: A §12.7 a failed directory fsync reaches the caller
    #[spec("SR-12.7-2")]
    fn p2_vfs_failed_dir_fsync_is_reported() {
        let v = SimVfs::new();
        v.set_faults(FaultPlan {
            fail_sync_at: Some(1),
            ..FaultPlan::default()
        });
        assert!(create(&v, "f").is_err());
    }

    // SB-12 must turn this red.
    #[test]
    // oracle: A §12.7 a rename is followed by fsync of its directory, so it survives DropAll
    #[spec("SR-12.7-1")]
    fn p2_vfs_rename_is_durable_when_it_returns() {
        let v = SimVfs::new();
        create_dir(&v, "d").unwrap();
        let mut f = create(&v, "d/a.tmp").unwrap();
        f.write_at(0, b"new").unwrap();
        sync(f.as_mut()).unwrap();
        rename(&v, "d/a.tmp", "d/a").unwrap();
        v.restart(CrashPolicy::DropAll);
        assert_eq!(v.list("d").unwrap(), ["a"]);
    }

    #[test]
    // oracle: A §12.7 creation and unlink are followed by fsync of the directory
    #[spec("SR-12.7-1")]
    fn p2_vfs_create_and_unlink_are_durable_when_they_return() {
        let v = SimVfs::new();
        create_dir(&v, "d").unwrap();
        create(&v, "d/x").unwrap();
        let after_create = v.fork();
        after_create.restart(CrashPolicy::DropAll);
        assert_eq!(after_create.list("d").unwrap(), ["x"]);
        unlink(&v, "d/x").unwrap();
        v.restart(CrashPolicy::DropAll);
        assert!(v.list("d").unwrap().is_empty());
        remove_dir(&v, "d").unwrap();
        v.restart(CrashPolicy::DropAll);
        assert!(v.list("").unwrap().is_empty());
    }

    #[test]
    // oracle: A §15.6 step 3 tmp + fsync + rename + fsync_dir; §12.4 old or new at every crash point
    #[spec("SR-12.4-2")]
    fn p2_vfs_replace_file_leaves_old_or_new_at_every_crash_point() {
        let base = SimVfs::new();
        replace_file(&base, "M", b"old").unwrap();
        let dry = base.fork();
        dry.set_faults(FaultPlan::default());
        replace_file(&dry, "M", b"new!").unwrap();
        let n = dry.ops_since_plan();
        for k in 1..=n {
            for policy in [
                CrashPolicy::DropAll,
                CrashPolicy::KeepAll,
                CrashPolicy::Random(k),
            ] {
                let v = base.fork();
                v.set_faults(FaultPlan {
                    crash_at_op: Some(k),
                    tear_bytes: 2,
                    ..FaultPlan::default()
                });
                assert!(replace_file(&v, "M", b"new!").is_err());
                v.restart(policy);
                let got = read_all(v.open("M", OpenMode::Existing).unwrap().as_ref()).unwrap();
                assert!(
                    got == b"old" || got == b"new!",
                    "k = {k}, {policy:?}: {got:?}"
                );
            }
        }
        // And a leftover temp file does not block the next install.
        let v = base.fork();
        v.open("M.tmp", OpenMode::CreateNew).unwrap();
        replace_file(&v, "M", b"x").unwrap();
    }
}
