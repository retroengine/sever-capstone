//! The index: groups, slots, locator, holding area, routing, flush, `plan` and `apply`
//! (spec §5, §7; Build §4.5).

use std::collections::HashMap;

use sever_partition::PartitionArtefact;
use sever_quant::QVec;
use sever_types::constants::{MAX_GROUP_MEMBERS, SCALE, SPAWN_TARGET_SIZE};
use sever_types::{CollectionId, Error, GroupId, RecordId, ScrambledId};
use sha2::{Digest, Sha256};

use crate::blob::canonical_blob;
#[cfg(feature = "test-hooks")]
use crate::blob::{GroupSnapshot, snapshot_from_members};
use crate::changeset::{
    ChangeSet, Counters, CreatedGroup, GroupChange, GroupState, LocatorOp, Outcome, Placement,
    Slot, SlotOp,
};
use crate::ext::GroupExtension;
use crate::route::{mahalanobis, sq_dist_f64};
use crate::scramble::IdScrambler;

/// Index configuration (Build §4.3).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct IndexConfig {
    /// When `false`, every vector goes to its nearest frozen group: the frozen-only control arm
    /// (overview §10.7) and the whole-index twin test (Build §4.7 L6).
    pub spawning_enabled: bool,
    /// §7.4: the holding area flushes at exactly this many records. 200 in v1; small fixtures
    /// use less (gap G-10).
    pub spawn_target: usize,
}

impl Default for IndexConfig {
    fn default() -> Self {
        Self {
            spawning_enabled: true,
            spawn_target: SPAWN_TARGET_SIZE,
        }
    }
}

/// The three kinds of group (§5.1).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GroupKind {
    /// From the artefact; accumulator; searchable.
    Frozen,
    /// From a flush; accumulator; searchable.
    Spawned,
    /// The holding area: no accumulator, not searchable.
    Holding,
}

/// An insert request (§16.1 shape; Part 1's credential is `()`).
pub struct InsertRequest<E: GroupExtension> {
    /// §3.2 record ID, validated in `plan`.
    pub record_id: String,
    /// `d` float32 values, normalised (§4.1, checked in `plan`).
    pub vector: Vec<f32>,
    /// What the extension needs to admit the insert (EP-1 capability 3).
    pub credential: E::Credential,
}

/// A delete request (§16.1): no `r_t`, no credential (DB-55).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DeleteRequest {
    /// The record to delete.
    pub record_id: String,
}

/// Global numbers (§16.1 `stats`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Stats {
    /// Frozen groups.
    pub frozen: u64,
    /// Spawned groups.
    pub spawned: u64,
    /// `N`.
    pub big_n: u64,
    /// `k`.
    pub k: u64,
    /// Records waiting in the holding area.
    pub holding: u64,
}

/// A searchable group as `sever-search` sees it (§8; mirror §12.6).
pub struct SearchGroup<'a> {
    /// The group ID (the rank tie-break, §8.1).
    pub id: GroupId,
    /// Its centroid (`d` values).
    pub centroid: &'a [f64],
    /// Record IDs of the mirror rows, row for row.
    pub ids: &'a [RecordId],
    /// The float32 mirror: `x̂` of each member, `d` values per row (§4.3).
    pub rows: &'a [f32],
}

struct Group<E: GroupExtension> {
    id: GroupId,
    kind: GroupKind,
    centroid: Vec<f64>,
    state: GroupState<E>,
    slots: Vec<Slot<E>>,
    mirror_ids: Vec<RecordId>,
    mirror: Vec<f32>,
}

impl<E: GroupExtension> Group<E> {
    fn new(id: GroupId, kind: GroupKind, centroid: Vec<f64>, d: usize) -> Self {
        Self {
            id,
            kind,
            centroid,
            state: GroupState::empty(d),
            slots: Vec::new(),
            mirror_ids: Vec::new(),
            mirror: Vec::new(),
        }
    }
}

/// One collection's index over a frozen partition (Part 1).
pub struct Index<E: GroupExtension, S: IdScrambler> {
    cfg: IndexConfig,
    d: usize,
    tau: f64,
    precision: Vec<f64>,
    k_frozen: usize,
    collection_id: CollectionId,
    ext: E,
    scrambler: S,
    /// Frozen groups in label order, then spawned groups in creation order.
    groups: Vec<Group<E>>,
    pos: HashMap<GroupId, usize>,
    holding: Group<E>,
    locator: HashMap<ScrambledId, (GroupId, usize)>,
    big_n: u64,
}

