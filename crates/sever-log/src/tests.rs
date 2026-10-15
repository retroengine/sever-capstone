//! Tests of the log. Expected values come from RFC 9162 (its §2.1.5 example, node names worked out
//! by hand: oracle A) and the reference model's Appendix B vector 9 (oracle B-shared).

use serde_json::Value;
use sever_spec::spec;

use crate::merkle::*;

const M7: &str = include_str!("../../../golden/p3_merkle_7.json");

fn json(s: &str) -> Value {
    serde_json::from_str(s).unwrap()
}

fn h32(v: &Value) -> Hash {
    let s = v.as_str().unwrap();
    (0..32)
        .map(|i| u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap())
        .collect::<Vec<_>>()
        .try_into()
        .unwrap()
}

fn tree7() -> (MerkleTree, Vec<Vec<u8>>) {
    let d: Vec<Vec<u8>> = (0..7).map(|i| format!("d{i}").into_bytes()).collect();
    let mut t = MerkleTree::new();
    for (i, x) in d.iter().enumerate() {
        assert_eq!(t.push(x), i as u64);
    }
    (t, d)
}

#[test]
// oracle: A RFC 9162 §2.1.5 worked example (spec §10.1): nodes a…l named and combined by hand
#[spec("SR-10.1-1", "SR-10.1-2")]
fn p3_log_tree_matches_the_rfc9162_worked_example() {
    let (t, d) = tree7();
    let [a, b, c, dd, e, f, d6] = std::array::from_fn(|i| leaf_hash(&d[i]));
    let (g, h, i, j) = (node_hash(&a, &b), node_hash(&c, &dd), node_hash(&e, &f), d6);
    let (k, l) = (node_hash(&g, &h), node_hash(&i, &j));
    assert_eq!(t.root(7), Some(node_hash(&k, &l)));
    assert_eq!(t.root(3), Some(node_hash(&g, &c)), "hash0");
    assert_eq!(t.root(4), Some(k), "hash1");
    assert_eq!(t.root(6), Some(node_hash(&k, &i)), "hash2");
    assert_eq!(t.root(0), Some(empty_root()));
    use sha2::Digest;
    assert_eq!(
        empty_root(),
        <[u8; 32]>::from(sha2::Sha256::digest(b"")),
        "MTH({{}}) = HASH()"
    );
    assert_eq!(
        leaf_hash(b"x"),
        <[u8; 32]>::from(sha2::Sha256::digest(b"\x00x"))
    );
    assert_eq!(t.inclusion_proof(0, 7).unwrap(), vec![b, h, l]);
    assert_eq!(t.inclusion_proof(3, 7).unwrap(), vec![c, g, l]);
    assert_eq!(t.inclusion_proof(4, 7).unwrap(), vec![f, j, k]);
    assert_eq!(t.inclusion_proof(6, 7).unwrap(), vec![i, k]);
    assert_eq!(t.consistency_proof(3, 7).unwrap(), vec![c, dd, g, l]);
}

#[test]
// oracle: B-shared golden/p3_merkle_7.json (Appendix B vector 9, the model's RFC 9162 definitions)
#[spec("SR-10.1-2", "SR-B-9")]
fn p3_log_proofs_match_golden_vector_9_and_verify() {
    let g = json(M7);
    let (t, d) = tree7();
    for (n, root) in g["roots"].as_array().unwrap().iter().enumerate() {
        assert_eq!(t.root(n as u64), Some(h32(root)), "root({n})");
    }
    for p in g["inclusion"].as_array().unwrap() {
        let (i, n) = (p["index"].as_u64().unwrap(), p["size"].as_u64().unwrap());
        let want: Vec<Hash> = p["path"].as_array().unwrap().iter().map(h32).collect();
        assert_eq!(t.inclusion_proof(i, n).unwrap(), want, "PATH({i}, {n})");
        let leaf = leaf_hash(&d[i as usize]);
        assert!(
            verify_inclusion(&leaf, i, n, &want, &t.root(n).unwrap()),
            "verify PATH({i}, {n})"
        );
    }
    for p in g["consistency"].as_array().unwrap() {
        let (m, n) = (p["first"].as_u64().unwrap(), p["second"].as_u64().unwrap());
        let want: Vec<Hash> = p["proof"].as_array().unwrap().iter().map(h32).collect();
        assert_eq!(t.consistency_proof(m, n).unwrap(), want, "PROOF({m}, {n})");
        assert!(
            verify_consistency(m, n, &t.root(m).unwrap(), &t.root(n).unwrap(), &want),
            "verify PROOF({m}, {n})"
        );
    }
}

