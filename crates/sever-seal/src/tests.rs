//! Tests of the sealer. Expected values: RFC 8452's vectors (oracle B,
//! `golden/p4_rfc8452_aes256gcmsiv.json`, extracted mechanically from the pinned RFC text), the
//! §13.2 associated data and the §14 sizes written out by hand (oracle A), Part 2's frozen EP-6
//! contract suite (oracle C), and §13.3's rotation rule stated as properties (oracle A).

use std::collections::BTreeSet;
use std::collections::HashSet;
use std::sync::Arc;

use serde_json::Value;
use sever_keys::{Domain, Key, bucket_of};
use sever_spec::spec;
use sever_txn::sealer::{GroupOwner, RecordOwner, Sealer};
use sever_types::{CollectionId, GroupId, ScrambledId};

use crate::ad::{self, Sid};
use crate::block::{self, BLOCK_BYTES, BucketKey, ENVELOPE_BYTES, Envelope};
use crate::ring::KeyRing;
use crate::{AeadSealer, aead};

const RFC: &str = include_str!("../../../golden/p4_rfc8452_aes256gcmsiv.json");

fn hex(s: &str) -> Vec<u8> {
    (0..s.len() / 2)
        .map(|i| u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap())
        .collect()
}

fn key(b: u8) -> Key {
    Key::from_bytes(&[b; 32])
}

fn dom(c: u8, g: u8) -> Domain {
    let mut group_id = [0u8; 32];
    group_id[0] = g;
    Domain {
        collection_id: [c; 16],
        group_id,
    }
}

fn sid_in_bucket(b: u8, tag: u8) -> Sid {
    let mut s = [tag; 64];
    s[0] = b;
    s
}

// --- RFC 8452 -----------------------------------------------------------------------------------

#[test]
// oracle: B RFC 8452 Appendix C.2 and C.3 (AEAD_AES_256_GCM_SIV), golden/p4_rfc8452_aes256gcmsiv.json
#[spec("SR-13.2-1", "SR-20.3-1")]
fn p4_seal_aes_256_gcm_siv_matches_every_rfc_8452_vector() {
    let g: Value = serde_json::from_str(RFC).unwrap();
    let vectors = g["vectors"].as_array().unwrap();
    assert_eq!(vectors.len(), 26);
    for v in vectors {
        let k: [u8; 32] = hex(v["key"].as_str().unwrap()).try_into().unwrap();
        let nonce: [u8; 12] = hex(v["nonce"].as_str().unwrap()).try_into().unwrap();
        let (aad, pt) = (
            hex(v["aad"].as_str().unwrap()),
            hex(v["plaintext"].as_str().unwrap()),
        );
        let want = [&nonce[..], &hex(v["result"].as_str().unwrap())].concat();
        let k = Key::from_bytes(&k);
        let got = aead::seal_with_nonce(&k, &nonce, &aad, &pt).unwrap();
        assert_eq!(got, want, "{}", v["source"]);
        assert_eq!(*aead::open(&k, &aad, &got).unwrap(), pt, "{}", v["source"]);
        let mut bad = got.clone();
        *bad.last_mut().unwrap() ^= 1;
        assert!(
            aead::open(&k, &aad, &bad).is_err(),
            "{}: a flipped tag bit",
            v["source"]
        );
    }
}

#[test]
// oracle: A §13.2 "a random 96-bit nonce and a 16-byte tag, so every ciphertext costs 28 bytes"
#[spec("SR-13.2-1")]
fn p4_seal_every_ciphertext_has_a_fresh_nonce_and_28_bytes_of_overhead() {
    let k = key(1);
    let a = aead::seal(&k, b"ad", b"same plaintext").unwrap();
    let b = aead::seal(&k, b"ad", b"same plaintext").unwrap();
    assert_eq!(a.len(), 14 + 28);
    assert_ne!(a[..12], b[..12], "two seals share a nonce");
    assert_ne!(a, b);
}

// --- §13.2 associated data ---------------------------------------------------------------------

