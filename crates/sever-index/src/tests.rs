//! L1, L2, L6 and L7 tests for `sever-index` (Build §4.7), on the small fixture: the golden
//! partition built by the Python builder (d = 16, 4 frozen groups), spawn target 8 (gap G-10).
//! `#[spec(...)]` attributes name the requirement IDs each test checks (Build §2.2).

use proptest::prelude::*;
use sever_partition::PartitionArtefact;
use sever_types::{CollectionId, GroupId, RecordId};

use crate::blob::{BlobReject, Field, assert_state_equivalent, canonical_blob, parse_blob};
use crate::changeset::{GroupState, Outcome, Placement};
use crate::contract::{Ep1Violation, ep1_contract, ep2_contract};
use crate::ext::{GroupExtension, NoExtension};
use crate::index::{DeleteRequest, Index, IndexConfig, InsertRequest, has_room, spawn_id};
use crate::scramble::HmacSha512Scrambler;
use sever_spec::spec;

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

// deleting one record: its group equals the survivors-only group, every
// other group is untouched, N falls by one (E2E-1.1 in miniature).
#[spec("SR-5.3-1", "SR-5.4-1")]
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

// a second delete is AlreadyAbsent and changes nothing (E2E-1.5).
#[spec("SR-5.4-2")]
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

// an emptied group is exactly the initial state, and stays.
#[spec("SR-5.4-3", "SR-5.2-1")]
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

// the equivalence helper catches each of the five fields on its own (phase P1
// must-fail).
#[spec("SR-5.5-3")]
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

// the blob round-trips through the strict parser, and every rejection
// rule fires.
#[spec("SR-5.5-1", "SR-5.5-2")]
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

// golden vector 8, core form, written by the reference model.
#[spec("SR-5.5-1")]
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

// duplicate live IDs, retries, re-insert after delete, and
// the §15.1 order (vector checks before ID checks).
#[spec("SR-3.2-3", "SR-3.2-4", "SR-4.1-0")]
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

// §7.6: every change set carries the counters the index holds after it is applied (EP-3: the
// Part 2 log replays them), through holding inserts, a flush, group inserts and deletions.
#[spec("SR-7.6-1")]
#[test]
fn p1_index_change_set_counters_match_the_applied_state() {
    let live = rows("live");
    let mut ix = small();
    let check = |ix: &mut Ix, cs: crate::changeset::ChangeSet<NoExtension>| {
        let claimed = cs.counters_after;
        ix.apply(cs);
        let st = ix.stats();
        assert_eq!((claimed.big_n, claimed.k), (st.big_n, st.k));
    };
    for (i, v) in live.iter().enumerate().take(10) {
        let cs = ix
            .plan_insert(InsertRequest {
                record_id: format!("live{i}"),
                vector: v.clone(),
                credential: (),
            })
            .unwrap();
        check(&mut ix, cs);
    }
    assert_eq!(ix.stats().k, 5); // the flush happened
    for i in [0, 9] {
        let cs = ix
            .plan_delete(DeleteRequest {
                record_id: format!("live{i}"),
            })
            .unwrap();
        check(&mut ix, cs);
    }
}

// the holding area flushes at exactly
// the target into exactly one group (E2E-1.2 in miniature).
#[spec("SR-7.4-1", "SR-7.4-2", "SR-7.5-1", "SR-7.5-2", "SR-7.6-1", "SR-2.1-1")]
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

// holding records are deletable at once, never searchable, not in N.
#[spec("SR-7.4-1", "SR-7.4-3")]
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

// spillover is checked before the holding area (SB-8).
#[spec("SR-7.3-2")]
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

// routing is pure and does not depend on group creation order (SB-7).
#[spec("SR-7.7-1", "SR-7.7-2", "SR-7-1")]
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

// the room test at 2kn = 3N − 1, 3N, 3N + 1.
#[spec("SR-5.6-1")]
#[test]
fn p1_index_room_test_boundaries() {
    assert!(has_room(1, 1, 1)); // 2 = 3 − 1
    assert!(!has_room(5, 3, 10)); // 30 = 30
    assert!(!has_room(1, 2, 1)); // 4 = 3 + 1
    assert!(!has_room(0, 4, 0)); // N = 0: no room anywhere
    assert!(!has_room(u64::MAX / 2, u64::MAX / 2, u64::MAX)); // huge values: no overflow, no room
}

