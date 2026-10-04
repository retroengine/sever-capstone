//! L1, L2, L6 and L7 tests for `sever-index` (Build §4.7), on the small fixture: the golden
//! partition built by the Python builder (d = 16, 4 frozen groups), spawn target 8 (gap G-10).
//! `// spec:` lines name the requirement IDs each test checks.

use proptest::prelude::*;
use sever_partition::PartitionArtefact;
use sever_types::{CollectionId, GroupId, RecordId};

use crate::blob::{BlobReject, Field, assert_state_equivalent, canonical_blob, parse_blob};
use crate::changeset::{GroupState, Outcome, Placement};
use crate::contract::{Ep1Violation, ep1_contract, ep2_contract};
use crate::ext::{GroupExtension, NoExtension};
use crate::index::{DeleteRequest, Index, IndexConfig, InsertRequest, has_room, spawn_id};
use crate::scramble::HmacSha512Scrambler;

type Ix = Index<NoExtension, HmacSha512Scrambler>;

fn artefact() -> PartitionArtefact {
    PartitionArtefact::parse(include_bytes!("../../../golden/p1_partition_small.svp")).unwrap()
}

fn rows(key: &str) -> Vec<Vec<f32>> {
    let doc: serde_json::Value =
        serde_json::from_str(include_str!("../../../golden/p1_fixture_vectors.json")).unwrap();
    doc[key]
        .as_array()
        .unwrap()
        .iter()
        .map(|h| {
            let bytes: Vec<u8> = (0..h.as_str().unwrap().len() / 2)
                .map(|i| u8::from_str_radix(&h.as_str().unwrap()[2 * i..2 * i + 2], 16).unwrap())
                .collect();
            bytes
                .chunks_exact(4)
                .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
                .collect()
        })
        .collect()
}

fn index_with(cfg: IndexConfig) -> Ix {
    Index::new(
        &artefact(),
        cfg,
        NoExtension,
        HmacSha512Scrambler::new(&[7; 64]),
        CollectionId::from_bytes([1; 16]),
    )
    .unwrap()
}

fn small() -> Ix {
    index_with(IndexConfig {
        spawning_enabled: true,
        spawn_target: 8,
    })
}

fn frozen_only() -> Ix {
    index_with(IndexConfig {
        spawning_enabled: false,
        spawn_target: 8,
    })
}

fn ins(ix: &mut Ix, id: &str, v: &[f32]) -> Result<Placement, sever_types::Error> {
    ix.insert(InsertRequest {
        record_id: id.into(),
        vector: v.to_vec(),
        credential: (),
    })
}

fn del(ix: &mut Ix, id: &str) -> Outcome {
    ix.delete(DeleteRequest {
        record_id: id.into(),
    })
    .unwrap()
}

/// Every group's blob plus the stats: a fingerprint of the whole observable state.
fn state_hash(ix: &Ix) -> Vec<Vec<u8>> {
    let mut out: Vec<Vec<u8>> = ix.group_ids().iter().map(|g| ix.blob(g).unwrap()).collect();
    out.push(format!("{:?}", ix.stats()).into_bytes());
    out
}

fn survivors_ok(ix: &Ix) {
    for g in ix.group_ids() {
        let got = ix.group_snapshot(&g).unwrap();
        let want = ix.survivors_snapshot(&g).unwrap();
        assert_eq!(assert_state_equivalent(&got, &want), Ok(()), "group {g}");
    }
    ix.check_invariants().unwrap();
}

// --- §5 exact deletion -------------------------------------------------------------------------

// spec: SR-5.3-1, SR-5.4-1 — deleting one record: its group equals the survivors-only group, every
// other group is untouched, N falls by one (E2E-1.1 in miniature).
#[test]
fn p1_index_delete_restores_survivors_state() {
    let refs = rows("ref");
    let mut ix = frozen_only();
    for (i, v) in refs.iter().enumerate().take(80) {
        ins(&mut ix, &format!("doc{i}"), v).unwrap();
    }
    let before = state_hash(&ix);
    let g = ix.location("doc17").unwrap();
    assert_eq!(del(&mut ix, "doc17"), Outcome::Deleted { from: g });
    survivors_ok(&ix);
    let after = state_hash(&ix);
    let changed: Vec<usize> = (0..before.len() - 1)
        .filter(|&i| before[i] != after[i])
        .collect();
    assert_eq!(changed.len(), 1, "exactly one group changes");
    assert_eq!(ix.stats().big_n, 79);
    assert_eq!(ix.location("doc17"), None);
}

