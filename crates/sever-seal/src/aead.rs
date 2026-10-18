//! AES-256-GCM-SIV (RFC 8452) with a random 96-bit nonce and a 16-byte tag (spec §13.2): a sealed
//! value is `nonce (12) ‖ ciphertext ‖ tag (16)`, 28 bytes of overhead.

use aes_gcm_siv::aead::{Aead, KeyInit, Payload};
use aes_gcm_siv::{Aes256GcmSiv, Nonce};
use rand_core::{OsRng, RngCore};
use sever_keys::Key;
use sever_types::Error;
use zeroize::Zeroizing;

/// Nonce bytes (§13.2).
pub const NONCE_BYTES: usize = 12;
/// Tag bytes (§13.2).
pub const TAG_BYTES: usize = 16;
/// Bytes sealing adds (§13.2: 28).
pub const OVERHEAD: usize = NONCE_BYTES + TAG_BYTES;

/// A fresh nonce from the OS CSPRNG (§13.2, §18 `nonce: random_96_bit_os_csprng`).
fn fresh_nonce() -> [u8; NONCE_BYTES] {
    let mut n = [0u8; NONCE_BYTES];
    if cfg!(feature = "sabotage-SB-30") {
        // SB-30: reuse one nonce for everything.
        n.fill(0x5A);
    } else {
        OsRng.fill_bytes(&mut n);
    }
    n
}

fn cipher(key: &Key) -> Result<Aes256GcmSiv, Error> {
    Aes256GcmSiv::new_from_slice(key.as_bytes()).map_err(|_| aead_error())
}

fn aead_error() -> Error {
    Error::IntegrityViolation {
        invariant: "§13.2 AEAD",
    }
}

/// Seals `plaintext` under `key`, bound to `ad`, with a fresh nonce.
pub fn seal(key: &Key, ad: &[u8], plaintext: &[u8]) -> Result<Vec<u8>, Error> {
    seal_with_nonce(key, &fresh_nonce(), ad, plaintext)
}

/// Seals with a given nonce: the RFC 8452 vectors only; the engine always uses [`seal`].
pub fn seal_with_nonce(
    key: &Key,
    nonce: &[u8; NONCE_BYTES],
    ad: &[u8],
    plaintext: &[u8],
) -> Result<Vec<u8>, Error> {
    let ct = cipher(key)?
        .encrypt(
            Nonce::from_slice(nonce),
            Payload {
                msg: plaintext,
                aad: ad,
            },
        )
        .map_err(|_| aead_error())?;
    let mut out = Vec::with_capacity(NONCE_BYTES + ct.len());
    out.extend_from_slice(nonce);
    out.extend_from_slice(&ct);
    Ok(out)
}

/// Opens `nonce ‖ ciphertext ‖ tag` under `key` and `ad`; `IntegrityViolation` ("§13.2 AEAD") if
/// the tag does not verify (another key, another owner, another version, or a changed byte).
pub fn open(key: &Key, ad: &[u8], sealed: &[u8]) -> Result<Zeroizing<Vec<u8>>, Error> {
    if sealed.len() < OVERHEAD {
        return Err(aead_error());
    }
    let (nonce, ct) = sealed.split_at(NONCE_BYTES);
    cipher(key)?
        .decrypt(Nonce::from_slice(nonce), Payload { msg: ct, aad: ad })
        .map(Zeroizing::new)
        .map_err(|_| aead_error())
}
