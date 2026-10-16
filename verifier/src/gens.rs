//! The generators `H` and `G_0 … G_{d−1}` (spec §9.2), `gdigest` (§9.6) and the startup
//! self-check the verifier runs with its own code (§9.2, SR-9.2-4; DB-77, DB-52).

use curve25519_dalek::ristretto::{CompressedRistretto, RistrettoPoint};
use sha2::{Digest, Sha512};

use crate::dst::DST_GEN;
use crate::hex;
use crate::xmd::expand_message_xmd_sha512;

/// The bundled generator golden file (spec Appendix B 1–2), part of the trust anchors (§11.3).
pub const GOLDEN_GENERATORS: &str = include_str!("../../golden/p3_generators.json");
/// RFC 9496 Appendix A known answers (one-way map, encodings).
pub const KAT_RISTRETTO: &str = include_str!("../../golden/p3_rfc9496_ristretto255.json");
/// RFC 9380 Appendix K.3 known answers (`expand_message_xmd`, SHA-512).
pub const KAT_XMD: &str = include_str!("../../golden/p3_rfc9380_k3_expand_xmd_sha512.json");

/// Why the self-check refused to run.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SelfCheckFailed(pub &'static str);

/// The generators of one dimension.
#[derive(Clone, Debug)]
pub struct Generators {
    /// `H`.
    pub h: RistrettoPoint,
    /// `G_0 … G_{d−1}`.
    pub g: Vec<RistrettoPoint>,
    /// `SHA-512(H ‖ G_0 ‖ … ‖ G_{d−1})` over the encodings (§9.6).
    pub gdigest: [u8; 64],
}

fn hash_to_group(msg: &[u8]) -> Option<RistrettoPoint> {
    let u: [u8; 64] = expand_message_xmd_sha512(msg, DST_GEN, 64)?
        .try_into()
        .ok()?;
    Some(RistrettoPoint::from_uniform_bytes(&u))
}

/// `H = hash_to_group(b"H")` (§9.2).
pub fn generator_h() -> Option<RistrettoPoint> {
    hash_to_group(b"H")
}

/// `G_i = hash_to_group(b"G" ‖ u32be(i))` (§9.2).
pub fn generator_g(i: u32) -> Option<RistrettoPoint> {
    let mut m = vec![b'G'];
    m.extend_from_slice(&i.to_be_bytes());
    hash_to_group(&m)
}

impl Generators {
    /// Derives the generators of dimension `d` (§9.2) and `gdigest` (§9.6).
    pub fn derive(d: usize) -> Option<Self> {
        let h = generator_h()?;
        let g = (0..u32::try_from(d).ok()?)
            .map(generator_g)
            .collect::<Option<Vec<_>>>()?;
        let mut dig = Sha512::new();
        dig.update(h.compress().as_bytes());
        for p in &g {
            dig.update(p.compress().as_bytes());
        }
        Some(Self {
            h,
            g,
            gdigest: dig.finalize().into(),
        })
    }

    /// The dimension.
    pub fn d(&self) -> usize {
        self.g.len()
    }
}

fn field<'a>(v: &'a serde_json::Value, k: &str) -> Result<&'a str, SelfCheckFailed> {
    v.get(k)
        .and_then(serde_json::Value::as_str)
        .ok_or(SelfCheckFailed("golden file unreadable"))
}

fn point_hex(p: &RistrettoPoint) -> String {
    hex::encode(p.compress().as_bytes())
}

/// The RFC 9380 Appendix K.3 known answers for `expand_message_xmd` (SHA-512).
pub fn check_xmd(kat: &str) -> Result<(), SelfCheckFailed> {
    let bad = SelfCheckFailed("RFC 9380 K.3 expand_message_xmd");
    let v: serde_json::Value = serde_json::from_str(kat).map_err(|_| bad)?;
    let dst = field(&v, "dst")?.as_bytes();
    let vectors = v.get("vectors").and_then(|x| x.as_array()).ok_or(bad)?;
    if vectors.is_empty() {
        return Err(bad);
    }
    for t in vectors {
        let len = t
            .get("len_in_bytes")
            .and_then(serde_json::Value::as_u64)
            .ok_or(bad)?;
        let out = expand_message_xmd_sha512(
            field(t, "msg")?.as_bytes(),
            dst,
            usize::try_from(len).map_err(|_| bad)?,
        )
        .ok_or(bad)?;
        if hex::encode(&out) != field(t, "uniform_bytes")? {
            return Err(bad);
        }
    }
    Ok(())
}

/// The RFC 9496 Appendix A known answers: the one-way map, and the invalid encodings refused.
pub fn check_ristretto(kat: &str) -> Result<(), SelfCheckFailed> {
    let bad = SelfCheckFailed("RFC 9496 ristretto255");
    let v: serde_json::Value = serde_json::from_str(kat).map_err(|_| bad)?;
    let maps = v
        .get("from_uniform_bytes")
        .and_then(|x| x.as_array())
        .ok_or(bad)?;
    for t in maps {
        let input: [u8; 64] = hex::decode_n(field(t, "input")?).ok_or(bad)?;
        if point_hex(&RistrettoPoint::from_uniform_bytes(&input)) != field(t, "output")? {
            return Err(bad);
        }
    }
    let invalid = v
        .get("invalid_encodings")
        .and_then(|x| x.as_array())
        .ok_or(bad)?;
    for t in invalid {
        let b: [u8; 32] = hex::decode_n(t.as_str().ok_or(bad)?).ok_or(bad)?;
        if CompressedRistretto(b).decompress().is_some() {
            return Err(bad);
        }
    }
    if maps.is_empty() || invalid.is_empty() {
        return Err(bad);
    }
    Ok(())
}

/// The startup self-check (§9.2): the known-answer tests, then `H`, `G_0` and `G_383` against the
/// golden file at every `d`, and `gdigest` when `d = 384`.
pub fn self_check(gens: &Generators, golden: &str) -> Result<(), SelfCheckFailed> {
    check_xmd(KAT_XMD)?;
    check_ristretto(KAT_RISTRETTO)?;
    let bad = SelfCheckFailed("§9.2 generators differ from the golden file");
    let v: serde_json::Value =
        serde_json::from_str(golden).map_err(|_| SelfCheckFailed("golden file unreadable"))?;
    if field(&v, "dst_gen")?.as_bytes() != DST_GEN {
        return Err(bad);
    }
    let g383 = match gens.g.get(383) {
        Some(p) => *p,
        None => generator_g(383).ok_or(bad)?,
    };
    let g0 = gens.g.first().ok_or(bad)?;
    if point_hex(&gens.h) != field(&v, "H")?
        || point_hex(g0) != field(&v, "G_0")?
        || point_hex(&g383) != field(&v, "G_383")?
    {
        return Err(bad);
    }
    if gens.d() == 384 && hex::encode(&gens.gdigest) != field(&v, "gdigest")? {
        return Err(bad);
    }
    Ok(())
}
