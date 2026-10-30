//! The participant's record bytes written out by hand from spec §14.6 and §14.8 (oracle A), its
//! merge rules, and Part 2's frozen EP-7 contract (oracle C).

use std::sync::Arc;

use sever_keys::Domain;
use sever_seal::KeyRing;
use sever_spec::spec;
use sever_txn::TxnParticipant;
use sever_txn::contract::{ProbedParticipant, ep7_participant_contract};

use crate::records::*;
use crate::{KeyRotationParticipant, parse_wal};

fn dom() -> Domain {
    let mut group_id = [0u8; 32];
    group_id[..11].copy_from_slice(b"frozen-0002");
    Domain {
        collection_id: [0xC1; 16],
        group_id,
    }
}

#[test]
// oracle: A §14.8 wrapped-key store values, kinds 1–3, and §14.6 BUCKET_BLOCK / EXTENSION payloads
#[spec("SR-14.8-4", "SR-14.6-5")]
fn p4_erasure_store_values_are_the_bytes_of_section_14_8() {
    let d = dom();
    let block = vec![0x42u8; 4_352];
    let mut want = vec![0x01];
    want.extend([0xC1; 16]);
    want.extend(b"frozen-0002");
    want.extend([0u8; 21]);
    want.extend([0, 0, 0, 0, 0, 0, 0, 3]);
    want.extend(&block);
    assert_eq!(block_value(&d, 3, &block), want);
    assert_eq!(want.len(), 1 + 16 + 32 + 8 + 4_352);
    let entry = ([0x55u8; 64], 7u64, [0x66u8; 60]);
    let mut want2 = vec![0x02];
    want2.extend([0xC1; 16]);
    want2.extend(b"frozen-0002");
    want2.extend([0u8; 21]);
    want2.extend([0, 0, 0, 1]); // u32be count
    want2.extend([0x55; 64]);
    want2.extend([0, 0, 0, 0, 0, 0, 0, 7]);
    want2.extend([0x66; 60]);
    assert_eq!(envelopes_value(&d, &[entry]), want2);
    let mut want3 = vec![0x03];
    want3.extend([0xC1; 16]);
    assert_eq!(drop_value(&[0xC1; 16]), want3);
    assert_eq!(KEY_PARTICIPANT_ID, 4);
    // Strict parsing: every value round-trips, a truncated one is refused.
    for v in [&want, &want2, &want3] {
        assert!(parse(v).is_ok());
        assert!(parse(&v[..v.len() - 1]).is_err());
    }
}

#[test]
// oracle: A §14.8 merge rules: the highest version wins, in any order; a drop removes its domains
#[spec("SR-14.8-4")]
fn p4_erasure_store_merge_is_monotonic_in_any_order() {
    let d = dom();
    let values = [
        Value::Block(d, 2, vec![2; 4_352]),
        Value::Block(d, 5, vec![5; 4_352]),
        Value::Envelopes(d, vec![([1; 64], 9, [9; 60])]),
        Value::Envelopes(d, vec![([1; 64], 4, [4; 60])]),
    ];
    let mut a = Durable::default();
    let mut b = Durable::default();
    for v in values.iter().cloned() {
        a.merge(v);
    }
    for v in values.iter().rev().cloned() {
        b.merge(v);
    }
    assert_eq!(a, b);
    assert_eq!(a.blocks[&d].0, 5);
    assert_eq!(a.envelopes[&(d, [1; 64])].0, 9);
    a.merge(Value::Drop([0xC1; 16]));
    assert!(a.blocks.is_empty() && a.envelopes.is_empty());
}

struct Probe(KeyRotationParticipant);

impl TxnParticipant<sever_index::NoExtension> for Probe {
    fn id(&self) -> u16 {
        <KeyRotationParticipant as TxnParticipant<sever_index::NoExtension>>::id(&self.0)
    }
    fn owned_types(&self) -> &[sever_format::RecordType] {
        <KeyRotationParticipant as TxnParticipant<sever_index::NoExtension>>::owned_types(&self.0)
    }
    fn prepare(
        &mut self,
        d: &mut sever_txn::TxnDraft<'_, sever_index::NoExtension>,
    ) -> Result<(), sever_types::Error> {
        self.0.prepare(d)
    }
    fn phase_a(&mut self) -> Result<(), sever_types::Error> {
        <KeyRotationParticipant as TxnParticipant<sever_index::NoExtension>>::phase_a(&mut self.0)
    }
    fn abort(&mut self) {
        <KeyRotationParticipant as TxnParticipant<sever_index::NoExtension>>::abort(&mut self.0);
    }
    fn after_commit(&mut self) -> Result<(), sever_types::Error> {
        <KeyRotationParticipant as TxnParticipant<sever_index::NoExtension>>::after_commit(
            &mut self.0,
        )
    }
    fn replay(&mut self, r: &sever_format::WalRecord) -> Result<(), sever_types::Error> {
        <KeyRotationParticipant as TxnParticipant<sever_index::NoExtension>>::replay(&mut self.0, r)
    }
    fn recover(&mut self) -> Result<(), sever_types::Error> {
        <KeyRotationParticipant as TxnParticipant<sever_index::NoExtension>>::recover(&mut self.0)
    }
    fn check_invariants(&self) -> Result<(), sever_types::Error> {
        <KeyRotationParticipant as TxnParticipant<sever_index::NoExtension>>::check_invariants(
            &self.0,
        )
    }
}

