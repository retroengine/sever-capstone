//! `LinuxProbe` on the test machine: the EP-11 contract (Build 3-4 §2.8 L7), the suite's own
//! sensitivity (each kind of wrong answer is rejected), and the §12.8 core-dump settings read back
//! from the kernel.

#![allow(clippy::unwrap_used)]

use std::path::{Path, PathBuf};

use rustix::process::{DumpableBehavior, Resource, dumpable_behavior, getrlimit};
use sever_platform::contract::{Ep11Violation, ep11_probe_contract};
use sever_platform::{Hibernation, LinuxProbe, PlatformProbe, ProbeError, Swap};
use sever_spec::spec;

fn scratch(name: &str) -> PathBuf {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join(name);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

// oracle: D the EP-11 suite on the default probe
#[test]
fn p4_platform_ep11_linux_probe_passes_contract() {
    ep11_probe_contract(&LinuxProbe, &scratch("ep11-linux")).unwrap();
}

/// `LinuxProbe` with one answer replaced by a wrong one.
struct Lying(u8);

impl PlatformProbe for Lying {
    fn filesystem(&self, dir: &Path) -> Result<i64, ProbeError> {
        match self.0 {
            0 => Err(ProbeError),
            1 => Ok(LinuxProbe.filesystem(dir).unwrap_or(0xEF53)),
            _ => LinuxProbe.filesystem(dir),
        }
    }
    fn no_cow(&self, path: &Path) -> Result<Option<bool>, ProbeError> {
        match self.0 {
            2 => Ok(None),
            3 => Ok(Some(LinuxProbe.no_cow(path)?.unwrap_or(false))),
            _ => LinuxProbe.no_cow(path),
        }
    }
    fn swaps(&self) -> Result<Vec<Swap>, ProbeError> {
        match self.0 {
            4 => Err(ProbeError),
            5 => Ok(vec![Swap {
                name: "/dev/sdz".into(),
                kind: "Partition".into(),
                dm_uuid: None,
            }]),
            _ => LinuxProbe.swaps(),
        }
    }
    fn hibernation(&self) -> Result<Hibernation, ProbeError> {
        if self.0 == 6 {
            Err(ProbeError)
        } else {
            LinuxProbe.hibernation()
        }
    }
    fn disable_core_dumps(&self) -> Result<(), ProbeError> {
        Ok(())
    }
    fn lock_memory(&self) -> Result<(), ProbeError> {
        Ok(())
    }
}

// oracle: D the EP-11 suite against probes that are wrong in one answer each
#[test]
fn p4_platform_ep11_contract_rejects_wrong_probes() {
    let dir = scratch("ep11-lying");
    let want = [
        Ep11Violation::FilesystemOfExisting,
        Ep11Violation::FilesystemOfMissing,
        Ep11Violation::AttributeOfExisting,
        Ep11Violation::AttributeOfMissing,
        Ep11Violation::Swaps,
        Ep11Violation::Swaps,
        Ep11Violation::Hibernation,
    ];
    for (i, w) in (0u8..).zip(want) {
        assert_eq!(ep11_probe_contract(&Lying(i), &dir), Err(w), "lie {i}");
    }
}

// oracle: A §12.8 "At startup the engine sets RLIMIT_CORE = 0 and PR_SET_DUMPABLE = 0", read back
// from the kernel (getrlimit, PR_GET_DUMPABLE)
#[spec("SR-12.8-3")]
#[test]
fn p4_platform_linux_probe_turns_core_dumps_off() {
    LinuxProbe.disable_core_dumps().unwrap();
    let core = getrlimit(Resource::Core);
    assert_eq!((core.current, core.maximum), (Some(0), Some(0)));
    assert_eq!(dumpable_behavior().unwrap(), DumpableBehavior::NotDumpable);
}
