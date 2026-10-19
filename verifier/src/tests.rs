//! Tests of the verifier (Build 3-4 §1.8 L2, L10). Expected values come from the certificate
//! model's golden files (`golden/p3_certificates.json`, `golden/p3_attacks.json`, Appendix B 6 and
//! 9; B-shared), the RFC vectors (B) and the spec's step list (A); never from this code.

use std::collections::BTreeMap;

use serde_json::Value;
use sever_spec::spec;

use crate::anchors::Anchors;
use crate::gens::{Generators, KAT_RISTRETTO, KAT_XMD, check_ristretto, check_xmd, self_check};
use crate::hex;
use crate::merkle::{leaf_hash, verify_inclusion};
use crate::verify::verify;
use crate::{GOLDEN_GENERATORS, Rejection};

const CERTS: &str = include_str!("../../golden/p3_certificates.json");
const ATTACKS: &str = include_str!("../../golden/p3_attacks.json");
const MERKLE: &str = include_str!("../../golden/p3_merkle_7.json");
const REGISTER: &str = include_str!("../../spec/registers_p3.yaml");

fn json(s: &str) -> Value {
    serde_json::from_str(s).unwrap()
}

fn h(v: &Value) -> Vec<u8> {
    hex::decode(v.as_str().unwrap()).unwrap()
}

