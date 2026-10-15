//! Pedersen commitments (§9.3): `C_t = r_t·H + Σ scalar(x̃_i)·G_i` for a record,
//! `C_S = r_agg·H + Σ scalar(S_i)·G_i` for a group, and the public transition check.

use curve25519_dalek::ristretto::RistrettoPoint;
use curve25519_dalek::scalar::Scalar;
use curve25519_dalek::traits::{Identity, MultiscalarMul};

use crate::CryptoError;
use crate::generators::Generators;
use crate::group::{decode_point, scalar_from_i64};

/// `blind·H + Σ_i scalar(v_i)·G_i`, constant time in the secret inputs (they are secret: `x̃`, `S`,
/// `r_t`, `r_agg`). A zero scalar is accepted and contributes the identity (§9).
fn commit(
    gens: &Generators,
    values: impl ExactSizeIterator<Item = i64>,
    blind: &Scalar,
) -> Result<RistrettoPoint, CryptoError> {
    if values.len() != gens.d() {
        return Err(CryptoError::WrongLength);
    }
    let scalars = std::iter::once(*blind).chain(values.map(scalar_from_i64));
    let points = std::iter::once(gens.h()).chain(gens.g().iter());
    Ok(RistrettoPoint::multiscalar_mul(scalars, points))
}

/// §9.3 record commitment `C_t = r_t·H + Σ_i scalar(x̃_i)·G_i`; `x̃` must have `d` components.
pub fn commit_record(
    gens: &Generators,
    x: &[i32],
    r_t: &Scalar,
) -> Result<RistrettoPoint, CryptoError> {
    commit(gens, x.iter().map(|&v| i64::from(v)), r_t)
}

/// §9.3 group commitment `C_S = r_agg·H + Σ_i scalar(S_i)·G_i`; `S` must have `d` components.
pub fn commit_group(
    gens: &Generators,
    s: &[i64],
    r_agg: &Scalar,
) -> Result<RistrettoPoint, CryptoError> {
    commit(gens, s.iter().copied(), r_agg)
}

/// §9.3 public transition check of a deletion: `C_S_post + C_t = C_S_pre`.
pub fn transition_holds(
    c_s_post: &RistrettoPoint,
    c_t: &RistrettoPoint,
    c_s_pre: &RistrettoPoint,
) -> bool {
    c_s_post + c_t == *c_s_pre
}

/// Decodes an untrusted record commitment `C_t`: canonical (§9.9) and not the identity (§9.9,
/// "C_t MUST NOT be the identity").
pub fn decode_record_commitment(bytes: &[u8]) -> Result<RistrettoPoint, CryptoError> {
    let c = decode_point(bytes)?;
    if c == RistrettoPoint::identity() {
        return Err(CryptoError::IdentityCommitment);
    }
    Ok(c)
}
