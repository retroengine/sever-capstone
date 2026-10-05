//! L9 end-to-end tests E2E-1.1 … E2E-1.7 (Build §4.7), through the composition root and the demo.
//! The Fast tier runs them on the offline small fixture (Build §2.7: d = 16, 4 frozen groups, spawn
//! size 8); `p1_e2e_demo_nq10k` runs the demo on `nq-10k` (ignored by default: it needs the P0 data
//! and the seed-42 artefact; run with `--ignored`).

// Test code (clippy.toml allows these in #[test] functions; the helpers here are test code too).
#![allow(clippy::unwrap_used, clippy::indexing_slicing)]

use std::collections::BTreeMap;
use std::path::PathBuf;

use sever_index::{DeleteRequest, IndexConfig, InsertRequest, Outcome, Placement};
use sever_p1::data::{load_nq, load_synthetic};
use sever_p1::{Dataset, P1Index, new_index, run};
use sever_types::{Error, GroupId};
use sha2::{Digest, Sha256};

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn fixture() -> Dataset {
    load_synthetic(&root()).unwrap()
}

fn index(ds: &Dataset) -> P1Index {
    new_index(
        &ds.artefact,
        IndexConfig {
            spawning_enabled: true,
            spawn_target: ds.spawn_target,
        },
    )
    .unwrap()
}

fn insert(ix: &mut P1Index, id: &str, x: &[f32]) -> Result<Placement, Error> {
    ix.insert(InsertRequest {
        record_id: id.to_owned(),
        vector: x.to_vec(),
        credential: (),
    })
}

fn delete(ix: &mut P1Index, id: &str) -> Outcome {
    ix.delete(DeleteRequest {
        record_id: id.to_owned(),
    })
    .unwrap()
}

fn blob_hashes(ix: &P1Index) -> BTreeMap<GroupId, Vec<u8>> {
    ix.group_ids()
        .into_iter()
        .map(|g| (g, Sha256::digest(ix.blob(&g).unwrap()).to_vec()))
        .collect()
}

/// Rows of the fixture by kind: `syn-ref-*` are in distribution, `syn-live-*` out of distribution.
fn rows<'a>(ds: &'a Dataset, kind: &str) -> Vec<(&'a str, &'a [f32])> {
    ds.ids
        .iter()
        .enumerate()
        .filter(|(_, id)| id.starts_with(&format!("syn-{kind}-")))
        .map(|(i, id)| (id.as_str(), ds.vector(i).unwrap()))
        .collect()
}

// spec: SR-5.3-1, SR-5.4-1, SR-5.5-1, SR-8.1-4 — E2E-1.1, E2E-1.4, E2E-1.5, E2E-1.6 through the
// demo: every touched group equals its survivors-only rebuild, nothing else changes, N falls by the
// cohort size, a second delete is AlreadyAbsent, and no search returns a deleted record.
#[test]
fn p1_e2e_demo_synthetic_deletion_is_exact() {
    let r = run(&fixture()).unwrap();
    assert!(!r.groups.is_empty());
    assert!(r.groups.iter().all(|g| g.exact), "a touched group differs");
    assert!(r.groups.iter().all(|g| g.n_after < g.n_before));
    assert_eq!(r.untouched.unchanged, r.untouched.groups);
    let in_groups = r.target.record_ids.len() as u64 - r.holding.cohort_members;
    assert_eq!(r.big_n[0] - r.big_n[1], in_groups);
    assert!(r.second_delete.all_already_absent && r.second_delete.state_unchanged);
    assert_eq!(r.search.deleted_returned_after, 0);
    assert!(
        r.search.example.is_some(),
        "no search found a cohort record before deletion"
    );
    assert_eq!(r.invariants, "ok");
}

