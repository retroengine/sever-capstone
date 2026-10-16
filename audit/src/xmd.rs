//! `expand_message_xmd` with SHA-512, written from RFC 9380 §5.3.1 (spec §9.1: the one primitive
//! the project implements; the verifier has its own copy, DB-52).

use sha2::{Digest, Sha512};

/// SHA-512's output size `b_in_bytes`.
const B_IN_BYTES: usize = 64;
/// SHA-512's input block size `s_in_bytes`.
const S_IN_BYTES: usize = 128;

/// `expand_message_xmd(msg, DST, len_in_bytes)` (RFC 9380 §5.3.1), or `None` when the RFC aborts
/// (`ell > 255`, `len_in_bytes > 65535` or `len(DST) > 255`).
pub fn expand_message_xmd_sha512(msg: &[u8], dst: &[u8], len_in_bytes: usize) -> Option<Vec<u8>> {
    // 1. ell = ceil(len_in_bytes / b_in_bytes)
    let ell = len_in_bytes.div_ceil(B_IN_BYTES);
    // 2. ABORT if ell > 255 or len_in_bytes > 65535 or len(DST) > 255
    if ell > 255 || len_in_bytes > 65535 {
        return None;
    }
    let dst_len = u8::try_from(dst.len()).ok()?;
    let ell = u8::try_from(ell).ok()?;
    let len = u16::try_from(len_in_bytes).ok()?;
    // 3. DST_prime = DST || I2OSP(len(DST), 1)
    let mut dst_prime = dst.to_vec();
    dst_prime.push(dst_len);
    // 4.–7. msg_prime = Z_pad || msg || l_i_b_str || I2OSP(0, 1) || DST_prime
    let mut h = Sha512::new();
    h.update([0u8; S_IN_BYTES]);
    h.update(msg);
    h.update(len.to_be_bytes());
    h.update([0u8]);
    h.update(&dst_prime);
    // 8. b_0 = H(msg_prime)
    let b0: [u8; B_IN_BYTES] = h.finalize().into();
    // 9. b_1 = H(b_0 || I2OSP(1, 1) || DST_prime)
    let mut h = Sha512::new();
    h.update(b0);
    h.update([1u8]);
    h.update(&dst_prime);
    let mut prev: [u8; B_IN_BYTES] = h.finalize().into();
    let mut out = Vec::with_capacity(usize::from(ell) * B_IN_BYTES);
    out.extend_from_slice(&prev);
    // 10. for i in (2, …, ell): b_i = H(strxor(b_0, b_(i - 1)) || I2OSP(i, 1) || DST_prime)
    for i in 2..=ell {
        let mut x = [0u8; B_IN_BYTES];
        for ((o, a), b) in x.iter_mut().zip(b0.iter()).zip(prev.iter()) {
            *o = a ^ b;
        }
        let mut h = Sha512::new();
        h.update(x);
        h.update([i]);
        h.update(&dst_prime);
        prev = h.finalize().into();
        out.extend_from_slice(&prev);
    }
    // 11.–12. uniform_bytes = b_1 || … || b_ell, truncated to len_in_bytes
    out.truncate(len_in_bytes);
    Some(out)
}
