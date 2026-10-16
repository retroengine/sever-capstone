//! Proof of knowledge of the group state after a deletion (§9.5): the deletion context, the
//! Fiat–Shamir challenge, the responses, the proof encoding and the verifier. The nonces come from
//! the hedged derivation of §9.6; [`prove_with_nonces`] takes them as given and is crate-internal.

use curve25519_dalek::ristretto::RistrettoPoint;
use curve25519_dalek::scalar::Scalar;
use curve25519_dalek::traits::{MultiscalarMul, VartimeMultiscalarMul};
use sha2::{Digest, Sha512};

use crate::CryptoError;
use crate::dst::DST_POSK;
use crate::generators::Generators;
use crate::group::{decode_point, decode_scalar, encode_point, scalar_from_i64};

/// Size of the deletion context (§9.5).
pub const CTX_LEN: usize = 152;
/// Size of the challenge preimage `DST_POSK ‖ C_S_post ‖ A ‖ ctx` (§9.5, Appendix A).
pub const CHALLENGE_PREIMAGE_LEN: usize = 231;

/// The deletion context of §9.5, bound into the challenge.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DeletionContext {
    /// `C_S_pre`, the group commitment before the deletion.
    pub c_s_pre: [u8; 32],
    /// `C_t`, the deleted record's commitment.
    pub c_t: [u8; 32],
    /// The record's `scrambled_id` (§9.7).
    pub scrambled_id: [u8; 64],
    /// This deletion's leaf index (§10.2).
    pub database_lsn: u64,
    /// The collection (§3.1).
    pub collection_id: [u8; 16],
}

impl DeletionContext {
    /// `ctx = C_S_pre (32) ‖ C_t (32) ‖ scrambled_id (64) ‖ u64be(database_lsn) ‖ collection_id (16)`.
    pub fn to_bytes(&self) -> [u8; CTX_LEN] {
        let mut out = [0u8; CTX_LEN];
        let parts: [&[u8]; 5] = [
            &self.c_s_pre,
            &self.c_t,
            &self.scrambled_id,
            &self.database_lsn.to_be_bytes(),
            &self.collection_id,
        ];
        let mut rest = out.as_mut_slice();
        for p in parts {
            let (head, tail) = rest.split_at_mut(p.len());
            head.copy_from_slice(p);
            rest = tail;
        }
        out
    }
}

/// `c = from_bytes_mod_order_wide(SHA-512(DST_POSK ‖ C_S_post ‖ A ‖ ctx))` (§9.5).
pub fn challenge(c_s_post: &[u8; 32], a: &[u8; 32], ctx: &[u8; CTX_LEN]) -> Scalar {
    let mut h = Sha512::new();
    h.update(DST_POSK);
    #[cfg(not(feature = "sabotage-SB-16"))]
    {
        h.update(c_s_post);
        h.update(a);
    }
    #[cfg(feature = "sabotage-SB-16")]
    {
        h.update(a); // SB-16 (Build §2.6): the preimage order is swapped
        h.update(c_s_post);
    }
    #[cfg(not(feature = "sabotage-SB-17"))]
    h.update(ctx);
    #[cfg(feature = "sabotage-SB-17")]
    let _ = ctx; // SB-17: the deletion context is left out of the challenge
    let wide: [u8; 64] = h.finalize().into();
    #[cfg(not(feature = "sabotage-SB-23"))]
    let c = Scalar::from_bytes_mod_order_wide(&wide);
    #[cfg(feature = "sabotage-SB-23")]
    let c = {
        // SB-23: reduce 32 bytes instead of 64
        let mut half = [0u8; 32];
        half.copy_from_slice(wide.get(..32).unwrap_or(&[0; 32]));
        Scalar::from_bytes_mod_order(half)
    };
    c
}

/// A proof `A ‖ z_r ‖ z_0 ‖ … ‖ z_{d−1}` (§9.5).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Proof {
    a: RistrettoPoint,
    z_r: Scalar,
    z: Vec<Scalar>,
}

impl Proof {
    /// The encoded size at dimension `d`: `32 + 32 + 32·d` (12,352 bytes at d = 384).
    pub fn encoded_len(d: usize) -> usize {
        64 + 32 * d
    }