/// §5.6, §7.3: a spawned group has room iff `2·k·n < 3·N`, in exact integers.
pub fn has_room(n: u64, k: u64, big_n: u64) -> bool {
    2 * u128::from(k) * u128::from(n) < 3 * u128::from(big_n)
}

/// §7.5: `spawn-` + the first 16 hex characters of
/// `SHA-256(‖_{ids ascending by bytes} u16be(len) ‖ id)`.
pub fn spawn_id<'a>(founders: impl IntoIterator<Item = &'a RecordId>) -> GroupId {
    let mut ids: Vec<&RecordId> = founders.into_iter().collect();
    ids.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
    let mut h = Sha256::new();
    for id in ids {
        h.update((id.len_bytes() as u16).to_be_bytes()); // ≤ 256 (§3.2)
        h.update(id.as_bytes());
    }
    let digest: [u8; 32] = h.finalize().into();
    let mut prefix = [0u8; 8];
    prefix.copy_from_slice(digest.get(..8).unwrap_or(&[0; 8]));
    GroupId::Spawned(prefix)
}

impl<E: GroupExtension, S: IdScrambler> Index<E, S> {
    /// A new, empty index over `artefact`'s frozen partition (§5.1: frozen groups and one holding
    /// area exist from creation). `k_scramble` is already inside `scrambler`.
    pub fn new(
        artefact: &PartitionArtefact,
        cfg: IndexConfig,
        ext: E,
        scrambler: S,
        collection_id: CollectionId,
    ) -> Result<Self, Error> {
        if cfg.spawn_target == 0 {
            return Err(Error::IntegrityViolation {
                invariant: "§7.4 spawn target 0",
            });
        }
        let d = artefact.d;
        let mut groups = Vec::with_capacity(artefact.k_frozen);
        let mut pos = HashMap::new();
        for (label, mu) in artefact.centroids.chunks_exact(d).enumerate() {
            let id = u16::try_from(label).ok().and_then(GroupId::frozen).ok_or(
                Error::IntegrityViolation {
                    invariant: "§5.1 frozen label",
                },
            )?;
            pos.insert(id, groups.len());
            groups.push(Group::new(id, GroupKind::Frozen, mu.to_vec(), d));
        }
        Ok(Self {
            cfg,
            d,
            tau: artefact.tau,
            precision: artefact.precision.clone(),
            k_frozen: artefact.k_frozen,
            collection_id,
            ext,
            scrambler,
            groups,
            pos,
            holding: Group::new(GroupId::Holding, GroupKind::Holding, vec![0.0; d], d),
            locator: HashMap::new(),
            big_n: 0,
        })
    }

    /// The dimension `d`.
    pub fn d(&self) -> usize {
        self.d
    }

    /// `k`: frozen plus spawned groups (§2.1).
    pub fn k(&self) -> u64 {
        self.groups.len() as u64
    }

    fn group(&self, id: &GroupId) -> Option<&Group<E>> {
        match id {
            GroupId::Holding => Some(&self.holding),
            _ => self.pos.get(id).and_then(|&i| self.groups.get(i)),
        }
    }

    fn group_mut(&mut self, id: &GroupId) -> Option<&mut Group<E>> {
        match id {
            GroupId::Holding => Some(&mut self.holding),
            _ => self.pos.get(id).and_then(|&i| self.groups.get_mut(i)),
        }
    }

    // --- routing (§7) ------------------------------------------------------------------------

