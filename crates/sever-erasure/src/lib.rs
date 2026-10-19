//! `sever-erasure`: the key-rotation participant (Part 4, Build 3-4 §2.4–2.5), EP-7.
//!
//! Every committed transaction in which a record leaves a key domain rotates that domain (§13.3);
//! the new group key reaches the key file before the `COMMIT` (phase A) and the old one is
//! overwritten after it (phase C, INV-13); the bucket blocks and the survivors' re-wrapped envelopes
//! go to the WAL in the same transaction and to the wrapped-key store in phase C (DB-90, DB-91); at
//! startup the store, the WAL tail and the key file are reconciled by INV-14 (§13.4).
//!
//! - [`records`]: the participant's WAL and store records and their monotonic merge.
//! - [`store`]: the wrapped-key store and its compaction.
//! - [`KeyRotationParticipant`]: the protocol.

mod participant;
pub mod records;
pub mod store;

pub use participant::{COMPACT_MIN_BYTES, KEYS_PATH, KeyRotationParticipant, parse_wal};

#[cfg(test)]
mod tests;
