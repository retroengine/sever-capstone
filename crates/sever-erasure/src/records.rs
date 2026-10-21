//! The key-rotation participant's records (spec §14.6, §14.8, DB-90, DB-91) and its durable state,
//! merged by monotonic rules so the wrapped-key store and the WAL tail can be applied in any order.
//!
//! ```text
//! store value, kind 1   0x01 ‖ collection_id ‖ group_id ‖ u64be group_key_version ‖ bucket block
//! store value, kind 2   0x02 ‖ collection_id ‖ group_id ‖ u32be count ‖ count × (scrambled_id ‖
//!                       u64be bucket_version ‖ envelope)
//! store value, kind 3   0x03 ‖ collection_id
//! WAL BUCKET_BLOCK      the kind-1 value without its kind byte
//! WAL EXTENSION         u16be 4 ‖ a kind-2 or kind-3 value
//! ```

use std::collections::{BTreeMap, BTreeSet};

use sever_keys::Domain;
use sever_seal::ad::Sid;
use sever_seal::block::{BLOCK_BYTES, ENVELOPE_BYTES, Envelope};
use sever_types::Error;

/// The participant's ID in `EXTENSION` records (DB-91).
pub const KEY_PARTICIPANT_ID: u16 = 4;

/// Store-value kinds (§14.8).
pub const KIND_BLOCK: u8 = 1;
/// See [`KIND_BLOCK`].
pub const KIND_ENVELOPES: u8 = 2;
/// See [`KIND_BLOCK`].
pub const KIND_DROP: u8 = 3;

const ENTRY: usize = 64 + 8 + ENVELOPE_BYTES;

fn bad() -> Error {
    Error::IntegrityViolation {
        invariant: "§14.8 wrapped-key record",
    }
}

fn put_domain(out: &mut Vec<u8>, d: &Domain) {
    out.extend_from_slice(&d.collection_id);
    out.extend_from_slice(&d.group_id);
}

/// A kind-1 value: a domain's bucket block at `version`.
pub fn block_value(d: &Domain, version: u64, block: &[u8]) -> Vec<u8> {
    let mut v = Vec::with_capacity(1 + 48 + 8 + block.len());
    v.push(KIND_BLOCK);
    put_domain(&mut v, d);
    v.extend_from_slice(&version.to_be_bytes());
    v.extend_from_slice(block);
    v
}

/// A kind-2 value: re-wrapped envelopes of domain `d`.
pub fn envelopes_value(d: &Domain, entries: &[(Sid, u64, Envelope)]) -> Vec<u8> {
    let mut v = Vec::with_capacity(1 + 48 + 4 + entries.len() * ENTRY);
    v.push(KIND_ENVELOPES);
    put_domain(&mut v, d);
    v.extend_from_slice(
        &u32::try_from(entries.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for (sid, bv, env) in entries {
        v.extend_from_slice(sid);
        v.extend_from_slice(&bv.to_be_bytes());
        v.extend_from_slice(env);
    }
    v
}

/// A kind-3 value: collection `cid` was dropped.
pub fn drop_value(cid: &[u8; 16]) -> Vec<u8> {
    let mut v = vec![KIND_DROP];
    v.extend_from_slice(cid);
    v
}

/// One parsed value.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Value {
    /// A bucket block.
    Block(Domain, u64, Vec<u8>),
    /// Re-wrapped envelopes.
    Envelopes(Domain, Vec<(Sid, u64, Envelope)>),
    /// A dropped collection.
    Drop([u8; 16]),
}

fn take<'a>(b: &mut &'a [u8], n: usize) -> Result<&'a [u8], Error> {
    if b.len() < n {
        return Err(bad());
    }
    let (head, rest) = b.split_at(n);
    *b = rest;
    Ok(head)
}

fn domain_of(b: &mut &[u8]) -> Result<Domain, Error> {
    Ok(Domain {
        collection_id: take(b, 16)?.try_into().map_err(|_| bad())?,
        group_id: take(b, 32)?.try_into().map_err(|_| bad())?,
    })
}

fn u64_of(b: &mut &[u8]) -> Result<u64, Error> {
    Ok(u64::from_be_bytes(
        take(b, 8)?.try_into().map_err(|_| bad())?,
    ))
}