// golden vector 7, written by the reference model.
#[spec("SR-7.5-1")]
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

// SR-3.5 — delete_user across groups, one unit; a repeated ID is AlreadyAbsent the
// second time and subtracts nothing (SB-3; E2E-1.4 in miniature).
#[spec("SR-5.4-2", "SR-3.5-1")]
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

// SR-5.4-1 (§14.4 swap-with-last) — after a slot move, the moved record is still found and
// deletable (SB-4).
#[spec("SR-5.4-1")]
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

// SR-8.1-4 (INV-9) — a deleted record leaves the search mirror at once (SB-5).
#[spec("SR-8.1-4")]
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

// plan never mutates: the state is identical before and after any plan.
#[spec("SR-5.5-4", "SR-5.3-1")]
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

// the scrambler against Python's hmac (golden).
#[spec("SR-9.7-1")]
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

// §7.1: the nearest frozen centroid by a sequential float64 sum, recomputed here from the artefact;
// label 2 is made an exact copy of label 1, so every vector nearest to them ties and must go to 1.
#[spec("SR-7.1-1")]
#[test]
fn p1_index_nearest_frozen_group_ties_to_smaller_label() {
    let mut art = artefact();
    let d = art.d;
    let c1 = art.centroids[d..2 * d].to_vec();
    art.centroids[2 * d..3 * d].copy_from_slice(&c1);
    let ix = Index::new(
        &art,
        IndexConfig {
            spawning_enabled: false,
            spawn_target: 8,
        },
        NoExtension,
        HmacSha512Scrambler::new(&[7; 64]),
        CollectionId::from_bytes([1; 16]),
    )
    .unwrap();
    let mut ties = 0;
    for v in rows("ref").iter().chain(rows("live").iter()) {
        let x = sever_quant::quantise(v, d).unwrap();
        let xhat = x.dequantise_f64();
        let dist = |j: usize| {
            let mut s = 0.0f64;
            for (i, xi) in xhat.iter().enumerate() {
                let t = xi - art.centroids[j * d + i];
                s += t * t;
            }
            s
        };
        let mut best = 0;
        for j in 1..art.k_frozen {
            if dist(j) < dist(best) {
                best = j;
            }
        }
        ties += usize::from(best == 1);
        assert_eq!(
            ix.route(&x).unwrap().0,
            GroupId::frozen(best as u16).unwrap()
        );
    }
    assert!(ties > 0, "no vector was nearest to the duplicated centroid");
}

// §5.6 hard cap at the three boundary points (Build §2.2): 10^6 − 1 and 10^6 members are accepted;
// the insert that would make 10^6 + 1 is GroupCapacityExceeded and changes nothing.
#[spec("SR-5.6-2", "SR-4.4-1")]
#[test]
#[ignore = "10^6 inserts (about 300 MB): Full tier, run with --release --ignored"]
fn p1_index_hard_cap_at_one_million() {
    let mut ix = frozen_only();
    let v = &rows("ref")[0];
    let cap = sever_types::constants::MAX_GROUP_MEMBERS;
    let (g, _) = ix.route(&sever_quant::quantise(v, 16).unwrap()).unwrap();
    for i in 0..cap {
        ins(&mut ix, &format!("r{i}"), v).unwrap();
    }
    assert_eq!(ix.group_len(&g), Some(cap as usize));
    let before = ix.stats();
    assert_eq!(
        ins(&mut ix, "one-too-many", v),
        Err(sever_types::Error::GroupCapacityExceeded)
    );
    assert_eq!(ix.stats(), before);
    assert_eq!(ix.location("one-too-many"), None);
    // One deletion makes room again.
    assert!(matches!(del(&mut ix, "r0"), Outcome::Deleted { .. }));
    ins(&mut ix, "one-too-many", v).unwrap();
    assert_eq!(ix.group_len(&g), Some(cap as usize));
    ix.check_invariants().unwrap();
}

// --- rules and defences found untested by branch coverage (P1-T10) --------------------------

use crate::changeset::{ChangeSet, Counters, CreatedGroup, GroupChange, LocatorOp, SlotOp};
use crate::scramble::IdScrambler;

