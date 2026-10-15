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
    // At d = 16, G_383 is derived for the check, so its drift is caught too (DB-77).
    let g16 = Generators::derive(16).unwrap();
    let drifted = GeneratorGolden {
        g_383: flip(GOLDEN.g_383),
        ..GOLDEN
    };
    assert!(matches!(
        generators::self_check_against(&g16, &drifted),
        Err(CryptoError::SelfCheck("generator G_383"))
    ));
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

const COMMITS: &str = include_str!("../../../golden/p3_commitments.json");

fn ints<T: TryFrom<i64>>(v: &Value) -> Vec<T>
where
    T::Error: std::fmt::Debug,
{
    v.as_array()
        .unwrap()
        .iter()
        .map(|n| T::try_from(n.as_i64().unwrap()).unwrap())
        .collect()
}

fn scalar_hex(v: &Value) -> Scalar {
    decode_scalar(&unhex(v.as_str().unwrap())).unwrap()
}

#[test]
// oracle: B-shared golden/p3_commitments.json, written by sever_refmodel_certs
#[spec("SR-9.3-1")]
fn p3_crypto_record_and_group_commitments_match_the_model() {
    let c = json(COMMITS);
    let g384 = Generators::derive(384).unwrap();
    for r in c["records"].as_array().unwrap() {
        let x: Vec<i32> = ints(&r["x"]);
        let got = commit_record(&g384, &x, &scalar_hex(&r["r"])).unwrap();
        assert_eq!(
            hex(&encode_point(&got)),
            r["C"].as_str().unwrap(),
            "{}",
            r["name"]
        );
    }
    let g16 = Generators::derive(16).unwrap();
    for g in c["groups"].as_array().unwrap() {
        let s: Vec<i64> = ints(&g["S"]);
        let got = commit_group(&g16, &s, &scalar_hex(&g["r_agg"])).unwrap();
        assert_eq!(
            hex(&encode_point(&got)),
            g["C_S"].as_str().unwrap(),
            "{}",
            g["name"]
        );
    }
}

#[test]
// oracle: B-shared golden/p3_commitments.json (C_t, C_S_pre, C_S_post of a three-record group, S and
// r_agg after deleting the third record by §5.3), checked with the §9.3 transition formula
#[spec("SR-9.3-2")]
fn p3_crypto_transition_check_holds_for_a_deletion_and_fails_otherwise() {
    let t = json(COMMITS)["transition"].clone();
    let g = Generators::derive(16).unwrap();
    let pt = |v: &Value| decode_point(&unhex(v.as_str().unwrap())).unwrap();
    let c_t: Vec<RistrettoPoint> = t["C_t"].as_array().unwrap().iter().map(pt).collect();
    let (pre, post) = (pt(&t["C_S_pre"]), pt(&t["C_S_post"]));
    assert_eq!(
        commit_group(&g, &ints::<i64>(&t["S_pre"]), &scalar_hex(&t["r_agg_pre"])).unwrap(),
        pre
    );
    assert_eq!(
        commit_group(
            &g,
            &ints::<i64>(&t["S_post"]),
            &scalar_hex(&t["r_agg_post"])
        )
        .unwrap(),
        post
    );
    assert!(
        transition_holds(&post, &c_t[2], &pre),
        "deleting the third record"
    );
    assert!(
        !transition_holds(&post, &c_t[1], &pre),
        "a different record's C_t"
    );
    assert!(
        !transition_holds(&pre, &c_t[2], &post),
        "pre and post swapped"
    );
}

#[test]
// oracle: A §5.4 (an empty group has S = 0, r_agg = 0, C_S = identity) and §0.2 (the identity is
// 32 zero bytes); §9: the zero scalar is accepted
#[spec("SR-5.4-4")]
fn p3_crypto_the_empty_group_commits_to_the_identity() {
    let g = Generators::derive(16).unwrap();
    let c = commit_group(&g, &[0; 16], &Scalar::ZERO).unwrap();
    assert_eq!(encode_point(&c), [0u8; 32]);
}

