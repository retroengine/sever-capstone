//! The log's durable side (§10.5, §14.1, §14.6, §14.8): the append stores of the leaves, leaf
//! hashes, log checkpoints and certificates, the log's WAL records, and recovery.
//!
//! Which bytes are committed (DB-81). Insert leaves and certificates are appended and `fsync`ed
//! before the `COMMIT` that covers them (§14.6, §14.8), so a crash can leave uncommitted ones; leaf
//! hashes and log checkpoints are appended only after the `COMMIT` (phase C), so their stores hold
//! committed entries only, in order, and the WAL tail restores any that a crash cut off. A storage
//! checkpoint (§12.4) truncates the WAL only after a transaction's phase C, so nothing committed is
//! ever in neither place. Each hash entry records its leaf's type; for a leaf index, the committed
//! insert leaf or certificate is the last entry with that key (a later transaction reuses the key
//! of one that never committed, and never the key of one that did).

use std::collections::BTreeMap;
use std::sync::Arc;

use sever_appendstore::{AppendStore, FileStore, StoreConfig, StoreRef};
use sever_format::{FileHeader, RecordType, StoreRecord, WalRecord};
use sever_types::Error;
use sever_vfs::{OpenMode, Vfs, VfsError, durable, read_exact_at};
use sha2::{Digest, Sha256};

use crate::checkpoint::{CHECKPOINT_LEN, COSIGNATURE_LEN, Cosignature, LogCheckpoint};
use crate::leaf::{
    INSERT_LEAF_LEN, InsertLeaf, LEAF_DELETE, LEAF_INSERT, PLACEMENT_LEN, Placement, delete_leaf,
};
use crate::merkle::{Hash, MerkleTree, leaf_hash};

/// The log's directory (§14.1).
pub const LOG_DIR: &str = "log";
/// Insert-leaf bytes, keyed by leaf index.
pub const LEAVES_DIR: &str = "log/leaves";
/// Every leaf's type and hash, in order, keyed by leaf index.
pub const HASHES_DIR: &str = "log/hashes";
/// Every log checkpoint with its cosignatures, keyed by tree size.
pub const CHECKPOINTS_DIR: &str = "log/checkpoints";
/// Certificates, keyed by `database_lsn` (§14.1).
pub const CERTS_DIR: &str = "certs";

fn inv(rule: &'static str) -> Error {
    Error::IntegrityViolation { invariant: rule }
}

fn io(_: VfsError) -> Error {
    Error::DurabilityFailure
}

/// A log checkpoint with the cosignatures collected for it (`LOG_CHECKPOINT`, §14.6).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Witnessed {
    /// The checkpoint.
    pub checkpoint: LogCheckpoint,
    /// Its cosignatures (possibly fewer than the threshold).
    pub cosignatures: Vec<Cosignature>,
}

impl Witnessed {
    /// `checkpoint (116) ‖ u8 count ‖ count × cosignature (69)`.
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut out = self.checkpoint.to_bytes().to_vec();
        out.push(u8::try_from(self.cosignatures.len()).unwrap_or(u8::MAX));
        for c in &self.cosignatures {
            out.extend_from_slice(&c.to_bytes());
        }
        out
    }

    /// Strict parse.
    pub fn parse(b: &[u8]) -> Option<Self> {
        let (cp, rest) = b.split_first_chunk::<CHECKPOINT_LEN>()?;
        let (&n, rest) = rest.split_first()?;
        if rest.len() != COSIGNATURE_LEN * usize::from(n) {
            return None;
        }
        Some(Self {
            checkpoint: LogCheckpoint::parse(cp)?,
            cosignatures: rest
                .chunks_exact(COSIGNATURE_LEN)
                .map(Cosignature::parse)
                .collect::<Option<_>>()?,
        })
    }
}