/// The d = 384 anchors of Appendix B 6: operator keys by epoch, the five witnesses in epoch 0.
fn golden_anchors() -> Anchors {
    let v = json(CERTS);
    let keys = &v["keys"];
    let operator = keys["operator"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(e, k)| (e.parse().unwrap(), h(&k["public"]).try_into().unwrap()))
        .collect();
    let witnesses = keys["witness_epoch0"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
        .map(|(i, k)| ((i as u8, 0), h(&k["public"]).try_into().unwrap()))
        .collect();
    Anchors {
        d: v["d"].as_u64().unwrap() as usize,
        gdigest: None,
        operator,
        witnesses,
    }
}

fn attack_anchors() -> Anchors {
    Anchors::from_json(&json(ATTACKS)["anchors"].to_string()).unwrap()
}

/// `{AT-n: [steps]}` from the register (spec/registers_p3.yaml).
fn register_steps() -> BTreeMap<String, Vec<u8>> {
    REGISTER
        .lines()
        .filter_map(|l| {
            let id = l.split("{id: ").nth(1)?.split(',').next()?;
            if !id.starts_with("AT-") {
                return None;
            }
            let steps = l.split("steps: [").nth(1)?.split(']').next()?;
            Some((
                id.to_owned(),
                steps
                    .split(',')
                    .map(|s| s.trim().parse().unwrap())
                    .collect(),
            ))
        })
        .collect()
}

#[test]
// oracle: B-shared sever_refmodel_certs golden Appendix B 6 (p3_certificates.json at d = 384) and the d = 16 certificates of p3_attacks.json
#[spec("SR-11.1-1", "SR-11.2-1", "SR-9.5-1", "SR-9.5-3")]
#[spec("SR-9.5-6", "SR-9.8-1", "SR-9.8-2", "SR-9.8-3")]
#[spec("SR-9.8-4", "SR-10.1-2", "SR-11.3-6")]
fn p3_verify_accepts_the_models_honest_certificates() {
    let v = json(CERTS);
    let a = golden_anchors();
    let gens = Generators::derive(a.d).unwrap();
    let group = verify(&h(&v["group_deletion"]["certificate"]), &a, &gens).unwrap();
    let tags = &v["group_deletion"]["tags"];
    assert_eq!(group.deletion_kind, 0);
    assert_eq!(group.database_lsn.to_be_bytes().to_vec(), h(&tags["10"]));
    assert_eq!(
        group.leaf_index,
        v["group_deletion"]["inclusion"]["leaf_index"]
            .as_u64()
            .unwrap()
    );
    assert!(!group.group_emptied);
    let holding = verify(&h(&v["holding_deletion"]["certificate"]), &a, &gens).unwrap();
    assert_eq!(holding.deletion_kind, 1);
    // d = 16: the same scenario, and a deletion that empties its group (tag 11 = 1).
    let t = json(ATTACKS);
    let a16 = attack_anchors();
    let g16 = Generators::derive(16).unwrap();
    for which in ["group", "holding"] {
        verify(&h(&t["honest"][which]), &a16, &g16).unwrap();
    }
    assert!(
        verify(&h(&t["honest"]["emptied"]), &a16, &g16)
            .unwrap()
            .group_emptied
    );
}

#[test]
// oracle: B-shared golden p3_attacks.json (each variant and the §11.3 step sever_refmodel_certs rejects it at); A the register's allowed steps (spec/registers_p3.yaml, §11.3)
#[spec("SR-11.3-1", "SR-11.3-2", "SR-11.3-3", "SR-11.3-4")]
#[spec("SR-11.3-5", "SR-11.3-6", "SR-11.3-7", "SR-11.1-2")]
#[spec("SR-11.1-3", "SR-9.9-1", "SR-9.9-2", "SR-10.4-2")]
fn p3_verify_rejects_every_attack_at_the_models_step() {
    let t = json(ATTACKS);
    let a = attack_anchors();
    let gens = Generators::derive(16).unwrap();
    let register = register_steps();
    assert_eq!(register.len(), 20);
    let mut seen = BTreeMap::<String, usize>::new();
    for row in t["attacks"].as_array().unwrap() {
        let id = row["id"].as_str().unwrap();
        let k = row["variant"].as_u64().unwrap();
        let want = row["model_step"].as_u64().unwrap() as u8;
        match verify(&h(&row["certificate"]), &a, &gens) {
            Ok(_) => panic!("{id} variant {k} accepted"),
            Err(Rejection { step, reason }) => {
                assert_eq!(step, want, "{id} variant {k}: {reason}");
                assert!(register[id].contains(&step), "{id} variant {k}");
            }
        }
        *seen.entry(id.to_owned()).or_default() += 1;
    }
    assert_eq!(
        seen.keys().collect::<Vec<_>>(),
        register.keys().collect::<Vec<_>>()
    );
    assert_eq!(seen["AT-4"], 14, "tags 1–13 and the trailer");
}

#[test]
// oracle: A §11.3 step 8 'Accept only if every step passes'; §9.8 the trailer signs every byte before it
#[spec("SR-9.8-4", "SR-11.3-2", "SR-11.3-8")]
fn p3_verify_rejects_every_single_byte_change() {
    let t = json(ATTACKS);
    let a = attack_anchors();
    let gens = Generators::derive(16).unwrap();
    for which in ["group", "holding"] {
        let good = h(&t["honest"][which]);
        for i in 0..good.len() {
            let mut bad = good.clone();
            bad[i] ^= 0x01;
            let r = verify(&bad, &a, &gens);
            assert!(r.is_err(), "{which}: byte {i} changed, still accepted");
        }
    }
}

#[test]
// oracle: B RFC 9380 Appendix K.3 and RFC 9496 Appendix A vectors; B-shared Appendix B 1–2 (p3_generators.json, sever_refmodel_certs)
#[spec("SR-9.2-1", "SR-9.2-2", "SR-9.2-3", "SR-9.2-4")]
fn p3_verify_self_check_with_its_own_code() {
    check_xmd(KAT_XMD).unwrap();
    check_ristretto(KAT_RISTRETTO).unwrap();
    for d in [16, 383, 384] {
        self_check(&Generators::derive(d).unwrap(), GOLDEN_GENERATORS).unwrap();
    }
    // A golden file that disagrees is refused (the check can fail).
    let other = GOLDEN_GENERATORS.replacen("\"H\": \"8", "\"H\": \"9", 1);
    assert_ne!(other, GOLDEN_GENERATORS);
    assert!(self_check(&Generators::derive(16).unwrap(), &other).is_err());
}

#[test]
// oracle: B-shared golden Appendix B 9 (p3_merkle_7.json: RFC 9162 §2.1 inclusion paths of a 7-leaf tree)
#[spec("SR-10.1-1", "SR-10.1-2")]
fn p3_verify_inclusion_matches_rfc9162_vectors() {
    let v = json(MERKLE);
    let leaves: Vec<Vec<u8>> = v["leaves"].as_array().unwrap().iter().map(h).collect();
    let roots: Vec<[u8; 32]> = v["roots"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| h(r).try_into().unwrap())
        .collect();
    let cases = v["inclusion"].as_array().unwrap();
    assert!(!cases.is_empty());
    for c in cases {
        let (i, n) = (c["index"].as_u64().unwrap(), c["size"].as_u64().unwrap());
        let path: Vec<[u8; 32]> = c["path"]
            .as_array()
            .unwrap()
            .iter()
            .map(|p| h(p).try_into().unwrap())
            .collect();
        let leaf = leaf_hash(&leaves[i as usize]);
        assert!(
            verify_inclusion(&leaf, i, n, &path, &roots[n as usize]),
            "{i} of {n}"
        );
        // The same path does not prove another leaf.
        let other = leaf_hash(&leaves[(i as usize + 1) % leaves.len()]);
        assert!(!verify_inclusion(&other, i, n, &path, &roots[n as usize]));
    }
}

#[test]
// oracle: A §11.3 trust anchors (operator keys by epoch, witness keys by epoch) in the published JSON form (DB-85), written by hand
#[spec("SR-11.3-9")]
fn p3_verify_reads_the_published_anchors() {
    let k = |b: u8| hex::encode(&[b; 32]);
    let text = format!(
        r#"{{"d": 16, "gdigest": "{}", "operator": {{"0": "{}", "3": "{}"}},
            "witnesses": [{{"0": "{}"}}, {{"0": "{}", "1": "{}"}}, {{}}, {{}}, {{}}]}}"#,
        "ab".repeat(64),
        k(1),
        k(2),
        k(3),
        k(4),
        k(5)
    );
    let a = Anchors::from_json(&text).unwrap();
    assert_eq!(a.d, 16);
    assert_eq!(a.gdigest, Some([0xab; 64]));
    assert_eq!(a.operator, BTreeMap::from([(0, [1; 32]), (3, [2; 32])]));
    assert_eq!(
        a.witnesses,
        BTreeMap::from([((0, 0), [3; 32]), ((1, 0), [4; 32]), ((1, 1), [5; 32])])
    );
    assert!(Anchors::from_json(&text.replace("\"d\": 16,", "")).is_err());
    assert!(Anchors::from_json(&text.replace(&k(1), &k(1)[2..])).is_err());
}

