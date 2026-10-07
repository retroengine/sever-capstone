//! `StoredExtension`: how a group extension's state is stored (DB-46).
//!
//! Part 1's frozen `GroupExtension` (EP-1) has no byte form for its state, because Part 1 has no
//! storage. Part 2 adds this trait beside it (F-3: extend, never edit): fixed sizes and codecs for
//! the public group state (in the header), the secret group state (sealed with `S`) and the
//! secret per record (at the end of the slot payload). Part 3's commitment extension implements
//! both traits.

use sever_index::{GroupExtension, NoExtension};
use sever_types::Error;

/// The stored form of an extension's state.
pub trait StoredExtension: GroupExtension {
    /// Bytes of the public group state (Part 3: `C_S`, 32).
    const PUBLIC_LEN: usize;
    /// Bytes of the secret group state (Part 3: `r_agg`, 32).
    const GROUP_SECRET_LEN: usize;
    /// Bytes of the secret per record (Part 3: 41).
    const RECORD_SECRET_LEN: usize;

    /// Encodes the public group state (exactly `PUBLIC_LEN` bytes).
    fn encode_public(p: &Self::GroupPublic) -> Vec<u8>;
    /// Decodes it; `IntegrityViolation` on bad bytes.
    fn decode_public(b: &[u8]) -> Result<Self::GroupPublic, Error>;
    /// Encodes the secret group state (exactly `GROUP_SECRET_LEN` bytes).
    fn encode_group_secret(s: &Self::GroupSecret) -> Vec<u8>;
    /// Decodes it.
    fn decode_group_secret(b: &[u8]) -> Result<Self::GroupSecret, Error>;
    /// Encodes a record secret (exactly `RECORD_SECRET_LEN` bytes).
    fn encode_record_secret(r: &Self::RecordSecret) -> Vec<u8>;
    /// Decodes it.
    fn decode_record_secret(b: &[u8]) -> Result<Self::RecordSecret, Error>;
}

fn empty(b: &[u8]) -> Result<(), Error> {
    if b.is_empty() {
        Ok(())
    } else {
        Err(Error::IntegrityViolation {
            invariant: "DB-46 extension bytes",
        })
    }
}

impl StoredExtension for NoExtension {
    const PUBLIC_LEN: usize = 0;
    const GROUP_SECRET_LEN: usize = 0;
    const RECORD_SECRET_LEN: usize = 0;
    fn encode_public(_: &()) -> Vec<u8> {
        Vec::new()
    }
    fn decode_public(b: &[u8]) -> Result<(), Error> {
        empty(b)
    }
    fn encode_group_secret(_: &()) -> Vec<u8> {
        Vec::new()
    }
    fn decode_group_secret(b: &[u8]) -> Result<(), Error> {
        empty(b)
    }
    fn encode_record_secret(_: &()) -> Vec<u8> {
        Vec::new()
    }
    fn decode_record_secret(b: &[u8]) -> Result<(), Error> {
        empty(b)
    }
}
