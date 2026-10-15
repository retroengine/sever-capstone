//! Tests of the certificate encoding and builder. Expected values come from the §11.1 table and
//! §11.2 layout written out by hand (oracle A), Appendix A (oracle A), and the reference model's
//! Appendix B vector 6 (`golden/p3_certificates.json`, oracle B-shared: the pure-Python model
//! signs with its own RFC 8032 Ed25519, so a byte-equal signature is an independent check).

use serde_json::Value;
use sever_crypto::{
    DeletionContext, Generators, KeyPair, Scalar, StrictProofRng, certificate_message,
    commit_group, commit_record, cosign_message, decode_point, encode_point, insert_message,
    transition_holds, verify, verify_signature,
};
use sever_log::checkpoint::{Cosignature, LogCheckpoint};
use sever_log::keys::{EpochSigner, Keyring};
use sever_log::leaf::InsertLeaf;
use sever_log::merkle::{Hash, MerkleTree, leaf_hash, verify_inclusion};
use sever_spec::spec;

use crate::*;

const GOLDEN: &str = include_str!("../../../golden/p3_certificates.json");

fn json() -> Value {
    serde_json::from_str(GOLDEN).unwrap()
}

fn hex(v: &Value) -> Vec<u8> {
    let s = v.as_str().unwrap();
    (0..s.len() / 2)
        .map(|i| u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap())
        .collect()
}

fn arr<const N: usize>(v: &Value) -> [u8; N] {
    hex(v).try_into().unwrap()
}

fn u(v: &Value) -> u64 {
    v.as_u64().unwrap()
}

