//! Record-key envelopes (§14.4) and bucket blocks (§14.5).
//!
//! - An envelope is `nonce ‖ AES-GCM-SIV(RK_t) ‖ tag` = 12 + 32 + 16 = 60 bytes, under the record's
//!   bucket key, with §13.2 row 3 as associated data.
//! - A bucket block is 64 entries of `u64be bucket_version ‖ wrapped bucket key (60)` = 4,352 bytes,
//!   each bucket key under the group key with §13.2 row 4 as associated data.

use sever_keys::{BUCKETS, Domain, KEY_BYTES, Key};
use sever_types::Error;

use crate::ad::{self, Sid};
use crate::aead;

/// Bytes of an envelope (§14.4).
pub const ENVELOPE_BYTES: usize = aead::OVERHEAD + KEY_BYTES;
/// Bytes of one bucket-block entry.
pub const ENTRY_BYTES: usize = 8 + ENVELOPE_BYTES;
/// Bytes of a bucket block (§14.5).
pub const BLOCK_BYTES: usize = BUCKETS as usize * ENTRY_BYTES;

/// An envelope.
pub type Envelope = [u8; ENVELOPE_BYTES];

/// A bucket key and its version.
#[derive(Debug)]
pub struct BucketKey {
    /// The bucket key's version.
    pub version: u64,
    /// The key.
    pub key: Key,
}

// §12.8: every secret type implements `Zeroize` and `ZeroizeOnDrop` (through its `Key`).
impl zeroize::Zeroize for BucketKey {
    fn zeroize(&mut self) {
        zeroize::Zeroize::zeroize(&mut self.key);
    }
}

impl zeroize::ZeroizeOnDrop for BucketKey {}

impl BucketKey {
    /// A fresh bucket key at `version`.
    pub fn generate(version: u64) -> Self {
        Self {
            version,
            key: Key::generate(),
        }
    }

    /// A second copy.
    pub fn duplicate(&self) -> Self {
        Self {
            version: self.version,
            key: self.key.duplicate(),
        }
    }
}

fn layout_error() -> Error {
    Error::IntegrityViolation {
        invariant: "§14.5 bucket block",
    }
}

fn key_of(bytes: &[u8]) -> Result<Key, Error> {
    let raw: &[u8; KEY_BYTES] = bytes.try_into().map_err(|_| layout_error())?;
    Ok(Key::from_bytes(raw))
}

/// Wraps record key `rk` under bucket key `bk` (§13.2 row 3).
pub fn wrap_record_key(bk: &BucketKey, d: &Domain, sid: &Sid, rk: &Key) -> Result<Envelope, Error> {
    let sealed = aead::seal(&bk.key, &ad::record_key(d, sid, bk.version), rk.as_bytes())?;
    // SB-29: the record key goes into its envelope unwrapped (padded to the envelope's length).
    #[cfg(feature = "sabotage-SB-29")]
    let sealed = {
        let mut v = rk.as_bytes().to_vec();
        v.resize(sealed.len(), 0);
        v
    };
    sealed.as_slice().try_into().map_err(|_| layout_error())
}

/// Opens an envelope under bucket key `bk`.
pub fn unwrap_record_key(bk: &BucketKey, d: &Domain, sid: &Sid, env: &[u8]) -> Result<Key, Error> {
    #[cfg(feature = "sabotage-SB-29")]
    {
        let _ = (bk, d, sid);
        return key_of(env.get(..32).unwrap_or_default());
    }
    #[allow(unreachable_code)]
    let plain = aead::open(&bk.key, &ad::record_key(d, sid, bk.version), env)?;
    key_of(&plain)
}

/// The bucket block of domain `d`: its 64 bucket keys under group key `gk` at `group_key_version`.
pub fn encode_block(
    gk: &Key,
    d: &Domain,
    group_key_version: u64,
    buckets: &[BucketKey],
) -> Result<Vec<u8>, Error> {
    if buckets.len() != usize::from(BUCKETS) {
        return Err(layout_error());
    }
    let mut out = Vec::with_capacity(BLOCK_BYTES);
    for (b, bk) in (0u8..).zip(buckets) {
        out.extend_from_slice(&bk.version.to_be_bytes());
        let wrapped = aead::seal(
            gk,
            &ad::bucket_key(d, b, group_key_version),
            bk.key.as_bytes(),
        )?;
        out.extend_from_slice(&wrapped);
    }
    Ok(out)
}

/// Opens a bucket block written by [`encode_block`].
pub fn decode_block(
    gk: &Key,
    d: &Domain,
    group_key_version: u64,
    block: &[u8],
) -> Result<Vec<BucketKey>, Error> {
    if block.len() != BLOCK_BYTES {
        return Err(layout_error());
    }
    (0u8..)
        .zip(block.chunks_exact(ENTRY_BYTES))
        .map(|(b, entry)| {
            let (v, wrapped) = entry.split_at(8);
            let version = u64::from_be_bytes(v.try_into().map_err(|_| layout_error())?);
            let plain = aead::open(gk, &ad::bucket_key(d, b, group_key_version), wrapped)?;
            Ok(BucketKey {
                version,
                key: key_of(&plain)?,
            })
        })
        .collect()
}