#[test]
// oracle: A §13.2 table rows 1 and 2 written out by hand
#[spec("SR-13.2-2", "SR-13.2-3")]
fn p4_seal_record_associated_data_is_section_13_2_rows_1_and_2() {
    let (c, s) = ([0xC0; 16], [0x5A; 64]);
    let mut want = vec![0xC0; 16];
    want.extend([0x5A; 64]);
    want.push(0x01);
    assert_eq!(ad::slot_payload(&c, &s), want);
    *want.last_mut().unwrap() = 0x02;
    assert_eq!(ad::passage(&c, &s), want);
    // Bound to its kind: a slot payload does not open as a passage.
    let k = key(2);
    let sealed = aead::seal(&k, &ad::slot_payload(&c, &s), b"x").unwrap();
    assert!(aead::open(&k, &ad::passage(&c, &s), &sealed).is_err());
    assert!(aead::open(&k, &ad::slot_payload(&c, &[0x5B; 64]), &sealed).is_err());
}

#[test]
// oracle: A §13.2 table rows 3, 4 and 5 written out by hand
#[spec("SR-13.2-4", "SR-13.2-5", "SR-13.2-6")]
fn p4_seal_key_and_accumulator_associated_data_is_section_13_2_rows_3_to_5() {
    let d = dom(0xC0, 0x67);
    let s = [0x5A; 64];
    let mut base = vec![0xC0; 16];
    base.push(0x67);
    base.extend([0u8; 31]);
    let row3 = [&base[..], &s[..], &[0, 0, 0, 0, 0, 0, 0, 9]].concat();
    assert_eq!(ad::record_key(&d, &s, 9), row3);
    let row4 = [&base[..], &[63], &[0, 0, 0, 0, 0, 0, 1, 0]].concat();
    assert_eq!(ad::bucket_key(&d, 63, 256), row4);
    let row5 = [
        &base[..],
        &[0, 0, 0, 0, 0, 0, 0, 2],
        &[0, 0, 0, 0, 0, 0, 0, 5],
    ]
    .concat();
    assert_eq!(ad::accumulator(&d, 2, 5), row5);
    // Bound to group, version and n.
    let k = key(3);
    let sealed = aead::seal(&k, &ad::accumulator(&d, 2, 5), b"S || r_agg").unwrap();
    assert!(aead::open(&k, &ad::accumulator(&d, 2, 5), &sealed).is_ok());
    assert!(
        aead::open(&k, &ad::accumulator(&d, 3, 5), &sealed).is_err(),
        "another version"
    );
    assert!(
        aead::open(&k, &ad::accumulator(&d, 2, 6), &sealed).is_err(),
        "another n"
    );
    assert!(aead::open(&k, &ad::accumulator(&dom(0xC0, 0x68), 2, 5), &sealed).is_err());
}

// --- §14 sizes ----------------------------------------------------------------------------------

#[test]
// oracle: A §14.4 (envelope 12 + 32 + 16 = 60), §14.5 (64 × (8 + 60) = 4,352), §14.3 (3,104 + 28)
#[spec("SR-14.4-5", "SR-14.5-1", "SR-14.3-2", "SR-A-3")]
fn p4_seal_envelope_block_and_accumulator_have_the_section_14_sizes() {
    assert_eq!(ENVELOPE_BYTES, 60);
    assert_eq!(BLOCK_BYTES, 4_352);
    let d = dom(1, 1);
    let bks: Vec<BucketKey> = (0..64).map(|_| BucketKey::generate(1)).collect();
    let blk = block::encode_block(&key(4), &d, 1, &bks).unwrap();
    assert_eq!(blk.len(), 4_352);
    assert_eq!(
        &blk[..8],
        &[0, 0, 0, 0, 0, 0, 0, 1],
        "u64be bucket_version first"
    );
    let back = block::decode_block(&key(4), &d, 1, &blk).unwrap();
    assert!(
        back.iter()
            .zip(&bks)
            .all(|(a, b)| a.key == b.key && a.version == b.version)
    );
    assert!(
        block::decode_block(&key(4), &d, 2, &blk).is_err(),
        "bound to the group key version"
    );
    let env = block::wrap_record_key(&bks[0], &d, &[7; 64], &key(5)).unwrap();
    assert_eq!(env.len(), 60);
    let sealed = aead::seal(&key(6), b"", &[0u8; 3_104]).unwrap();
    assert_eq!(sealed.len(), 3_132);
}

// --- EP-6 ---------------------------------------------------------------------------------------

#[test]
// oracle: C Part 2's frozen EP-6 contract suite (sever_txn::contract::ep6_sealer_contract)
#[spec("SR-13.2-1")]
fn p4_seal_aead_sealer_passes_the_frozen_ep6_contract() {
    let s = AeadSealer::new(Arc::new(KeyRing::new()));
    assert_eq!(sever_txn::contract::ep6_sealer_contract(&s), Ok(()));
    assert_eq!(s.sealer_id(), 1);
    assert_eq!((s.seal_overhead(), s.envelope_len()), (28, 60));
}