/// The golden certificate `which`, rebuilt field by field from its intermediate values (not from
/// its bytes).
fn golden_certificate(g: &Value, which: &str) -> Certificate {
    let w = &g[which];
    let t = &w["tags"];
    let cp = &g["checkpoint"];
    let rec = g["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["name"] == w["record"])
        .unwrap();
    let group = (which == "group_deletion").then(|| GroupFields {
        c_s_pre: arr(&w["C_S_pre"]),
        c_s_post: arr(&w["C_S_post"]),
        proof: hex(&t["4"]),
        emptied: false,
    });
    Certificate {
        c_t: arr(&rec["C_t"]),
        group,
        user_signature: arr(&rec["user_signature"]),
        inclusion: InsertInclusion {
            leaf: InsertLeaf::parse(&hex(&rec["leaf"])).unwrap(),
            leaf_index: u(&rec["leaf_index"]),
            checkpoint: LogCheckpoint {
                tree_size: u(&cp["tree_size"]),
                root: arr(&cp["root"]),
                timestamp_ms: u(&cp["timestamp_ms"]),
                epoch: u(&cp["epoch"]) as u32,
                operator_signature: arr(&cp["operator_signature"]),
            },
            path: w["inclusion"]["path"]
                .as_array()
                .unwrap()
                .iter()
                .map(arr::<32>)
                .collect(),
        },
        cosignatures: g["cosignatures"]
            .as_array()
            .unwrap()
            .iter()
            .map(|c| Cosignature {
                witness_index: u(&c["witness_index"]) as u8,
                witness_epoch: u(&c["witness_epoch"]) as u32,
                signature: arr(&c["signature"]),
            })
            .collect(),
        key_period: 1,
        scrambled_id: arr(&rec["scrambled_id"]),
        database_lsn: u(&w["database_lsn"]),
        collection_id: arr(&g["collection_id"]),
        operator_signature: [0; 64],
    }
}

#[test]
// oracle: B-shared golden/p3_certificates.json (Appendix B 6, sever_refmodel_certs with RFC 8032)
#[spec("SR-B-6", "SR-11.1-1", "SR-11.2-1", "SR-9.8-4")]
fn p3_cert_golden_certificates_encode_and_sign_byte_for_byte() {
    let g = json();
    let op1 = KeyPair::from_secret(&arr(&g["keys"]["operator"]["1"]["secret"]));
    for which in ["group_deletion", "holding_deletion"] {
        let mut c = golden_certificate(&g, which);
        assert_eq!(c.body(), hex(&g[which]["body"]), "{which} body");
        c.sign(&op1);
        assert_eq!(
            c.operator_signature,
            arr::<64>(&g[which]["operator_signature"]),
            "{which} signature over DST_CERT ‖ body"
        );
        assert_eq!(c.to_bytes(), hex(&g[which]["certificate"]), "{which}");
    }
}

#[test]
// oracle: B-shared golden/p3_certificates.json (Appendix B 6): every intermediate value
#[spec("SR-B-6")]
fn p3_cert_golden_intermediate_values_match_the_engine_primitives() {
    let g = json();
    let d = u(&g["d"]) as usize;
    let gens = Generators::derive(d).unwrap();
    let coll: [u8; 16] = arr(&g["collection_id"]);
    let user = KeyPair::from_secret(&arr(&g["keys"]["user"]["secret"]));
    let mut tree = MerkleTree::new();
    for rec in g["records"].as_array().unwrap() {
        let x: Vec<i32> = rec["x"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_i64().unwrap() as i32)
            .collect();
        let r = Scalar::from_canonical_bytes(arr(&rec["r_t"])).unwrap();
        let c_t = encode_point(&commit_record(&gens, &x, &r).unwrap());
        assert_eq!(c_t, arr::<32>(&rec["C_t"]));
        let usig = user.sign(&insert_message(&coll, &c_t));
        assert_eq!(usig, arr::<64>(&rec["user_signature"]));
        let leaf = InsertLeaf {
            collection_id: coll,
            scrambled_id: arr(&rec["scrambled_id"]),
            c_t,
            user_public_key: user.public(),
            user_signature: usig,
        };
        assert_eq!(leaf.to_bytes().to_vec(), hex(&rec["leaf"]));
        assert_eq!(leaf_hash(&leaf.to_bytes()), arr::<32>(&rec["leaf_hash"]));
        tree.push(&leaf.to_bytes());
    }
    let cpj = &g["checkpoint"];
    assert_eq!(tree.root(tree.size()), Some(arr(&cpj["root"])));
    let mut op = EpochSigner::from_secrets(
        u(&g["genesis_ms"]),
        [0u32, 1].map(|e| (e, arr(&g["keys"]["operator"][e.to_string()]["secret"]))),
    );
    let cp = LogCheckpoint::sign(
        &mut op,
        tree.size(),
        arr(&cpj["root"]),
        u(&cpj["timestamp_ms"]),
    )
    .unwrap();
    assert_eq!(cp.to_bytes().to_vec(), hex(&cpj["encoded"]));
    assert_eq!(
        cosign_message(&cp.message()).to_vec(),
        hex(&cpj["cosign_message"])
    );
    for (i, c) in g["cosignatures"].as_array().unwrap().iter().enumerate() {
        let w = KeyPair::from_secret(&arr(&g["keys"]["witness_epoch0"][i]["secret"]));
        assert_eq!(
            w.sign(&cosign_message(&cp.message())),
            arr::<64>(&c["signature"])
        );
    }
    for which in ["group_deletion", "holding_deletion"] {
        let inc = &g[which]["inclusion"];
        let path: Vec<Hash> = inc["path"]
            .as_array()
            .unwrap()
            .iter()
            .map(arr::<32>)
            .collect();
        assert_eq!(tree.inclusion_proof(u(&inc["leaf_index"]), 5), Some(path));
    }
    let gd = &g["group_deletion"];
    let s = |k: &str| -> Vec<i64> {
        gd[k]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_i64().unwrap())
            .collect()
    };
    let r = |k: &str| Scalar::from_canonical_bytes(arr(&gd[k])).unwrap();
    let pre = encode_point(&commit_group(&gens, &s("S_pre"), &r("r_agg_pre")).unwrap());
    let post = encode_point(&commit_group(&gens, &s("S_post"), &r("r_agg_post")).unwrap());
    assert_eq!((pre, post), (arr(&gd["C_S_pre"]), arr(&gd["C_S_post"])));
    let rec_c = &g["records"][2];
    let ctx = DeletionContext {
        c_s_pre: pre,
        c_t: arr(&rec_c["C_t"]),
        scrambled_id: arr(&rec_c["scrambled_id"]),
        database_lsn: u(&gd["database_lsn"]),
        collection_id: coll,
    };
    assert_eq!(ctx.to_bytes().to_vec(), hex(&gd["ctx"]));
    assert!(verify(&gens, &post, &ctx, &hex(&gd["tags"]["4"])).is_ok());
}

