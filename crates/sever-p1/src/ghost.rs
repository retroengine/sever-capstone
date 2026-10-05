//! The two "ghost" baselines of the demo (Build §4.9 step 6) and measure P1-T14: how far each
//! baseline's group summary remains from the summary of the survivors alone after a deletion.
//!
//! Both work on the original float32 vectors, as conventional vector indexes do, and are given the
//! same group membership as SEVER so that only the deletion mechanism differs.

use std::collections::HashMap;

/// A conventional IVF index that deletes by tombstone: the record stays in its posting list and the
/// centroid (the mean of everything ever inserted) keeps its contribution.
#[derive(Default)]
pub struct SoftDeleteIvf {
    lists: HashMap<String, Vec<Posting>>,
}

struct Posting {
    id: String,
    x: Vec<f32>,
    deleted: bool,
}

/// A float index that keeps a running mean per group and subtracts on deletion.
#[derive(Default)]
pub struct RunningMeanIndex {
    groups: HashMap<String, MeanAcc>,
    members: HashMap<String, (String, Vec<f32>)>,
}

struct MeanAcc {
    n: u64,
    mean: Vec<f32>,
}

fn mean_f64<'a>(rows: impl Iterator<Item = &'a [f32]>, d: usize) -> Vec<f64> {
    let mut sum = vec![0.0f64; d];
    let mut n = 0u64;
    for x in rows {
        for (s, &v) in sum.iter_mut().zip(x) {
            *s += f64::from(v);
        }
        n += 1;
    }
    if n > 0 {
        for s in &mut sum {
            *s /= n as f64;
        }
    }
    sum
}

impl SoftDeleteIvf {
    /// Appends a record to `group`'s posting list.
    pub fn insert(&mut self, group: &str, id: &str, x: &[f32]) {
        self.lists
            .entry(group.to_owned())
            .or_default()
            .push(Posting {
                id: id.to_owned(),
                x: x.to_vec(),
                deleted: false,
            });
    }

    /// Marks a record deleted. Returns whether it was found.
    pub fn delete(&mut self, id: &str) -> bool {
        for list in self.lists.values_mut() {
            if let Some(p) = list.iter_mut().find(|p| p.id == id && !p.deleted) {
                p.deleted = true;
                return true;
            }
        }
        false
    }

    /// Whether a deleted record's vector is still stored.
    pub fn still_stored(&self, id: &str) -> bool {
        self.lists
            .values()
            .any(|l| l.iter().any(|p| p.id == id && p.deleted))
    }

    /// Euclidean distance between the group's centroid (mean of every record ever inserted) and the
    /// mean of its live records.
    pub fn summary_distance(&self, group: &str, d: usize) -> f64 {
        let Some(list) = self.lists.get(group) else {
            return 0.0;
        };
        let all = mean_f64(list.iter().map(|p| p.x.as_slice()), d);
        let live = mean_f64(
            list.iter().filter(|p| !p.deleted).map(|p| p.x.as_slice()),
            d,
        );
        all.iter()
            .zip(&live)
            .map(|(a, b)| (a - b) * (a - b))
            .sum::<f64>()
            .sqrt()
    }
}

/// `mean ← mean + (x − mean)/n`, in float32.
fn running_add(acc: &mut MeanAcc, x: &[f32]) {
    acc.n += 1;
    let n = acc.n as f32;
    for (m, &v) in acc.mean.iter_mut().zip(x) {
        *m += (v - *m) / n;
    }
}

impl RunningMeanIndex {
    /// Adds a record to `group`'s running mean.
    pub fn insert(&mut self, group: &str, id: &str, x: &[f32]) {
        let acc = self.groups.entry(group.to_owned()).or_insert(MeanAcc {
            n: 0,
            mean: vec![0.0; x.len()],
        });
        running_add(acc, x);
        self.members
            .insert(id.to_owned(), (group.to_owned(), x.to_vec()));
    }

    /// Subtracts a record: `mean ← (n·mean − x)/(n − 1)`, in float32. Returns whether it was found.
    pub fn delete(&mut self, id: &str) -> bool {
        let Some((group, x)) = self.members.remove(id) else {
            return false;
        };
        if let Some(acc) = self.groups.get_mut(&group) {
            let n = acc.n as f32;
            acc.n -= 1;
            for (m, &v) in acc.mean.iter_mut().zip(&x) {
                *m = if acc.n == 0 {
                    0.0
                } else {
                    (n * *m - v) / (n - 1.0)
                };
            }
        }
        true
    }

    /// The group's current mean.
    pub fn mean(&self, group: &str) -> Option<&[f32]> {
        self.groups.get(group).map(|a| a.mean.as_slice())
    }
}

/// The survivors-only reference for the running-mean baseline: the same float32 running mean over
/// the surviving records alone, in their insertion order ("as if never inserted").
pub fn running_mean_of<'a>(rows: impl Iterator<Item = &'a [f32]>, d: usize) -> Vec<f32> {
    let mut acc = MeanAcc {
        n: 0,
        mean: vec![0.0; d],
    };
    for x in rows {
        running_add(&mut acc, x);
    }
    acc.mean
}

/// The largest absolute componentwise difference, and how many components differ in their bits.
pub fn compare_f32(a: &[f32], b: &[f32]) -> (f64, usize) {
    let max = a
        .iter()
        .zip(b)
        .map(|(x, y)| (f64::from(*x) - f64::from(*y)).abs())
        .fold(0.0, f64::max);
    let differing = a
        .iter()
        .zip(b)
        .filter(|(x, y)| x.to_bits() != y.to_bits())
        .count();
    (max, differing)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rows() -> Vec<Vec<f32>> {
        (0..7u8)
            .map(|i| {
                (0..8u8)
                    .map(|j| f32::from(i * 8 + j).sin() * 0.37)
                    .collect()
            })
            .collect()
    }

    #[test]
    fn p1_ghost_soft_delete_keeps_the_record_and_its_contribution() {
        let r = rows();
        let mut ivf = SoftDeleteIvf::default();
        for (i, x) in r.iter().enumerate() {
            ivf.insert("g", &format!("r{i}"), x);
        }
        assert!(ivf.summary_distance("g", 8) < 1e-12);
        assert!(ivf.delete("r3"));
        assert!(ivf.still_stored("r3"));
        assert!(ivf.summary_distance("g", 8) > 1e-3);
        assert!(!ivf.delete("r3"));
    }

    #[test]
    fn p1_ghost_running_mean_drifts_from_the_survivors_mean() {
        let r = rows();
        let mut ix = RunningMeanIndex::default();
        for (i, x) in r.iter().enumerate() {
            ix.insert("g", &format!("r{i}"), x);
        }
        assert!(ix.delete("r2"));
        assert!(!ix.delete("r2"));
        let survivors = running_mean_of(
            r.iter()
                .enumerate()
                .filter(|(i, _)| *i != 2)
                .map(|(_, x)| x.as_slice()),
            8,
        );
        let (max, differing) = compare_f32(ix.mean("g").unwrap_or(&[]), &survivors);
        // The subtraction is not the inverse of the additions in float32: some bits differ.
        assert!(differing > 0, "max {max}");
        assert!(max > 0.0);
    }

    #[test]
    fn p1_ghost_running_mean_empties_to_zero() {
        let mut ix = RunningMeanIndex::default();
        ix.insert("g", "a", &[0.5, -0.25]);
        assert!(ix.delete("a"));
        assert_eq!(ix.mean("g"), Some([0.0f32, 0.0].as_slice()));
    }
}
