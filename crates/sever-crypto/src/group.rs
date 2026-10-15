//! ristretto255 encodings (§0.2, §9.9), `hash_to_group` (§9.2) and `scalar(v)` (§4.5).

use curve25519_dalek::ristretto::{CompressedRistretto, RistrettoPoint};
use curve25519_dalek::scalar::Scalar;

use crate::CryptoError;
use crate::xmd::expand_message_xmd_sha512;

/// RFC 9496 §4.3.4 one-way map from 64 uniform bytes to a point.
pub fn map_to_group(uniform: &[u8; 64]) -> RistrettoPoint {
    RistrettoPoint::from_uniform_bytes(uniform)
}

/// `hash_to_group(msg, dst)`: the one-way map of `expand_message_xmd_sha512(msg, dst, 64)` (§9.2).
pub fn hash_to_group(msg: &[u8], dst: &[u8]) -> Result<RistrettoPoint, CryptoError> {
    let u: [u8; 64] = expand_message_xmd_sha512(msg, dst, 64)?
        .try_into()
        .map_err(|_| CryptoError::ExpandOutOfRange)?;
    Ok(map_to_group(&u))
}

/// The 32-byte canonical encoding of a point; the identity is 32 zero bytes (§0.2).
pub fn encode_point(p: &RistrettoPoint) -> [u8; 32] {
    p.compress().to_bytes()
}

/// Decodes an untrusted point, rejecting every non-canonical encoding (§9.9). `curve25519-dalek`'s
/// decompression is RFC 9496 §4.3.1 `DECODE`, which rejects non-canonical and negative field
/// elements and non-square cases.
pub fn decode_point(bytes: &[u8]) -> Result<RistrettoPoint, CryptoError> {
    let c = CompressedRistretto::from_slice(bytes).map_err(|_| CryptoError::WrongLength)?;
    c.decompress().ok_or(CryptoError::NonCanonicalPoint)
}

/// The 32-byte little-endian encoding of a scalar mod ℓ (§0.2).
pub fn encode_scalar(s: &Scalar) -> [u8; 32] {
    s.to_bytes()
}

/// Decodes an untrusted scalar, rejecting any value `≥ ℓ` (§9.9).
pub fn decode_scalar(bytes: &[u8]) -> Result<Scalar, CryptoError> {
    let b: [u8; 32] = bytes.try_into().map_err(|_| CryptoError::WrongLength)?;
    #[cfg(feature = "sabotage-SB-19")]
    let decoded = Some(Scalar::from_bytes_mod_order(b)); // SB-19 (Build §2.6): reduce, never reject
    #[cfg(not(feature = "sabotage-SB-19"))]
    let decoded = Option::from(Scalar::from_canonical_bytes(b));
    decoded.ok_or(CryptoError::NonCanonicalScalar)
}

/// §4.5: `scalar(v) = v mod ℓ` for `v ≥ 0`, and `ℓ − (|v| mod ℓ)` for `v < 0`. Since
/// `|v| ≤ 2^63 < ℓ`, `|v| mod ℓ = |v|` and the negative case is the group negation of `|v|`.
pub fn scalar_from_i64(v: i64) -> Scalar {
    let m = Scalar::from(v.unsigned_abs());
    if v < 0 { -m } else { m }
}
