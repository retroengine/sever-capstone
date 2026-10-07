//! From a `ChangeSet` (EP-3) to the after-image records the WAL carries (spec §12.3, §14.6).
//!
//! Every slot operation of Part 1 becomes slot after-images: a put seals the new record's payload;
//! a move-last copies the last slot's stored bytes (ciphertext is moved, not decrypted, §14.4); a
//! flush re-wraps each record's envelope for the new group and moves the payload unchanged
//! (§15.2 step 3). Every touched group gets a new header, with its accumulator re-sealed. The
//! records are produced in replay order, so `DbImage::apply` of the list gives the post-state.

use std::collections::{BTreeSet, HashMap};

use sever_format::group::encode_accumulator;
use sever_format::{
    CollectionImage, CollectionMeta, CoreRecord, GroupHeader, Layout, PayloadRef, SlotBytes,
    SlotPayload,
};
use sever_index::{ChangeSet, changeset::LocatorOp, changeset::SlotOp};
use sever_types::{CollectionId, Error, GroupId};
use zeroize::Zeroizing;

use crate::ext::StoredExtension;
use crate::sealer::{GroupOwner, RecordOwner, Sealer};

fn integrity(check: &'static str) -> Error {
    Error::IntegrityViolation { invariant: check }
}

/// The layout of a collection stored with extension `E` and `sealer` (DB-46).
pub fn layout_for<E: StoredExtension>(d: usize, sealer: &dyn Sealer) -> Layout {
    Layout {
        d,
        ext_public: E::PUBLIC_LEN,
        ext_group_secret: E::GROUP_SECRET_LEN,
        ext_record_secret: E::RECORD_SECRET_LEN,
        envelope: sealer.envelope_len(),
        seal_overhead: sealer.seal_overhead(),
    }
}

/// Seals a group's accumulator into a header.
#[allow(clippy::too_many_arguments)]
fn sealed_header<E: StoredExtension>(
    sealer: &dyn Sealer,
    cid: &CollectionId,
    group: GroupId,
    prev: Option<u64>,
    departure: bool,
    centroid: Vec<f64>,
    s: &[i64],
    n: u64,
    public: &E::GroupPublic,
    secret: &E::GroupSecret,
) -> Result<GroupHeader, Error> {
    let owner = GroupOwner {
        collection: cid,
        group: &group,
        n,
    };
    let version = sealer.next_version(&owner, prev, departure);
    let plain = Zeroizing::new(encode_accumulator(s, &E::encode_group_secret(secret)));
    Ok(GroupHeader {
        group_id: group,
        seal_version: version,
        n,
        ext_public: E::encode_public(public),
        centroid,
        sealed_accumulator: sealer.seal_accumulator(&owner, version, &plain)?,
    })
}

/// The records that create a collection (§16.1 `create_collection`): the collection, one empty
/// group per frozen centroid (label order), the holding area, and the counters (`N = 0`,
/// `k = k_frozen`, §7.6).
pub fn collection_records<E: StoredExtension>(
    meta: CollectionMeta,
    artefact: Vec<u8>,
    centroids: &[f64],
    sealer: &dyn Sealer,
) -> Result<Vec<CoreRecord>, Error> {
    let d = usize::from(meta.d);
    let cid = meta.cid;
    let mut out = vec![CoreRecord::CollectionCreate { meta, artefact }];
    let zero = vec![0i64; d];
    let mut k = 0u64;
    for (label, mu) in centroids.chunks_exact(d).enumerate() {
        let g = u16::try_from(label)
            .ok()
            .and_then(GroupId::frozen)
            .ok_or(integrity("§5.1 frozen label"))?;
        let header = sealed_header::<E>(
            sealer,
            &cid,
            g,
            None,
            false,
            mu.to_vec(),
            &zero,
            0,
            &Default::default(),
            &Default::default(),
        )?;
        out.push(CoreRecord::GroupCreate {
            cid,
            header,
            bucket_block: Vec::new(),
        });
        k += 1;
    }
    let holding = GroupOwner {
        collection: &cid,
        group: &GroupId::Holding,
        n: 0,
    };
    out.push(CoreRecord::GroupCreate {
        cid,
        header: GroupHeader {
            group_id: GroupId::Holding,
            seal_version: sealer.next_version(&holding, None, false),
            n: 0,
            ext_public: E::encode_public(&Default::default()),
            centroid: vec![0.0; d],
            sealed_accumulator: Vec::new(),
        },
        bucket_block: Vec::new(),
    });
    out.push(CoreRecord::Counters { cid, big_n: 0, k });
    Ok(out)
}

