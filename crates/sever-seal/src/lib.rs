//! `sever-seal`: sealer 1 of spec §14, AES-256-GCM-SIV (Part 4, Build 3-4 §2.4).
//!
//! - [`aead`]: RFC 8452 with a random 96-bit nonce and a 16-byte tag (§13.2), 28 bytes of overhead.
//! - [`ad`]: the associated data of every row of the §13.2 table.
//! - [`block`]: record-key envelopes (§14.4, 60 bytes) and bucket blocks (§14.5, 4,352 bytes).
//! - [`ring`]: the key ring the sealer shares with the key-rotation participant: every domain's
//!   keys, every live record's current envelope (DB-91), and the transaction's stage.
//! - [`AeadSealer`]: EP-6 over the ring.

pub mod ad;
pub mod aead;
pub mod block;
pub mod ring;
mod sealer;

pub use ring::KeyRing;
pub use sealer::{AeadSealer, domain};

#[cfg(test)]
mod tests;