#[test]
// oracle: B-shared golden/p3_certificates.json (Appendix B 6)
#[spec("SR-B-6")]
fn p3_cert_parse_reads_the_golden_certificates() {
    let g = json();
    let op1 = KeyPair::from_secret(&arr(&g["keys"]["operator"]["1"]["secret"]));
    for which in ["group_deletion", "holding_deletion"] {
        let bytes = hex(&g[which]["certificate"]);
        let parsed = Certificate::parse(&bytes, 384).unwrap();
        let mut expected = golden_certificate(&g, which);
        expected.sign(&op1);
        assert_eq!(parsed, expected, "{which}");
        assert_eq!(parsed.to_bytes(), bytes);
        assert_eq!(
            parsed.deletion_kind(),
            u8::from(which == "holding_deletion")
        );
    }
}

/// A small certificate whose every field is a recognisable byte pattern; `group` adds tags 2–4
/// with a d = 2 proof (64 + 2 × 32 = 128 bytes).
fn pattern(group: bool) -> Certificate {
    Certificate {
        c_t: [0x11; 32],
        group: group.then(|| GroupFields {
            c_s_pre: [0x22; 32],
            c_s_post: [0x33; 32],
            proof: vec![0x44; 128],
            emptied: true,
        }),
        user_signature: [0x55; 64],
        inclusion: InsertInclusion {
            leaf: InsertLeaf {
                collection_id: [0xDD; 16],
                scrambled_id: [0x99; 64],
                c_t: [0x11; 32],
                user_public_key: [0x66; 32],
                user_signature: [0x55; 64],
            },
            leaf_index: 0x0102,
            checkpoint: LogCheckpoint {
                tree_size: 0x0304,
                root: [0x77; 32],
                timestamp_ms: 0x0506,
                epoch: 0x07,
                operator_signature: [0x88; 64],
            },
            path: vec![[0xA1; 32], [0xA2; 32]],
        },
        cosignatures: vec![Cosignature {
            witness_index: 3,
            witness_epoch: 0x0809,
            signature: [0xBB; 64],
        }],
        key_period: 0x0A0B,
        scrambled_id: [0x99; 64],
        database_lsn: 0x0C0D,
        collection_id: [0xDD; 16],
        operator_signature: [0xEE; 64],
    }
}

/// The bytes of [`pattern`], written out from the §11.1 table and the §11.2 layout.
fn pattern_bytes(group: bool) -> Vec<u8> {
    let rep = |b: u8, n: usize| vec![b; n];
    let mut tag6 = vec![1u8]; // version
    tag6.push(0x01); // insert leaf: type, collection_id, scrambled_id, C_t, user key, signature
    for (b, n) in [(0xDD, 16), (0x99, 64), (0x11, 32), (0x66, 32), (0x55, 64)] {
        tag6.extend(rep(b, n));
    }
    tag6.extend([0, 0, 0, 0, 0, 0, 0x01, 0x02]); // u64be leaf_index
    tag6.extend([0, 0, 0, 0, 0, 0, 0x03, 0x04]); // u64be tree_size
    tag6.extend(rep(0x77, 32)); // root
    tag6.extend([0, 0, 0, 0, 0, 0, 0x05, 0x06]); // u64be timestamp_ms
    tag6.extend([0, 0, 0, 0x07]); // u32be epoch
    tag6.extend(rep(0x88, 64)); // operator signature
    tag6.push(2); // path_len
    tag6.extend(rep(0xA1, 32));
    tag6.extend(rep(0xA2, 32));
    assert_eq!(tag6.len(), 1 + 209 + 8 + 116 + 1 + 64);
    let mut tag7 = vec![1u8, 3, 0, 0, 0x08, 0x09]; // count, witness_index, u32be witness_epoch
    tag7.extend(rep(0xBB, 64));
    let (pre, post, proof, emptied, kind) = if group {
        (rep(0x22, 32), rep(0x33, 32), rep(0x44, 128), 1u8, 0u8)
    } else {
        (vec![], vec![], vec![], 0, 1)
    };
    let fields: [(u8, Vec<u8>); 13] = [
        (1, rep(0x11, 32)),
        (2, pre),
        (3, post),
        (4, proof),
        (5, rep(0x55, 64)),
        (6, tag6),
        (7, tag7),
        (8, vec![0, 0, 0x0A, 0x0B]),
        (9, rep(0x99, 64)),
        (10, vec![0, 0, 0, 0, 0, 0, 0x0C, 0x0D]),
        (11, vec![emptied]),
        (12, vec![kind]),
        (13, rep(0xDD, 16)),
    ];
    let mut out = vec![];
    for (tag, v) in fields {
        out.push(tag);
        out.extend((v.len() as u32).to_be_bytes());
        out.extend(v);
    }
    out.extend([0xFF, 0, 0, 0, 64]);
    out.extend(rep(0xEE, 64));
    out
}