#[test]
// oracle: A §9.9 (C_t MUST NOT be the identity; points canonical on parse)
#[spec("SR-9.9-2")]
fn p3_crypto_a_record_commitment_may_not_be_the_identity() {
    assert_eq!(
        decode_record_commitment(&[0u8; 32]),
        Err(CryptoError::IdentityCommitment)
    );
    let r = json(R9496);
    let bad = unhex(r["invalid_encodings"][0].as_str().unwrap());
    assert_eq!(
        decode_record_commitment(&bad),
        Err(CryptoError::NonCanonicalPoint)
    );
    let b1 = unhex(r["generator_multiples"][1].as_str().unwrap());
    assert!(decode_record_commitment(&b1).is_ok());
}

#[test]
// oracle: A §9.3 (each commitment is linear in its inputs) and the d-component rule of §2.1
fn p3_crypto_commitments_are_additive_and_need_d_components() {
    let g = Generators::derive(8).unwrap();
    let (s, x) = (
        [5i64, -7, 1 << 40, -(1 << 40), 0, 1, -1, 3],
        [-(1i32 << 24), 16_777_232, 9, -9, 0, 0, 4, -4],
    );
    let (r_agg, r_t) = (Scalar::from(11u64), Scalar::from(22u64));
    let sum: Vec<i64> = s.iter().zip(x).map(|(a, b)| a + i64::from(b)).collect();
    let pre = commit_group(&g, &sum, &(r_agg + r_t)).unwrap();
    assert_eq!(
        pre,
        commit_group(&g, &s, &r_agg).unwrap() + commit_record(&g, &x, &r_t).unwrap()
    );
    assert_eq!(
        commit_record(&g, &x[..7], &r_t),
        Err(CryptoError::WrongLength)
    );
    assert_eq!(
        commit_group(&g, &[0; 9], &r_agg),
        Err(CryptoError::WrongLength)
    );
}

const POSK: &str = include_str!("../../../golden/p3_posk.json");

fn arr<const N: usize>(v: &Value) -> [u8; N] {
    unhex(v.as_str().unwrap()).try_into().unwrap()
}

fn golden_ctx() -> DeletionContext {
    let f = &json(POSK)["ctx_fields"];
    DeletionContext {
        c_s_pre: arr(&f["C_S_pre"]),
        c_t: arr(&f["C_t"]),
        scrambled_id: arr(&f["scrambled_id"]),
        database_lsn: f["database_lsn"].as_u64().unwrap(),
        collection_id: arr(&f["collection_id"]),
    }
}

/// The d = 16 reference proof of golden/p3_posk.json, made by the engine with the same nonces.
fn engine_proof_d16() -> (Generators, Vec<u8>) {
    let p = &json(POSK)["proof_d16"];
    let g = Generators::derive(16).unwrap();
    let k: Vec<Scalar> = p["k"].as_array().unwrap().iter().map(scalar_hex).collect();
    let proof = posk::prove_with_nonces(
        &g,
        &ints::<i64>(&p["S_post"]),
        &scalar_hex(&p["r_post"]),
        &golden_ctx(),
        &scalar_hex(&p["k_r"]),
        &k,
    )
    .unwrap();
    (g, proof.to_bytes())
}

#[test]
// oracle: A §9.5 deletion context layout, bytes written by hand from the field order
#[spec("SR-9.5-1")]
fn p3_crypto_deletion_context_is_the_152_byte_concatenation_of_section_9_5() {
    let ctx = DeletionContext {
        c_s_pre: [0x11; 32],
        c_t: [0x22; 32],
        scrambled_id: [0x33; 64],
        database_lsn: 0x0102_0304_0506_0708,
        collection_id: [0x44; 16],
    };
    let mut want = Vec::new();
    want.extend([0x11; 32]);
    want.extend([0x22; 32]);
    want.extend([0x33; 64]);
    want.extend([1, 2, 3, 4, 5, 6, 7, 8]); // u64be
    want.extend([0x44; 16]);
    assert_eq!(CTX_LEN, 152);
    assert_eq!(ctx.to_bytes().as_slice(), want.as_slice());
    assert_eq!(
        hex(&golden_ctx().to_bytes()),
        json(POSK)["ctx"].as_str().unwrap()
    );
}