fn owner<'a>(c: &'a CollectionId, g: &'a GroupId, s: &'a ScrambledId) -> RecordOwner<'a> {
    RecordOwner {
        collection: c,
        group: g,
        scrambled_id: s,
    }
}

#[test]
// oracle: A §13.2 "a slot can move … from the holding area into a new group without being decrypted"
#[spec("SR-13.2-7")]
fn p4_seal_a_flush_moves_a_record_without_touching_its_payload_ciphertext() {
    let ring = Arc::new(KeyRing::new());
    let s = AeadSealer::new(Arc::clone(&ring));
    let cid = CollectionId::from_bytes([9; 16]);
    let (h, g) = (GroupId::Holding, GroupId::Spawned([2; 8]));
    let sid = ScrambledId::from_bytes([0x41; 64]);
    let go = |grp| GroupOwner {
        collection: &cid,
        group: grp,
        n: 0,
    };
    s.next_version(&go(&h), None, false);
    s.next_version(&go(&g), None, false);
    ring.adopt();
    let (env, sealed) = s.seal_record(&owner(&cid, &h, &sid), b"payload").unwrap();
    ring.adopt();
    let moved = s
        .rewrap_record(&owner(&cid, &h, &sid), &owner(&cid, &g, &sid), &env)
        .unwrap();
    ring.adopt();
    assert_ne!(moved, env, "the envelope is re-wrapped for the new group");
    // The payload ciphertext is unchanged and opens in the new group.
    assert_eq!(
        &*s.open_record(&owner(&cid, &g, &sid), &moved, &sealed)
            .unwrap(),
        b"payload"
    );
}

// --- §13.3 rotation -----------------------------------------------------------------------------

/// A committed domain with records in buckets 3 (three records) and 9 (one record).
fn populated() -> (Arc<KeyRing>, Domain, Vec<(Sid, Key)>) {
    let ring = Arc::new(KeyRing::new());
    let d = dom(1, 7);
    ring.next_version(&d, None, false);
    let recs: Vec<(Sid, Key)> = [(3, 1), (3, 2), (3, 3), (9, 4)]
        .iter()
        .map(|&(b, t)| (sid_in_bucket(b, t), Key::generate()))
        .collect();
    for (sid, rk) in &recs {
        ring.join(&d, sid, rk).unwrap();
    }
    ring.adopt();
    (ring, d, recs)
}

#[test]
// oracle: A §13.3 steps 1–4: a new group key, new keys for buckets that lost a record, survivors re-wrapped
#[spec("SR-13.3-1", "SR-13.3-2")]
fn p4_seal_a_departure_rotates_the_group_key_and_the_buckets_it_left() {
    let (ring, d, recs) = populated();
    let (gone, _) = recs[0];
    let before_block = ring.committed_block(&d).unwrap();
    assert_eq!(
        ring.next_version(&d, Some(1), true),
        2,
        "step 1: version + 1"
    );
    let rot = ring.rotate(&d, &[gone]).unwrap();
    assert_eq!(rot.version, 2);
    // Step 4: the two survivors of bucket 3 are re-wrapped (version 2); bucket 9 is untouched.
    let rewrapped: Vec<Sid> = rot.envelopes.iter().map(|(s, _, _)| *s).collect();
    assert_eq!(rewrapped, [recs[1].0, recs[2].0]);
    assert!(rot.envelopes.iter().all(|(_, v, _)| *v == 2));
    let (v, blk) = ring.staged_block(&d).unwrap();
    assert_eq!(v, 2);
    ring.adopt();
    // Every survivor's key is still reachable; the departed record's is not.
    for (sid, rk) in &recs[1..] {
        assert_eq!(&ring.record_key(&d, sid, &[0; 60]).unwrap(), rk);
    }
    assert!(ring.record_key(&d, &gone, &[0; 60]).is_err());
    // Step 3: the new block opens only under the new group key; bucket 3's key changed, 9's did not.
    let gk2 = ring.group_key(&d, 2).unwrap();
    let new = block::decode_block(&gk2, &d, 2, &blk).unwrap();
    assert!(
        ring.group_key(&d, 1).is_err(),
        "the old group key is gone from the ring"
    );
    let old_gk_opens_new_block = block::decode_block(&key(0), &d, 2, &blk).is_ok();
    assert!(!old_gk_opens_new_block);
    let (_, old_blk) = before_block;
    assert_eq!(&old_blk[..8], &[0, 0, 0, 0, 0, 0, 0, 1]);
    assert_eq!((new[3].version, new[9].version), (2, 1));
    assert_eq!(bucket_of(&gone), 3);
}