// P1-T14 (measure, descriptive): the baselines keep a ghost; SEVER keeps none.
#[test]
fn p1_e2e_demo_synthetic_ghost_rows() {
    let r = run(&fixture()).unwrap();
    let by: BTreeMap<_, _> = r.ghost.summary.iter().map(|s| (s.system, s)).collect();
    assert!(by["soft-delete IVF"].deleted_record_still_stored);
    assert!(by["soft-delete IVF"].distance > 0.0);
    assert!(!by["float running mean"].deleted_record_still_stored);
    assert_eq!(by["SEVER (Part 1)"].distance, 0.0);
    assert!(r.ghost.per_group.iter().all(|g| g.sever_max_abs_diff == 0));
}

// spec: SR-7.4-2, SR-7.5-1 — E2E-1.2: the holding area holds spawn_target − 1 records; the next
// out-of-distribution record flushes exactly those records into exactly one spawned group whose ID is
// `spawn-` + the first 16 hex of SHA-256(‖ u16be(len) ‖ id), IDs ascending by bytes (computed here
// from the spec, not with the engine's function).
#[test]
fn p1_e2e_flush_at_exactly_the_spawn_target() {
    let ds = fixture();
    let mut ix = index(&ds);
    let live = rows(&ds, "live");
    let t = ds.spawn_target;
    for (id, x) in live.iter().take(t - 1) {
        assert_eq!(insert(&mut ix, id, x).unwrap(), Placement::Holding);
    }
    assert_eq!(ix.stats().holding, (t - 1) as u64);
    assert_eq!(ix.stats().spawned, 0);
    let (last_id, last_x) = live[t - 1];
    let placed = insert(&mut ix, last_id, last_x).unwrap();
    let st = ix.stats();
    assert_eq!((st.spawned, st.holding, st.big_n), (1, 0, t as u64));
    let mut ids: Vec<&str> = live.iter().take(t).map(|(id, _)| *id).collect();
    ids.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
    let mut h = Sha256::new();
    for id in &ids {
        h.update((id.len() as u16).to_be_bytes());
        h.update(id.as_bytes());
    }
    let hexid: String = h.finalize()[..8]
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    let expected = GroupId::parse(&format!("spawn-{hexid}")).unwrap();
    assert_eq!(placed, Placement::Spawned(expected));
    assert_eq!(ix.group_len(&expected), Some(t));
    for id in &ids {
        assert_eq!(ix.location(id), Some(expected));
    }
}

// spec: SR-7.4-1, SR-7.4-3 — E2E-1.3: a holding-area record is deleted at once; no accumulator and no
// N changes.
#[test]
fn p1_e2e_holding_record_deleted_at_once() {
    let ds = fixture();
    let mut ix = index(&ds);
    for (id, x) in rows(&ds, "ref").iter().take(40) {
        insert(&mut ix, id, x).unwrap();
    }
    let live = rows(&ds, "live");
    for (id, x) in live.iter().take(3) {
        assert_eq!(insert(&mut ix, id, x).unwrap(), Placement::Holding);
    }
    let blobs = blob_hashes(&ix);
    let n = ix.stats().big_n;
    // About 1 % of in-distribution rows exceed τ (the P99) and wait in the holding area too.
    let holding = ix.stats().holding;
    assert!(holding >= 3);
    assert_eq!(
        delete(&mut ix, live[1].0),
        Outcome::Deleted {
            from: GroupId::Holding
        }
    );
    assert_eq!(ix.location(live[1].0), None);
    assert_eq!(ix.stats().holding, holding - 1);
    assert_eq!(ix.stats().big_n, n);
    assert_eq!(blob_hashes(&ix), blobs);
    ix.check_invariants().unwrap();
}

