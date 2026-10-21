//! `sever-db`: the final composition root (Build 3-4 §2.4, Part 4 module 5):
//! `Engine<CommitmentExtension, AeadSealer, (LogParticipant, KeyRotationParticipant)>`.
//!
//! - Every stored secret is AES-256-GCM-SIV ciphertext under the three-level key hierarchy (§13,
//!   EP-6 `AeadSealer`), and every deletion rotates its domain and erases the old group key before
//!   it returns (§13.3–13.4, EP-7 `KeyRotationParticipant`).
//! - Every deletion yields a certificate (§11, Part 3's `LogParticipant`, registered first).
//! - [`open`] runs the startup checks of §12.8–12.9 (`sever-platform`), locks the process's memory
//!   and installs the `mlock` provider (EP-4, DB-93), takes `ENGINE.lock`, and keeps `SECRETS`
//!   mode 0600.
//!
//! The API is Part 3's (§16.1); [`Anchors`] and [`Deleted`] are Part 3's types.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use sever_cert::Certificate;
use sever_cert::participant::{LOG_PARTICIPANT_ID, LogHandle, LogParticipant, LogParts};
use sever_commit::{CommitmentExtension, InsertCredential, LeafLog};
use sever_crypto::{Generators, self_check};
use sever_engine::{
    CollectionOptions, DeleteOutcome, Engine, EngineConfig, EngineLock, FailurePolicy,
    InsertRequest,
};
use sever_erasure::KeyRotationParticipant;
use sever_index::Placement;
use sever_log::keys::OperatorKeys;
use sever_log::merkle::Hash;
use sever_log::store::{LogStoreConfig, Witnessed};
use sever_p3::keys::{self, OperatorStore};
use sever_p3::witnesses;
use sever_partition::PartitionArtefact;
use sever_platform::{LinuxProbe, MlockProvider, Overrides};
use sever_seal::{AeadSealer, KeyRing};
use sever_txn::{Clock, SystemClock, TxnParticipant};
use sever_types::{CollectionId, Error};
use sever_vfs::{PosixVfs, Vfs};

pub use sever_p3::{Anchors, Deleted, cid_hex, parse_cid, placement_text};

/// The final engine.
pub type FinalEngine = Engine<CommitmentExtension, AeadSealer>;

/// What a database is opened with.
pub struct Settings {
    /// The vector dimension of every collection (§2.2: 384 in v1; the fixtures use 16).
    pub d: usize,
    /// EP-9 (checkpoint timestamps, epochs).
    pub clock: Arc<dyn Clock>,
    /// The engine's settings.
    pub engine: EngineConfig,
    /// Segment size of the log's stores.
    pub log_segment_bytes: u64,
    /// Segment size of the wrapped-key store (§14.8).
    pub wrapped_segment_bytes: u64,
    /// Called after every rewrite of `SECRETS`.
    pub after_secrets_write: Option<keys::AfterWrite>,
    /// Generators already derived for `d`; the self-check still runs at every open (§9.2).
    pub generators: Option<Arc<Generators>>,
}

impl Settings {
    /// v1 settings for dimension `d`.
    pub fn new(d: usize) -> Self {
        Self {
            d,
            clock: Arc::new(SystemClock::default()),
            engine: EngineConfig::default(),
            log_segment_bytes: 64 * 1024 * 1024,
            wrapped_segment_bytes: 64 * 1024 * 1024,
            after_secrets_write: None,
            generators: None,
        }
    }
}

/// An open database.
pub struct Db {
    /// The engine.
    pub engine: FinalEngine,
    /// The log, as its participant keeps it.
    pub log: Arc<LogHandle>,
    ring: Arc<KeyRing>,
    gens: Arc<Generators>,
}

impl core::fmt::Debug for Db {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "Db(d = {})", self.gens.d())
    }
}

