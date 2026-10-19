//! The checks the kit applies to what the engine returns: the §11.3 steps (with the engine's own
//! primitives; the independent verifier is P3-T1's judge), and a model of the commitments: a
//! group's `C_S` is the sum of its members' `C_t` (§5.3, §9.3), which every certificate's
//! `C_S_pre` must equal.

use std::collections::{BTreeMap, BTreeSet};

use sever_cert::Certificate;
use sever_crypto::{
    DeletionContext, Generators, certificate_message, cosign_message, decode_point, encode_point,
    insert_message, transition_holds, verify, verify_signature,
};
use sever_db::Anchors;
use sever_index::Placement;
use sever_log::checkpoint::THRESHOLD;
use sever_log::merkle::{leaf_hash, verify_inclusion};
use sever_types::GroupId;

/// §11.3 steps 1–8 against `a`; the failed step's description on rejection.
pub fn accept(a: &Anchors, gens: &Generators, bytes: &[u8]) -> Result<Certificate, &'static str> {
    let c = Certificate::parse(bytes, a.d).map_err(|_| "step 1: parse")?;
    if c.c_t == [0; 32] {
        return Err("step 1: C_t is the identity");
    }
    let key = a
        .operator
        .get(c.key_period)
        .ok_or("step 2: unknown epoch")?;
    let body = bytes
        .get(..bytes.len().saturating_sub(69))
        .ok_or("step 1")?;
    verify_signature(key, &certificate_message(body), &c.operator_signature)
        .map_err(|_| "step 2: operator signature")?;
    let inc = &c.inclusion;
    let leaf = inc.leaf;
    if (
        leaf.collection_id,
        leaf.scrambled_id,
        leaf.c_t,
        leaf.user_signature,
    ) != (c.collection_id, c.scrambled_id, c.c_t, c.user_signature)
    {
        return Err("step 3: leaf fields");
    }
    verify_signature(
        &leaf.user_public_key,
        &insert_message(&leaf.collection_id, &leaf.c_t),
        &leaf.user_signature,
    )
    .map_err(|_| "step 3: user signature")?;
    let cp = inc.checkpoint;
    if !verify_inclusion(
        &leaf_hash(&leaf.to_bytes()),
        inc.leaf_index,
        cp.tree_size,
        &inc.path,
        &cp.root,
    ) || !cp.verify(&a.operator)
    {
        return Err("step 3: inclusion or checkpoint signature");
    }
    let good: BTreeSet<u8> = c
        .cosignatures
        .iter()
        .filter(|s| {
            a.witnesses
                .get(usize::from(s.witness_index))
                .and_then(|r| r.get(s.witness_epoch))
                .is_some_and(|k| {
                    verify_signature(k, &cosign_message(&cp.message()), &s.signature).is_ok()
                })
        })
        .map(|s| s.witness_index)
        .collect();
    if good.len() < THRESHOLD {
        return Err("step 4: witnesses");
    }
    if c.database_lsn <= inc.leaf_index {
        return Err("step 5: order");
    }
    if let Some(g) = &c.group {
        let pre = decode_point(&g.c_s_pre).map_err(|_| "step 1: C_S_pre")?;
        let post = decode_point(&g.c_s_post).map_err(|_| "step 1: C_S_post")?;
        let c_t = decode_point(&c.c_t).map_err(|_| "step 1: C_t")?;
        if !transition_holds(&post, &c_t, &pre) {
            return Err("step 6: transition");
        }
        let ctx = DeletionContext {
            c_s_pre: g.c_s_pre,
            c_t: c.c_t,
            scrambled_id: c.scrambled_id,
            database_lsn: c.database_lsn,
            collection_id: c.collection_id,
        };
        verify(gens, &g.c_s_post, &ctx, &g.proof).map_err(|_| "step 6: proof")?;
        if g.emptied != (g.c_s_post == [0; 32]) {
            return Err("step 6: emptied");
        }
    }
    Ok(c)
}

/// The commitment model: each group's members by scrambled ID, with their `C_t`.
#[derive(Clone, Debug, Default)]
pub struct Model {
    groups: BTreeMap<GroupId, BTreeMap<[u8; 64], [u8; 32]>>,
}

fn group_of(p: &Placement) -> GroupId {
    match p {
        Placement::Frozen(g) | Placement::Spawned(g) => *g,
        Placement::Holding => GroupId::Holding,
    }
}

impl Model {
    /// An insert the engine placed at `p`. A spawned group the model has not seen was created by a
    /// flush (§15.2): every holding record moves into it with this one.
    pub fn insert(&mut self, p: &Placement, sid: [u8; 64], c_t: [u8; 32]) {
        let g = group_of(p);
        if matches!(p, Placement::Spawned(_)) && !self.groups.contains_key(&g) {
            let moved = self.groups.remove(&GroupId::Holding).unwrap_or_default();
            self.groups.insert(g, moved);
        }
        self.groups.entry(g).or_default().insert(sid, c_t);
    }

    /// `Σ C_t` of the group's members (the identity for an empty group).
    pub fn commitment(&self, g: &GroupId) -> Option<[u8; 32]> {
        let mut total = decode_point(&[0; 32]).ok()?;
        for c in self.groups.get(g).into_iter().flat_map(BTreeMap::values) {
            total += decode_point(c).ok()?;
        }
        Some(encode_point(&total))
    }

    /// A certificate for a deletion from `g`: the record is a member, and for a group deletion
    /// `C_S_pre` is the model's `C_S`. Removes the record.
    pub fn delete(&mut self, g: &GroupId, c: &Certificate) -> Result<(), &'static str> {
        let members = self.groups.get(g).ok_or("model: unknown group")?;
        if members.get(&c.scrambled_id) != Some(&c.c_t) {
            return Err("model: the record is not a member with this C_t");
        }
        match (&c.group, *g == GroupId::Holding) {
            (Some(f), false) if Some(f.c_s_pre) == self.commitment(g) => {}
            (None, true) => {}
            _ => return Err("model: C_S_pre is not the sum of the members' C_t"),
        }
        if let Some(m) = self.groups.get_mut(g) {
            m.remove(&c.scrambled_id);
        }
        Ok(())
    }

    /// Every group the model knows, except the holding area.
    pub fn groups(&self) -> Vec<GroupId> {
        self.groups
            .keys()
            .filter(|g| **g != GroupId::Holding)
            .copied()
            .collect()
    }
}
