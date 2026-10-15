//! Hedged nonce derivation (§9.6) and the public prover.
//!
//! The nonces come from three sources at once: the secret witness, the public statement and fresh
//! OS entropy, so neither a broken random source nor a fault injected mid-proof can repeat a nonce
//! vector (reusing one would reveal the group's whole sum, §9.5).

use curve25519_dalek::scalar::Scalar;
use merlin::Transcript;
use rand_core::{CryptoRng, OsRng, RngCore};
use zeroize::Zeroize;

use crate::dst::DST_NONCE;
use crate::generators::Generators;
use crate::group::{encode_point, scalar_from_i64};
use crate::posk::{DeletionContext, Proof, prove_with_nonces};
use crate::{CryptoError, commit_group};

/// The only random source [`prove`] accepts (§9.6): a zero-sized wrapper around `OsRng` that
/// implements `RngCore + CryptoRng` and deliberately not `SeedableRng`, so a seeded generator cannot
/// be wired into proof generation.
///
/// Passing any other generator to `prove` does not compile:
///
/// ```compile_fail
/// # use sever_crypto::*;
/// struct Seeded([u8; 32]);
/// impl rand_core::RngCore for Seeded {
///     fn next_u32(&mut self) -> u32 { 7 }
///     fn next_u64(&mut self) -> u64 { 7 }
///     fn fill_bytes(&mut self, d: &mut [u8]) { d.fill(7) }
///     fn try_fill_bytes(&mut self, d: &mut [u8]) -> Result<(), rand_core::Error> { d.fill(7); Ok(()) }
/// }
/// impl rand_core::CryptoRng for Seeded {}
/// impl rand_core::SeedableRng for Seeded {
///     type Seed = [u8; 32];
///     fn from_seed(s: [u8; 32]) -> Self { Seeded(s) }
/// }
/// let gens = Generators::derive(8).unwrap();
/// let ctx = DeletionContext { c_s_pre: [0; 32], c_t: [0; 32], scrambled_id: [0; 64],
///                             database_lsn: 1, collection_id: [0; 16] };
/// let mut rng = <Seeded as rand_core::SeedableRng>::from_seed([1; 32]);
/// let _ = prove(&gens, &[0; 8], &Scalar::ZERO, &ctx, &mut rng);
/// ```
///
/// The same call with this type compiles:
///
/// ```
/// # use sever_crypto::*;
/// let gens = Generators::derive(8).unwrap();
/// let ctx = DeletionContext { c_s_pre: [0; 32], c_t: [0; 32], scrambled_id: [0; 64],
///                             database_lsn: 1, collection_id: [0; 16] };
/// let mut rng = StrictProofRng::new();
/// let _ = prove(&gens, &[0; 8], &Scalar::ZERO, &ctx, &mut rng);
/// ```
///
/// and it is not seedable:
///
/// ```compile_fail
/// fn seedable<T: rand_core::SeedableRng>() {}
/// seedable::<sever_crypto::StrictProofRng>();
/// ```
#[derive(Debug, Default)]
pub struct StrictProofRng {
    _private: (),
}

impl StrictProofRng {
    /// The OS random source; there is no constructor that takes a seed.
    pub fn new() -> Self {
        Self { _private: () }
    }
}

impl RngCore for StrictProofRng {
    fn next_u32(&mut self) -> u32 {
        OsRng.next_u32()
    }
    fn next_u64(&mut self) -> u64 {
        OsRng.next_u64()
    }
    fn fill_bytes(&mut self, dest: &mut [u8]) {
        OsRng.fill_bytes(dest)
    }
    fn try_fill_bytes(&mut self, dest: &mut [u8]) -> Result<(), rand_core::Error> {
        OsRng.try_fill_bytes(dest)
    }
}

impl CryptoRng for StrictProofRng {}

/// SB-18 (Build §2.6): a source with no entropy, so proving the same statement twice reuses the
/// nonce vector.
#[cfg(feature = "sabotage-SB-18")]
struct NoEntropy;
#[cfg(feature = "sabotage-SB-18")]
impl RngCore for NoEntropy {
    fn next_u32(&mut self) -> u32 {
        0
    }
    fn next_u64(&mut self) -> u64 {
        0
    }
    fn fill_bytes(&mut self, dest: &mut [u8]) {
        dest.fill(0)
    }
    fn try_fill_bytes(&mut self, dest: &mut [u8]) -> Result<(), rand_core::Error> {
        dest.fill(0);
        Ok(())
    }
}
#[cfg(feature = "sabotage-SB-18")]
impl CryptoRng for NoEntropy {}

/// §9.6: the hedged nonces `(k_r, k_0 … k_{d−1})` for statement `C_S_post`, context `ctx` and
/// witness `(r_post, s_0 … s_{d−1})`. Crate-internal and generic only so that a test can follow
/// the steps with a fixed source; [`prove`] calls it with [`StrictProofRng`] alone.
pub(crate) fn hedged_nonces<R: RngCore + CryptoRng>(
    gens: &Generators,
    c_s_post: &[u8; 32],
    ctx: &DeletionContext,
    r_post: &Scalar,
    s: &[Scalar],
    entropy: &mut R,
) -> (Scalar, Vec<Scalar>) {
    let mut t = Transcript::new(DST_NONCE);
    t.append_message(b"gens", gens.gdigest());
    t.append_message(b"stmt", c_s_post);
    t.append_message(b"ctx", &ctx.to_bytes());
    let mut b = t
        .build_rng()
        .rekey_with_witness_bytes(b"r", r_post.as_bytes());
    for si in s {
        b = b.rekey_with_witness_bytes(b"s", si.as_bytes());
    }
    let mut rng = b.finalize(entropy); // injects 32 bytes from `entropy`
    let mut buf = [0u8; 64];
    let mut next = || {
        rng.fill_bytes(&mut buf);
        let k = Scalar::from_bytes_mod_order_wide(&buf);
        buf.zeroize();
        k
    };
    let k_r = next(); // k_r, then k_0 … k_{d−1}, in that order
    let k = (0..s.len()).map(|_| next()).collect();
    (k_r, k)
}

/// §9.5 prover with §9.6 hedged nonces: proves knowledge of `(r_post, scalar(S_post_i))` for
/// `C_S_post = r_post·H + Σ scalar(S_post_i)·G_i`, bound to `ctx`. Accepts only [`StrictProofRng`].
pub fn prove(
    gens: &Generators,
    s_post: &[i64],
    r_post: &Scalar,
    ctx: &DeletionContext,
    rng: &mut StrictProofRng,
) -> Result<Proof, CryptoError> {
    let c_s_post = encode_point(&commit_group(gens, s_post, r_post)?);
    let mut s: Vec<Scalar> = s_post.iter().map(|&v| scalar_from_i64(v)).collect();
    #[cfg(not(feature = "sabotage-SB-18"))]
    let (mut k_r, mut k) = hedged_nonces(gens, &c_s_post, ctx, r_post, &s, rng);
    #[cfg(feature = "sabotage-SB-18")]
    let (mut k_r, mut k) = {
        let _ = rng;
        hedged_nonces(gens, &c_s_post, ctx, r_post, &s, &mut NoEntropy)
    };
    let proof = prove_with_nonces(gens, s_post, r_post, ctx, &k_r, &k);
    k_r.zeroize();
    k.zeroize();
    s.zeroize();
    proof
}
