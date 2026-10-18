//! `sever-keys`: the keys of spec §13.1 and the key file of §14.7 (Part 4, Build 3-4 §2.4).
//!
//! - [`Key`]: a 32-byte key from the OS CSPRNG (§13.1), held in a [`SecretBuf`] (EP-4: zeroed on
//!   release, locked memory once Part 4's provider is installed, §12.8).
//! - [`bucket_of`]: a record's bucket, `scrambled_id[0] mod 64` (§13.1).
//! - [`file`]: the key file's bytes and [`file::KeyFile`], the file itself on a [`sever_vfs::Vfs`]
//!   (§14.7, DB-90): a header written once, then one pair of 512-byte slots per domain, appended.
//! - [`recovery`]: the recovery rule INV-14 (§13.4) as a pure function from the active versions and
//!   the slots read back to the slots to keep and the slots to erase.
//!
//! Only group keys live in the key file; bucket and record keys exist on disk only wrapped
//! (`sever-seal`). This crate never logs or prints a key (§17).

use core::fmt;

use rand_core::{OsRng, RngCore};
use sever_types::SecretBuf;

pub mod file;
pub mod recovery;

/// Bytes in every key (§13.1).
pub const KEY_BYTES: usize = 32;

/// Buckets per group (§13.1, §18 `buckets_per_group`).
pub const BUCKETS: u8 = 64;

/// A 32-byte key: a group key `GK_g`, a bucket key `BK_{g,b}` or a record key `RK_t` (§13.1).
/// Never cloned, never printed; its bytes are zeroed when it is dropped.
pub struct Key(SecretBuf);

impl Key {
    /// A fresh key from the OS CSPRNG (§13.1). There is no seeded variant (CLAUDE.md §6.2).
    pub fn generate() -> Self {
        let mut buf = SecretBuf::new(KEY_BYTES);
        OsRng.fill_bytes(buf.as_bytes_mut());
        Self(buf)
    }

    /// A key read back from storage (the key file, or an unwrapped envelope).
    pub fn from_bytes(bytes: &[u8; KEY_BYTES]) -> Self {
        let mut buf = SecretBuf::new(KEY_BYTES);
        buf.as_bytes_mut().copy_from_slice(bytes);
        Self(buf)
    }

    /// The key's bytes.
    pub fn as_bytes(&self) -> &[u8] {
        self.0.as_bytes()
    }

    /// A second copy in its own secret buffer (the key cache and the key file each hold one).
    pub fn duplicate(&self) -> Self {
        let mut buf = SecretBuf::new(KEY_BYTES);
        buf.as_bytes_mut().copy_from_slice(self.0.as_bytes());
        Self(buf)
    }
}

impl PartialEq for Key {
    fn eq(&self, other: &Self) -> bool {
        // Not constant time: keys are compared only by tests and by recovery's duplicate check.
        self.as_bytes() == other.as_bytes()
    }
}

impl Eq for Key {}

impl fmt::Debug for Key {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("Key(<redacted>)")
    }
}

/// A record's bucket: `b(t) = scrambled_id[0] mod 64` (§13.1). It depends only on the scrambled
/// ID, so it never changes while the record is live.
pub fn bucket_of(scrambled_id: &[u8; 64]) -> u8 {
    scrambled_id[0] % BUCKETS
}

/// A domain: the owner of one group key, named by its collection and group (§13.1, §14.7). The
/// holding area is a domain like any group.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Domain {
    /// The collection.
    pub collection_id: [u8; 16],
    /// The group, its §5.1 label zero-padded to 32 bytes as in §14.3.
    pub group_id: [u8; 32],
}

#[cfg(test)]
mod tests;