/// The after-image records of `cs` on collection `coll`.
///
/// `passage`: the text of the inserted record (an insert's first put), stored through `store`
/// and referenced by a `PAYLOAD_REF` record; `store` is called only when there is a passage.
pub fn changeset_records<E: StoredExtension>(
    coll: &CollectionImage,
    layout: &Layout,
    cs: &ChangeSet<E>,
    sealer: &dyn Sealer,
    passage: Option<&[u8]>,
    store: &mut dyn FnMut(&[u8]) -> Result<PayloadRef, Error>,
) -> Result<Vec<CoreRecord>, Error> {
    let cid = coll.meta.cid;
    let mut out = Vec::new();
    let mut overlay: HashMap<(GroupId, usize), SlotBytes> = HashMap::new();
    let mut lens: HashMap<GroupId, usize> = HashMap::new();
    let mut touched: BTreeSet<Vec<u8>> = BTreeSet::new();
    let mut touched_ids: HashMap<Vec<u8>, GroupId> = HashMap::new();
    let key = |g: &GroupId| g.to_padded_bytes().0.to_vec();
    let mut touch = |g: GroupId| {
        touched.insert(key(&g));
        touched_ids.insert(key(&g), g);
    };
    let departed: BTreeSet<Vec<u8>> = cs.departures.iter().map(|(g, _)| key(g)).collect();
    let len_of = |lens: &HashMap<GroupId, usize>, g: &GroupId| {
        lens.get(g)
            .copied()
            .unwrap_or_else(|| coll.group(g).map_or(0, |gi| gi.slots.len()))
    };
    let slot_at = |overlay: &HashMap<(GroupId, usize), SlotBytes>, g: GroupId, i: usize| {
        overlay
            .get(&(g, i))
            .cloned()
            .or_else(|| coll.group(&g).and_then(|gi| gi.slots.get(i).cloned()))
            .ok_or(integrity("INV-7 slot"))
    };

    // Groups created by a flush exist before anything moves into them.
    let mut created: HashMap<GroupId, Vec<f64>> = HashMap::new();
    for c in &cs.created {
        if coll.group(&c.id).is_some() {
            return Err(integrity("§7.5 spawn ID collision"));
        }
        let header = sealed_header::<E>(
            sealer,
            &cid,
            c.id,
            None,
            false,
            c.centroid.clone(),
            &vec![0; layout.d],
            0,
            &Default::default(),
            &Default::default(),
        )?;
        out.push(CoreRecord::GroupCreate {
            cid,
            header,
            bucket_block: Vec::new(),
        });
        created.insert(c.id, c.centroid.clone());
    }

    let mut inserted = None;
    for op in &cs.slots {
        match op {
            SlotOp::Put { group, index, slot } => {
                let payload = Zeroizing::new(
                    SlotPayload {
                        record_id: slot.record_id.clone(),
                        x: slot.x.as_slice().to_vec(),
                        ext_secret: E::encode_record_secret(&slot.ext),
                    }
                    .encode(layout)?,
                );
                let owner = RecordOwner {
                    collection: &cid,
                    group,
                    scrambled_id: &slot.scrambled_id,
                };
                let (envelope, sealed_payload) = sealer.seal_record(&owner, &payload)?;
                let bytes = SlotBytes {
                    scrambled_id: slot.scrambled_id,
                    envelope,
                    sealed_payload,
                };
                if inserted.is_none() {
                    inserted = Some((slot.scrambled_id, *group, bytes.envelope.clone()));
                }
                if *index != len_of(&lens, group) {
                    return Err(integrity("§14.4 put position"));
                }
                out.push(CoreRecord::SlotPut {
                    cid,
                    group: *group,
                    index: *index as u64,
                    slot: bytes.clone(),
                });
                overlay.insert((*group, *index), bytes);
                lens.insert(*group, index + 1);
                touch(*group);
            }
            SlotOp::MoveLast { group, from, to } => {
                if from != to {
                    let bytes = slot_at(&overlay, *group, *from)?;
                    out.push(CoreRecord::SlotPut {
                        cid,
                        group: *group,
                        index: *to as u64,
                        slot: bytes.clone(),
                    });
                    overlay.insert((*group, *to), bytes);
                }
                touch(*group);
            }
            SlotOp::Truncate { group, len } => {
                out.push(CoreRecord::SlotTruncate {
                    cid,
                    group: *group,
                    len: *len as u64,
                });
                let old = len_of(&lens, group);
                for i in *len..old {
                    overlay.remove(&(*group, i));
                }
                lens.insert(*group, *len);
                touch(*group);
            }
            SlotOp::DrainInto { from, to } => {
                let n = len_of(&lens, from);
                let base = len_of(&lens, to);
                for i in 0..n {
                    let s = slot_at(&overlay, *from, i)?;
                    let envelope = sealer.rewrap_record(
                        &RecordOwner {
                            collection: &cid,
                            group: from,
                            scrambled_id: &s.scrambled_id,
                        },
                        &RecordOwner {
                            collection: &cid,
                            group: to,
                            scrambled_id: &s.scrambled_id,
                        },
                        &s.envelope,
                    )?;
                    let moved = SlotBytes { envelope, ..s };
                    out.push(CoreRecord::SlotPut {
                        cid,
                        group: *to,
                        index: (base + i) as u64,
                        slot: moved.clone(),
                    });
                    overlay.insert((*to, base + i), moved);
                }
                out.push(CoreRecord::SlotTruncate {
                    cid,
                    group: *from,
                    len: 0,
                });
                for i in 0..n {
                    overlay.remove(&(*from, i));
                }
                lens.insert(*from, 0);
                lens.insert(*to, base + n);
                touch(*from);
                touch(*to);
            }
        }
    }

    for op in &cs.locator {
        out.push(match op {
            LocatorOp::Put {
                scrambled_id,
                group,
                index,
            } => CoreRecord::LocatorPut {
                cid,
                scrambled_id: *scrambled_id,
                group: *group,
                index: *index as u64,
            },
            LocatorOp::Delete { scrambled_id } => CoreRecord::LocatorDel {
                cid,
                scrambled_id: *scrambled_id,
            },
        });
    }

    if let (Some(text), Some((sid, group, envelope))) = (passage, &inserted) {
        let owner = RecordOwner {
            collection: &cid,
            group,
            scrambled_id: sid,
        };
        let sealed = sealer.seal_passage(&owner, envelope, text)?;
        out.push(CoreRecord::PayloadRef {
            cid,
            scrambled_id: *sid,
            at: store(&sealed)?,
        });
    }

    // New headers: every group with an accumulator change, then any other touched group (the
    // holding area, whose header carries only its count).
    let mut headed: BTreeSet<Vec<u8>> = BTreeSet::new();
    for gc in &cs.groups {
        let (prev, centroid) = match (coll.group(&gc.group), created.get(&gc.group)) {
            (Some(gi), _) => (Some(gi.header.seal_version), gi.header.centroid.clone()),
            (None, Some(c)) => (None, c.clone()),
            (None, None) => return Err(integrity("§15.7 unknown group")),
        };
        let header = sealed_header::<E>(
            sealer,
            &cid,
            gc.group,
            prev,
            departed.contains(&key(&gc.group)),
            centroid,
            &gc.after.s,
            gc.after.n,
            &gc.after.ext_public,
            &gc.after.ext_secret,
        )?;
        out.push(CoreRecord::GroupHeader { cid, header });
        headed.insert(key(&gc.group));
    }
    for k in &touched {
        if headed.contains(k) {
            continue;
        }
        let g = *touched_ids.get(k).ok_or(integrity("§14.3 header"))?;
        let gi = coll.group(&g).ok_or(integrity("§15.7 unknown group"))?;
        if g != GroupId::Holding {
            return Err(integrity("INV-2 accumulator not updated"));
        }
        let n = len_of(&lens, &g) as u64;
        let owner = GroupOwner {
            collection: &cid,
            group: &g,
            n,
        };
        out.push(CoreRecord::GroupHeader {
            cid,
            header: GroupHeader {
                seal_version: sealer.next_version(
                    &owner,
                    Some(gi.header.seal_version),
                    departed.contains(k),
                ),
                n,
                ..gi.header.clone()
            },
        });
    }

    if cs.counters_after != cs.counters_before {
        out.push(CoreRecord::Counters {
            cid,
            big_n: cs.counters_after.big_n,
            k: cs.counters_after.k,
        });
    }
    Ok(out)
}