// spec: SR-5.4-2 — a second delete is AlreadyAbsent and changes nothing (E2E-1.5).
#[test]
fn p1_index_delete_is_idempotent() {
    let refs = rows("ref");
    let mut ix = small();
    ins(&mut ix, "doc0", &refs[0]).unwrap();
    ins(&mut ix, "doc1", &refs[1]).unwrap();
    del(&mut ix, "doc0");
    let h = state_hash(&ix);
    assert_eq!(del(&mut ix, "doc0"), Outcome::AlreadyAbsent);
    assert_eq!(del(&mut ix, "never-there"), Outcome::AlreadyAbsent);
    assert_eq!(del(&mut ix, "007"), Outcome::AlreadyAbsent); // invalid IDs are never live
    assert_eq!(state_hash(&ix), h);
}

// spec: SR-5.4-3, SR-5.2-1 — an emptied group is exactly the initial state, and stays.
#[test]
fn p1_index_empty_group_is_initial_state_and_stays() {
    let refs = rows("ref");
    let mut ix = frozen_only();
    ins(&mut ix, "doc0", &refs[0]).unwrap();
    let g = ix.location("doc0").unwrap();
    del(&mut ix, "doc0");
    let snap = ix.group_snapshot(&g).unwrap();
    assert_eq!((snap.n, snap.s), (0, vec![0; 16]));
    assert!(ix.group_ids().contains(&g));
    assert_eq!(ix.stats().k, 4);
}

// spec: SR-5.5-3 — the equivalence helper catches each of the five fields on its own (phase P1
// must-fail).
#[test]
fn p1_index_equivalence_helper_catches_each_field() {
    let refs = rows("ref");
    let mut ix = frozen_only();
    for (i, v) in refs.iter().enumerate().take(10) {
        ins(&mut ix, &format!("doc{i}"), v).unwrap();
    }
    let g = ix.location("doc0").unwrap();
    let snap = ix.group_snapshot(&g).unwrap();
    let mut s = snap.clone();
    s.s[3] ^= 1;
    assert_eq!(assert_state_equivalent(&snap, &s), Err(Field::S));
    let mut s = snap.clone();
    s.n += 1;
    assert_eq!(assert_state_equivalent(&snap, &s), Err(Field::N));
    let mut s = snap.clone();
    *s.blob.last_mut().unwrap() ^= 1;
    assert_eq!(assert_state_equivalent(&snap, &s), Err(Field::Blob));
    let mut s = snap.clone();
    s.member_ids.push(RecordId::new("extra").unwrap());
    assert_eq!(assert_state_equivalent(&snap, &s), Err(Field::MemberIds));
    // Field 3 (C_S) is `()` under NoExtension; Part 3's suite corrupts it with real commitments.
    assert_eq!(assert_state_equivalent(&snap, &snap), Ok(()));
}