    /// §7.3: the destination of `x`, and whether it is out of distribution. A pure function of
    /// `(x̃, state)` (INV-16); `k` and `N` are the values before this insert.
    pub fn route(&self, x: &QVec) -> Result<(GroupId, bool), Error> {
        let xhat = x.dequantise_f64(); // §4.3: float64, exact
        // §7.1: nearest frozen group; strict `<` keeps the first (smaller) label on a tie.
        let mut best: Option<(&Group<E>, f64)> = None;
        for g in self.groups.iter().take(self.k_frozen) {
            let dist = sq_dist_f64(&xhat, &g.centroid);
            if best.is_none_or(|(_, b)| dist < b) {
                best = Some((g, dist));
            }
        }
        let (nearest, _) = best.ok_or(Error::IntegrityViolation {
            invariant: "§7.1 no frozen group",
        })?;
        if !self.cfg.spawning_enabled {
            return Ok((nearest.id, false));
        }
        // §7.2: the drift test against the frozen partition.
        if mahalanobis(&xhat, &nearest.centroid, &self.precision)? <= self.tau {
            return Ok((nearest.id, false));
        }
        // SB-8: the holding area before spillover.
        if cfg!(feature = "sabotage-SB-8") {
            return Ok((GroupId::Holding, true));
        }
        // §7.3: out of distribution. Spillover first: the nearest spawned group with room,
        // ties to the smaller group-ID bytes.
        let (k, big_n) = (self.k(), self.big_n);
        let mut spill: Option<(&Group<E>, f64)> = None;
        for g in self.groups.iter().skip(self.k_frozen) {
            if !has_room(g.state.n, k, big_n) {
                continue;
            }
            // SB-7: "the most recently created group with room" (the last one in creation order).
            if cfg!(feature = "sabotage-SB-7") {
                spill = Some((g, 0.0));
                continue;
            }
            let dist = sq_dist_f64(&xhat, &g.centroid);
            if spill.is_none_or(|(b, bd)| dist < bd || (dist == bd && g.id < b.id)) {
                spill = Some((g, dist));
            }
        }
        Ok(spill.map_or((GroupId::Holding, true), |(g, _)| (g.id, true)))
    }

    // --- plan (pure) ---------------------------------------------------------------------------

    /// Plans an insert (§15.1 checks in order: §4.1, §3.2, not live, admission; then §7.3
    /// routing, the §5.6 cap, and a flush at the spawn target). Never mutates.
    pub fn plan_insert(&self, req: InsertRequest<E>) -> Result<ChangeSet<E>, Error> {
        let x = sever_quant::quantise(&req.vector, self.d)?; // §4.1–4.2, no bypass (INV-1)
        let record_id = RecordId::new(req.record_id)?; // §3.2 rules 1–2
        let scrambled_id = self.scrambler.scramble(&self.collection_id, &record_id); // §9.7
        let mut draft = Draft::new(self);
        // §3.2 rule 3: not live. A retry is recognised by the extension (EP-1 capability 9).
        if let Some(live) = draft.lookup(&scrambled_id) {
            let same = self
                .ext
                .same_commitment(&live.x, &live.ext, &x, &req.credential);
            return Err(Error::DuplicateRecord {
                same_commitment: same,
            });
        }
        let ext = self.ext.admit(&x, req.credential)?; // EP-1 capability 3
        let (dest, _) = self.route(&x)?;
        let slot = Slot {
            scrambled_id,
            record_id,
            x,
            ext,
        };
        match self.group(&dest).map(|g| g.kind) {
            Some(GroupKind::Holding) => {
                if self.holding.slots.len() + 1 == self.cfg.spawn_target {
                    draft.flush(slot)?; // §7.4: same transaction
                } else {
                    draft.put(GroupId::Holding, slot);
                    draft.cs.outcomes.push(Outcome::Placed(Placement::Holding));
                }
            }
            Some(kind) => {
                let n = self.group(&dest).map_or(0, |g| g.state.n);
                if n + 1 > MAX_GROUP_MEMBERS {
                    return Err(Error::GroupCapacityExceeded); // §5.6, INV-4
                }
                draft.join(dest, slot);
                let placement = match kind {
                    GroupKind::Spawned => Placement::Spawned(dest),
                    _ => Placement::Frozen(dest),
                };
                draft.cs.outcomes.push(Outcome::Placed(placement));
            }
            None => {
                return Err(Error::IntegrityViolation {
                    invariant: "§7.3 unknown group",
                });
            }
        }
        Ok(draft.finish())
    }

    /// Plans one delete. `AlreadyAbsent` is an outcome, not an error (§5.4).
    pub fn plan_delete(&self, req: DeleteRequest) -> Result<ChangeSet<E>, Error> {
        self.plan_delete_many(vec![req])
    }