#[test]
// oracle: A RFC 9162 §2.1.3.2 and §2.1.4.2 (a proof verifies only its own leaf, index, size and
// roots)
#[spec("SR-10.1-2")]
fn p3_log_verifiers_reject_altered_proofs() {
    let (t, d) = tree7();
    let root7 = t.root(7).unwrap();
    let p = t.inclusion_proof(4, 7).unwrap();
    let leaf = leaf_hash(&d[4]);
    assert!(verify_inclusion(&leaf, 4, 7, &p, &root7));
    assert!(
        !verify_inclusion(&leaf_hash(b"d9"), 4, 7, &p, &root7),
        "another leaf"
    );
    assert!(!verify_inclusion(&leaf, 5, 7, &p, &root7), "another index");
    assert!(
        !verify_inclusion(&leaf, 7, 7, &p, &root7),
        "index beyond the tree"
    );
    assert!(
        !verify_inclusion(&leaf, 4, 7, &p[..2], &root7),
        "a node short"
    );
    let mut q = p.clone();
    q.push(root7);
    assert!(
        !verify_inclusion(&leaf, 4, 7, &q, &root7),
        "a node too many"
    );
    assert!(
        !verify_inclusion(&leaf, 4, 7, &p, &t.root(6).unwrap()),
        "another root"
    );
    let c = t.consistency_proof(3, 7).unwrap();
    let (r3, r6) = (t.root(3).unwrap(), t.root(6).unwrap());
    assert!(verify_consistency(3, 7, &r3, &root7, &c));
    assert!(
        !verify_consistency(3, 7, &r6, &root7, &c),
        "another first root"
    );
    assert!(
        !verify_consistency(3, 7, &r3, &r6, &c),
        "another second root (a fork)"
    );
    assert!(!verify_consistency(3, 7, &r3, &root7, &[]), "empty proof");
    assert!(!verify_consistency(0, 7, &r3, &root7, &c), "first = 0");
    assert!(
        !verify_consistency(7, 7, &root7, &root7, &c),
        "first = second"
    );
}

#[test]
// oracle: A §10.5 (every level of the complete subtrees is kept, so an inclusion proof takes
// O(log n) time) — counted in node hashes; and RFC 9162 §2.1.3.2 (each proof verifies)
#[spec("SR-10.5-2")]
fn p3_log_proofs_cost_logarithmic_work_at_any_size() {
    let mut t = MerkleTree::new();
    let n: u64 = (1 << 16) + 5;
    for i in 0..n {
        t.push(&i.to_be_bytes());
    }
    let log2n = 64 - n.leading_zeros() as u64; // 17
    for (m, size) in [(0, n), (n - 1, n), (12_345, n), (40_000, 50_001), (7, 9)] {
        NODE_HASHES.with(|c| c.set(0));
        let p = t.inclusion_proof(m, size).unwrap();
        let root = t.root(size).unwrap();
        let work = NODE_HASHES.with(|c| c.get());
        assert!(
            work <= 4 * log2n,
            "PATH({m}, {size}) took {work} node hashes"
        );
        assert!(verify_inclusion(
            &leaf_hash(&m.to_be_bytes()),
            m,
            size,
            &p,
            &root
        ));
    }
    NODE_HASHES.with(|c| c.set(0));
    let p = t.consistency_proof(1000, n).unwrap();
    assert!(NODE_HASHES.with(|c| c.get()) <= 4 * log2n);
    assert!(verify_consistency(
        1000,
        n,
        &t.root(1000).unwrap(),
        &t.root(n).unwrap(),
        &p
    ));
}

#[test]
// oracle: D recovery rebuilds the tree from stored leaf hashes (§10.5) and must agree with the
// tree built from the leaves
fn p3_log_tree_rebuilt_from_leaf_hashes_is_identical() {
    let (t, _) = tree7();
    let mut r = MerkleTree::new();
    for i in 0..t.size() {
        r.push_hash(t.leaf(i).unwrap());
    }
    for n in 0..=7 {
        assert_eq!(r.root(n), t.root(n));
    }
}
