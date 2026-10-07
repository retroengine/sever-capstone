//! `sever-appendstore`: EP-8 append-only record stores (Part 2, Build §3.3; spec §14.8).
//!
//! A store is a directory of segment files `<dir>/<seq>.store`, each a 16-byte file header
//! (DB-48) followed by records `u64be key ‖ u32be len ‖ bytes ‖ u32be crc32c`. Records are
//! appended and made durable by [`AppendStore::sync`] **before** the `COMMIT` that references
//! them (§14.6); a reference is `(segment, offset, len)`. Bytes that no committed transaction
//! references are ignored, and a torn tail is cut off at the next open (§14.8: "unreferenced bytes
//! after a crash are ignored and overwritten").
//!
//! Part 2 uses one store for passage text (`payloads/`); Part 3 adds stores for log leaves and
//! certificates through the same trait.

use std::sync::Arc;

use sever_format::codec::bad;
use sever_format::store::MAX_VALUE;
use sever_format::{FileHeader, PayloadRef, StoreRecord, magic};
use sever_types::Error;
use sever_vfs::{OpenMode, Vfs, VfsError, VfsFile, durable, read_exact_at};

#[cfg(any(test, feature = "contract-tests"))]
pub mod contract;

/// Where a record lies: segment, offset of the record in the file, value length.
pub type StoreRef = PayloadRef;

/// EP-8 (Build §3.3): an append-only record store.
pub trait AppendStore: Send {
    /// Appends `bytes` under `key`. Not durable until [`AppendStore::sync`].
    fn append(&mut self, key: u64, bytes: &[u8]) -> Result<StoreRef, Error>;
    /// Makes every appended record durable. On failure the caller aborts (§12.7).
    fn sync(&mut self) -> Result<(), Error>;
    /// Reads the record at `at`, checking its CRC and length.
    fn read(&self, at: &StoreRef) -> Result<StoreRecord, Error>;
}

/// Settings of a file-backed store.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StoreConfig {
    /// Its directory, relative to the data directory (`payloads`).
    pub dir: String,
    /// The sealer (DB-48).
    pub sealer_id: u16,
    /// A segment is closed when the next record would make it longer than this.
    pub segment_bytes: u64,
}

/// The default segment size: 64 MiB.
pub const DEFAULT_SEGMENT_BYTES: u64 = 64 * 1024 * 1024;

fn io(_: VfsError) -> Error {
    Error::DurabilityFailure
}

fn segment_path(dir: &str, seq: u64) -> String {
    format!("{dir}/{seq:020}.store")
}

fn parse_name(name: &str) -> Option<u64> {
    let digits = name.strip_suffix(".store")?;
    (digits.len() == 20 && digits.bytes().all(|b| b.is_ascii_digit()))
        .then(|| digits.parse().ok())
        .flatten()
}

/// The file-backed store.
pub struct FileStore {
    vfs: Arc<dyn Vfs>,
    cfg: StoreConfig,
    seq: u64,
    file: Box<dyn VfsFile>,
    len: u64,
    dirty: bool,
    failed: bool,
}

impl core::fmt::Debug for FileStore {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(
            f,
            "FileStore({}, segment {}, {} bytes)",
            self.cfg.dir, self.seq, self.len
        )
    }
}

impl FileStore {
    /// Creates a new, empty store: its directory and first segment, durable.
    pub fn create(vfs: Arc<dyn Vfs>, cfg: StoreConfig) -> Result<Self, Error> {
        durable::create_dir(vfs.as_ref(), &cfg.dir).map_err(io)?;
        let file = new_segment(vfs.as_ref(), &cfg, 1)?;
        Ok(Self {
            vfs,
            cfg,
            seq: 1,
            file,
            len: FileHeader::LEN as u64,
            dirty: false,
            failed: false,
        })
    }

