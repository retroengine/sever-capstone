//! The EP-5 contract suite (Build §3.4, test level L7).
//!
//! Enabled by the `contract-tests` feature, so a backend written after this crate froze runs the
//! same checks. Two parts:
//!
//! - [`ep5_functional_contract`]: what every [`Vfs`] must do (`PosixVfs` on tmpfs and ext4,
//!   `SimVfs`).
//! - [`ep5_crash_contract`]: what a crash simulator must do (spec §12.2). Synced data and synced
//!   entries always survive; unsynced ones can be lost, torn and reordered; a failed `fsync` can
//!   be injected. A backend that "loses" nothing fails this part (Build §5.7 L7), because a crash
//!   test run on it could never find a missing `fsync`.

use crate::{CrashPolicy, FaultPlan, OpenMode, SimVfs, Vfs, VfsError, VfsFile, VfsOp, read_all};

/// Why a backend failed the EP-5 contract.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ep5Violation {
    /// A call that should succeed failed, or the reverse; the label names the step.
    Step(&'static str),
    /// Bytes read back differ from the bytes written.
    ReadBack(&'static str),
    /// `list` returned the wrong names or order.
    Listing(&'static str),
    /// Crash part: `fsync`ed data was lost or changed.
    SyncedDataLost,
    /// Crash part: an `fsync_dir`ed entry was lost.
    SyncedEntryLost,
    /// Crash part: an unsynced write survived `CrashPolicy::DropAll`.
    UnsyncedWriteSurvived,
    /// Crash part: an unsynced directory entry survived `CrashPolicy::DropAll`.
    UnsyncedEntrySurvived,
    /// Crash part: `CrashPolicy::KeepAll` lost a write that reached the page cache.
    KeepAllLostData,
    /// Crash part: no seed ever dropped an unsynced write.
    NeverDrops,
    /// Crash part: no seed ever tore an unsynced write.
    NeverTears,
    /// Crash part: no seed ever let a later unsynced write land without an earlier one.
    NeverReorders,
    /// Crash part: an injected `fsync` failure was not reported.
    FsyncFailureNotInjected,
    /// Crash part: data whose `fsync` failed became durable anyway (a retry must not save it).
    FailedSyncMadeDurable,
    /// Crash part: a call succeeded after the crash.
    OpAfterCrash,
    /// Crash part: the same seed gave two different file systems.
    NotDeterministic,
}

type Ep5 = Result<(), Ep5Violation>;

fn step<T>(r: Result<T, VfsError>, label: &'static str) -> Result<T, Ep5Violation> {
    r.map_err(|_| Ep5Violation::Step(label))
}

fn expect_err<T>(r: Result<T, VfsError>, want: VfsError, label: &'static str) -> Ep5 {
    match r {
        Err(e) if e == want => Ok(()),
        _ => Err(Ep5Violation::Step(label)),
    }
}

fn read_path(vfs: &dyn Vfs, path: &str) -> Result<Vec<u8>, VfsError> {
    read_all(vfs.open(path, OpenMode::Existing)?.as_ref())
}

fn check_bytes(got: &[u8], want: &[u8], label: &'static str) -> Ep5 {
    if got == want {
        Ok(())
    } else {
        Err(Ep5Violation::ReadBack(label))
    }
}

fn check_list(vfs: &dyn Vfs, dir: &str, want: &[&str], label: &'static str) -> Ep5 {
    let got = step(vfs.list(dir), label)?;
    if got.iter().map(String::as_str).eq(want.iter().copied()) {
        Ok(())
    } else {
        Err(Ep5Violation::Listing(label))
    }
}

/// EP-5, functional part. `vfs` must be rooted at an empty directory; it is empty again after a
/// passing run.
pub fn ep5_functional_contract(vfs: &dyn Vfs) -> Ep5 {
    check_list(vfs, "", &[], "empty root")?;

    // open modes
    expect_err(
        vfs.open("f", OpenMode::Existing),
        VfsError::NotFound,
        "open missing",
    )?;
    let mut f = step(vfs.open("f", OpenMode::CreateNew), "create new")?;
    expect_err(
        vfs.open("f", OpenMode::CreateNew),
        VfsError::AlreadyExists,
        "create new twice",
    )?;
    step(vfs.open("f", OpenMode::Create), "create existing")?;

    // positional reads and writes, append, holes, truncate
    step(f.write_at(0, b"hello"), "write_at")?;
    if step(f.len(), "len")? != 5 {
        return Err(Ep5Violation::ReadBack("len after write"));
    }
    let mut buf = [0u8; 10];
    let n = step(f.read_at(0, &mut buf), "read_at")?;
    check_bytes(
        buf.get(..n).unwrap_or_default(),
        b"hello",
        "short read at end",
    )?;
    if step(f.append(b"world"), "append")? != 5 {
        return Err(Ep5Violation::ReadBack("append offset"));
    }
    step(f.write_at(12, b"!"), "write past end")?;
    check_bytes(
        &step(read_all(f.as_ref()), "read all")?,
        b"helloworld\0\0!",
        "hole is zero",
    )?;
    if step(f.read_at(100, &mut buf), "read past end")? != 0 {
        return Err(Ep5Violation::ReadBack("read past end"));
    }
    step(f.truncate(4), "truncate down")?;
    step(f.truncate(6), "truncate up")?;
    check_bytes(
        &step(read_path(vfs, "f"), "second handle")?,
        b"hell\0\0",
        "truncate",
    )?;
    step(f.fsync(), "fsync")?;
    step(vfs.fsync_dir(""), "fsync_dir root")?;
    drop(f);

    // directories
    step(vfs.create_dir("d"), "create_dir")?;
    expect_err(
        vfs.create_dir("d"),
        VfsError::AlreadyExists,
        "create_dir twice",
    )?;
    expect_err(
        vfs.create_dir("x/y"),
        VfsError::NotFound,
        "create_dir no parent",
    )?;
    expect_err(
        vfs.open("d", OpenMode::Create),
        VfsError::IsADirectory,
        "open a directory",
    )?;
    expect_err(
        vfs.open("f/x", OpenMode::Create),
        VfsError::NotADirectory,
        "file as directory",
    )?;
    expect_err(vfs.list("f"), VfsError::NotADirectory, "list a file")?;
    expect_err(vfs.list("nope"), VfsError::NotFound, "list missing")?;
    step(vfs.fsync_dir("d"), "fsync_dir")?;

    // names sort by UTF-8 bytes: "B" (0x42) < "a" (0x61) < "é" (0xC3 0xA9)
    for name in ["é", "a", "B"] {
        step(
            vfs.open(&format!("d/{name}"), OpenMode::CreateNew),
            "create names",
        )?;
    }
    check_list(vfs, "d", &["B", "a", "é"], "byte order")?;
    for name in ["é", "a", "B"] {
        step(vfs.unlink(&format!("d/{name}")), "unlink names")?;
    }
    check_list(vfs, "", &["d", "f"], "root listing")?;

    // rename: move, replace a file, move a directory, refusals
    step(vfs.rename("f", "d/g"), "rename move")?;
    expect_err(
        vfs.open("f", OpenMode::Existing),
        VfsError::NotFound,
        "old name gone",
    )?;
    check_bytes(
        &step(read_path(vfs, "d/g"), "moved file")?,
        b"hell\0\0",
        "moved file",
    )?;
    let mut h = step(vfs.open("h", OpenMode::CreateNew), "create h")?;
    step(h.write_at(0, b"new"), "write h")?;
    drop(h);
    step(vfs.rename("h", "d/g"), "rename replace")?;
    check_bytes(
        &step(read_path(vfs, "d/g"), "replaced")?,
        b"new",
        "replaced file",
    )?;
    check_list(vfs, "", &["d"], "after replace")?;
    step(vfs.create_dir("c.tmp"), "create c.tmp")?;
    step(vfs.open("c.tmp/m", OpenMode::CreateNew), "create c.tmp/m")?;
    step(vfs.rename("c.tmp", "c"), "rename directory")?;
    check_list(vfs, "c", &["m"], "renamed directory keeps entries")?;
    expect_err(
        vfs.rename("c", "c/sub"),
        VfsError::InvalidPath,
        "rename into itself",
    )?;
    expect_err(
        vfs.rename("d/g", "c"),
        VfsError::IsADirectory,
        "rename onto directory",
    )?;
    expect_err(
        vfs.rename("nope", "x"),
        VfsError::NotFound,
        "rename missing",
    )?;

    // unlink and remove_dir
    step(vfs.unlink("d/g"), "unlink")?;
    expect_err(vfs.unlink("d/g"), VfsError::NotFound, "unlink twice")?;
    expect_err(
        vfs.unlink("c"),
        VfsError::IsADirectory,
        "unlink a directory",
    )?;
    expect_err(
        vfs.remove_dir("c"),
        VfsError::DirectoryNotEmpty,
        "remove_dir non-empty",
    )?;
    step(vfs.unlink("c/m"), "unlink c/m")?;
    step(vfs.remove_dir("c"), "remove_dir")?;
    step(vfs.remove_dir("d"), "remove_dir d")?;
    expect_err(vfs.remove_dir("d"), VfsError::NotFound, "remove_dir twice")?;

    // invalid paths
    expect_err(
        vfs.open("/abs", OpenMode::Create),
        VfsError::InvalidPath,
        "absolute path",
    )?;
    expect_err(
        vfs.open("a/../b", OpenMode::Create),
        VfsError::InvalidPath,
        "dot-dot",
    )?;
    expect_err(vfs.list("a//b"), VfsError::InvalidPath, "empty component")?;
    check_list(vfs, "", &[], "empty at the end")
}

/// A backend that can simulate crashes (the crash part of EP-5).
pub trait CrashableVfs: Vfs {
    /// The process dies now.
    fn crash(&self);
    /// Power cut and reboot under `policy`.
    fn restart(&self, policy: CrashPolicy);
    /// The next `fsync` or `fsync_dir` fails.
    fn fail_next_sync(&self);
    /// An independent copy of the simulation.
    fn fork_box(&self) -> Box<dyn CrashableVfs>;
}

impl CrashableVfs for SimVfs {
    fn crash(&self) {
        SimVfs::crash(self);
    }
    fn restart(&self, policy: CrashPolicy) {
        SimVfs::restart(self, policy);
    }
    fn fail_next_sync(&self) {
        self.set_faults(FaultPlan {
            fail_sync_at: Some(1),
            ..FaultPlan::default()
        });
    }
    fn fork_box(&self) -> Box<dyn CrashableVfs> {
        Box::new(self.fork())
    }
}

const DURABLE: &[u8] = b"durable";

/// `d/a` holds "durable"; the file, `d` and both entries are synced.
fn durable_base(vfs: &dyn Vfs) -> Ep5 {
    step(vfs.create_dir("d"), "base: create_dir")?;
    step(vfs.fsync_dir(""), "base: fsync_dir root")?;
    let mut a = step(vfs.open("d/a", OpenMode::CreateNew), "base: create")?;
    step(a.write_at(0, DURABLE), "base: write")?;
    step(a.fsync(), "base: fsync")?;
    step(vfs.fsync_dir("d"), "base: fsync_dir")
}

fn open_a(vfs: &dyn Vfs) -> Result<Box<dyn VfsFile>, Ep5Violation> {
    vfs.open("d/a", OpenMode::Existing)
        .map_err(|_| Ep5Violation::SyncedEntryLost)
}

fn read_a(vfs: &dyn Vfs) -> Result<Vec<u8>, Ep5Violation> {
    read_all(open_a(vfs)?.as_ref()).map_err(|_| Ep5Violation::SyncedDataLost)
}

/// Every file of the tree under `dir`, as `(path, bytes)` in name order.
fn snapshot(vfs: &dyn Vfs, dir: &str, out: &mut Vec<(String, Vec<u8>)>) -> Result<(), VfsError> {
    for name in vfs.list(dir)? {
        let path = if dir.is_empty() {
            name
        } else {
            format!("{dir}/{name}")
        };
        match vfs.open(&path, OpenMode::Existing) {
            Ok(f) => out.push((path, read_all(f.as_ref())?)),
            Err(VfsError::IsADirectory) => snapshot(vfs, &path, out)?,
            Err(e) => return Err(e),
        }
    }
    Ok(())
}

/// EP-5, crash part (spec §12.2). `empty` must be an empty simulation; it is not modified.
pub fn ep5_crash_contract(empty: &dyn CrashableVfs) -> Ep5 {
    let base = empty.fork_box();
    durable_base(base.as_ref())?;

    // 1. Synced data and synced entries survive every policy.
    let policies = [CrashPolicy::DropAll, CrashPolicy::KeepAll]
        .into_iter()
        .chain((0..64).map(CrashPolicy::Random));
    for policy in policies {
        let v = base.fork_box();
        v.restart(policy);
        if read_a(v.as_ref())? != DURABLE {
            return Err(Ep5Violation::SyncedDataLost);
        }
    }

    // 2. Unsynced writes are lost under DropAll and kept under KeepAll.
    for (policy, want) in [
        (CrashPolicy::DropAll, &b"durable"[..]),
        (CrashPolicy::KeepAll, &b"XXXXXXXtail"[..]),
    ] {
        let v = base.fork_box();
        let mut a = open_a(v.as_ref())?;
        step(a.write_at(0, b"XXXXXXX"), "unsynced write")?;
        step(a.append(b"tail"), "unsynced append")?;
        v.restart(policy);
        let got = read_a(v.as_ref())?;
        if got != want {
            return Err(match policy {
                CrashPolicy::DropAll => Ep5Violation::UnsyncedWriteSurvived,
                _ => Ep5Violation::KeepAllLostData,
            });
        }
    }

    // 3. An entry that was never fsync_dir'ed is lost, even if its data was fsynced.
    let v = base.fork_box();
    let mut b = step(v.open("d/b", OpenMode::CreateNew), "create d/b")?;
    step(b.write_at(0, b"b"), "write d/b")?;
    step(b.fsync(), "fsync d/b")?;
    v.restart(CrashPolicy::DropAll);
    if v.open("d/b", OpenMode::Existing).is_ok() {
        return Err(Ep5Violation::UnsyncedEntrySurvived);
    }

    // 4. An unsynced rename is undone; a synced one stays.
    for synced in [false, true] {
        let v = base.fork_box();
        step(v.rename("d/a", "d/c"), "rename")?;
        if synced {
            step(v.fsync_dir("d"), "fsync_dir after rename")?;
        }
        v.restart(CrashPolicy::DropAll);
        let names = step(v.list("d"), "list after rename")?;
        match (synced, names.as_slice()) {
            (false, [n]) if n == "a" => {}
            (true, [n]) if n == "c" => {}
            (false, _) => return Err(Ep5Violation::UnsyncedEntrySurvived),
            (true, _) => return Err(Ep5Violation::SyncedEntryLost),
        }
    }

    // 5. Under Random, unsynced writes are sometimes dropped, torn and reordered, and the synced
    //    prefix never changes.
    let (mut dropped, mut torn, mut reordered) = (false, false, false);
    for seed in 0..256 {
        let v = base.fork_box();
        let mut a = open_a(v.as_ref())?;
        step(a.append(&[0x11; 64]), "append one")?;
        step(a.append(&[0x22; 64]), "append two")?;
        v.restart(CrashPolicy::Random(seed));
        let got = read_a(v.as_ref())?;
        let (head, rest) = got.split_at(DURABLE.len().min(got.len()));
        if head != DURABLE {
            return Err(Ep5Violation::SyncedDataLost);
        }
        let one = rest.get(..64).unwrap_or(rest);
        let two = rest.get(64..).unwrap_or_default();
        dropped |= rest.is_empty();
        let partial = |r: &[u8], v: u8| {
            let k = r.iter().filter(|&&x| x == v).count();
            k > 0 && k < 64
        };
        torn |= partial(one, 0x11) || partial(two, 0x22);

        // Overlapping writes: the first covers bytes [0, 64) after the durable prefix, the
        // second [32, 96). Bytes [64, 96) can only come from the second write, and when any of
        // them is present the second write covered [32, 64) whole; a 0x11 byte there means the
        // first write landed after it. A dropped first write can never look like this.
        let v = base.fork_box();
        let mut a = open_a(v.as_ref())?;
        let at = DURABLE.len() as u64;
        step(a.write_at(at, &[0x11; 64]), "overlap one")?;
        step(a.write_at(at + 32, &[0x22; 64]), "overlap two")?;
        v.restart(CrashPolicy::Random(seed));
        let got = read_a(v.as_ref())?;
        if got.get(..DURABLE.len()) != Some(DURABLE) {
            return Err(Ep5Violation::SyncedDataLost);
        }
        let rest = got.get(DURABLE.len()..).unwrap_or_default();
        let mid = rest.get(32..64).unwrap_or_default();
        let tail = rest.get(64..).unwrap_or_default();
        reordered |= tail.contains(&0x22) && mid.contains(&0x11);
    }
    if !dropped {
        return Err(Ep5Violation::NeverDrops);
    }
    if !torn {
        return Err(Ep5Violation::NeverTears);
    }
    if !reordered {
        return Err(Ep5Violation::NeverReorders);
    }

    // 6. A failed fsync is reported, and a retry does not make the data durable.
    let v = base.fork_box();
    let mut a = open_a(v.as_ref())?;
    step(a.write_at(0, b"LOST!!!"), "write before failed fsync")?;
    v.fail_next_sync();
    match a.fsync() {
        Err(VfsError::Io {
            op: VfsOp::Fsync, ..
        }) => {}
        _ => return Err(Ep5Violation::FsyncFailureNotInjected),
    }
    let _ = a.fsync(); // the forbidden retry (§12.7), here only to probe the model
    v.restart(CrashPolicy::KeepAll);
    if read_a(v.as_ref())? != DURABLE {
        return Err(Ep5Violation::FailedSyncMadeDurable);
    }

    // 7. After a crash nothing succeeds, and old handles stay dead after the restart.
    let v = base.fork_box();
    let mut a = open_a(v.as_ref())?;
    v.crash();
    let mut buf = [0u8; 1];
    let dead = a.read_at(0, &mut buf).is_err()
        && a.write_at(0, b"x").is_err()
        && a.fsync().is_err()
        && v.open("d/a", OpenMode::Existing).is_err()
        && v.list("").is_err()
        && v.create_dir("e").is_err();
    v.restart(CrashPolicy::KeepAll);
    if !dead || a.read_at(0, &mut buf).is_ok() {
        return Err(Ep5Violation::OpAfterCrash);
    }

    // 8. The same seed gives the same file system.
    let run = |seed| -> Result<Vec<(String, Vec<u8>)>, Ep5Violation> {
        let v = base.fork_box();
        let mut a = open_a(v.as_ref())?;
        for i in 0..8u8 {
            step(a.append(&[i; 100]), "determinism: append")?;
        }
        step(v.open("d/n", OpenMode::CreateNew), "determinism: create")?;
        v.restart(CrashPolicy::Random(seed));
        let mut out = Vec::new();
        step(snapshot(v.as_ref(), "", &mut out), "determinism: snapshot")?;
        Ok(out)
    };
    for seed in [42, 123, 777, 2024, 9999] {
        if run(seed)? != run(seed)? {
            return Err(Ep5Violation::NotDeterministic);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use sever_spec::spec;
    use std::sync::Mutex;

    #[test]
    #[spec("SR-12.2-1", "SR-12.2-3")]
    fn p2_vfs_ep5_sim_passes_functional_contract() {
        assert_eq!(ep5_functional_contract(&SimVfs::new()), Ok(()));
    }

    #[test]
    #[spec("SR-12.2-3", "SR-12.2-4", "SR-12.2-5")]
    fn p2_vfs_ep5_sim_passes_crash_contract() {
        assert_eq!(ep5_crash_contract(&SimVfs::new()), Ok(()));
    }

    /// Delegates every call to a `SimVfs`.
    macro_rules! delegate_vfs {
        ($t:ty, $inner:expr) => {
            impl Vfs for $t {
                fn open(&self, p: &str, m: OpenMode) -> Result<Box<dyn VfsFile>, VfsError> {
                    $inner(self).open(p, m)
                }
                fn fsync_dir(&self, d: &str) -> Result<(), VfsError> {
                    $inner(self).fsync_dir(d)
                }
                fn rename(&self, a: &str, b: &str) -> Result<(), VfsError> {
                    $inner(self).rename(a, b)
                }
                fn unlink(&self, p: &str) -> Result<(), VfsError> {
                    $inner(self).unlink(p)
                }
                fn list(&self, d: &str) -> Result<Vec<String>, VfsError> {
                    $inner(self).list(d)
                }
                fn create_dir(&self, p: &str) -> Result<(), VfsError> {
                    $inner(self).create_dir(p)
                }
                fn remove_dir(&self, p: &str) -> Result<(), VfsError> {
                    $inner(self).remove_dir(p)
                }
            }
        };
    }

    /// Deliberately wrong: a crash loses nothing (every restart is `KeepAll`).
    struct Kind(SimVfs);
    delegate_vfs!(Kind, |s: &Kind| s.0.clone());
    impl CrashableVfs for Kind {
        fn crash(&self) {
            self.0.crash();
        }
        fn restart(&self, _policy: CrashPolicy) {
            self.0.restart(CrashPolicy::KeepAll);
        }
        fn fail_next_sync(&self) {
            CrashableVfs::fail_next_sync(&self.0);
        }
        fn fork_box(&self) -> Box<dyn CrashableVfs> {
            Box::new(Kind(self.0.fork()))
        }
    }

    /// Deliberately wrong: a crash loses everything, synced or not.
    struct Amnesiac(Mutex<SimVfs>);
    delegate_vfs!(Amnesiac, |s: &Amnesiac| s.0.lock().unwrap().clone());
    impl CrashableVfs for Amnesiac {
        fn crash(&self) {
            self.0.lock().unwrap().crash();
        }
        fn restart(&self, _policy: CrashPolicy) {
            *self.0.lock().unwrap() = SimVfs::new();
        }
        fn fail_next_sync(&self) {
            CrashableVfs::fail_next_sync(&*self.0.lock().unwrap());
        }
        fn fork_box(&self) -> Box<dyn CrashableVfs> {
            Box::new(Amnesiac(Mutex::new(self.0.lock().unwrap().fork())))
        }
    }

    /// Deliberately wrong: fsync failures cannot be injected.
    struct Infallible(SimVfs);
    delegate_vfs!(Infallible, |s: &Infallible| s.0.clone());
    impl CrashableVfs for Infallible {
        fn crash(&self) {
            self.0.crash();
        }
        fn restart(&self, policy: CrashPolicy) {
            self.0.restart(policy);
        }
        fn fail_next_sync(&self) {}
        fn fork_box(&self) -> Box<dyn CrashableVfs> {
            Box::new(Infallible(self.0.fork()))
        }
    }

    // Build §5.7 L7, P2-T7 — a deliberately non-durable backend fails the crash part.
    #[test]
    #[spec("SR-12.2-3")]
    fn p2_vfs_ep5_contract_rejects_a_backend_that_loses_nothing() {
        assert_eq!(
            ep5_crash_contract(&Kind(SimVfs::new())),
            Err(Ep5Violation::UnsyncedWriteSurvived)
        );
    }

    #[test]
    #[spec("SR-12.2-3")]
    fn p2_vfs_ep5_contract_rejects_a_backend_that_loses_synced_data() {
        assert_eq!(
            ep5_crash_contract(&Amnesiac(Mutex::new(SimVfs::new()))),
            Err(Ep5Violation::SyncedEntryLost)
        );
    }

    #[test]
    #[spec("SR-12.2-4")]
    fn p2_vfs_ep5_contract_rejects_a_backend_without_fsync_faults() {
        assert_eq!(
            ep5_crash_contract(&Infallible(SimVfs::new())),
            Err(Ep5Violation::FsyncFailureNotInjected)
        );
    }
}
