//! The audit of a log export (spec §11.3 "what it does not prove"; DB-86): what the auditor checks,
//! with log access, that no certificate can prove by itself.
//!
//! * Every delete leaf holds a certificate that verifies (§11.3) and names that leaf's own index as
//!   its `database_lsn`; a checkpoint larger than the log means leaves are missing (AF-1).
//! * A group's commitment is the sum of its members' `C_t` (§5.3, §9.3: commitments add), so
//!   replaying the placements gives every group's `C_S` before each deletion: a group
//!   certificate's `C_S_pre` must equal it, and the deleted record must be a member (AF-2). This
//!   checks that consecutive certificates of a group chain, inserts in between included.
//! * Consecutive checkpoints are consistent (RFC 9162 §2.1.4, the proof computed from the leaves),
//!   and one tree size has one root (AF-3).
//! * The leaf at the `database_lsn` of every certificate a user holds is `0x02 ‖` it (AF-4).
//! * Every checkpoint's root is the root of the leaves at its size (AF-5), and it is signed by the
//!   operator and, after the genesis, witnessed by four of five.

use std::collections::{BTreeMap, BTreeSet};

use curve25519_dalek::ristretto::{CompressedRistretto, RistrettoPoint};
use curve25519_dalek::traits::Identity;
use ed25519_dalek::{Signature, VerifyingKey};

use crate::anchors::Anchors;
use crate::cert::{CHECKPOINT_LEN, COSIGNATURE_LEN, Checkpoint, INSERT_LEAF_LEN, parse};
use crate::dst::DST_COSIGN;
use crate::gens::Generators;
use crate::hex;
use crate::merkle::{leaf_hash, node_hash};
use crate::verify::{THRESHOLD, checkpoint_message, verify};

/// One problem the audit found.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Finding {
    /// `AF-1` … `AF-5`, or `leaf`, `certificate`, `checkpoint` for a malformed or unsigned entry.
    pub kind: &'static str,
    /// The leaf index (or, for a checkpoint, its position in the export).
    pub at: u64,
    /// Why, in fixed words.
    pub why: &'static str,
}

/// One leaf's placement (DB-86): the group its record joined or left, and the group a flush
/// created.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Placement {
    /// `frozen-NNNN`, `spawn-…` or `holding`.
    pub group: String,
    /// The spawned group a flush created, if one did.
    pub flush: Option<String>,
}

/// A log export (DB-86).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Export {
    /// Every leaf, in order.
    pub leaves: Vec<Vec<u8>>,
    /// Every leaf's placement.
    pub placements: Vec<Placement>,
    /// Every checkpoint: `checkpoint (116) ‖ u8 count ‖ count × cosignature (69)`.
    pub checkpoints: Vec<Vec<u8>>,
}

impl Export {
    /// `{"version": 1, "leaves": [hex], "placements": [{"group", "flush"}], "checkpoints": [hex]}`.
    pub fn from_json(text: &str) -> Result<Self, &'static str> {
        let v: serde_json::Value = serde_json::from_str(text).map_err(|_| "not JSON")?;
        if v.get("version").and_then(serde_json::Value::as_u64) != Some(1) {
            return Err("not a version 1 export");
        }
        let list = |k: &str| {
            v.get(k)
                .and_then(serde_json::Value::as_array)
                .ok_or("a list is missing")
        };
        let hexes = |k: &str| -> Result<Vec<Vec<u8>>, &'static str> {
            list(k)?
                .iter()
                .map(|h| h.as_str().and_then(hex::decode).ok_or("not hex"))
                .collect()
        };
        let placements = list("placements")?
            .iter()
            .map(|p| {
                Ok(Placement {
                    group: p
                        .get("group")
                        .and_then(serde_json::Value::as_str)
                        .ok_or("a placement has no group")?
                        .to_owned(),
                    flush: p
                        .get("flush")
                        .and_then(serde_json::Value::as_str)
                        .map(str::to_owned),
                })
            })
            .collect::<Result<_, &'static str>>()?;
        Ok(Self {
            leaves: hexes("leaves")?,
            placements,
            checkpoints: hexes("checkpoints")?,
        })
    }
}