/// An empty change set on `ix`'s counters: the base for forged ones.
fn forged(ix: &Ix) -> ChangeSet<NoExtension> {
    let c = Counters {
        big_n: ix.stats().big_n,
        k: ix.k(),
    };
    ChangeSet {
        created: vec![],
        groups: vec![],
        slots: vec![],
        locator: vec![],
        counters_before: c,
        counters_after: c,
        departures: vec![],
        arrivals: vec![],
        outcomes: vec![],
    }
}

fn state_of(ix: &Ix, g: &GroupId) -> GroupState<NoExtension> {
    let snap = ix.group_snapshot(g).unwrap();
    let mut st = GroupState::<NoExtension>::empty(16);
    st.s = snap.s;
    st.n = snap.n;
    st
}

/// Sets a spawned group's `n` without members: enough for routing, which reads only `n` (§5.6).
fn set_n(ix: &mut Ix, g: GroupId, n: u64) {
    let mut cs = forged(ix);
    let before = state_of(ix, &g);
    let mut after = before.clone();
    after.n = n;
    cs.groups.push(GroupChange {
        group: g,
        before,
        after,
    });
    ix.apply(cs);
}

fn create_spawned(ix: &mut Ix, text: &str, centroid: Vec<f64>) -> GroupId {
    let id = GroupId::parse(text).unwrap();
    let mut cs = forged(ix);
    cs.created.push(CreatedGroup { id, centroid });
    ix.apply(cs);
    id
}

// §7.4: a spawn target of 0 could never flush; the index refuses it.
#[test]
fn p1_index_spawn_target_zero_is_refused() {
    let r = Index::new(
        &artefact(),
        IndexConfig {
            spawning_enabled: true,
            spawn_target: 0,
        },
        NoExtension,
        HmacSha512Scrambler::new(&[7; 64]),
        CollectionId::from_bytes([1; 16]),
    );
    assert!(matches!(
        r,
        Err(sever_types::Error::IntegrityViolation { .. })
    ));
}

// §7.3: out of distribution, the nearest spawned group *with room*; equal distances go to the
// smaller group-ID bytes; no group with room means the holding area.
#[spec("SR-7.3-1", "SR-5.6-1")]
#[test]
fn p1_index_spillover_skips_full_groups_and_ties_to_smaller_id() {
    let mut ix = small();
    for (i, v) in rows("ref").iter().enumerate().take(20) {
        ins(&mut ix, &format!("doc{i}"), v).unwrap();
    }
    let x = sever_quant::quantise(&rows("live")[0], 16).unwrap();
    assert_eq!(ix.route(&x).unwrap(), (GroupId::Holding, true));
    let mu = x.dequantise_f64();
    let b = create_spawned(&mut ix, "spawn-0000000000000002", mu.clone());
    let a = create_spawned(&mut ix, "spawn-0000000000000001", mu);
    assert_eq!(ix.route(&x).unwrap(), (a, true), "tie → smaller ID bytes");
    set_n(&mut ix, a, 1_000);
    assert_eq!(ix.route(&x).unwrap(), (b, true), "a has no room");
    set_n(&mut ix, b, 1_000);
    assert_eq!(
        ix.route(&x).unwrap(),
        (GroupId::Holding, true),
        "no room anywhere"
    );
}

// §7.5: a flush whose spawn ID already exists fails with IntegrityViolation and changes nothing.
#[spec("SR-7.5-1")]
#[test]
fn p1_index_spawn_id_collision_fails_the_flush() {
    let mut ix = small();
    let live = rows("live");
    let ids: Vec<String> = (0..8).map(|i| format!("live{i}")).collect();
    for (id, v) in ids.iter().zip(&live).take(7) {
        assert_eq!(ins(&mut ix, id, v).unwrap(), Placement::Holding);
    }
    let rids: Vec<RecordId> = ids
        .iter()
        .map(|s| RecordId::new(s.as_str()).unwrap())
        .collect();
    let taken = spawn_id(rids.iter()).as_text();
    let g = create_spawned(&mut ix, &taken, vec![0.0; 16]);
    set_n(&mut ix, g, 1_000_000); // no room, so the 8th record goes to the holding area
    let before = state_hash(&ix);
    assert!(matches!(
        ins(&mut ix, &ids[7], &live[7]),
        Err(sever_types::Error::IntegrityViolation { .. })
    ));
    assert_eq!(state_hash(&ix), before);
}

