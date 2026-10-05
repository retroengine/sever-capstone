//! `sever-demo idea` (Build §4.9): build an index, delete one cohort, show that every touched group
//! is bit for bit the group of its survivors alone, and show the ghost the two baselines keep.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::time::Instant;

use serde::Serialize;
use sever_index::blob::{parse_blob, snapshot_from_members};
use sever_index::{
    DeleteRequest, GroupExtension, IndexConfig, InsertRequest, NoExtension, Outcome, Placement,
};
use sever_quant::QVec;
use sever_types::{Error, GroupId, RecordId};
use sha2::{Digest, Sha256};

use crate::data::{Dataset, DemoError};
use crate::ghost::{RunningMeanIndex, SoftDeleteIvf, compare_f32, running_mean_of};
use crate::root::{P1Index, new_index};

/// Results per query in the search step (the overview's top-10).
pub const TOP_K: usize = 10;

/// The whole run, written as JSON for the `sever_demo` renderer.
#[derive(Serialize)]
pub struct Report {
    /// Report format.
    pub format: &'static str,
    /// Data slice.
    pub data: String,
    /// Run seed (selects the artefact).
    pub seed: u64,
    /// Dimension.
    pub d: usize,
    /// SHA-256 of the partition artefact.
    pub artefact_sha256: String,
    /// §7.4 flush size.
    pub spawn_target: usize,
    /// How the stream was ordered.
    pub stream_order: &'static str,
    /// Step 1.
    pub build: BuildStats,
    /// Step 2.
    pub target: Target,
    /// Steps 3 and 5, one row per touched frozen or spawned group.
    pub groups: Vec<GroupRow>,
    /// The holding area before and after.
    pub holding: HoldingRow,
    /// Groups the deletion did not touch, compared before and after.
    pub untouched: Untouched,
    /// `N` before and after.
    pub big_n: [u64; 2],
    /// Step 4: the outcome of each deletion.
    pub outcomes: Vec<String>,
    /// E2E-1.5: deleting the cohort a second time.
    pub second_delete: SecondDelete,
    /// Step 6 and measure P1-T14.
    pub ghost: Ghost,
    /// Step 7.
    pub search: SearchReport,
    /// INV-4 … INV-9 after the deletion.
    pub invariants: String,
}

/// Global numbers after the stream (step 1).
#[derive(Serialize)]
pub struct BuildStats {
    /// Records streamed.
    pub records: usize,
    /// Records accepted.
    pub accepted: usize,
    /// Rejections by §17 error.
    pub rejected: BTreeMap<String, u64>,
    /// Frozen groups.
    pub frozen: u64,
    /// Spawned groups.
    pub spawned: u64,
    /// `N`.
    pub big_n: u64,
    /// `k`.
    pub k: u64,
    /// Holding area.
    pub holding: u64,
    /// Inserts judged out of distribution (§7.2).
    pub out_of_distribution: u64,
    /// Their share of accepted inserts.
    pub ood_rate: f64,
    /// Wall-clock seconds for the stream.
    pub seconds: f64,
}

/// The deleted cohort (step 2).
#[derive(Serialize)]
pub struct Target {
    /// Cohort title.
    pub cohort: String,
    /// Its records.
    pub record_ids: Vec<String>,
    /// Where they were (frozen and spawned groups, then `holding` if any were there).
    pub groups: Vec<String>,
    /// How it was chosen.
    pub rule: &'static str,
}

/// One touched group, before and after.
#[derive(Serialize)]
pub struct GroupRow {
    /// Group ID.
    pub group: String,
    /// `n` before.
    pub n_before: u64,
    /// `n` after.
    pub n_after: u64,
    /// SHA-256 of `S` (i64be) before.
    pub s_sha_before: String,
    /// SHA-256 of `S` after.
    pub s_sha_after: String,
    /// SHA-256 of the canonical blob before.
    pub blob_sha_before: String,
    /// SHA-256 of the canonical blob after.
    pub blob_sha_after: String,
    /// SHA-256 of the blob of the group rebuilt from its survivors' original vectors alone.
    pub survivors_blob_sha: String,
    /// The two blobs are byte-identical.
    pub exact: bool,
}

/// The holding area (§7.4): no accumulator, so a deletion there changes no sum.
#[derive(Serialize)]
pub struct HoldingRow {
    /// Records before.
    pub n_before: u64,
    /// Records after.
    pub n_after: u64,
    /// Cohort records that were there.
    pub cohort_members: u64,
}