/// Opens (recovering, or creating) the database on the data directory `data` and the key
/// directory `keys`. The participants are registered in Build 3-4 §2.5's order: the log, then key
/// rotation; the sealer and the rotation participant share one key ring.
pub fn open_on(data: Arc<dyn Vfs>, keys: Arc<dyn Vfs>, s: Settings) -> Result<Db, Error> {
    let gens = match s.generators {
        Some(g) if g.d() == s.d => g,
        _ => Arc::new(Generators::derive(s.d).map_err(|_| Error::WrongDimension)?),
    };
    self_check(&gens).map_err(|_| Error::IntegrityViolation {
        invariant: "INV-10",
    })?;
    let operator = OperatorStore::load_sealed(
        Arc::clone(&keys),
        sever_format::SEALER_AES_GCM_SIV,
        s.clock.now_ms(),
        s.after_secrets_write,
    )?;
    let witnesses = witnesses::load(
        Arc::clone(&keys),
        operator.genesis_ms(),
        operator.published(),
    )?;
    let (log_participant, log) = LogParticipant::new(
        Arc::clone(&data),
        LogParts {
            gens: Arc::clone(&gens),
            clock: s.clock,
            operator: Box::new(operator),
            witnesses,
            store: LogStoreConfig {
                // DB-48: every file of the data directory names the database's sealer; the log's
                // leaves and certificates are plaintext by design (§13.2).
                sealer_id: sever_format::SEALER_AES_GCM_SIV,
                segment_bytes: s.log_segment_bytes,
            },
        },
    );
    let ring = Arc::new(KeyRing::new());
    let rotation = KeyRotationParticipant::new(
        Arc::clone(&data),
        Arc::clone(&keys),
        Arc::clone(&ring),
        s.wrapped_segment_bytes,
    );
    let participants: Vec<Box<dyn TxnParticipant<CommitmentExtension>>> =
        vec![Box::new(log_participant), Box::new(rotation)];
    let ext = CommitmentExtension::new(Arc::clone(&gens), Arc::clone(&log) as Arc<dyn LeafLog>);
    let engine = Engine::open(
        data,
        keys,
        AeadSealer::new(Arc::clone(&ring)),
        ext,
        participants,
        s.engine,
    )?;
    Ok(Db {
        engine,
        log,
        ring,
        gens,
    })
}

fn log_output(outputs: &[(u16, Vec<u8>)]) -> Option<&[u8]> {
    outputs
        .iter()
        .find(|(p, _)| *p == LOG_PARTICIPANT_ID)
        .map(|(_, b)| b.as_slice())
}

fn not_recovered() -> Error {
    Error::IntegrityViolation {
        invariant: "§15.7 log not recovered",
    }
}

impl Db {
    /// The dimension.
    pub fn d(&self) -> usize {
        self.gens.d()
    }

    /// The generators.
    pub fn generators(&self) -> &Generators {
        &self.gens
    }

    /// The key ring the sealer and the rotation participant share (tests and the scanner).
    pub fn key_ring(&self) -> &Arc<KeyRing> {
        &self.ring
    }

    /// `create_collection` (§16.1); the artefact's dimension must be the database's.
    pub fn create_collection(
        &self,
        artefact: &[u8],
        opts: CollectionOptions,
    ) -> Result<CollectionId, Error> {
        if PartitionArtefact::parse(artefact)?.d != self.d() {
            // §6.3, DB-64: a failed artefact check names the check (WrongDimension is §4.1's).
            return Err(Error::IntegrityViolation {
                invariant: "§6.3 artefact d",
            });
        }
        self.engine.create_collection(artefact, opts)
    }

    /// `insert` (§15.1, §16.1): the record's `database_lsn` and where it landed.
    pub fn insert(
        &self,
        cid: CollectionId,
        mut req: InsertRequest<InsertCredential>,
    ) -> Result<(u64, Placement), Error> {
        // §15.1 step 2: the signature is checked over the collection inserted into.
        req.credential.collection_id = *cid.as_bytes();
        let r = self.engine.insert(cid, req)?;
        let lsn = log_output(&r.outputs)
            .and_then(|b| <[u8; 8]>::try_from(b).ok())
            .map(u64::from_be_bytes)
            .ok_or(Error::IntegrityViolation {
                invariant: "§15.1 step 9",
            })?;
        Ok((lsn, r.placement))
    }

    fn outcome(&self, o: DeleteOutcome) -> Result<Deleted, Error> {
        match o {
            DeleteOutcome::AlreadyAbsent => Ok(Deleted::AlreadyAbsent),
            DeleteOutcome::Deleted { outputs } => {
                let certificate = log_output(&outputs)
                    .ok_or(Error::IntegrityViolation {
                        invariant: "§15.3 step 9",
                    })?
                    .to_vec();
                let database_lsn = Certificate::parse(&certificate, self.d())
                    .map_err(|_| Error::IntegrityViolation {
                        invariant: "§11.1 certificate",
                    })?
                    .database_lsn;
                Ok(Deleted::Deleted {
                    database_lsn,
                    certificate,
                })
            }
        }
    }

    /// `delete` (§15.3, §16.1): returns once the old key is erased (§13.4 phase C).
    pub fn delete(&self, cid: CollectionId, record_id: &str) -> Result<Deleted, Error> {
        let o = self.engine.delete(cid, record_id)?;
        self.outcome(o)
    }

    /// `delete_user` (§15.3): one transaction; the certificates chain.
    pub fn delete_user(
        &self,
        cid: CollectionId,
        record_ids: &[&str],
    ) -> Result<Vec<Deleted>, Error> {
        self.engine
            .delete_user(cid, record_ids)?
            .into_iter()
            .map(|o| self.outcome(o))
            .collect()
    }

