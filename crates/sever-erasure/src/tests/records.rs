//! The participant's record bytes written out by hand from spec §14.6 and §14.8 (oracle A), its
//! merge rules, and Part 2's frozen EP-7 contract (oracle C).

use std::sync::Arc;

use sever_keys::Domain;
use sever_seal::KeyRing;
use sever_spec::spec;
use sever_txn::TxnParticipant;
use sever_txn::contract::{ProbedParticipant, ep7_participant_contract};

use crate::KeyRotationParticipant;
use crate::records::*;

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
