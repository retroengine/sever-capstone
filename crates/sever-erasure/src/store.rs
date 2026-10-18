//! The wrapped-key store `wrapped/<seq>.store` (spec §14.8, DB-91): the key-rotation participant's
//! committed entries, appended in phase C, scanned in order at recovery, and compacted by writing
//! the live entries to `wrapped.new/` and swapping the directories with durable renames.

use std::sync::Arc;

use sever_appendstore::{AppendStore, FileStore, StoreConfig};
use sever_format::{FileHeader, StoreRecord};
use sever_types::Error;
use sever_vfs::{OpenMode, Vfs, VfsError, durable, read_exact_at};

/// The store's directory (§14.1).
pub const DIR: &str = "wrapped";
const NEW: &str = "wrapped.new";
const OLD: &str = "wrapped.old";

fn io(_: VfsError) -> Error {
    Error::DurabilityFailure
}

fn bad() -> Error {
    Error::IntegrityViolation {
        invariant: "§14.8 wrapped-key store",
    }
}

fn cfg(dir: &str, segment_bytes: u64) -> StoreConfig {
    StoreConfig {
        dir: dir.into(),
        sealer_id: sever_format::SEALER_AES_GCM_SIV,
        segment_bytes,
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
    vfs.remove_dir(path).map_err(io)?;
    durable::sync_dir(vfs, "").map_err(io)
}

/// Every value of the store in `dir`, in order, and the bytes they take.
fn scan(vfs: &dyn Vfs, dir: &str) -> Result<(Vec<Vec<u8>>, u64), Error> {
    let mut seqs: Vec<u64> = vfs
        .list(dir)
        .map_err(io)?
        .iter()
        .filter_map(|n| n.strip_suffix(".store").and_then(|d| d.parse().ok()))
        .collect();
    seqs.sort_unstable();
    let (mut out, mut bytes) = (Vec::new(), 0u64);
    for seq in seqs {
        let f = vfs
            .open(&format!("{dir}/{seq:020}.store"), OpenMode::Existing)
            .map_err(io)?;
        let size = f.len().map_err(io)?;
        let mut off = FileHeader::LEN as u64;
        while off + StoreRecord::OVERHEAD as u64 <= size {
            let mut head = [0u8; 12];
            read_exact_at(f.as_ref(), off, &mut head).map_err(io)?;
            let len = u32::from_be_bytes(
                head.get(8..12)
                    .ok_or_else(bad)?
                    .try_into()
                    .map_err(|_| bad())?,
            );
            let total = StoreRecord::OVERHEAD as u64 + u64::from(len);
            if off + total > size {
                break; // a torn tail: FileStore::open cuts it on the newest segment
            }
            let mut buf = vec![0u8; usize::try_from(total).map_err(|_| bad())?];
            read_exact_at(f.as_ref(), off, &mut buf).map_err(io)?;
            let (rec, _) = StoreRecord::parse_next(&buf).ok_or_else(bad)?;
            out.push(rec.bytes);
            bytes += total;
            off += total;
        }
    }
    Ok((out, bytes))
}

/// The open store.
pub struct WrappedStore {
    vfs: Arc<dyn Vfs>,
    store: FileStore,
    segment_bytes: u64,
    next_key: u64,
    bytes: u64,
}

impl core::fmt::Debug for WrappedStore {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "WrappedStore({} bytes)", self.bytes)
    }
}

impl WrappedStore {
    /// Opens the store (creating it on the participant's first recovery, and finishing or undoing
    /// an interrupted compaction); returns it and every value in it, in order.
    pub fn open(vfs: Arc<dyn Vfs>, segment_bytes: u64) -> Result<(Self, Vec<Vec<u8>>), Error> {
        let v = vfs.as_ref();
        if !exists(v, DIR)? && exists(v, NEW)? {
            // The swap was cut after the old store moved away: the new one is complete (it was
            // synced before the first rename).
            durable::rename(v, NEW, DIR).map_err(io)?;
        }
        remove_tree(v, NEW)?;
        remove_tree(v, OLD)?;
        if !exists(v, DIR)? {
            FileStore::create(Arc::clone(&vfs), cfg(DIR, segment_bytes))?;
        }
        let (values, bytes) = scan(v, DIR)?;
        let store = FileStore::open(Arc::clone(&vfs), cfg(DIR, segment_bytes))?;
        Ok((
            Self {
                vfs,
                store,
                segment_bytes,
                next_key: values.len() as u64,
                bytes,
            },
            values,
        ))
    }

    /// Bytes the store holds.
    pub fn bytes(&self) -> u64 {
        self.bytes
    }

    /// Appends `values` and makes them durable (phase C).
    pub fn append(&mut self, values: &[Vec<u8>]) -> Result<(), Error> {
        for v in values {
            self.store.append(self.next_key, v)?;
            self.next_key += 1;
            self.bytes += (StoreRecord::OVERHEAD + v.len()) as u64;
        }
        if values.is_empty() {
            Ok(())
        } else {
            self.store.sync()
        }
    }

    /// Replaces the store by one holding exactly `values` (§14.8 compaction): written to
    /// `wrapped.new/` and synced first, then swapped in by two durable renames.
    pub fn compact(&mut self, values: &[Vec<u8>]) -> Result<(), Error> {
        let v = self.vfs.as_ref();
        remove_tree(v, NEW)?;
        let mut fresh = FileStore::create(Arc::clone(&self.vfs), cfg(NEW, self.segment_bytes))?;
        let mut bytes = 0u64;
        for (key, value) in (0u64..).zip(values) {
            fresh.append(key, value)?;
            bytes += (StoreRecord::OVERHEAD + value.len()) as u64;
        }
        fresh.sync()?;
        drop(fresh);
        durable::rename(v, DIR, OLD).map_err(io)?;
        durable::rename(v, NEW, DIR).map_err(io)?;
        remove_tree(v, OLD)?;
        self.store = FileStore::open(Arc::clone(&self.vfs), cfg(DIR, self.segment_bytes))?;
        self.next_key = values.len() as u64;
        self.bytes = bytes;
        Ok(())
    }
}