    /// `A ‖ z_r ‖ z_0 ‖ … ‖ z_{d−1}`.
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut out = Vec::with_capacity(Self::encoded_len(self.z.len()));
        out.extend_from_slice(&encode_point(&self.a));
        out.extend_from_slice(self.z_r.as_bytes());
        for zi in &self.z {
            out.extend_from_slice(zi.as_bytes());
        }
        out
    }

    /// Strict decoding at dimension `d`: exact length, `A` and every `z` canonical (§9.5, §9.9).
    pub fn from_bytes(bytes: &[u8], d: usize) -> Result<Self, CryptoError> {
        if bytes.len() != Self::encoded_len(d) {
            return Err(CryptoError::WrongLength);
        }
        let mut chunks = bytes.chunks_exact(32);
        let mut next = || chunks.next().ok_or(CryptoError::WrongLength);
        let a = decode_point(next()?)?;
        let z_r = decode_scalar(next()?)?;
        let z = (0..d)
            .map(|_| decode_scalar(next()?))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Self { a, z_r, z })
    }
}

/// The §9.5 prover with the nonces `(k_r, k_0 … k_{d−1})` given. Only the hedged prover of §9.6
/// may call it outside tests: reusing a nonce vector would reveal the group's sum.
pub(crate) fn prove_with_nonces(
    gens: &Generators,
    s_post: &[i64],
    r_post: &Scalar,
    ctx: &DeletionContext,
    k_r: &Scalar,
    k: &[Scalar],
) -> Result<Proof, CryptoError> {
    let d = gens.d();
    if s_post.len() != d || k.len() != d {
        return Err(CryptoError::WrongLength);
    }
    let s: Vec<Scalar> = s_post.iter().map(|&v| scalar_from_i64(v)).collect();
    let c_s_post = RistrettoPoint::multiscalar_mul(
        std::iter::once(r_post).chain(s.iter()),
        std::iter::once(gens.h()).chain(gens.g().iter()),
    );
    // A = k_r·H + Σ k_i·G_i, constant time: the nonces are secret.
    let a = RistrettoPoint::multiscalar_mul(
        std::iter::once(k_r).chain(k.iter()),
        std::iter::once(gens.h()).chain(gens.g().iter()),
    );
    let c = challenge(&encode_point(&c_s_post), &encode_point(&a), &ctx.to_bytes());
    let z_r = k_r + c * r_post;
    let z = k.iter().zip(&s).map(|(ki, si)| ki + c * si).collect();
    Ok(Proof { a, z_r, z })
}

/// The §9.5 verifier: decode the proof strictly, recompute `c`, and accept if and only if
/// `z_r·H + Σ_i z_i·G_i = A + c·C_S_post`. Every input is public, so variable time is fine.
pub fn verify(
    gens: &Generators,
    c_s_post: &[u8; 32],
    ctx: &DeletionContext,
    proof: &[u8],
) -> Result<(), CryptoError> {
    let p = Proof::from_bytes(proof, gens.d())?;
    let c_pt = decode_point(c_s_post)?;
    let a_bytes = encode_point(&p.a);
    let c = challenge(c_s_post, &a_bytes, &ctx.to_bytes());
    if equation_holds(gens, &c_pt, &p.a, &c, &p.z_r, &p.z) {
        Ok(())
    } else {
        Err(CryptoError::ProofInvalid)
    }
}

/// The Σ-protocol's verification equation (§9.5): `z_r·H + Σ_i z_i·G_i = A + c·C_S_post`, for a
/// given challenge (docs/SOUNDNESS.md: the simulator's transcripts satisfy it with no opening).
pub(crate) fn equation_holds(
    gens: &Generators,
    c_s_post: &RistrettoPoint,
    a: &RistrettoPoint,
    c: &Scalar,
    z_r: &Scalar,
    z: &[Scalar],
) -> bool {
    if z.len() != gens.d() {
        return false;
    }
    let lhs = RistrettoPoint::vartime_multiscalar_mul(
        std::iter::once(z_r).chain(z.iter()),
        std::iter::once(gens.h()).chain(gens.g().iter()),
    );
    lhs == a + c * c_s_post
}
