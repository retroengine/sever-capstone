//! The commitment generators (§9.2), their digest (§9.6) and the startup self-check (§9.2, INV-10).

use curve25519_dalek::ristretto::RistrettoPoint;
use sha2::{Digest, Sha512};

use crate::CryptoError;
use crate::dst::DST_GEN;
use crate::group::{decode_point, encode_point, hash_to_group, map_to_group};
use crate::xmd::expand_message_xmd_sha512;

/// `H, G_0 … G_{d−1}` and `gdigest`, derived once at startup.
#[derive(Clone, Debug)]
pub struct Generators {
    h: RistrettoPoint,
    g: Vec<RistrettoPoint>,
    gdigest: [u8; 64],
}

/// §9.2: `G_i` from `msg = b"G" ‖ u32be(i)`.
fn generator_g(i: u32) -> Result<RistrettoPoint, CryptoError> {
    let mut msg = [0u8; 5];
    msg[0] = b'G';
    msg[1..].copy_from_slice(&i.to_be_bytes());
    hash_to_group(&msg, DST_GEN)
}

/// §9.2: `H` from `msg = b"H"`.
fn generator_h() -> Result<RistrettoPoint, CryptoError> {
    hash_to_group(b"H", DST_GEN)
}

impl Generators {
    /// Derives `H` and `G_0 … G_{d−1}`, one `expand_message` call each (§9.2), and
    /// `gdigest = SHA-512(H ‖ G_0 ‖ … ‖ G_{d−1})` over the encodings (§9.6).
    pub fn derive(d: usize) -> Result<Self, CryptoError> {
        let d32 = u32::try_from(d).map_err(|_| CryptoError::ExpandOutOfRange)?;
        let h = generator_h()?;
        let g = (0..d32).map(generator_g).collect::<Result<Vec<_>, _>>()?;
        let mut sha = Sha512::new();
        sha.update(encode_point(&h));
        for gi in &g {
            sha.update(encode_point(gi));
        }
        let gdigest: [u8; 64] = sha.finalize().into();
        Ok(Self { h, g, gdigest })
    }

    /// The dimension `d`.
    pub fn d(&self) -> usize {
        self.g.len()
    }

    /// The blinding generator `H`.
    pub fn h(&self) -> &RistrettoPoint {
        &self.h
    }

    /// `G_0 … G_{d−1}`.
    pub fn g(&self) -> &[RistrettoPoint] {
        &self.g
    }

    /// Test only: swaps `H` and `G_0` in memory, to show the self-check refuses it.
    #[cfg(test)]
    pub(crate) fn swap_h_g0_for_test(&mut self) {
        if let Some(g0) = self.g.first_mut() {
            std::mem::swap(&mut self.h, g0);
        }
    }

    /// `gdigest` (§9.6), the first message of the nonce transcript.
    pub fn gdigest(&self) -> &[u8; 64] {
        &self.gdigest
    }
}

/// The frozen generator values (`golden/p3_generators.json`, Appendix B vectors 1–2, written by the
/// reference model `sever_refmodel_certs`, DB-51). A test checks these constants against the file.
#[derive(Clone, Copy, Debug)]
pub struct GeneratorGolden {
    /// `H`.
    pub h: &'static str,
    /// `G_0`.
    pub g_0: &'static str,
    /// `G_383`.
    pub g_383: &'static str,
    /// `gdigest` at d = 384.
    pub gdigest_384: &'static str,
}

/// The values of `golden/p3_generators.json`.
pub const GOLDEN: GeneratorGolden = GeneratorGolden {
    h: "80162606b4d5c1e2f2c40f1d21a2338e768114d9fa841739788f0b0f018b2556",
    g_0: "46fd08889c692c2040cf735ad765e0a14a15c729b005926ae27922b1f9e46e3b",
    g_383: "c465fe97602fba52cc235da917cd7f5617484838cda4a5a5582d2da051d1425b",
    gdigest_384: "91632a1b7838973337c4e982ef7545102249c3f8a8bcefce1ebf881df9194d23\
                  82b3559d634896486152ed39eb99ac208e223a2f9b926281f2c37837636c9de7",
};

