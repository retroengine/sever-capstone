//! Tests of the commitment extension. Expected values come from the spec (oracle A), Part 1's
//! frozen EP-1 contract suite (oracle C) and the reference model's goldens (oracle B-shared).

use std::collections::HashMap;
use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::Value;
use sever_crypto::KeyPair;
use sever_index::blob::snapshot_from_members;
use sever_index::contract::ep1_contract;
use sever_spec::spec;
use sever_types::RecordId;

use super::*;

/// A log stand-in: the next leaf index and the insert leaves' `C_t` by index.
#[derive(Default)]
struct MemLog {
    next: AtomicU64,
    leaves: Mutex<HashMap<u64, [u8; 32]>>,
}

impl LeafLog for MemLog {
    fn next_leaf_index(&self) -> u64 {
        self.next.load(Ordering::SeqCst)
    }
    fn insert_leaf_c_t(&self, index: u64) -> Option<[u8; 32]> {
        self.leaves.lock().unwrap().get(&index).copied()
    }
}

impl MemLog {
    /// Appends an insert leaf carrying `c_t` (what `sever-log` does at commit).
    fn append(&self, c_t: [u8; 32]) {
        let i = self.next.fetch_add(1, Ordering::SeqCst);
        self.leaves.lock().unwrap().insert(i, c_t);
    }
}

fn json(s: &str) -> Value {
    serde_json::from_str(s).unwrap()
}