// spec: SR-5.5-1, SR-5.5-2 — the blob round-trips through the strict parser, and every rejection
// rule fires.
#[test]
fn p1_index_blob_parser_rejections() {
    let refs = rows("ref");
    let mut ix = frozen_only();
    for (i, v) in refs.iter().enumerate().take(6) {
        ins(&mut ix, &format!("doc{i}"), v).unwrap();
    }
    let g = ix.location("doc0").unwrap();
    let blob = ix.blob(&g).unwrap();
    let parsed = parse_blob(&blob, b"SEVERC", 0).unwrap();
    assert_eq!(parsed.n as usize, parsed.members.len());
    assert_eq!(parse_blob(&blob, b"SEVERG", 0), Err(BlobReject::Magic));
    let mut trailing = blob.clone();
    trailing.push(0);
    assert_eq!(
        parse_blob(&trailing, b"SEVERC", 0),
        Err(BlobReject::TrailingBytes)
    );
    let mut count = blob.clone();
    let at = 18 + 8 * 16 + 7;
    count[at] ^= 1;
    assert_eq!(
        parse_blob(&count, b"SEVERC", 0),
        Err(BlobReject::CountMismatch)
    );
    // Hand-built: unsorted, duplicate, empty.
    let mk = |ids: &[&[u8]]| {
        let mut b = b"SEVERC".to_vec();
        b.extend(1u16.to_be_bytes());
        b.extend(1u16.to_be_bytes()); // d = 1
        b.extend((ids.len() as u64).to_be_bytes());
        b.extend(0i64.to_be_bytes());
        b.extend((ids.len() as u64).to_be_bytes());
        for id in ids {
            b.extend((id.len() as u16).to_be_bytes());
            b.extend(*id);
            b.extend(0i64.to_be_bytes());
        }
        b
    };
    assert_eq!(
        parse_blob(&mk(&[b"b", b"a"]), b"SEVERC", 0),
        Err(BlobReject::Unsorted)
    );
    assert_eq!(
        parse_blob(&mk(&[b"a", b"a"]), b"SEVERC", 0),
        Err(BlobReject::Unsorted)
    );
    assert_eq!(
        parse_blob(&mk(&[b""]), b"SEVERC", 0),
        Err(BlobReject::EmptyId)
    );
    assert!(parse_blob(&mk(&[b"a", b"b"]), b"SEVERC", 0).is_ok());
}

// spec: SR-5.5-1 — golden vector 8, core form, written by the reference model.
#[test]
fn p1_index_golden_core_blob() {
    let g: serde_json::Value =
        serde_json::from_str(include_str!("../../../golden/p1_core_blob.json")).unwrap();
    let d = g["d"].as_u64().unwrap() as usize;
    let members: Vec<(RecordId, sever_quant::QVec)> = g["members"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| {
            let xs: Vec<i32> = v
                .as_array()
                .unwrap()
                .iter()
                .map(|n| n.as_i64().unwrap() as i32)
                .collect();
            (
                RecordId::new(k.as_str()).unwrap(),
                sever_quant::QVec::from_stored(xs, d).unwrap(),
            )
        })
        .collect();
    let mut state = GroupState::<NoExtension>::empty(d);
    for (_, x) in &members {
        for (a, &v) in state.s.iter_mut().zip(x.as_slice()) {
            *a += i64::from(v);
        }
        state.n += 1;
    }
    let pairs: Vec<_> = members.iter().map(|(id, x)| (id, x)).collect();
    let hex: String = canonical_blob(&NoExtension, d, &state, &pairs)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    assert_eq!(hex, g["blob_hex"].as_str().unwrap());
}

// --- §3.2 and §15.1 order of checks --------------------------------------------------------------

// spec: SR-3.2-3, SR-3.2-4, SR-4.1-0 — duplicate live IDs, retries, re-insert after delete, and
// the §15.1 order (vector checks before ID checks).
#[test]
fn p1_index_insert_validation_order_and_duplicates() {
    let refs = rows("ref");
    let mut ix = small();
    ins(&mut ix, "doc0", &refs[0]).unwrap();
    assert_eq!(
        ins(&mut ix, "doc0", &refs[0]),
        Err(sever_types::Error::DuplicateRecord {
            same_commitment: true
        })
    );
    assert_eq!(
        ins(&mut ix, "doc0", &refs[1]),
        Err(sever_types::Error::DuplicateRecord {
            same_commitment: false
        })
    );
    assert_eq!(
        ins(&mut ix, "1", &[0.0; 16]),
        Err(sever_types::Error::NotNormalised)
    );
    assert_eq!(
        ins(&mut ix, "1", &[0.0; 8]),
        Err(sever_types::Error::WrongDimension)
    );
    assert!(matches!(
        ins(&mut ix, "1", &refs[2]),
        Err(sever_types::Error::InvalidRecordId(_))
    ));
    del(&mut ix, "doc0");
    assert!(ins(&mut ix, "doc0", &refs[1]).is_ok()); // §3.2: re-insert after deletion
    ix.check_invariants().unwrap();
}