#[test]
// oracle: A §11.1 field table and §11.2 layout, bytes written out by hand
#[spec("SR-11.1-1", "SR-11.1-3", "SR-11.2-1")]
fn p3_cert_layout_matches_section_11_byte_for_byte() {
    for group in [false, true] {
        let c = pattern(group);
        let want = pattern_bytes(group);
        assert_eq!(c.to_bytes(), want, "group = {group}");
        assert_eq!(c.body(), want[..want.len() - 69].to_vec());
        assert_eq!(Certificate::parse(&want, 2).unwrap(), c);
    }
}

#[test]
// oracle: A Appendix A: a group deletion at d = 384 with a 21-hash path is 14,093 bytes
#[spec("SR-A-2")]
fn p3_cert_group_deletion_size_matches_appendix_a() {
    let mut c = pattern(true);
    let g = c.group.as_mut().unwrap();
    g.proof = vec![0; 12_352];
    c.inclusion.path = vec![[0; 32]; 21];
    c.cosignatures = vec![c.cosignatures[0]; 5];
    assert_eq!(c.to_bytes().len(), 14_093);
}

/// Splits [`pattern_bytes`] into its 14 TLVs (tags 1–13 and the trailer).
fn tlvs(b: &[u8]) -> Vec<Vec<u8>> {
    let mut out = vec![];
    let mut pos = 0;
    while pos < b.len() {
        let n = u32::from_be_bytes(b[pos + 1..pos + 5].try_into().unwrap()) as usize;
        out.push(b[pos..pos + 5 + n].to_vec());
        pos += 5 + n;
    }
    out
}

fn with_value(t: &[u8], v: &[u8]) -> Vec<u8> {
    let mut out = vec![t[0]];
    out.extend((v.len() as u32).to_be_bytes());
    out.extend(v);
    out
}

#[test]
// oracle: A §11.1 "A parser MUST reject: missing, repeated or out-of-order tags; a wrong length for any fixed-size field; and trailing bytes"
#[spec("SR-11.1-2")]
fn p3_cert_parser_rejects_malformed_tlv() {
    for group in [false, true] {
        let good = pattern_bytes(group);
        let parts = tlvs(&good);
        assert_eq!(parts.len(), 14);
        let join = |p: &[Vec<u8>]| p.concat();
        for i in 0..14 {
            let mut missing = parts.clone();
            missing.remove(i);
            assert!(
                Certificate::parse(&join(&missing), 2).is_err(),
                "missing #{i}"
            );
            let mut repeated = parts.clone();
            repeated.insert(i, parts[i].clone());
            assert!(
                Certificate::parse(&join(&repeated), 2).is_err(),
                "repeated #{i}"
            );
        }
        for i in 0..13 {
            let mut swapped = parts.clone();
            swapped.swap(i, i + 1);
            assert!(
                Certificate::parse(&join(&swapped), 2).is_err(),
                "swapped #{i}"
            );
        }
        let mut trailing = good.clone();
        trailing.push(0);
        assert_eq!(
            Certificate::parse(&trailing, 2),
            Err(ParseError::TrailingBytes)
        );
        for cut in [0, 1, 4, 5, good.len() - 64, good.len() - 1] {
            assert!(Certificate::parse(&good[..cut], 2).is_err(), "cut at {cut}");
        }
        // A wrong length for each fixed-size field: one byte more and one byte less.
        for (i, len) in [
            (0, 32),
            (4, 64),
            (7, 4),
            (8, 64),
            (9, 8),
            (10, 1),
            (11, 1),
            (12, 16),
        ] {
            for n in [len - 1, len + 1] {
                let mut p = parts.clone();
                p[i] = with_value(&parts[i], &vec![0; n]);
                assert_eq!(
                    Certificate::parse(&join(&p), 2),
                    Err(ParseError::Length { tag: i as u8 + 1 }),
                    "tag {} length {n}",
                    i + 1
                );
            }
        }
        let mut p = parts.clone();
        p[13] = with_value(&parts[13], &[0xEE; 63]);
        assert!(
            Certificate::parse(&join(&p), 2).is_err(),
            "trailer length 63"
        );
    }
}