/// Groups the deletion did not touch.
#[derive(Serialize)]
pub struct Untouched {
    /// How many.
    pub groups: usize,
    /// How many have the same blob hash after.
    pub unchanged: usize,
}

/// E2E-1.5.
#[derive(Serialize)]
pub struct SecondDelete {
    /// Every outcome was `AlreadyAbsent`.
    pub all_already_absent: bool,
    /// The whole-index state hash did not change.
    pub state_unchanged: bool,
}

/// Step 6 (P1-T14).
#[derive(Serialize)]
pub struct Ghost {
    /// Per touched group.
    pub per_group: Vec<GhostGroup>,
    /// The three-row comparison.
    pub summary: Vec<GhostSummary>,
}

/// One touched group in the three systems.
#[derive(Serialize)]
pub struct GhostGroup {
    /// Group ID.
    pub group: String,
    /// Soft-delete IVF: distance between its centroid and the survivors' mean.
    pub soft_delete_distance: f64,
    /// Float running mean: largest absolute difference from the survivors-only running mean.
    pub float_mean_max_abs_diff: f64,
    /// Float running mean: components whose bits differ.
    pub float_mean_components_differing: usize,
    /// SEVER: largest absolute difference between `S` and the survivors-only `S` (Q24 units).
    pub sever_max_abs_diff: u64,
}

/// One baseline row.
#[derive(Serialize)]
pub struct GhostSummary {
    /// System.
    pub system: &'static str,
    /// Whether a deleted record's vector is still stored.
    pub deleted_record_still_stored: bool,
    /// The largest summary difference over the touched groups.
    pub distance: f64,
    /// What `distance` is.
    pub measure: &'static str,
}

/// Step 7.
#[derive(Serialize)]
pub struct SearchReport {
    /// Real queries run before and after.
    pub queries: usize,
    /// Results per query.
    pub k: usize,
    /// Real queries whose top-k held a cohort record before the deletion.
    pub queries_hit_before: usize,
    /// Searches (real queries and each deleted record's own vector) that returned a deleted record
    /// after the deletion. Gate P1-T5: 0.
    pub deleted_returned_after: usize,
    /// One worked example.
    pub example: Option<SearchExample>,
}

