//! The pinned distance kernel (spec §8.2). Scalar and AVX2 produce bit-identical scores.
//!
//! Eight float32 partial sums `L_0 … L_7`, all starting at `+0.0`. For `i = 0 … d−1`, lane
//! `j = i mod 8` does `t = q_i − x̂_i; L_j = L_j + t·t`, the multiply and the add as separate IEEE
//! operations (no fused multiply-add). Then `((L0 + L1) + (L2 + L3)) + ((L4 + L5) + (L6 + L7))`.
//! `d` must be a multiple of 8 (the artefact parser enforces it); any tail is ignored.

/// §8.2 reduction tree.
fn reduce(l: [f32; 8]) -> f32 {
    let [l0, l1, l2, l3, l4, l5, l6, l7] = l;
    ((l0 + l1) + (l2 + l3)) + ((l4 + l5) + (l6 + l7))
}

/// §8.2, scalar: the reference implementation and the fallback when AVX2 is absent.
pub fn score_scalar(q: &[f32], x: &[f32]) -> f32 {
    let mut lanes = [0.0_f32; 8];
    for (qc, xc) in q.chunks_exact(8).zip(x.chunks_exact(8)) {
        for ((l, a), b) in lanes.iter_mut().zip(qc).zip(xc) {
            let t = a - b;
            let sq = t * t; // rounded on its own: Rust never contracts into an FMA
            *l += sq;
        }
    }
    reduce(lanes)
}

/// §8.2: the AVX2 kernel when the CPU has it (detected at runtime), else the scalar one.
pub fn score(q: &[f32], x: &[f32]) -> f32 {
    #[cfg(target_arch = "x86_64")]
    {
        if avx2::available() {
            return avx2::score(q, x);
        }
    }
    score_scalar(q, x)
}

/// Whether [`score`] uses the AVX2 kernel on this machine.
pub fn uses_avx2() -> bool {
    #[cfg(target_arch = "x86_64")]
    {
        avx2::available()
    }
    #[cfg(not(target_arch = "x86_64"))]
    {
        false
    }
}

#[cfg(target_arch = "x86_64")]
pub(crate) mod avx2 {
    //! The AVX2 kernel: one 256-bit register holds the eight lanes, so lane `j` of block `s` is
    //! element `8s + j`, exactly the scalar layout. Built from separate `sub`, `mul` and `add`
    //! intrinsics; FMA is never enabled for it (spec §8.2), except by sabotage SB-9.
    #![allow(unsafe_code)]
    // Build §1.2: the listed SIMD exception; every block has a SAFETY note.
    // Rust 1.85 (the MSRV) needs `unsafe` around value intrinsics inside a `#[target_feature]`
    // function; from 1.86 they are safe there and the same blocks are "unused". Both compile clean.
    #![allow(unused_unsafe)]

    use core::arch::x86_64::{
        __m256, _mm256_loadu_ps, _mm256_setzero_ps, _mm256_storeu_ps, _mm256_sub_ps,
    };

    pub(crate) fn available() -> bool {
        if cfg!(feature = "sabotage-SB-9") {
            return std::is_x86_feature_detected!("avx2") && std::is_x86_feature_detected!("fma");
        }
        std::is_x86_feature_detected!("avx2")
    }

    pub(crate) fn score(q: &[f32], x: &[f32]) -> f32 {
        // SAFETY: `available()` returned true before any caller reaches here, so the CPU supports
        // AVX2 (and FMA, under SB-9), which is all `kernel` requires.
        unsafe { kernel(q, x) }
    }

    #[target_feature(enable = "avx2")]
    #[cfg_attr(feature = "sabotage-SB-9", target_feature(enable = "fma"))]
    unsafe fn kernel(q: &[f32], x: &[f32]) -> f32 {
        // SAFETY: this function runs only with AVX2 enabled (`#[target_feature]`, checked by
        // `available()`); the value intrinsics below touch no memory.
        let mut acc: __m256 = unsafe { _mm256_setzero_ps() }; // L_0 … L_7 = +0.0
        for (qc, xc) in q.chunks_exact(8).zip(x.chunks_exact(8)) {
            // SAFETY: `chunks_exact(8)` yields exactly 8 f32 (32 bytes) per chunk, and
            // `loadu` has no alignment requirement.
            let (a, b) = unsafe { (_mm256_loadu_ps(qc.as_ptr()), _mm256_loadu_ps(xc.as_ptr())) };
            // SAFETY: AVX2 is enabled here (see above); no memory is touched.
            let t = unsafe { _mm256_sub_ps(a, b) };
            #[cfg(not(feature = "sabotage-SB-9"))]
            {
                use core::arch::x86_64::{_mm256_add_ps, _mm256_mul_ps};
                // SAFETY: AVX2 is enabled here (see above); no memory is touched.
                acc = unsafe { _mm256_add_ps(acc, _mm256_mul_ps(t, t)) }; // separate mul, then add
            }
            #[cfg(feature = "sabotage-SB-9")]
            {
                // SB-9: a fused multiply-add rounds once instead of twice.
                // SAFETY: FMA is enabled for this build (SB-9 only); no memory is touched.
                acc = unsafe { core::arch::x86_64::_mm256_fmadd_ps(t, t, acc) };
            }
        }
        let mut lanes = [0.0_f32; 8];
        // SAFETY: `lanes` is 8 f32 = 32 bytes, and `storeu` has no alignment requirement.
        unsafe { _mm256_storeu_ps(lanes.as_mut_ptr(), acc) };
        super::reduce(lanes)
    }
}
