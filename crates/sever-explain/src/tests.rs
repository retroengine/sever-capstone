//! Oracle A: §4.2, §7.1–7.3 and §8.1 worked by hand on the small artefact (golden, d = 16), with
//! the distances summed again here, sequentially, from the spec's formulas.

use sever_partition::PartitionArtefact;
use sever_types::GroupId;

use super::*;

const ARTEFACT: &[u8] = include_bytes!("../../../golden/p1_partition_small.svp");

fn art() -> PartitionArtefact {
    PartitionArtefact::parse(ARTEFACT).unwrap()
}

fn seq(a: &[f64], b: &[f64]) -> f64 {
    let mut s = 0.0;
    for i in 0..a.len() {
        s += (a[i] - b[i]) * (a[i] - b[i]);
    }
    s
}

fn unit(seed: u64, d: usize) -> Vec<f32> {
    let mut x = seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1;
    let v: Vec<f64> = (0..d)
        .map(|_| {
            x ^= x << 13;
            x ^= x >> 7;
            x ^= x << 17;
            (x >> 11) as f64 / (1u64 << 53) as f64 * 2.0 - 1.0
        })
        .collect();
    let n = v.iter().map(|a| a * a).sum::<f64>().sqrt();
    v.iter().map(|a| (a / n) as f32).collect()
}

#[test]
fn p4_explain_a_frozen_centroid_routes_to_its_own_group() {
    // oracle: A §7.1–7.3: a vector at a frozen centroid has D = 0 to it and d_M = 0 ≤ τ
    let a = art();
    let mu = a.centroid(2).unwrap();
    let n = mu.iter().map(|v| v * v).sum::<f64>().sqrt();
    let x: Vec<f32> = mu.iter().map(|v| (v / n) as f32).collect();
    let e = explain_route(&a, &x, &[], 100, 4).unwrap();
    assert_eq!(e.j_star, e.nearest[0].0);
    assert!(e.in_distribution);
    assert_eq!(e.destination, GroupId::frozen(e.j_star as u16).unwrap());
}

#[test]
fn p4_explain_distances_are_the_specs_sums_on_x_hat() {
    // oracle: A §4.2 x̃ = round(x·2^24), x̂ = x̃/2^24; §7.1 D_j = Σ (x̂_i − μ_{j,i})² sequential
    let a = art();
    for seed in 1..50 {
        let x = unit(seed, a.d);
        let e = explain_route(&a, &x, &[], 100, 4).unwrap();
        let xt: Vec<i32> = x
            .iter()
            .map(|v| (f64::from(*v) * 16_777_216.0).round_ties_even() as i32)
            .collect();
        assert_eq!(e.x_tilde, xt);
        let xhat: Vec<f64> = xt.iter().map(|v| f64::from(*v) / 16_777_216.0).collect();
        let mut all: Vec<(usize, f64)> = (0..a.k_frozen)
            .map(|j| (j, seq(&xhat, a.centroid(j).unwrap())))
            .collect();
        all.sort_by(|p, q| p.1.total_cmp(&q.1));
        for (got, want) in e.nearest.iter().zip(&all) {
            assert_eq!(got.0, want.0);
            assert_eq!(got.1.to_bits(), want.1.to_bits());
        }
        assert_eq!(e.in_distribution, e.d_m <= a.tau);
    }
}

#[test]
fn p4_explain_out_of_distribution_goes_to_room_else_holding() {
    // oracle: A §7.3 and §5.6: OOD → nearest spawned group with 2·k·n < 3·N, else the holding area
    let a = art();
    let x = (1..400)
        .map(|s| unit(s, a.d))
        .find(|x| !explain_route(&a, x, &[], 100, 4).unwrap().in_distribution)
        .expect("an OOD vector");
    let far = vec![0.0; a.d];
    let near: Vec<f64> = x.iter().map(|v| f64::from(*v)).collect();
    let g = |s: &str| GroupId::parse(s).unwrap();
    let full = Spawned {
        id: g("spawn-00000000000000aa"),
        centroid: near.clone(),
        n: 200,
    };
    let open = Spawned {
        id: g("spawn-00000000000000bb"),
        centroid: far,
        n: 8,
    };
    // N = 300, k = 6: room needs 2·6·n < 900, so n = 8 has room and n = 200 does not
    let e = explain_route(&a, &x, &[full.clone(), open.clone()], 300, 6).unwrap();
    assert_eq!(e.room.len(), 1);
    assert_eq!(e.destination, open.id);
    let e = explain_route(&a, &x, &[full], 300, 6).unwrap();
    assert_eq!(e.destination, GroupId::Holding);
}

#[test]
fn p4_explain_search_opens_a_quarter_of_the_groups() {
    // oracle: A §8.1 p = ⌈0.25·k⌉, empty groups included; ranked by (D_g, group-ID bytes)
    let a = art();
    let groups: Vec<(GroupId, Vec<f64>)> = (0..a.k_frozen)
        .map(|j| {
            (
                GroupId::frozen(j as u16).unwrap(),
                a.centroid(j).unwrap().to_vec(),
            )
        })
        .collect();
    let q = unit(7, a.d);
    let e = explain_search(&q, &groups);
    assert_eq!(e.probed, a.k_frozen.div_ceil(4));
    let qd: Vec<f64> = q.iter().map(|v| f64::from(*v)).collect();
    let mut want: Vec<(usize, f64)> = (0..a.k_frozen)
        .map(|j| (j, seq(&qd, a.centroid(j).unwrap())))
        .collect();
    want.sort_by(|p, r| p.1.total_cmp(&r.1));
    for ((g, d), (j, dw)) in e.ranked.iter().zip(&want) {
        assert_eq!(*g, GroupId::frozen(*j as u16).unwrap());
        assert_eq!(d.to_bits(), dw.to_bits());
    }
}
