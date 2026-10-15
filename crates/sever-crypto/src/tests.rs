//! Tests of the primitives layer. Expected values come from the spec (oracle A) or from the RFC
//! texts through `golden/p3_rfc*.json` (oracle B, extracted by `sever_testkit_p3.rfc_vectors`).

use serde_json::Value;
use sever_spec::spec;

use super::*;
use crate::dst::*;

const K3: &str = include_str!("../../../golden/p3_rfc9380_k3_expand_xmd_sha512.json");
const R9496: &str = include_str!("../../../golden/p3_rfc9496_ristretto255.json");

fn unhex(s: &str) -> Vec<u8> {
    assert!(s.len() % 2 == 0, "odd hex length");
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn json(s: &str) -> Value {
    serde_json::from_str(s).unwrap()
}

#[test]
// oracle: A §2.3 domain-string table, bytes and lengths copied by hand
#[spec("SR-2.3-1")]
fn p3_crypto_domain_strings_are_the_exact_bytes_of_section_2_3() {
    let table: [(&[u8], &str, usize); 7] = [
        (DST_GEN, "PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS", 41),
        (DST_POSK, "SEVERDB_POSK_V1", 15),
        (DST_NONCE, "SEVERDB_POSK_NONCE_V1", 21),
        (DST_INSERT, "SEVERDB-INSERT-V1", 17),
        (DST_STH, "SEVERDB-STH-V1", 14),
        (DST_COSIGN, "SEVERDB-COSIGN-V1", 17),
        (DST_CERT, "SEVERDB-CERT-V1", 15),
    ];
    for (got, want, len) in table {
        assert_eq!(got, want.as_bytes());
        assert_eq!(got.len(), len, "{want}");
        assert!(got.is_ascii());
    }
}

#[test]
// oracle: B RFC 9380 Appendix K.3 (golden/p3_rfc9380_k3_expand_xmd_sha512.json)
#[spec("SR-9.2-2")]
fn p3_crypto_expand_message_xmd_matches_rfc9380_k3() {
    let k3 = json(K3);
    let dst = k3["dst"].as_str().unwrap().as_bytes();
    let vectors = k3["vectors"].as_array().unwrap();
    assert_eq!(vectors.len(), 10);
    for v in vectors {
        let msg = v["msg"].as_str().unwrap().as_bytes();
        let n = usize::try_from(v["len_in_bytes"].as_u64().unwrap()).unwrap();
        let got = expand_message_xmd_sha512(msg, dst, n).unwrap();
        assert_eq!(
            hex(&got),
            v["uniform_bytes"].as_str().unwrap(),
            "msg len {}",
            msg.len()
        );
    }
}

#[test]
// oracle: A RFC 9380 §5.3.1 step 3, the abort conditions (ell > 255, len > 65535, DST > 255 bytes)
fn p3_crypto_expand_message_xmd_refuses_out_of_range_requests() {
    assert_eq!(
        expand_message_xmd_sha512(b"", b"d", 255 * 64 + 1),
        Err(CryptoError::ExpandOutOfRange)
    );
    assert_eq!(
        expand_message_xmd_sha512(b"", &[b'd'; 256], 64),
        Err(CryptoError::ExpandOutOfRange)
    );
    assert_eq!(
        expand_message_xmd_sha512(b"", b"d", 255 * 64)
            .unwrap()
            .len(),
        255 * 64
    );
    assert_eq!(
        expand_message_xmd_sha512(b"", &[b'd'; 255], 64)
            .unwrap()
            .len(),
        64
    );
}

#[test]
// oracle: B RFC 9496 Appendix A.3 (golden/p3_rfc9496_ristretto255.json)
#[spec("SR-9.2-2")]
fn p3_crypto_one_way_map_matches_rfc9496_a3() {
    let r = json(R9496);
    let pairs = r["from_uniform_bytes"].as_array().unwrap();
    assert_eq!(pairs.len(), 11);
    for p in pairs {
        let input: [u8; 64] = unhex(p["input"].as_str().unwrap()).try_into().unwrap();
        let got = encode_point(&map_to_group(&input));
        assert_eq!(hex(&got), p["output"].as_str().unwrap());
    }
}

#[test]
// oracle: B RFC 9496 Appendix A.1 and A.2 (golden/p3_rfc9496_ristretto255.json)
#[spec("SR-9.9-1")]
fn p3_crypto_decode_point_accepts_canonical_and_rejects_rfc9496_invalid_encodings() {
    let r = json(R9496);
    for (i, m) in r["generator_multiples"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
    {
        let bytes = unhex(m.as_str().unwrap());
        let p = decode_point(&bytes).unwrap_or_else(|e| panic!("B[{i}] refused: {e:?}"));
        assert_eq!(
            encode_point(&p).as_slice(),
            bytes.as_slice(),
            "B[{i}] round trip"
        );
    }
    let invalid = r["invalid_encodings"].as_array().unwrap();
    assert_eq!(invalid.len(), 29);
    for (i, e) in invalid.iter().enumerate() {
        let bytes = unhex(e.as_str().unwrap());
        assert_eq!(
            decode_point(&bytes),
            Err(CryptoError::NonCanonicalPoint),
            "A.2 entry {i}"
        );
    }
}

#[test]
// oracle: B RFC 9496 Appendix A.1: B[0] is the identity, B[i+1] = B[i] + B (the generator B[1])
fn p3_crypto_point_encoding_is_canonical_ristretto255() {
    let r = json(R9496);
    let m: Vec<RistrettoPoint> = r["generator_multiples"]
        .as_array()
        .unwrap()
        .iter()
        .map(|h| decode_point(&unhex(h.as_str().unwrap())).unwrap())
        .collect();
    assert_eq!(
        encode_point(&m[0]),
        [0u8; 32],
        "§0.2: the identity is 32 zero bytes"
    );
    for i in 0..15 {
        assert_eq!(m[i] + m[1], m[i + 1], "B[{}]", i + 1);
    }
}

#[test]
// oracle: A §0.2, §2.1 ℓ, §9.9; little-endian bytes of ℓ, ℓ − 1, ℓ + 1 and 2^255 − 1 computed with
// Python integers from the §2.1 definition of ℓ
#[spec("SR-9.9-1")]
fn p3_crypto_decode_scalar_rejects_values_at_or_above_the_group_order() {
    let l = "edd3f55c1a631258d69cf7a2def9de1400000000000000000000000000000010";
    let l_minus_1 = "ecd3f55c1a631258d69cf7a2def9de1400000000000000000000000000000010";
    let l_plus_1 = "eed3f55c1a631258d69cf7a2def9de1400000000000000000000000000000010";
    let top = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f";
    for bad in [l, l_plus_1, top] {
        assert_eq!(
            decode_scalar(&unhex(bad)),
            Err(CryptoError::NonCanonicalScalar),
            "{bad}"
        );
    }
    for good in [l_minus_1, &"00".repeat(32)] {
        let s = decode_scalar(&unhex(good)).unwrap();
        assert_eq!(hex(&encode_scalar(&s)), good);
    }
    assert_eq!(decode_scalar(&[0u8; 31]), Err(CryptoError::WrongLength));
    assert_eq!(decode_point(&[0u8; 33]), Err(CryptoError::WrongLength));
}

#[test]
// oracle: A §4.5 formula with ℓ from §2.1; bytes computed with Python integers (Appendix B vector
// 4's inputs plus the i64 extremes)
#[spec("SR-4.5-1")]
fn p3_crypto_scalar_map_follows_section_4_5() {
    let table: [(i64, &str); 7] = [
        (
            0,
            "0000000000000000000000000000000000000000000000000000000000000000",
        ),
        (
            1,
            "0100000000000000000000000000000000000000000000000000000000000000",
        ),
        (
            -1,
            "ecd3f55c1a631258d69cf7a2def9de1400000000000000000000000000000010",
        ),
        (
            1 << 44,
            "0000000000100000000000000000000000000000000000000000000000000000",
        ),
        (
            -(1 << 44),
            "edd3f55c1a531258d69cf7a2def9de1400000000000000000000000000000010",
        ),
        (
            i64::MAX,
            "ffffffffffffff7f000000000000000000000000000000000000000000000000",
        ),
        (
            i64::MIN,
            "edd3f55c1a6312d8d59cf7a2def9de1400000000000000000000000000000010",
        ),
    ];
    for (v, want) in table {
        assert_eq!(
            hex(&encode_scalar(&scalar_from_i64(v))),
            want,
            "scalar({v})"
        );
    }
}

#[test]
// oracle: A §9.2 (H = one-way map of expand_message_xmd(msg, DST_GEN, 64)), composed from the two
// RFC-checked halves above; no golden value yet (Appendix B vector 1 comes from the reference model)
fn p3_crypto_hash_to_group_is_the_map_of_the_expanded_bytes() {
    let u: [u8; 64] = expand_message_xmd_sha512(b"H", DST_GEN, 64)
        .unwrap()
        .try_into()
        .unwrap();
    assert_eq!(hash_to_group(b"H", DST_GEN).unwrap(), map_to_group(&u));
    assert_ne!(
        hash_to_group(b"H", DST_GEN).unwrap(),
        hash_to_group(b"G", DST_GEN).unwrap()
    );
}

const GENS: &str = include_str!("../../../golden/p3_generators.json");

#[test]
// oracle: B-shared golden/p3_generators.json, written by sever_refmodel_certs (Appendix B vector 1)
#[spec("SR-9.2-1", "SR-B-1")]
fn p3_crypto_generators_match_the_golden_file() {
    let golden = json(GENS);
    let gens = Generators::derive(384).unwrap();
    assert_eq!(gens.d(), 384);
    assert_eq!(hex(&encode_point(gens.h())), golden["H"].as_str().unwrap());
    assert_eq!(
        hex(&encode_point(&gens.g()[0])),
        golden["G_0"].as_str().unwrap()
    );
    assert_eq!(
        hex(&encode_point(&gens.g()[383])),
        golden["G_383"].as_str().unwrap()
    );
}

#[test]
// oracle: B-shared golden/p3_generators.json (Appendix B vector 2)
#[spec("SR-9.6-1", "SR-B-2")]
fn p3_crypto_gdigest_matches_the_golden_file() {
    let golden = json(GENS);
    let gens = Generators::derive(384).unwrap();
    assert_eq!(hex(gens.gdigest()), golden["gdigest"].as_str().unwrap());
}

#[test]
// oracle: A §9.2 (msg b"H"; b"G" ‖ u32be(i); DST_GEN; one call per generator) and §9.6 (gdigest =
// SHA-512 of the encodings in order), composed from the RFC-checked hash_to_group
#[spec("SR-9.2-1", "SR-9.6-1")]
fn p3_crypto_generators_follow_section_9_2_byte_for_byte() {
    let gens = Generators::derive(300).unwrap();
    assert_eq!(*gens.h(), hash_to_group(b"H", DST_GEN).unwrap());
    // i = 1 and i = 256 tell big-endian from little-endian; i = 299 is the last one.
    for (i, msg) in [
        (1usize, *b"G\x00\x00\x00\x01"),
        (256, *b"G\x00\x00\x01\x00"),
        (299, *b"G\x00\x00\x01\x2b"),
    ] {
        assert_eq!(gens.g()[i], hash_to_group(&msg, DST_GEN).unwrap(), "G_{i}");
    }
    // Each generator is its own call, so a smaller d gives a prefix of a larger one.
    let small = Generators::derive(16).unwrap();
    assert_eq!(small.g(), &gens.g()[..16]);
    let mut all = encode_point(gens.h()).to_vec();
    gens.g()
        .iter()
        .for_each(|g| all.extend_from_slice(&encode_point(g)));
    use sha2::Digest;
    assert_eq!(
        gens.gdigest().as_slice(),
        sha2::Sha512::digest(&all).as_slice()
    );
}

#[test]
// oracle: A §9.2 self-check (refuse on any mismatch with the golden file) and §21 INV-10
#[spec("SR-9.2-3", "SR-21-10")]
fn p3_crypto_self_check_passes_honestly_and_refuses_any_drift() {
    for d in [16, 384] {
        let gens = Generators::derive(d).unwrap();
        assert_eq!(self_check(&gens), Ok(()), "d = {d}");
    }
    let gens = Generators::derive(384).unwrap();
    // A golden file that differs in one generator, or in gdigest, is refused.
    let flip = |s: &'static str| -> &'static str {
        Box::leak(
            format!("{}{}", if s.starts_with('0') { '1' } else { '0' }, &s[1..]).into_boxed_str(),
        )
    };
    for (name, golden) in [
        (
            "H",
            GeneratorGolden {
                h: flip(GOLDEN.h),
                ..GOLDEN
            },
        ),
        (
            "G_0",
            GeneratorGolden {
                g_0: flip(GOLDEN.g_0),
                ..GOLDEN
            },
        ),
        (
            "G_383",
            GeneratorGolden {
                g_383: flip(GOLDEN.g_383),
                ..GOLDEN
            },
        ),
        (
            "gdigest",
            GeneratorGolden {
                gdigest_384: flip(GOLDEN.gdigest_384),
                ..GOLDEN
            },
        ),
    ] {
        assert!(
            matches!(
                generators::self_check_against(&gens, &golden),
                Err(CryptoError::SelfCheck(_))
            ),
            "{name}"
        );
    }
    // Generators swapped in memory are refused.
    let mut swapped = gens.clone();
    swapped.swap_h_g0_for_test();
    assert!(matches!(
        self_check(&swapped),
        Err(CryptoError::SelfCheck(_))
    ));
}

#[test]
// oracle: B the golden files the embedded constants were copied from
fn p3_crypto_embedded_constants_equal_their_golden_files() {
    let g = json(GENS);
    assert_eq!(GOLDEN.h, g["H"].as_str().unwrap());
    assert_eq!(GOLDEN.g_0, g["G_0"].as_str().unwrap());
    assert_eq!(GOLDEN.g_383, g["G_383"].as_str().unwrap());
    let digest: String = GOLDEN.gdigest_384.split_whitespace().collect();
    assert_eq!(digest, g["gdigest"].as_str().unwrap());
    let k3 = json(K3);
    assert_eq!(KAT_XMD_DST, k3["dst"].as_str().unwrap());
    assert!(
        k3["vectors"]
            .as_array()
            .unwrap()
            .iter()
            .any(|v| v["msg"] == KAT_XMD.0
                && v["len_in_bytes"] == KAT_XMD.1
                && v["uniform_bytes"] == KAT_XMD.2)
    );
    let r = json(R9496);
    let input: String = KAT_MAP.0.split_whitespace().collect();
    assert!(
        r["from_uniform_bytes"]
            .as_array()
            .unwrap()
            .iter()
            .any(|p| p["input"] == input.as_str() && p["output"] == KAT_MAP.1)
    );
}