/// Parses a store value strictly.
pub fn parse(value: &[u8]) -> Result<Value, Error> {
    let (&kind, mut b) = value.split_first().ok_or_else(bad)?;
    let v = match kind {
        KIND_BLOCK => {
            let d = domain_of(&mut b)?;
            let version = u64_of(&mut b)?;
            let block = take(&mut b, BLOCK_BYTES)?.to_vec();
            Value::Block(d, version, block)
        }
        KIND_ENVELOPES => {
            let d = domain_of(&mut b)?;
            let n = u32::from_be_bytes(take(&mut b, 4)?.try_into().map_err(|_| bad())?);
            let mut entries = Vec::new();
            for _ in 0..n {
                let sid: Sid = take(&mut b, 64)?.try_into().map_err(|_| bad())?;
                let bv = u64_of(&mut b)?;
                let env: Envelope = take(&mut b, ENVELOPE_BYTES)?
                    .try_into()
                    .map_err(|_| bad())?;
                entries.push((sid, bv, env));
            }
            Value::Envelopes(d, entries)
        }
        KIND_DROP => Value::Drop(take(&mut b, 16)?.try_into().map_err(|_| bad())?),
        _ => return Err(bad()),
    };
    if b.is_empty() { Ok(v) } else { Err(bad()) }
}

/// The participant's durable state: what the wrapped-key store and the WAL tail say, merged.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Durable {
    /// Each domain's newest bucket block: `(group_key_version, block)`.
    pub blocks: BTreeMap<Domain, (u64, Vec<u8>)>,
    /// Each re-wrapped record's newest envelope: `(bucket_version, envelope)`.
    pub envelopes: BTreeMap<(Domain, Sid), (u64, Envelope)>,
    /// Dropped collections.
    pub dropped: BTreeSet<[u8; 16]>,
}

impl Durable {
    /// Would merging `v` change this state? (Recovery writes back only such WAL values, G-43.)
    pub fn newer(&self, v: &Value) -> bool {
        match v {
            Value::Block(d, version, _) => self.blocks.get(d).is_none_or(|(old, _)| old < version),
            Value::Envelopes(d, entries) => entries.iter().any(|(sid, bv, _)| {
                self.envelopes
                    .get(&(*d, *sid))
                    .is_none_or(|(old, _)| old < bv)
            }),
            Value::Drop(cid) => !self.dropped.contains(cid),
        }
    }

    /// Merges one value (§14.8: the highest version wins; a drop is final).
    pub fn merge(&mut self, v: Value) {
        match v {
            Value::Block(d, version, block) => {
                if self.blocks.get(&d).is_none_or(|(old, _)| *old < version) {
                    self.blocks.insert(d, (version, block));
                }
            }
            Value::Envelopes(d, entries) => {
                for (sid, bv, env) in entries {
                    let k = (d, sid);
                    if self.envelopes.get(&k).is_none_or(|(old, _)| *old < bv) {
                        self.envelopes.insert(k, (bv, env));
                    }
                }
            }
            Value::Drop(cid) => {
                self.dropped.insert(cid);
            }
        }
        self.forget_dropped();
    }

    fn forget_dropped(&mut self) {
        if self.dropped.is_empty() {
            return;
        }
        let gone = |d: &Domain| self.dropped.contains(&d.collection_id);
        let dropped_blocks: Vec<Domain> = self.blocks.keys().filter(|d| gone(d)).copied().collect();
        for d in dropped_blocks {
            self.blocks.remove(&d);
        }
        let dropped = self.dropped.clone();
        self.envelopes
            .retain(|(d, _), _| !dropped.contains(&d.collection_id));
    }

    /// The store values that hold this state (for compaction), in a fixed order.
    pub fn values(&self) -> Vec<Vec<u8>> {
        let mut out: Vec<Vec<u8>> = self.dropped.iter().map(drop_value).collect();
        out.extend(self.blocks.iter().map(|(d, (v, b))| block_value(d, *v, b)));
        let mut by_domain: BTreeMap<Domain, Vec<(Sid, u64, Envelope)>> = BTreeMap::new();
        for ((d, sid), (bv, env)) in &self.envelopes {
            by_domain.entry(*d).or_default().push((*sid, *bv, *env));
        }
        for (d, entries) in by_domain {
            for chunk in entries.chunks(4_096) {
                out.push(envelopes_value(&d, chunk));
            }
        }
        out
    }
}