/// One of the log's WAL records (§14.6; DB-81 puts the leaf index first in `LOG_LEAF`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LogRecord {
    /// `LOG_LEAF`: `u64be leaf_index ‖ leaf hash ‖ placement (64, DB-86) ‖` the 209-byte insert leaf
    /// (insert leaves only).
    Leaf {
        /// Its index.
        index: u64,
        /// Its RFC 9162 leaf hash.
        hash: Hash,
        /// Where its record went (DB-86).
        placement: Placement,
        /// The insert leaf's bytes, or `None` for a delete leaf.
        insert: Option<[u8; INSERT_LEAF_LEN]>,
    },
    /// `LOG_CHECKPOINT`: the checkpoint with its cosignatures.
    Checkpoint(Witnessed),
    /// `CERT_REF`: `database_lsn ‖ u64be segment ‖ u64be offset ‖ u32be length ‖ SHA-256`.
    CertRef {
        /// The deletion's leaf index.
        lsn: u64,
        /// Where the certificate lies in the certificate store.
        at: StoreRef,
        /// SHA-256 of the certificate.
        sha256: [u8; 32],
    },
}

impl LogRecord {
    /// The WAL record type and payload.
    pub fn encode(&self) -> (RecordType, Vec<u8>) {
        match self {
            Self::Leaf {
                index,
                hash,
                placement,
                insert,
            } => {
                let mut p = index.to_be_bytes().to_vec();
                p.extend_from_slice(hash);
                p.extend_from_slice(&placement.to_bytes());
                if let Some(leaf) = insert {
                    p.extend_from_slice(leaf);
                }
                (RecordType::LogLeaf, p)
            }
            Self::Checkpoint(w) => (RecordType::LogCheckpoint, w.to_bytes()),
            Self::CertRef { lsn, at, sha256 } => {
                let mut p = lsn.to_be_bytes().to_vec();
                p.extend_from_slice(&at.segment.to_be_bytes());
                p.extend_from_slice(&at.offset.to_be_bytes());
                p.extend_from_slice(&at.len.to_be_bytes());
                p.extend_from_slice(sha256);
                (RecordType::CertRef, p)
            }
        }
    }

    /// Strict decoding of a WAL record the log owns.
    pub fn decode(r: &WalRecord) -> Result<Self, Error> {
        let p = r.payload.as_slice();
        match r.ty {
            RecordType::LogLeaf => {
                let (index, rest) = p.split_first_chunk::<8>().ok_or(inv("§14.6 LOG_LEAF"))?;
                let (hash, rest) = rest
                    .split_first_chunk::<32>()
                    .ok_or(inv("§14.6 LOG_LEAF"))?;
                let (placement, rest) = rest
                    .split_first_chunk::<PLACEMENT_LEN>()
                    .ok_or(inv("§14.6 LOG_LEAF"))?;
                let placement = Placement::parse(placement).map_err(|_| inv("§14.6 LOG_LEAF"))?;
                let insert = match rest.len() {
                    0 => None,
                    INSERT_LEAF_LEN => Some(
                        <[u8; INSERT_LEAF_LEN]>::try_from(rest)
                            .map_err(|_| inv("§14.6 LOG_LEAF"))?,
                    ),
                    _ => return Err(inv("§14.6 LOG_LEAF")),
                };
                Ok(Self::Leaf {
                    index: u64::from_be_bytes(*index),
                    hash: *hash,
                    placement,
                    insert,
                })
            }
            RecordType::LogCheckpoint => Witnessed::parse(p)
                .map(Self::Checkpoint)
                .ok_or(inv("§14.6 LOG_CHECKPOINT")),
            RecordType::CertRef => {
                let b: &[u8; 60] = p.try_into().map_err(|_| inv("§14.6 CERT_REF"))?;
                let (lsn, rest) = b.split_first_chunk::<8>().ok_or(inv("§14.6 CERT_REF"))?;
                let (seg, rest) = rest.split_first_chunk::<8>().ok_or(inv("§14.6 CERT_REF"))?;
                let (off, rest) = rest.split_first_chunk::<8>().ok_or(inv("§14.6 CERT_REF"))?;
                let (len, sha) = rest.split_first_chunk::<4>().ok_or(inv("§14.6 CERT_REF"))?;
                Ok(Self::CertRef {
                    lsn: u64::from_be_bytes(*lsn),
                    at: StoreRef {
                        segment: u64::from_be_bytes(*seg),
                        offset: u64::from_be_bytes(*off),
                        len: u32::from_be_bytes(*len),
                    },
                    sha256: sha.try_into().map_err(|_| inv("§14.6 CERT_REF"))?,
                })
            }
            _ => Err(inv("§14.6 not a log record")),
        }
    }
}

