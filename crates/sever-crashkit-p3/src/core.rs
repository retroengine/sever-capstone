//! The core form of a group's state (§5.5): what Parts 1 and 2's oracles digest. The full form
//! (`SEVERG`) is the core form with the 64-byte region `C_S ‖ r_agg` after `S`; removing it and
//! the magic's last letter gives the core blob (`SEVERC`) byte for byte.

use sever_crashkit::state_digest;
use sever_engine::hooks::CanonicalState;

/// The core blob of a full-form blob of dimension `d`, or `None` if it is not one.
pub fn core_blob(full: &[u8], d: usize) -> Option<Vec<u8>> {
    let s_end = 18 + 8 * d;
    if full.get(..6) != Some(b"SEVERG".as_slice()) || full.len() < s_end + 64 + 8 {
        return None;
    }
    let mut out = b"SEVERC".to_vec();
    out.extend_from_slice(full.get(6..s_end)?);
    out.extend_from_slice(full.get(s_end + 64..)?);
    Some(out)
}

/// The canonical state with every blob in core form.
pub fn core_state(s: &CanonicalState, d: usize) -> Option<CanonicalState> {
    Some(CanonicalState {
        groups: s
            .groups
            .iter()
            .map(|(g, b)| core_blob(b, d).map(|c| (g.clone(), c)))
            .collect::<Option<_>>()?,
        holding: s.holding.clone(),
        big_n: s.big_n,
        k: s.k,
    })
}

/// The state digest of Part 2's oracle, over the core form.
pub fn core_digest(s: &CanonicalState, d: usize) -> Option<[u8; 32]> {
    core_state(s, d).map(|c| state_digest(&c))
}
