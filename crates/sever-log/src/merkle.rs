//! The log's Merkle tree, exactly RFC 9162 §2.1 (spec §10.1): `leaf_hash = SHA-256(0x00 ‖ leaf)`,
//! `node_hash = SHA-256(0x01 ‖ left ‖ right)`, the left-heavy tree built from the largest complete
//! left subtree; inclusion and consistency proofs by RFC 9162's own algorithms.
//!
//! [`MerkleTree`] keeps every level of the complete subtrees (§10.5): `levels[k][j]` is the hash of
//! leaves `[j·2^k, (j+1)·2^k)`. Any subtree hash, any root at a past size and any proof is then a
//! walk of `O(log n)` stored nodes plus `O(log n)` new hashes, never a rebuild from the leaves.

use sha2::{Digest, Sha256};

/// A SHA-256 hash.
pub type Hash = [u8; 32];

#[cfg(test)]
thread_local! {
    /// Test only: node hashes computed on this thread (for the `O(log n)` check of §10.5).
    pub(crate) static NODE_HASHES: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}

/// `SHA-256(0x00 ‖ leaf)` (RFC 9162 §2.1.1).
pub fn leaf_hash(leaf: &[u8]) -> Hash {
    let mut h = Sha256::new();
    h.update([0u8]);
    h.update(leaf);
    h.finalize().into()
}

/// `SHA-256(0x01 ‖ left ‖ right)` (RFC 9162 §2.1.1).
pub fn node_hash(left: &Hash, right: &Hash) -> Hash {
    #[cfg(test)]
    NODE_HASHES.with(|c| c.set(c.get() + 1));
    let mut h = Sha256::new();
    h.update([1u8]);
    h.update(left);
    h.update(right);
    h.finalize().into()
}

/// `MTH({}) = SHA-256()`, the root of the empty tree.
pub fn empty_root() -> Hash {
    Sha256::digest([]).into()
}

/// The largest power of two smaller than `n` (`n > 1`): RFC 9162's `k`, with `k < n ≤ 2k`.
fn split(n: u64) -> u64 {
    let mut k = 1u64;
    while k * 2 < n {
        k *= 2;
    }
    k
}

/// An append-only RFC 9162 tree holding every complete subtree.
#[derive(Clone, Debug, Default)]
pub struct MerkleTree {
    levels: Vec<Vec<Hash>>,
}

impl MerkleTree {
    /// The empty tree.
    pub fn new() -> Self {
        Self::default()
    }

    /// The number of leaves.
    pub fn size(&self) -> u64 {
        self.levels.first().map_or(0, |l| l.len() as u64)
    }

    /// Appends a leaf; returns its 0-based index.
    pub fn push(&mut self, leaf: &[u8]) -> u64 {
        self.push_hash(leaf_hash(leaf))
    }

    /// Appends a leaf by its leaf hash (recovery replays stored hashes, §10.5); returns its index.
    pub fn push_hash(&mut self, h: Hash) -> u64 {
        let index = self.size();
        let mut carry = h;
        let mut k = 0usize;
        loop {
            if self.levels.len() == k {
                self.levels.push(Vec::new());
            }
            let Some(level) = self.levels.get_mut(k) else {
                break;
            };
            level.push(carry);
            // A completed pair at level k makes one node at level k + 1.
            if level.len() % 2 == 1 {
                break;
            }
            let (Some(l), Some(r)) = (level.get(level.len() - 2), level.last()) else {
                break;
            };
            carry = node_hash(l, r);
            k += 1;
        }
        index
    }

    /// The hash of the leaf at `index`.
    pub fn leaf(&self, index: u64) -> Option<Hash> {
        self.levels
            .first()?
            .get(usize::try_from(index).ok()?)
            .copied()
    }

    /// `MTH(D[start : start + len])`, `len ≥ 1`, from the stored levels (`start + len ≤ size`).
    fn subtree(&self, start: u64, len: u64) -> Option<Hash> {
        if len.is_power_of_two() && start % len == 0 {
            let level = len.trailing_zeros() as usize;
            return self
                .levels
                .get(level)?
                .get(usize::try_from(start / len).ok()?)
                .copied();
        }
        let k = split(len);
        Some(node_hash(
            &self.subtree(start, k)?,
            &self.subtree(start + k, len - k)?,
        ))
    }

    /// The root at a past or present size `n ≤ size` (RFC 9162 §2.1.1; `n = 0` gives `SHA-256()`).
    pub fn root(&self, n: u64) -> Option<Hash> {
        match n {
            0 => Some(empty_root()),
            n if n <= self.size() => self.subtree(0, n),
            _ => None,
        }
    }