#[test]
// oracle: A §11.1 tags 2–4 are 32, 32 and 64 + 32·d bytes or empty; tag 7 is u8 count ‖ count × 69; tags 11 and 12 are 0 or 1 (DB-76)
#[spec("SR-11.1-2", "SR-11.1-3")]
fn p3_cert_parser_rejects_bad_variable_fields_and_flag_values() {
    let good = pattern_bytes(true);
    let parts = tlvs(&good);
    let join = |p: &[Vec<u8>]| p.concat();
    let set = |i: usize, v: &[u8]| {
        let mut p = parts.clone();
        p[i] = with_value(&parts[i], v);
        Certificate::parse(&join(&p), 2)
    };
    assert_eq!(set(1, &[0x22; 31]), Err(ParseError::Length { tag: 2 }));
    assert_eq!(set(2, &[0x33; 33]), Err(ParseError::Length { tag: 3 }));
    assert_eq!(
        set(3, &[0x44; 160]),
        Err(ParseError::Length { tag: 4 }),
        "d = 3"
    );
    assert!(
        Certificate::parse(&good, 3).is_err(),
        "the proof is for d = 2"
    );
    let tag7 = &parts[6][5..];
    assert_eq!(
        set(6, &tag7[..tag7.len() - 1]),
        Err(ParseError::Length { tag: 7 })
    );
    let mut two = tag7.to_vec();
    two[0] = 2;
    assert_eq!(set(6, &two), Err(ParseError::Length { tag: 7 }));
    assert_eq!(set(10, &[2]), Err(ParseError::Value { tag: 11 }));
    assert_eq!(set(11, &[2]), Err(ParseError::Value { tag: 12 }));
    assert_eq!(set(11, &[0xFF]), Err(ParseError::Value { tag: 12 }));
}

#[test]
// oracle: A §11.2 "u8 version = 1"; §10.2 an insert leaf starts 0x01; path_len × 32 bytes
#[spec("SR-11.2-1")]
fn p3_cert_parser_rejects_a_bad_insert_inclusion() {
    let good = pattern_bytes(false);
    let parts = tlvs(&good);
    let join = |p: &[Vec<u8>]| p.concat();
    let tag6 = parts[5][5..].to_vec();
    let set = |v: &[u8]| {
        let mut p = parts.clone();
        p[5] = with_value(&parts[5], v);
        Certificate::parse(&join(&p), 2)
    };
    let mut v2 = tag6.clone();
    v2[0] = 2;
    assert_eq!(set(&v2), Err(ParseError::Version));
    let mut delete_leaf = tag6.clone();
    delete_leaf[1] = 0x02;
    assert_eq!(set(&delete_leaf), Err(ParseError::LeafType));
    let mut short_path = tag6.clone();
    short_path.truncate(tag6.len() - 1);
    assert_eq!(set(&short_path), Err(ParseError::Length { tag: 6 }));
    let mut long_path = tag6.clone();
    long_path.extend([0; 32]);
    assert_eq!(set(&long_path), Err(ParseError::Length { tag: 6 }));
}

#[test]
// oracle: A §11.3 steps 6–7: group fields all present with kind 0, all empty with kind 1 and tag 11 = 0
#[spec("SR-11.1-3")]
fn p3_cert_parser_rejects_kind_and_group_fields_that_disagree() {
    let parts = tlvs(&pattern_bytes(true));
    let join = |p: &[Vec<u8>]| p.concat();
    let set = |edits: &[(usize, &[u8])]| {
        let mut p = parts.clone();
        for &(i, v) in edits {
            p[i] = with_value(&parts[i], v);
        }
        Certificate::parse(&join(&p), 2)
    };
    assert_eq!(
        set(&[(11, &[1])]),
        Err(ParseError::Kind),
        "kind 1 with tags 2–4"
    );
    assert_eq!(set(&[(1, &[])]), Err(ParseError::Kind), "tag 2 empty alone");
    assert_eq!(set(&[(3, &[])]), Err(ParseError::Kind), "tag 4 empty alone");
    let holding = [(1, &[][..]), (2, &[][..]), (3, &[][..]), (11, &[1][..])];
    assert_eq!(
        set(&holding),
        Err(ParseError::Kind),
        "holding with tag 11 = 1"
    );
    assert!(set(&[holding[0], holding[1], holding[2], holding[3], (10, &[0])]).is_ok());
    assert_eq!(
        set(&[holding[0], holding[1], holding[2]]),
        Err(ParseError::Kind),
        "kind 0 empty"
    );
}

// The builder.