// --- §7 routing, holding, flush, spillover --------------------------------------------------------

// spec: SR-7.4-1, SR-7.4-2, SR-7.5-1, SR-7.5-2, SR-7.6-1 — the holding area flushes at exactly
// the target into exactly one group (E2E-1.2 in miniature).
#[test]
fn p1_index_holding_flushes_exactly_at_target() {
    let live = rows("live");
    let mut ix = small();
    for (i, v) in live.iter().enumerate().take(7) {
        assert_eq!(ins(&mut ix, &format!("live{i}"), v), Ok(Placement::Holding));
    }
    let st = ix.stats();
    assert_eq!((st.holding, st.big_n, st.k, st.spawned), (7, 0, 4, 0));
    let ids: Vec<RecordId> = (0..8)
        .map(|i| RecordId::new(format!("live{i}")).unwrap())
        .collect();
    let gid = spawn_id(ids.iter());
    assert_eq!(ins(&mut ix, "live7", &live[7]), Ok(Placement::Spawned(gid)));
    let st = ix.stats();
    assert_eq!((st.holding, st.big_n, st.k, st.spawned), (0, 8, 5, 1));
    let snap = ix.group_snapshot(&gid).unwrap();
    assert_eq!(snap.n, 8);
    let centroid = ix
        .search_groups()
        .find(|g| g.id == gid)
        .unwrap()
        .centroid
        .to_vec();
    let want: Vec<f64> = snap
        .s
        .iter()
        .map(|&v| (v as f64 / 16_777_216.0) / 8.0)
        .collect();
    assert_eq!(centroid, want);
    survivors_ok(&ix);
}

// spec: SR-7.4-1, SR-7.4-3 — holding records are deletable at once, never searchable, not in N.
#[test]
fn p1_index_holding_record_deletable_not_searchable() {
    let live = rows("live");
    let mut ix = small();
    ins(&mut ix, "live0", &live[0]).unwrap();
    assert!(
        ix.search_groups()
            .all(|g| g.ids.iter().all(|r| r.as_str() != "live0"))
    );
    assert_eq!(
        del(&mut ix, "live0"),
        Outcome::Deleted {
            from: GroupId::Holding
        }
    );
    assert_eq!(ix.stats().holding, 0);
    assert_eq!(ix.stats().big_n, 0);
}

// spec: SR-7.3-2 — spillover is checked before the holding area (SB-8).
#[test]
fn p1_index_spillover_before_holding() {
    let (refs, live) = (rows("ref"), rows("live"));
    let mut ix = small();
    for (i, v) in live.iter().enumerate().take(8) {
        ins(&mut ix, &format!("live{i}"), v).unwrap();
    }
    for (i, v) in refs.iter().enumerate().take(20) {
        ins(&mut ix, &format!("doc{i}"), v).unwrap();
    }
    let gid = *ix.group_ids().last().unwrap();
    assert_eq!(ins(&mut ix, "live8", &live[8]), Ok(Placement::Spawned(gid)));
    survivors_ok(&ix);
}

// spec: SR-7.7-1, SR-7.7-2 — routing is pure and does not depend on group creation order (SB-7).
#[test]
fn p1_index_routing_ignores_creation_order() {
    let (refs, live) = (rows("ref"), rows("live"));
    let (mut a, mut b) = (small(), small());
    for i in (0..8).chain(8..16) {
        ins(&mut a, &format!("live{i}"), &live[i]).unwrap();
    }
    for i in (8..16).chain(0..8) {
        ins(&mut b, &format!("live{i}"), &live[i]).unwrap();
    }
    for (i, v) in refs.iter().enumerate().take(40) {
        ins(&mut a, &format!("doc{i}"), v).unwrap();
        ins(&mut b, &format!("doc{i}"), v).unwrap();
    }
    let mut ga = a.group_ids();
    let mut gb = b.group_ids();
    assert_ne!(ga, gb, "creation order differs");
    ga.sort();
    gb.sort();
    assert_eq!(ga, gb);
    for v in live.iter().skip(16) {
        let x = sever_quant::quantise(v, 16).unwrap();
        assert_eq!(a.route(&x).unwrap(), a.route(&x).unwrap());
        assert_eq!(a.route(&x).unwrap(), b.route(&x).unwrap());
    }
}