#[test]
// oracle: A §13.3 "records joining a domain … never rotate anything"
#[spec("SR-13.3-3")]
fn p4_seal_joining_a_domain_rotates_nothing() {
    let (ring, d, _) = populated();
    let (v, blk) = ring.committed_block(&d).unwrap();
    assert_eq!(ring.next_version(&d, Some(v), false), v);
    ring.join(&d, &sid_in_bucket(3, 9), &Key::generate())
        .unwrap();
    assert!(ring.staged_rotations().unwrap().is_empty());
    ring.adopt();
    let (v2, blk2) = ring.committed_block(&d).unwrap();
    assert_eq!(v2, v);
    let gk = ring.group_key(&d, v).unwrap();
    let a = block::decode_block(&gk, &d, v, &blk).unwrap();
    let b = block::decode_block(&gk, &d, v, &blk2).unwrap();
    assert!(
        a.iter()
            .zip(&b)
            .all(|(x, y)| x.key == y.key && x.version == y.version)
    );
}

#[test]
// oracle: A §14.4 (DB-91) a record's current envelope: the store's when its version is current, else the slot's
#[spec("SR-14.4-6")]
fn p4_seal_after_a_restart_a_survivor_opens_through_the_wrapped_key_store() {
    let (ring, d, recs) = populated();
    ring.next_version(&d, Some(1), true);
    let rot = ring.rotate(&d, &[recs[0].0]).unwrap();
    let (v, blk) = ring.staged_block(&d).unwrap();
    ring.adopt();
    let gk = ring.group_key(&d, v).unwrap();
    // A restart: a new ring loads the domain and the store's envelopes; slots still hold the old ones.
    let fresh = KeyRing::new();
    fresh.load_domain(d, v, gk, &blk).unwrap();
    for (sid, bv, env) in &rot.envelopes {
        fresh.load_envelope(d, *sid, *bv, *env);
    }
    let stale = [0xEE; 60]; // the slot's envelope, under the rotated bucket key: never opened
    assert_eq!(
        &fresh.record_key(&d, &recs[1].0, &stale).unwrap(),
        &recs[1].1
    );
    assert_eq!(
        &fresh.record_key(&d, &recs[2].0, &stale).unwrap(),
        &recs[2].1
    );
    // A store entry whose version is not the bucket's current one is ignored: the slot's is used.
    let other = KeyRing::new();
    other
        .load_domain(d, v, ring.group_key(&d, v).unwrap(), &blk)
        .unwrap();
    let (sid, _, env) = rot.envelopes[0];
    other.load_envelope(d, sid, 1, env);
    assert!(
        other.record_key(&d, &sid, &stale).is_err(),
        "the stale slot envelope does not open"
    );
    assert_eq!(&other.record_key(&d, &sid, &env).unwrap(), &recs[1].1);
}

// --- the stage and recovery of the ring (P4-T10 survivors, DB-114) --------------------------------

/// A ring with `populated()`'s committed domain, a rotation of bucket 3 staged and adopted, and the
/// store's envelope for the survivor `recs[1]` at bucket version 2.
fn rotated() -> (Arc<KeyRing>, Domain, Vec<(Sid, Key)>, Sid, Envelope) {
    let (ring, d, recs) = populated();
    ring.next_version(&d, Some(1), true);
    let rot = ring.rotate(&d, &[recs[0].0]).unwrap();
    ring.adopt();
    let (sid, bv, env) = rot.envelopes[0];
    assert_eq!((sid, bv), (recs[1].0, 2));
    (ring, d, recs, sid, env)
}

