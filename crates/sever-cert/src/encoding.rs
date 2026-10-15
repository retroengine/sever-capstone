//! The certificate encoding (§11.1) and the `insert_inclusion` field (§11.2).

use sever_crypto::{KeyPair, Proof, certificate_message};
use sever_log::checkpoint::{CHECKPOINT_LEN, COSIGNATURE_LEN, Cosignature, LogCheckpoint};
use sever_log::leaf::{INSERT_LEAF_LEN, InsertLeaf, LeafError};
use sever_log::merkle::Hash;

/// The `insert_inclusion` version (§11.2).
pub const VERSION: u8 = 1;
/// The trailer's tag (§11.1).
pub const TRAILER: u8 = 0xFF;
/// The trailer's size: `u8 0xFF ‖ u32be 64 ‖ signature`.
pub const TRAILER_LEN: usize = 1 + 4 + 64;

/// Why certificate bytes were refused (§11.1). Names a tag number at most, never a value (§17).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ParseError {
    /// The bytes end inside a TLV.
    Truncated,
    /// A tag is missing, repeated or out of order: `found` stands where `expected` belongs.
    Tag {
        /// The tag that belongs here.
        expected: u8,
        /// The tag found.
        found: u8,
    },
    /// A field has the wrong length (the trailer is tag 255).
    Length {
        /// The field's tag.
        tag: u8,
    },
    /// Tag 11 or 12 is neither 0 nor 1 (DB-76).
    Value {
        /// The field's tag.
        tag: u8,
    },
    /// `insert_inclusion` has a version other than 1 (§11.2).
    Version,
    /// The leaf in `insert_inclusion` is not an insert leaf (§10.2).
    LeafType,
    /// `deletion_kind` disagrees with tags 2–4 and 11: a group deletion carries all three
    /// arithmetic fields, a holding-area deletion none and tag 11 = 0 (§11.1, §11.3 steps 6–7).
    Kind,
    /// Bytes after the trailer.
    TrailingBytes,
}

/// §11.2: the insert leaf, its index, the log checkpoint that covers it and the RFC 9162 path.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InsertInclusion {
    /// The record's insert leaf (§10.2).
    pub leaf: InsertLeaf,
    /// Its leaf index.
    pub leaf_index: u64,
    /// A signed log checkpoint whose tree covers the leaf.
    pub checkpoint: LogCheckpoint,
    /// The RFC 9162 inclusion path from the leaf to the checkpoint's root (at most 255 hashes).
    pub path: Vec<Hash>,
}

/// Fixed part of `insert_inclusion`: version, leaf, leaf index, checkpoint, path length.
const INCLUSION_FIXED: usize = 1 + INSERT_LEAF_LEN + 8 + CHECKPOINT_LEN + 1;

impl InsertInclusion {
    /// `u8 version ‖ insert_leaf ‖ u64be leaf_index ‖ checkpoint ‖ u8 path_len ‖ path`.
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut out = Vec::with_capacity(INCLUSION_FIXED + 32 * self.path.len());
        out.push(VERSION);
        out.extend_from_slice(&self.leaf.to_bytes());
        out.extend_from_slice(&self.leaf_index.to_be_bytes());
        out.extend_from_slice(&self.checkpoint.to_bytes());
        // A path never exceeds 64 hashes (RFC 9162: one per tree level); the builder refuses more
        // than 255.
        out.push(u8::try_from(self.path.len()).unwrap_or(u8::MAX));
        for h in &self.path {
            out.extend_from_slice(h);
        }
        out
    }

    fn parse(b: &[u8]) -> Result<Self, ParseError> {
        const TAG: u8 = 6;
        let len = ParseError::Length { tag: TAG };
        let (&version, rest) = b.split_first().ok_or(len)?;
        if version != VERSION {
            return Err(ParseError::Version);
        }
        let (leaf, rest) = rest.split_first_chunk::<INSERT_LEAF_LEN>().ok_or(len)?;
        let leaf = InsertLeaf::parse(leaf).map_err(|e| match e {
            LeafError::Type => ParseError::LeafType,
            LeafError::Length => len,
        })?;
        let (index, rest) = rest.split_first_chunk::<8>().ok_or(len)?;
        let (cp, rest) = rest.split_first_chunk::<CHECKPOINT_LEN>().ok_or(len)?;
        let checkpoint = LogCheckpoint::parse(cp).ok_or(len)?;
        let (&n, rest) = rest.split_first().ok_or(len)?;
        if rest.len() != 32 * usize::from(n) {
            return Err(len);
        }
        let path = rest
            .chunks_exact(32)
            .map(|h| <Hash>::try_from(h).map_err(|_| len))
            .collect::<Result<_, _>>()?;
        Ok(Self {
            leaf,
            leaf_index: u64::from_be_bytes(*index),
            checkpoint,
            path,
        })
    }
}