/// Settings of the log's stores.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LogStoreConfig {
    /// The sealer (DB-48; 0 = plaintext until Part 4).
    pub sealer_id: u16,
    /// Segment size of each store.
    pub segment_bytes: u64,
}

struct Stores {
    leaves: FileStore,
    hashes: FileStore,
    checkpoints: FileStore,
    certs: FileStore,
}

/// What one transaction staged, applied in memory only after its `COMMIT`.
#[derive(Debug, Default)]
struct Pending {
    leaves: Vec<(Hash, Option<StoreRef>, Placement)>,
    certs: Vec<(u64, StoreRef)>,
    checkpoints: Vec<Witnessed>,
}

/// The log's committed state and its stores.
pub struct LogStore {
    vfs: Arc<dyn Vfs>,
    stores: Stores,
    tree: MerkleTree,
    /// For each committed leaf: where its insert leaf lies (`None` for a delete leaf).
    inserts: Vec<Option<StoreRef>>,
    /// Committed certificates by `database_lsn`.
    certs: BTreeMap<u64, StoreRef>,
    /// Committed log checkpoints, by tree size (non-decreasing: an unwitnessed one may be issued
    /// again at the same size); the first is the genesis (DB-79).
    checkpoints: Vec<Witnessed>,
    /// Insert leaves and certificates in the stores at keys not (yet) committed, for replay.
    spare_inserts: BTreeMap<u64, StoreRef>,
    pending: Pending,
}

impl core::fmt::Debug for LogStore {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(
            f,
            "LogStore({} leaves, {} checkpoints)",
            self.tree.size(),
            self.checkpoints.len()
        )
    }
}

fn store_cfg(cfg: &LogStoreConfig, dir: &str) -> StoreConfig {
    StoreConfig {
        dir: dir.into(),
        sealer_id: cfg.sealer_id,
        segment_bytes: cfg.segment_bytes,
    }
}

fn exists(vfs: &dyn Vfs, dir: &str) -> Result<bool, Error> {
    match vfs.list(dir) {
        Ok(_) => Ok(true),
        Err(VfsError::NotFound) => Ok(false),
        Err(e) => Err(io(e)),
    }
}

fn remove_tree(vfs: &dyn Vfs, path: &str) -> Result<(), Error> {
    match vfs.unlink(path) {
        Ok(()) | Err(VfsError::NotFound) => return Ok(()),
        Err(VfsError::IsADirectory) => {}
        Err(e) => return Err(io(e)),
    }
    for name in vfs.list(path).map_err(io)? {
        remove_tree(vfs, &format!("{path}/{name}"))?;
    }
    vfs.remove_dir(path).map_err(io)
}

/// One scanned store record: key, reference, and the value if asked for.
type Scanned = (u64, StoreRef, Option<Vec<u8>>);

/// Every record of a store, in order.
fn scan(vfs: &dyn Vfs, dir: &str, values: bool) -> Result<Vec<Scanned>, Error> {
    let mut seqs: Vec<u64> = vfs
        .list(dir)
        .map_err(io)?
        .iter()
        .filter_map(|n| n.strip_suffix(".store").and_then(|d| d.parse().ok()))
        .collect();
    seqs.sort_unstable();
    let mut out = Vec::new();
    for seq in seqs {
        let f = vfs
            .open(&format!("{dir}/{seq:020}.store"), OpenMode::Existing)
            .map_err(io)?;
        let size = f.len().map_err(io)?;
        let mut off = FileHeader::LEN as u64;
        while off + StoreRecord::OVERHEAD as u64 <= size {
            let mut head = [0u8; 12];
            read_exact_at(f.as_ref(), off, &mut head).map_err(io)?;
            let (key, len) = head.split_at(8);
            let key = u64::from_be_bytes(key.try_into().map_err(|_| inv("§14.8 store record"))?);
            let len = u32::from_be_bytes(len.try_into().map_err(|_| inv("§14.8 store record"))?);
            let total = StoreRecord::OVERHEAD as u64 + u64::from(len);
            if off + total > size {
                break; // a torn tail (FileStore::open cuts it on the newest segment)
            }
            let value = if values {
                let mut buf = vec![0u8; usize::try_from(total).map_err(|_| inv("§14.8"))?];
                read_exact_at(f.as_ref(), off, &mut buf).map_err(io)?;
                let (rec, _) = StoreRecord::parse_next(&buf).ok_or(inv("§14.8 store record"))?;
                Some(rec.bytes)
            } else {
                None
            };
            out.push((
                key,
                StoreRef {
                    segment: seq,
                    offset: off,
                    len,
                },
                value,
            ));
            off += total;
        }
    }
    Ok(out)
}