// spec: SR-5.6-1 — the room test at 2kn = 3N − 1, 3N, 3N + 1.
#[test]
fn p1_index_room_test_boundaries() {
    assert!(has_room(1, 1, 1)); // 2 = 3 − 1
    assert!(!has_room(5, 3, 10)); // 30 = 30
    assert!(!has_room(1, 2, 1)); // 4 = 3 + 1
    assert!(!has_room(0, 4, 0)); // N = 0: no room anywhere
    assert!(!has_room(u64::MAX / 2, u64::MAX / 2, u64::MAX)); // huge values: no overflow, no room
}

// spec: SR-7.5-1 — golden vector 7, written by the reference model.
#[test]
fn p1_index_golden_spawn_id() {
    let g: serde_json::Value =
        serde_json::from_str(include_str!("../../../golden/p1_spawn_id.json")).unwrap();
    let ids: Vec<RecordId> = g["cohort"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| RecordId::new(v.as_str().unwrap()).unwrap())
        .collect();
    assert_eq!(
        spawn_id(ids.iter()).as_text(),
        g["spawn_id"].as_str().unwrap()
    );
    assert_eq!(spawn_id(ids.iter().rev()), spawn_id(ids.iter())); // order-free
}

// --- delete_user, locator, mirror -----------------------------------------------------------------

// spec: SR-5.4-2, SR-3.5 — delete_user across groups, one unit; a repeated ID is AlreadyAbsent the
// second time and subtracts nothing (SB-3; E2E-1.4 in miniature).
#[test]
fn p1_index_delete_user_across_groups_with_repeats() {
    let (refs, live) = (rows("ref"), rows("live"));
    let mut ix = small();
    for (i, v) in refs.iter().enumerate().take(40) {
        ins(&mut ix, &format!("doc{i}"), v).unwrap();
    }
    for (i, v) in live.iter().enumerate().take(11) {
        ins(&mut ix, &format!("live{i}"), v).unwrap();
    }
    let cohort = ["doc3", "doc9", "live2", "live9", "doc3", "missing", "doc21"];
    let groups: std::collections::BTreeSet<_> =
        cohort.iter().filter_map(|r| ix.location(r)).collect();
    assert!(
        groups.len() >= 2,
        "a frozen and a spawned group (live8–10 spill over)"
    );
    let out = ix
        .delete_many(
            cohort
                .iter()
                .map(|r| DeleteRequest {
                    record_id: (*r).into(),
                })
                .collect(),
        )
        .unwrap();
    assert!(matches!(out[0], Outcome::Deleted { .. }));
    assert_eq!(out[4], Outcome::AlreadyAbsent);
    assert_eq!(out[5], Outcome::AlreadyAbsent);
    survivors_ok(&ix);
}

// spec: SR-5.4-1 (§14.4 swap-with-last) — after a slot move, the moved record is still found and
// deletable (SB-4).
#[test]
fn p1_index_locator_follows_moved_slot() {
    let refs = rows("ref");
    let mut ix = frozen_only();
    for (i, v) in refs.iter().enumerate().take(60) {
        ins(&mut ix, &format!("doc{i}"), v).unwrap();
    }
    let g = ix.location("doc0").unwrap();
    // Delete the group's first member, so its last member moves into slot 0; then delete every
    // other member by name: each must still be found.
    let members: Vec<String> = (0..60)
        .map(|i| format!("doc{i}"))
        .filter(|r| ix.location(r) == Some(g))
        .collect();
    for r in &members {
        assert_eq!(del(&mut ix, r), Outcome::Deleted { from: g }, "{r}");
        ix.check_invariants().unwrap();
    }
    assert_eq!(ix.group_len(&g), Some(0));
}