/// Tags 2, 3, 4 and 11 of a group deletion (`deletion_kind = 0`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GroupFields {
    /// Tag 2, `C_S_pre`.
    pub c_s_pre: [u8; 32],
    /// Tag 3, `C_S_post`.
    pub c_s_post: [u8; 32],
    /// Tag 4, the proof `A ‖ z_r ‖ z_0 … z_{d−1}` (§9.5).
    pub proof: Vec<u8>,
    /// Tag 11, `group_emptied_by_this_deletion`.
    pub emptied: bool,
}

/// A deletion certificate (§11.1). `group` is `None` for a holding-area deletion
/// (`deletion_kind = 1`: tags 2–4 empty, tag 11 = 0).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Certificate {
    /// Tag 1, `C_t`.
    pub c_t: [u8; 32],
    /// Tags 2, 3, 4 and 11 of a group deletion.
    pub group: Option<GroupFields>,
    /// Tag 5, the user's insert signature.
    pub user_signature: [u8; 64],
    /// Tag 6.
    pub inclusion: InsertInclusion,
    /// Tag 7, over the checkpoint in tag 6.
    pub cosignatures: Vec<Cosignature>,
    /// Tag 8, the operator epoch that signs this certificate.
    pub key_period: u32,
    /// Tag 9.
    pub scrambled_id: [u8; 64],
    /// Tag 10, this deletion's own leaf index.
    pub database_lsn: u64,
    /// Tag 13.
    pub collection_id: [u8; 16],
    /// The trailer: the operator's signature over `DST_CERT ‖ body`.
    pub operator_signature: [u8; 64],
}

fn tlv(out: &mut Vec<u8>, tag: u8, value: &[u8]) {
    out.push(tag);
    // Every value is far below 4 GiB (the largest, tag 4, is 64 + 32·d bytes).
    out.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    out.extend_from_slice(value);
}

/// Reads one TLV that must carry `expected`.
fn take<'a>(b: &mut &'a [u8], expected: u8) -> Result<&'a [u8], ParseError> {
    let (&tag, rest) = b.split_first().ok_or(ParseError::Truncated)?;
    if tag != expected {
        return Err(ParseError::Tag {
            expected,
            found: tag,
        });
    }
    let (n, rest) = rest.split_first_chunk::<4>().ok_or(ParseError::Truncated)?;
    let n = usize::try_from(u32::from_be_bytes(*n)).map_err(|_| ParseError::Truncated)?;
    if rest.len() < n {
        return Err(ParseError::Truncated);
    }
    let (value, rest) = rest.split_at(n);
    *b = rest;
    Ok(value)
}

fn fixed<const N: usize>(v: &[u8], tag: u8) -> Result<[u8; N], ParseError> {
    v.try_into().map_err(|_| ParseError::Length { tag })
}

fn flag(v: &[u8], tag: u8) -> Result<bool, ParseError> {
    match fixed::<1>(v, tag)? {
        [0] => Ok(false),
        [1] => Ok(true),
        _ => Err(ParseError::Value { tag }),
    }
}

/// Tags 2 and 3: 32 bytes, or empty.
fn optional_point(v: &[u8], tag: u8) -> Result<Option<[u8; 32]>, ParseError> {
    if v.is_empty() {
        Ok(None)
    } else {
        fixed(v, tag).map(Some)
    }
}

impl Certificate {
    /// `deletion_kind` (tag 12): 0 from a group, 1 from the holding area.
    pub fn deletion_kind(&self) -> u8 {
        u8::from(self.group.is_none())
    }