#[test]
// oracle: A §13.3 / §15.3: a transaction that stages nothing leaves the stage empty, one that stages anything does not
fn p4_seal_the_stage_is_empty_exactly_when_nothing_is_staged() {
    let ring = Arc::new(KeyRing::new());
    assert!(ring.stage_is_empty(), "a fresh ring stages nothing");
    let d = dom(1, 7);
    // a new domain alone (§13.3: a spawned group starts with fresh keys)
    ring.next_version(&d, None, false);
    assert!(!ring.stage_is_empty(), "a staged new domain");
    ring.discard();
    assert!(ring.stage_is_empty(), "a discarded stage is empty");
    ring.next_version(&d, None, false);
    ring.adopt();
    assert!(ring.stage_is_empty(), "an adopted stage is empty");
    // a staged rotation alone
    ring.next_version(&d, Some(1), true);
    assert!(!ring.stage_is_empty(), "a staged rotation");
    ring.discard();
    // a joining record alone
    ring.join(&d, &sid_in_bucket(3, 1), &Key::generate())
        .unwrap();
    assert!(!ring.stage_is_empty(), "a staged joining record");
    ring.adopt();
    // a departing record alone
    ring.depart(&d, &sid_in_bucket(3, 1));
    assert!(!ring.stage_is_empty(), "a staged departure");
    ring.discard();
    // a staged drop alone
    ring.drop_collection(&d.collection_id);
    assert!(!ring.stage_is_empty(), "a staged drop");
    ring.discard();
    assert!(ring.stage_is_empty());
}

#[test]
// oracle: A §15.9 drop collection: after the commit the collection's domains and envelopes are gone from the ring
fn p4_seal_a_staged_drop_removes_the_collections_domains_when_adopted() {
    let (ring, d, recs) = populated();
    let other = dom(2, 7);
    ring.next_version(&other, None, false);
    ring.adopt();
    ring.drop_collection(&d.collection_id);
    assert_eq!(
        ring.active_versions().len(),
        2,
        "a stage is not yet the state"
    );
    let out = ring.adopt();
    assert_eq!(out.dropped, [(d.collection_id, vec![d])]);
    assert_eq!(
        ring.active_versions().keys().copied().collect::<Vec<_>>(),
        [other]
    );
    assert!(ring.record_key(&d, &recs[0].0, &[0; 60]).is_err());
}

#[test]
// oracle: A §15.3 the core drops what a failed planning attempt staged: only what the transaction justifies stays
fn p4_seal_retain_stage_keeps_the_justified_and_drops_the_rest() {
    let ring = Arc::new(KeyRing::new());
    let d = dom(1, 7);
    ring.next_version(&d, None, false);
    ring.drop_collection(&d.collection_id);
    ring.retain_stage(
        &BTreeSet::new(),
        &BTreeSet::new(),
        &HashSet::new(),
        &HashSet::new(),
    );
    assert!(
        ring.stage_is_empty(),
        "nothing is justified: the stage, the drop included, is gone"
    );
    // The new domain is justified, the drop never is.
    ring.next_version(&d, None, false);
    ring.drop_collection(&d.collection_id);
    ring.retain_stage(
        &BTreeSet::from([d]),
        &BTreeSet::new(),
        &HashSet::new(),
        &HashSet::new(),
    );
    assert!(!ring.stage_is_empty(), "the justified new domain stays");
    let out = ring.adopt();
    assert_eq!(out.created, [(d, 1)]);
    assert!(out.dropped.is_empty(), "the unjustified drop was cleared");
}

#[test]
// oracle: A §14.8 (DB-91): the store's envelope serves only until recovery has opened every slot
fn p4_seal_finish_recovery_forgets_the_envelopes_no_slot_claimed() {
    let (ring, d, recs, sid, env) = rotated();
    let gk = ring.group_key(&d, 2).unwrap();
    let (v, blk) = ring.committed_block(&d).unwrap();
    assert_eq!(v, 2);
    let stale = [0xEE; 60];
    let fresh = KeyRing::new();
    fresh.load_domain(d, 2, gk.duplicate(), &blk).unwrap();
    fresh.load_envelope(d, sid, 2, env);
    fresh.finish_recovery();
    assert!(
        fresh.record_key(&d, &sid, &stale).is_err(),
        "the unclaimed store entry is forgotten"
    );
    let kept = KeyRing::new();
    kept.load_domain(d, 2, gk, &blk).unwrap();
    kept.load_envelope(d, sid, 2, env);
    assert_eq!(&kept.record_key(&d, &sid, &stale).unwrap(), &recs[1].1);
    // A record the engine opened is learned: it still opens after recovery forgets the rest.
    kept.finish_recovery();
    assert_eq!(&kept.record_key(&d, &sid, &stale).unwrap(), &recs[1].1);
}

