//! The EP-11 contract suite (Build 3-4 §2.4, §2.8 L7; overview DB-53): a probe answers for what
//! exists, and says so when something does not, so a rule never reads a made-up answer.
//! `LinuxProbe` passes it on the test machine; the refusal matrix itself (P4-T8) runs on a fake
//! probe in this crate's tests.

use std::fs;
use std::path::Path;

use crate::probe::PlatformProbe;

/// Why a probe failed the EP-11 contract.
#[derive(Clone, Copy, Debug, PartialEq, Eq, thiserror::Error)]
pub enum Ep11Violation {
    /// The scratch directory could not be prepared (not the probe's fault).
    #[error("the scratch directory is not writable")]
    Scratch,
    /// No filesystem type for a directory that exists.
    #[error("no filesystem type for an existing directory")]
    FilesystemOfExisting,
    /// A filesystem type for a directory that does not exist.
    #[error("a filesystem type for a missing directory")]
    FilesystemOfMissing,
    /// No attribute answer for a file that exists.
    #[error("no attribute answer for an existing file")]
    AttributeOfExisting,
    /// An attribute answer for a file that does not exist.
    #[error("an attribute answer for a missing file")]
    AttributeOfMissing,
    /// The swap list could not be read, or holds an entry without a name or a known type.
    #[error("the swap list is unreadable or malformed")]
    Swaps,
    /// The hibernation state could not be read.
    #[error("the hibernation state is unreadable")]
    Hibernation,
}

/// Runs the suite with `scratch`, an existing writable directory the suite may add one file to.
pub fn ep11_probe_contract(probe: &dyn PlatformProbe, scratch: &Path) -> Result<(), Ep11Violation> {
    let file = scratch.join("ep11-probe-file");
    fs::write(&file, b"ep11").map_err(|_| Ep11Violation::Scratch)?;
    let missing = scratch.join("ep11-probe-missing");
    match fs::remove_file(&missing) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err(Ep11Violation::Scratch),
    }

    if probe.filesystem(scratch).is_err() {
        return Err(Ep11Violation::FilesystemOfExisting);
    }
    if probe.filesystem(&missing).is_ok() {
        return Err(Ep11Violation::FilesystemOfMissing);
    }
    if !matches!(probe.no_cow(&file), Ok(Some(_))) {
        return Err(Ep11Violation::AttributeOfExisting);
    }
    if probe.no_cow(&missing) != Ok(None) {
        return Err(Ep11Violation::AttributeOfMissing);
    }
    let swaps = probe.swaps().map_err(|_| Ep11Violation::Swaps)?;
    if swaps
        .iter()
        .any(|s| s.name.is_empty() || !(s.kind == "partition" || s.kind == "file"))
    {
        return Err(Ep11Violation::Swaps);
    }
    probe
        .hibernation()
        .map_err(|_| Ep11Violation::Hibernation)?;
    Ok(())
}