/// RFC 9162 §2.1.1 `MTH` of leaf hashes.
fn mth(h: &[[u8; 32]]) -> [u8; 32] {
    match h.len() {
        0 => sha2::Digest::finalize(<sha2::Sha256 as sha2::Digest>::new()).into(),
        1 => h.first().copied().unwrap_or_default(),
        n => {
            let k = split(n);
            node_hash(
                &mth(h.get(..k).unwrap_or_default()),
                &mth(h.get(k..).unwrap_or_default()),
            )
        }
    }
}

/// The largest power of two smaller than `n` (n > 1).
fn split(n: usize) -> usize {
    let mut k = 1;
    while k * 2 < n {
        k *= 2;
    }
    k
}

/// RFC 9162 §2.1.4.1 `SUBPROOF(m, D[n], b)`.
fn subproof(m: usize, h: &[[u8; 32]], b: bool, out: &mut Vec<[u8; 32]>) {
    let n = h.len();
    if m == n {
        if !b {
            out.push(mth(h));
        }
        return;
    }
    let k = split(n);
    if m <= k {
        subproof(m, h.get(..k).unwrap_or_default(), b, out);
        out.push(mth(h.get(k..).unwrap_or_default()));
    } else {
        subproof(m - k, h.get(k..).unwrap_or_default(), false, out);
        out.push(mth(h.get(..k).unwrap_or_default()));
    }
}

/// RFC 9162 §2.1.4.2: does `proof` show the tree of `first` leaves (root `r1`) is a prefix of the
/// tree of `second` leaves (root `r2`)? For `0 < first < second`.
fn verify_consistency(
    first: u64,
    second: u64,
    r1: &[u8; 32],
    r2: &[u8; 32],
    proof: &[[u8; 32]],
) -> bool {
    // 1. If consistency_path is an empty array, stop and fail the proof verification.
    if proof.is_empty() {
        return false;
    }
    // 2. If first is an exact power of 2, then prepend first_hash to the consistency_path array.
    let mut p = proof.to_vec();
    if first.is_power_of_two() {
        p.insert(0, *r1);
    }
    // 3. Set fn to first - 1 and sn to second - 1.
    let (mut f, mut s) = (first - 1, second - 1);
    // 4. If LSB(fn) is set, then right-shift both fn and sn equally until LSB(fn) is not set.
    while f & 1 == 1 {
        f >>= 1;
        s >>= 1;
    }
    // 5. Set both fr and sr to the first value in the consistency_path array.
    let Some((&first_value, rest)) = p.split_first() else {
        return false;
    };
    let (mut fr, mut sr) = (first_value, first_value);
    // 6. For each subsequent value c in the consistency_path array:
    for c in rest {
        // a. If sn is 0, then stop the iteration and fail the proof verification.
        if s == 0 {
            return false;
        }
        // b. If LSB(fn) is set, or if fn is equal to sn, then:
        if f & 1 == 1 || f == s {
            fr = node_hash(c, &fr);
            sr = node_hash(c, &sr);
            // iii. If LSB(fn) is not set, right-shift fn and sn until LSB(fn) is set or fn is 0.
            if f & 1 == 0 {
                while f & 1 == 0 && f != 0 {
                    f >>= 1;
                    s >>= 1;
                }
            }
        } else {
            // Otherwise: i. Set sr to HASH(0x01 || sr || c).
            sr = node_hash(&sr, c);
        }
        // c. Finally, right-shift both fn and sn one time.
        f >>= 1;
        s >>= 1;
    }
    // 7. fr equals first_hash, sr equals second_hash and sn is 0.
    &fr == r1 && &sr == r2 && s == 0
}

fn signed(public: &[u8; 32], msg: &[u8], sig: &[u8; 64]) -> bool {
    VerifyingKey::from_bytes(public)
        .is_ok_and(|k| k.verify_strict(msg, &Signature::from_bytes(sig)).is_ok())
}