#[test]
// oracle: A §9.5 challenge formula, computed in the test with SHA-512 over the hand-built 231-byte
// preimage [SR-9.5-3]
// oracle: B-shared golden/p3_posk.json vector3 (Appendix B vector 3) and its must-fail swap [SR-B-3]
#[spec("SR-9.5-3", "SR-B-3")]
fn p3_crypto_challenge_matches_section_9_5_and_golden_vector_3() {
    let v = &json(POSK)["vector3"];
    let (c_s_post, a) = (arr::<32>(&v["C_S_post"]), arr::<32>(&v["A"]));
    let ctx = golden_ctx().to_bytes();
    let mut pre = Vec::new();
    pre.extend_from_slice(b"SEVERDB_POSK_V1");
    pre.extend_from_slice(&c_s_post);
    pre.extend_from_slice(&a);
    pre.extend_from_slice(&ctx);
    assert_eq!(pre.len(), CHALLENGE_PREIMAGE_LEN);
    assert_eq!(pre.len(), 231);
    use sha2::Digest;
    let wide: [u8; 64] = sha2::Sha512::digest(&pre).into();
    let by_hand = Scalar::from_bytes_mod_order_wide(&wide);
    let c = challenge(&c_s_post, &a, &ctx);
    assert_eq!(c, by_hand);
    assert_eq!(hex(&encode_scalar(&c)), v["c"].as_str().unwrap());
    // Appendix B vector 3's must-fail: swapping A and C_S_post changes c.
    assert_ne!(challenge(&a, &c_s_post, &ctx), c);
}

#[test]
// oracle: B-shared golden/p3_posk.json proof_d16 (the model's prover with the same fixed nonces)
#[spec("SR-9.5-2", "SR-9.5-4", "SR-9.5-5")]
fn p3_crypto_proof_equals_the_models_for_the_same_nonces() {
    let (_, proof) = engine_proof_d16();
    assert_eq!(proof.len(), 32 + 32 + 32 * 16);
    assert_eq!(
        hex(&proof),
        json(POSK)["proof_d16"]["proof"].as_str().unwrap()
    );
}

#[test]
// oracle: A §9.5 verifier (accept iff z_r·H + Σ z_i·G_i = A + c·C_S_post; canonical decoding)
#[spec("SR-9.5-6")]
fn p3_crypto_verifier_accepts_the_honest_proof_and_rejects_every_change() {
    let (g, proof) = engine_proof_d16();
    let ctx = golden_ctx();
    let c_s_post = arr::<32>(&json(POSK)["proof_d16"]["C_S_post"]);
    assert_eq!(verify(&g, &c_s_post, &ctx, &proof), Ok(()));
    let model = unhex(json(POSK)["proof_d16"]["proof"].as_str().unwrap());
    assert_eq!(
        verify(&g, &c_s_post, &ctx, &model),
        Ok(()),
        "the model's proof"
    );
    // Another statement or another context: the proof cannot be replayed (§9.5).
    assert_eq!(
        verify(&g, &ctx.c_s_pre, &ctx, &proof),
        Err(CryptoError::ProofInvalid)
    );
    let other = DeletionContext {
        database_lsn: ctx.database_lsn + 1,
        ..ctx
    };
    assert_eq!(
        verify(&g, &c_s_post, &other, &proof),
        Err(CryptoError::ProofInvalid)
    );
    // z_r + 1, and the last z replaced: invalid.
    let mut bad = proof.clone();
    let z_r = decode_scalar(&bad[32..64]).unwrap() + Scalar::ONE;
    bad[32..64].copy_from_slice(&encode_scalar(&z_r));
    assert_eq!(
        verify(&g, &c_s_post, &ctx, &bad),
        Err(CryptoError::ProofInvalid)
    );
    // A replaced by another valid point.
    let mut bad = proof.clone();
    bad[..32].copy_from_slice(&encode_point(g.h()));
    assert_eq!(
        verify(&g, &c_s_post, &ctx, &bad),
        Err(CryptoError::ProofInvalid)
    );
    // A non-canonical z (ℓ itself) and a truncated proof are refused before any arithmetic.
    let mut bad = proof.clone();
    let l = unhex("edd3f55c1a631258d69cf7a2def9de1400000000000000000000000000000010");
    bad[64..96].copy_from_slice(&l);
    assert_eq!(
        verify(&g, &c_s_post, &ctx, &bad),
        Err(CryptoError::NonCanonicalScalar)
    );
    assert_eq!(
        verify(&g, &c_s_post, &ctx, &proof[..proof.len() - 1]),
        Err(CryptoError::WrongLength)
    );
}