    /// Opens an existing store after a restart: the newest segment's tail is cut after its last
    /// valid record, and a newest segment whose header never became durable is removed.
    pub fn open(vfs: Arc<dyn Vfs>, cfg: StoreConfig) -> Result<Self, Error> {
        let mut seqs = Vec::new();
        for name in vfs
            .list(&cfg.dir)
            .map_err(|_| bad("§14.8 store directory"))?
        {
            seqs.push(parse_name(&name).ok_or(bad("§14.8 store file name"))?);
        }
        seqs.sort_unstable();
        loop {
            let seq = *seqs.last().ok_or(bad("§14.8 no store segment"))?;
            let path = segment_path(&cfg.dir, seq);
            let mut file = vfs.open(&path, OpenMode::Existing).map_err(io)?;
            let bytes = sever_vfs::read_all(file.as_ref()).map_err(io)?;
            let header = bytes
                .get(..FileHeader::LEN)
                .ok_or(bad("§14.8 store header"))
                .and_then(|h| FileHeader::parse(h, &magic::STORE, cfg.sealer_id));
            match header {
                Ok(_) => {}
                Err(Error::IntegrityViolation {
                    invariant: "DB-48 sealer_id",
                }) => return Err(bad("DB-48 sealer_id")),
                Err(_) if seqs.len() > 1 => {
                    durable::unlink(vfs.as_ref(), &path).map_err(io)?;
                    seqs.pop();
                    continue;
                }
                Err(e) => return Err(e),
            }
            let mut off = FileHeader::LEN;
            while let Some((_, n)) = bytes.get(off..).and_then(StoreRecord::parse_next) {
                off += n;
            }
            if off < bytes.len() {
                file.truncate(off as u64).map_err(io)?;
                durable::sync(file.as_mut()).map_err(io)?;
            }
            return Ok(Self {
                vfs,
                cfg,
                seq,
                file,
                len: off as u64,
                dirty: false,
                failed: false,
            });
        }
    }

    fn guard<T>(&mut self, r: Result<T, Error>) -> Result<T, Error> {
        if r.is_err() {
            self.failed = true;
        }
        r
    }
}

fn new_segment(vfs: &dyn Vfs, cfg: &StoreConfig, seq: u64) -> Result<Box<dyn VfsFile>, Error> {
    let mut f = durable::create(vfs, &segment_path(&cfg.dir, seq)).map_err(io)?;
    let h = FileHeader {
        magic: magic::STORE,
        sealer_id: cfg.sealer_id,
    };
    f.write_at(0, &h.encode()).map_err(io)?;
    durable::sync(f.as_mut()).map_err(io)?;
    Ok(f)
}

impl AppendStore for FileStore {
    fn append(&mut self, key: u64, bytes: &[u8]) -> Result<StoreRef, Error> {
        if self.failed {
            return Err(Error::DurabilityFailure);
        }
        let len = u32::try_from(bytes.len())
            .ok()
            .filter(|_| bytes.len() <= MAX_VALUE)
            .ok_or(bad("§14.8 value too large"))?;
        let rec = StoreRecord {
            key,
            bytes: bytes.to_vec(),
        }
        .encode();
        let r = (|| {
            if self.len + rec.len() as u64 > self.cfg.segment_bytes
                && self.len > FileHeader::LEN as u64
            {
                durable::sync(self.file.as_mut()).map_err(io)?;
                self.seq += 1;
                self.file = new_segment(self.vfs.as_ref(), &self.cfg, self.seq)?;
                self.len = FileHeader::LEN as u64;
            }
            let at = self.file.append(&rec).map_err(io)?;
            if at != self.len {
                return Err(Error::DurabilityFailure);
            }
            self.len += rec.len() as u64;
            self.dirty = true;
            Ok(StoreRef {
                segment: self.seq,
                offset: at,
                len,
            })
        })();
        self.guard(r)
    }

    fn sync(&mut self) -> Result<(), Error> {
        if self.failed {
            return Err(Error::DurabilityFailure);
        }
        if !self.dirty {
            return Ok(());
        }
        let r = durable::sync(self.file.as_mut()).map_err(io);
        self.dirty = false;
        self.guard(r)
    }

