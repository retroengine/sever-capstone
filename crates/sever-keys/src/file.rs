//! The key file `KEYS` (spec §14.7, DB-90).
//!
//! ```text
//! header (4,096)  b"SVDBKEYS" ‖ u16be version ‖ zero padding ‖ u32be crc32c   written once
//! pair i          at 4,096 + 1,024·i: slot 0 (512) ‖ slot 1 (512)              appended, never reused
//! slot (512)      u32be magic b"SVKS" ‖ u64be domain_index ‖ u64be key_version ‖ key (32) ‖
//!                 collection_id (16) ‖ group_id (32) ‖ zero padding ‖ u32be crc32c
//! erased slot     512 zero bytes
//! ```
//!
//! Every CRC is CRC-32C over every byte before it. A slot that is neither erased nor valid (a torn
//! write, a bad magic, a `domain_index` that is not its pair's position) is treated as absent
//! (§14.7). Every write and erase is `fsync`ed before it returns (§13.4: phase A and phase C).

use std::sync::Arc;

use sever_types::{Error, SecretBuf};
use sever_vfs::{OpenMode, Vfs, VfsError, VfsFile, durable, read_exact_at};
use zeroize::Zeroize;

use crate::{Domain, KEY_BYTES, Key};

/// The header's length.
pub const HEADER_BYTES: usize = 4_096;
/// One slot's length (one sector, §14.7).
pub const SLOT_BYTES: usize = 512;
/// One pair's length: the two slots of a domain.
pub const PAIR_BYTES: usize = 2 * SLOT_BYTES;
/// The header's magic.
pub const FILE_MAGIC: &[u8; 8] = b"SVDBKEYS";
/// Every slot's magic (DB-90).
pub const SLOT_MAGIC: &[u8; 4] = b"SVKS";
/// The format version (§14.9: every version is 1 in v1).
pub const VERSION: u16 = 1;

/// The key file's size with `domains` pairs: 4 KB plus 1 KB per domain (§14.7, Appendix A).
pub fn file_size(domains: u64) -> u64 {
    HEADER_BYTES as u64 + PAIR_BYTES as u64 * domains
}

/// Where pair `index` starts: its domain index is its position (DB-90).
pub fn pair_offset(index: u64) -> u64 {
    file_size(index)
}

/// What one slot holds.
pub struct SlotRecord {
    /// The domain's index: its pair's position.
    pub domain_index: u64,
    /// The key's version.
    pub key_version: u64,
    /// Which domain the key belongs to.
    pub domain: Domain,
    /// The group key.
    pub key: Key,
}

/// One slot as read back.
#[derive(Debug)]
pub enum SlotState {
    /// 512 zero bytes: erased (or never written).
    Erased,
    /// A slot with a valid magic, CRC and position.
    Valid(SlotRecord),
    /// Anything else, treated as absent (§14.7).
    Torn,
}

impl core::fmt::Debug for SlotRecord {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.debug_struct("SlotRecord")
            .field("domain_index", &self.domain_index)
            .field("key_version", &self.key_version)
            .field("domain", &self.domain)
            .finish_non_exhaustive()
    }
}

/// The header's bytes.
pub fn encode_header() -> [u8; HEADER_BYTES] {
    let mut h = [0u8; HEADER_BYTES];
    put(&mut h, 0, FILE_MAGIC);
    put(&mut h, 8, &VERSION.to_be_bytes());
    seal_crc(&mut h);
    h
}

/// Checks the header (`IntegrityViolation` naming §14.7 otherwise).
pub fn check_header(h: &[u8]) -> Result<(), Error> {
    let ok = h.len() == HEADER_BYTES
        && h.get(..8) == Some(FILE_MAGIC.as_slice())
        && h.get(8..10) == Some(VERSION.to_be_bytes().as_slice())
        && crc_ok(h);
    if ok {
        Ok(())
    } else {
        Err(bad("§14.7 key file header"))
    }
}