struct World {
    gens: Generators,
    operator: EpochSigner,
    witnesses: Vec<EpochSigner>,
    user: KeyPair,
    tree: MerkleTree,
    leaves: Vec<InsertLeaf>,
    xs: Vec<Vec<i32>>,
    rs: Vec<Scalar>,
}

const D: usize = 16;
const GENESIS: u64 = 1_790_000_000_000;
const EPOCH_MS: u64 = 7_776_000_000;
const COLL: [u8; 16] = [0xC0; 16];

/// `n` records inserted under one user key (test vectors and test blinding values; keys from
/// the OS).
fn world(n: usize) -> World {
    let gens = Generators::derive(D).unwrap();
    let user = KeyPair::generate();
    let mut w = World {
        operator: EpochSigner::new(GENESIS),
        witnesses: (0..5).map(|_| EpochSigner::new(GENESIS)).collect(),
        user,
        tree: MerkleTree::new(),
        leaves: vec![],
        xs: vec![],
        rs: vec![],
        gens,
    };
    for k in 0..n {
        let x: Vec<i32> = (0..D as i32)
            .map(|i| (k as i32 + 1) * 1000 - i * 77)
            .collect();
        let r = Scalar::from(1_000_003u64 * (k as u64 + 1));
        let c_t = encode_point(&commit_record(&w.gens, &x, &r).unwrap());
        let leaf = InsertLeaf {
            collection_id: COLL,
            scrambled_id: [k as u8; 64],
            c_t,
            user_public_key: w.user.public(),
            user_signature: w.user.sign(&insert_message(&COLL, &c_t)),
        };
        w.tree.push(&leaf.to_bytes());
        w.leaves.push(leaf);
        w.xs.push(x);
        w.rs.push(r);
    }
    w
}

impl World {
    /// A checkpoint of the whole tree at `now`, cosigned by the witnesses in `by`.
    fn checkpoint(&mut self, now: u64, by: &[usize]) -> (LogCheckpoint, Vec<Cosignature>) {
        let size = self.tree.size();
        let cp = LogCheckpoint::sign(&mut self.operator, size, self.tree.root(size).unwrap(), now)
            .unwrap();
        let cosigs = by
            .iter()
            .map(|&i| {
                let w = &mut self.witnesses[i];
                let e = w.epoch_at(now).unwrap();
                Cosignature {
                    witness_index: i as u8,
                    witness_epoch: e,
                    signature: w.key(e).sign(&cosign_message(&cp.message())),
                }
            })
            .collect();
        (cp, cosigs)
    }

    fn inclusion(&self, i: usize, cp: LogCheckpoint) -> InsertInclusion {
        InsertInclusion {
            leaf: self.leaves[i],
            leaf_index: i as u64,
            checkpoint: cp,
            path: self.tree.inclusion_proof(i as u64, cp.tree_size).unwrap(),
        }
    }

    fn rings(&self) -> Vec<Keyring> {
        self.witnesses.iter().map(|w| w.keyring().clone()).collect()
    }

    /// `S` and `r_agg` of the group made of `members`.
    fn state(&self, members: &[usize]) -> (Vec<i64>, Scalar) {
        let mut s = vec![0i64; D];
        let mut r = Scalar::ZERO;
        for &m in members {
            for (si, &xi) in s.iter_mut().zip(&self.xs[m]) {
                *si += i64::from(xi);
            }
            r += self.rs[m];
        }
        (s, r)
    }

    /// Deletes `victim` from the group `members` with a certificate issued at `now`.
    fn delete(
        &mut self,
        members: &[usize],
        victim: usize,
        inc: InsertInclusion,
        cosigs: Vec<Cosignature>,
        lsn: u64,
        now: u64,
    ) -> Result<Certificate, CertError> {
        let (s_pre, r_pre) = self.state(members);
        let rest: Vec<usize> = members.iter().copied().filter(|&m| m != victim).collect();
        let (s_post, r_post) = self.state(&rest);
        let c_s_pre = encode_point(&commit_group(&self.gens, &s_pre, &r_pre).unwrap());
        let rings = self.rings();
        let deletion = Deletion {
            inclusion: inc,
            cosignatures: cosigs,
            database_lsn: lsn,
            removal: Removal::Group {
                c_s_pre,
                s_post: &s_post,
                r_post: &r_post,
                n_post: rest.len() as u64,
            },
        };
        build(
            &self.gens,
            deletion,
            &mut self.operator,
            &rings,
            now,
            &mut StrictProofRng::new(),
        )
    }
}