// spec: SR-5.4-2 — E2E-1.5 on its own: deleting an absent record changes nothing.
#[test]
fn p1_e2e_delete_absent_is_already_absent() {
    let ds = fixture();
    let mut ix = index(&ds);
    for (id, x) in rows(&ds, "ref").iter().take(20) {
        insert(&mut ix, id, x).unwrap();
    }
    let before = blob_hashes(&ix);
    assert_eq!(delete(&mut ix, "never-inserted"), Outcome::AlreadyAbsent);
    assert_eq!(blob_hashes(&ix), before);
    assert!(matches!(
        delete(&mut ix, "syn-ref-000"),
        Outcome::Deleted { from } if from != GroupId::Holding
    ));
    let after_first = blob_hashes(&ix);
    let n = ix.stats().big_n;
    assert_eq!(delete(&mut ix, "syn-ref-000"), Outcome::AlreadyAbsent);
    assert_eq!(blob_hashes(&ix), after_first);
    assert_eq!(ix.stats().big_n, n);
}

// spec: SR-17-1, SR-17-2, SR-3.2-1, SR-3.2-2, SR-3.2-3, SR-4.1-0, SR-4.1-1, SR-4.1-3 — E2E-1.7: every
// malformed input Part 1 owns gets a typed error whose text names no ID and no vector value.
#[test]
fn p1_e2e_malformed_inputs_typed_errors_without_secrets() {
    let ds = fixture();
    let mut ix = index(&ds);
    let (good_id, good_x) = rows(&ds, "ref")[0];
    insert(&mut ix, good_id, good_x).unwrap();
    let mut nan = good_x.to_vec();
    nan[3] = f32::NAN;
    let mut unnormalised = good_x.to_vec();
    unnormalised[0] += 0.25;
    let long_id = "x".repeat(257);
    let cases: Vec<(&str, Vec<f32>, Error)> = vec![
        ("syn-short", good_x[..15].to_vec(), Error::WrongDimension),
        ("syn-nan", nan, Error::NonFinite),
        ("syn-unnormalised", unnormalised, Error::NotNormalised),
        (
            "",
            good_x.to_vec(),
            Error::InvalidRecordId(sever_types::InvalidRecordIdReason::Empty),
        ),
        (
            &long_id,
            good_x.to_vec(),
            Error::InvalidRecordId(sever_types::InvalidRecordIdReason::TooLong),
        ),
        (
            "-0042",
            good_x.to_vec(),
            Error::InvalidRecordId(sever_types::InvalidRecordIdReason::CounterShaped),
        ),
        (
            good_id,
            good_x.to_vec(),
            Error::DuplicateRecord {
                same_commitment: true,
            },
        ),
    ];
    let before = blob_hashes(&ix);
    for (id, x, want) in cases {
        let e = insert(&mut ix, id, &x).unwrap_err();
        assert_eq!(e, want, "id {id:?}");
        for text in [format!("{e}"), format!("{e:?}")] {
            if !id.is_empty() {
                assert!(!text.contains(id), "error text names the record ID: {text}");
            }
            for v in &x {
                assert!(
                    !text.contains(&format!("{v}")),
                    "error text names a vector value: {text}"
                );
            }
        }
    }
    assert_eq!(
        blob_hashes(&ix),
        before,
        "a rejected insert changed the index"
    );
    // §8.1 input: the query is checked like a vector.
    assert_eq!(
        sever_search::search(&ix, &good_x[..8], 10).unwrap_err(),
        Error::WrongDimension
    );
}

// The full demo on nq-10k, seed 42 (Build §4.9; E2E-1.1, 1.4, 1.5, 1.6 on real data).
#[test]
#[ignore = "needs the P0 data and artefacts/partition-seed42.svp; run with --ignored"]
fn p1_e2e_demo_nq10k() {
    let ds = load_nq(&root(), "nq-10k", 42).unwrap();
    let r = run(&ds).unwrap();
    assert_eq!(r.build.accepted, 10_000);
    assert!(r.groups.iter().all(|g| g.exact));
    assert_eq!(r.untouched.unchanged, r.untouched.groups);
    assert!(r.second_delete.all_already_absent && r.second_delete.state_unchanged);
    assert_eq!(r.search.queries, 3_452);
    assert_eq!(r.search.deleted_returned_after, 0);
    assert_eq!(r.invariants, "ok");
}
