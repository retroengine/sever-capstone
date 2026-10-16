//! The proof of knowledge of the group state: verification only (spec §9.5).

use curve25519_dalek::ristretto::{CompressedRistretto, RistrettoPoint};
use curve25519_dalek::scalar::Scalar;
use curve25519_dalek::traits::VartimeMultiscalarMul;
use sha2::{Digest, Sha512};

use crate::dst::DST_POSK;
use crate::gens::Generators;

/// `ctx = C_S_pre ‖ C_t ‖ scrambled_id ‖ u64be(database_lsn) ‖ collection_id`, 152 bytes (§9.5).
pub fn ctx(
    c_s_pre: &[u8; 32],
    c_t: &[u8; 32],
    scrambled_id: &[u8; 64],
    database_lsn: u64,
    collection_id: &[u8; 16],
) -> [u8; 152] {
    let mut out = [0u8; 152];
    let parts: [&[u8]; 5] = [
        c_s_pre,
        c_t,
        scrambled_id,
        &database_lsn.to_be_bytes(),
        collection_id,
    ];
    let mut at = 0;
    for p in parts {
        if let Some(dst) = out.get_mut(at..at + p.len()) {
            dst.copy_from_slice(p);
        }
        at += p.len();
    }
    out
}

/// `c = from_bytes_mod_order_wide(SHA-512(DST_POSK ‖ C_S_post ‖ A ‖ ctx))` (§9.5).
pub fn challenge(c_s_post: &[u8; 32], a: &[u8; 32], ctx: &[u8; 152]) -> Scalar {
    let mut h = Sha512::new();
    h.update(DST_POSK);
    h.update(c_s_post);
    h.update(a);
    h.update(ctx);
    Scalar::from_bytes_mod_order_wide(&h.finalize().into())
}

/// A proof decoded canonically: `A` and `z_r, z_0 … z_{d−1}` (§9.5, §9.9).
#[derive(Clone, Debug)]
pub struct DecodedProof {
    /// The encoding of `A`.
    pub a_bytes: [u8; 32],
    /// `A`.
    pub a: RistrettoPoint,
    /// `z_r` then `z_0 … z_{d−1}`.
    pub z: Vec<Scalar>,
}

/// Decodes `A ‖ z_r ‖ z_0 … z_{d−1}` (32 + 32 + 32·d bytes), every element canonically.
pub fn decode(proof: &[u8], d: usize) -> Option<DecodedProof> {
    if proof.len() != 32 * (d + 2) {
        return None;
    }
    let mut chunks = proof.chunks_exact(32);
    let a_bytes: [u8; 32] = chunks.next()?.try_into().ok()?;
    let a = CompressedRistretto(a_bytes).decompress()?;
    let z = chunks
        .map(|c| {
            let b: [u8; 32] = c.try_into().ok()?;
            Option::<Scalar>::from(Scalar::from_canonical_bytes(b))
        })
        .collect::<Option<Vec<_>>>()?;
    Some(DecodedProof { a_bytes, a, z })
}

/// Accepts if and only if `z_r·H + Σ_i z_i·G_i = A + c·C_S_post` (§9.5 verifier).
pub fn verify(
    gens: &Generators,
    c_s_post_bytes: &[u8; 32],
    c_s_post: &RistrettoPoint,
    ctx: &[u8; 152],
    p: &DecodedProof,
) -> bool {
    if p.z.len() != gens.d() + 1 {
        return false;
    }
    let c = challenge(c_s_post_bytes, &p.a_bytes, ctx);
    let points = std::iter::once(&gens.h).chain(gens.g.iter());
    let lhs = RistrettoPoint::vartime_multiscalar_mul(p.z.iter(), points);
    lhs == p.a + c * c_s_post
}
