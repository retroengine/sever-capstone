//! Log leaves (§10.2): the 209-byte insert leaf and the delete leaf `0x02 ‖ certificate`.

/// Leaf type byte of an insert leaf.
pub const LEAF_INSERT: u8 = 0x01;
/// Leaf type byte of a delete leaf.
pub const LEAF_DELETE: u8 = 0x02;
/// Size of an insert leaf (§10.2, Appendix A).
pub const INSERT_LEAF_LEN: usize = 209;

/// Why leaf bytes were refused.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LeafError {
    /// Not 209 bytes (insert) or empty after the type byte (delete).
    Length,
    /// The type byte is not the expected one.
    Type,
}

/// An insert leaf: `0x01 ‖ collection_id (16) ‖ scrambled_id (64) ‖ C_t (32) ‖ user_public_key (32)
/// ‖ user_signature (64)` = 209 bytes, appended on every insert (§10.2).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct InsertLeaf {
    /// The collection.
    pub collection_id: [u8; 16],
    /// The record's scrambled ID (§9.7).
    pub scrambled_id: [u8; 64],
    /// The record commitment.
    pub c_t: [u8; 32],
    /// The account's public key, published here (§3.3).
    pub user_public_key: [u8; 32],
    /// The insert signature over `DST_INSERT ‖ collection_id ‖ C_t` (§9.8).
    pub user_signature: [u8; 64],
}

impl InsertLeaf {
    /// The 209 leaf bytes.
    pub fn to_bytes(&self) -> [u8; INSERT_LEAF_LEN] {
        let mut out = [0u8; INSERT_LEAF_LEN];
        let parts: [&[u8]; 6] = [
            &[LEAF_INSERT],
            &self.collection_id,
            &self.scrambled_id,
            &self.c_t,
            &self.user_public_key,
            &self.user_signature,
        ];
        let mut rest = out.as_mut_slice();
        for p in parts {
            let (head, tail) = rest.split_at_mut(p.len());
            head.copy_from_slice(p);
            rest = tail;
        }
        out
    }

    /// Strict parse: exactly 209 bytes with type `0x01`.
    pub fn parse(b: &[u8]) -> Result<Self, LeafError> {
        let b: &[u8; INSERT_LEAF_LEN] = b.try_into().map_err(|_| LeafError::Length)?;
        let (ty, rest) = b.split_first().ok_or(LeafError::Length)?;
        if *ty != LEAF_INSERT {
            return Err(LeafError::Type);
        }
        let (collection_id, rest) = rest.split_first_chunk::<16>().ok_or(LeafError::Length)?;
        let (scrambled_id, rest) = rest.split_first_chunk::<64>().ok_or(LeafError::Length)?;
        let (c_t, rest) = rest.split_first_chunk::<32>().ok_or(LeafError::Length)?;
        let (user_public_key, rest) = rest.split_first_chunk::<32>().ok_or(LeafError::Length)?;
        let user_signature: [u8; 64] = rest.try_into().map_err(|_| LeafError::Length)?;
        Ok(Self {
            collection_id: *collection_id,
            scrambled_id: *scrambled_id,
            c_t: *c_t,
            user_public_key: *user_public_key,
            user_signature,
        })
    }
}

/// A delete leaf's bytes: `0x02 ‖ certificate` (§10.2).
pub fn delete_leaf(certificate: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(1 + certificate.len());
    out.push(LEAF_DELETE);
    out.extend_from_slice(certificate);
    out
}

/// The certificate inside a delete leaf.
pub fn parse_delete_leaf(b: &[u8]) -> Result<&[u8], LeafError> {
    match b.split_first() {
        Some((&LEAF_DELETE, cert)) if !cert.is_empty() => Ok(cert),
        Some((&LEAF_DELETE, _)) | None => Err(LeafError::Length),
        Some(_) => Err(LeafError::Type),
    }
}