/// §11.3 checks written out in the test: the trailer under the key of tag 8's epoch, the
/// inclusion path, and for a group deletion the transition and the proof under the context taken
/// from the certificate's own fields.
fn check(w: &World, c: &Certificate) {
    let bytes = c.to_bytes();
    assert_eq!(Certificate::parse(&bytes, D).unwrap(), *c);
    let key = w.operator.keyring().get(c.key_period).unwrap();
    let body = &bytes[..bytes.len() - 69];
    verify_signature(key, &certificate_message(body), &c.operator_signature).unwrap();
    let inc = &c.inclusion;
    assert!(verify_inclusion(
        &leaf_hash(&inc.leaf.to_bytes()),
        inc.leaf_index,
        inc.checkpoint.tree_size,
        &inc.path,
        &inc.checkpoint.root
    ));
    assert_eq!(
        (c.c_t, c.user_signature, c.scrambled_id, c.collection_id),
        (
            inc.leaf.c_t,
            inc.leaf.user_signature,
            inc.leaf.scrambled_id,
            inc.leaf.collection_id
        )
    );
    if let Some(g) = &c.group {
        let (pre, post) = (
            decode_point(&g.c_s_pre).unwrap(),
            decode_point(&g.c_s_post).unwrap(),
        );
        assert!(transition_holds(
            &post,
            &decode_point(&c.c_t).unwrap(),
            &pre
        ));
        let ctx = DeletionContext {
            c_s_pre: g.c_s_pre,
            c_t: c.c_t,
            scrambled_id: c.scrambled_id,
            database_lsn: c.database_lsn,
            collection_id: c.collection_id,
        };
        verify(&w.gens, &g.c_s_post, &ctx, &g.proof).unwrap();
    }
}

#[test]
// oracle: A §11.1 tag 11 "group_emptied_by_this_deletion"; §11.3 step 6: 1 iff C_S_post is the identity (§5.4: an empty group has S = 0, r_agg = 0)
#[spec("SR-11.1-3", "SR-11.3-6", "SR-15.3-4")]
fn p3_cert_builder_marks_the_deletion_that_empties_the_group() {
    let mut w = world(3);
    let (cp, cosigs) = w.checkpoint(GENESIS + 10, &[0, 1, 2, 3, 4]);
    // Group {0, 1}: delete 1 (one member left), then 0 (the group is empty).
    let c1 = w
        .delete(
            &[0, 1],
            1,
            w.inclusion(1, cp),
            cosigs.clone(),
            3,
            GENESIS + 20,
        )
        .unwrap();
    check(&w, &c1);
    let g1 = c1.group.as_ref().unwrap();
    assert!(!g1.emptied);
    assert_ne!(g1.c_s_post, [0; 32]);
    assert_eq!(c1.body()[c1.body().len() - 28], 0, "tag 11 value byte");
    let c0 = w
        .delete(&[0], 0, w.inclusion(0, cp), cosigs, 4, GENESIS + 30)
        .unwrap();
    check(&w, &c0);
    let g0 = c0.group.as_ref().unwrap();
    assert!(g0.emptied);
    assert_eq!(g0.c_s_post, [0; 32], "C_S_post is the identity");
    assert_eq!(g1.c_s_post, g0.c_s_pre, "the certificates chain");
    assert_eq!(c0.body()[c0.body().len() - 28], 1, "tag 11 value byte");
}

#[test]
// oracle: A §11.1 tags 2–4 empty and tag 12 = 1 for a holding-area deletion; §11.3 step 7 tag 11 = 0
#[spec("SR-11.1-3")]
fn p3_cert_builder_holding_area_deletion_has_no_arithmetic_fields() {
    let mut w = world(2);
    let (cp, cosigs) = w.checkpoint(GENESIS + 10, &[0, 1, 2, 3]);
    let rings = w.rings();
    let deletion = Deletion {
        inclusion: w.inclusion(1, cp),
        cosignatures: cosigs,
        database_lsn: 2,
        removal: Removal::Holding,
    };
    let c = build(
        &w.gens,
        deletion,
        &mut w.operator,
        &rings,
        GENESIS + 20,
        &mut StrictProofRng::new(),
    )
    .unwrap();
    check(&w, &c);
    assert!(c.group.is_none());
    assert_eq!(c.deletion_kind(), 1);
    let b = c.to_bytes();
    let parts = tlvs(&b);
    for i in [1, 2, 3] {
        assert_eq!(
            parts[i],
            vec![i as u8 + 1, 0, 0, 0, 0],
            "tag {} empty",
            i + 1
        );
    }
    assert_eq!(parts[10], vec![11, 0, 0, 0, 1, 0]);
    assert_eq!(parts[11], vec![12, 0, 0, 0, 1, 1]);
}

