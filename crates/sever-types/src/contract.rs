//! Contract suites for the extension points this crate declares (Build §3.4, test level L7).
//!
//! Enabled by the `contract-tests` feature, so implementations written in later parts, after this
//! crate is frozen, can run the same checks: Part 4's `MlockProvider` must pass
//! [`ep4_provider_contract`] unchanged (Build 3-4 §2.8).

use crate::secret::{SecretBuf, SecretMemory};

/// Why a provider failed the EP-4 contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Ep4Violation {
    /// A region did not have the requested length.
    WrongLength,
    /// A fresh region was not all zero.
    NotZeroed,
    /// Writing one live region changed another.
    SharedMemory,
}

/// EP-4: `allocate(len)` returns exactly `len` bytes, all zero, independent of every other live
/// region; the bytes read back as written.
pub fn ep4_provider_contract(provider: &dyn SecretMemory) -> Result<(), Ep4Violation> {
    // Sizes used by Parts 1–4: empty, one byte, a key (32), k_scramble (64), an accumulator
    // (3,104 at d = 384, Appendix A), and more than a page.
    for len in [0, 1, 32, 64, 3_104, 4_097] {
        let mut a = SecretBuf::new_in(provider, len);
        let b = SecretBuf::new_in(provider, len);
        if a.len() != len || b.len() != len {
            return Err(Ep4Violation::WrongLength);
        }
        if a.as_bytes().iter().chain(b.as_bytes()).any(|&x| x != 0) {
            return Err(Ep4Violation::NotZeroed);
        }
        a.as_bytes_mut().fill(0x5a);
        if a.as_bytes().iter().any(|&x| x != 0x5a) {
            return Err(Ep4Violation::SharedMemory);
        }
        if b.as_bytes().iter().any(|&x| x != 0) {
            return Err(Ep4Violation::SharedMemory);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::secret::{HeapProvider, SecretRegion};

    // Build §3.4 — the default implementation passes its own contract.
    #[test]
    fn p1_types_ep4_heap_provider_passes_contract() {
        assert_eq!(ep4_provider_contract(&HeapProvider), Ok(()));
    }

    struct Region(Vec<u8>);
    impl SecretRegion for Region {
        fn bytes(&self) -> &[u8] {
            &self.0
        }
        fn bytes_mut(&mut self) -> &mut [u8] {
            &mut self.0
        }
    }

    /// Deliberately wrong: hands out memory that still holds old bytes.
    struct Dirty;
    impl SecretMemory for Dirty {
        fn allocate(&self, len: usize) -> Box<dyn SecretRegion> {
            Box::new(Region(vec![0xaa; len]))
        }
    }

    /// Deliberately wrong: rounds every request up to a multiple of 16.
    struct Rounding;
    impl SecretMemory for Rounding {
        fn allocate(&self, len: usize) -> Box<dyn SecretRegion> {
            Box::new(Region(vec![0; len.div_ceil(16) * 16]))
        }
    }

    // Build §3.4, P1-T13 — a deliberately wrong implementation fails the contract.
    #[test]
    fn p1_types_ep4_contract_rejects_wrong_providers() {
        assert_eq!(ep4_provider_contract(&Dirty), Err(Ep4Violation::NotZeroed));
        assert_eq!(
            ep4_provider_contract(&Rounding),
            Err(Ep4Violation::WrongLength)
        );
    }
}
