//! L1 and L2 tests for `sever-search` (Build §4.7). `#[spec(...)]` names requirement IDs.

use proptest::prelude::*;
use sever_index::{
    DeleteRequest, HmacSha512Scrambler, Index, IndexConfig, InsertRequest, NoExtension,
};
use sever_partition::PartitionArtefact;
use sever_types::CollectionId;

use crate::kernel::{score, score_scalar, uses_avx2};
use crate::{probe_count, search};
use sever_spec::spec;

type Ix = Index<NoExtension, HmacSha512Scrambler>;

fn rows(key: &str) -> Vec<Vec<f32>> {
    let doc: serde_json::Value =
        serde_json::from_str(include_str!("../../../golden/p1_fixture_vectors.json")).unwrap();
    doc[key]
        .as_array()
        .unwrap()
        .iter()
        .map(|h| {
            let s = h.as_str().unwrap();
            let bytes: Vec<u8> = (0..s.len() / 2)
                .map(|i| u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap())
                .collect();
            bytes
                .chunks_exact(4)
                .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
                .collect()
        })
        .collect()
}

fn index(spawning: bool) -> Ix {
    let art =
        PartitionArtefact::parse(include_bytes!("../../../golden/p1_partition_small.svp")).unwrap();
    Index::new(
        &art,
        IndexConfig {
            spawning_enabled: spawning,
            spawn_target: 8,
        },
        NoExtension,
        HmacSha512Scrambler::new(&[7; 64]),
        CollectionId::from_bytes([1; 16]),
    )
    .unwrap()
}

fn ins(ix: &mut Ix, id: &str, v: &[f32]) {
    ix.insert(InsertRequest {
        record_id: id.into(),
        vector: v.to_vec(),
        credential: (),
    })
    .unwrap();
}

// a hand-computed 16-dimensional example where the lane layout matters:
// t_0 = 4096, t_1 = t_9 = 1. Lanes: L0 = 2^24, L1 = 1 + 1 = 2, so the total is 2^24 + 2 exactly.
// A plain sequential sum would give 2^24 (each +1 is lost against 2^24 in float32).
#[spec("SR-8.2-1")]
#[test]
fn p1_search_kernel_lane_layout_by_hand() {
    let mut q = [0.0_f32; 16];
    q[0] = 4096.0;
    q[1] = 1.0;
    q[9] = 1.0;
    let x = [0.0_f32; 16];
    assert_eq!(score_scalar(&q, &x), 16_777_218.0);
    assert_eq!(score(&q, &x), 16_777_218.0);
    let naive: f32 = q
        .iter()
        .zip(&x)
        .fold(0.0, |acc, (a, b)| acc + (a - b) * (a - b));
    assert_eq!(naive, 16_777_216.0, "the order really matters here");
}

// P1-T4: scalar and AVX2 bit-identical (10^5 pairs here; 10^7 in the ignored
// test below, run by the Full tier).
#[spec("SR-8.2-1")]
#[test]
fn p1_search_kernel_scalar_equals_avx2() {
    assert!(
        uses_avx2(),
        "this machine has AVX2 (spec §20.4); without it the test proves nothing"
    );
    let mut state = 0x9e37_79b9_7f4a_7c15_u64;
    let mut next = || {
        state = state.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut z = state;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        ((z ^ (z >> 31)) >> 40) as f32 / (1u64 << 24) as f32 * 2.0 - 1.0
    };
    for _ in 0..100_000 {
        let q: Vec<f32> = (0..384).map(|_| next()).collect();
        let x: Vec<f32> = (0..384).map(|_| next()).collect();
        assert_eq!(score(&q, &x).to_bits(), score_scalar(&q, &x).to_bits());
    }
}

#[test]
#[ignore = "P1-T4 at full size: 10^7 pairs (Full CI tier)"]
fn p1_search_kernel_scalar_equals_avx2_ten_million() {
    let mut state = 1_u64;
    let mut next = || {
        state = state
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1);
        ((state >> 40) as f32 / (1u64 << 24) as f32) * 2.0 - 1.0
    };
    for _ in 0..10_000_000 {
        let q: Vec<f32> = (0..384).map(|_| next()).collect();
        let x: Vec<f32> = (0..384).map(|_| next()).collect();
        assert_eq!(score(&q, &x).to_bits(), score_scalar(&q, &x).to_bits());
    }
}

// ⌈0.25·k⌉ for k mod 4 = 0, 1, 2, 3, and the Appendix A counts.
#[spec("SR-8.1-2")]
#[test]
fn p1_search_probe_count() {
    for (k, p) in [(4, 1), (5, 2), (6, 2), (7, 2), (8, 2), (128, 32), (263, 66)] {
        assert_eq!(probe_count(k), p);
    }
}

// empty groups use probe slots (SB-6): emptying the nearest group must not let
// a farther group into the budget.
#[spec("SR-8.1-2")]
#[test]
fn p1_search_empty_groups_count_in_the_budget() {
    let refs = rows("ref");
    let mut ix = index(false);
    for (i, v) in refs.iter().enumerate() {
        ins(&mut ix, &format!("doc{i}"), v);
    }
    let q = &refs[0];
    let first = crate::probed_groups(&ix, q)[0]; // k = 4, so p = 1: only the nearest group
    let members: Vec<String> = (0..refs.len())
        .map(|i| format!("doc{i}"))
        .filter(|r| ix.location(r) == Some(first))
        .collect();
    ix.delete_many(
        members
            .into_iter()
            .map(|record_id| DeleteRequest { record_id })
            .collect(),
    )
    .unwrap();
    assert_eq!(crate::probed_groups(&ix, q), vec![first]);
    assert!(
        search(&ix, q, 10).unwrap().is_empty(),
        "the probe slot went to the empty group"
    );
}