#[test]
// oracle: A §9.8 epochs of 90 days from genesis; tag 8 is the epoch that signs; old keys stay resolvable
#[spec("SR-9.8-4", "SR-9.8-6")]
fn p3_cert_builder_signs_with_the_epoch_of_issue() {
    let mut w = world(1);
    let (cp, cosigs) = w.checkpoint(GENESIS + 10, &[0, 1, 2, 3, 4]);
    for (now, epoch) in [
        (GENESIS + EPOCH_MS - 1, 0),
        (GENESIS + EPOCH_MS, 1),
        (GENESIS + 5 * EPOCH_MS, 5),
    ] {
        let c = w
            .delete(&[0], 0, w.inclusion(0, cp), cosigs.clone(), 1, now)
            .unwrap();
        assert_eq!(c.key_period, epoch);
        check(&w, &c);
    }
    assert!(
        w.operator.keyring().get(0).is_some(),
        "epoch 0 stays resolvable"
    );
}

#[test]
// oracle: A §10.3–10.4, §11.2, §11.3 steps 3–5 and §5.3: the builder never issues what the verifier must reject
fn p3_cert_builder_refuses_what_a_verifier_would_reject() {
    let mut w = world(3);
    let (cp, cosigs) = w.checkpoint(GENESIS + 10, &[0, 1, 2, 3, 4]);
    let now = GENESIS + 20;
    let inc = w.inclusion(1, cp);
    let ok = |w: &mut World, inc: InsertInclusion, cosigs: Vec<Cosignature>, lsn: u64, now: u64| {
        w.delete(&[0, 1], 1, inc, cosigs, lsn, now)
    };
    assert!(ok(&mut w, inc.clone(), cosigs.clone(), 3, now).is_ok());
    assert_eq!(
        ok(&mut w, inc.clone(), cosigs.clone(), 1, now).unwrap_err(),
        CertError::LsnNotAfterInsert
    );
    assert_eq!(
        ok(&mut w, inc.clone(), cosigs[..3].to_vec(), 3, now).unwrap_err(),
        CertError::NotWitnessed
    );
    let dup = vec![cosigs[0], cosigs[1], cosigs[2], cosigs[2]];
    assert_eq!(
        ok(&mut w, inc.clone(), dup, 3, now).unwrap_err(),
        CertError::NotWitnessed
    );
    let mut bad_path = inc.clone();
    bad_path.path[0][0] ^= 1;
    assert_eq!(
        ok(&mut w, bad_path, cosigs.clone(), 3, now).unwrap_err(),
        CertError::NotIncluded
    );
    let mut wrong_leaf = inc.clone();
    wrong_leaf.leaf = w.leaves[2];
    assert_eq!(
        ok(&mut w, wrong_leaf, cosigs.clone(), 3, now).unwrap_err(),
        CertError::NotIncluded
    );
    let mut forged = inc.clone();
    forged.checkpoint.operator_signature[0] ^= 1;
    assert_eq!(
        ok(&mut w, forged, cosigs.clone(), 3, now).unwrap_err(),
        CertError::CheckpointSignature
    );
    assert_eq!(
        ok(&mut w, inc.clone(), cosigs.clone(), 3, GENESIS - 1).unwrap_err(),
        CertError::BeforeGenesis
    );
    // The record is not in the group whose state is given: C_S_post + C_t ≠ C_S_pre (§5.3).
    let rings = w.rings();
    let (s_post, r_post) = w.state(&[0]);
    let c_s_pre =
        encode_point(&commit_group(&w.gens, &w.state(&[0, 2]).0, &w.state(&[0, 2]).1).unwrap());
    let deletion = Deletion {
        inclusion: inc,
        cosignatures: cosigs,
        database_lsn: 3,
        removal: Removal::Group {
            c_s_pre,
            s_post: &s_post,
            r_post: &r_post,
            n_post: 1,
        },
    };
    assert_eq!(
        build(
            &w.gens,
            deletion,
            &mut w.operator,
            &rings,
            now,
            &mut StrictProofRng::new()
        )
        .unwrap_err(),
        CertError::TransitionBroken
    );
}
