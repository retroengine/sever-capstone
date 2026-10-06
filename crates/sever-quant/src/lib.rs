//! `sever-quant`: the normalisation check, Q24 quantisation and dequantisation (Part 1, Build §4.4;
//! spec §4.1–4.3).
//!
//! The only way to get a quantised vector ([`QVec`]) from floats is [`quantise`], which runs the
//! §4.1 check first: there is no bypass (INV-1). The application backend's SDK uses this same
//! quantiser, because it builds `C_t` from `x̃` (§4.2).
//!
//! No file I/O, clock or randomness here (CLAUDE.md §7).

use sever_types::Error;
use sever_types::constants::{MAX_ABS_QUANTISED, NORM_TOLERANCE, SCALE};

/// `2^24` as a float64. Converting it is exact.
const SCALE_F64: f64 = SCALE as f64;

/// §4.1: checks a float32 vector against dimension `d`, in the spec's step order.
///
/// 0. exactly `d` components, else `WrongDimension`;
/// 1. every component finite, else `NonFinite`;
/// 2. `norm = sqrt(Σ (f64)x_i²)` in float64, summed sequentially from `i = 0`;
/// 3. `|norm − 1| ≤ 8 · 2^−23`, else `NotNormalised`.
///
/// The check validates normalisation and never performs it (CLAUDE.md §7).
pub fn check_normalised(x: &[f32], d: usize) -> Result<(), Error> {
    // §4.1 step 0 (DB-60): the dimension, before anything is read.
    if x.len() != d {
        return Err(Error::WrongDimension);
    }
    // §4.1 step 1: every component finite.
    if !x.iter().all(|v| v.is_finite()) {
        return Err(Error::NonFinite);
    }
    // §4.1 step 2: float64, sequential from i = 0. f32 → f64 is exact, and the square of a 24-bit
    // significand fits f64's 53 bits, so the only roundings are the additions, in this order.
    // (Rust never fuses `a + b * c` into an FMA on its own.)
    let mut sum = 0.0_f64;
    for &v in x {
        let w = f64::from(v);
        sum += w * w;
    }
    let norm = sum.sqrt();
    // §4.1 step 3: the 8-ULP tolerance.
    if (norm - 1.0).abs() <= NORM_TOLERANCE {
        Ok(())
    } else {
        Err(Error::NotNormalised)
    }
}

/// §4.2: one component, `round_half_to_even((f64)x · 2^24)`.
///
/// Both the widening and the multiplication by a power of two are exact, so the rounding is the
/// only inexact step. Callers that are not [`quantise`] are tests and golden vectors: a stored
/// vector must come through [`quantise`] (INV-1).
pub fn quantise_component(x: f32) -> i64 {
    // `as i64` saturates; for any |x| ≤ 2^39 the value is exact, far beyond the §4.2 bound.
    (f64::from(x) * SCALE_F64).round_ties_even() as i64
}

/// A quantised vector `x̃` (§4.2), stored as `i32`.
///
/// Every value satisfies `|x̃_i| ≤ 2^24 + 16` (§4.2 bound, Appendix A).
#[derive(Clone, PartialEq, Eq, Hash)]
pub struct QVec(Box<[i32]>);

/// §4.2 then §4.1: check, then quantise. The only path from floats to a [`QVec`] (INV-1).
pub fn quantise(x: &[f32], d: usize) -> Result<QVec, Error> {
    check_normalised(x, d)?;
    let mut out = Vec::with_capacity(d);
    for &v in x {
        // §4.2 bound: after the check, |x_i| ≤ norm ≤ 1 + 8·2^−23, so |x̃_i| ≤ 2^24 + 16 < 2^31.
        // `try_from` turns a violated bound into an error instead of a wrapped value.
        let q = i32::try_from(quantise_component(v)).map_err(|_| Error::IntegrityViolation {
            invariant: "INV-1 (§4.2 bound)",
        })?;
        out.push(q);
    }
    Ok(QVec(out.into_boxed_slice()))
}