    /// Plans a `delete_user` (§3.5): every record in list order, as one atomic `ChangeSet`;
    /// each step sees the state the previous one left (§15.3).
    pub fn plan_delete_many(&self, reqs: Vec<DeleteRequest>) -> Result<ChangeSet<E>, Error> {
        let mut draft = Draft::new(self);
        for req in reqs {
            draft.delete(&req.record_id)?;
        }
        Ok(draft.finish())
    }

    // --- apply (infallible) --------------------------------------------------------------------

    /// Installs a `ChangeSet` produced by `plan` on this exact state. Cannot fail: every check
    /// happened in `plan` (Build §1.1).
    pub fn apply(&mut self, cs: ChangeSet<E>) {
        let d = self.d;
        for c in cs.created {
            self.pos.insert(c.id, self.groups.len());
            self.groups
                .push(Group::new(c.id, GroupKind::Spawned, c.centroid, d));
        }
        for gc in cs.groups {
            if let Some(g) = self.group_mut(&gc.group) {
                g.state = gc.after;
                // SB-1: flip one bit of a group sum on every deletion.
                if cfg!(feature = "sabotage-SB-1") && gc.before.n > g.state.n {
                    if let Some(v) = g.state.s.first_mut() {
                        *v ^= 1;
                    }
                }
            }
        }
        for op in cs.slots {
            match op {
                SlotOp::Put { group, slot, .. } => {
                    if let Some(g) = self.group_mut(&group) {
                        if g.kind != GroupKind::Holding {
                            g.mirror_ids.push(slot.record_id.clone());
                            g.mirror.extend(slot.x.dequantise_f32()); // §4.3, §12.6
                        }
                        g.slots.push(slot);
                    }
                }
                SlotOp::MoveLast { group, from, to } => {
                    if let Some(g) = self.group_mut(&group) {
                        if from < g.slots.len() && to < g.slots.len() {
                            g.slots.swap(from, to);
                        }
                        if from < g.mirror_ids.len() && to < g.mirror_ids.len() {
                            g.mirror_ids.swap(from, to);
                            for c in 0..d {
                                let (a, b) = (from * d + c, to * d + c);
                                if a < g.mirror.len() && b < g.mirror.len() {
                                    g.mirror.swap(a, b);
                                }
                            }
                        }
                    }
                }
                SlotOp::Truncate { group, len } => {
                    if let Some(g) = self.group_mut(&group) {
                        // §12.6: overwrite the removed mirror rows before they are released.
                        // SB-5: keep the deleted vector in the search mirror.
                        if !cfg!(feature = "sabotage-SB-5") {
                            if let Some(tail) = g.mirror.get_mut(len * d..) {
                                tail.fill(0.0);
                            }
                            g.mirror.truncate(len * d);
                            g.mirror_ids.truncate(len); // RecordId zeroes itself on drop
                        }
                        g.slots.truncate(len);
                    }
                }
                SlotOp::DrainInto { from, to } => {
                    let moved = self.group_mut(&from).map(|g| std::mem::take(&mut g.slots));
                    if let (Some(moved), Some(g)) = (moved, self.group_mut(&to)) {
                        for slot in moved {
                            g.mirror_ids.push(slot.record_id.clone());
                            g.mirror.extend(slot.x.dequantise_f32());
                            g.slots.push(slot);
                        }
                    }
                }
            }
        }
        for op in cs.locator {
            match op {
                LocatorOp::Put {
                    scrambled_id,
                    group,
                    index,
                } => {
                    self.locator.insert(scrambled_id, (group, index));
                }
                LocatorOp::Delete { scrambled_id } => {
                    self.locator.remove(&scrambled_id);
                }
            }
        }
        self.big_n = cs.counters_after.big_n;
    }

    /// `plan_insert` then `apply` (Build §4.5: Part 1's convenience wrapper).
    pub fn insert(&mut self, req: InsertRequest<E>) -> Result<Placement, Error> {
        let cs = self.plan_insert(req)?;
        let out = match cs.outcomes.first() {
            Some(Outcome::Placed(p)) => *p,
            _ => Placement::Holding,
        };
        self.apply(cs);
        Ok(out)
    }

