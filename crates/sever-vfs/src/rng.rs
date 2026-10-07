//! SplitMix64: the seeded generator behind [`crate::SimVfs`]'s crash choices.
//!
//! Written out here, not taken from a crate, so that a saved failing seed reproduces the same
//! crash forever, whatever happens to dependency versions (Build §2.1: a failing random case is
//! kept as a permanent regression). Never used for keys, nonces or proofs (CLAUDE.md §6.2).

/// SplitMix64 (Steele, Lea and Flood, 2014).
#[derive(Clone, Debug)]
pub struct SplitMix64(u64);

impl SplitMix64 {
    /// A generator whose whole output is fixed by `seed`.
    pub fn new(seed: u64) -> Self {
        Self(seed)
    }

    /// The internal state: `SplitMix64::new(g.state())` continues exactly where `g` is (used to
    /// resume an interrupted campaign).
    pub fn state(&self) -> u64 {
        self.0
    }

    /// The next 64 output bits.
    pub fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        z ^ (z >> 31)
    }

    /// A value in `0..n` (`0` when `n == 0`), by Lemire's multiply-shift.
    pub fn below(&mut self, n: u64) -> u64 {
        ((u128::from(self.next_u64()) * u128::from(n)) >> 64) as u64
    }

    /// True with probability `1 / n` (`n ≥ 1`).
    pub fn one_in(&mut self, n: u64) -> bool {
        self.below(n) == 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Reference outputs for seed 1234567 (the published SplitMix64 test vector).
    #[test]
    fn p2_vfs_splitmix64_matches_reference() {
        let mut r = SplitMix64::new(1_234_567);
        let want = [
            6_457_827_717_110_365_317,
            3_203_168_211_198_807_973,
            9_817_491_932_198_370_423,
            4_593_380_528_125_082_431,
            16_408_922_859_458_223_821,
        ];
        for w in want {
            assert_eq!(r.next_u64(), w);
        }
    }

    #[test]
    fn p2_vfs_below_stays_in_range() {
        let mut r = SplitMix64::new(42);
        assert_eq!(r.below(0), 0);
        for n in [1, 2, 3, 7, 512, u64::MAX] {
            for _ in 0..1000 {
                assert!(r.below(n) < n);
            }
        }
    }
}