/// One RFC 9380 Appendix K.3 vector: `(msg, len_in_bytes, uniform_bytes)` (a test checks it
/// against `golden/p3_rfc9380_k3_expand_xmd_sha512.json`).
pub const KAT_XMD: (&str, usize, &str) = (
    "abc",
    32,
    "0da749f12fbe5483eb066a5f595055679b976e93abe9be6f0f6318bce7aca8dc",
);
/// The RFC 9380 Appendix K.3 DST.
pub const KAT_XMD_DST: &str = "QUUX-V01-CS02-with-expander-SHA512-256";
/// One RFC 9496 Appendix A.3 pair: 64 input bytes and the encoded output (checked against
/// `golden/p3_rfc9496_ristretto255.json`).
pub const KAT_MAP: (&str, &str) = (
    "5d1be09e3d0c82fc538112490e35701979d99e06ca3e2b5b54bffe8b4dc772c1\
     4d98b696a1bbfb5ca32c436cc61c16563790306c79eaca7705668b47dffe5bb6",
    "3066f82a1a747d45120d1740f14358531a8f04bbffe6a819f86dfe50f44a0a46",
);

fn unhex<const N: usize>(s: &str) -> Option<[u8; N]> {
    let s: Vec<u8> = s.bytes().filter(|b| !b.is_ascii_whitespace()).collect();
    if s.len() != 2 * N {
        return None;
    }
    let mut out = [0u8; N];
    for (o, pair) in out.iter_mut().zip(s.chunks_exact(2)) {
        let txt = std::str::from_utf8(pair).ok()?;
        *o = u8::from_str_radix(txt, 16).ok()?;
    }
    Some(out)
}

fn same_point(p: &RistrettoPoint, golden_hex: &str) -> bool {
    unhex::<32>(golden_hex)
        .and_then(|b| decode_point(&b).ok())
        .is_some_and(|q| q == *p)
}

/// §9.2 startup self-check (INV-10, DB-77): the RFC 9496 one-way-map and RFC 9380 K.3 known
/// answers hold, and `H`, `G_0` and `G_383` equal the golden file at every `d` (`G_383` is the
/// generator in use when `d > 383`, and is derived for the check otherwise); `gdigest` is compared
/// when `d = 384`. On any mismatch the engine refuses to run; the error names the failed check,
/// never a value.
pub fn self_check(gens: &Generators) -> Result<(), CryptoError> {
    self_check_against(gens, &GOLDEN)
}

pub(crate) fn self_check_against(
    gens: &Generators,
    golden: &GeneratorGolden,
) -> Result<(), CryptoError> {
    let fail = CryptoError::SelfCheck;
    // RFC known answers first: if the primitives drifted, nothing derived from them is trusted.
    let (msg, n, want) = KAT_XMD;
    let got = expand_message_xmd_sha512(msg.as_bytes(), KAT_XMD_DST.as_bytes(), n)?;
    if unhex::<32>(want).is_none_or(|w| got != w) {
        return Err(fail("RFC 9380 K.3 known answer"));
    }
    let input = unhex::<64>(KAT_MAP.0).ok_or(fail("RFC 9496 A.3 known answer"))?;
    if !same_point(&map_to_group(&input), KAT_MAP.1) {
        return Err(fail("RFC 9496 A.3 known answer"));
    }
    // The generators against the golden file.
    if !same_point(gens.h(), golden.h) {
        return Err(fail("generator H"));
    }
    let Some(g_0) = gens.g().first() else {
        return Err(fail("no generators"));
    };
    if !same_point(g_0, golden.g_0) {
        return Err(fail("generator G_0"));
    }
    let g_383 = match gens.g().get(383) {
        Some(g) => *g,
        None => generator_g(383)?,
    };
    if !same_point(&g_383, golden.g_383) {
        return Err(fail("generator G_383"));
    }
    if gens.d() == 384 && unhex::<64>(golden.gdigest_384).is_none_or(|w| w != *gens.gdigest()) {
        return Err(fail("gdigest"));
    }
    Ok(())
}
