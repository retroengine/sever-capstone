//! `sever-p3`: Part 3's composition root (Build 3-4 §1.4):
//! `Engine<CommitmentExtension, PlaintextSealer, (LogParticipant)>` with the generators
//! self-checked at startup (§9.2, INV-10), the operator's keys durable in `SECRETS`
//! ([`keys`]), five simulated witnesses with durable memory ([`witnesses`]), and the API of
//! §16.1 that Part 3 adds: inserts return their `database_lsn`, deletions their certificate, and
//! certificates, checkpoints and proofs can be read back. The verifier's trust anchors are
//! exported from here ([`Anchors`]).
//!
//! Like `sever-p2`, this is where Part 3 meets the operating system: [`open`] adds the platform
//! checks, `ENGINE.lock`, the configuration hash and `SECRETS` mode 0600 (§12.9, §14.1).

pub mod keys;
pub mod witnesses;

use std::path::PathBuf;
use std::sync::Arc;

use sever_cert::Certificate;
use sever_cert::participant::{LOG_PARTICIPANT_ID, LogHandle, LogParticipant, LogParts};
use sever_commit::{CommitmentExtension, InsertCredential, LeafLog};
use sever_crypto::{Generators, self_check};
use sever_engine::{
    CollectionOptions, DeleteOutcome, Engine, EngineConfig, EngineLock, FailurePolicy,
    InsertRequest, PlatformReport,
};
use sever_format::WalRecord;
use sever_index::Placement;
use sever_log::keys::{Keyring, OperatorKeys};
use sever_log::merkle::Hash;
use sever_log::store::{LogStoreConfig, Witnessed};
use sever_partition::PartitionArtefact;
use sever_txn::{Clock, PlaintextSealer, PreTxn, SystemClock, TxnDraft, TxnKind, TxnParticipant};
use sever_types::{CollectionId, Error};
use sever_vfs::{PosixVfs, Vfs};

use crate::keys::OperatorStore;

/// Part 3's engine.
pub type P3Engine = Engine<CommitmentExtension, PlaintextSealer>;

/// What a Part 3 database is opened with.
pub struct Settings {
    /// The vector dimension of every collection (§2.2: 384 in v1; the fixtures use 16).
    pub d: usize,
    /// EP-9 (checkpoint timestamps, epochs).
    pub clock: Arc<dyn Clock>,
    /// The engine's settings (segment sizes, checkpoint cadence, failure policy, config hash).
    pub engine: EngineConfig,
    /// Segment size of the log's stores.
    pub log_segment_bytes: u64,
    /// Called after every rewrite of `SECRETS`.
    pub after_secrets_write: Option<keys::AfterWrite>,
}

impl Settings {
    /// v1 settings for dimension `d`: the system clock, Part 2's engine defaults.
    pub fn new(d: usize) -> Self {
        Self {
            d,
            clock: Arc::new(SystemClock::default()),
            engine: EngineConfig::default(),
            log_segment_bytes: 64 * 1024 * 1024,
            after_secrets_write: None,
        }
    }
}

/// An open Part 3 database.
pub struct Db {
    /// The engine.
    pub engine: P3Engine,
    /// The log, as the participant keeps it.
    pub log: Arc<LogHandle>,
    gens: Arc<Generators>,
}

impl core::fmt::Debug for Db {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "Db(d = {})", self.gens.d())
    }
}

/// The result of one deletion (§16.1).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Deleted {
    /// §5.4: the record was not live; nothing changed.
    AlreadyAbsent,
    /// Deleted: its certificate and the index of its delete leaf.
    Deleted {
        /// The deletion's leaf index (tag 10).
        database_lsn: u64,
        /// The certificate (§11.1).
        certificate: Vec<u8>,
    },
}

/// The verifier's trust anchors (§11.3): the operator's and each witness's public keys by epoch,
/// and the generator digest of `d` (§9.6).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Anchors {
    /// The dimension.
    pub d: usize,
    /// `gdigest` (§9.6).
    pub gdigest: [u8; 64],
    /// The operator's keys by epoch.
    pub operator: Keyring,
    /// Each witness's keys by epoch, by witness index.
    pub witnesses: Vec<Keyring>,
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn ring_json(r: &Keyring) -> serde_json::Value {
    serde_json::Value::Object(
        r.iter()
            .map(|(e, k)| (e.to_string(), serde_json::Value::String(hex(k))))
            .collect(),
    )
}