fn unhex<const N: usize>(v: &Value) -> [u8; N] {
    let s = v.as_str().unwrap();
    (0..N)
        .map(|i| u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap())
        .collect::<Vec<_>>()
        .try_into()
        .unwrap()
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn qvec(v: &Value, d: usize) -> QVec {
    let xs: Vec<i32> = v
        .as_array()
        .unwrap()
        .iter()
        .map(|n| i32::try_from(n.as_i64().unwrap()).unwrap())
        .collect();
    QVec::from_stored(xs, d).unwrap()
}

fn ext(d: usize) -> (CommitmentExtension, Arc<MemLog>) {
    let log = Arc::new(MemLog::default());
    let e = CommitmentExtension::new(Arc::new(Generators::derive(d).unwrap()), log.clone());
    (e, log)
}

/// An honest credential for `x` and `r_t`, signed by `key` for collection `cid`.
fn credential(
    e: &CommitmentExtension,
    key: &KeyPair,
    cid: [u8; 16],
    x: &QVec,
    r_t: &Scalar,
) -> InsertCredential {
    let c_t = encode_point(&e.record_commitment(x, r_t).unwrap());
    InsertCredential {
        collection_id: cid,
        c_t,
        r_t: encode_scalar(r_t),
        user_public_key: key.public(),
        signature: key.sign(&insert_message(&cid, &c_t)),
    }
}

const STREAM: &str = include_str!("../../../golden/p3_group_stream.json");
const FULL: &str = include_str!("../../../golden/p3_full_blob.json");
const CID: [u8; 16] = [0x5e; 16];

#[test]
// oracle: B-shared golden/p3_group_stream.json (the reference model's state after every step of a
// scripted insert/delete stream, §5.3–5.5)
#[spec("SR-5.3-2", "SR-5.4-4", "SR-9.4-2")]
fn p3_commit_stream_matches_the_model_step_by_step() {
    let g = json(STREAM);
    let d = 8;
    let (e, log) = ext(d);
    let key = KeyPair::generate();
    let (mut c_s, mut r_agg) = (GroupCommitment::default(), BlindingTotal::default());
    let mut s = vec![0i64; d];
    let mut live: HashMap<String, (QVec, RecordBlind)> = HashMap::new();
    for (k, step) in g["steps"].as_array().unwrap().iter().enumerate() {
        let id = step["id"].as_str().unwrap().to_string();
        if step["op"] == "insert" {
            let x = qvec(&step["x"], d);
            let r_t = decode_scalar(&unhex::<32>(&step["r_t"])).unwrap();
            let cred = credential(&e, &key, CID, &x, &r_t);
            assert_eq!(
                hex(&cred.c_t),
                step["C_t"].as_str().unwrap(),
                "step {k}: C_t"
            );
            let rec = e.admit(&x, cred).unwrap();
            log.append(encode_point(&e.record_commitment(&x, &r_t).unwrap()));
            e.add(&mut c_s, &mut r_agg, &x, &rec);
            for (a, &v) in s.iter_mut().zip(x.as_slice()) {
                *a += i64::from(v);
            }
            live.insert(id, (x, rec));
        } else if let Some((x, rec)) = live.remove(&id) {
            assert_eq!(step["absent"], false, "step {k}");
            e.check_removal(&x, &rec).unwrap();
            assert_eq!(
                hex(&encode_point(&c_s.0)),
                step["C_S_pre"].as_str().unwrap(),
                "step {k}: C_S_pre"
            );
            e.remove(&mut c_s, &mut r_agg, &x, &rec); // deletion takes no r_t argument (§9.4)
            for (a, &v) in s.iter_mut().zip(x.as_slice()) {
                *a -= i64::from(v);
            }
            assert_eq!(
                hex(&encode_point(&c_s.0)),
                step["C_S_post"].as_str().unwrap(),
                "step {k}: C_S_post"
            );
            assert_eq!(
                c_s.0 == GroupCommitment::default().0,
                step["group_emptied"] == true,
                "step {k}"
            );
        } else {
            assert_eq!(step["absent"], true, "step {k}: AlreadyAbsent");
        }
        let after = &step["after"];
        assert_eq!(
            hex(&encode_point(&c_s.0)),
            after["C_S"].as_str().unwrap(),
            "step {k}: C_S"
        );
        assert_eq!(
            hex(&encode_scalar(&r_agg.0)),
            after["r_agg"].as_str().unwrap(),
            "step {k}: r_agg"
        );
        let want_s: Vec<i64> = after["S"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_i64().unwrap())
            .collect();
        assert_eq!(s, want_s, "step {k}: S");
        e.check_group(&s, &c_s, &r_agg).unwrap();
    }
    assert_eq!(
        encode_point(&c_s.0),
        [0u8; 32],
        "the stream empties the group: C_S = identity"
    );
    assert_eq!(r_agg.0, Scalar::ZERO);
}

#[test]
// oracle: C Part 1's frozen EP-1 contract suite (sever_index::contract::ep1_contract)
#[spec("SR-5.3-2")]
fn p3_commit_passes_the_frozen_ep1_contract() {
    let (e, _) = ext(8);
    let key = KeyPair::generate();
    let recs: Vec<(QVec, RecordBlind)> = (0..5i32)
        .map(|k| {
            let x =
                QVec::from_stored((0..8).map(|i| (k * 1000 - i * 37) * 991).collect(), 8).unwrap();
            let r = Scalar::from(u64::try_from(k).unwrap() * 7 + 3);
            let cred = credential(&e, &key, CID, &x, &r);
            (x.clone(), e.admit(&x, cred).unwrap())
        })
        .collect();
    // ep1_contract calls check_removal, which reads the insert leaves: none are logged here, so a
    // log that holds every record's C_t at index 0 cannot serve; use one log per record instead.
    for (x, rec) in &recs {
        let log = Arc::new(MemLog::default());
        log.leaves.lock().unwrap().insert(
            rec.insert_leaf_index,
            encode_point(&e.record_commitment(x, &rec.r_t).unwrap()),
        );
        let e1 = CommitmentExtension::new(Arc::new(e.generators().clone()), log);
        assert_eq!(ep1_contract(&e1, &[(x.clone(), rec.clone())]), Ok(()));
    }
}

#[test]
// oracle: A §15.1 step 2, §9.3, §9.8, §17 (CommitmentMismatch, BadUserSignature) and DB-78
#[spec("SR-9.3-3", "SR-15.1-3", "SR-17-3", "SR-17-4")]
fn p3_commit_admit_recomputes_c_t_and_checks_the_signature() {
    let (e, log) = ext(8);
    let key = KeyPair::generate();
    let x = QVec::from_stored(vec![5, -6, 7, -8, 9, -10, 11, -12], 8).unwrap();
    let r = Scalar::from(4242u64);
    log.next.store(17, Ordering::SeqCst);
    let rec = e.admit(&x, credential(&e, &key, CID, &x, &r)).unwrap();
    assert_eq!((rec.insert_leaf_index, rec.has_rt, rec.r_t), (17, 1, r));
    // Another r_t, or another vector, than the one C_t commits to.
    let mut c = credential(&e, &key, CID, &x, &r);
    c.r_t = encode_scalar(&(r + Scalar::ONE));
    assert_eq!(e.admit(&x, c).err(), Some(Error::CommitmentMismatch));
    let y = QVec::from_stored(vec![5, -6, 7, -8, 9, -10, 11, -13], 8).unwrap();
    assert_eq!(
        e.admit(&y, credential(&e, &key, CID, &x, &r)).err(),
        Some(Error::CommitmentMismatch)
    );
    // A signature over another collection, by another key, or altered.
    let mut c = credential(&e, &key, CID, &x, &r);
    c.collection_id = [0x5f; 16];
    assert_eq!(e.admit(&x, c).err(), Some(Error::BadUserSignature));
    let mut c = credential(&e, &key, CID, &x, &r);
    c.user_public_key = KeyPair::generate().public();
    assert_eq!(e.admit(&x, c).err(), Some(Error::BadUserSignature));
    let mut c = credential(&e, &key, CID, &x, &r);
    c.signature[10] ^= 1;
    assert_eq!(e.admit(&x, c).err(), Some(Error::BadUserSignature));
}

#[test]
// oracle: A §9.9 (C_t MUST NOT be the identity; canonical scalars) and DB-78 (a malformed credential
// is CommitmentMismatch)
#[spec("SR-9.9-2")]
fn p3_commit_admit_refuses_an_identity_or_non_canonical_credential() {
    let (e, _) = ext(8);
    let key = KeyPair::generate();
    let zero = QVec::from_stored(vec![0; 8], 8).unwrap();
    // x̃ = 0 and r_t = 0 commit to the identity: refused although the recomputation matches.
    let c = credential(&e, &key, CID, &zero, &Scalar::ZERO);
    assert_eq!(c.c_t, [0u8; 32]);
    assert_eq!(e.admit(&zero, c).err(), Some(Error::CommitmentMismatch));
    let x = QVec::from_stored(vec![1; 8], 8).unwrap();
    let mut c = credential(&e, &key, CID, &x, &Scalar::ONE);
    c.r_t = [0xff; 32]; // ≥ ℓ
    assert_eq!(e.admit(&x, c).err(), Some(Error::CommitmentMismatch));
}

#[test]
// oracle: A §14.4 and DB-46 (record secret u64be insert_leaf_index ‖ u8 has_rt ‖ r_t, 41 bytes;
// has_rt ≠ 1 is an IntegrityViolation), bytes written by hand
#[spec("SR-14.4-4", "SR-14.4-3")]
fn p3_commit_record_secret_has_the_41_byte_layout() {
    let rec = RecordBlind {
        insert_leaf_index: 0x0102_0304_0506_0708,
        has_rt: 1,
        r_t: Scalar::from(0x0a0bu64),
    };
    let mut want = vec![1, 2, 3, 4, 5, 6, 7, 8, 1, 0x0b, 0x0a];
    want.extend([0u8; 30]);
    let got = CommitmentExtension::encode_record_secret(&rec);
    assert_eq!(
        (got.len(), CommitmentExtension::RECORD_SECRET_LEN),
        (41, 41)
    );
    assert_eq!(got, want);
    assert_eq!(
        CommitmentExtension::decode_record_secret(&got).unwrap(),
        rec
    );
    let mut bad = want.clone();
    bad[8] = 0;
    assert_eq!(
        CommitmentExtension::decode_record_secret(&bad).err(),
        Some(Error::IntegrityViolation {
            invariant: "§14.4 has_rt"
        })
    );
    assert!(CommitmentExtension::decode_record_secret(&want[..40]).is_err());
    let rec0 = RecordBlind {
        has_rt: 0,
        ..rec.clone()
    };
    let (e, _) = ext(8);
    let x = QVec::from_stored(vec![1; 8], 8).unwrap();
    assert_eq!(
        e.check_removal(&x, &rec0).err(),
        Some(Error::IntegrityViolation {
            invariant: "§14.4 has_rt"
        })
    );
}

#[test]
// oracle: A §15.3 step 2 (the stored x̃ and r_t must reproduce the C_t in the insert leaf,
// otherwise IntegrityViolation)
#[spec("SR-15.3-2")]
fn p3_commit_removal_check_compares_with_the_logged_c_t() {
    let (e, log) = ext(8);
    let key = KeyPair::generate();
    let x = QVec::from_stored(vec![3, 1, 4, 1, 5, 9, 2, 6], 8).unwrap();
    let r = Scalar::from(31u64);
    let rec = e.admit(&x, credential(&e, &key, CID, &x, &r)).unwrap();
    // No insert leaf yet: refused.
    assert_eq!(
        e.check_removal(&x, &rec).err(),
        Some(Error::IntegrityViolation {
            invariant: "§15.3 insert leaf"
        })
    );
    log.append(encode_point(&e.record_commitment(&x, &r).unwrap()));
    assert_eq!(e.check_removal(&x, &rec), Ok(()));
    // A stored vector or r_t that no longer reproduces the leaf: refused.
    let y = QVec::from_stored(vec![3, 1, 4, 1, 5, 9, 2, 7], 8).unwrap();
    assert_eq!(
        e.check_removal(&y, &rec).err(),
        Some(Error::IntegrityViolation {
            invariant: "§15.3 C_t"
        })
    );
    let tampered = RecordBlind {
        r_t: r + Scalar::ONE,
        ..rec.clone()
    };
    assert_eq!(
        e.check_removal(&x, &tampered).err(),
        Some(Error::IntegrityViolation {
            invariant: "§15.3 C_t"
        })
    );
}

#[test]
// oracle: A §21 INV-3 (C_S = r_agg·H + Σ scalar(S_i)·G_i)
#[spec("SR-21-3")]
fn p3_commit_group_check_is_inv_3() {
    let (e, _) = ext(8);
    let key = KeyPair::generate();
    let x = QVec::from_stored(vec![10, 20, 30, 40, -50, -60, -70, -80], 8).unwrap();
    let r = Scalar::from(9u64);
    let rec = e.admit(&x, credential(&e, &key, CID, &x, &r)).unwrap();
    let (mut c_s, mut r_agg) = (GroupCommitment::default(), BlindingTotal::default());
    e.add(&mut c_s, &mut r_agg, &x, &rec);
    let s: Vec<i64> = x.as_slice().iter().map(|&v| i64::from(v)).collect();
    assert_eq!(e.check_group(&s, &c_s, &r_agg), Ok(()));
    let mut s2 = s.clone();
    s2[0] += 1;
    assert_eq!(
        e.check_group(&s2, &c_s, &r_agg).err(),
        Some(Error::IntegrityViolation { invariant: "INV-3" })
    );
    let r2 = BlindingTotal(r_agg.0 + Scalar::ONE);
    assert_eq!(
        e.check_group(&s, &c_s, &r2).err(),
        Some(Error::IntegrityViolation { invariant: "INV-3" })
    );
}

#[test]
// oracle: B-shared golden/p3_full_blob.json (Appendix B vector 8, full form, by the reference model)
#[spec("SR-5.5-5", "SR-B-8")]
fn p3_commit_full_blob_matches_golden_vector_8() {
    let g = json(FULL);
    let d = usize::try_from(g["d"].as_u64().unwrap()).unwrap();
    let (e, _) = ext(d);
    let key = KeyPair::generate();
    let mut rows = Vec::new();
    for m in g["members"].as_array().unwrap() {
        let id = RecordId::new(m["id"].as_str().unwrap()).unwrap();
        let x = qvec(&m["x"], d);
        let r = decode_scalar(&unhex::<32>(&m["r_t"])).unwrap();
        let rec = e.admit(&x, credential(&e, &key, CID, &x, &r)).unwrap();
        rows.push((id, x, rec));
    }
    let refs: Vec<_> = rows.iter().map(|(i, x, r)| (i, x, r)).collect();
    let snap = snapshot_from_members(&e, d, &refs);
    assert_eq!(&snap.blob[..6], b"SEVERG");
    assert_eq!(hex(&snap.blob), g["blob"].as_str().unwrap());
    assert_eq!(
        hex(&encode_point(&snap.ext_public.0)),
        g["C_S"].as_str().unwrap()
    );
}

#[test]
// oracle: A §17 DuplicateRecord { same_commitment }: a retry carries the live record's C_t
fn p3_commit_same_commitment_recognises_a_retried_insert() {
    let (e, _) = ext(8);
    let key = KeyPair::generate();
    let x = QVec::from_stored(vec![2; 8], 8).unwrap();
    let r = Scalar::from(77u64);
    let rec = e.admit(&x, credential(&e, &key, CID, &x, &r)).unwrap();
    assert!(e.same_commitment(&x, &rec, &x, &credential(&e, &key, CID, &x, &r)));
    assert!(!e.same_commitment(
        &x,
        &rec,
        &x,
        &credential(&e, &key, CID, &x, &(r + Scalar::ONE))
    ));
}

/// The golden vector 8 group (B-shared), built through the extension: its snapshot and members.
fn golden_group() -> (
    CommitmentExtension,
    usize,
    Vec<(RecordId, QVec, RecordBlind)>,
) {
    let g = json(FULL);
    let d = usize::try_from(g["d"].as_u64().unwrap()).unwrap();
    let (e, _) = ext(d);
    let key = KeyPair::generate();
    let rows = g["members"]
        .as_array()
        .unwrap()
        .iter()
        .map(|m| {
            let x = qvec(&m["x"], d);
            let r = decode_scalar(&unhex::<32>(&m["r_t"])).unwrap();
            let rec = e.admit(&x, credential(&e, &key, CID, &x, &r)).unwrap();
            (RecordId::new(m["id"].as_str().unwrap()).unwrap(), x, rec)
        })
        .collect();
    (e, d, rows)
}

#[test]
// oracle: A §5.5 full form: magic SEVERG, extension region C_S ‖ r_agg (64), and the SR-5.5-2 rejections (count ≠ n, unsorted or duplicate, empty ID, trailing bytes, the wrong magic, SEVERC included); B-shared golden vector 8
#[spec("SR-5.5-6")]
fn p3_commit_full_form_parser_rejects_what_section_5_5_rejects() {
    let (e, d, rows) = golden_group();
    let refs: Vec<_> = rows.iter().map(|(i, x, r)| (i, x, r)).collect();
    let blob = snapshot_from_members(&e, d, &refs).blob;
    let magic = CommitmentExtension::BLOB_MAGIC;
    let parsed = sever_index::blob::parse_blob(&blob, &magic, 64).unwrap();
    assert_eq!(parsed.members.len(), rows.len());
    let reject = |b: &[u8]| sever_index::blob::parse_blob(b, &magic, 64).err();
    use sever_index::blob::BlobReject as R;
    let mut core = blob.clone();
    core[..6].copy_from_slice(b"SEVERC");
    assert_eq!(reject(&core), Some(R::Magic), "the core form's magic");
    assert_eq!(
        reject(&[blob.as_slice(), &[0]].concat()),
        Some(R::TrailingBytes)
    );
    assert_eq!(reject(&blob[..blob.len() - 1]), Some(R::Truncated));
    // Header: magic (6) ‖ u16be version ‖ u16be d ‖ u64be n ‖ S (8·d) ‖ region (64) ‖ u64be count.
    let count_at = 6 + 2 + 2 + 8 + 8 * d + 64;
    let mut wrong_count = blob.clone();
    wrong_count[count_at + 7] ^= 1;
    assert!(reject(&wrong_count).is_some(), "member_count ≠ n");
}

#[test]
// oracle: A §5.5 "With commitments, assert_state_equivalent compares all five fields … a corruption of C_S or r_agg alone MUST be caught"
#[spec("SR-5.5-7")]
fn p3_commit_state_equivalence_catches_c_s_or_r_agg_alone() {
    let (e, d, rows) = golden_group();
    let refs: Vec<_> = rows.iter().map(|(i, x, r)| (i, x, r)).collect();
    let good = snapshot_from_members(&e, d, &refs);
    // C_S alone corrupted.
    let mut bad = good.clone();
    bad.ext_public = GroupCommitment(bad.ext_public.0 + *Generators::derive(1).unwrap().h());
    assert_eq!(
        sever_index::blob::assert_state_equivalent(&good, &bad),
        Err(sever_index::blob::Field::CommitmentS)
    );
    // r_agg alone corrupted (C_S unchanged): only the blob's region shows it.
    let mut state = sever_index::changeset::GroupState::<CommitmentExtension>::empty(d);
    for (_, x, rec) in &rows {
        for (acc, &v) in state.s.iter_mut().zip(x.as_slice()) {
            *acc += i64::from(v);
        }
        state.n += 1;
        e.add(&mut state.ext_public, &mut state.ext_secret, x, rec);
    }
    state.ext_secret = BlindingTotal(state.ext_secret.0 + Scalar::ONE);
    let pairs: Vec<(&RecordId, &QVec)> = rows.iter().map(|(i, x, _)| (i, x)).collect();
    let mut bad = good.clone();
    bad.blob = sever_index::blob::canonical_blob(&e, d, &state, &pairs);
    assert_eq!(bad.ext_public, good.ext_public);
    assert_eq!(
        sever_index::blob::assert_state_equivalent(&good, &bad),
        Err(sever_index::blob::Field::Blob)
    );
}
