//! Signatures and key epochs (§9.8): Ed25519 over domain-separated messages, always checked with
//! `verify_strict`, and the 90-day epochs of operator and witness keys.

use ed25519_dalek::{Signature, Signer, SigningKey, VerifyingKey};
use rand_core::{OsRng, RngCore};
use zeroize::Zeroize;

use crate::CryptoError;
use crate::dst::{DST_CERT, DST_COSIGN, DST_INSERT, DST_STH};

/// Length of the user insert-signature message (§9.8, Appendix A).
pub const INSERT_MESSAGE_LEN: usize = 65;
/// Length of the operator log-checkpoint message (§9.8).
pub const CHECKPOINT_MESSAGE_LEN: usize = 66;
/// Length of the witness cosignature message (§9.8).
pub const COSIGN_MESSAGE_LEN: usize = 83;
/// One key epoch: 90 days in milliseconds (§2.2, §9.8).
pub const EPOCH_MS: u64 = 90 * 24 * 60 * 60 * 1000;

/// An Ed25519 signing key. Generated only from the OS random source; loading a stored key is
/// [`KeyPair::from_secret`].
pub struct KeyPair(SigningKey);

impl KeyPair {
    /// A new key from 32 bytes of OS entropy.
    pub fn generate() -> Self {
        let mut secret = [0u8; 32];
        OsRng.fill_bytes(&mut secret);
        let k = Self(SigningKey::from_bytes(&secret));
        secret.zeroize();
        k
    }

    /// A stored key, from its 32-byte secret (RFC 8032 §5.1.5).
    pub fn from_secret(secret: &[u8; 32]) -> Self {
        Self(SigningKey::from_bytes(secret))
    }

    /// The 32-byte public key.
    pub fn public(&self) -> [u8; 32] {
        self.0.verifying_key().to_bytes()
    }

    /// Signs `msg` (RFC 8032 Ed25519; deterministic).
    pub fn sign(&self, msg: &[u8]) -> [u8; 64] {
        self.0.sign(msg).to_bytes()
    }
}

impl std::fmt::Debug for KeyPair {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("KeyPair(<secret>)") // §17: never print a key
    }
}

/// Verifies `sig` over `msg` under `public` with `verify_strict` (§9.8: small-order keys and
/// non-canonical encodings are rejected).
pub fn verify_signature(public: &[u8; 32], msg: &[u8], sig: &[u8; 64]) -> Result<(), CryptoError> {
    let pk = VerifyingKey::from_bytes(public).map_err(|_| CryptoError::BadSignature)?;
    let s = Signature::from_bytes(sig);
    pk.verify_strict(msg, &s)
        .map_err(|_| CryptoError::BadSignature)
}

/// §9.8 user insert signature message: `DST_INSERT ‖ collection_id ‖ C_t` (65 bytes).
pub fn insert_message(collection_id: &[u8; 16], c_t: &[u8; 32]) -> [u8; INSERT_MESSAGE_LEN] {
    let mut m = [0u8; INSERT_MESSAGE_LEN];
    fill(&mut m, &[DST_INSERT, collection_id, c_t]);
    m
}

/// §9.8 operator log-checkpoint message:
/// `DST_STH ‖ u64be tree_size ‖ root ‖ u64be timestamp_ms ‖ u32be epoch` (66 bytes).
pub fn checkpoint_message(
    tree_size: u64,
    root: &[u8; 32],
    timestamp_ms: u64,
    epoch: u32,
) -> [u8; CHECKPOINT_MESSAGE_LEN] {
    let mut m = [0u8; CHECKPOINT_MESSAGE_LEN];
    let parts: [&[u8]; 5] = [
        DST_STH,
        &tree_size.to_be_bytes(),
        root,
        &timestamp_ms.to_be_bytes(),
        &epoch.to_be_bytes(),
    ];
    fill(&mut m, &parts);
    m
}

/// §9.8 witness cosignature message: `DST_COSIGN ‖` the 66-byte log-checkpoint message (83 bytes).
pub fn cosign_message(checkpoint: &[u8; CHECKPOINT_MESSAGE_LEN]) -> [u8; COSIGN_MESSAGE_LEN] {
    let mut m = [0u8; COSIGN_MESSAGE_LEN];
    fill(&mut m, &[DST_COSIGN, checkpoint]);
    m
}

/// §9.8 operator certificate signature message: `DST_CERT ‖` certificate body (§11.1).
pub fn certificate_message(body: &[u8]) -> Vec<u8> {
    let mut m = Vec::with_capacity(DST_CERT.len() + body.len());
    m.extend_from_slice(DST_CERT);
    m.extend_from_slice(body);
    m
}

/// Concatenates `parts` into `out`, whose length is their total (fixed by the callers' types).
fn fill(out: &mut [u8], parts: &[&[u8]]) {
    let mut rest = out;
    for p in parts {
        let (head, tail) = rest.split_at_mut(p.len());
        head.copy_from_slice(p);
        rest = tail;
    }
}

/// §9.8: the epoch `e` with `genesis + 90·e days ≤ t < genesis + 90·(e+1) days`; `None` before
/// `genesis` or past the last `u32` epoch.
pub fn epoch_of(genesis_ms: u64, t_ms: u64) -> Option<u32> {
    let since = t_ms.checked_sub(genesis_ms)?;
    u32::try_from(since / EPOCH_MS).ok()
}