/// A hash-store entry (§10.5, DB-81, DB-86): `leaf type ‖ leaf hash ‖ placement`.
fn hash_entry_bytes(ty: u8, hash: &Hash, placement: &Placement) -> Vec<u8> {
    let mut v = vec![ty];
    v.extend_from_slice(hash);
    v.extend_from_slice(&placement.to_bytes());
    v
}

/// Parses a hash-store entry strictly.
fn hash_entry(v: &[u8]) -> Result<(u8, Hash, Placement), Error> {
    let bad = || inv("§10.5 hash entry");
    let (&ty, rest) = v.split_first().ok_or_else(bad)?;
    let (hash, rest) = rest.split_first_chunk::<32>().ok_or_else(bad)?;
    let placement = Placement::parse(rest).map_err(|_| bad())?;
    Ok((ty, *hash, placement))
}

/// The whole committed log, for an auditor (DB-86): every leaf's bytes (the insert leaf, or
/// `0x02 ‖ certificate`), every leaf's placement, and every checkpoint with its cosignatures.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LogExport {
    /// Leaf `i`'s bytes, in order.
    pub leaves: Vec<Vec<u8>>,
    /// Leaf `i`'s placement.
    pub placements: Vec<Placement>,
    /// The committed checkpoints, the genesis first.
    pub checkpoints: Vec<Witnessed>,
}

impl LogStore {
    /// Opens the log's stores in the data directory `vfs`, creating them with `genesis` as the
    /// first checkpoint if they do not exist or were left half-created (the genesis checkpoint is
    /// written last, so a log without it has no leaves).
    pub fn open(
        vfs: Arc<dyn Vfs>,
        cfg: LogStoreConfig,
        genesis: &Witnessed,
    ) -> Result<Self, Error> {
        let complete = exists(vfs.as_ref(), CHECKPOINTS_DIR)?
            && !scan(vfs.as_ref(), CHECKPOINTS_DIR, false)?.is_empty();
        if !complete {
            Self::create(&vfs, &cfg, genesis)?;
        }
        let stores = Stores {
            leaves: FileStore::open(Arc::clone(&vfs), store_cfg(&cfg, LEAVES_DIR))?,
            hashes: FileStore::open(Arc::clone(&vfs), store_cfg(&cfg, HASHES_DIR))?,
            checkpoints: FileStore::open(Arc::clone(&vfs), store_cfg(&cfg, CHECKPOINTS_DIR))?,
            certs: FileStore::open(Arc::clone(&vfs), store_cfg(&cfg, CERTS_DIR))?,
        };
        let mut s = Self {
            vfs,
            stores,
            tree: MerkleTree::new(),
            inserts: Vec::new(),
            certs: BTreeMap::new(),
            checkpoints: Vec::new(),
            spare_inserts: BTreeMap::new(),
            pending: Pending::default(),
        };
        s.load()?;
        Ok(s)
    }

    fn create(vfs: &Arc<dyn Vfs>, cfg: &LogStoreConfig, genesis: &Witnessed) -> Result<(), Error> {
        remove_tree(vfs.as_ref(), LOG_DIR)?;
        remove_tree(vfs.as_ref(), CERTS_DIR)?;
        durable::sync_dir(vfs.as_ref(), "").map_err(io)?;
        durable::create_dir(vfs.as_ref(), LOG_DIR).map_err(io)?;
        for dir in [LEAVES_DIR, HASHES_DIR, CERTS_DIR] {
            FileStore::create(Arc::clone(vfs), store_cfg(cfg, dir))?;
        }
        let mut cps = FileStore::create(Arc::clone(vfs), store_cfg(cfg, CHECKPOINTS_DIR))?;
        cps.append(genesis.checkpoint.tree_size, &genesis.to_bytes())?;
        cps.sync()
    }