    /// `plan_delete` then `apply`.
    pub fn delete(&mut self, req: DeleteRequest) -> Result<Outcome, Error> {
        let cs = self.plan_delete(req)?;
        let out = cs
            .outcomes
            .first()
            .copied()
            .unwrap_or(Outcome::AlreadyAbsent);
        self.apply(cs);
        Ok(out)
    }

    /// `plan_delete_many` then `apply`: one atomic unit.
    pub fn delete_many(&mut self, reqs: Vec<DeleteRequest>) -> Result<Vec<Outcome>, Error> {
        let cs = self.plan_delete_many(reqs)?;
        let out = cs.outcomes.clone();
        self.apply(cs);
        Ok(out)
    }

    // --- observation ---------------------------------------------------------------------------

    /// §16.1 `stats`.
    pub fn stats(&self) -> Stats {
        let spawned = (self.groups.len() - self.k_frozen) as u64;
        Stats {
            frozen: self.k_frozen as u64,
            spawned,
            big_n: self.big_n,
            k: self.k(),
            holding: self.holding.slots.len() as u64,
        }
    }

    /// Every frozen and spawned group ID: frozen in label order, then spawned in creation order.
    pub fn group_ids(&self) -> Vec<GroupId> {
        self.groups.iter().map(|g| g.id).collect()
    }

    /// Where a live record is: its group (or `Holding`), or `None`.
    pub fn location(&self, record_id: &str) -> Option<GroupId> {
        let rid = RecordId::new(record_id).ok()?;
        let s = self.scrambler.scramble(&self.collection_id, &rid);
        self.locator.get(&s).map(|(g, _)| *g)
    }

    /// `n` of a group, or of the holding area.
    pub fn group_len(&self, id: &GroupId) -> Option<usize> {
        self.group(id).map(|g| g.slots.len())
    }

    /// The canonical blob of a frozen or spawned group (§5.5).
    pub fn blob(&self, id: &GroupId) -> Option<Vec<u8>> {
        let g = self.group(id).filter(|g| g.kind != GroupKind::Holding)?;
        let members: Vec<(&RecordId, &QVec)> =
            g.slots.iter().map(|s| (&s.record_id, &s.x)).collect();
        Some(canonical_blob(&self.ext, self.d, &g.state, &members))
    }

