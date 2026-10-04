//! `sever-search`: IVF-flat search over the index's float32 mirror (Part 1, Build §4.4; spec §8).
//!
//! Rank every frozen and spawned group by centroid distance, scan the closest `⌈0.25·k⌉` (empty
//! groups count), score with the pinned kernel, return the `k` best. Results are approximate;
//! deletion is exact. Searching never writes (§15.5). No file I/O, clock or randomness here.

pub mod kernel;

#[cfg(test)]
mod tests;

use sever_index::{GroupExtension, IdScrambler, Index, SearchGroup};
use sever_types::{Error, GroupId, RecordId};

use crate::route_dist::sq_dist_f64;

mod route_dist {
    /// `Σ_i ((f64)q_i − μ_i)²` in float64, sequential from `i = 0` (§8.1 step 1).
    pub fn sq_dist_f64(q: &[f32], mu: &[f64]) -> f64 {
        let mut sum = 0.0_f64;
        for (a, m) in q.iter().zip(mu) {
            let t = f64::from(*a) - m;
            sum += t * t;
        }
        sum
    }
}

/// One search result.
#[derive(Clone, Debug, PartialEq)]
pub struct Hit {
    /// The record.
    pub record_id: RecordId,
    /// Its §8.2 score (squared Euclidean distance in float32; smaller is closer).
    pub score: f32,
}

/// §8.1 step 2: `p = ⌈0.25·k⌉` groups.
pub fn probe_count(k: usize) -> usize {
    k.div_ceil(4)
}

/// §8.1 step 1: frozen and spawned groups sorted ascending by `(D_g, group-ID bytes)`.
pub fn rank_groups<'a>(
    query: &[f32],
    groups: impl Iterator<Item = SearchGroup<'a>>,
) -> Vec<(f64, SearchGroup<'a>)> {
    let mut ranked: Vec<(f64, SearchGroup<'a>)> = groups
        .map(|g| (sq_dist_f64(query, g.centroid), g))
        .collect();
    ranked.sort_by(|(da, a), (db, b)| da.total_cmp(db).then_with(|| a.id.cmp(&b.id)));
    ranked
}

/// §8.1: the `k_results` nearest records to `query` (§15.5: shared access only).
pub fn search<E: GroupExtension, S: IdScrambler>(
    index: &Index<E, S>,
    query: &[f32],
    k_results: usize,
) -> Result<Vec<Hit>, Error> {
    let d = index.d();
    sever_quant::check_normalised(query, d)?; // §8.1 input: checked per §4.1 steps 0–3
    let ranked = rank_groups(query, index.search_groups());
    // §8.1 step 2: the budget counts every frozen and spawned group, empty ones included.
    // SB-6: skip empty groups when filling it.
    let candidates: Vec<&SearchGroup<'_>> = ranked
        .iter()
        .map(|(_, g)| g)
        .filter(|g| !cfg!(feature = "sabotage-SB-6") || !g.ids.is_empty())
        .collect();
    let p = probe_count(ranked.len());
    // §8.1 step 3: score every member of every probed group.
    let mut scored: Vec<(f32, &RecordId)> = Vec::new();
    for g in candidates.into_iter().take(p) {
        for (row, id) in g.rows.chunks_exact(d).zip(g.ids) {
            scored.push((kernel::score(query, row), id));
        }
    }
    // §8.1 step 4: smallest scores, ties by record-ID bytes.
    scored.sort_by(|(sa, ia), (sb, ib)| {
        sa.total_cmp(sb)
            .then_with(|| ia.as_bytes().cmp(ib.as_bytes()))
    });
    Ok(scored
        .into_iter()
        .take(k_results)
        .map(|(score, id)| Hit {
            record_id: id.clone(),
            score,
        })
        .collect())
}

/// The probed groups for `query`, in rank order (for the demo and the differential traces).
pub fn probed_groups<E: GroupExtension, S: IdScrambler>(
    index: &Index<E, S>,
    query: &[f32],
) -> Vec<GroupId> {
    let ranked = rank_groups(query, index.search_groups());
    let p = probe_count(ranked.len());
    ranked.into_iter().take(p).map(|(_, g)| g.id).collect()
}