// §7.2: P is positive definite, so q < 0 means corrupt state: IntegrityViolation.
#[spec("SR-7.2-2")]
#[test]
fn p1_index_negative_mahalanobis_is_an_integrity_violation() {
    let not_pd = [-1.0, 0.0, 0.0, -1.0];
    assert!(matches!(
        crate::route::mahalanobis(&[0.5, 0.0], &[0.0, 0.0], &not_pd),
        Err(sever_types::Error::IntegrityViolation { .. })
    ));
    assert_eq!(
        crate::route::mahalanobis(&[0.0, 0.0], &[0.0, 0.0], &not_pd),
        Ok(0.0)
    );
}

// §5.5: the parser rejects a wrong format version and an ID that is not UTF-8.
#[spec("SR-5.5-2")]
#[test]
fn p1_index_blob_parser_rejects_version_and_non_utf8() {
    let mut ix = small();
    ins(&mut ix, "doc0", &rows("ref")[0]).unwrap();
    let g = ix.location("doc0").unwrap();
    let blob = ix.blob(&g).unwrap();
    let mut v2 = blob.clone();
    v2[7] = 2; // u16be version at offset 6
    assert_eq!(parse_blob(&v2, b"SEVERC", 0), Err(BlobReject::Version));
    let mut bad = blob.clone();
    let id_at = 18 + 8 * 16 + 8 + 2; // header, S, member_count, id_len
    bad[id_at] = 0xff;
    assert_eq!(parse_blob(&bad, b"SEVERC", 0), Err(BlobReject::Truncated));
    assert!(parse_blob(&blob, b"SEVERC", 0).is_ok());
}

// §5.5: the equivalence helper compares field (3), C_S, on its own.
#[spec("SR-5.5-3")]
#[test]
fn p1_index_equivalence_helper_catches_the_extension_field() {
    let a = crate::blob::GroupSnapshot::<Leaky> {
        s: vec![1, 2],
        n: 1,
        ext_public: 7,
        blob: vec![1],
        member_ids: vec![],
    };
    let mut b = a.clone();
    b.ext_public = 8;
    assert_eq!(assert_state_equivalent(&a, &b), Err(Field::CommitmentS));
}

// §21 INV-4, INV-6, INV-7, INV-8: check_invariants catches each corruption on its own, made here
// by applying forged change sets.
#[test]
fn p1_index_invariant_checks_fire() {
    let build = || {
        let mut ix = small();
        for (i, v) in rows("ref").iter().enumerate().take(30) {
            ins(&mut ix, &format!("doc{i}"), v).unwrap();
        }
        ix.check_invariants().unwrap();
        ix
    };
    let inv = |ix: &Ix| match ix.check_invariants() {
        Err(sever_types::Error::IntegrityViolation { invariant }) => invariant,
        other => panic!("expected a violation, got {other:?}"),
    };
    let g = build().location("doc0").unwrap();
    let corrupt = |f: &dyn Fn(&mut GroupState<NoExtension>)| {
        let mut ix = build();
        let before = state_of(&ix, &g);
        let mut after = before.clone();
        f(&mut after);
        let mut cs = forged(&ix);
        cs.groups.push(GroupChange {
            group: g,
            before,
            after,
        });
        ix.apply(cs);
        inv(&ix)
    };
    assert_eq!(corrupt(&|s| s.n = 1_000_001), "INV-4");
    assert_eq!(corrupt(&|s| s.n += 1), "INV-6 n");
    assert_eq!(corrupt(&|s| s.s[3] += 1), "INV-6 S");
    // INV-8: N disagrees with the group counts.
    let mut ix = build();
    let mut cs = forged(&ix);
    cs.counters_after.big_n += 1;
    ix.apply(cs);
    assert_eq!(inv(&ix), "INV-8");
    // INV-7: a locator entry removed, or pointing at the wrong slot.
    let sid = |id: &str| {
        HmacSha512Scrambler::new(&[7; 64]).scramble(
            &CollectionId::from_bytes([1; 16]),
            &RecordId::new(id).unwrap(),
        )
    };
    let mut ix = build();
    let mut cs = forged(&ix);
    cs.locator.push(LocatorOp::Delete {
        scrambled_id: sid("doc0"),
    });
    ix.apply(cs);
    assert_eq!(inv(&ix), "INV-7");
    let mut ix = build();
    let mut cs = forged(&ix);
    cs.locator.push(LocatorOp::Put {
        scrambled_id: sid("doc0"),
        group: g,
        index: 999,
    });
    ix.apply(cs);
    assert!(inv(&ix).starts_with("INV-7"));
}