    /// The searchable groups (frozen and spawned; never the holding area) for `sever-search`.
    pub fn search_groups(&self) -> impl Iterator<Item = SearchGroup<'_>> {
        self.groups.iter().map(|g| SearchGroup {
            id: g.id,
            centroid: &g.centroid,
            ids: &g.mirror_ids,
            rows: &g.mirror,
        })
    }

    /// §16.1 `group_snapshot` (test hooks only): the five fields of §5.5.
    #[cfg(feature = "test-hooks")]
    pub fn group_snapshot(&self, id: &GroupId) -> Option<GroupSnapshot<E>> {
        let g = self.group(id).filter(|g| g.kind != GroupKind::Holding)?;
        let mut member_ids: Vec<RecordId> = g.slots.iter().map(|s| s.record_id.clone()).collect();
        member_ids.sort();
        Some(GroupSnapshot {
            s: g.state.s.clone(),
            n: g.state.n,
            ext_public: g.state.ext_public.clone(),
            blob: self.blob(id)?,
            member_ids,
        })
    }

    /// The same group rebuilt from its surviving members alone (test hooks only): the "as if
    /// never inserted" side of the survivors check (Build §4.7 L6).
    #[cfg(feature = "test-hooks")]
    pub fn survivors_snapshot(&self, id: &GroupId) -> Option<GroupSnapshot<E>> {
        let g = self.group(id).filter(|g| g.kind != GroupKind::Holding)?;
        let members: Vec<_> = g
            .slots
            .iter()
            .map(|s| (&s.record_id, &s.x, &s.ext))
            .collect();
        Some(snapshot_from_members(&self.ext, self.d, &members))
    }

    /// The §21 invariants Part 1 owns: INV-4 to INV-9 (and the extension's own, EP-1 cap. 8).
    pub fn check_invariants(&self) -> Result<(), Error> {
        let inv = |invariant: &'static str| Error::IntegrityViolation { invariant };
        let d = self.d;
        let mut total = 0u64;
        let mut slots = 0usize;
        for g in &self.groups {
            if g.state.n > MAX_GROUP_MEMBERS {
                return Err(inv("INV-4"));
            }
            if g.state.n != g.slots.len() as u64 {
                return Err(inv("INV-6 n"));
            }
            let mut sum = vec![0i64; d];
            for s in &g.slots {
                for (acc, &v) in sum.iter_mut().zip(s.x.as_slice()) {
                    *acc += i64::from(v);
                }
            }
            if sum != g.state.s {
                return Err(inv("INV-6 S"));
            }
            self.ext
                .check_group(&g.state.s, &g.state.ext_public, &g.state.ext_secret)?;
            let ids_match = g.mirror_ids.len() == g.slots.len()
                && g.mirror_ids
                    .iter()
                    .zip(&g.slots)
                    .all(|(a, s)| *a == s.record_id)
                && g.mirror.len() == g.slots.len() * d;
            if !ids_match {
                return Err(inv("INV-9 mirror"));
            }
            total += g.state.n;
            slots += g.slots.len();
        }
        if total != self.big_n {
            return Err(inv("INV-8"));
        }
        // INV-5: ⌊1.5·N/k⌋ ≤ 1,000,000.
        if (3 * u128::from(self.big_n)) / (2 * u128::from(self.k().max(1)))
            > u128::from(MAX_GROUP_MEMBERS)
        {
            return Err(inv("INV-5"));
        }
        slots += self.holding.slots.len();
        // INV-7: the locator and the slots in exact one-to-one correspondence.
        if self.locator.len() != slots {
            return Err(inv("INV-7"));
        }
        for g in self.groups.iter().chain(core::iter::once(&self.holding)) {
            for (i, s) in g.slots.iter().enumerate() {
                if self.locator.get(&s.scrambled_id) != Some(&(g.id, i)) {
                    return Err(inv("INV-7"));
                }
            }
        }
        Ok(())
    }
}

// --- the draft: a pure overlay that plans several steps on top of an unchanged index -----------

#[derive(Clone, Copy)]
enum SlotRef {
    Base(GroupId, usize),
    New(usize),
}

struct Draft<'a, E: GroupExtension, S: IdScrambler> {
    ix: &'a Index<E, S>,
    cs: ChangeSet<E>,
    lens: HashMap<GroupId, usize>,
    moved: HashMap<(GroupId, usize), SlotRef>,
    locator: HashMap<ScrambledId, Option<(GroupId, usize)>>,
    new_slots: Vec<Slot<E>>,
    /// SB-3 only: what each deletion in this plan removed, so a retry can subtract it again.
    deleted: HashMap<ScrambledId, (GroupId, Slot<E>)>,
    /// Never used for real state: the borrow checker's fallback in `state_mut`.
    scratch: GroupState<E>,
}

impl<'a, E: GroupExtension, S: IdScrambler> Draft<'a, E, S> {
    fn new(ix: &'a Index<E, S>) -> Self {
        let counters = Counters {
            big_n: ix.big_n,
            k: ix.k(),
        };
        Self {
            ix,
            cs: ChangeSet {
                created: Vec::new(),
                groups: Vec::new(),
                slots: Vec::new(),
                locator: Vec::new(),
                counters_before: counters,
                counters_after: counters,
                departures: Vec::new(),
                arrivals: Vec::new(),
                outcomes: Vec::new(),
            },
            lens: HashMap::new(),
            moved: HashMap::new(),
            locator: HashMap::new(),
            new_slots: Vec::new(),
            deleted: HashMap::new(),
            scratch: GroupState::empty(ix.d),
        }
    }

    fn finish(self) -> ChangeSet<E> {
        self.cs
    }

    fn len(&self, g: &GroupId) -> usize {
        self.lens
            .get(g)
            .copied()
            .unwrap_or_else(|| self.ix.group(g).map_or(0, |gr| gr.slots.len()))
    }

    fn slot_ref(&self, g: GroupId, i: usize) -> SlotRef {
        self.moved
            .get(&(g, i))
            .copied()
            .unwrap_or(SlotRef::Base(g, i))
    }