    fn read(&self, at: &StoreRef) -> Result<StoreRecord, Error> {
        let f = self
            .vfs
            .open(&segment_path(&self.cfg.dir, at.segment), OpenMode::Existing)
            .map_err(|_| bad("§14.8 store reference"))?;
        let mut buf = vec![0u8; StoreRecord::OVERHEAD + at.len as usize];
        read_exact_at(f.as_ref(), at.offset, &mut buf).map_err(|_| bad("§14.8 store reference"))?;
        match StoreRecord::parse_next(&buf) {
            Some((rec, n)) if n == buf.len() && at.offset >= FileHeader::LEN as u64 => Ok(rec),
            _ => Err(bad("§14.8 store record")),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sever_spec::spec;
    use sever_vfs::{CrashPolicy, FaultPlan, SimVfs};

    fn cfg(segment_bytes: u64) -> StoreConfig {
        StoreConfig {
            dir: "payloads".into(),
            sealer_id: 0,
            segment_bytes,
        }
    }

    #[test]
    #[spec("SR-14.8-1", "SR-14.6-3")]
    fn p2_store_synced_records_survive_and_unsynced_tail_is_cut() {
        let v = SimVfs::new();
        let mut s = FileStore::create(Arc::new(v.clone()), cfg(DEFAULT_SEGMENT_BYTES)).unwrap();
        let a = s.append(1, b"first passage").unwrap();
        s.sync().unwrap();
        let _lost = s.append(2, b"never synced").unwrap();
        v.restart(CrashPolicy::Random(3));
        let mut s = FileStore::open(Arc::new(v.clone()), cfg(DEFAULT_SEGMENT_BYTES)).unwrap();
        assert_eq!(s.read(&a).unwrap().bytes, b"first passage");
        // The next record lands after the last valid one, whatever the crash left behind.
        let b = s.append(3, b"after restart").unwrap();
        s.sync().unwrap();
        v.restart(CrashPolicy::DropAll);
        let s = FileStore::open(Arc::new(v.clone()), cfg(DEFAULT_SEGMENT_BYTES)).unwrap();
        assert_eq!(s.read(&b).unwrap().bytes, b"after restart");
        assert_eq!(s.read(&a).unwrap().key, 1);
    }

    #[test]
    fn p2_store_crash_at_every_operation_never_loses_a_synced_record() {
        let base = SimVfs::new();
        FileStore::create(Arc::new(base.clone()), cfg(200)).unwrap();
        let work = |v: &SimVfs| -> Vec<StoreRef> {
            let mut synced = Vec::new();
            let Ok(mut s) = FileStore::open(Arc::new(v.clone()), cfg(200)) else {
                return synced;
            };
            for i in 0..8u64 {
                let Ok(r) = s.append(i, &vec![i as u8; 40 + i as usize * 9]) else {
                    break;
                };
                if s.sync().is_err() {
                    break;
                }
                synced.push(r);
            }
            synced
        };
        let dry = base.fork();
        dry.set_faults(FaultPlan::default());
        assert_eq!(work(&dry).len(), 8);
        for k in 1..=dry.ops_since_plan() {
            for policy in [
                CrashPolicy::DropAll,
                CrashPolicy::KeepAll,
                CrashPolicy::Random(k),
            ] {
                let v = base.fork();
                v.set_faults(FaultPlan {
                    crash_at_op: Some(k),
                    tear_bytes: 21,
                    ..FaultPlan::default()
                });
                let synced = work(&v);
                v.restart(policy);
                let s = FileStore::open(Arc::new(v.clone()), cfg(200)).unwrap();
                for (i, r) in synced.iter().enumerate() {
                    let rec = s.read(r).unwrap();
                    assert_eq!(rec.key, i as u64, "k = {k}, {policy:?}");
                }
            }
        }
    }

    #[test]
    fn p2_store_read_checks_the_reference() {
        let v = SimVfs::new();
        let mut s = FileStore::create(Arc::new(v.clone()), cfg(DEFAULT_SEGMENT_BYTES)).unwrap();
        let r = s.append(9, b"abc").unwrap();
        s.sync().unwrap();
        for bad_ref in [
            StoreRef { len: 4, ..r },
            StoreRef {
                offset: r.offset + 1,
                ..r
            },
            StoreRef { segment: 2, ..r },
            StoreRef {
                offset: 0,
                len: 0,
                ..r
            },
        ] {
            assert!(s.read(&bad_ref).is_err(), "{bad_ref:?}");
        }
    }

    #[test]
    fn p2_store_rejects_wrong_sealer_and_foreign_files() {
        let v = SimVfs::new();
        FileStore::create(Arc::new(v.clone()), cfg(DEFAULT_SEGMENT_BYTES)).unwrap();
        let mut other = cfg(DEFAULT_SEGMENT_BYTES);
        other.sealer_id = 1;
        assert_eq!(
            FileStore::open(Arc::new(v.clone()), other).err(),
            Some(bad("DB-48 sealer_id"))
        );
        v.open("payloads/x", OpenMode::CreateNew).unwrap();
        assert!(FileStore::open(Arc::new(v.clone()), cfg(DEFAULT_SEGMENT_BYTES)).is_err());
    }

    #[test]
    fn p2_store_failure_poisons_the_store() {
        let v = SimVfs::new();
        let mut s = FileStore::create(Arc::new(v.clone()), cfg(DEFAULT_SEGMENT_BYTES)).unwrap();
        s.append(1, b"x").unwrap();
        v.set_faults(FaultPlan {
            fail_sync_at: Some(1),
            ..FaultPlan::default()
        });
        assert_eq!(s.sync(), Err(Error::DurabilityFailure));
        assert_eq!(s.append(2, b"y").err(), Some(Error::DurabilityFailure));
    }
}
