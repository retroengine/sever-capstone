//! `expand_message_xmd` with SHA-512 (RFC 9380 §5.3.1), implemented here because the pinned
//! `curve25519-dalek` does not provide it (§9.1, DB-52). Checked against RFC 9380 Appendix K.3.

use sha2::{Digest, Sha512};

use crate::CryptoError;

/// SHA-512 output size `b_in_bytes` (RFC 9380 §5.3.1).
const B_IN_BYTES: usize = 64;
/// SHA-512 input block size `s_in_bytes`, the length of `Z_pad` (RFC 9380 §5.3.1).
const S_IN_BYTES: usize = 128;

/// RFC 9380 §5.3.1 `expand_message_xmd(msg, DST, len_in_bytes)` with H = SHA-512.
pub fn expand_message_xmd_sha512(
    msg: &[u8],
    dst: &[u8],
    len_in_bytes: usize,
) -> Result<Vec<u8>, CryptoError> {
    // Steps 1-2: ell = ceil(len_in_bytes / b_in_bytes); abort if ell > 255, len_in_bytes > 65535
    // or len(DST) > 255.
    let ell = len_in_bytes.div_ceil(B_IN_BYTES);
    let (Ok(ell), Ok(len16), Ok(dst_len)) = (
        u8::try_from(ell),
        u16::try_from(len_in_bytes),
        u8::try_from(dst.len()),
    ) else {
        return Err(CryptoError::ExpandOutOfRange);
    };
    // Step 3: DST_prime = DST ‖ I2OSP(len(DST), 1).
    let dst_prime = |h: &mut Sha512| {
        h.update(dst);
        h.update([dst_len]);
    };
    // Steps 4-7: b_0 = H(Z_pad ‖ msg ‖ I2OSP(len_in_bytes, 2) ‖ I2OSP(0, 1) ‖ DST_prime).
    let mut h = Sha512::new();
    h.update([0u8; S_IN_BYTES]);
    h.update(msg);
    h.update(len16.to_be_bytes());
    h.update([0u8]);
    dst_prime(&mut h);
    let b_0 = h.finalize();
    // Steps 8-10: b_1 = H(b_0 ‖ I2OSP(1, 1) ‖ DST_prime);
    // b_i = H(strxor(b_0, b_(i−1)) ‖ I2OSP(i, 1) ‖ DST_prime); uniform_bytes = b_1 ‖ … ‖ b_ell.
    let mut out = Vec::with_capacity(usize::from(ell) * B_IN_BYTES);
    let mut prev = [0u8; B_IN_BYTES]; // strxor(b_0, 0…0) = b_0 for i = 1
    for i in 1..=ell {
        let mut h = Sha512::new();
        let x: Vec<u8> = b_0.iter().zip(prev.iter()).map(|(a, b)| a ^ b).collect();
        h.update(&x);
        h.update([i]);
        dst_prime(&mut h);
        let b_i = h.finalize();
        prev.copy_from_slice(&b_i);
        out.extend_from_slice(&b_i);
    }
    // Step 11: the first len_in_bytes bytes.
    out.truncate(len_in_bytes);
    Ok(out)
}
