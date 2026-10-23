//! `sever-explain`: why a record went where it did (§7.1–7.3) and which groups a search opens
//! (§8.1 steps 1–2), for programs that show the engine at work (DB-108, spec §16.1).
//!
//! The arithmetic is the frozen crates' own: `sever_quant::quantise` (§4.2),
//! `sever_index::route::{sq_dist_f64, mahalanobis}` (§7.1–7.2, the pinned summation orders) and
//! `sever_search::{rank_groups, probe_count}` (§8.1). The few lines of decision between them
//! follow §7.3 as written, and whoever shows an explanation checks it against the engine's actual
//! placement every time. No file I/O, clock or randomness here (CLAUDE.md §7).

pub use sever_partition::PartitionArtefact;

use sever_index::SearchGroup;
use sever_index::route::{mahalanobis, sq_dist_f64};
use sever_search::{probe_count, rank_groups};
use sever_types::{Error, GroupId};

/// How many of the nearest frozen groups an explanation lists.
pub const NEAREST: usize = 5;

/// A spawned group as the engine reported it: its ID, its centre `μ` (§7.5) and its size `n`.
#[derive(Clone, Debug, PartialEq)]
pub struct Spawned {
    /// The group.
    pub id: GroupId,
    /// Its frozen centre.
    pub centroid: Vec<f64>,
    /// Its member count now.
    pub n: u64,
}

/// §7.1–7.3 for one vector.
#[derive(Clone, Debug, PartialEq)]
pub struct RouteExplanation {
    /// `x̃` (§4.2).
    pub x_tilde: Vec<i32>,
    /// The nearest frozen groups, `(label, D_j)`, ascending (ties to the smaller label).
    pub nearest: Vec<(usize, f64)>,
    /// `j*` (§7.1).
    pub j_star: usize,
    /// `d_M(x̂, μ_{j*})` (§7.2).
    pub d_m: f64,
    /// `τ` from the artefact (§6.2 step 6).
    pub tau: f64,
    /// `d_M ≤ τ`.
    pub in_distribution: bool,
    /// Spawned groups with room (`2·k·n < 3·N`, §5.6), `(group, n, D)`, ascending by
    /// `(D, group-ID bytes)`; empty when in distribution.
    pub room: Vec<(GroupId, u64, f64)>,
    /// Where §7.3 sends it.
    pub destination: GroupId,
}

/// §7.3 for `x` against the frozen partition and the spawned groups, with `k` and `N` the
/// counters before this insert. Errors as the engine's (`WrongDimension`, `NonFinite`,
/// `NotNormalised`, `IntegrityViolation` for `q < 0`).
pub fn explain_route(
    art: &PartitionArtefact,
    x: &[f32],
    spawned: &[Spawned],
    big_n: u64,
    k: u64,
) -> Result<RouteExplanation, Error> {
    let q = sever_quant::quantise(x, art.d)?;
    let xhat = q.dequantise_f64();
    let mut d: Vec<(usize, f64)> = (0..art.k_frozen)
        .filter_map(|j| art.centroid(j).map(|mu| (j, sq_dist_f64(&xhat, mu))))
        .collect();
    // §7.1: ascending; a stable sort keeps the smaller label first on a tie.
    d.sort_by(|a, b| a.1.total_cmp(&b.1));
    let (j_star, _) = *d.first().ok_or(Error::IntegrityViolation {
        invariant: "§7.1 no frozen group",
    })?;
    let mu = art.centroid(j_star).ok_or(Error::IntegrityViolation {
        invariant: "§7.1 no frozen group",
    })?;
    let d_m = mahalanobis(&xhat, mu, &art.precision)?;
    let in_distribution = d_m <= art.tau;
    let frozen =
        u16::try_from(j_star)
            .ok()
            .and_then(GroupId::frozen)
            .ok_or(Error::IntegrityViolation {
                invariant: "§5.1 frozen label",
            })?;
    let mut room: Vec<(GroupId, u64, f64)> = Vec::new();
    if !in_distribution {
        room = spawned
            .iter()
            .filter(|g| 2 * k * g.n < 3 * big_n) // §5.6, exact integers
            .map(|g| (g.id, g.n, sq_dist_f64(&xhat, &g.centroid)))
            .collect();
        // §7.3: ties to the smaller group-ID bytes
        room.sort_by(|a, b| {
            a.2.total_cmp(&b.2)
                .then_with(|| a.0.as_text().as_bytes().cmp(b.0.as_text().as_bytes()))
        });
    }
    let destination = if in_distribution {
        frozen
    } else {
        room.first().map_or(GroupId::Holding, |r| r.0)
    };
    d.truncate(NEAREST);
    Ok(RouteExplanation {
        x_tilde: q.as_slice().to_vec(),
        nearest: d,
        j_star,
        d_m,
        tau: art.tau,
        in_distribution,
        room,
        destination,
    })
}

/// §8.1 steps 1–2 for a query.
#[derive(Clone, Debug, PartialEq)]
pub struct SearchExplanation {
    /// Every frozen and spawned group, `(group, D_g)`, in rank order.
    pub ranked: Vec<(GroupId, f64)>,
    /// `p = ⌈0.25·k⌉`: the first `p` are probed.
    pub probed: usize,
}

/// §8.1 steps 1–2: `groups` are every frozen and spawned group with its centre, empty ones too.
pub fn explain_search(query: &[f32], groups: &[(GroupId, Vec<f64>)]) -> SearchExplanation {
    let ranked = rank_groups(
        query,
        groups.iter().map(|(id, mu)| SearchGroup {
            id: *id,
            centroid: mu,
            ids: &[],
            rows: &[],
        }),
    );
    SearchExplanation {
        probed: probe_count(ranked.len()),
        ranked: ranked.into_iter().map(|(d, g)| (g.id, d)).collect(),
    }
}

#[cfg(test)]
mod tests;