impl ProbedParticipant for Probe {
    fn digest(&self) -> Vec<u8> {
        self.0.durable().values().concat()
    }
}

#[test]
// oracle: C Part 2's frozen EP-7 contract suite (crash at every VFS operation, three policies; its
// drafts change nothing, so it labels no requirement: the rules are the erasure tests' labels)
fn p4_erasure_the_participant_passes_the_frozen_ep7_contract() {
    let make = |vfs: Arc<dyn sever_vfs::Vfs>| -> Box<dyn ProbedParticipant> {
        Box::new(Probe(KeyRotationParticipant::new(
            Arc::clone(&vfs),
            vfs,
            Arc::new(KeyRing::new()),
            64 * 1024,
        )))
    };
    assert_eq!(ep7_participant_contract(&make), Ok(()));
}

#[test]
// oracle: A §14.8 "the highest version wins; a drop is final": recovery writes back only a value that would change the state (G-43)
fn p4_erasure_a_value_is_newer_only_when_merging_it_would_change_the_state() {
    let d = dom();
    let mut s = Durable::default();
    let (b2, b3) = (
        Value::Block(d, 2, vec![2; 4_352]),
        Value::Block(d, 3, vec![3; 4_352]),
    );
    assert!(s.newer(&b2), "an absent block is news");
    s.merge(b2.clone());
    assert!(!s.newer(&b2), "the same version is not news");
    assert!(s.newer(&b3), "a higher version is news");
    assert!(
        !s.newer(&Value::Block(d, 1, vec![1; 4_352])),
        "a lower version is not news"
    );
    let e = |v: u64| Value::Envelopes(d, vec![([1; 64], v, [v as u8; 60])]);
    assert!(s.newer(&e(5)), "an absent envelope is news");
    s.merge(e(5));
    assert!(
        !s.newer(&e(5)) && !s.newer(&e(4)),
        "the same or a lower version is not news"
    );
    assert!(s.newer(&e(6)), "a higher version is news");
    let mixed = Value::Envelopes(d, vec![([1; 64], 5, [5; 60]), ([2; 64], 1, [1; 60])]);
    assert!(s.newer(&mixed), "one new entry among old ones is news");
    let cid = [0xC1; 16];
    assert!(s.newer(&Value::Drop(cid)), "a drop not yet seen is news");
    s.merge(Value::Drop(cid));
    assert!(!s.newer(&Value::Drop(cid)), "a drop seen is not news");
}

fn bare() -> (KeyRotationParticipant, Arc<KeyRing>) {
    let vfs: Arc<dyn sever_vfs::Vfs> = Arc::new(sever_vfs::SimVfs::new());
    let ring = Arc::new(KeyRing::new());
    (
        KeyRotationParticipant::new(Arc::clone(&vfs), vfs, Arc::clone(&ring), 64 * 1024),
        ring,
    )
}

type NoExt = sever_index::NoExtension;

#[test]
// oracle: A §14.6 BUCKET_BLOCK / EXTENSION payloads: a block record is a §14.8 block value without its kind byte; an extension record starts with participant ID 4
fn p4_erasure_parse_wal_reads_only_the_participants_own_records() {
    use sever_format::{RecordType, WalRecord};
    let d = dom();
    let rec = |ty, payload: Vec<u8>| WalRecord {
        ty,
        wal_seq: 1,
        txn_id: 1,
        payload,
    };
    let block = vec![0x42u8; 4_352];
    let value = block_value(&d, 3, &block);
    let got = parse_wal(&rec(RecordType::BucketBlock, value[1..].to_vec()));
    assert_eq!(got, Some(Value::Block(d, 3, block)));
    let mut ext = KEY_PARTICIPANT_ID.to_be_bytes().to_vec();
    ext.extend(drop_value(&[0xC1; 16]));
    assert_eq!(
        parse_wal(&rec(RecordType::Extension, ext.clone())),
        Some(Value::Drop([0xC1; 16]))
    );
    ext[1] ^= 1; // another participant's extension record
    assert_eq!(parse_wal(&rec(RecordType::Extension, ext)), None);
    assert_eq!(parse_wal(&rec(RecordType::Extension, vec![])), None);
}

#[test]
// oracle: A §14.8 "compaction starts at 1 MiB" as the participant's constant (COMPACT_MIN_BYTES = 2^20)
fn p4_erasure_compaction_starts_from_one_mebibyte() {
    assert_eq!(crate::participant::COMPACT_MIN_BYTES, 1_048_576);
}

#[test]
// oracle: A §15.3 an abort drops the stage; INV-14 every domain the ring knows has its key slot
fn p4_erasure_abort_discards_the_stage_and_the_invariant_names_a_ring_domain_without_a_slot() {
    let (mut p, ring) = bare();
    assert!(
        Arc::ptr_eq(p.ring(), &ring),
        "the participant shares the engine's ring"
    );
    assert!(format!("{p:?}").starts_with("KeyRotationParticipant("));
    ring.next_version(&dom(), None, false);
    assert!(!ring.stage_is_empty());
    <KeyRotationParticipant as TxnParticipant<NoExt>>::abort(&mut p);
    assert!(
        ring.stage_is_empty(),
        "abort discards what the transaction staged"
    );
    // A committed ring domain with no key slot breaks INV-14.
    ring.next_version(&dom(), None, false);
    ring.adopt();
    let r = <KeyRotationParticipant as TxnParticipant<NoExt>>::check_invariants(&p);
    assert!(r.is_err(), "INV-14: a domain without a key slot");
}
