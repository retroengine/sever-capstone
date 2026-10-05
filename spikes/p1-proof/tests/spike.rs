//! The spike's gate: EP-1 contract, five-field exactness with commitments, EP-3 rotation reader.

use std::collections::BTreeSet;

use sever_index::GroupExtension;
use sever_index::contract::ep1_contract;
use sever_index::{
    DeleteRequest, HmacSha512Scrambler, Index, IndexConfig, InsertRequest, assert_state_equivalent,
};
use sever_partition::PartitionArtefact;
use sever_spike_p1_proof::{CommitmentExtension, groups_to_rotate};
use sever_types::{CollectionId, GroupId};

fn rows(key: &str) -> Vec<Vec<f32>> {
    let doc: serde_json::Value =
        serde_json::from_str(include_str!("../../../golden/p1_fixture_vectors.json")).unwrap();
    doc[key]
        .as_array()
        .unwrap()
        .iter()
        .map(|h| {
            let s = h.as_str().unwrap();
            (0..s.len() / 8)
                .map(|j| {
                    let b: Vec<u8> = (0..4)
                        .map(|k| {
                            u8::from_str_radix(&s[8 * j + 2 * k..8 * j + 2 * k + 2], 16).unwrap()
                        })
                        .collect();
                    f32::from_le_bytes([b[0], b[1], b[2], b[3]])
                })
                .collect()
        })
        .collect()
}

type Ix = Index<CommitmentExtension, HmacSha512Scrambler>;

fn index() -> Ix {
    let art =
        PartitionArtefact::parse(include_bytes!("../../../golden/p1_partition_small.svp")).unwrap();
    Index::new(
        &art,
        IndexConfig {
            spawning_enabled: true,
            spawn_target: 8,
        },
        CommitmentExtension::new(16),
        HmacSha512Scrambler::new(&[9; 64]),
        CollectionId::from_bytes([3; 16]),
    )
    .unwrap()
}

#[test]
fn spike_ep1_contract_passes_with_pedersen_commitments() {
    let ext = CommitmentExtension::new(16);
    let records: Vec<_> = rows("ref")
        .iter()
        .chain(rows("live").iter())
        .take(60)
        .map(|v| {
            let x = sever_quant::quantise(v, 16).unwrap();
            let rec = ext.admit(&x, ext.credential(&x)).unwrap();
            (x, rec)
        })
        .collect();
    assert_eq!(ep1_contract(&ext, &records), Ok(()));
}

#[test]
fn spike_admission_rejects_a_wrong_commitment() {
    let ext = CommitmentExtension::new(16);
    let x = sever_quant::quantise(&rows("ref")[0], 16).unwrap();
    let y = sever_quant::quantise(&rows("ref")[1], 16).unwrap();
    let c = ext.credential(&y);
    assert!(ext.admit(&x, c).is_err());
}

#[test]
fn spike_five_field_exactness_holds_with_commitments() {
    let ext = CommitmentExtension::new(16);
    let mut ix = index();
    let all: Vec<Vec<f32>> = rows("ref").into_iter().chain(rows("live")).collect();
    for (i, v) in all.iter().enumerate() {
        let x = sever_quant::quantise(v, 16).unwrap();
        ix.insert(InsertRequest {
            record_id: format!("r{i}"),
            vector: v.clone(),
            credential: ext.credential(&x),
        })
        .unwrap();
    }
    for i in (0..all.len()).step_by(3) {
        ix.delete(DeleteRequest {
            record_id: format!("r{i}"),
        })
        .unwrap();
    }
    ix.check_invariants().unwrap(); // includes the extension's INV-3
    for g in ix.group_ids() {
        let got = ix.group_snapshot(&g).unwrap();
        let want = ix.survivors_snapshot(&g).unwrap();
        assert_eq!(
            assert_state_equivalent(&got, &want),
            Ok(()),
            "group {}",
            g.as_text()
        );
    }
}

#[test]
fn spike_ep3_rotation_reader_finds_exactly_the_touched_groups() {
    let ext = CommitmentExtension::new(16);
    let mut ix = index();
    let all: Vec<Vec<f32>> = rows("ref").into_iter().chain(rows("live")).collect();
    for (i, v) in all.iter().enumerate() {
        let x = sever_quant::quantise(v, 16).unwrap();
        let req = InsertRequest {
            record_id: format!("r{i}"),
            vector: v.clone(),
            credential: ext.credential(&x),
        };
        let cs = ix.plan_insert(req).unwrap();
        let rot = groups_to_rotate(&cs);
        // An insert rotates the group it lands in; a flush also the new group (holding has no key).
        assert!(rot.len() <= 1 || !cs.created.is_empty());
        ix.apply(cs);
    }
    let cohort: Vec<String> = [1usize, 5, 130, 140, 141, 200]
        .iter()
        .map(|i| format!("r{i}"))
        .collect();
    let expect: BTreeSet<GroupId> = cohort
        .iter()
        .filter_map(|id| ix.location(id))
        .filter(|g| *g != GroupId::Holding)
        .collect();
    let cs = ix
        .plan_delete_many(
            cohort
                .iter()
                .map(|r| DeleteRequest {
                    record_id: r.clone(),
                })
                .collect(),
        )
        .unwrap();
    assert_eq!(groups_to_rotate(&cs), expect);
    ix.apply(cs);
    // A delete of absent records rotates nothing.
    let cs = ix
        .plan_delete(DeleteRequest {
            record_id: "r1".into(),
        })
        .unwrap();
    assert!(groups_to_rotate(&cs).is_empty());
}
