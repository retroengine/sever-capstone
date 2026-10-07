//! `sever-p2`: Part 2's composition root (Build §5.5): `Engine<NoExtension, PlaintextSealer>`
//! with no participants, on real files, after the platform checks and with `ENGINE.lock` held.
//!
//! This is where Part 2 meets the operating system: the data and key directories, the lock, the
//! configuration hash, `SECRETS` file permissions (mode 0600, §14.1), and the failure policy
//! (abort the process on a durability failure, §12.7).

use std::path::{Path, PathBuf};
use std::sync::Arc;

use sever_engine::{Engine, EngineConfig, EngineLock, FailurePolicy, PlatformReport};
use sever_index::NoExtension;
use sever_txn::PlaintextSealer;
use sever_types::{CollectionId, Error};
use sever_vfs::PosixVfs;
use sha2::{Digest, Sha256};

/// Part 2's engine.
pub type P2Engine = Engine<NoExtension, PlaintextSealer>;

/// How to open a database.
#[derive(Clone, Debug)]
pub struct OpenOptions {
    /// The data directory (created if missing).
    pub data_dir: PathBuf,
    /// The key directory (created if missing; may be another filesystem, §14.1).
    pub key_dir: PathBuf,
    /// Development only: allow a data directory that is not ext4 or XFS (§12.9; recorded).
    pub allow_unsafe_fs: bool,
    /// The configuration file whose SHA-256 is recorded in every storage checkpoint (§18).
    pub config_file: Option<PathBuf>,
    /// Abort (production) or poison (tests).
    pub on_failure: FailurePolicy,
}

impl OpenOptions {
    /// Defaults: abort on failure, the platform checks enforced.
    pub fn new(data_dir: impl Into<PathBuf>, key_dir: impl Into<PathBuf>) -> Self {
        Self {
            data_dir: data_dir.into(),
            key_dir: key_dir.into(),
            allow_unsafe_fs: false,
            config_file: None,
            on_failure: FailurePolicy::Abort,
        }
    }
}

/// An open database: the engine, the lock that keeps other processes out, and what the platform
/// checks found.
pub struct Opened {
    /// The engine.
    pub engine: P2Engine,
    /// `ENGINE.lock`, held while this value lives.
    pub lock: EngineLock,
    /// The §12.9 report (record `overridden` in the run ledger).
    pub platform: PlatformReport,
}

impl core::fmt::Debug for Opened {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "Opened({:?})", self.platform)
    }
}

fn io_err(check: &'static str) -> impl Fn(std::io::Error) -> Error {
    move |_| Error::PlatformUnsafe { check }
}

/// Opens (recovering, or creating) the database: platform checks, lock, engine.
pub fn open(o: &OpenOptions) -> Result<Opened, Error> {
    std::fs::create_dir_all(&o.data_dir).map_err(io_err("§12.9 data directory"))?;
    std::fs::create_dir_all(&o.key_dir).map_err(io_err("§14.1 key directory"))?;
    let platform = sever_engine::check_data_dir(&o.data_dir, o.allow_unsafe_fs)?;
    let lock = EngineLock::acquire(&o.data_dir)?;
    let config_hash = match &o.config_file {
        Some(p) => {
            Sha256::digest(std::fs::read(p).map_err(io_err("§18 configuration file"))?).into()
        }
        None => [0; 32],
    };
    let cfg = EngineConfig {
        on_failure: o.on_failure,
        config_hash,
        ..EngineConfig::default()
    };
    let engine = Engine::open(
        Arc::new(
            PosixVfs::new(&o.data_dir).map_err(|_| Error::PlatformUnsafe {
                check: "§12.9 data directory",
            })?,
        ),
        Arc::new(
            PosixVfs::new(&o.key_dir).map_err(|_| Error::PlatformUnsafe {
                check: "§14.1 key directory",
            })?,
        ),
        PlaintextSealer,
        NoExtension,
        Vec::new(),
        cfg,
    )?;
    secrets_mode_0600(&o.key_dir)?;
    Ok(Opened {
        engine,
        lock,
        platform,
    })
}

/// §14.1: `SECRETS` is mode 0600.
fn secrets_mode_0600(key_dir: &Path) -> Result<(), Error> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(
        key_dir.join(sever_engine::SECRETS),
        std::fs::Permissions::from_mode(0o600),
    )
    .map_err(io_err("§14.1 SECRETS permissions"))
}

/// A collection ID as 32 lowercase hex characters.
pub fn cid_hex(c: &CollectionId) -> String {
    c.as_bytes().iter().map(|b| format!("{b:02x}")).collect()
}

/// Parses 32 hex characters into a collection ID.
pub fn parse_cid(s: &str) -> Option<CollectionId> {
    if s.len() != 32 {
        return None;
    }
    let mut out = [0u8; 16];
    for (i, b) in out.iter_mut().enumerate() {
        *b = u8::from_str_radix(s.get(2 * i..2 * i + 2)?, 16).ok()?;
    }
    Some(CollectionId::from_bytes(out))
}

#[cfg(test)]
mod tests {
    use super::*;
    use sever_spec::spec;

    fn dir(tag: &str) -> PathBuf {
        // Under target/, on the repository's ext4 disk.
        let d = Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/../../target/p2-tests"))
            .join(format!("{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        d
    }

    #[test]
    #[spec("SR-12.9-1", "SR-12.9-2")]
    fn p2_root_opens_on_ext4_locks_and_protects_secrets() {
        let d = dir("open");
        let o = OpenOptions::new(d.join("data"), d.join("keys"));
        let opened = open(&o).unwrap();
        assert!(!opened.platform.overridden);
        // A second process (here: a second open) is refused while the lock is held.
        assert!(matches!(open(&o), Err(Error::PlatformUnsafe { .. })));
        use std::os::unix::fs::PermissionsExt;
        let mode = std::fs::metadata(d.join("keys/SECRETS"))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(mode & 0o777, 0o600);
        drop(opened);
        open(&o).unwrap();
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    #[spec("SR-12.9-1")]
    fn p2_root_refuses_tmpfs_unless_overridden() {
        let d = Path::new("/dev/shm").join(format!("p2-shm-{}", std::process::id()));
        let mut o = OpenOptions::new(d.join("data"), d.join("keys"));
        assert!(matches!(open(&o), Err(Error::PlatformUnsafe { .. })));
        o.allow_unsafe_fs = true;
        assert!(open(&o).unwrap().platform.overridden);
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn p2_root_collection_ids_round_trip_as_hex() {
        let c = CollectionId::from_bytes([0xa5; 16]);
        assert_eq!(parse_cid(&cid_hex(&c)), Some(c));
        assert_eq!(parse_cid("xyz"), None);
    }
}