#[test]
// oracle: A §14.8 "the highest version wins": a lower version never replaces a higher one, a higher always does
fn p4_seal_a_stored_envelope_is_replaced_only_by_a_higher_bucket_version() {
    let (ring, d, recs, sid, env) = rotated();
    let gk = ring.group_key(&d, 2).unwrap();
    let (_, blk) = ring.committed_block(&d).unwrap();
    let stale = [0xEE; 60];
    let junk: Envelope = [0xAB; ENVELOPE_BYTES];
    let load = |order: &[(u64, Envelope)]| {
        let r = KeyRing::new();
        r.load_domain(d, 2, gk.duplicate(), &blk).unwrap();
        for (bv, e) in order {
            r.load_envelope(d, sid, *bv, *e);
        }
        r.record_key(&d, &sid, &stale)
    };
    // current version first, an older one after: the current one stays
    assert_eq!(&load(&[(2, env), (1, junk)]).unwrap(), &recs[1].1);
    // an older one first, the current one after: the current one replaces it
    assert_eq!(&load(&[(1, junk), (2, env)]).unwrap(), &recs[1].1);
    // a newer-than-current entry replaces the current one (and is then not the bucket's version)
    assert!(load(&[(2, env), (3, junk)]).is_err());
}

#[test]
// oracle: A §13.3 steps 1–4 on a bucket that loses a record while another record joins it: the joiner is a survivor; other domains and buckets are untouched
fn p4_seal_a_rotation_rewraps_exactly_the_survivors_of_the_buckets_that_lost_a_record() {
    let (ring, d, recs) = populated();
    let other = dom(1, 8);
    ring.next_version(&other, None, false);
    ring.join(&other, &sid_in_bucket(3, 50), &Key::generate())
        .unwrap();
    let joiner = sid_in_bucket(3, 60);
    ring.join(&d, &joiner, &Key::generate()).unwrap();
    ring.next_version(&d, Some(1), true);
    let new = ring.staged_new();
    assert_eq!(new.len(), 1, "the other domain is new in this transaction");
    assert_eq!(new[0].0, other);
    let rot = ring.rotate(&d, &[recs[0].0]).unwrap();
    let sids: Vec<Sid> = rot.envelopes.iter().map(|(s, _, _)| *s).collect();
    assert_eq!(sids, [recs[1].0, recs[2].0, joiner]);
    let staged = ring.staged_rotations().unwrap();
    assert_eq!(staged.len(), 1);
    assert_eq!((staged[0].0, staged[0].1, staged[0].2), (d, 1, 2));
    // the new group key differs from the old one, before and after the commit
    let (old, new_key) = (
        ring.group_key(&d, 1).unwrap(),
        ring.group_key(&d, 2).unwrap(),
    );
    assert!(
        old != new_key,
        "step 1: a new group key, not the old bytes under a new version"
    );
    assert!(ring.group_key(&d, 5).is_err());
    ring.adopt();
    let stored: Vec<(Sid, u64)> = ring.stored_envelopes().iter().map(|e| (e.1, e.2)).collect();
    assert_eq!(stored, [(recs[1].0, 2), (recs[2].0, 2), (joiner, 2)]);
}

#[test]
// oracle: A §15.9 a drop removes one collection's keys and envelopes and leaves every other collection's alone
fn p4_seal_dropping_one_collection_leaves_the_others_keys_and_envelopes() {
    let (ring, d, _) = populated();
    let keep = dom(2, 7);
    ring.next_version(&keep, None, false);
    let (a, b) = (sid_in_bucket(3, 1), sid_in_bucket(3, 2));
    let (ka, kb) = (Key::generate(), Key::generate());
    ring.join(&keep, &a, &ka).unwrap();
    ring.join(&keep, &b, &kb).unwrap();
    ring.adopt();
    ring.drop_collection(&d.collection_id);
    ring.adopt();
    assert_eq!(&ring.record_key(&keep, &a, &[0; 60]).unwrap(), &ka);
    // its bucket membership survives too: a departure re-wraps the other record
    ring.next_version(&keep, Some(1), true);
    let rot = ring.rotate(&keep, &[a]).unwrap();
    assert_eq!(rot.envelopes.iter().map(|e| e.0).collect::<Vec<_>>(), [b]);
    assert!(format!("{ring:?}").starts_with("KeyRing"));
}
