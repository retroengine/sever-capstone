//! The verification algorithm (spec §11.3, steps 1–8). A rejection names the step that failed.

use std::collections::BTreeSet;

use curve25519_dalek::ristretto::{CompressedRistretto, RistrettoPoint};
use curve25519_dalek::traits::Identity;
use ed25519_dalek::{Signature, VerifyingKey};

use crate::anchors::Anchors;
use crate::cert::{Certificate, Checkpoint, parse};
use crate::dst::{DST_CERT, DST_COSIGN, DST_INSERT, DST_STH};
use crate::gens::Generators;
use crate::merkle;
use crate::posk;

/// §10.4: a log checkpoint is witnessed with four of five cosignatures.
pub const THRESHOLD: usize = 4;

/// A rejection: the §11.3 step that failed and why (no input bytes).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Rejection {
    /// 1 … 7.
    pub step: u8,
    /// A fixed description of the failed check.
    pub reason: &'static str,
}

/// What an accepted certificate states.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Accepted {
    /// 0 = from a group, 1 = from the holding area.
    pub deletion_kind: u8,
    /// The deletion's own leaf index.
    pub database_lsn: u64,
    /// The insert leaf's index.
    pub leaf_index: u64,
    /// Tag 11.
    pub group_emptied: bool,
    /// Tag 13.
    pub collection_id: [u8; 16],
    /// Tag 3, for a group deletion (what the auditor chains, §11.3).
    pub c_s_post: Option<[u8; 32]>,
    /// Tag 2, for a group deletion.
    pub c_s_pre: Option<[u8; 32]>,
}

fn reject(step: u8, reason: &'static str) -> Rejection {
    Rejection { step, reason }
}

fn point(b: &[u8; 32]) -> Option<RistrettoPoint> {
    CompressedRistretto(*b).decompress()
}

/// `verify_strict` (§9.8).
fn signed(public: &[u8; 32], msg: &[u8], sig: &[u8; 64]) -> bool {
    VerifyingKey::from_bytes(public)
        .is_ok_and(|k| k.verify_strict(msg, &Signature::from_bytes(sig)).is_ok())
}

/// `DST_STH ‖ u64be tree_size ‖ root ‖ u64be timestamp_ms ‖ u32be epoch` (§9.8, 66 bytes).
pub fn checkpoint_message(c: &Checkpoint) -> Vec<u8> {
    let mut m = DST_STH.to_vec();
    m.extend_from_slice(&c.tree_size.to_be_bytes());
    m.extend_from_slice(&c.root);
    m.extend_from_slice(&c.timestamp_ms.to_be_bytes());
    m.extend_from_slice(&c.epoch.to_be_bytes());
    m
}

fn concat(parts: &[&[u8]]) -> Vec<u8> {
    parts.concat()
}