/// A slot's bytes, in secret memory (they hold the key).
pub fn encode_slot(r: &SlotRecord) -> SecretBuf {
    let mut buf = SecretBuf::new(SLOT_BYTES);
    let s = buf.as_bytes_mut();
    put(s, 0, SLOT_MAGIC);
    put(s, 4, &r.domain_index.to_be_bytes());
    put(s, 12, &r.key_version.to_be_bytes());
    put(s, 20, r.key.as_bytes());
    put(s, 52, &r.domain.collection_id);
    put(s, 68, &r.domain.group_id);
    seal_crc(s);
    buf
}

/// Reads slot bytes found at pair `position`.
pub fn decode_slot(s: &[u8], position: u64) -> SlotState {
    if s.len() != SLOT_BYTES {
        return SlotState::Torn;
    }
    if s.iter().all(|b| *b == 0) {
        return SlotState::Erased;
    }
    let field = |a: usize, b: usize| s.get(a..b).unwrap_or_default();
    let u64_at = |a: usize| {
        let mut x = [0u8; 8];
        x.copy_from_slice(field(a, a + 8));
        u64::from_be_bytes(x)
    };
    if field(0, 4) != SLOT_MAGIC || !crc_ok(s) || field(100, SLOT_BYTES - 4).iter().any(|b| *b != 0)
    {
        return SlotState::Torn;
    }
    let domain_index = u64_at(4);
    if domain_index != position {
        return SlotState::Torn;
    }
    let (mut key, mut collection_id, mut group_id) = ([0u8; KEY_BYTES], [0u8; 16], [0u8; 32]);
    key.copy_from_slice(field(20, 52));
    collection_id.copy_from_slice(field(52, 68));
    group_id.copy_from_slice(field(68, 100));
    let record = SlotRecord {
        domain_index,
        key_version: u64_at(12),
        domain: Domain {
            collection_id,
            group_id,
        },
        key: Key::from_bytes(&key),
    };
    key.zeroize();
    SlotState::Valid(record)
}

fn put(buf: &mut [u8], at: usize, bytes: &[u8]) {
    if let Some(dst) = buf.get_mut(at..at + bytes.len()) {
        dst.copy_from_slice(bytes);
    }
}

fn seal_crc(buf: &mut [u8]) {
    let n = buf.len() - 4;
    let crc = crc32c::crc32c(buf.get(..n).unwrap_or_default());
    put(buf, n, &crc.to_be_bytes());
}

fn crc_ok(buf: &[u8]) -> bool {
    let n = buf.len().saturating_sub(4);
    let (body, tail) = buf.split_at(n);
    tail == crc32c::crc32c(body).to_be_bytes()
}

fn bad(rule: &'static str) -> Error {
    Error::IntegrityViolation { invariant: rule }
}

fn io(_: VfsError) -> Error {
    Error::DurabilityFailure
}

/// The key file on a [`Vfs`] (the key directory, §12.9). Opening it truncates a trailing partial
/// pair; every write and erase is `fsync`ed before it returns.
pub struct KeyFile {
    vfs: Arc<dyn Vfs>,
    path: String,
    file: Box<dyn VfsFile>,
    pairs: u64,
}

