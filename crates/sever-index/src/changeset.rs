//! EP-3 `ChangeSet` (Build §3.3): everything one mutation does, computed by a pure `plan` and
//! installed by an infallible `apply`. Part 2 logs it before applying it, Part 3 builds a
//! certificate from it, Part 4 rotates keys for its departures; none of them edits this crate.

use sever_quant::QVec;
use sever_types::{GroupId, RecordId, ScrambledId};

use crate::ext::GroupExtension;

/// One record as the index holds it (spec §14.4 semantics, in memory).
#[derive(Clone, PartialEq)]
pub struct Slot<E: GroupExtension> {
    /// §9.7: the only name below the API.
    pub scrambled_id: ScrambledId,
    /// The record ID (§3.2), for the canonical blob and search results.
    pub record_id: RecordId,
    /// The quantised vector `x̃` (§4.2).
    pub x: QVec,
    /// The extension's per-record secret (EP-1 capability 2).
    pub ext: E::RecordSecret,
}

impl<E: GroupExtension> core::fmt::Debug for Slot<E> {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "Slot({:?})", self.scrambled_id)
    }
}

/// A group's accumulator state: `S`, `n` and the extension's public and secret state.
#[derive(Clone, PartialEq)]
pub struct GroupState<E: GroupExtension> {
    /// `S`, one `i64` per dimension (§5.2).
    pub s: Vec<i64>,
    /// `n` (§5.2).
    pub n: u64,
    /// Extension public state (Part 3: `C_S`).
    pub ext_public: E::GroupPublic,
    /// Extension secret state (Part 3: `r_agg`).
    pub ext_secret: E::GroupSecret,
}

impl<E: GroupExtension> GroupState<E> {
    /// §5.2 initial state: `S = 0`, `n = 0`, extension defaults.
    pub fn empty(d: usize) -> Self {
        Self {
            s: vec![0; d],
            n: 0,
            ext_public: Default::default(),
            ext_secret: Default::default(),
        }
    }
}

/// The pre-state and post-state of one touched group (frozen or spawned; never the holding area,
/// which has no accumulator).
#[derive(Clone)]
pub struct GroupChange<E: GroupExtension> {
    /// The group.
    pub group: GroupId,
    /// State before the change set.
    pub before: GroupState<E>,
    /// State after the change set.
    pub after: GroupState<E>,
}

/// One slot-array operation, applied in order.
#[derive(Clone)]
pub enum SlotOp<E: GroupExtension> {
    /// Append `slot` to `group` at position `index` (always the current length).
    Put {
        /// Target group (or the holding area).
        group: GroupId,
        /// Position; equals the group's slot count before the put.
        index: usize,
        /// The record.
        slot: Slot<E>,
    },
    /// Swap-with-last removal, first half (§14.4): exchange the last slot (`from`) with the gap
    /// (`to`). The following `Truncate` drops the removed record.
    MoveLast {
        /// The group.
        group: GroupId,
        /// The last position.
        from: usize,
        /// The removed record's position.
        to: usize,
    },
    /// Drop every slot from position `len` on.
    Truncate {
        /// The group.
        group: GroupId,
        /// New slot count.
        len: usize,
    },
    /// A flush (§7.4): move every slot of `from` (the holding area), in order, to the end of `to`
    /// (the new spawned group). Payloads move unchanged (§14.4).
    DrainInto {
        /// Source (the holding area).
        from: GroupId,
        /// Destination (the new spawned group).
        to: GroupId,
    },
}

/// One locator operation (`scrambled_id → (group, slot index)`, §12.6).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LocatorOp {
    /// Point `scrambled_id` at `(group, index)`.
    Put {
        /// The record.
        scrambled_id: ScrambledId,
        /// Its group.
        group: GroupId,
        /// Its slot.
        index: usize,
    },
    /// Remove `scrambled_id`.
    Delete {
        /// The record.
        scrambled_id: ScrambledId,
    },
}

/// A spawned group created by a flush (§7.5).
#[derive(Clone, Debug, PartialEq)]
pub struct CreatedGroup {
    /// `spawn-…` from the founders' IDs.
    pub id: GroupId,
    /// `μ_i = ((f64)S_i / 2^24) / n`, frozen from now on.
    pub centroid: Vec<f64>,
}

/// The counters of §7.6.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub struct Counters {
    /// `N`: records in frozen and spawned groups.
    pub big_n: u64,
    /// `k`: frozen plus spawned groups.
    pub k: u64,
}

/// Where an insert landed, after the whole transaction (a flush moves it into the new group).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Placement {
    /// A frozen group (in distribution).
    Frozen(GroupId),
    /// A spawned group (spillover, or the group its insert's flush created).
    Spawned(GroupId),
    /// The holding area: stored, deletable, not searchable (§7.4).
    Holding,
}

/// The outcome of one request (Build §3.3).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Outcome {
    /// An insert was placed.
    Placed(Placement),
    /// A delete excised the record from `from` (a group or the holding area).
    Deleted {
        /// Where the record was.
        from: GroupId,
    },
    /// §5.4: the record was not live; nothing changed.
    AlreadyAbsent,
}

/// EP-3: everything one `plan` decided. `apply` installs it and cannot fail.
#[derive(Clone)]
pub struct ChangeSet<E: GroupExtension> {
    /// Groups created by a flush, created before anything else is applied.
    pub created: Vec<CreatedGroup>,
    /// Pre-state and post-state of every touched group (one entry per group).
    pub groups: Vec<GroupChange<E>>,
    /// Slot operations, in order.
    pub slots: Vec<SlotOp<E>>,
    /// Locator operations, in order.
    pub locator: Vec<LocatorOp>,
    /// `N` and `k` before.
    pub counters_before: Counters,
    /// `N` and `k` after.
    pub counters_after: Counters,
    /// Every `(domain, scrambled_id)` that leaves a group or the holding area (Part 4 rotates
    /// exactly these domains).
    pub departures: Vec<(GroupId, ScrambledId)>,
    /// Every `(domain, scrambled_id)` that joins one.
    pub arrivals: Vec<(GroupId, ScrambledId)>,
    /// One outcome per request, in request order.
    pub outcomes: Vec<Outcome>,
}

impl<E: GroupExtension> ChangeSet<E> {
    /// True when applying it changes nothing (every request was `AlreadyAbsent`).
    pub fn is_noop(&self) -> bool {
        self.created.is_empty()
            && self.groups.is_empty()
            && self.slots.is_empty()
            && self.locator.is_empty()
    }
}