impl Anchors {
    /// `{"d", "gdigest", "operator": {epoch: key}, "witnesses": [{epoch: key}, …]}`.
    pub fn to_json(&self) -> String {
        serde_json::json!({
            "d": self.d,
            "gdigest": hex(&self.gdigest),
            "operator": ring_json(&self.operator),
            "witnesses": self.witnesses.iter().map(ring_json).collect::<Vec<_>>(),
        })
        .to_string()
    }
}

/// EP-7 wrapper around the log participant: everything is forwarded.
struct Guarded(LogParticipant);

impl TxnParticipant<CommitmentExtension> for Guarded {
    fn id(&self) -> u16 {
        self.0.id()
    }
    fn owned_types(&self) -> &[sever_format::RecordType] {
        self.0.owned_types()
    }
    fn pre_transaction(
        &mut self,
        kind: TxnKind,
        c: &CollectionId,
    ) -> Result<Option<PreTxn>, Error> {
        self.0.pre_transaction(kind, c)
    }
    fn prepare(&mut self, d: &mut TxnDraft<'_, CommitmentExtension>) -> Result<(), Error> {
        self.0.prepare(d)?;
        // SB-21: the deletion's leaf and certificate join the log before its COMMIT.
        #[cfg(feature = "sabotage-SB-21")]
        if d.kind == TxnKind::Delete {
            self.0.sync_stores()?;
            self.0.after_commit()?;
        }
        Ok(())
    }
    fn sync_stores(&mut self) -> Result<(), Error> {
        self.0.sync_stores()
    }
    fn phase_a(&mut self) -> Result<(), Error> {
        self.0.phase_a()
    }
    fn abort(&mut self) {
        self.0.abort();
    }
    fn after_commit(&mut self) -> Result<(), Error> {
        self.0.after_commit()
    }
    fn replay(&mut self, r: &WalRecord) -> Result<(), Error> {
        self.0.replay(r)
    }
    fn recover(&mut self) -> Result<(), Error> {
        self.0.recover()
    }
    fn check_invariants(&self) -> Result<(), Error> {
        self.0.check_invariants()
    }
    fn on_drop_collection(&mut self, c: &CollectionId) -> Result<(), Error> {
        self.0.on_drop_collection(c)
    }
}