    /// Every byte before the trailer: tags 1 … 13 in ascending order (§11.1).
    pub fn body(&self) -> Vec<u8> {
        let g = self.group.as_ref();
        let empty: &[u8] = &[];
        let mut out = Vec::new();
        tlv(&mut out, 1, &self.c_t);
        tlv(&mut out, 2, g.map_or(empty, |g| &g.c_s_pre));
        tlv(&mut out, 3, g.map_or(empty, |g| &g.c_s_post));
        tlv(&mut out, 4, g.map_or(empty, |g| &g.proof));
        tlv(&mut out, 5, &self.user_signature);
        tlv(&mut out, 6, &self.inclusion.to_bytes());
        let mut cosigs = Vec::with_capacity(1 + COSIGNATURE_LEN * self.cosignatures.len());
        cosigs.push(u8::try_from(self.cosignatures.len()).unwrap_or(u8::MAX));
        for c in &self.cosignatures {
            cosigs.extend_from_slice(&c.to_bytes());
        }
        tlv(&mut out, 7, &cosigs);
        tlv(&mut out, 8, &self.key_period.to_be_bytes());
        tlv(&mut out, 9, &self.scrambled_id);
        tlv(&mut out, 10, &self.database_lsn.to_be_bytes());
        tlv(&mut out, 11, &[u8::from(g.is_some_and(|g| g.emptied))]);
        tlv(&mut out, 12, &[self.deletion_kind()]);
        tlv(&mut out, 13, &self.collection_id);
        out
    }

    /// Signs the body with the operator's key of epoch `key_period` (§9.8: over
    /// `DST_CERT ‖ body`).
    pub fn sign(&mut self, operator: &KeyPair) {
        self.operator_signature = operator.sign(&certificate_message(&self.body()));
    }

    /// The certificate: the body, then `0xFF ‖ u32be 64 ‖ operator_signature`.
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut out = self.body();
        tlv(&mut out, TRAILER, &self.operator_signature);
        out
    }

    /// Strict parse (§11.1) of a certificate for vectors of dimension `d`: every tag once and in
    /// order, the length of every fixed-size field, tags 11 and 12 in {0, 1}, the §11.2 layout of
    /// tag 6, tags 2–4 consistent with the deletion kind, and no trailing bytes. Points and scalars
    /// are not decoded here: the verifier decodes them (§11.3 step 1).
    pub fn parse(bytes: &[u8], d: usize) -> Result<Self, ParseError> {
        let mut b = bytes;
        let mut v: [&[u8]; 13] = [&[]; 13];
        for (tag, slot) in (1u8..).zip(v.iter_mut()) {
            *slot = take(&mut b, tag)?;
        }
        let sig = take(&mut b, TRAILER)?;
        if !b.is_empty() {
            return Err(ParseError::TrailingBytes);
        }
        let [t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11, t12, t13] = v;
        let c_t = fixed(t1, 1)?;
        let c_s_pre = optional_point(t2, 2)?;
        let c_s_post = optional_point(t3, 3)?;
        if !t4.is_empty() && t4.len() != Proof::encoded_len(d) {
            return Err(ParseError::Length { tag: 4 });
        }
        let user_signature = fixed(t5, 5)?;
        let inclusion = InsertInclusion::parse(t6)?;
        let cosignatures = parse_cosignatures(t7)?;
        let key_period = u32::from_be_bytes(fixed(t8, 8)?);
        let scrambled_id = fixed(t9, 9)?;
        let database_lsn = u64::from_be_bytes(fixed(t10, 10)?);
        let emptied = flag(t11, 11)?;
        let holding = flag(t12, 12)?;
        let collection_id = fixed(t13, 13)?;
        let operator_signature = fixed(sig, TRAILER)?;
        let group = match (holding, c_s_pre, c_s_post, t4.is_empty()) {
            (false, Some(c_s_pre), Some(c_s_post), false) => Some(GroupFields {
                c_s_pre,
                c_s_post,
                proof: t4.to_vec(),
                emptied,
            }),
            (true, None, None, true) if !emptied => None,
            _ => return Err(ParseError::Kind),
        };
        Ok(Self {
            c_t,
            group,
            user_signature,
            inclusion,
            cosignatures,
            key_period,
            scrambled_id,
            database_lsn,
            collection_id,
            operator_signature,
        })
    }
}

/// Tag 7: `u8 count ‖ count × (u8 witness_index ‖ u32be witness_epoch ‖ signature)`.
fn parse_cosignatures(v: &[u8]) -> Result<Vec<Cosignature>, ParseError> {
    let len = ParseError::Length { tag: 7 };
    let (&count, rest) = v.split_first().ok_or(len)?;
    if rest.len() != COSIGNATURE_LEN * usize::from(count) {
        return Err(len);
    }
    rest.chunks_exact(COSIGNATURE_LEN)
        .map(|c| Cosignature::parse(c).ok_or(len))
        .collect()
}