    /// `certificate(database_lsn)` (§16.1).
    pub fn certificate(&self, lsn: u64) -> Result<Option<Vec<u8>>, Error> {
        self.log
            .with(|l| l.certificate(lsn))
            .ok_or_else(not_recovered)?
    }

    /// `latest_log_checkpoint` (§16.1), with its cosignatures.
    pub fn latest_log_checkpoint(&self) -> Result<Witnessed, Error> {
        self.log
            .with(|l| l.checkpoints().last().cloned())
            .ok_or_else(not_recovered)?
            .ok_or(Error::IntegrityViolation {
                invariant: "DB-79 genesis checkpoint",
            })
    }

    /// `inclusion_proof(leaf_index, tree_size)` (§16.1, RFC 9162).
    pub fn inclusion_proof(
        &self,
        leaf_index: u64,
        tree_size: u64,
    ) -> Result<Option<Vec<Hash>>, Error> {
        self.log
            .with(|l| l.tree().inclusion_proof(leaf_index, tree_size))
            .ok_or_else(not_recovered)
    }

    /// `consistency_proof(old_size, new_size)` (§16.1, RFC 9162).
    pub fn consistency_proof(
        &self,
        old_size: u64,
        new_size: u64,
    ) -> Result<Option<Vec<Hash>>, Error> {
        self.log
            .with(|l| l.tree().consistency_proof(old_size, new_size))
            .ok_or_else(not_recovered)
    }

    /// The committed log for an auditor (DB-86), as JSON: `{"version", "leaves", "placements",
    /// "checkpoints"}` (Part 3's format).
    pub fn export_log(&self) -> Result<String, Error> {
        let e = self.log.with(|l| l.export()).ok_or_else(not_recovered)??;
        let hex = |b: &[u8]| b.iter().map(|x| format!("{x:02x}")).collect::<String>();
        let placements: Vec<serde_json::Value> = e
            .placements
            .iter()
            .map(|p| {
                serde_json::json!({
                    "group": p.group.as_text(),
                    "flush": p.flush.map(|f| f.as_text()),
                })
            })
            .collect();
        Ok(serde_json::json!({
            "version": 1,
            "leaves": e.leaves.iter().map(|l| hex(l)).collect::<Vec<_>>(),
            "placements": placements,
            "checkpoints": e.checkpoints.iter().map(|w| hex(&w.to_bytes())).collect::<Vec<_>>(),
        })
        .to_string())
    }

    /// The verifier's trust anchors as of now (§11.3).
    pub fn anchors(&self) -> Anchors {
        let (operator, witnesses) = self.log.anchors();
        Anchors {
            d: self.d(),
            gdigest: *self.gens.gdigest(),
            operator,
            witnesses,
        }
    }
}

/// How to open a database on real directories.
#[derive(Clone, Debug)]
pub struct OpenOptions {
    /// The data directory (created if missing).
    pub data_dir: PathBuf,
    /// The key directory (created if missing).
    pub key_dir: PathBuf,
    /// The dimension (§2.2).
    pub d: usize,
    /// The development-only overrides of §12.8–12.9; each one used is reported.
    pub overrides: Overrides,
    /// The configuration file whose SHA-256 is recorded in every storage checkpoint (§18).
    pub config_file: Option<PathBuf>,
    /// Abort (production) or poison (tests).
    pub on_failure: FailurePolicy,
}

impl OpenOptions {
    /// Defaults: d = 384, abort on failure, every startup check enforced.
    pub fn new(data_dir: impl Into<PathBuf>, key_dir: impl Into<PathBuf>) -> Self {
        Self {
            data_dir: data_dir.into(),
            key_dir: key_dir.into(),
            d: 384,
            overrides: Overrides::default(),
            config_file: None,
            on_failure: FailurePolicy::Abort,
        }
    }
}

/// An open database on real directories, with its lock and what the startup checks found.
pub struct Opened {
    /// The database.
    pub db: Db,
    /// `ENGINE.lock`, held while this value lives.
    pub lock: EngineLock,
    /// The startup checks that failed and were overridden (recorded in every ledger entry).
    pub overridden: Vec<&'static str>,
    /// Whether the process's memory is locked (§12.8, DB-93).
    pub memory_locked: bool,
    /// `data/ENGINE.lock` and the (device, inode) of the file this process locked (§12.9, G-42).
    lock_file: PathBuf,
    lock_id: (u64, u64),
    /// Set by the first `IntegrityViolation`: the engine stops serving (§17).
    stopped: AtomicBool,
}

fn file_id(path: &std::path::Path) -> Option<(u64, u64)> {
    use std::os::unix::fs::MetadataExt;
    std::fs::metadata(path).ok().map(|m| (m.dev(), m.ino()))
}