#[test]
// oracle: A §9.5 proof size 32 + 32 + 32·d and Appendix A (12,352 bytes at d = 384)
#[spec("SR-9.5-5", "SR-A-1")]
fn p3_crypto_a_proof_at_d_384_is_12352_bytes_and_verifies() {
    let g = Generators::derive(384).unwrap();
    let s: Vec<i64> = (0..384).map(|i| (i - 192) * 1_000_003).collect();
    let r = Scalar::from(987_654_321u64);
    let k: Vec<Scalar> = (0..384u64).map(|i| Scalar::from(i * 7 + 1)).collect();
    let c_s_post = encode_point(&commit_group(&g, &s, &r).unwrap());
    let ctx = golden_ctx();
    let proof = posk::prove_with_nonces(&g, &s, &r, &ctx, &Scalar::from(5u64), &k)
        .unwrap()
        .to_bytes();
    assert_eq!(Proof::encoded_len(384), 12_352);
    assert_eq!(proof.len(), 12_352);
    assert_eq!(verify(&g, &c_s_post, &ctx, &proof), Ok(()));
}

/// A fixed entropy source for following §9.6 step by step in tests (never reaches `prove`).
struct FixedEntropy(u8);
impl rand_core::RngCore for FixedEntropy {
    fn next_u32(&mut self) -> u32 {
        u32::from(self.0)
    }
    fn next_u64(&mut self) -> u64 {
        u64::from(self.0)
    }
    fn fill_bytes(&mut self, dest: &mut [u8]) {
        dest.fill(self.0)
    }
    fn try_fill_bytes(&mut self, dest: &mut [u8]) -> Result<(), rand_core::Error> {
        dest.fill(self.0);
        Ok(())
    }
}
impl rand_core::CryptoRng for FixedEntropy {}

#[test]
// oracle: A §9.6 transcript steps, followed by hand with merlin in this test (labels gens, stmt,
// ctx, r, s; entropy at finalize; 64 bytes per nonce reduced wide, k_r first)
#[spec("SR-9.6-2")]
fn p3_crypto_nonce_derivation_follows_section_9_6_step_by_step() {
    use rand_core::RngCore;
    let g = Generators::derive(16).unwrap();
    let ctx = golden_ctx();
    let s_post: Vec<i64> = (0..16).map(|i| i * 1000 - 7000).collect();
    let r_post = Scalar::from(4242u64);
    let s: Vec<Scalar> = s_post.iter().map(|&v| scalar_from_i64(v)).collect();
    let c_s_post = encode_point(&commit_group(&g, &s_post, &r_post).unwrap());

    let mut t = merlin::Transcript::new(b"SEVERDB_POSK_NONCE_V1");
    t.append_message(b"gens", g.gdigest());
    t.append_message(b"stmt", &c_s_post);
    t.append_message(b"ctx", &ctx.to_bytes());
    let mut b = t
        .build_rng()
        .rekey_with_witness_bytes(b"r", &encode_scalar(&r_post));
    for si in &s {
        b = b.rekey_with_witness_bytes(b"s", &encode_scalar(si));
    }
    let mut rng = b.finalize(&mut FixedEntropy(9));
    let mut want = Vec::new();
    for _ in 0..17 {
        let mut buf = [0u8; 64];
        rng.fill_bytes(&mut buf);
        want.push(Scalar::from_bytes_mod_order_wide(&buf));
    }

    let (k_r, k) = nonce::hedged_nonces(&g, &c_s_post, &ctx, &r_post, &s, &mut FixedEntropy(9));
    assert_eq!(k_r, want[0]);
    assert_eq!(k, want[1..]);
    // The nonces depend on the entropy, the witness and the context.
    assert_ne!(
        nonce::hedged_nonces(&g, &c_s_post, &ctx, &r_post, &s, &mut FixedEntropy(8)).0,
        k_r
    );
    let r2 = r_post + Scalar::ONE;
    assert_ne!(
        nonce::hedged_nonces(&g, &c_s_post, &ctx, &r2, &s, &mut FixedEntropy(9)).0,
        k_r
    );
    let ctx2 = DeletionContext {
        database_lsn: ctx.database_lsn + 1,
        ..ctx
    };
    assert_ne!(
        nonce::hedged_nonces(&g, &c_s_post, &ctx2, &r_post, &s, &mut FixedEntropy(9)).0,
        k_r
    );
}

