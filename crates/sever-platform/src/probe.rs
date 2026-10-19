//! EP-11 `PlatformProbe` (Build 3-4 §2.4; overview DB-53): what the startup checks of spec
//! §12.8–12.9 ask the machine, and the two actions they take on it. The rules in
//! [`crate::rules`] are pure functions of these answers, so every refusal can be tested with a fake
//! probe, without root and without reconfiguring the test machine.
//!
//! [`LinuxProbe`] is the default: it reads `/proc`, `/sys` and `statfs`, and acts through
//! `setrlimit`, `prctl` and `mlockall`.

use std::fs;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};

use rustix::fs::{IFlags, ioctl_getflags, statfs};
use rustix::mm::{MlockAllFlags, mlockall};
use rustix::process::{
    DumpableBehavior, Resource, Rlimit, getrlimit, set_dumpable_behavior, setrlimit,
};

/// The probe could not answer (the check that asked fails closed).
#[derive(Clone, Copy, Debug, PartialEq, Eq, thiserror::Error)]
#[error("the platform probe could not answer")]
pub struct ProbeError;

/// One active entry of `/proc/swaps`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Swap {
    /// The `Filename` column, unescaped (`/dev/zram0`, `/dev/dm-1`, `/swapfile`).
    pub name: String,
    /// The `Type` column: `partition` or `file`.
    pub kind: String,
    /// For a device-mapper device, the contents of its `dm/uuid` (trimmed); otherwise `None`.
    pub dm_uuid: Option<String>,
}

/// The two files §12.8 reads to decide whether hibernation is enabled; `None` when absent.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Hibernation {
    /// `/sys/power/state`.
    pub state: Option<String>,
    /// `/sys/power/resume`.
    pub resume: Option<String>,
}

/// EP-11: the platform as the startup checks see it.
pub trait PlatformProbe {
    /// The `statfs` magic number of the filesystem holding `dir`.
    fn filesystem(&self, dir: &Path) -> Result<i64, ProbeError>;
    /// Whether `path` carries the no-copy-on-write attribute (`FS_NOCOW_FL`); `Ok(None)` when
    /// `path` does not exist.
    fn no_cow(&self, path: &Path) -> Result<Option<bool>, ProbeError>;
    /// The active swap devices.
    fn swaps(&self) -> Result<Vec<Swap>, ProbeError>;
    /// The hibernation state.
    fn hibernation(&self) -> Result<Hibernation, ProbeError>;
    /// §12.8: sets `RLIMIT_CORE = 0` and `PR_SET_DUMPABLE = 0` for this process.
    fn disable_core_dumps(&self) -> Result<(), ProbeError>;
    /// §12.8, DB-93: locks every page of the process, present and future, in memory; fails when
    /// a finite memory-lock limit could later refuse an allocation.
    fn lock_memory(&self) -> Result<(), ProbeError>;
}

/// The default probe: the running Linux kernel.
#[derive(Clone, Copy, Debug, Default)]
pub struct LinuxProbe;

/// `/proc/swaps` without its header line: `(name, type)` per entry. Names escape space, tab,
/// newline and backslash as `\ooo` octal (the kernel's `seq_file_path`).
pub fn parse_swaps(text: &str) -> Vec<(String, String)> {
    text.lines()
        .skip(1)
        .filter_map(|line| {
            let mut cols = line.split_whitespace();
            let name = unescape(cols.next()?);
            let kind = cols.next()?.to_owned();
            Some((name, kind))
        })
        .collect()
}

