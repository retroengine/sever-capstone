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

use crate::checkpoint::*;
use crate::keys::*;
use crate::leaf::*;
use crate::witness::*;

#[test]
// oracle: A §10.2 insert leaf layout (0x01 ‖ collection_id ‖ scrambled_id ‖ C_t ‖ user_public_key ‖
// user_signature = 209 bytes), bytes written by hand
#[spec("SR-10.2-1")]
fn p3_log_insert_leaf_is_the_209_byte_layout() {
    let leaf = InsertLeaf {
        collection_id: [0x11; 16],
        scrambled_id: [0x22; 64],
        c_t: [0x33; 32],
        user_public_key: [0x44; 32],
        user_signature: [0x55; 64],
    };
    let mut want = vec![0x01];
    for (b, n) in [(0x11, 16), (0x22, 64), (0x33, 32), (0x44, 32), (0x55, 64)] {
        want.extend(std::iter::repeat_n(b, n));
    }
    assert_eq!((INSERT_LEAF_LEN, want.len()), (209, 209));
    assert_eq!(leaf.to_bytes().as_slice(), want.as_slice());
    assert_eq!(InsertLeaf::parse(&want), Ok(leaf));
    let mut wrong = want.clone();
    wrong[0] = 0x02;
    assert_eq!(InsertLeaf::parse(&wrong), Err(LeafError::Type));
    assert_eq!(InsertLeaf::parse(&want[..208]), Err(LeafError::Length));
}

#[test]
// oracle: A §10.2 delete leaf (0x02 ‖ certificate bytes)
#[spec("SR-10.2-2")]
fn p3_log_delete_leaf_is_0x02_and_the_certificate() {
    assert_eq!(delete_leaf(&[9, 8, 7]), vec![0x02, 9, 8, 7]);
    assert_eq!(parse_delete_leaf(&[0x02, 9, 8, 7]), Ok(&[9u8, 8, 7][..]));
    assert_eq!(parse_delete_leaf(&[0x01, 9]), Err(LeafError::Type));
    assert_eq!(parse_delete_leaf(&[0x02]), Err(LeafError::Length));
}

#[test]
// oracle: A §10.3 (a checkpoint is (tree_size, root, timestamp_ms, epoch, operator_signature)
// signed over the §9.8 message) and §11.2 (its 116-byte encoding), bytes written by hand
#[spec("SR-10.3-1")]
fn p3_log_checkpoint_is_signed_over_section_9_8_and_encodes_in_116_bytes() {
    // Epoch 258 = 0x102, so a byte-order mistake in the epoch shows (epoch 0 would hide it).
    let mut op = EpochSigner::new(1_000);
    let t = 1_000 + 258 * sever_crypto::EPOCH_MS + 5;
    let cp = LogCheckpoint::sign(&mut op, 0x0102_0304_0506_0708, [0xab; 32], t).unwrap();
    assert_eq!(cp.epoch, 258);
    assert!(cp.verify(op.keyring()));
    let b = cp.to_bytes();
    let mut want = vec![1, 2, 3, 4, 5, 6, 7, 8];
    want.extend([0xab; 32]);
    want.extend(t.to_be_bytes());
    want.extend([0, 0, 1, 2]);
    want.extend(cp.operator_signature);
    assert_eq!((CHECKPOINT_LEN, b.as_slice()), (116, want.as_slice()));
    assert_eq!(LogCheckpoint::parse(&b), Some(cp));
    let mut moved = cp;
    moved.tree_size += 1;
    assert!(
        !moved.verify(op.keyring()),
        "the signature covers tree_size"
    );
    assert!(
        !cp.verify(&Keyring::new()),
        "an unknown epoch does not verify"
    );
}

#[test]
// oracle: A §10.3 and §2.2 (a checkpoint whenever tree_size reaches a multiple of 10,000)
#[spec("SR-10.3-2")]
fn p3_log_checkpoint_cadence_is_every_10000_leaves() {
    assert_eq!(CHECKPOINT_EVERY, 10_000);
    let due: Vec<u64> = [0, 1, 9_999, 10_000, 10_001, 20_000, 30_000, 1_900_000]
        .into_iter()
        .filter(|&n| checkpoint_due(n))
        .collect();
    assert_eq!(due, vec![10_000, 20_000, 30_000, 1_900_000]);
}

fn five_witnesses(op: &mut EpochSigner) -> (Vec<SimulatedWitness>, LogCheckpoint) {
    let genesis = LogCheckpoint::genesis(op).unwrap();
    let ws = (0..WITNESSES)
        .map(|i| SimulatedWitness::new(i, op.genesis_ms(), op.keyring().clone(), genesis))
        .collect();
    (ws, genesis)
}