/// A query that returned a deleted passage before, and its results after.
#[derive(Serialize)]
pub struct SearchExample {
    /// `nq query #i`, or `own vector of <id>` when no real query found the cohort.
    pub query: String,
    /// The deleted record it found.
    pub deleted_record: String,
    /// Its rank before (1-based).
    pub rank_before: usize,
    /// Top results before: `(record ID, score)`.
    pub before: Vec<(String, f32)>,
    /// Top results after.
    pub after: Vec<(String, f32)>,
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn error_kind(e: &Error) -> String {
    format!("{e:?}")
        .split([' ', '(', '{'])
        .next()
        .unwrap_or("")
        .to_owned()
}

/// `n`, SHA-256 of `S` and SHA-256 of the blob, read back from the canonical blob (§5.5).
fn view(ix: &P1Index, g: &GroupId) -> Result<(u64, String, String), DemoError> {
    let blob = ix
        .blob(g)
        .ok_or_else(|| DemoError(format!("no group {}", g.as_text())))?;
    let parsed = parse_blob(&blob, &<NoExtension as GroupExtension>::BLOB_MAGIC, 0)
        .map_err(|e| DemoError(format!("blob of {}: {e:?}", g.as_text())))?;
    let s_bytes: Vec<u8> = parsed.s.iter().flat_map(|v| v.to_be_bytes()).collect();
    Ok((
        parsed.n,
        hex(&Sha256::digest(&s_bytes)),
        hex(&Sha256::digest(&blob)),
    ))
}

fn s_of(ix: &P1Index, g: &GroupId) -> Vec<i64> {
    ix.blob(g)
        .and_then(|b| parse_blob(&b, &<NoExtension as GroupExtension>::BLOB_MAGIC, 0).ok())
        .map(|p| p.s)
        .unwrap_or_default()
}

fn all_blob_hashes(ix: &P1Index) -> BTreeMap<GroupId, String> {
    ix.group_ids()
        .into_iter()
        .filter_map(|g| ix.blob(&g).map(|b| (g, hex(&Sha256::digest(b)))))
        .collect()
}

fn state_hash(ix: &P1Index) -> String {
    let mut h = Sha256::new();
    for (g, b) in all_blob_hashes(ix) {
        h.update(g.as_text());
        h.update(b);
    }
    h.update(ix.group_len(&GroupId::Holding).unwrap_or(0).to_be_bytes());
    hex(&h.finalize())
}

fn row(ds: &Dataset, i: usize) -> Result<(&String, &[f32]), DemoError> {
    let id = ds
        .ids
        .get(i)
        .ok_or_else(|| DemoError("row out of range".into()))?;
    let x = ds
        .vector(i)
        .ok_or_else(|| DemoError("row out of range".into()))?;
    Ok((id, x))
}

fn top(ix: &P1Index, q: &[f32]) -> Result<Vec<(String, f32)>, DemoError> {
    Ok(sever_search::search(ix, q, TOP_K)?
        .into_iter()
        .map(|h| (h.record_id.as_str().to_owned(), h.score))
        .collect())
}

/// Runs the demo on `ds`.
pub fn run(ds: &Dataset) -> Result<Report, DemoError> {
    let d = ds.d;
    let n = ds.ids.len();
    let mut ix = new_index(
        &ds.artefact,
        IndexConfig {
            spawning_enabled: true,
            spawn_target: ds.spawn_target,
        },
    )?;

    // Step 1: build.
    let t0 = Instant::now();
    let mut accepted: Vec<usize> = Vec::with_capacity(n);
    let mut rejected: BTreeMap<String, u64> = BTreeMap::new();
    let mut ood = 0u64;
    for i in 0..n {
        let (id, x) = row(ds, i)?;
        let req = InsertRequest {
            record_id: id.clone(),
            vector: x.to_vec(),
            credential: (),
        };
        match ix.insert(req) {
            Ok(p) => {
                accepted.push(i);
                // §7.3: with spawning on, only an out-of-distribution insert leaves the frozen set.
                if !matches!(p, Placement::Frozen(_)) {
                    ood += 1;
                }
            }
            Err(e) => *rejected.entry(error_kind(&e)).or_default() += 1,
        }
    }
    let seconds = t0.elapsed().as_secs_f64();
    let st = ix.stats();
    let build = BuildStats {
        records: n,
        accepted: accepted.len(),
        rejected,
        frozen: st.frozen,
        spawned: st.spawned,
        big_n: st.big_n,
        k: st.k,
        holding: st.holding,
        out_of_distribution: ood,
        ood_rate: ood as f64 / accepted.len().max(1) as f64,
        seconds,
    };

    // Where every live record is, once (each lookup is one HMAC, §9.7).
    let locate = |ix: &P1Index| -> Result<HashMap<usize, GroupId>, DemoError> {
        let mut out = HashMap::new();
        for &i in &accepted {
            let (id, _) = row(ds, i)?;
            if let Some(g) = ix.location(id) {
                out.insert(i, g);
            }
        }
        Ok(out)
    };
    let loc_before = locate(&ix)?;

    // Step 2: the cohort touching the most frozen or spawned groups; then the largest; then the
    // first title by bytes.
    let mut by_cohort: BTreeMap<&str, Vec<usize>> = BTreeMap::new();
    for &i in &accepted {
        if let Some(c) = ds.cohorts.get(i) {
            by_cohort.entry(c.as_str()).or_default().push(i);
        }
    }
    let mut best: Option<(&str, &Vec<usize>, (usize, usize))> = None;
    for (c, rows) in &by_cohort {
        let groups: BTreeSet<&GroupId> = rows.iter().filter_map(|r| loc_before.get(r)).collect();
        let key = (
            groups.iter().filter(|g| ***g != GroupId::Holding).count(),
            rows.len(),
        );
        if best.is_none_or(|(_, _, k)| key > k) {
            best = Some((c, rows, key));
        }
    }
    let (cohort, cohort_rows, _) = best.ok_or_else(|| DemoError("no records".into()))?;
    let cohort_rows = cohort_rows.clone();
    let deleted_ids: Vec<String> = cohort_rows
        .iter()
        .map(|&i| row(ds, i).map(|(id, _)| id.clone()))
        .collect::<Result<_, _>>()?;
    let deleted_set: HashSet<&str> = deleted_ids.iter().map(String::as_str).collect();
    let touched: BTreeSet<GroupId> = cohort_rows
        .iter()
        .filter_map(|r| loc_before.get(r).copied())
        .collect();
    let touched_groups: Vec<GroupId> = touched
        .iter()
        .copied()
        .filter(|g| *g != GroupId::Holding)
        .collect();
    let in_holding = cohort_rows
        .iter()
        .filter(|r| loc_before.get(r) == Some(&GroupId::Holding))
        .count() as u64;

    // Step 3: before.
    let mut before = Vec::new();
    for g in &touched_groups {
        before.push(view(&ix, g)?);
    }
    let s_before_all = all_blob_hashes(&ix);
    let holding_before = ix.group_len(&GroupId::Holding).unwrap_or(0) as u64;
    let n_before = ix.stats().big_n;

    // Step 7 (before): real queries, then each deleted record's own vector.
    let nq = ds.n_queries();
    let mut results_before = Vec::with_capacity(nq);
    for q in 0..nq {
        let qv = ds.query(q).ok_or_else(|| DemoError("query".into()))?;
        results_before.push(top(&ix, qv)?);
    }
    let mut own_before = Vec::new();
    for &i in &cohort_rows {
        let (_, x) = row(ds, i)?;
        own_before.push(top(&ix, x)?);
    }

    // Step 6 (setup): the baselines get SEVER's membership, in stream order.
    let mut ivf = SoftDeleteIvf::default();
    let mut rm = RunningMeanIndex::default();
    for &i in &accepted {
        if let Some(g) = loc_before.get(&i) {
            let (id, x) = row(ds, i)?;
            ivf.insert(&g.as_text(), id, x);
            rm.insert(&g.as_text(), id, x);
        }
    }

    // Step 4: delete the cohort with one delete_user.
    let reqs: Vec<DeleteRequest> = deleted_ids
        .iter()
        .map(|id| DeleteRequest {
            record_id: id.clone(),
        })
        .collect();
    let outcomes: Vec<String> = ix
        .delete_many(reqs.clone())?
        .iter()
        .map(|o| match o {
            Outcome::Deleted { from } => format!("deleted from {}", from.as_text()),
            Outcome::AlreadyAbsent => "already absent".to_owned(),
            Outcome::Placed(_) => "placed".to_owned(),
        })
        .collect();
    for id in &deleted_ids {
        ivf.delete(id);
        rm.delete(id);
    }

    // Step 5: after, against the group rebuilt from its survivors' original vectors.
    let loc_after = locate(&ix)?;
    let mut survivors: HashMap<GroupId, Vec<usize>> = HashMap::new();
    for &i in &accepted {
        if let Some(g) = loc_after.get(&i) {
            survivors.entry(*g).or_default().push(i);
        }
    }
    let mut groups = Vec::new();
    let mut ghost_rows = Vec::new();
    for (g, (nb, sb, bb)) in touched_groups.iter().zip(before) {
        let (na, sa, ba) = view(&ix, g)?;
        let rows = survivors.get(g).cloned().unwrap_or_default();
        let mut members: Vec<(RecordId, QVec)> = Vec::with_capacity(rows.len());
        for &i in &rows {
            let (id, x) = row(ds, i)?;
            members.push((RecordId::new(id.clone())?, sever_quant::quantise(x, d)?));
        }
        let refs: Vec<(&RecordId, &QVec, &())> = members.iter().map(|(r, x)| (r, x, &())).collect();
        let snap = snapshot_from_members(&NoExtension, d, &refs);
        let survivors_blob_sha = hex(&Sha256::digest(&snap.blob));
        let s_now = s_of(&ix, g);
        let sever_max_abs_diff = s_now
            .iter()
            .zip(&snap.s)
            .map(|(a, b)| a.abs_diff(*b))
            .max()
            .unwrap_or(0);
        let gt = g.as_text();
        let (fm_max, fm_diff) = compare_f32(
            rm.mean(&gt).unwrap_or(&[]),
            &running_mean_of(rows.iter().filter_map(|&i| ds.vector(i)), d),
        );
        ghost_rows.push(GhostGroup {
            group: gt.clone(),
            soft_delete_distance: ivf.summary_distance(&gt, d),
            float_mean_max_abs_diff: fm_max,
            float_mean_components_differing: fm_diff,
            sever_max_abs_diff,
        });
        groups.push(GroupRow {
            group: gt,
            n_before: nb,
            n_after: na,
            s_sha_before: sb,
            s_sha_after: sa,
            blob_sha_before: bb,
            exact: ba == survivors_blob_sha,
            blob_sha_after: ba,
            survivors_blob_sha,
        });
    }
    let s_after_all = all_blob_hashes(&ix);
    let untouched_ids: Vec<&GroupId> = s_before_all
        .keys()
        .filter(|g| !touched.contains(*g))
        .collect();
    let untouched = Untouched {
        groups: untouched_ids.len(),
        unchanged: untouched_ids
            .iter()
            .filter(|g| s_before_all.get(**g) == s_after_all.get(**g))
            .count(),
    };

    // Step 7 (after).
    let mut deleted_returned_after = 0;
    let mut results_after = Vec::with_capacity(nq);
    for q in 0..nq {
        let qv = ds.query(q).ok_or_else(|| DemoError("query".into()))?;
        let r = top(&ix, qv)?;
        deleted_returned_after +=
            usize::from(r.iter().any(|(id, _)| deleted_set.contains(id.as_str())));
        results_after.push(r);
    }
    let mut own_after = Vec::new();
    for &i in &cohort_rows {
        let (_, x) = row(ds, i)?;
        let r = top(&ix, x)?;
        deleted_returned_after +=
            usize::from(r.iter().any(|(id, _)| deleted_set.contains(id.as_str())));
        own_after.push(r);
    }
    let hit = |r: &Vec<(String, f32)>| {
        r.iter()
            .position(|(id, _)| deleted_set.contains(id.as_str()))
    };
    let queries_hit_before = results_before.iter().filter(|r| hit(r).is_some()).count();
    let example = results_before
        .iter()
        .zip(&results_after)
        .enumerate()
        .find_map(|(q, (b, a))| hit(b).map(|rank| (format!("nq query #{q}"), rank, b, a)))
        .or_else(|| {
            own_before
                .iter()
                .zip(&own_after)
                .zip(&deleted_ids)
                .find_map(|((b, a), id)| {
                    hit(b).map(|rank| (format!("own vector of {id}"), rank, b, a))
                })
        })
        .and_then(|(query, rank, b, a)| {
            b.get(rank).map(|(id, _)| SearchExample {
                query,
                deleted_record: id.clone(),
                rank_before: rank + 1,
                before: b.clone(),
                after: a.clone(),
            })
        });

    // E2E-1.5: a second deletion of the same cohort changes nothing.
    let hash_before_second = state_hash(&ix);
    let second = ix.delete_many(reqs)?;
    let second_delete = SecondDelete {
        all_already_absent: second.iter().all(|o| *o == Outcome::AlreadyAbsent),
        state_unchanged: state_hash(&ix) == hash_before_second,
    };

    let invariants = match ix.check_invariants() {
        Ok(()) => "ok".to_owned(),
        Err(e) => format!("FAILED: {e}"),
    };
    let soft_max = ghost_rows
        .iter()
        .map(|r| r.soft_delete_distance)
        .fold(0.0, f64::max);
    let fm_max = ghost_rows
        .iter()
        .map(|r| r.float_mean_max_abs_diff)
        .fold(0.0, f64::max);
    let sever_max = ghost_rows
        .iter()
        .map(|r| r.sever_max_abs_diff)
        .max()
        .unwrap_or(0);
    let ghost = Ghost {
        summary: vec![
            GhostSummary {
                system: "soft-delete IVF",
                deleted_record_still_stored: deleted_ids.iter().any(|id| ivf.still_stored(id)),
                distance: soft_max,
                measure: "L2 distance, centroid to survivors' mean",
            },
            GhostSummary {
                system: "float running mean",
                deleted_record_still_stored: false,
                distance: fm_max,
                measure: "max abs difference from the survivors-only running mean",
            },
            GhostSummary {
                system: "SEVER (Part 1)",
                deleted_record_still_stored: false,
                distance: sever_max as f64,
                measure: "max abs difference of S from the survivors-only S (0 = bit-identical)",
            },
        ],
        per_group: ghost_rows,
    };

    Ok(Report {
        format: "sever-demo-idea-1",
        data: ds.name.clone(),
        seed: ds.seed,
        d,
        artefact_sha256: ds.artefact_sha256.clone(),
        spawn_target: ds.spawn_target,
        stream_order: ds.stream_order,
        build,
        target: Target {
            cohort: cohort.to_owned(),
            record_ids: deleted_ids,
            groups: touched.iter().map(GroupId::as_text).collect(),
            rule: "most frozen or spawned groups touched, then most records, then first title by bytes",
        },
        groups,
        holding: HoldingRow {
            n_before: holding_before,
            n_after: ix.group_len(&GroupId::Holding).unwrap_or(0) as u64,
            cohort_members: in_holding,
        },
        untouched,
        big_n: [n_before, ix.stats().big_n],
        outcomes,
        second_delete,
        ghost,
        search: SearchReport {
            queries: nq,
            k: TOP_K,
            queries_hit_before,
            deleted_returned_after,
            example,
        },
        invariants,
    })
}