#[test]
// oracle: A §9.6 (fresh OS entropy at finalize: proving one statement twice never repeats the
// nonce vector) and §9.5 (each proof verifies)
#[spec("SR-9.6-2")]
fn p3_crypto_proving_one_statement_twice_uses_fresh_nonces() {
    let g = Generators::derive(16).unwrap();
    let ctx = golden_ctx();
    let s_post: Vec<i64> = (0..16).map(|i| 3 * i - 20).collect();
    let r_post = Scalar::from(99u64);
    let c_s_post = encode_point(&commit_group(&g, &s_post, &r_post).unwrap());
    let mut rng = StrictProofRng::new();
    let p1 = prove(&g, &s_post, &r_post, &ctx, &mut rng)
        .unwrap()
        .to_bytes();
    let p2 = prove(&g, &s_post, &r_post, &ctx, &mut rng)
        .unwrap()
        .to_bytes();
    assert_ne!(p1[..32], p2[..32], "A repeated: a nonce vector was reused");
    assert_eq!(verify(&g, &c_s_post, &ctx, &p1), Ok(()));
    assert_eq!(verify(&g, &c_s_post, &ctx, &p2), Ok(()));
}

#[test]
// oracle: A §9.6 (StrictProofRng is a zero-sized wrapper around OsRng, RngCore + CryptoRng, the
// only type prove accepts); the not-SeedableRng half is the compile_fail doc tests on the type
#[spec("SR-9.6-3")]
fn p3_crypto_prove_takes_the_zero_sized_strict_proof_rng() {
    fn crypto_rng<T: rand_core::RngCore + rand_core::CryptoRng>(_: &T) {}
    let mut rng = StrictProofRng::new();
    crypto_rng(&rng);
    assert_eq!(std::mem::size_of::<StrictProofRng>(), 0);
    let mut a = [0u8; 32];
    let mut b = [0u8; 32];
    rand_core::RngCore::fill_bytes(&mut rng, &mut a);
    rand_core::RngCore::fill_bytes(&mut rng, &mut b);
    assert_ne!(a, b, "two OS draws of 32 bytes coincided");
    let g = Generators::derive(384).unwrap();
    let s: Vec<i64> = (0..384).map(|i| i - 100).collect();
    let r = Scalar::from(5u64);
    let proof = prove(&g, &s, &r, &golden_ctx(), &mut rng)
        .unwrap()
        .to_bytes();
    let c_s_post = encode_point(&commit_group(&g, &s, &r).unwrap());
    assert_eq!(proof.len(), 12_352);
    assert_eq!(verify(&g, &c_s_post, &golden_ctx(), &proof), Ok(()));
}

const R8032: &str = include_str!("../../../golden/p3_rfc8032_ed25519.json");

#[test]
// oracle: B RFC 8032 §7.1 (golden/p3_rfc8032_ed25519.json): public keys and signatures, byte for byte
fn p3_crypto_ed25519_matches_rfc8032() {
    let e = json(R8032);
    let vs = e["vectors"].as_array().unwrap();
    assert_eq!(vs.len(), 5);
    for v in vs {
        let k = KeyPair::from_secret(&arr::<32>(&v["secret_key"]));
        let msg = unhex(v["message"].as_str().unwrap());
        assert_eq!(
            hex(&k.public()),
            v["public_key"].as_str().unwrap(),
            "TEST {}",
            v["name"]
        );
        let sig = k.sign(&msg);
        assert_eq!(
            hex(&sig),
            v["signature"].as_str().unwrap(),
            "TEST {}",
            v["name"]
        );
        assert_eq!(verify_signature(&k.public(), &msg, &sig), Ok(()));
    }
}

