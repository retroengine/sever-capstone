//! The float arithmetic of routing (spec §7.1–7.2), in the pinned orders.
//!
//! Every sum is a plain sequential loop from index 0, with the multiply and the add as separate
//! IEEE operations: Rust never contracts `a + b * c` into a fused multiply-add on its own, so these
//! produce the same bits as the reference model's `np.cumsum(...)[..., -1]`.

use sever_types::Error;

/// `Σ_i (a_i − b_i)²` in float64, sequential from `i = 0` (§7.1, §7.3, §8.1).
pub fn sq_dist_f64(a: &[f64], b: &[f64]) -> f64 {
    let mut sum = 0.0_f64;
    for (x, y) in a.iter().zip(b) {
        let t = x - y;
        sum += t * t;
    }
    sum
}

/// §7.2: `d_M = sqrt(q)` with `δ = x̂ − μ`, `y_a = Σ_b P[a][b]·δ_b` (sequential in b),
/// `q = Σ_a δ_a·y_a` (sequential in a). `precision` is `P`, row-major, `d × d`.
pub fn mahalanobis(xhat: &[f64], mu: &[f64], precision: &[f64]) -> Result<f64, Error> {
    let delta: Vec<f64> = xhat.iter().zip(mu).map(|(x, m)| x - m).collect();
    let mut q = 0.0_f64;
    for (row, &delta_a) in precision.chunks_exact(delta.len()).zip(&delta) {
        let mut y = 0.0_f64;
        for (p, d) in row.iter().zip(&delta) {
            y += p * d;
        }
        q += delta_a * y;
    }
    // §7.2: P is positive definite, so q < 0 means the state is corrupt.
    if q < 0.0 {
        return Err(Error::IntegrityViolation {
            invariant: "§7.2 q < 0",
        });
    }
    Ok(q.sqrt())
}