/// Opens (recovering, or creating) a Part 3 database on the data directory `data` and the key
/// directory `keys`: the generators of `d` are derived and self-checked (§9.2), the operator's
/// keys and the witnesses' memory are loaded, then the engine recovers with the log participant.
pub fn open_on(data: Arc<dyn Vfs>, keys: Arc<dyn Vfs>, s: Settings) -> Result<Db, Error> {
    let gens = Arc::new(Generators::derive(s.d).map_err(|_| Error::WrongDimension)?);
    self_check(&gens).map_err(|_| Error::IntegrityViolation {
        invariant: "INV-10",
    })?;
    let operator = OperatorStore::load(Arc::clone(&keys), s.clock.now_ms(), s.after_secrets_write)?;
    let witnesses = witnesses::load(
        Arc::clone(&keys),
        operator.genesis_ms(),
        operator.published(),
    )?;
    let (participant, log) = LogParticipant::new(
        Arc::clone(&data),
        LogParts {
            gens: Arc::clone(&gens),
            clock: s.clock,
            operator: Box::new(operator),
            witnesses,
            store: LogStoreConfig {
                sealer_id: 0,
                segment_bytes: s.log_segment_bytes,
            },
        },
    );
    let ext = CommitmentExtension::new(Arc::clone(&gens), Arc::clone(&log) as Arc<dyn LeafLog>);
    let engine = Engine::open(
        data,
        keys,
        PlaintextSealer,
        ext,
        vec![Box::new(Guarded(participant))],
        s.engine,
    )?;
    Ok(Db { engine, log, gens })
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

    /// `create_collection` (§16.1); the artefact's dimension must be the database's.
    pub fn create_collection(
        &self,
        artefact: &[u8],
        opts: CollectionOptions,
    ) -> Result<CollectionId, Error> {
        if PartitionArtefact::parse(artefact)?.d != self.d() {
            return Err(Error::WrongDimension);
        }
        self.engine.create_collection(artefact, opts)
    }

    /// `insert` (§15.1, §16.1): the record's `database_lsn` and where it landed.
    pub fn insert(
        &self,
        cid: CollectionId,
        mut req: InsertRequest<InsertCredential>,
    ) -> Result<(u64, Placement), Error> {
        // §15.1 step 2: the signature is checked over the collection inserted into, so one signed
        // for another collection fails as BadUserSignature (EP-1's admit does not see `cid`).
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

    /// `delete` (§15.3, §16.1).
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

    /// `certificate(database_lsn)` (§16.1, §15.4: retrievable by `database_lsn`).
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

    /// The committed log for an auditor (DB-86; §11.3 "what it does not prove"), as JSON:
    /// `{"leaves": [hex], "placements": [{"group": id, "flush": id | null}], "checkpoints": [hex]}`,
    /// a checkpoint being `checkpoint (116) ‖ u8 count ‖ count × cosignature (69)`.
    pub fn export_log(&self) -> Result<String, Error> {
        let e = self.log.with(|l| l.export()).ok_or_else(not_recovered)??;
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
    /// Development only: allow a data directory that is not ext4 or XFS (§12.9; recorded).
    pub allow_unsafe_fs: bool,
    /// The configuration file whose SHA-256 is recorded in every storage checkpoint (§18).
    pub config_file: Option<PathBuf>,
    /// Abort (production) or poison (tests).
    pub on_failure: FailurePolicy,
}

impl OpenOptions {
    /// Defaults: d = 384, abort on failure, the platform checks enforced.
    pub fn new(data_dir: impl Into<PathBuf>, key_dir: impl Into<PathBuf>) -> Self {
        Self {
            data_dir: data_dir.into(),
            key_dir: key_dir.into(),
            d: 384,
            allow_unsafe_fs: false,
            config_file: None,
            on_failure: FailurePolicy::Abort,
        }
    }
}

/// An open database on real directories, with its lock and platform report.
pub struct Opened {
    /// The database.
    pub db: Db,
    /// `ENGINE.lock`, held while this value lives.
    pub lock: EngineLock,
    /// The §12.9 report.
    pub platform: PlatformReport,
}

fn io_err(check: &'static str) -> impl Fn(std::io::Error) -> Error {
    move |_| Error::PlatformUnsafe { check }
}

fn secrets_0600(key_dir: &std::path::Path) -> Result<(), Error> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(
        key_dir.join(keys::SECRETS),
        std::fs::Permissions::from_mode(0o600),
    )
    .map_err(io_err("§14.1 SECRETS permissions"))
}

/// Opens (recovering, or creating) the database on real files: platform checks, lock, engine;
/// `SECRETS` and `WITNESSES` stay mode 0600 (§14.1).
pub fn open(o: &OpenOptions) -> Result<Opened, Error> {
    std::fs::create_dir_all(&o.data_dir).map_err(io_err("§12.9 data directory"))?;
    std::fs::create_dir_all(&o.key_dir).map_err(io_err("§14.1 key directory"))?;
    let platform = sever_engine::check_data_dir(&o.data_dir, o.allow_unsafe_fs)?;
    let lock = EngineLock::acquire(&o.data_dir)?;
    let config_hash = match &o.config_file {
        Some(p) => {
            use sha2::Digest;
            sha2::Sha256::digest(std::fs::read(p).map_err(io_err("§18 configuration file"))?).into()
        }
        None => [0; 32],
    };
    let data: Arc<dyn Vfs> =
        Arc::new(
            PosixVfs::new(&o.data_dir).map_err(|_| Error::PlatformUnsafe {
                check: "§12.9 data directory",
            })?,
        );
    let keys: Arc<dyn Vfs> =
        Arc::new(
            PosixVfs::new(&o.key_dir).map_err(|_| Error::PlatformUnsafe {
                check: "§14.1 key directory",
            })?,
        );
    let kd = o.key_dir.clone();
    let mut s = Settings::new(o.d);
    s.engine = EngineConfig {
        on_failure: o.on_failure,
        config_hash,
        ..EngineConfig::default()
    };
    s.after_secrets_write = Some(Box::new(move || secrets_0600(&kd)));
    let db = open_on(data, keys, s)?;
    secrets_0600(&o.key_dir)?;
    if o.key_dir.join(witnesses::WITNESS_FILE).exists() {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(
            o.key_dir.join(witnesses::WITNESS_FILE),
            std::fs::Permissions::from_mode(0o600),
        )
        .map_err(io_err("§14.1 WITNESSES permissions"))?;
    }
    Ok(Opened { db, lock, platform })
}

pub use sever_p2::{cid_hex, parse_cid};

#[cfg(test)]
mod tests;