/// Verifies `bytes` against `anchors`, with the generators of `anchors.d` (§11.3).
pub fn verify(bytes: &[u8], anchors: &Anchors, gens: &Generators) -> Result<Accepted, Rejection> {
    if gens.d() != anchors.d {
        return Err(reject(
            1,
            "the generators are not of the anchors' dimension",
        ));
    }
    // 1. Parse strictly (§11.1). Decode every point and scalar canonically. C_t is not the identity.
    let c: Certificate = parse(bytes, anchors.d).map_err(|e| reject(1, e.0))?;
    let c_t = point(&c.c_t).ok_or(reject(1, "C_t is not a canonical point"))?;
    let pre = match &c.c_s_pre {
        Some(b) => Some(point(b).ok_or(reject(1, "C_S_pre is not a canonical point"))?),
        None => None,
    };
    let post = match &c.c_s_post {
        Some(b) => Some(point(b).ok_or(reject(1, "C_S_post is not a canonical point"))?),
        None => None,
    };
    let proof = if c.proof.is_empty() {
        None
    } else {
        Some(
            posk::decode(&c.proof, anchors.d)
                .ok_or(reject(1, "the proof holds a non-canonical point or scalar"))?,
        )
    };
    if c_t == RistrettoPoint::identity() {
        return Err(reject(1, "C_t is the identity"));
    }
    // 2. Operator signature: the key for tag 8's epoch is in the anchors; verify the trailer.
    let op = anchors
        .operator
        .get(&c.key_period)
        .ok_or(reject(2, "unknown operator epoch"))?;
    if !signed(op, &concat(&[DST_CERT, &c.body]), &c.signature) {
        return Err(reject(2, "the operator signature does not verify"));
    }
    // 3. Insert inclusion (tag 6).
    let inc = &c.inclusion;
    let leaf = &inc.leaf;
    if leaf.first() != Some(&0x01) {
        return Err(reject(3, "the leaf is not an insert leaf"));
    }
    let (l_coll, l_sid, l_ct, l_upk, l_sig) = (
        leaf.get(1..17),
        leaf.get(17..81),
        leaf.get(81..113),
        leaf.get(113..145),
        leaf.get(145..209),
    );
    if l_coll != Some(&c.collection_id[..])
        || l_sid != Some(&c.scrambled_id[..])
        || l_ct != Some(&c.c_t[..])
        || l_sig != Some(&c.user_signature[..])
    {
        return Err(reject(
            3,
            "the leaf's fields differ from tags 13, 9, 1 and 5",
        ));
    }
    let upk: [u8; 32] = l_upk
        .and_then(|k| k.try_into().ok())
        .ok_or(reject(3, "the leaf is truncated"))?;
    if !signed(
        &upk,
        &concat(&[DST_INSERT, &c.collection_id, &c.c_t]),
        &c.user_signature,
    ) {
        return Err(reject(3, "the user signature does not verify"));
    }
    let cp = &inc.checkpoint;
    if !merkle::verify_inclusion(
        &merkle::leaf_hash(leaf),
        inc.leaf_index,
        cp.tree_size,
        &inc.path,
        &cp.root,
    ) {
        return Err(reject(
            3,
            "the inclusion path does not lead to the checkpoint's root",
        ));
    }
    let cp_msg = checkpoint_message(cp);
    let cp_key = anchors
        .operator
        .get(&cp.epoch)
        .ok_or(reject(3, "the checkpoint's operator epoch is unknown"))?;
    if !signed(cp_key, &cp_msg, &cp.signature) {
        return Err(reject(
            3,
            "the checkpoint's operator signature does not verify",
        ));
    }
    // 4. Witnesses (tag 7): at least four cosignatures from distinct witnesses, each valid for its
    //    epoch, over that log checkpoint.
    let cosign_msg = concat(&[DST_COSIGN, &cp_msg]);
    let good: BTreeSet<u8> = c
        .cosignatures
        .iter()
        .filter(|s| {
            anchors
                .witnesses
                .get(&(s.witness_index, s.witness_epoch))
                .is_some_and(|k| signed(k, &cosign_msg, &s.signature))
        })
        .map(|s| s.witness_index)
        .collect();
    if good.len() < THRESHOLD {
        return Err(reject(4, "fewer than four distinct valid cosignatures"));
    }
    // 5. Ordering: database_lsn > leaf_index.
    if c.database_lsn <= inc.leaf_index {
        return Err(reject(5, "database_lsn is not after the insert leaf"));
    }
    match c.deletion_kind {
        // 6. From a group.
        0 => {
            let (Some(pre_b), Some(post_b), Some(pre), Some(post), Some(proof)) =
                (&c.c_s_pre, &c.c_s_post, pre, post, &proof)
            else {
                return Err(reject(6, "a group deletion needs tags 2, 3 and 4"));
            };
            if post + c_t != pre {
                return Err(reject(6, "C_S_post + C_t differs from C_S_pre"));
            }
            let ctx = posk::ctx(
                pre_b,
                &c.c_t,
                &c.scrambled_id,
                c.database_lsn,
                &c.collection_id,
            );
            if !posk::verify(gens, post_b, &post, &ctx, proof) {
                return Err(reject(6, "the proof of knowledge does not verify"));
            }
            if (c.group_emptied == 1) != (post == RistrettoPoint::identity()) {
                return Err(reject(6, "group_emptied disagrees with C_S_post"));
            }
        }
        // 7. From the holding area: tags 2, 3 and 4 are empty and tag 11 is 0.
        _ => {
            if c.c_s_pre.is_some() || c.c_s_post.is_some() || proof.is_some() {
                return Err(reject(
                    7,
                    "a holding-area certificate carries tags 2, 3 or 4",
                ));
            }
            if c.group_emptied != 0 {
                return Err(reject(7, "a holding-area certificate has tag 11 = 1"));
            }
        }
    }
    // 8. Every step passed.
    Ok(Accepted {
        deletion_kind: c.deletion_kind,
        database_lsn: c.database_lsn,
        leaf_index: inc.leaf_index,
        group_emptied: c.group_emptied == 1,
        collection_id: c.collection_id,
        c_s_post: c.c_s_post,
        c_s_pre: c.c_s_pre,
    })
}
