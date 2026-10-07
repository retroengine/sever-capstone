//! L7: the EP-5 functional contract on real files (Build §5.7: `PosixVfs` on tmpfs and ext4).

// Test code (clippy.toml allows these in #[test] functions; the helpers here are test code too).
#![allow(clippy::unwrap_used)]

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};

use sever_spec::spec;
use sever_vfs::contract::ep5_functional_contract;
use sever_vfs::{OpenMode, PosixVfs, Vfs, VfsError};

/// A fresh empty directory under `base`, removed when dropped.
struct Scratch(PathBuf);

impl Scratch {
    fn new(base: &Path) -> Self {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = base.join(format!(
            "sever-vfs-{}-{}",
            std::process::id(),
            N.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(&dir).unwrap();
        Self(dir)
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

/// The filesystem type of `path` from /proc/self/mounts (longest matching mount point).
fn fs_type(path: &Path) -> String {
    let path = path.canonicalize().unwrap();
    let mounts = std::fs::read_to_string("/proc/self/mounts").unwrap();
    mounts
        .lines()
        .filter_map(|l| {
            let mut it = l.split_whitespace();
            let (_, mnt, ty) = (it.next()?, it.next()?, it.next()?);
            path.starts_with(mnt).then(|| (mnt.len(), ty.to_owned()))
        })
        .max()
        .map(|(_, ty)| ty)
        .unwrap()
}

#[test]
#[spec("SR-12.2-1", "SR-12.2-2")]
fn p2_vfs_ep5_posix_passes_functional_contract_on_ext4() {
    // Cargo's per-target scratch directory lives under target/, on the repository's disk.
    let base = Path::new(env!("CARGO_TARGET_TMPDIR"));
    let scratch = Scratch::new(base);
    assert_eq!(
        fs_type(&scratch.0),
        "ext4",
        "run from the WSL ext4 disk (CLAUDE.md §9)"
    );
    let vfs = PosixVfs::new(&scratch.0).unwrap();
    assert_eq!(ep5_functional_contract(&vfs), Ok(()));
}

#[test]
#[spec("SR-12.2-1", "SR-12.2-2")]
fn p2_vfs_ep5_posix_passes_functional_contract_on_tmpfs() {
    let scratch = Scratch::new(Path::new("/dev/shm"));
    assert_eq!(fs_type(&scratch.0), "tmpfs");
    let vfs = PosixVfs::new(&scratch.0).unwrap();
    assert_eq!(ep5_functional_contract(&vfs), Ok(()));
}

#[test]
fn p2_vfs_posix_root_must_be_an_existing_directory() {
    let scratch = Scratch::new(Path::new(env!("CARGO_TARGET_TMPDIR")));
    assert_eq!(
        PosixVfs::new(scratch.0.join("missing")).err(),
        Some(VfsError::NotFound)
    );
    std::fs::write(scratch.0.join("file"), b"x").unwrap();
    assert_eq!(
        PosixVfs::new(scratch.0.join("file")).err(),
        Some(VfsError::NotADirectory)
    );
}

#[test]
fn p2_vfs_posix_paths_stay_inside_the_root() {
    let scratch = Scratch::new(Path::new(env!("CARGO_TARGET_TMPDIR")));
    let vfs = PosixVfs::new(&scratch.0).unwrap();
    for bad in ["../escape", "/etc/passwd", "a/../../b"] {
        assert_eq!(
            vfs.open(bad, OpenMode::Create).err(),
            Some(VfsError::InvalidPath),
            "{bad}"
        );
    }
}