#[test]
// oracle: A §10.4 and §2.2 (five witnesses, threshold four, distinct witnesses, each valid for its
// epoch; §11.3 step 4)
#[spec("SR-10.4-2", "SR-2.2-2")]
fn p3_log_a_checkpoint_is_witnessed_by_four_distinct_valid_cosignatures() {
    let t0 = 5_000;
    let mut op = EpochSigner::new(t0);
    let (mut ws, _) = five_witnesses(&mut op);
    let mut tree = MerkleTree::new();
    tree.push(b"leaf");
    let cp = LogCheckpoint::sign(&mut op, 1, tree.root(1).unwrap(), t0 + 1).unwrap();
    let sigs: Vec<Cosignature> = ws
        .iter_mut()
        .map(|w| w.cosign(&cp, &[], t0 + 2).unwrap())
        .collect();
    let rings: Vec<Keyring> = ws.iter().map(|w| w.keyring().clone()).collect();
    assert_eq!((WITNESSES, THRESHOLD), (5, 4));
    assert!(is_witnessed(&cp, &sigs, &rings));
    assert!(is_witnessed(&cp, &sigs[..4], &rings));
    assert!(!is_witnessed(&cp, &sigs[..3], &rings), "three of five");
    let dup = vec![sigs[0], sigs[1], sigs[2], sigs[2]];
    assert!(
        !is_witnessed(&cp, &dup, &rings),
        "two from one witness (AT-17)"
    );
    let mut bad = sigs[..4].to_vec();
    bad[3].signature[0] ^= 1;
    assert!(!is_witnessed(&cp, &bad, &rings), "one invalid");
    let mut unknown = sigs[..4].to_vec();
    unknown[3].witness_epoch = 7;
    assert!(
        !is_witnessed(&cp, &unknown, &rings),
        "an epoch not in the anchors (AT-20)"
    );
    let mut out_of_range = sigs[..4].to_vec();
    out_of_range[3].witness_index = 9;
    assert!(
        !is_witnessed(&cp, &out_of_range, &rings),
        "a witness index not in the anchors (AT-20)"
    );
    let other = LogCheckpoint::sign(&mut op, 1, tree.root(1).unwrap(), t0 + 3).unwrap();
    assert!(
        !is_witnessed(&other, &sigs, &rings),
        "cosignatures over another checkpoint (AT-10)"
    );
}

/// A witness that cosigns without checking consistency: must fail the EP-10 contract (P3-T12).
struct CarelessWitness(SimulatedWitness, EpochSigner);
impl Witness for CarelessWitness {
    fn index(&self) -> u8 {
        self.0.index()
    }
    fn last(&self) -> &LogCheckpoint {
        self.0.last()
    }
    fn cosign(
        &mut self,
        new: &LogCheckpoint,
        _proof: &[Hash],
        now_ms: u64,
    ) -> Result<Cosignature, Refusal> {
        let e = self.1.epoch_at(now_ms).ok_or(Refusal::NoEpoch)?;
        let signature = self
            .1
            .key(e)
            .sign(&sever_crypto::cosign_message(&new.message()));
        Ok(Cosignature {
            witness_index: self.index(),
            witness_epoch: e,
            signature,
        })
    }
    fn keyring(&self) -> &Keyring {
        self.1.keyring()
    }
}

#[test]
// oracle: A §10.4 (a witness cosigns only if the consistency proof from its last cosigned checkpoint
// verifies) and Build 3-4 §1.9 P3-T12 (the contract passes for SimulatedWitness and fails for a
// witness that skips the check)
#[spec("SR-10.4-1")]
fn p3_log_ep10_contract_passes_for_simulated_and_fails_for_careless_witnesses() {
    assert_eq!(
        ep10_contract(|ops, g| SimulatedWitness::new(0, 1_700_000_000_000, ops, g)),
        Ok(())
    );
    let careless = ep10_contract(|ops, g| {
        CarelessWitness(
            SimulatedWitness::new(0, 1_700_000_000_000, ops, g),
            EpochSigner::new(1_700_000_000_000),
        )
    });
    assert_eq!(careless, Err(Ep10Violation::CosignedInconsistent));
}

#[test]
// oracle: A §9.8 (old public keys stay resolvable forever, so a checkpoint signed in an earlier
// epoch keeps verifying after later epochs begin)
#[spec("SR-9.8-6")]
fn p3_log_old_epoch_keys_stay_resolvable() {
    let g = 0u64;
    let mut op = EpochSigner::new(g);
    let early = LogCheckpoint::sign(&mut op, 1, [1; 32], g + 10).unwrap();
    let late =
        LogCheckpoint::sign(&mut op, 2, [2; 32], g + 3 * sever_crypto::EPOCH_MS + 10).unwrap();
    assert_eq!((early.epoch, late.epoch), (0, 3));
    assert_ne!(
        op.keyring().get(0),
        op.keyring().get(3),
        "a new key each epoch"
    );
    assert!(early.verify(op.keyring()) && late.verify(op.keyring()));
}

#[test]
// oracle: A §10.3 and DB-79 (genesis = (0, SHA-256(""), creation time, epoch 0), signed; witnesses
// start from it)
#[spec("SR-10.3-4")]
fn p3_log_genesis_checkpoint_is_the_signed_empty_tree() {
    let mut op = EpochSigner::new(42_000);
    let (ws, genesis) = five_witnesses(&mut op);
    assert_eq!(
        (
            genesis.tree_size,
            genesis.root,
            genesis.timestamp_ms,
            genesis.epoch
        ),
        (0, empty_root(), 42_000, 0)
    );
    assert!(genesis.verify(op.keyring()));
    assert!(ws.iter().all(|w| *w.last() == genesis));
}