fn unescape(s: &str) -> String {
    let mut rest = s.as_bytes();
    let mut out = Vec::with_capacity(rest.len());
    while let Some((&c, tail)) = rest.split_first() {
        let octal = match tail {
            [a @ b'0'..=b'3', b @ b'0'..=b'7', d @ b'0'..=b'7', ..] if c == b'\\' => {
                Some((a - b'0') * 64 + (b - b'0') * 8 + (d - b'0'))
            }
            _ => None,
        };
        match (octal, tail.get(3..)) {
            (Some(byte), Some(after)) => {
                out.push(byte);
                rest = after;
            }
            _ => {
                out.push(c);
                rest = tail;
            }
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// The `dm/uuid` of a swap device, if it is a device-mapper device.
fn dm_uuid(name: &str) -> Result<Option<String>, ProbeError> {
    let dev: PathBuf = match fs::canonicalize(name) {
        Ok(p) => p,
        Err(_) => return Ok(None), // a swap file under a path that moved, or not a device
    };
    let Some(base) = dev.file_name().and_then(|b| b.to_str()) else {
        return Ok(None);
    };
    if !base.starts_with("dm-") {
        return Ok(None);
    }
    match fs::read_to_string(format!("/sys/block/{base}/dm/uuid")) {
        Ok(u) => Ok(Some(u.trim().to_owned())),
        Err(_) => Err(ProbeError),
    }
}

/// `CAP_IPC_LOCK` (capability 14) is in this process's effective set (`/proc/self/status` `CapEff`).
fn has_ipc_lock() -> Result<bool, ProbeError> {
    let status = fs::read_to_string("/proc/self/status").map_err(|_| ProbeError)?;
    let hex = status
        .lines()
        .find_map(|l| l.strip_prefix("CapEff:"))
        .ok_or(ProbeError)?;
    let caps = u64::from_str_radix(hex.trim(), 16).map_err(|_| ProbeError)?;
    Ok(caps & (1 << 14) != 0)
}

fn read_optional(path: &str) -> Result<Option<String>, ProbeError> {
    match fs::read_to_string(path) {
        Ok(s) => Ok(Some(s)),
        Err(e) if e.kind() == ErrorKind::NotFound => Ok(None),
        Err(_) => Err(ProbeError),
    }
}

impl PlatformProbe for LinuxProbe {
    fn filesystem(&self, dir: &Path) -> Result<i64, ProbeError> {
        let fs = statfs(dir).map_err(|_| ProbeError)?;
        #[allow(clippy::useless_conversion)] // f_type's type differs between targets
        Ok(i64::from(fs.f_type))
    }

    fn no_cow(&self, path: &Path) -> Result<Option<bool>, ProbeError> {
        let file = match fs::File::open(path) {
            Ok(f) => f,
            Err(e) if e.kind() == ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(ProbeError),
        };
        match ioctl_getflags(&file) {
            Ok(flags) => Ok(Some(flags.contains(IFlags::NOCOW))),
            // A filesystem without inode flags (tmpfs, 9p, …) has no such attribute.
            Err(rustix::io::Errno::NOTTY | rustix::io::Errno::NOSYS | rustix::io::Errno::INVAL) => {
                Ok(Some(false))
            }
            Err(_) => Err(ProbeError),
        }
    }

    fn swaps(&self) -> Result<Vec<Swap>, ProbeError> {
        let text = fs::read_to_string("/proc/swaps").map_err(|_| ProbeError)?;
        parse_swaps(&text)
            .into_iter()
            .map(|(name, kind)| {
                let dm_uuid = dm_uuid(&name)?;
                Ok(Swap {
                    name,
                    kind,
                    dm_uuid,
                })
            })
            .collect()
    }

    fn hibernation(&self) -> Result<Hibernation, ProbeError> {
        Ok(Hibernation {
            state: read_optional("/sys/power/state")?,
            resume: read_optional("/sys/power/resume")?,
        })
    }

    fn disable_core_dumps(&self) -> Result<(), ProbeError> {
        setrlimit(
            Resource::Core,
            Rlimit {
                current: Some(0),
                maximum: Some(0),
            },
        )
        .map_err(|_| ProbeError)?;
        set_dumpable_behavior(DumpableBehavior::NotDumpable).map_err(|_| ProbeError)
    }

    fn lock_memory(&self) -> Result<(), ProbeError> {
        // DB-93: with MCL_FUTURE every later allocation counts against RLIMIT_MEMLOCK, so a finite
        // limit would make the engine fail an allocation (and abort) once it grows past it. The
        // lock is taken only when nothing can stop it: no limit, or CAP_IPC_LOCK.
        let unlimited = getrlimit(Resource::Memlock).current.is_none();
        if !(unlimited || has_ipc_lock()?) {
            return Err(ProbeError);
        }
        mlockall(MlockAllFlags::CURRENT | MlockAllFlags::FUTURE | MlockAllFlags::ONFAULT)
            .map_err(|_| ProbeError)
    }
}