// spec: SR-8.1-4 (INV-9) — a deleted record leaves the search mirror at once (SB-5).
#[test]
fn p1_index_deleted_record_leaves_the_mirror() {
    let refs = rows("ref");
    let mut ix = frozen_only();
    for (i, v) in refs.iter().enumerate().take(30) {
        ins(&mut ix, &format!("doc{i}"), v).unwrap();
    }
    for r in ["doc0", "doc7", "doc29"] {
        del(&mut ix, r);
        for g in ix.search_groups() {
            assert!(g.ids.iter().all(|id| id.as_str() != r));
            assert_eq!(g.rows.len(), g.ids.len() * 16);
        }
    }
    ix.check_invariants().unwrap();
}

// spec: SR-5.5-4, SR-5.3-1 — plan never mutates: the state is identical before and after any plan.
#[test]
fn p1_index_plan_never_mutates() {
    let (refs, live) = (rows("ref"), rows("live"));
    let mut ix = small();
    for (i, v) in refs.iter().enumerate().take(20) {
        ins(&mut ix, &format!("doc{i}"), v).unwrap();
    }
    for (i, v) in live.iter().enumerate().take(7) {
        ins(&mut ix, &format!("live{i}"), v).unwrap();
    }
    let h = state_hash(&ix);
    let _ = ix.plan_insert(InsertRequest {
        record_id: "live7".into(),
        vector: live[7].clone(),
        credential: (),
    });
    let _ = ix.plan_delete_many(vec![DeleteRequest {
        record_id: "doc3".into(),
    }]);
    assert_eq!(state_hash(&ix), h);
}

// --- L6 metamorphic -----------------------------------------------------------------------------------

// The whole-index twin (Build §4.7 L6): frozen-only, insert all then delete D ≡ never insert D.
#[test]
fn p1_index_whole_index_twin() {
    let refs = rows("ref");
    let mut a = frozen_only();
    let mut b = frozen_only();
    let dropped = |i: usize| i % 3 == 0;
    for (i, v) in refs.iter().enumerate() {
        ins(&mut a, &format!("doc{i}"), v).unwrap();
        if !dropped(i) {
            ins(&mut b, &format!("doc{i}"), v).unwrap();
        }
    }
    let reqs = (0..refs.len())
        .filter(|&i| dropped(i))
        .map(|i| DeleteRequest {
            record_id: format!("doc{i}"),
        });
    a.delete_many(reqs.collect()).unwrap();
    assert_eq!(state_hash(&a), state_hash(&b));
}

// Delete then re-insert equals never deleting (Build §4.7 L6).
#[test]
fn p1_index_delete_then_reinsert_is_identity() {
    let refs = rows("ref");
    let mut a = frozen_only();
    for (i, v) in refs.iter().enumerate().take(50) {
        ins(&mut a, &format!("doc{i}"), v).unwrap();
    }
    let h = state_hash(&a);
    del(&mut a, "doc11");
    ins(&mut a, "doc11", &refs[11]).unwrap();
    assert_eq!(state_hash(&a), h);
}

// --- L7 contracts -------------------------------------------------------------------------------------

/// Deliberately wrong extension: its `remove` is not the inverse of `add`.
#[derive(Clone)]
struct Leaky;
impl GroupExtension for Leaky {
    type GroupPublic = u64;
    type GroupSecret = ();
    type RecordSecret = ();
    type Credential = ();
    const BLOB_MAGIC: [u8; 6] = *b"LEAKY!";
    fn admit(&self, _: &sever_quant::QVec, _: ()) -> Result<(), sever_types::Error> {
        Ok(())
    }
    fn add(&self, p: &mut u64, _: &mut (), _: &sever_quant::QVec, _: &()) {
        *p += 1;
    }
    fn remove(&self, _: &mut u64, _: &mut (), _: &sever_quant::QVec, _: &()) {}
    fn check_removal(&self, _: &sever_quant::QVec, _: &()) -> Result<(), sever_types::Error> {
        Ok(())
    }
    fn blob_region(&self, p: &u64, _: &(), out: &mut Vec<u8>) {
        out.extend(p.to_be_bytes());
    }
    fn check_group(&self, _: &[i64], _: &u64, _: &()) -> Result<(), sever_types::Error> {
        Ok(())
    }
    fn same_commitment(
        &self,
        _: &sever_quant::QVec,
        _: &(),
        _: &sever_quant::QVec,
        _: &(),
    ) -> bool {
        false
    }
}