// Build §1.1: apply cannot fail. A change set naming groups or slots that do not exist (not one
// plan could produce) changes nothing and does not panic.
#[test]
fn p1_index_apply_ignores_unknown_groups_and_slots() {
    let mut ix = small();
    for (i, v) in rows("ref").iter().enumerate().take(10) {
        ins(&mut ix, &format!("doc{i}"), v).unwrap();
    }
    let before = state_hash(&ix);
    let ghost = GroupId::parse("spawn-00000000000000ff").unwrap();
    let real = ix.location("doc0").unwrap();
    let mut cs = forged(&ix);
    cs.groups.push(GroupChange {
        group: ghost,
        before: GroupState::empty(16),
        after: GroupState::empty(16),
    });
    cs.slots.push(SlotOp::MoveLast {
        group: ghost,
        from: 0,
        to: 1,
    });
    cs.slots.push(SlotOp::MoveLast {
        group: real,
        from: 500,
        to: 600,
    });
    cs.slots.push(SlotOp::Truncate {
        group: ghost,
        len: 0,
    });
    cs.slots.push(SlotOp::DrainInto {
        from: ghost,
        to: real,
    });
    cs.slots.push(SlotOp::DrainInto {
        from: GroupId::Holding,
        to: ghost,
    });
    ix.apply(cs);
    assert_eq!(state_hash(&ix), before);
    ix.check_invariants().unwrap();
}