    fn resolve(&self, r: SlotRef) -> Option<&Slot<E>> {
        match r {
            SlotRef::Base(g, i) => self.ix.group(&g).and_then(|gr| gr.slots.get(i)),
            SlotRef::New(j) => self.new_slots.get(j),
        }
    }

    fn locate(&self, s: &ScrambledId) -> Option<(GroupId, usize)> {
        match self.locator.get(s) {
            Some(over) => *over,
            None => self.ix.locator.get(s).copied(),
        }
    }

    fn lookup(&self, s: &ScrambledId) -> Option<&Slot<E>> {
        let (g, i) = self.locate(s)?;
        self.resolve(self.slot_ref(g, i))
    }

    /// The touched group's post-state, created from its current state on first touch.
    fn state_mut(&mut self, g: GroupId) -> &mut GroupState<E> {
        let at = match self.cs.groups.iter().position(|c| c.group == g) {
            Some(at) => at,
            None => {
                let before = self
                    .ix
                    .group(&g)
                    .map_or_else(|| GroupState::empty(self.ix.d), |gr| gr.state.clone());
                self.cs.groups.push(GroupChange {
                    group: g,
                    before: before.clone(),
                    after: before,
                });
                self.cs.groups.len() - 1
            }
        };
        // `at` is in range: it was found or just pushed, so the fallback is never reached.
        if let Some(c) = self.cs.groups.get_mut(at) {
            return &mut c.after;
        }
        &mut self.scratch
    }

    /// Appends `slot` to group `g` (no accumulator change).
    fn put(&mut self, g: GroupId, slot: Slot<E>) {
        let index = self.len(&g);
        let s = slot.scrambled_id;
        self.moved
            .insert((g, index), SlotRef::New(self.new_slots.len()));
        self.new_slots.push(slot.clone());
        self.lens.insert(g, index + 1);
        self.cs.slots.push(SlotOp::Put {
            group: g,
            index,
            slot,
        });
        self.locator.insert(s, Some((g, index)));
        self.cs.locator.push(LocatorOp::Put {
            scrambled_id: s,
            group: g,
            index,
        });
        self.cs.arrivals.push((g, s));
    }

    /// §5.3 insert into a frozen or spawned group: `S += x̃`, `n += 1`, extension, `N += 1`.
    fn join(&mut self, g: GroupId, slot: Slot<E>) {
        let ext = self.ix.ext.clone();
        let st = self.state_mut(g);
        for (acc, &v) in st.s.iter_mut().zip(slot.x.as_slice()) {
            *acc += i64::from(v);
        }
        st.n += 1;
        ext.add(&mut st.ext_public, &mut st.ext_secret, &slot.x, &slot.ext);
        self.cs.counters_after.big_n += 1;
        self.put(g, slot);
    }

    /// §5.4: delete one record, or report `AlreadyAbsent`.
    fn delete(&mut self, record_id: &str) -> Result<(), Error> {
        // An ID that breaks §3.2 rules 1–2 can never be live.
        let Ok(rid) = RecordId::new(record_id) else {
            self.cs.outcomes.push(Outcome::AlreadyAbsent);
            return Ok(());
        };
        let s = self.ix.scrambler.scramble(&self.ix.collection_id, &rid);
        let Some((g, i)) = self.locate(&s) else {
            // SB-3: a retried deletion subtracts the vector a second time.
            if cfg!(feature = "sabotage-SB-3") {
                if let Some((g, slot)) = self.deleted.get(&s).cloned() {
                    self.subtract(g, &slot);
                }
            }
            self.cs.outcomes.push(Outcome::AlreadyAbsent); // §5.4: nothing changes
            return Ok(());
        };
        let slot = self
            .resolve(self.slot_ref(g, i))
            .cloned()
            .ok_or(Error::IntegrityViolation { invariant: "INV-7" })?;
        self.ix.ext.check_removal(&slot.x, &slot.ext)?; // EP-1 capability 5
        if g != GroupId::Holding {
            self.subtract(g, &slot);
            self.cs.counters_after.big_n -= 1;
        }
        // §14.4: swap-with-last, then truncate (physical excision; no marker, §5.4).
        let last = self.len(&g).saturating_sub(1);
        if i != last {
            let r = self.slot_ref(g, last);
            self.moved.insert((g, i), r);
            self.cs.slots.push(SlotOp::MoveLast {
                group: g,
                from: last,
                to: i,
            });
            // SB-4: forget the locator update after a slot move.
            if !cfg!(feature = "sabotage-SB-4") {
                if let Some(moved_id) = self.resolve(r).map(|m| m.scrambled_id) {
                    self.locator.insert(moved_id, Some((g, i)));
                    self.cs.locator.push(LocatorOp::Put {
                        scrambled_id: moved_id,
                        group: g,
                        index: i,
                    });
                }
            }
        }
        self.moved.remove(&(g, last));
        self.lens.insert(g, last);
        self.cs.slots.push(SlotOp::Truncate {
            group: g,
            len: last,
        });
        self.locator.insert(s, None);
        self.cs.locator.push(LocatorOp::Delete { scrambled_id: s });
        self.cs.departures.push((g, s));
        self.cs.outcomes.push(Outcome::Deleted { from: g });
        if cfg!(feature = "sabotage-SB-3") {
            self.deleted.insert(s, (g, slot));
        }
        Ok(())
    }