// Build §3.4, P1-T13 — EP-1 and EP-2 contracts pass for the defaults and fail for a wrong one.
#[test]
fn p1_index_contracts() {
    let refs = rows("ref");
    let xs: Vec<(sever_quant::QVec, ())> = refs
        .iter()
        .take(10)
        .map(|v| (sever_quant::quantise(v, 16).unwrap(), ()))
        .collect();
    assert_eq!(ep1_contract(&NoExtension, &xs), Ok(()));
    assert_eq!(
        ep1_contract(&Leaky, &xs),
        Err(Ep1Violation::RemoveIsNotInverse)
    );
    assert_eq!(ep2_contract(&HmacSha512Scrambler::new(&[9; 64])), Ok(()));
}

// spec: SR-9.7-1 — the scrambler against Python's hmac (golden).
#[test]
fn p1_index_scrambler_matches_python_hmac() {
    use crate::scramble::IdScrambler;
    let g: serde_json::Value =
        serde_json::from_str(include_str!("../../../golden/p1_scramble.json")).unwrap();
    let key: Vec<u8> = (0..64).collect();
    let s = HmacSha512Scrambler::new(&key.try_into().unwrap());
    let cid = CollectionId::from_bytes([0xaa; 16]);
    for row in g["rows"].as_array().unwrap() {
        let id = RecordId::new(row["record_id"].as_str().unwrap()).unwrap();
        let hex: String = s
            .scramble(&cid, &id)
            .as_bytes()
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        assert_eq!(hex, row["scrambled_id"].as_str().unwrap());
    }
}

// --- L2 properties ------------------------------------------------------------------------------------

#[derive(Clone, Debug)]
enum Op {
    InsRef(usize),
    InsLive(usize),
    Del(usize),
    DelUser(Vec<usize>),
}

fn op() -> impl Strategy<Value = Op> {
    prop_oneof![
        (0usize..60).prop_map(Op::InsRef),
        (0usize..60).prop_map(Op::InsLive),
        (0usize..60).prop_map(Op::Del),
        proptest::collection::vec(0usize..60, 1..6).prop_map(Op::DelUser),
    ]
}

proptest! {
    #![proptest_config(ProptestConfig { cases: 48, ..ProptestConfig::default() })]

    // P1-T1: after any sequence of operations, every group passes the survivors check on every
    // core field, and every invariant holds.
    #[test]
    fn p1_index_prop_survivors_check_after_any_sequence(ops in proptest::collection::vec(op(), 0..120)) {
        let (refs, live) = (rows("ref"), rows("live"));
        let mut ix = small();
        for o in ops {
            match o {
                Op::InsRef(i) => { let _ = ins(&mut ix, &format!("r{i}"), &refs[i]); }
                Op::InsLive(i) => { let _ = ins(&mut ix, &format!("l{i}"), &live[i]); }
                Op::Del(i) => { del(&mut ix, &format!("r{i}")); del(&mut ix, &format!("l{i}")); }
                Op::DelUser(is) => {
                    let reqs = is.iter().flat_map(|i| [format!("r{i}"), format!("l{i}")])
                        .map(|record_id| DeleteRequest { record_id }).collect();
                    ix.delete_many(reqs).unwrap();
                }
            }
        }
        survivors_ok(&ix);
    }

    // P1-T3: any insertion order of the same members gives identical blobs (frozen-only, so the
    // index shape cannot differ).
    #[test]
    fn p1_index_prop_insertion_order_independent(perm in Just((0..40usize).collect::<Vec<_>>()).prop_shuffle()) {
        let refs = rows("ref");
        let (mut a, mut b) = (frozen_only(), frozen_only());
        for (i, v) in refs.iter().enumerate().take(40) {
            ins(&mut a, &format!("doc{i}"), v).unwrap();
        }
        for &i in &perm {
            ins(&mut b, &format!("doc{i}"), &refs[i]).unwrap();
        }
        prop_assert_eq!(state_hash(&a), state_hash(&b));
    }
}
