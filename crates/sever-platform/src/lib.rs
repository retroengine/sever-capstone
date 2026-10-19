//! Startup checks and memory hygiene (spec §12.8–12.9; Build 3-4 §2.4, Part 4 module 4).
//!
//! [`startup`] runs, in order: Linux x86-64; core dumps off; swap, hibernation and the memory lock
//! (§12.8, overridden only by `allow_unsafe_memory`); the data directory's and the key directory's
//! filesystems (§12.9, overridden only by `allow_unsafe_fs`). The first check that fails without
//! its override refuses with `PlatformUnsafe`, naming the rule. Each overridden check is listed in
//! the [`StartupReport`], which every run ledger entry records (DB-90). `ENGINE.lock` and the
//! generator and hash self-checks stay with the engine (Part 2 and 3).

pub mod contract;
pub mod memory;
pub mod probe;
pub mod rules;

#[cfg(test)]
mod tests;

use std::path::Path;

use sever_types::Error;

pub use memory::{LockedMemory, MlockProvider};
pub use probe::{Hibernation, LinuxProbe, PlatformProbe, ProbeError, Swap};

/// The key file's name in the key directory (§14.7).
pub const KEYS_FILE: &str = "KEYS";

/// §12.9: not Linux x86-64.
pub const CHECK_TARGET: &str = "§12.9 Linux x86-64";
/// §12.8: core dumps could not be turned off.
pub const CHECK_CORE_DUMPS: &str = "§12.8 core dumps";
/// §12.8: swap is on and not encrypted.
pub const CHECK_SWAP: &str = "§12.8 swap not encrypted";
/// §12.8: hibernation is enabled.
pub const CHECK_HIBERNATION: &str = "§12.8 hibernation enabled";
/// §12.8: memory could not be locked.
pub const CHECK_MLOCK: &str = "§12.8 mlock";
/// §12.9: the data directory is not on ext4 or XFS (the text of Part 2's check).
pub const CHECK_DATA_FS: &str = "§12.9 data filesystem not ext4 or XFS";
/// §12.9: the key file's filesystem does not overwrite in place.
pub const CHECK_KEY_FS: &str = "§12.9 key filesystem does not overwrite in place";

/// The two development-only overrides (§12.8, §12.9; DB-90).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Overrides {
    /// `memory.allow_unsafe_memory`: the §12.8 checks.
    pub allow_unsafe_memory: bool,
    /// `platform.allow_unsafe_fs`: the §12.9 filesystem checks.
    pub allow_unsafe_fs: bool,
}

/// What [`startup`] found.
#[derive(Debug)]
pub struct StartupReport {
    /// The checks that failed and were overridden, in the order they ran; recorded in every run
    /// ledger entry.
    pub overridden: Vec<&'static str>,
    /// Present when the memory lock took effect: install [`MlockProvider`] with it. Absent only
    /// under `allow_unsafe_memory`, when Part 1's heap provider stays in place.
    pub locked: Option<LockedMemory>,
}

fn refuse(check: &'static str) -> Error {
    Error::PlatformUnsafe { check }
}

/// Runs the startup checks of §12.8–12.9 for a database whose data directory is `data_dir` and
/// whose key directory is `key_dir`.
pub fn startup(
    probe: &dyn PlatformProbe,
    data_dir: &Path,
    key_dir: &Path,
    o: Overrides,
) -> Result<StartupReport, Error> {
    if !(cfg!(target_os = "linux") && cfg!(target_arch = "x86_64")) {
        return Err(refuse(CHECK_TARGET));
    }
    let mut overridden = Vec::new();
    let mut check = |ok: bool, name: &'static str, allowed: bool| -> Result<(), Error> {
        if ok {
            Ok(())
        } else if allowed {
            overridden.push(name);
            Ok(())
        } else {
            Err(refuse(name))
        }
    };
    let mem = o.allow_unsafe_memory;
    check(probe.disable_core_dumps().is_ok(), CHECK_CORE_DUMPS, mem)?;
    let swap_ok = probe.swaps().is_ok_and(|s| rules::swap_safe(&s));
    check(swap_ok, CHECK_SWAP, mem)?;
    let hib_ok = probe
        .hibernation()
        .is_ok_and(|h| !rules::hibernation_enabled(&h));
    check(hib_ok, CHECK_HIBERNATION, mem)?;
    let locked = probe.lock_memory().is_ok();
    check(locked, CHECK_MLOCK, mem)?;

    let fs = o.allow_unsafe_fs;
    let data_ok = probe.filesystem(data_dir).is_ok_and(rules::data_fs_ok);
    check(data_ok, CHECK_DATA_FS, fs)?;
    // DB-93: before KEYS exists, its attribute is the one it will inherit from the directory.
    let keys = key_dir.join(KEYS_FILE);
    let no_cow = match probe.no_cow(&keys) {
        Ok(Some(v)) => Ok(v),
        Ok(None) => probe.no_cow(key_dir).map(|v| v.unwrap_or(false)),
        Err(e) => Err(e),
    };
    let key_ok = match (probe.filesystem(key_dir), no_cow) {
        (Ok(magic), Ok(nc)) => rules::key_fs_ok(magic, nc),
        _ => false,
    };
    check(key_ok, CHECK_KEY_FS, fs)?;

    Ok(StartupReport {
        overridden,
        locked: locked.then_some(LockedMemory(())),
    })
}