impl Opened {
    /// Runs one call on the open database. After an `IntegrityViolation` no call is served
    /// (§17); a data directory whose `ENGINE.lock` is no longer the file this process locked
    /// (another process replaced it) is never written again (§12.9, G-42).
    pub fn serve<T>(&self, f: impl FnOnce(&Db) -> Result<T, Error>) -> Result<T, Error> {
        self.alive()?;
        let r = f(&self.db);
        if matches!(r, Err(Error::IntegrityViolation { .. })) {
            self.stopped.store(true, Ordering::SeqCst);
        }
        r
    }

    fn alive(&self) -> Result<(), Error> {
        if self.stopped.load(Ordering::SeqCst) {
            return Err(Error::IntegrityViolation {
                invariant: "§17 the engine stopped serving",
            });
        }
        if file_id(&self.lock_file) != Some(self.lock_id) {
            self.stopped.store(true, Ordering::SeqCst);
            return Err(Error::IntegrityViolation {
                invariant: "§12.9 data directory replaced",
            });
        }
        Ok(())
    }

    /// A clean shutdown: a storage checkpoint (§12.4), then `ENGINE.lock` is released. After an
    /// `IntegrityViolation`, or in a replaced data directory, nothing is written: the lock is
    /// released and the error returned (§17, §12.9).
    pub fn close(self) -> Result<(), Error> {
        let alive = self.alive();
        let Self { db, lock, .. } = self;
        let r = alive.and_then(|()| db.engine.close());
        drop(lock);
        r
    }
}

fn io_err(check: &'static str) -> impl Fn(std::io::Error) -> Error {
    move |_| Error::PlatformUnsafe { check }
}

fn private(path: &std::path::Path, check: &'static str) -> Result<(), Error> {
    use std::os::unix::fs::PermissionsExt;
    if path.exists() {
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
            .map_err(io_err(check))?;
    }
    Ok(())
}

/// Opens (recovering, or creating) the database on real files: the startup checks (§12.8–12.9),
/// the `mlock` provider, `ENGINE.lock`, the engine; `SECRETS`, `WITNESSES` and `KEYS` stay mode
/// 0600 (§14.1).
pub fn open(o: &OpenOptions) -> Result<Opened, Error> {
    std::fs::create_dir_all(&o.data_dir).map_err(io_err("§12.9 data directory"))?;
    std::fs::create_dir_all(&o.key_dir).map_err(io_err("§14.1 key directory"))?;
    // §15.7 steps 1 and 4: ENGINE.lock first, then the platform checks and the memory hygiene.
    let lock = EngineLock::acquire(&o.data_dir)?;
    let lock_file = o.data_dir.join(sever_engine::platform::LOCK_FILE);
    let lock_id = file_id(&lock_file).ok_or(Error::PlatformUnsafe {
        check: "§12.9 ENGINE.lock",
    })?;
    let report = sever_platform::startup(&LinuxProbe, &o.data_dir, &o.key_dir, o.overrides)?;
    let memory_locked = report.locked.is_some();
    if let Some(locked) = &report.locked {
        // DB-50: refused when a provider is already fixed (an earlier open in this process, or a
        // secret made before it); the memory is locked either way (DB-93).
        let _ = sever_types::install_provider(Box::new(MlockProvider::new(locked)));
    }
    let config_hash = match &o.config_file {
        Some(p) => {
            use sha2::Digest;
            sha2::Sha256::digest(std::fs::read(p).map_err(io_err("§18 configuration file"))?).into()
        }
        None => [0; 32],
    };
    let vfs = |dir: &std::path::Path, check: &'static str| -> Result<Arc<dyn Vfs>, Error> {
        Ok(Arc::new(
            PosixVfs::new(dir).map_err(|_| Error::PlatformUnsafe { check })?,
        ))
    };
    let data = vfs(&o.data_dir, "§12.9 data directory")?;
    let keys_vfs = vfs(&o.key_dir, "§14.1 key directory")?;
    let kd = o.key_dir.clone();
    let mut s = Settings::new(o.d);
    s.engine = EngineConfig {
        on_failure: o.on_failure,
        config_hash,
        ..EngineConfig::default()
    };
    s.after_secrets_write = Some(Box::new(move || {
        private(&kd.join(keys::SECRETS), "§14.1 SECRETS permissions")
    }));
    let db = open_on(data, keys_vfs, s)?;
    private(&o.key_dir.join(keys::SECRETS), "§14.1 SECRETS permissions")?;
    private(
        &o.key_dir.join(witnesses::WITNESS_FILE),
        "§14.1 WITNESSES permissions",
    )?;
    private(
        &o.key_dir.join(sever_platform::KEYS_FILE),
        "§14.1 KEYS permissions",
    )?;
    Ok(Opened {
        db,
        lock,
        overridden: report.overridden,
        memory_locked,
        lock_file,
        lock_id,
        stopped: AtomicBool::new(false),
    })
}

#[cfg(test)]
mod tests;
