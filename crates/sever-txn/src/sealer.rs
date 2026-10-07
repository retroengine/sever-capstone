//! EP-6 `Sealer` (Build §3.3): turns stored plaintext into stored bytes and back, per data kind
//! of spec §13.2, bound to the owner and version fields the specification lists as associated
//! data, with a fixed overhead so that file layouts are computable (DB-46, DB-48).
//!
//! Part 2 ships [`PlaintextSealer`]: zero overhead, empty record-key envelopes, `sealer_id` 0, and
//! no confidentiality claim (DB-48). Part 4 plugs in the AES-256-GCM-SIV sealer.

use sever_types::{CollectionId, Error, GroupId, ScrambledId};
use zeroize::Zeroizing;

/// The owner of a record-level value: the slot payload, the passage text and the record key's
/// envelope (§13.2 rows 1–3).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RecordOwner<'a> {
    /// The collection.
    pub collection: &'a CollectionId,
    /// The group (key domain) the record is in, or joins.
    pub group: &'a GroupId,
    /// The record.
    pub scrambled_id: &'a ScrambledId,
}

/// The owner of a group-level value: the accumulator (§13.2 row 5).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct GroupOwner<'a> {
    /// The collection.
    pub collection: &'a CollectionId,
    /// The group.
    pub group: &'a GroupId,
    /// The group's `n` after the change (part of the accumulator's associated data, §13.2).
    pub n: u64,
}

/// EP-6.
pub trait Sealer: Send + Sync {
    /// The DB-48 marker written into every file.
    fn sealer_id(&self) -> u16;
    /// Bytes sealing adds to a payload, a passage or an accumulator (AES-GCM-SIV: 28).
    fn seal_overhead(&self) -> usize;
    /// Bytes of a record-key envelope in each slot (AES-GCM-SIV: 60).
    fn envelope_len(&self) -> usize;

    /// A new record joins `owner.group`: its envelope and sealed payload.
    fn seal_record(
        &self,
        owner: &RecordOwner<'_>,
        payload: &[u8],
    ) -> Result<(Vec<u8>, Vec<u8>), Error>;
    /// Opens a stored payload.
    fn open_record(
        &self,
        owner: &RecordOwner<'_>,
        envelope: &[u8],
        sealed: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>, Error>;
    /// The record moves to another group (a flush, §15.2 step 3): its envelope for the new group.
    /// The payload ciphertext is unchanged.
    fn rewrap_record(
        &self,
        from: &RecordOwner<'_>,
        to: &RecordOwner<'_>,
        envelope: &[u8],
    ) -> Result<Vec<u8>, Error>;
    /// Seals passage text under the record's key (§13.2 row 2).
    fn seal_passage(
        &self,
        owner: &RecordOwner<'_>,
        envelope: &[u8],
        text: &[u8],
    ) -> Result<Vec<u8>, Error>;
    /// Opens passage text.
    fn open_passage(
        &self,
        owner: &RecordOwner<'_>,
        envelope: &[u8],
        sealed: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>, Error>;

    /// The header's `seal_version` after a change: `prev` is `None` for a new group; `departure`
    /// is true when a record left the group in this transaction (§13.3: the domain rotates).
    fn next_version(&self, owner: &GroupOwner<'_>, prev: Option<u64>, departure: bool) -> u64;
    /// Seals a group accumulator under `version`.
    fn seal_accumulator(
        &self,
        owner: &GroupOwner<'_>,
        version: u64,
        plaintext: &[u8],
    ) -> Result<Vec<u8>, Error>;
    /// Opens a group accumulator.
    fn open_accumulator(
        &self,
        owner: &GroupOwner<'_>,
        version: u64,
        sealed: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>, Error>;
}

/// No encryption (DB-48): the sealed bytes are the plaintext, envelopes are empty and
/// `seal_version` is always 0. Parts 2 and 3 make no confidentiality claim.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct PlaintextSealer;

fn no_envelope(envelope: &[u8]) -> Result<(), Error> {
    if envelope.is_empty() {
        Ok(())
    } else {
        Err(Error::IntegrityViolation {
            invariant: "DB-48 plaintext envelope",
        })
    }
}

impl Sealer for PlaintextSealer {
    fn sealer_id(&self) -> u16 {
        sever_format::SEALER_PLAINTEXT
    }
    fn seal_overhead(&self) -> usize {
        0
    }
    fn envelope_len(&self) -> usize {
        0
    }
    fn seal_record(
        &self,
        _: &RecordOwner<'_>,
        payload: &[u8],
    ) -> Result<(Vec<u8>, Vec<u8>), Error> {
        Ok((Vec::new(), payload.to_vec()))
    }
    fn open_record(
        &self,
        _: &RecordOwner<'_>,
        envelope: &[u8],
        sealed: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>, Error> {
        no_envelope(envelope)?;
        Ok(Zeroizing::new(sealed.to_vec()))
    }
    fn rewrap_record(
        &self,
        _: &RecordOwner<'_>,
        _: &RecordOwner<'_>,
        envelope: &[u8],
    ) -> Result<Vec<u8>, Error> {
        no_envelope(envelope)?;
        Ok(Vec::new())
    }
    fn seal_passage(
        &self,
        _: &RecordOwner<'_>,
        envelope: &[u8],
        text: &[u8],
    ) -> Result<Vec<u8>, Error> {
        no_envelope(envelope)?;
        Ok(text.to_vec())
    }
    fn open_passage(
        &self,
        _: &RecordOwner<'_>,
        envelope: &[u8],
        sealed: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>, Error> {
        no_envelope(envelope)?;
        Ok(Zeroizing::new(sealed.to_vec()))
    }
    fn next_version(&self, _: &GroupOwner<'_>, _: Option<u64>, _: bool) -> u64 {
        0
    }
    fn seal_accumulator(
        &self,
        _: &GroupOwner<'_>,
        _: u64,
        plaintext: &[u8],
    ) -> Result<Vec<u8>, Error> {
        Ok(plaintext.to_vec())
    }
    fn open_accumulator(
        &self,
        _: &GroupOwner<'_>,
        version: u64,
        sealed: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>, Error> {
        if version != 0 {
            return Err(Error::IntegrityViolation {
                invariant: "DB-48 plaintext seal_version",
            });
        }
        Ok(Zeroizing::new(sealed.to_vec()))
    }
}