// results sorted by (score, id); a deleted record never comes back
// (E2E-1.6 in miniature); the holding area is never searched.
#[spec("SR-8.1-3", "SR-8.1-4")]
#[test]
fn p1_search_results_order_and_deletion() {
    let (refs, live) = (rows("ref"), rows("live"));
    let mut ix = index(true);
    for (i, v) in refs.iter().enumerate() {
        ins(&mut ix, &format!("doc{i}"), v);
    }
    for (i, v) in live.iter().enumerate().take(5) {
        ins(&mut ix, &format!("live{i}"), v); // all in the holding area (target 8)
    }
    let hits = search(&ix, &refs[5], 20).unwrap();
    assert_eq!(hits[0].record_id.as_str(), "doc5");
    // Not 0: the mirror holds x̂ = x̃ / 2^24 (§8.1 step 3), so the query differs from its own
    // stored copy by the Q24 rounding, at most 2^−25 per component.
    assert!(hits[0].score > 0.0 && hits[0].score < 16.0 * 2f32.powi(-50));
    assert!(hits.windows(2).all(
        |w| (w[0].score, w[0].record_id.as_bytes()) <= (w[1].score, w[1].record_id.as_bytes())
    ));
    assert!(
        search(&ix, &live[0], 50)
            .unwrap()
            .iter()
            .all(|h| !h.record_id.as_str().starts_with("live"))
    );
    ix.delete(DeleteRequest {
        record_id: "doc5".into(),
    })
    .unwrap();
    for q in &refs {
        assert!(
            search(&ix, q, 50)
                .unwrap()
                .iter()
                .all(|h| h.record_id.as_str() != "doc5")
        );
    }
}

// the query is checked like any vector.
#[spec("SR-4.1-0")]
#[test]
fn p1_search_rejects_bad_queries() {
    let ix = index(true);
    assert_eq!(
        search(&ix, &[0.0; 8], 5),
        Err(sever_types::Error::WrongDimension)
    );
    assert_eq!(
        search(&ix, &[0.0; 16], 5),
        Err(sever_types::Error::NotNormalised)
    );
    let mut nan = rows("ref")[0].clone();
    nan[2] = f32::NAN;
    assert_eq!(search(&ix, &nan, 5), Err(sever_types::Error::NonFinite));
}

proptest! {
    // scalar and AVX2 agree bit for bit on arbitrary finite inputs.
    #[spec("SR-8.2-1")]
    #[test]
    fn p1_search_prop_kernels_agree(q in proptest::collection::vec(-4.0f32..4.0, 64),
                                    x in proptest::collection::vec(-4.0f32..4.0, 64)) {
        prop_assert_eq!(score(&q, &x).to_bits(), score_scalar(&q, &x).to_bits());
    }
}

// §8.1 step 1: D_g = Σ((f64)q_i − μ_{g,i})², sequential from i = 0; groups ascending by
// (D_g, group-ID bytes). Two pairs tie on D_g; "frozen-…" < "spawn-…" by bytes.
#[spec("SR-8.1-1")]
#[test]
fn p1_search_rank_groups_by_distance_then_id_bytes() {
    use sever_index::SearchGroup;
    use sever_types::GroupId;
    let q = [0.5f32, -0.25, 0.125, 0.0, 0.0, 0.0, 0.0, 0.0];
    let near = [0.5f64, -0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0];
    let far = [0.0f64; 8];
    let spawn = GroupId::parse("spawn-0000000000000001").unwrap();
    let f = |l: u16| GroupId::frozen(l).unwrap();
    let groups = [(f(2), &far), (spawn, &near), (f(1), &far), (f(3), &near)];
    let ranked = crate::rank_groups(
        &q,
        groups.iter().map(|(id, c)| SearchGroup {
            id: *id,
            centroid: c.as_slice(),
            ids: &[],
            rows: &[],
        }),
    );
    let order: Vec<GroupId> = ranked.iter().map(|(_, g)| g.id).collect();
    assert_eq!(order, vec![f(3), spawn, f(1), f(2)]);
    let seq = |c: &[f64]| {
        let mut s = 0.0f64;
        for (a, m) in q.iter().zip(c) {
            let t = f64::from(*a) - m;
            s += t * t;
        }
        s
    };
    assert_eq!(ranked[0].0.to_bits(), seq(&near).to_bits());
    assert_eq!(ranked[2].0.to_bits(), seq(&far).to_bits());
}

// §8.2 reduction tree with all eight lanes distinct and non-zero (L_j = (j + 1)²), so every
// addition of ((L0 + L1) + (L2 + L3)) + ((L4 + L5) + (L6 + L7)) changes the result if altered.
#[spec("SR-8.2-1")]
#[test]
fn p1_search_reduction_uses_every_lane() {
    let q: Vec<f32> = (1..=8).map(|j| j as f32).collect();
    let x = [0.0_f32; 8];
    assert_eq!(score_scalar(&q, &x), 204.0); // (1+4)+(9+16) + (25+36)+(49+64), exact in f32
    assert_eq!(score(&q, &x), 204.0);
}