impl QVec {
    /// Rebuilds a vector that was quantised earlier and stored (for example read back from a WAL
    /// or storage checkpoint in Part 2). Checks the dimension and the §4.2 bound; it cannot check
    /// that the values came from [`quantise`], so it is only for bytes this engine wrote itself.
    pub fn from_stored(values: Vec<i32>, d: usize) -> Result<Self, Error> {
        if values.len() != d {
            return Err(Error::WrongDimension);
        }
        if values
            .iter()
            .any(|&v| i64::from(v).abs() > MAX_ABS_QUANTISED)
        {
            return Err(Error::IntegrityViolation {
                invariant: "INV-1 (§4.2 bound)",
            });
        }
        Ok(Self(values.into_boxed_slice()))
    }

    /// The integers `x̃_0 … x̃_{d−1}`.
    pub fn as_slice(&self) -> &[i32] {
        &self.0
    }

    /// The dimension `d`.
    pub fn dim(&self) -> usize {
        self.0.len()
    }

    /// §4.3: `x̂_i = x̃_i / 2^24` in float64, exact. Used for routing (§7).
    pub fn dequantise_f64(&self) -> Vec<f64> {
        self.0
            .iter()
            .map(|&v| dequantise_component_f64(v))
            .collect()
    }

    /// §4.3: `x̂_i` as float32, exact whenever `|x̃_i| ≤ 2^24`, otherwise rounded to nearest even.
    /// Used for the search mirror (§8, §12.6).
    pub fn dequantise_f32(&self) -> Vec<f32> {
        self.0
            .iter()
            .map(|&v| dequantise_component_f32(v))
            .collect()
    }
}

impl core::fmt::Debug for QVec {
    // §17: a vector value never appears in printed output.
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "QVec(<redacted, d = {}>)", self.0.len())
    }
}

/// §4.3, one component in float64: exact (an `i32` has at most 31 significant bits).
pub fn dequantise_component_f64(v: i32) -> f64 {
    f64::from(v) / SCALE_F64
}

