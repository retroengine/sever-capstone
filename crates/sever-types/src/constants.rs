//! Fixed parameters of the v1 configuration (spec §2.2) and the bounds derived from them
//! (Appendix A). The code accepts any `d` that is a multiple of 8 and any number of frozen groups
//! ≥ 1; these are the v1 values (overview DB-49).

/// §2.2: vector dimension `d` in v1.
pub const DIMENSION_V1: usize = 384;

/// §2.2: fractional bits `f` of the fixed-point encoding.
pub const FRACTIONAL_BITS: u32 = 24;

/// §2.2: the scale `2^f = 16,777,216`.
pub const SCALE: i64 = 1 << FRACTIONAL_BITS;

/// §2.2: the normalisation tolerance, in float32 ULPs at 1.0.
pub const NORM_TOLERANCE_ULPS: u32 = 8;

/// §2.2, §4.1: the tolerance `8 · 2^−23 ≈ 9.54 × 10^−7`. Dividing by a power of two is exact.
pub const NORM_TOLERANCE: f64 = NORM_TOLERANCE_ULPS as f64 / 8_388_608.0;

/// §2.2: frozen groups in v1.
pub const FROZEN_GROUPS_V1: usize = 128;

/// §2.2, §5.6: hard cap on members per group (INV-4).
pub const MAX_GROUP_MEMBERS: u64 = 1_000_000;

/// §2.2, §7.4: the holding area flushes at exactly this many records.
pub const SPAWN_TARGET_SIZE: usize = 200;

/// §2.2, §5.6: capacity multiplier 1.5 as the exact ratio `(3, 2)`, so the room test is integer
/// arithmetic: `2·k·n < 3·N`.
pub const CAPACITY_MULTIPLIER: (u64, u64) = (3, 2);

/// §2.2, §8.1: probe coverage 25 % as the exact ratio `(1, 4)`, rounded up.
pub const PROBE_COVERAGE: (u64, u64) = (1, 4);

/// §2.2, §3.2 rule 1: shortest record ID, in bytes.
pub const RECORD_ID_MIN_BYTES: usize = 1;

/// §2.2, §3.2 rule 1: longest record ID, in bytes.
pub const RECORD_ID_MAX_BYTES: usize = 256;

/// §5.1: group IDs are at most 32 bytes.
pub const GROUP_ID_MAX_BYTES: usize = 32;

/// §3.1: `collection_id` is 16 bytes.
pub const COLLECTION_ID_BYTES: usize = 16;

/// §9.7: `scrambled_id` is an HMAC-SHA-512 output, 64 bytes.
pub const SCRAMBLED_ID_BYTES: usize = 64;

/// §9.7: `k_scramble` is 64 bytes.
pub const SCRAMBLE_KEY_BYTES: usize = 64;

/// §4.2, Appendix A: the largest `|x̃_i|`, `2^24 + 16`, reached at the tolerance edge.
pub const MAX_ABS_QUANTISED: i64 = SCALE + 16;

/// §4.4, Appendix A: under the hard cap, every `|S_i| < 2^44`.
pub const MAX_ACCUMULATOR_BITS: u32 = 44;

#[cfg(test)]
mod tests {
    use super::*;

    // spec: SR-2.2-1 — the Part 1 rows of the §2.2 table, value by value.
    #[test]
    fn p1_types_v1_parameters_match_spec_table() {
        assert_eq!(DIMENSION_V1, 384);
        assert_eq!(FRACTIONAL_BITS, 24);
        assert_eq!(SCALE, 16_777_216);
        assert_eq!(NORM_TOLERANCE_ULPS, 8);
        assert_eq!(FROZEN_GROUPS_V1, 128);
        assert_eq!(MAX_GROUP_MEMBERS, 1_000_000);
        assert_eq!(SPAWN_TARGET_SIZE, 200);
        assert_eq!(CAPACITY_MULTIPLIER, (3, 2));
        assert_eq!(PROBE_COVERAGE, (1, 4));
        assert_eq!((RECORD_ID_MIN_BYTES, RECORD_ID_MAX_BYTES), (1, 256));
    }

    // spec: SR-2.2-1 — Appendix A "Normalisation tolerance: 8 × 2^−23 = 9.54 × 10^−7", exactly.
    #[test]
    fn p1_types_tolerance_is_exactly_eight_float32_ulps() {
        assert_eq!(NORM_TOLERANCE, 8.0 * f64::from(f32::EPSILON));
        assert_eq!(NORM_TOLERANCE, 9.5367431640625e-7);
    }

    // spec: SR-2.2-1 — Appendix A rows "Largest |x̃_i|" and "Largest |S_i| at 10^6 members".
    #[test]
    fn p1_types_appendix_a_bounds_hold() {
        assert_eq!(MAX_ABS_QUANTISED, 16_777_232);
        assert!(MAX_ABS_QUANTISED < i64::from(i32::MAX));
        let max_sum = i128::from(MAX_GROUP_MEMBERS) * i128::from(MAX_ABS_QUANTISED);
        assert!(max_sum < 1_i128 << MAX_ACCUMULATOR_BITS);
        assert_eq!(63 - MAX_ACCUMULATOR_BITS, 19, "19 bits of headroom in i64");
    }

    // Appendix A: probe counts at 128 and 263 groups.
    #[test]
    fn p1_types_probe_ratio_gives_appendix_a_probe_counts() {
        let probes = |k: u64| (k * PROBE_COVERAGE.0).div_ceil(PROBE_COVERAGE.1);
        assert_eq!(probes(128), 32);
        assert_eq!(probes(263), 66);
    }
}