    fn load(&mut self) -> Result<(), Error> {
        let v = Arc::clone(&self.vfs);
        let mut types = Vec::new();
        for (key, _, value) in scan(v.as_ref(), HASHES_DIR, true)? {
            let value = value.ok_or(inv("§14.8"))?;
            let (ty, hash, _) = hash_entry(&value)?;
            if key != self.tree.size() || !(ty == LEAF_INSERT || ty == LEAF_DELETE) {
                return Err(inv("§10.5 hash store order"));
            }
            self.tree.push_hash(hash);
            types.push(ty);
        }
        for (_, _, value) in scan(v.as_ref(), CHECKPOINTS_DIR, true)? {
            let w = Witnessed::parse(&value.ok_or(inv("§14.8"))?)
                .ok_or(inv("§10.3 checkpoint entry"))?;
            self.push_checkpoint(w)?;
        }
        self.inserts = vec![None; types.len()];
        for (key, at, _) in scan(v.as_ref(), LEAVES_DIR, false)? {
            match types.get(usize::try_from(key).unwrap_or(usize::MAX)) {
                Some(&LEAF_INSERT) => {
                    if let Some(slot) = self
                        .inserts
                        .get_mut(usize::try_from(key).unwrap_or(usize::MAX))
                    {
                        *slot = Some(at); // the last entry with this key wins
                    }
                }
                Some(_) => {}
                None => {
                    self.spare_inserts.insert(key, at);
                }
            }
        }
        for (key, at, _) in scan(v.as_ref(), CERTS_DIR, false)? {
            if types.get(usize::try_from(key).unwrap_or(usize::MAX)) == Some(&LEAF_DELETE) {
                self.certs.insert(key, at);
            }
        }
        Ok(())
    }

    fn push_checkpoint(&mut self, w: Witnessed) -> Result<(), Error> {
        if let Some(last) = self.checkpoints.last() {
            if w.checkpoint.tree_size < last.checkpoint.tree_size {
                return Err(inv("§10.3 checkpoints ascend"));
            }
        }
        self.checkpoints.push(w);
        Ok(())
    }

    // --- reading ---------------------------------------------------------------------------

    /// The committed tree.
    pub fn tree(&self) -> &MerkleTree {
        &self.tree
    }

    /// The committed log checkpoints, ascending; the first is the genesis.
    pub fn checkpoints(&self) -> &[Witnessed] {
        &self.checkpoints
    }

    /// The index the next staged leaf takes.
    pub fn next_index(&self) -> u64 {
        self.tree.size() + self.pending.leaves.len() as u64
    }

    /// The committed insert leaf at `index`, checked against its leaf hash; `None` if that leaf
    /// is not an insert leaf (or does not exist).
    pub fn insert_leaf(&self, index: u64) -> Result<Option<InsertLeaf>, Error> {
        let Some(Some(at)) = usize::try_from(index)
            .ok()
            .and_then(|i| self.inserts.get(i))
        else {
            return Ok(None);
        };
        let rec = self.stores.leaves.read(at)?;
        if rec.key != index || Some(leaf_hash(&rec.bytes)) != self.tree.leaf(index) {
            return Err(inv("§10.5 insert leaf store"));
        }
        InsertLeaf::parse(&rec.bytes)
            .map(Some)
            .map_err(|_| inv("§10.5 insert leaf store"))
    }

    /// The committed certificate of the deletion at `database_lsn`, checked against its leaf hash.
    pub fn certificate(&self, lsn: u64) -> Result<Option<Vec<u8>>, Error> {
        let Some(at) = self.certs.get(&lsn) else {
            return Ok(None);
        };
        let rec = self.stores.certs.read(at)?;
        if rec.key != lsn || Some(leaf_hash(&delete_leaf(&rec.bytes))) != self.tree.leaf(lsn) {
            return Err(inv("§14.8 certificate store"));
        }
        Ok(Some(rec.bytes))
    }