    /// `PATH(m, D[0:n])` (RFC 9162 §2.1.3.1), for `m < n ≤ size`.
    pub fn inclusion_proof(&self, m: u64, n: u64) -> Option<Vec<Hash>> {
        if m >= n || n > self.size() {
            return None;
        }
        let mut out = Vec::new();
        self.path(m, 0, n, &mut out)?;
        Some(out)
    }

    /// `PATH(m, D[start : start + len])`, appending in RFC order (deepest first).
    fn path(&self, m: u64, start: u64, len: u64, out: &mut Vec<Hash>) -> Option<()> {
        if len == 1 {
            return Some(());
        }
        let k = split(len);
        if m < k {
            self.path(m, start, k, out)?;
            out.push(self.subtree(start + k, len - k)?);
        } else {
            self.path(m - k, start + k, len - k, out)?;
            out.push(self.subtree(start, k)?);
        }
        Some(())
    }

    /// `PROOF(m, D[0:n])` (RFC 9162 §2.1.4.1), for `0 < m < n ≤ size`.
    pub fn consistency_proof(&self, m: u64, n: u64) -> Option<Vec<Hash>> {
        if m == 0 || m >= n || n > self.size() {
            return None;
        }
        let mut out = Vec::new();
        self.subproof(m, 0, n, true, &mut out)?;
        Some(out)
    }

    /// `SUBPROOF(m, D[start : start + len], b)`.
    fn subproof(&self, m: u64, start: u64, len: u64, b: bool, out: &mut Vec<Hash>) -> Option<()> {
        if m == len {
            if !b {
                out.push(self.subtree(start, len)?);
            }
            return Some(());
        }
        let k = split(len);
        if m <= k {
            self.subproof(m, start, k, b, out)?;
            out.push(self.subtree(start + k, len - k)?);
        } else {
            self.subproof(m - k, start + k, len - k, false, out)?;
            out.push(self.subtree(start, k)?);
        }
        Some(())
    }
}

/// RFC 9162 §2.1.3.2: does `path` prove leaf hash `h` at `leaf_index` in the tree of `tree_size`
/// with root `root`?
pub fn verify_inclusion(
    h: &Hash,
    leaf_index: u64,
    tree_size: u64,
    path: &[Hash],
    root: &Hash,
) -> bool {
    if leaf_index >= tree_size {
        return false; // step 1
    }
    let (mut fn_, mut sn) = (leaf_index, tree_size - 1); // step 2
    let mut r = *h; // step 3
    for p in path {
        // step 4
        if sn == 0 {
            return false; // 4a
        }
        if fn_ & 1 == 1 || fn_ == sn {
            r = node_hash(p, &r); // 4b i
            if fn_ & 1 == 0 {
                while fn_ & 1 == 0 && fn_ != 0 {
                    fn_ >>= 1;
                    sn >>= 1;
                }
            }
        } else {
            r = node_hash(&r, p); // 4b otherwise
        }
        fn_ >>= 1; // 4c
        sn >>= 1;
    }
    sn == 0 && r == *root // step 5
}

/// RFC 9162 §2.1.4.2: does `path` prove the tree of size `second` with root `second_hash` extends
/// the tree of size `first` with root `first_hash`, for `0 < first < second`?
pub fn verify_consistency(
    first: u64,
    second: u64,
    first_hash: &Hash,
    second_hash: &Hash,
    path: &[Hash],
) -> bool {
    if first == 0 || first >= second || path.is_empty() {
        return false; // step 1 (and the RFC's 0 < first < second)
    }
    let mut nodes: Vec<Hash> = Vec::with_capacity(path.len() + 1);
    if first.is_power_of_two() {
        nodes.push(*first_hash); // step 2
    }
    nodes.extend_from_slice(path);
    let (mut fn_, mut sn) = (first - 1, second - 1); // step 3
    while fn_ & 1 == 1 {
        fn_ >>= 1; // step 4
        sn >>= 1;
    }
    let Some((head, rest)) = nodes.split_first() else {
        return false;
    };
    let (mut fr, mut sr) = (*head, *head); // step 5
    for c in rest {
        // step 6
        if sn == 0 {
            return false; // 6a
        }
        if fn_ & 1 == 1 || fn_ == sn {
            fr = node_hash(c, &fr); // 6b i
            sr = node_hash(c, &sr); // 6b ii
            if fn_ & 1 == 0 {
                while fn_ & 1 == 0 && fn_ != 0 {
                    fn_ >>= 1;
                    sn >>= 1;
                }
            }
        } else {
            sr = node_hash(&sr, c); // 6b otherwise
        }
        fn_ >>= 1; // 6c
        sn >>= 1;
    }
    fr == *first_hash && sr == *second_hash && sn == 0 // step 7
}
