//! From the stored image back to typed state (§15.7 step 5: "decrypt into memory; rebuild").
//!
//! [`decode_collection`] opens every accumulator and slot payload through the sealer and parses
//! them strictly. [`rebuild_changeset`] turns the result into one `ChangeSet` that, applied to a
//! fresh `Index` over the same artefact, installs exactly the stored state through Part 1's
//! public, infallible `apply` (F-3: no edit to the frozen index).

use sever_format::group::parse_accumulator;
use sever_format::{CollectionImage, KindByte, Layout, SlotPayload};
use sever_index::changeset::{CreatedGroup, GroupChange, GroupState, LocatorOp, SlotOp};
use sever_index::{ChangeSet, Counters, Slot};
use sever_quant::QVec;
use sever_types::{Error, GroupId};

use crate::ext::StoredExtension;
use crate::sealer::{GroupOwner, RecordOwner, Sealer};

/// One group, decoded.
pub struct DecodedGroup<E: StoredExtension> {
    /// The group.
    pub id: GroupId,
    /// Its centroid (zero for the holding area).
    pub centroid: Vec<f64>,
    /// Its accumulator state; `None` for the holding area.
    pub state: Option<GroupState<E>>,
    /// Its records, in slot order.
    pub slots: Vec<Slot<E>>,
}

/// Opens and parses every group of `coll`, in creation order.
pub fn decode_collection<E: StoredExtension>(
    coll: &CollectionImage,
    layout: &Layout,
    sealer: &dyn Sealer,
) -> Result<Vec<DecodedGroup<E>>, Error> {
    let cid = coll.meta.cid;
    let mut out = Vec::with_capacity(coll.groups.len());
    for g in &coll.groups {
        let h = &g.header;
        let id = h.group_id;
        let state = if h.kind() == KindByte::Holding {
            None
        } else {
            let owner = GroupOwner {
                collection: &cid,
                group: &id,
                n: h.n,
            };
            let plain = sealer.open_accumulator(&owner, h.seal_version, &h.sealed_accumulator)?;
            let (s, secret) = parse_accumulator(&plain, layout)?;
            Some(GroupState {
                s,
                n: h.n,
                ext_public: E::decode_public(&h.ext_public)?,
                ext_secret: E::decode_group_secret(&secret)?,
            })
        };
        let mut slots = Vec::with_capacity(g.slots.len());
        for sb in &g.slots {
            let owner = RecordOwner {
                collection: &cid,
                group: &id,
                scrambled_id: &sb.scrambled_id,
            };
            let plain = sealer.open_record(&owner, &sb.envelope, &sb.sealed_payload)?;
            let p = SlotPayload::parse(&plain, layout)?;
            slots.push(Slot {
                scrambled_id: sb.scrambled_id,
                record_id: p.record_id,
                x: QVec::from_stored(p.x, layout.d)?,
                ext: E::decode_record_secret(&p.ext_secret)?,
            });
        }
        out.push(DecodedGroup {
            id,
            centroid: h.centroid.clone(),
            state,
            slots,
        });
    }
    Ok(out)
}

/// The `ChangeSet` that installs `groups` into a fresh index over the same artefact: spawned
/// groups in creation order, every accumulator, every slot in order, a locator entry per slot,
/// and the counters.
pub fn rebuild_changeset<E: StoredExtension>(
    d: usize,
    groups: Vec<DecodedGroup<E>>,
    counters: Counters,
) -> ChangeSet<E> {
    let mut cs = ChangeSet {
        created: Vec::new(),
        groups: Vec::new(),
        slots: Vec::new(),
        locator: Vec::new(),
        counters_before: Counters::default(),
        counters_after: counters,
        departures: Vec::new(),
        arrivals: Vec::new(),
        outcomes: Vec::new(),
    };
    for g in groups {
        if matches!(g.id, GroupId::Spawned(_)) {
            cs.created.push(CreatedGroup {
                id: g.id,
                centroid: g.centroid,
            });
        }
        if let Some(state) = g.state {
            cs.groups.push(GroupChange {
                group: g.id,
                before: GroupState::empty(d),
                after: state,
            });
        }
        for (index, slot) in g.slots.into_iter().enumerate() {
            cs.locator.push(LocatorOp::Put {
                scrambled_id: slot.scrambled_id,
                group: g.id,
                index,
            });
            cs.slots.push(SlotOp::Put {
                group: g.id,
                index,
                slot,
            });
        }
    }
    cs
}