    /// The committed log for an auditor (DB-86), read back from the stores.
    pub fn export(&self) -> Result<LogExport, Error> {
        let mut placements = Vec::new();
        for (key, _, value) in scan(self.vfs.as_ref(), HASHES_DIR, true)? {
            if key != placements.len() as u64 {
                return Err(inv("§10.5 hash store order"));
            }
            placements.push(hash_entry(&value.ok_or(inv("§14.8"))?)?.2);
        }
        let n = self.tree.size();
        if placements.len() as u64 != n {
            return Err(inv("§10.5 hash store"));
        }
        let mut leaves = Vec::new();
        for i in 0..n {
            leaves.push(match (self.insert_leaf(i)?, self.certificate(i)?) {
                (Some(l), None) => l.to_bytes().to_vec(),
                (None, Some(c)) => delete_leaf(&c),
                _ => return Err(inv("§10.5 leaf store")),
            });
        }
        Ok(LogExport {
            leaves,
            placements,
            checkpoints: self.checkpoints.clone(),
        })
    }

    // --- one transaction: stage (prepare), sync (step 3), commit (phase C) or abort ----------

    /// Stages an insert leaf and its placement (DB-86): its bytes join the leaf store; returns its
    /// index and `LOG_LEAF`.
    pub fn stage_insert(
        &mut self,
        leaf: &InsertLeaf,
        placement: Placement,
    ) -> Result<(u64, LogRecord), Error> {
        let index = self.next_index();
        let bytes = leaf.to_bytes();
        let at = self.stores.leaves.append(index, &bytes)?;
        let hash = leaf_hash(&bytes);
        self.pending.leaves.push((hash, Some(at), placement));
        Ok((
            index,
            LogRecord::Leaf {
                index,
                hash,
                placement,
                insert: Some(bytes),
            },
        ))
    }

    /// Stages a deletion's leaf `0x02 ‖ certificate`: the certificate joins the certificate store
    /// under its `database_lsn` (which must be the next index); returns `LOG_LEAF` and `CERT_REF`.
    pub fn stage_delete(
        &mut self,
        lsn: u64,
        certificate: &[u8],
        placement: Placement,
    ) -> Result<[LogRecord; 2], Error> {
        if lsn != self.next_index() {
            return Err(inv("§10.2 database_lsn"));
        }
        let at = self.stores.certs.append(lsn, certificate)?;
        let hash = leaf_hash(&delete_leaf(certificate));
        self.pending.leaves.push((hash, None, placement));
        self.pending.certs.push((lsn, at));
        Ok([
            LogRecord::Leaf {
                index: lsn,
                hash,
                placement,
                insert: None,
            },
            LogRecord::CertRef {
                lsn,
                at,
                sha256: Sha256::digest(certificate).into(),
            },
        ])
    }

    /// Stages a log checkpoint (of committed leaves only, DB-82; never smaller than the last one);
    /// returns `LOG_CHECKPOINT`.
    pub fn stage_checkpoint(&mut self, w: Witnessed) -> Result<LogRecord, Error> {
        let last = self.pending.checkpoints.last().or(self.checkpoints.last());
        if w.checkpoint.tree_size > self.tree.size()
            || last.is_some_and(|l| w.checkpoint.tree_size < l.checkpoint.tree_size)
        {
            return Err(inv("§10.3 checkpoint size"));
        }
        self.pending.checkpoints.push(w.clone());
        Ok(LogRecord::Checkpoint(w))
    }

    /// Protocol step 3: the staged insert leaves and certificates become durable before `COMMIT`.
    pub fn sync(&mut self) -> Result<(), Error> {
        self.stores.leaves.sync()?;
        self.stores.certs.sync()
    }

    /// Phase C: the transaction committed; its leaves, certificates and checkpoints join the
    /// committed state, and the hash and checkpoint stores, durably.
    pub fn commit(&mut self) -> Result<(), Error> {
        let p = core::mem::take(&mut self.pending);
        for (hash, at, placement) in p.leaves {
            let index = self.tree.size();
            let ty = if at.is_some() {
                LEAF_INSERT
            } else {
                LEAF_DELETE
            };
            self.stores
                .hashes
                .append(index, &hash_entry_bytes(ty, &hash, &placement))?;
            self.tree.push_hash(hash);
            self.inserts.push(at);
        }
        self.certs.extend(p.certs);
        for w in p.checkpoints {
            self.stores
                .checkpoints
                .append(w.checkpoint.tree_size, &w.to_bytes())?;
            self.push_checkpoint(w)?;
        }
        self.stores.hashes.sync()?;
        self.stores.checkpoints.sync()
    }