/// Deliberately wrong extension: its blob region depends on the order of adds.
#[derive(Clone)]
struct LastWins;
impl GroupExtension for LastWins {
    type GroupPublic = i64;
    type GroupSecret = ();
    type RecordSecret = ();
    type Credential = ();
    const BLOB_MAGIC: [u8; 6] = *b"LASTW!";
    fn admit(&self, _: &sever_quant::QVec, _: ()) -> Result<(), sever_types::Error> {
        Ok(())
    }
    fn add(&self, p: &mut i64, _: &mut (), x: &sever_quant::QVec, _: &()) {
        *p = i64::from(x.as_slice()[0]);
    }
    fn remove(&self, p: &mut i64, _: &mut (), _: &sever_quant::QVec, _: &()) {
        *p = 0;
    }
    fn check_removal(&self, _: &sever_quant::QVec, _: &()) -> Result<(), sever_types::Error> {
        Ok(())
    }
    fn blob_region(&self, p: &i64, _: &(), out: &mut Vec<u8>) {
        out.extend(p.to_be_bytes());
    }
    fn check_group(&self, _: &[i64], _: &i64, _: &()) -> Result<(), sever_types::Error> {
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

/// Deliberately wrong extension: it refuses to remove the records it admitted.
#[derive(Clone)]
struct Refuses;
impl GroupExtension for Refuses {
    type GroupPublic = ();
    type GroupSecret = ();
    type RecordSecret = ();
    type Credential = ();
    const BLOB_MAGIC: [u8; 6] = *b"REFUSE";
    fn admit(&self, _: &sever_quant::QVec, _: ()) -> Result<(), sever_types::Error> {
        Ok(())
    }
    fn add(&self, _: &mut (), _: &mut (), _: &sever_quant::QVec, _: &()) {}
    fn remove(&self, _: &mut (), _: &mut (), _: &sever_quant::QVec, _: &()) {}
    fn check_removal(&self, _: &sever_quant::QVec, _: &()) -> Result<(), sever_types::Error> {
        Err(sever_types::Error::IntegrityViolation { invariant: "test" })
    }
    fn blob_region(&self, _: &(), _: &(), _: &mut Vec<u8>) {}
    fn check_group(&self, _: &[i64], _: &(), _: &()) -> Result<(), sever_types::Error> {
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

/// Deliberately wrong scramblers, one per EP-2 rule.
struct Counting(std::sync::atomic::AtomicU8);
impl IdScrambler for Counting {
    fn scramble(&self, _: &CollectionId, _: &RecordId) -> sever_types::ScrambledId {
        let n = self.0.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        sever_types::ScrambledId::from_bytes([n; 64])
    }
}
struct IgnoresCollection;
impl IdScrambler for IgnoresCollection {
    fn scramble(&self, _: &CollectionId, r: &RecordId) -> sever_types::ScrambledId {
        let mut b = [0u8; 64];
        for (o, i) in b.iter_mut().zip(r.as_bytes()) {
            *o = *i;
        }
        sever_types::ScrambledId::from_bytes(b)
    }
}
struct Constant;
impl IdScrambler for Constant {
    fn scramble(&self, c: &CollectionId, _: &RecordId) -> sever_types::ScrambledId {
        sever_types::ScrambledId::from_bytes([c.as_bytes()[0]; 64])
    }
}

// Build §4.7 L7: each contract rule fails for a wrong implementation of it.
#[test]
fn p1_index_contracts_reject_each_wrong_implementation() {
    let xs: Vec<(sever_quant::QVec, ())> = rows("ref")
        .iter()
        .take(6)
        .map(|v| (sever_quant::quantise(v, 16).unwrap(), ()))
        .collect();
    assert_eq!(
        ep1_contract(&LastWins, &xs),
        Err(Ep1Violation::OrderDependent)
    );
    assert_eq!(
        ep1_contract(&Refuses, &xs),
        Err(Ep1Violation::RefusesItsOwnRecord)
    );
    use crate::contract::Ep2Violation;
    assert_eq!(
        ep2_contract(&Counting(std::sync::atomic::AtomicU8::new(0))),
        Err(Ep2Violation::NotDeterministic)
    );
    assert_eq!(
        ep2_contract(&IgnoresCollection),
        Err(Ep2Violation::CollectionIgnored)
    );
    assert_eq!(ep2_contract(&Constant), Err(Ep2Violation::IdCollision));
}

/// Deliberately wrong extensions for the secret half of the EP-1 rules: one keeps an
/// order-dependent secret, one does not restore its secret on removal.
#[derive(Clone)]
struct SecretOrder(bool);
impl GroupExtension for SecretOrder {
    type GroupPublic = ();
    type GroupSecret = i64;
    type RecordSecret = ();
    type Credential = ();
    const BLOB_MAGIC: [u8; 6] = *b"SECRET";
    fn admit(&self, _: &sever_quant::QVec, _: ()) -> Result<(), sever_types::Error> {
        Ok(())
    }
    fn add(&self, _: &mut (), s: &mut i64, x: &sever_quant::QVec, _: &()) {
        if self.0 {
            *s = i64::from(x.as_slice()[0]); // order-dependent
        } else {
            *s += 1;
        }
    }
    fn remove(&self, _: &mut (), s: &mut i64, _: &sever_quant::QVec, _: &()) {
        if self.0 {
            *s = 0;
        } // else: the secret is never restored
    }
    fn check_removal(&self, _: &sever_quant::QVec, _: &()) -> Result<(), sever_types::Error> {
        Ok(())
    }
    fn blob_region(&self, _: &(), _: &i64, _: &mut Vec<u8>) {}
    fn check_group(&self, _: &[i64], _: &(), _: &i64) -> Result<(), sever_types::Error> {
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

#[test]
fn p1_index_contract_checks_the_secret_state_too() {
    let xs: Vec<(sever_quant::QVec, ())> = rows("ref")
        .iter()
        .take(6)
        .map(|v| (sever_quant::quantise(v, 16).unwrap(), ()))
        .collect();
    assert_eq!(
        ep1_contract(&SecretOrder(true), &xs),
        Err(Ep1Violation::OrderDependent)
    );
    assert_eq!(
        ep1_contract(&SecretOrder(false), &xs),
        Err(Ep1Violation::RemoveIsNotInverse)
    );
}

// EP-3: a change set that changes nothing says so (every request AlreadyAbsent); any real change
// does not.
#[spec("SR-5.4-2")]
#[test]
fn p1_index_change_set_is_noop_only_when_nothing_changes() {
    let mut ix = small();
    ins(&mut ix, "doc0", &rows("ref")[0]).unwrap();
    let absent = ix
        .plan_delete(DeleteRequest {
            record_id: "nope".into(),
        })
        .unwrap();
    assert!(absent.is_noop());
    assert_eq!(absent.outcomes, vec![Outcome::AlreadyAbsent]);
    let real = ix
        .plan_delete(DeleteRequest {
            record_id: "doc0".into(),
        })
        .unwrap();
    assert!(!real.is_noop());
    let insert = ix
        .plan_insert(InsertRequest {
            record_id: "doc1".into(),
            vector: rows("ref")[1].clone(),
            credential: (),
        })
        .unwrap();
    assert!(!insert.is_noop());
    // An insert into the holding area changes slots and the locator but no accumulator: still a
    // change.
    let held = ix
        .plan_insert(InsertRequest {
            record_id: "live0".into(),
            vector: rows("live")[0].clone(),
            credential: (),
        })
        .unwrap();
    assert!(held.groups.is_empty() && held.created.is_empty());
    assert!(!held.is_noop());
}

// §4.3, §12.6: after inserts, flushes and swap-with-last deletions, every group's float32 mirror
// row equals x̃ / 2^24 of the member it is listed for (row for row), so search scores real vectors.
#[spec("SR-4.3-2", "SR-8.1-3")]
#[test]
fn p1_index_mirror_rows_follow_their_records() {
    let mut ix = small();
    let all: Vec<Vec<f32>> = rows("ref").into_iter().chain(rows("live")).collect();
    for (i, v) in all.iter().enumerate() {
        ins(&mut ix, &format!("r{i}"), v).unwrap();
    }
    for i in (0..all.len()).step_by(3) {
        del(&mut ix, &format!("r{i}"));
    }
    let mut checked = 0;
    for g in ix.search_groups() {
        let blob = ix.blob(&g.id).unwrap();
        let members: std::collections::HashMap<Vec<u8>, Vec<i64>> = parse_blob(&blob, b"SEVERC", 0)
            .unwrap()
            .members
            .into_iter()
            .collect();
        for (row, id) in g.rows.chunks_exact(16).zip(g.ids) {
            let x = &members[id.as_bytes()];
            let want: Vec<f32> = x.iter().map(|&v| v as f32 / 16_777_216.0).collect();
            assert_eq!(
                row,
                want.as_slice(),
                "mirror row of {} in {}",
                id.as_str(),
                g.id
            );
            checked += 1;
        }
    }
    assert_eq!(checked as u64, ix.stats().big_n);
}

// Build §1.1: a MoveLast whose positions sit exactly at the slot count (one past the end) is
// ignored, not a panic.
#[test]
fn p1_index_apply_ignores_moves_at_the_slot_count() {
    let mut ix = small();
    for (i, v) in rows("ref").iter().enumerate().take(10) {
        ins(&mut ix, &format!("doc{i}"), v).unwrap();
    }
    let g = ix.location("doc0").unwrap();
    let len = ix.group_len(&g).unwrap();
    let before = state_hash(&ix);
    let mut cs = forged(&ix);
    for (from, to) in [(len, 0), (0, len), (len, len)] {
        cs.slots.push(SlotOp::MoveLast { group: g, from, to });
    }
    ix.apply(cs);
    assert_eq!(state_hash(&ix), before);
    ix.check_invariants().unwrap();
}

// §5.6 hard cap at its boundary without 10^6 inserts: the group's n is set by a forged change set,
// then plan_insert alone is asked (n = 10^6 − 1 admits one more; n = 10^6 admits none).
#[spec("SR-5.6-2")]
#[test]
fn p1_index_hard_cap_boundary_by_plan() {
    let mut ix = frozen_only();
    let v = rows("ref")[0].clone();
    let (g, _) = ix.route(&sever_quant::quantise(&v, 16).unwrap()).unwrap();
    let cap = sever_types::constants::MAX_GROUP_MEMBERS;
    let plan = |ix: &Ix| {
        ix.plan_insert(InsertRequest {
            record_id: "x".into(),
            vector: v.clone(),
            credential: (),
        })
        .map(|_| ())
    };
    set_n(&mut ix, g, cap - 1);
    assert_eq!(plan(&ix), Ok(()));
    set_n(&mut ix, g, cap);
    assert_eq!(plan(&ix), Err(sever_types::Error::GroupCapacityExceeded));
}

// §21: n = 10^6 exactly is within INV-4 (the cap), so a wrong n there is INV-6, not INV-4.
#[test]
fn p1_index_inv4_boundary_is_inclusive() {
    let mut ix = small();
    ins(&mut ix, "doc0", &rows("ref")[0]).unwrap();
    let g = ix.location("doc0").unwrap();
    set_n(&mut ix, g, sever_types::constants::MAX_GROUP_MEMBERS);
    assert_eq!(
        ix.check_invariants(),
        Err(sever_types::Error::IntegrityViolation {
            invariant: "INV-6 n"
        })
    );
}

// §21 INV-5: ⌊1.5·N/k⌋ ≤ 10^6 holds for a frozen-only index with N·k well above 10^5
// (N = 42,000, k = 4: ⌊1.5·N/k⌋ = 15,750), so the check passes on a real, larger index.
#[test]
fn p1_index_inv5_holds_on_a_larger_index() {
    let refs = rows("ref");
    let mut ix = frozen_only();
    for i in 0..42_000 {
        let r = ins(&mut ix, &format!("r{i}"), &refs[i % refs.len()]);
        assert!(matches!(r, Ok(Placement::Frozen(_))));
    }
    assert_eq!((ix.stats().big_n, ix.stats().k), (42_000, 4));
    ix.check_invariants().unwrap();
}

// §7.3 spillover in both creation orders: the nearest group wins; on equal distance the smaller
// group-ID bytes win, whichever was created first.
#[spec("SR-7.3-1")]
#[test]
fn p1_index_spillover_nearest_and_tie_in_both_orders() {
    let x = sever_quant::quantise(&rows("live")[0], 16).unwrap();
    let mu = x.dequantise_f64();
    let far: Vec<f64> = mu.iter().map(|m| m + 0.25).collect();
    let fill = |ix: &mut Ix| {
        for (i, v) in rows("ref").iter().enumerate().take(20) {
            ins(ix, &format!("doc{i}"), v).unwrap();
        }
    };
    // Tie, the smaller ID created first.
    let mut ix = small();
    fill(&mut ix);
    let a = create_spawned(&mut ix, "spawn-0000000000000001", mu.clone());
    create_spawned(&mut ix, "spawn-0000000000000002", mu.clone());
    assert_eq!(ix.route(&x).unwrap(), (a, true));
    // The nearest wins over a smaller ID, in either order.
    for near_first in [true, false] {
        let mut ix = small();
        fill(&mut ix);
        let (near, _far) = if near_first {
            let n = create_spawned(&mut ix, "spawn-00000000000000f0", mu.clone());
            (
                n,
                create_spawned(&mut ix, "spawn-0000000000000001", far.clone()),
            )
        } else {
            let f = create_spawned(&mut ix, "spawn-0000000000000001", far.clone());
            (
                create_spawned(&mut ix, "spawn-00000000000000f0", mu.clone()),
                f,
            )
        };
        assert_eq!(ix.route(&x).unwrap(), (near, true));
    }
}

// §17, §9.7: Debug output of a slot and of the scrambler names the type and never the key.
#[test]
fn p1_index_debug_output_is_redacted() {
    let s = HmacSha512Scrambler::new(&[0x41; 64]);
    let text = format!("{s:?}");
    assert!(text.starts_with("HmacSha512Scrambler(") && text.contains("redacted"));
    assert!(!text.contains("41") && !text.contains('A'));
    let mut ix = small();
    ins(&mut ix, "doc0", &rows("ref")[0]).unwrap();
    let cs = ix
        .plan_insert(InsertRequest {
            record_id: "doc1".into(),
            vector: rows("ref")[1].clone(),
            credential: (),
        })
        .unwrap();
    let slot = cs
        .slots
        .iter()
        .find_map(|op| match op {
            SlotOp::Put { slot, .. } => Some(slot),
            _ => None,
        })
        .unwrap();
    let text = format!("{slot:?}");
    assert!(text.starts_with("Slot(") && !text.contains("doc1"));
}