#[test]
// oracle: A §11.3 'Forward limit': a verifier whose anchors predate an operator epoch cannot check a certificate signed in it; step 2 'the key for tag 8's epoch MUST be in the anchors' (E2E-3.7, overview L-14)
#[spec("SR-11.3-2")]
fn p3_verify_an_older_verifier_rejects_a_later_epoch() {
    let v = json(CERTS);
    let cert = h(&v["group_deletion"]["certificate"]);
    let mut older = golden_anchors();
    let gens = Generators::derive(older.d).unwrap();
    assert_eq!(h(&v["group_deletion"]["tags"]["8"]), 1u32.to_be_bytes());
    verify(&cert, &older, &gens).unwrap();
    older.operator.remove(&1); // released before epoch 1 began
    let r = verify(&cert, &older, &gens).unwrap_err();
    assert_eq!(r.step, 2);
    assert!(r.reason.contains("unknown"), "{}", r.reason);
}

#[test]
// oracle: D the verifier's own guards: generators of another dimension are refused at step 1, before parsing; odd-length hex does not decode
fn p3_verify_refuses_generators_of_another_dimension_and_odd_hex() {
    let t = json(ATTACKS);
    let a16 = attack_anchors();
    let g8 = Generators::derive(8).unwrap();
    let r = verify(&h(&t["honest"]["group"]), &a16, &g8).unwrap_err();
    assert_eq!(r.step, 1);
    assert!(r.reason.contains("dimension"), "{}", r.reason);
    assert_eq!(hex::decode("abc"), None);
    assert_eq!(hex::decode("ab"), Some(vec![0xab]));
}