    /// The transaction did not commit: forget what it staged (its store bytes stay unreferenced
    /// and are superseded by the next transaction's, §14.6).
    pub fn abort(&mut self) {
        self.pending = Pending::default();
    }

    // --- recovery --------------------------------------------------------------------------

    /// Replays one committed log record from the WAL tail. Records the stores already hold are
    /// checked; the rest are appended to them (made durable by [`LogStore::recover`]).
    pub fn replay(&mut self, r: &WalRecord) -> Result<(), Error> {
        match LogRecord::decode(r)? {
            LogRecord::Leaf {
                index,
                hash,
                placement,
                insert,
            } => {
                if index < self.tree.size() {
                    let same_type = self
                        .inserts
                        .get(usize::try_from(index).unwrap_or(usize::MAX))
                        .is_some_and(|a| a.is_some() == insert.is_some());
                    return if self.tree.leaf(index) == Some(hash) && same_type {
                        Ok(())
                    } else {
                        Err(inv("§12.3 replayed leaf differs"))
                    };
                }
                if index != self.tree.size() {
                    return Err(inv("§12.3 replayed leaf out of order"));
                }
                let at = match insert {
                    None => None,
                    Some(bytes) => Some(match self.spare_inserts.remove(&index) {
                        Some(at)
                            if self
                                .stores
                                .leaves
                                .read(&at)
                                .is_ok_and(|rec| rec.bytes == bytes) =>
                        {
                            at
                        }
                        _ => self.stores.leaves.append(index, &bytes)?,
                    }),
                };
                if insert.as_ref().is_some_and(|b| leaf_hash(b) != hash) {
                    return Err(inv("§12.3 replayed leaf hash"));
                }
                let ty = if at.is_some() {
                    LEAF_INSERT
                } else {
                    LEAF_DELETE
                };
                self.stores
                    .hashes
                    .append(index, &hash_entry_bytes(ty, &hash, &placement))?;
                self.tree.push_hash(hash);
                self.inserts.push(at);
                Ok(())
            }
            LogRecord::CertRef { lsn, at, sha256 } => {
                let rec = self.stores.certs.read(&at)?;
                if rec.key != lsn || <[u8; 32]>::from(Sha256::digest(&rec.bytes)) != sha256 {
                    return Err(inv("§14.6 CERT_REF"));
                }
                self.certs.insert(lsn, at);
                Ok(())
            }
            LogRecord::Checkpoint(w) => {
                if self.checkpoints.contains(&w) {
                    return Ok(());
                }
                self.stores
                    .checkpoints
                    .append(w.checkpoint.tree_size, &w.to_bytes())?;
                self.push_checkpoint(w)
            }
        }
    }

    /// After replay: the stores are durable and the invariants hold.
    pub fn recover(&mut self) -> Result<(), Error> {
        self.spare_inserts.clear();
        self.stores.leaves.sync()?;
        self.stores.hashes.sync()?;
        self.stores.checkpoints.sync()?;
        self.check_invariants()
    }

    /// INV-15 (first half): the root at every checkpoint's size is that checkpoint's root; every
    /// committed insert leaf and certificate lies in its store.
    pub fn check_invariants(&self) -> Result<(), Error> {
        for w in &self.checkpoints {
            if self.tree.root(w.checkpoint.tree_size) != Some(w.checkpoint.root) {
                return Err(inv("INV-15"));
            }
        }
        if self
            .checkpoints
            .first()
            .is_none_or(|g| g.checkpoint.tree_size != 0)
        {
            return Err(inv("DB-79 genesis checkpoint"));
        }
        let deletes = self.inserts.iter().filter(|a| a.is_none()).count();
        if self.inserts.len() as u64 != self.tree.size() || deletes != self.certs.len() {
            return Err(inv("INV-15 log stores"));
        }
        Ok(())
    }
}
