//! `sever-crypto`: Part 3's cryptography (Build 3-4 §1.4; spec §4.5, §9).
//!
//! This first layer holds the primitives every later piece is built from:
//!
//! - the domain strings of §2.3 ([`dst`]);
//! - `expand_message_xmd` with SHA-512 (RFC 9380 §5.3.1), the one primitive the project implements
//!   itself, because `curve25519-dalek 4.1.3` lacks it (§9.1, DB-52);
//! - `hash_to_group`: RFC 9496's one-way map on 64 expanded bytes (§9.2);
//! - canonical decoding of points and scalars (§9.9) and their encodings (§0.2);
//! - the integer-to-scalar map `scalar(v)` (§4.5);
//! - the generators `H, G_0 … G_{d−1}`, `gdigest` and the startup self-check (§9.2, §9.6, INV-10);
//! - record and group commitments and the public transition check (§9.3).

#![forbid(unsafe_code)]

mod commit;
pub mod dst;
pub(crate) mod generators;
mod group;
mod xmd;

pub use commit::{commit_group, commit_record, decode_record_commitment, transition_holds};
pub use curve25519_dalek::ristretto::RistrettoPoint;
pub use curve25519_dalek::scalar::Scalar;
pub use generators::{
    GOLDEN, GeneratorGolden, Generators, KAT_MAP, KAT_XMD, KAT_XMD_DST, self_check,
};
pub use group::{
    decode_point, decode_scalar, encode_point, encode_scalar, hash_to_group, map_to_group,
    scalar_from_i64,
};
pub use xmd::expand_message_xmd_sha512;

/// Why a cryptographic input was refused. Carries no input bytes (§17).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CryptoError {
    /// An encoding is not exactly the size its type needs (32 bytes for points and scalars).
    WrongLength,
    /// §9.9: not the canonical encoding of a ristretto255 point.
    NonCanonicalPoint,
    /// §9.9: not the canonical encoding of a scalar (the value is `≥ ℓ`).
    NonCanonicalScalar,
    /// RFC 9380 §5.3.1 step 3: the requested length or the DST is out of range.
    ExpandOutOfRange,
    /// §9.9: a record commitment `C_t` is the identity.
    IdentityCommitment,
    /// §9.2 startup self-check failed (INV-10); names the check, never a value.
    SelfCheck(&'static str),
}

#[cfg(test)]
mod tests;