impl KeyFile {
    /// Opens `path` on `vfs`, creating it (the header, written once and `fsync`ed, then the
    /// directory entry) if it does not exist. Returns the file and every slot read back, pair by
    /// pair. A trailing partial pair (a crash while the file grew) is truncated (DB-90).
    pub fn open(vfs: Arc<dyn Vfs>, path: &str) -> Result<(Self, Vec<[SlotState; 2]>), Error> {
        let mut file = match vfs.open(path, OpenMode::Existing) {
            Ok(f) => f,
            Err(VfsError::NotFound) => {
                let mut f = durable::create(vfs.as_ref(), path).map_err(io)?;
                f.write_at(0, &encode_header()).map_err(io)?;
                durable::sync(f.as_mut()).map_err(io)?;
                f
            }
            Err(e) => return Err(io(e)),
        };
        let len = file.len().map_err(io)?;
        let mut header = [0u8; HEADER_BYTES];
        if len < HEADER_BYTES as u64 {
            return Err(bad("§14.7 key file header"));
        }
        read_exact_at(file.as_ref(), 0, &mut header).map_err(io)?;
        check_header(&header)?;
        let pairs = (len - HEADER_BYTES as u64) / PAIR_BYTES as u64;
        if file_size(pairs) != len {
            file.truncate(file_size(pairs)).map_err(io)?;
            durable::sync(file.as_mut()).map_err(io)?;
        }
        let mut slots = Vec::new();
        for i in 0..pairs {
            let mut pair = SecretBuf::new(PAIR_BYTES);
            read_exact_at(file.as_ref(), pair_offset(i), pair.as_bytes_mut()).map_err(io)?;
            let (a, b) = pair.as_bytes().split_at(SLOT_BYTES);
            slots.push([decode_slot(a, i), decode_slot(b, i)]);
        }
        Ok((
            Self {
                vfs,
                path: path.to_owned(),
                file,
                pairs,
            },
            slots,
        ))
    }

    /// Pairs in the file (domain indices `0 … pairs − 1` are allocated).
    pub fn pairs(&self) -> u64 {
        self.pairs
    }

    /// The path the file was opened under.
    pub fn path(&self) -> &str {
        &self.path
    }

    /// The file system the file lives on.
    pub fn vfs(&self) -> &Arc<dyn Vfs> {
        &self.vfs
    }

    /// Appends a pair for a new domain: slot 0 holds `key` at `key_version`, slot 1 is erased.
    /// Returns the domain's index (the pair's position), durable when this returns.
    pub fn append(&mut self, domain: Domain, key_version: u64, key: &Key) -> Result<u64, Error> {
        let index = self.pairs;
        let slot = encode_slot(&SlotRecord {
            domain_index: index,
            key_version,
            domain,
            key: key.duplicate(),
        });
        let mut pair = SecretBuf::new(PAIR_BYTES);
        if let Some(dst) = pair.as_bytes_mut().get_mut(..SLOT_BYTES) {
            dst.copy_from_slice(slot.as_bytes());
        }
        self.file
            .write_at(pair_offset(index), pair.as_bytes())
            .map_err(io)?;
        durable::sync(self.file.as_mut()).map_err(io)?;
        self.pairs += 1;
        Ok(index)
    }

    /// Writes slot `which` (0 or 1) of pair `index` and `fsync`s it (phase A of a rotation,
    /// §13.4).
    pub fn write_slot(
        &mut self,
        index: u64,
        which: u8,
        domain: Domain,
        key_version: u64,
        key: &Key,
    ) -> Result<(), Error> {
        let at = self.slot_offset(index, which)?;
        let slot = encode_slot(&SlotRecord {
            domain_index: index,
            key_version,
            domain,
            key: key.duplicate(),
        });
        self.file.write_at(at, slot.as_bytes()).map_err(io)?;
        durable::sync(self.file.as_mut()).map_err(io)
    }

    /// Overwrites slot `which` of pair `index` with zeros and `fsync`s it (phase C, §13.4).
    pub fn erase_slot(&mut self, index: u64, which: u8) -> Result<(), Error> {
        let at = self.slot_offset(index, which)?;
        self.file.write_at(at, &[0u8; SLOT_BYTES]).map_err(io)?;
        durable::sync(self.file.as_mut()).map_err(io)
    }

    fn slot_offset(&self, index: u64, which: u8) -> Result<u64, Error> {
        if index >= self.pairs || which > 1 {
            return Err(bad("§14.7 slot outside the key file"));
        }
        Ok(pair_offset(index) + u64::from(which) * SLOT_BYTES as u64)
    }
}