struct Cosig {
    index: u8,
    epoch: u32,
    signature: [u8; 64],
}

fn witnessed(b: &[u8]) -> Option<(Checkpoint, Vec<Cosig>)> {
    let (cp, rest) = b.split_at_checked(CHECKPOINT_LEN)?;
    let (&n, cos) = rest.split_first()?;
    if cos.len() != COSIGNATURE_LEN * usize::from(n) {
        return None;
    }
    let checkpoint = Checkpoint {
        tree_size: u64::from_be_bytes(cp.get(..8)?.try_into().ok()?),
        root: cp.get(8..40)?.try_into().ok()?,
        timestamp_ms: u64::from_be_bytes(cp.get(40..48)?.try_into().ok()?),
        epoch: u32::from_be_bytes(cp.get(48..52)?.try_into().ok()?),
        signature: cp.get(52..116)?.try_into().ok()?,
    };
    let cosigs = cos
        .chunks_exact(COSIGNATURE_LEN)
        .map(|c| {
            Some(Cosig {
                index: *c.first()?,
                epoch: u32::from_be_bytes(c.get(1..5)?.try_into().ok()?),
                signature: c.get(5..69)?.try_into().ok()?,
            })
        })
        .collect::<Option<Vec<_>>>()?;
    Some((checkpoint, cosigs))
}

/// A group's members: scrambled_id → `C_t`.
type Members = BTreeMap<[u8; 64], [u8; 32]>;

fn sum(members: &Members) -> Option<[u8; 32]> {
    let mut total = RistrettoPoint::identity();
    for c in members.values() {
        total += CompressedRistretto(*c).decompress()?;
    }
    Some(total.compress().to_bytes())
}