#[test]
// oracle: A §9.8 signer table and §2.3: each message's bytes written by hand in field order
#[spec("SR-9.8-1", "SR-9.8-2", "SR-9.8-3", "SR-9.8-4")]
fn p3_crypto_signed_messages_have_the_layouts_of_section_9_8() {
    let ins = insert_message(&[0xc1; 16], &[0x7a; 32]);
    let mut want = b"SEVERDB-INSERT-V1".to_vec();
    want.extend([0xc1; 16]);
    want.extend([0x7a; 32]);
    assert_eq!((ins.as_slice(), INSERT_MESSAGE_LEN), (want.as_slice(), 65));

    let cp = checkpoint_message(
        0x0102_0304_0506_0708,
        &[0xab; 32],
        0x1112_1314_1516_1718,
        0x2122_2324,
    );
    let mut want = b"SEVERDB-STH-V1".to_vec();
    want.extend([1, 2, 3, 4, 5, 6, 7, 8]); // u64be tree_size
    want.extend([0xab; 32]); // root
    want.extend([0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18]); // u64be timestamp_ms
    want.extend([0x21, 0x22, 0x23, 0x24]); // u32be epoch
    assert_eq!(
        (cp.as_slice(), CHECKPOINT_MESSAGE_LEN),
        (want.as_slice(), 66)
    );

    let co = cosign_message(&cp);
    let mut want = b"SEVERDB-COSIGN-V1".to_vec();
    want.extend_from_slice(&cp);
    assert_eq!((co.as_slice(), COSIGN_MESSAGE_LEN), (want.as_slice(), 83));

    let mut want = b"SEVERDB-CERT-V1".to_vec();
    want.extend([1, 2, 3]);
    assert_eq!(certificate_message(&[1, 2, 3]), want);
}

#[test]
// oracle: A §9.8 (every check uses verify_strict: small-order keys and non-canonical encodings are
// rejected) and RFC 8032 §5.1.7 (S must be below ℓ); the identity and ℓ written by hand
#[spec("SR-9.8-7")]
fn p3_crypto_signatures_are_checked_strictly() {
    let k = KeyPair::generate();
    let msg = insert_message(&[1; 16], &[2; 32]);
    let sig = k.sign(&msg);
    assert_eq!(verify_signature(&k.public(), &msg, &sig), Ok(()));
    // Domain separation: the same signature does not cover any other message.
    let other = cosign_message(&checkpoint_message(1, &[2; 32], 3, 4));
    assert_eq!(
        verify_signature(&k.public(), &other, &sig),
        Err(CryptoError::BadSignature)
    );
    // A small-order public key (the Edwards identity, y = 1) with R = identity and S = 0 satisfies
    // the plain equation [S]B = R + [k]A for every message; verify_strict must refuse it.
    let mut identity = [0u8; 32];
    identity[0] = 1;
    let mut weak_sig = [0u8; 64];
    weak_sig[0] = 1;
    assert_eq!(
        verify_signature(&identity, &msg, &weak_sig),
        Err(CryptoError::BadSignature)
    );
    // S + ℓ (non-canonical S) is refused.
    let l = unhex("edd3f55c1a631258d69cf7a2def9de1400000000000000000000000000000010");
    let mut big = sig;
    let mut carry = 0u16;
    for (b, li) in big[32..].iter_mut().zip(&l) {
        let s = u16::from(*b) + u16::from(*li) + carry;
        *b = (s & 0xff) as u8;
        carry = s >> 8;
    }
    assert_eq!(carry, 0);
    assert_eq!(
        verify_signature(&k.public(), &msg, &big),
        Err(CryptoError::BadSignature)
    );
}

#[test]
// oracle: A §9.8 epochs ([genesis + 90·e days, genesis + 90·(e+1) days)); 90 days = 7,776,000,000 ms
// by hand
#[spec("SR-9.8-5")]
fn p3_crypto_epochs_are_90_day_windows_from_genesis() {
    let g = 1_700_000_000_000u64;
    assert_eq!(EPOCH_MS, 7_776_000_000);
    assert_eq!(epoch_of(g, g), Some(0));
    assert_eq!(epoch_of(g, g + 7_776_000_000 - 1), Some(0));
    assert_eq!(epoch_of(g, g + 7_776_000_000), Some(1));
    assert_eq!(epoch_of(g, g + 3 * 7_776_000_000 + 5), Some(3));
    assert_eq!(epoch_of(g, g - 1), None);
}
