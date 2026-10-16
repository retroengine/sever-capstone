//! RFC 9162 §2.1 hashes and the §2.1.3.2 inclusion-proof verification (spec §10.1).

use sha2::{Digest, Sha256};

/// `SHA-256(0x00 ‖ leaf)`.
pub fn leaf_hash(leaf: &[u8]) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update([0u8]);
    h.update(leaf);
    h.finalize().into()
}

/// `SHA-256(0x01 ‖ left ‖ right)`.
pub fn node_hash(left: &[u8; 32], right: &[u8; 32]) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update([1u8]);
    h.update(left);
    h.update(right);
    h.finalize().into()
}

/// RFC 9162 §2.1.3.2: does `path` prove the leaf with hash `leaf` at `index` in the tree of
/// `size` leaves whose root is `root`?
pub fn verify_inclusion(
    leaf: &[u8; 32],
    index: u64,
    size: u64,
    path: &[[u8; 32]],
    root: &[u8; 32],
) -> bool {
    // 1. Compare leaf_index from the inclusion_proof against tree_size; fail if it is not smaller.
    if index >= size {
        return false;
    }
    // 2. Set fn to leaf_index and sn to tree_size - 1. 3. Set r to hash.
    let (mut f, mut s, mut r) = (index, size - 1, *leaf);
    // 4. For each value p in the inclusion_proof array:
    for p in path {
        // a. If sn is 0, then stop the iteration and fail the proof verification.
        if s == 0 {
            return false;
        }
        // b. If LSB(fn) is set, or if fn is equal to sn, then:
        if f & 1 == 1 || f == s {
            // i. Set r to HASH(0x01 || p || r).
            r = node_hash(p, &r);
            // ii. If LSB(fn) is not set, then right-shift both fn and sn equally until either
            //     LSB(fn) is set or fn is 0.
            if f & 1 == 0 {
                while f & 1 == 0 && f != 0 {
                    f >>= 1;
                    s >>= 1;
                }
            }
        } else {
            // Otherwise: i. Set r to HASH(0x01 || r || p).
            r = node_hash(&r, p);
        }
        // c. Finally, right-shift both fn and sn one time.
        f >>= 1;
        s >>= 1;
    }
    // 5. Compare sn to 0. Compare r against the root_hash. If sn is equal to 0 and r and the
    //    root_hash are equal, then the log has proven the inclusion of hash.
    s == 0 && &r == root
}