    /// §5.3 delete: `S −= x̃`, `n −= 1`, extension.
    fn subtract(&mut self, g: GroupId, slot: &Slot<E>) {
        let ext = self.ix.ext.clone();
        let st = self.state_mut(g);
        for (acc, &v) in st.s.iter_mut().zip(slot.x.as_slice()) {
            *acc -= i64::from(v);
        }
        // SB-2: skip the count decrement on deletion.
        if !cfg!(feature = "sabotage-SB-2") {
            st.n -= 1;
        }
        ext.remove(&mut st.ext_public, &mut st.ext_secret, &slot.x, &slot.ext);
    }

    /// §7.4–7.5, §15.2: the insert that brings the holding area to the target forms exactly one
    /// spawned group from exactly those records. Every check precedes every change.
    fn flush(&mut self, new_slot: Slot<E>) -> Result<(), Error> {
        let held: Vec<&Slot<E>> = self.ix.holding.slots.iter().collect();
        let mut cohort: Vec<&Slot<E>> = held.clone();
        cohort.push(&new_slot);
        let gid = spawn_id(cohort.iter().map(|s| &s.record_id));
        if self.ix.pos.contains_key(&gid) {
            return Err(Error::IntegrityViolation {
                invariant: "§7.5 spawn ID collision",
            });
        }
        let d = self.ix.d;
        let mut state = GroupState::<E>::empty(d);
        for s in &cohort {
            for (acc, &v) in state.s.iter_mut().zip(s.x.as_slice()) {
                *acc += i64::from(v);
            }
            state.n += 1;
            self.ix
                .ext
                .add(&mut state.ext_public, &mut state.ext_secret, &s.x, &s.ext);
        }
        // §7.5: μ_i = ((f64)S_i / 2^24) / n, computed once from the exact accumulator.
        let n = state.n as f64;
        let centroid: Vec<f64> = state
            .s
            .iter()
            .map(|&v| (v as f64 / SCALE as f64) / n)
            .collect();
        let order: Vec<ScrambledId> = cohort.iter().map(|s| s.scrambled_id).collect();
        let founders = state.n;
        self.cs.created.push(CreatedGroup { id: gid, centroid });
        self.cs.groups.push(GroupChange {
            group: gid,
            before: GroupState::empty(d),
            after: state,
        });
        self.put(GroupId::Holding, new_slot);
        self.cs.slots.push(SlotOp::DrainInto {
            from: GroupId::Holding,
            to: gid,
        });
        for (index, s) in order.into_iter().enumerate() {
            self.locator.insert(s, Some((gid, index)));
            self.cs.locator.push(LocatorOp::Put {
                scrambled_id: s,
                group: gid,
                index,
            });
            self.cs.departures.push((GroupId::Holding, s)); // a flush is a departure (§13.3)
            self.cs.arrivals.push((gid, s));
        }
        self.cs.counters_after.big_n += founders; // §7.6: N += 200
        self.cs.counters_after.k += 1; // k += 1
        self.cs
            .outcomes
            .push(Outcome::Placed(Placement::Spawned(gid)));
        Ok(())
    }
}