/// Audits `export` against `anchors` (and `gens` of their dimension), with the certificates users
/// hold. Returns every finding; none for an honest log.
pub fn audit(
    export: &Export,
    anchors: &Anchors,
    gens: &Generators,
    held: &[Vec<u8>],
) -> Vec<Finding> {
    let mut out = Vec::new();
    let mut find = |kind, at: usize, why| {
        out.push(Finding {
            kind,
            at: at as u64,
            why,
        });
    };
    let n = export.leaves.len();
    if export.placements.len() != n {
        find("leaf", n, "placements and leaves differ in number");
    }
    // Members of each (collection, group): scrambled_id → C_t.
    let mut members: BTreeMap<([u8; 16], String), Members> = BTreeMap::new();
    let none = Placement {
        group: String::new(),
        flush: None,
    };
    for (i, leaf) in export.leaves.iter().enumerate() {
        let pl = export.placements.get(i).unwrap_or(&none);
        if leaf.first() == Some(&0x01) && leaf.len() == INSERT_LEAF_LEN {
            let (Some(coll), Some(sid), Some(c_t)) = (
                leaf.get(1..17).and_then(|b| <[u8; 16]>::try_from(b).ok()),
                leaf.get(17..81).and_then(|b| <[u8; 64]>::try_from(b).ok()),
                leaf.get(81..113).and_then(|b| <[u8; 32]>::try_from(b).ok()),
            ) else {
                continue;
            };
            match &pl.flush {
                Some(created) => {
                    // §15.2: the flush moves every holding record, this one included.
                    let mut moved = members
                        .remove(&(coll, "holding".to_owned()))
                        .unwrap_or_default();
                    moved.insert(sid, c_t);
                    members
                        .entry((coll, created.clone()))
                        .or_default()
                        .extend(moved);
                    if &pl.group != created {
                        find(
                            "AF-2",
                            i,
                            "a flushed record is not in the group the flush created",
                        );
                    }
                }
                None => {
                    members
                        .entry((coll, pl.group.clone()))
                        .or_default()
                        .insert(sid, c_t);
                }
            }
            continue;
        }
        let Some(cert) = leaf.strip_prefix(&[0x02]) else {
            find("leaf", i, "neither an insert leaf nor a delete leaf");
            continue;
        };
        if verify(cert, anchors, gens).is_err() {
            find("certificate", i, "the certificate does not verify (§11.3)");
            continue;
        }
        let Ok(c) = parse(cert, anchors.d) else {
            continue;
        };
        if c.database_lsn != i as u64 {
            find(
                "AF-1",
                i,
                "its certificate names another leaf: a leaf is missing or out of place",
            );
        }
        let group = members
            .entry((c.collection_id, pl.group.clone()))
            .or_default();
        if group.get(&c.scrambled_id) != Some(&c.c_t) {
            find("AF-2", i, "the record is not a member of the group it left");
        } else if c.deletion_kind == 0 {
            if pl.group == "holding" || sum(group) != c.c_s_pre {
                find("AF-2", i, "C_S_pre is not the group's commitment");
            }
        } else if pl.group != "holding" {
            find("AF-2", i, "a holding-area certificate for a group record");
        }
        group.remove(&c.scrambled_id);
    }
    // Checkpoints.
    let hashes: Vec<[u8; 32]> = export.leaves.iter().map(|l| leaf_hash(l)).collect();
    let mut roots: BTreeMap<u64, [u8; 32]> = BTreeMap::new();
    let mut prev: Option<Checkpoint> = None;
    for (j, entry) in export.checkpoints.iter().enumerate() {
        let Some((cp, cosigs)) = witnessed(entry) else {
            find("checkpoint", j, "malformed");
            continue;
        };
        let msg = checkpoint_message(&cp);
        if !anchors
            .operator
            .get(&cp.epoch)
            .is_some_and(|k| signed(k, &msg, &cp.signature))
        {
            find("checkpoint", j, "the operator signature does not verify");
        }
        if j > 0 {
            // The genesis checkpoint is not cosigned (DB-79).
            let cosign = [DST_COSIGN, &msg].concat();
            let good: BTreeSet<u8> = cosigs
                .iter()
                .filter(|c| {
                    anchors
                        .witnesses
                        .get(&(c.index, c.epoch))
                        .is_some_and(|k| signed(k, &cosign, &c.signature))
                })
                .map(|c| c.index)
                .collect();
            if good.len() < THRESHOLD {
                find("checkpoint", j, "fewer than four distinct witnesses");
            }
        }
        let size = usize::try_from(cp.tree_size).unwrap_or(usize::MAX);
        match hashes.get(..size) {
            None => find("AF-1", j, "a checkpoint covers leaves the export lacks"),
            Some(prefix) if mth(prefix) != cp.root => {
                find("AF-5", j, "the root is not the tree's at its size")
            }
            Some(_) => {}
        }
        if roots.get(&cp.tree_size).is_some_and(|r| *r != cp.root) {
            find("AF-3", j, "two roots for one tree size");
        }
        roots.insert(cp.tree_size, cp.root);
        if let Some(p) = &prev {
            if p.tree_size > 0 && p.tree_size < cp.tree_size && size <= n {
                let first = usize::try_from(p.tree_size).unwrap_or(usize::MAX);
                let mut proof = Vec::new();
                subproof(
                    first,
                    hashes.get(..size).unwrap_or_default(),
                    true,
                    &mut proof,
                );
                if !verify_consistency(p.tree_size, cp.tree_size, &p.root, &cp.root, &proof) {
                    find("AF-3", j, "not consistent with the previous checkpoint");
                }
            }
        }
        prev = Some(cp);
    }
    // Certificates users hold: the leaf at their database_lsn must be theirs.
    for h in held {
        let lsn = parse(h, anchors.d)
            .map(|c| c.database_lsn)
            .unwrap_or(u64::MAX);
        let at = usize::try_from(lsn).unwrap_or(usize::MAX);
        let mine = [&[0x02][..], h].concat();
        if export.leaves.get(at) != Some(&mine) {
            find(
                "AF-4",
                at,
                "the leaf at database_lsn is not this certificate",
            );
        }
    }
    out
}