/// §4.3, one component in float32: the exact float64 value rounded once to nearest even.
pub fn dequantise_component_f32(v: i32) -> f32 {
    dequantise_component_f64(v) as f32
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;
    use sever_spec::spec;

    /// A d-vector with `a` in component 0 and zeros elsewhere: its norm is exactly |a|.
    fn axis(a: f32, d: usize) -> Vec<f32> {
        let mut x = vec![0.0_f32; d];
        x[0] = a;
        x
    }

    /// 1 + n·2^−23 (n float32 ULPs above 1.0).
    fn above(n: i32) -> f32 {
        1.0 + n as f32 * f32::EPSILON
    }

    /// 1 − n·2^−24 (n float32 ULPs below 1.0, where the spacing halves).
    fn below(n: i32) -> f32 {
        1.0 - n as f32 * (f32::EPSILON / 2.0)
    }

    // step 0: wrong length is WrongDimension, checked before anything else.
    #[spec("SR-4.1-0")]
    #[test]
    fn p1_quant_wrong_dimension_is_rejected_first() {
        assert_eq!(
            check_normalised(&axis(1.0, 15), 16),
            Err(Error::WrongDimension)
        );
        assert_eq!(
            check_normalised(&axis(1.0, 17), 16),
            Err(Error::WrongDimension)
        );
        assert_eq!(check_normalised(&[], 16), Err(Error::WrongDimension));
        // A NaN in a wrong-length vector still reports the dimension: step 0 runs first.
        assert_eq!(
            check_normalised(&[f32::NAN; 3], 16),
            Err(Error::WrongDimension)
        );
    }

    // NaN, +inf and −inf are rejected anywhere in the vector.
    #[spec("SR-4.1-1")]
    #[test]
    fn p1_quant_non_finite_is_rejected() {
        for bad in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY] {
            for pos in [0, 7, 15] {
                let mut x = axis(1.0, 16);
                x[pos] = bad;
                assert_eq!(
                    check_normalised(&x, 16),
                    Err(Error::NonFinite),
                    "{bad} at {pos}"
                );
            }
        }
    }

    // the tolerance boundary, exactly at ±8 ULPs and one ULP beyond (Build §4.7).
    #[spec("SR-4.1-3")]
    #[test]
    fn p1_quant_tolerance_boundaries() {
        // Above 1.0 the float32 spacing is 2^−23: 8 steps is exactly the tolerance.
        assert_eq!(check_normalised(&axis(above(8), 16), 16), Ok(()));
        assert_eq!(
            check_normalised(&axis(above(9), 16), 16),
            Err(Error::NotNormalised)
        );
        // Below 1.0 the spacing is 2^−24: the same distance, 8·2^−23, is 16 steps.
        assert_eq!(check_normalised(&axis(below(16), 16), 16), Ok(()));
        assert_eq!(
            check_normalised(&axis(below(17), 16), 16),
            Err(Error::NotNormalised)
        );
        // A negative component counts by its square.
        assert_eq!(check_normalised(&axis(-above(8), 16), 16), Ok(()));
        // Far off: zero vector and a doubled vector.
        assert_eq!(
            check_normalised(&axis(0.0, 16), 16),
            Err(Error::NotNormalised)
        );
        assert_eq!(
            check_normalised(&axis(2.0, 16), 16),
            Err(Error::NotNormalised)
        );
    }

    // the norm is a float64 sum: a vector whose float32 sum of squares would
    // round away from 1 still passes, because the check never computes in float32.
    #[spec("SR-4.1-2")]
    #[test]
    fn p1_quant_norm_is_summed_in_f64_sequentially() {
        let d = 384;
        let c = (1.0_f64 / d as f64).sqrt() as f32;
        let x = vec![c; d];
        let f64_norm = x
            .iter()
            .map(|&v| f64::from(v) * f64::from(v))
            .sum::<f64>()
            .sqrt();
        assert!((f64_norm - 1.0).abs() <= NORM_TOLERANCE);
        assert_eq!(check_normalised(&x, d), Ok(()));
    }

    // golden vector 5 (Appendix B), produced independently by NumPy.
    #[spec("SR-4.2-1")]
    #[test]
    fn p1_quant_golden_half_steps_round_to_even() {
        let doc: serde_json::Value =
            serde_json::from_str(include_str!("../../../golden/p1_quant_half_steps.json")).unwrap();
        let rows = doc["rows"].as_array().unwrap();
        assert!(rows.len() >= 30);
        for row in rows {
            let bits = u32::from_str_radix(row["x_f32_bits"].as_str().unwrap(), 16).unwrap();
            let x = f32::from_bits(bits);
            let want = row["q"].as_i64().unwrap();
            assert_eq!(quantise_component(x), want, "x = {x:e}");
        }
    }

    // ties to even, by hand: ±0.5 → 0, 1.5 → 2, 2.5 → 2, −2.5 → −2, 3.5 → 4.
    #[spec("SR-4.2-1")]
    #[test]
    fn p1_quant_ties_to_even_by_hand() {
        let half = |k2: i32| k2 as f32 / (1 << 25) as f32; // k2 / 2^25, so x · 2^24 = k2 / 2
        assert_eq!(quantise_component(half(1)), 0);
        assert_eq!(quantise_component(half(-1)), 0);
        assert_eq!(quantise_component(half(3)), 2);
        assert_eq!(quantise_component(half(5)), 2);
        assert_eq!(quantise_component(half(-5)), -2);
        assert_eq!(quantise_component(half(7)), 4);
    }

    // the bound |x̃| ≤ 2^24 + 16 is reached exactly at the tolerance edge.
    #[spec("SR-4.2-2")]
    #[test]
    fn p1_quant_bound_is_reached_at_tolerance_edge() {
        let q = quantise(&axis(above(8), 16), 16).unwrap();
        assert_eq!(i64::from(q.as_slice()[0]), MAX_ABS_QUANTISED);
        let q = quantise(&axis(-above(8), 16), 16).unwrap();
        assert_eq!(i64::from(q.as_slice()[0]), -MAX_ABS_QUANTISED);
    }

    // INV-1 — quantise refuses what the check refuses: no bypass.
    #[spec("SR-4.1-3")]
    #[test]
    fn p1_quant_quantise_runs_the_check() {
        assert_eq!(quantise(&axis(2.0, 16), 16), Err(Error::NotNormalised));
        assert_eq!(quantise(&axis(f32::NAN, 16), 16), Err(Error::NonFinite));
        assert_eq!(quantise(&axis(1.0, 8), 16), Err(Error::WrongDimension));
    }

    // dequantisation: exact in f64; f32 exact up to 2^24 and rounded to
    // nearest even above it.
    #[spec("SR-4.3-1", "SR-4.3-2")]
    #[test]
    fn p1_quant_dequantise() {
        assert_eq!(dequantise_component_f64(1 << 24), 1.0);
        assert_eq!(dequantise_component_f64(-(1 << 23)), -0.5);
        assert_eq!(
            dequantise_component_f64(16_777_233),
            1.0 + 17.0 / 16_777_216.0
        );
        assert_eq!(dequantise_component_f32(1 << 24), 1.0);
        // 2^24 + 1 is not a float32 at scale 1: 1 + 2^−24 rounds to even, i.e. to 1.0.
        assert_eq!(dequantise_component_f32((1 << 24) + 1), 1.0);
        // 2^24 + 3 → 1 + 3·2^−24 lies between 1 + 2^−23 and 1 + 2^−22: ties to 1 + 2^−22.
        assert_eq!(
            dequantise_component_f32((1 << 24) + 3),
            1.0 + 2.0 * f32::EPSILON
        );
        assert_eq!(dequantise_component_f32((1 << 24) + 16), above(8));
    }

    // INV-1 — stored values are bounds-checked when read back.
    #[test]
    fn p1_quant_from_stored_checks_dimension_and_bound() {
        assert!(QVec::from_stored(vec![16_777_232, -16_777_232], 2).is_ok());
        assert_eq!(QVec::from_stored(vec![0; 3], 3).map(|v| v.dim()), Ok(3));
        assert!(matches!(
            QVec::from_stored(vec![16_777_233, 0], 2),
            Err(Error::IntegrityViolation { .. })
        ));
        assert_eq!(QVec::from_stored(vec![0; 3], 2), Err(Error::WrongDimension));
    }

    // spec §17 — a vector's values never appear in printed output.
    #[test]
    fn p1_quant_debug_is_redacted() {
        let q = quantise(&axis(1.0, 16), 16).unwrap();
        assert_eq!(format!("{q:?}"), "QVec(<redacted, d = 16>)");
    }

    /// A random unit vector in float32, normalised in float64 then rounded (as an encoder would).
    fn unit_vector(d: usize) -> impl Strategy<Value = Vec<f32>> {
        proptest::collection::vec(-1.0_f64..1.0, d).prop_filter_map("non-zero", |v| {
            let n = v.iter().map(|a| a * a).sum::<f64>().sqrt();
            (n > 1e-3).then(|| v.iter().map(|a| (a / n) as f32).collect())
        })
    }

    proptest! {
        // properly normalised float32 vectors (d = 384) always pass.
        #[spec("SR-4.1-3")]
        #[test]
        fn p1_quant_prop_unit_vectors_pass(x in unit_vector(384)) {
            prop_assert_eq!(check_normalised(&x, 384), Ok(()));
        }

        // round trip within half a step, bound respected,
        // deterministic.
        #[spec("SR-4.2-1", "SR-4.2-2", "SR-4.3-1")]
        #[test]
        fn p1_quant_prop_round_trip_within_half_step(x in unit_vector(64)) {
            let q = quantise(&x, 64).unwrap();
            prop_assert_eq!(&q, &quantise(&x, 64).unwrap());
            for (&orig, back) in x.iter().zip(q.dequantise_f64()) {
                prop_assert!((f64::from(orig) - back).abs() <= 0.5 / SCALE_F64);
            }
            prop_assert!(q.as_slice().iter().all(|&v| i64::from(v).abs() <= MAX_ABS_QUANTISED));
        }
    }

    // Stored x̃ read back (Part 2 loads it): the length must be d and every value within the §4.2
    // bound, otherwise the stored state is corrupt.
    #[spec("SR-4.2-2")]
    #[test]
    fn p1_quant_from_stored_checks_length_and_bound() {
        assert_eq!(
            QVec::from_stored(vec![0; 3], 4).unwrap_err(),
            Error::WrongDimension
        );
        let edge = 16_777_232;
        assert!(QVec::from_stored(vec![edge, -edge], 2).is_ok());
        assert!(matches!(
            QVec::from_stored(vec![edge + 1, 0], 2),
            Err(Error::IntegrityViolation { .. })
        ));
    }
}
