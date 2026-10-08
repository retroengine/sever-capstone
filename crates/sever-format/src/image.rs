//! The storage image: the whole database in its stored form (§12.6 "slot arrays as on disk",
//! group headers, locator, counters), changed only by applying after-image records (§12.3).
//!
//! The image is what a storage checkpoint writes (§15.6) and what recovery loads and replays the
//! WAL onto (§15.7 step 3). Normal operation and recovery change it through the same
//! [`DbImage::apply`], so the state after replay is the state that was committed.

use std::collections::{BTreeMap, HashMap};

use sever_types::{CollectionId, Error, GroupId, ScrambledId};

use crate::Layout;
use crate::codec::{Reader, Writer, bad};
use crate::group::GroupHeader;
use crate::slot::SlotBytes;
use crate::wal::CoreRecord;

/// A collection's fixed metadata: `collection_id ‖ u16be d ‖ u32be spawn_target ‖
/// u8 spawning_enabled ‖ u8 store_passages ‖ artefact SHA-256 (32)`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CollectionMeta {
    /// The collection (§3.1).
    pub cid: CollectionId,
    /// Its dimension (from the artefact, §6.3).
    pub d: u16,
    /// The holding area's flush size (§7.4; 200 in v1, DB-62).
    pub spawn_target: u32,
    /// `false` only for the frozen-only control arm (overview §10.7).
    pub spawning_enabled: bool,
    /// Whether passage text is stored (§18.1 `store_passage_text`).
    pub store_passages: bool,
    /// `sha256_artefact` of the partition artefact (§6.3).
    pub artefact_sha256: [u8; 32],
}

impl CollectionMeta {
    /// Appends the encoding.
    pub fn write(&self, w: &mut Writer) {
        w.collection(&self.cid)
            .u16(self.d)
            .u32(self.spawn_target)
            .u8(u8::from(self.spawning_enabled))
            .u8(u8::from(self.store_passages))
            .bytes(&self.artefact_sha256);
    }

    /// Reads one; the flags must be 0 or 1 and `d` a positive multiple of 8 (DB-49).
    pub fn read(r: &mut Reader<'_>) -> Result<Self, Error> {
        let cid = r.collection()?;
        let d = r.u16()?;
        let spawn_target = r.u32()?;
        let flag = |b: u8| match b {
            0 => Ok(false),
            1 => Ok(true),
            _ => Err(bad("§14 collection flags")),
        };
        let spawning_enabled = flag(r.u8()?)?;
        let store_passages = flag(r.u8()?)?;
        let artefact_sha256 = r.array()?;
        if d == 0 || d % 8 != 0 || spawn_target == 0 {
            return Err(bad("§14 collection parameters"));
        }
        Ok(Self {
            cid,
            d,
            spawn_target,
            spawning_enabled,
            store_passages,
            artefact_sha256,
        })
    }
}

/// Where a record's passage text lies: `u64be store segment ‖ u64be offset ‖ u32be length`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PayloadRef {
    /// The payload store segment, `payloads/<segment>.store`.
    pub segment: u64,
    /// The record's offset in that file.
    pub offset: u64,
    /// The length of the stored bytes.
    pub len: u32,
}

impl PayloadRef {
    /// Appends the encoding.
    pub fn write(&self, w: &mut Writer) {
        w.u64(self.segment).u64(self.offset).u32(self.len);
    }
    /// Reads one.
    pub fn read(r: &mut Reader<'_>) -> Result<Self, Error> {
        Ok(Self {
            segment: r.u64()?,
            offset: r.u64()?,
            len: r.u32()?,
        })
    }
}

/// One group (or the holding area) as stored.
#[derive(Clone, Debug, PartialEq)]
pub struct GroupImage {
    /// The header.
    pub header: GroupHeader,
    /// The slots, in slot order.
    pub slots: Vec<SlotBytes>,
}

/// One collection as stored.
#[derive(Clone, Debug, PartialEq)]
pub struct CollectionImage {
    /// Fixed metadata.
    pub meta: CollectionMeta,
    /// The partition artefact (§6.3 bytes).
    pub artefact: Vec<u8>,
    /// Groups in creation order: frozen groups and the holding area at collection creation, then
    /// spawned groups in flush order.
    pub groups: Vec<GroupImage>,
    pos: HashMap<GroupId, usize>,
    /// `scrambled_id → (group, slot index)`.
    pub locator: BTreeMap<ScrambledId, (GroupId, u64)>,
    /// `scrambled_id → passage text location`.
    pub payload_refs: BTreeMap<ScrambledId, PayloadRef>,
    /// `N`.
    pub big_n: u64,
    /// `k`.
    pub k: u64,
}

impl CollectionImage {
    /// A new collection with no groups yet.
    pub fn new(meta: CollectionMeta, artefact: Vec<u8>) -> Self {
        Self {
            meta,
            artefact,
            groups: Vec::new(),
            pos: HashMap::new(),
            locator: BTreeMap::new(),
            payload_refs: BTreeMap::new(),
            big_n: 0,
            k: 0,
        }
    }

    /// The group with this ID.
    pub fn group(&self, id: &GroupId) -> Option<&GroupImage> {
        self.pos.get(id).and_then(|&i| self.groups.get(i))
    }

    fn group_mut(&mut self, id: &GroupId) -> Result<&mut GroupImage, Error> {
        self.pos
            .get(id)
            .and_then(|&i| self.groups.get_mut(i))
            .ok_or(bad("§15.7 replay: unknown group"))
    }

    fn push_group(&mut self, g: GroupImage) -> Result<(), Error> {
        let id = g.header.group_id;
        if self.pos.contains_key(&id) {
            return Err(bad("§15.7 replay: group exists"));
        }
        self.pos.insert(id, self.groups.len());
        self.groups.push(g);
        Ok(())
    }
}

/// The whole database as stored.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct DbImage {
    /// Collections by ID.
    pub collections: BTreeMap<CollectionId, CollectionImage>,
}

impl DbImage {
    /// The collection with this ID.
    pub fn collection(&self, cid: &CollectionId) -> Option<&CollectionImage> {
        self.collections.get(cid)
    }

    fn coll_mut(&mut self, cid: &CollectionId) -> Result<&mut CollectionImage, Error> {
        self.collections
            .get_mut(cid)
            .ok_or(bad("§15.7 replay: unknown collection"))
    }

    /// Applies one after-image. Strict: a record that does not fit the image (an unknown group, a
    /// slot index beyond the end, a truncate that grows, a missing locator entry) is an integrity
    /// failure, never silently repaired. Participant records and `BEGIN`/`COMMIT` change nothing.
    pub fn apply(&mut self, rec: &CoreRecord) -> Result<(), Error> {
        match rec {
            CoreRecord::Begin | CoreRecord::Commit | CoreRecord::Participant { .. } => {}
            CoreRecord::CollectionCreate { meta, artefact } => {
                if self.collections.contains_key(&meta.cid) {
                    return Err(bad("§15.7 replay: collection exists"));
                }
                self.collections
                    .insert(meta.cid, CollectionImage::new(*meta, artefact.clone()));
            }
            CoreRecord::CollectionDrop { cid } => {
                self.collections
                    .remove(cid)
                    .ok_or(bad("§15.7 replay: unknown collection"))?;
            }
            CoreRecord::GroupCreate { cid, header, .. } => {
                self.coll_mut(cid)?.push_group(GroupImage {
                    header: header.clone(),
                    slots: Vec::new(),
                })?;
            }
            CoreRecord::GroupHeader { cid, header } => {
                self.coll_mut(cid)?.group_mut(&header.group_id)?.header = header.clone();
            }
            CoreRecord::SlotPut {
                cid,
                group,
                index,
                slot,
            } => {
                let g = self.coll_mut(cid)?.group_mut(group)?;
                let i = usize::try_from(*index).map_err(|_| bad("§15.7 replay: slot index"))?;
                if i == g.slots.len() {
                    g.slots.push(slot.clone());
                } else {
                    *g.slots.get_mut(i).ok_or(bad("§15.7 replay: slot index"))? = slot.clone();
                }
            }
            CoreRecord::SlotTruncate { cid, group, len } => {
                let g = self.coll_mut(cid)?.group_mut(group)?;
                let n = usize::try_from(*len).map_err(|_| bad("§15.7 replay: truncate"))?;
                if n > g.slots.len() {
                    return Err(bad("§15.7 replay: truncate"));
                }
                g.slots.truncate(n);
            }
            CoreRecord::LocatorPut {
                cid,
                scrambled_id,
                group,
                index,
            } => {
                self.coll_mut(cid)?
                    .locator
                    .insert(*scrambled_id, (*group, *index));
            }
            CoreRecord::LocatorDel { cid, scrambled_id } => {
                let c = self.coll_mut(cid)?;
                c.locator
                    .remove(scrambled_id)
                    .ok_or(bad("§15.7 replay: locator entry"))?;
                c.payload_refs.remove(scrambled_id);
            }
            CoreRecord::PayloadRef {
                cid,
                scrambled_id,
                at,
            } => {
                self.coll_mut(cid)?.payload_refs.insert(*scrambled_id, *at);
            }
            CoreRecord::Counters { cid, big_n, k } => {
                let c = self.coll_mut(cid)?;
                c.big_n = *big_n;
                c.k = *k;
            }
        }
        Ok(())
    }
}

/// The byte streams of one storage checkpoint (§14.1), before paging (§14.2). The artefacts go
/// to `partitions/<collection>.svp` verbatim.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CheckpointStreams {
    /// `meta.bin`: `u64be checkpoint_id ‖ u64be next_wal_seq ‖ u64be next_txn_id ‖ config hash
    /// (32) ‖ u32be collection count ‖ collection IDs`.
    pub meta: Vec<u8>,
    /// `collections.bin`: per collection, `meta ‖ u64be N ‖ u64be k`.
    pub collections: Vec<u8>,
    /// `groups.bin`: per collection, `collection_id ‖ u64be count ‖ headers in creation order`.
    pub groups: Vec<u8>,
    /// `slots.bin`: per collection and group, `collection_id ‖ group_id ‖ u64be count ‖ slots`.
    pub slots: Vec<u8>,
    /// `locator.bin`: per collection, `collection_id ‖ u64be count ‖ (scrambled_id ‖ group_id ‖
    /// u64be slot index)` ascending by `scrambled_id`.
    pub locator: Vec<u8>,
    /// `payloads.bin`: per collection, `collection_id ‖ u64be count ‖ (scrambled_id ‖ ref)`.
    pub payload_refs: Vec<u8>,
    /// `(collection, artefact bytes)` for `partitions/`.
    pub artefacts: Vec<(CollectionId, Vec<u8>)>,
}

/// The parts of `meta.bin` that are not the image.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CheckpointMeta {
    /// This checkpoint's ID (its directory name).
    pub checkpoint_id: u64,
    /// The first `wal_seq` not covered: replay starts here.
    pub next_wal_seq: u64,
    /// The next transaction ID.
    pub next_txn_id: u64,
    /// SHA-256 of the engine configuration (§18: a changed value invalidates a run).
    pub config_hash: [u8; 32],
}

/// Upper bound on any count in a checkpoint stream, so a corrupt count cannot force a huge
/// allocation (a stream is at most a few GiB, and every entry takes at least 8 bytes).
const MAX_COUNT: usize = 1 << 32;

impl DbImage {
    /// Serialises the image for a checkpoint. `layout_of` gives each collection's layout.
    pub fn to_streams(
        &self,
        meta: &CheckpointMeta,
        layout_of: &dyn Fn(&CollectionMeta) -> Layout,
    ) -> Result<CheckpointStreams, Error> {
        let mut out = CheckpointStreams::default();
        let mut m = Writer::new();
        m.u64(meta.checkpoint_id)
            .u64(meta.next_wal_seq)
            .u64(meta.next_txn_id)
            .bytes(&meta.config_hash)
            .u32(u32::try_from(self.collections.len()).map_err(|_| bad("§14.1 meta"))?);
        let (mut cs, mut gs, mut ss, mut ls, mut ps) = (
            Writer::new(),
            Writer::new(),
            Writer::new(),
            Writer::new(),
            Writer::new(),
        );
        for (cid, c) in &self.collections {
            let layout = layout_of(&c.meta);
            m.collection(cid);
            c.meta.write(&mut cs);
            cs.u64(c.big_n).u64(c.k);
            gs.collection(cid).u64(c.groups.len() as u64);
            for g in &c.groups {
                gs.bytes(&g.header.encode(&layout)?);
                ss.collection(cid)
                    .group_id(&g.header.group_id)
                    .u64(g.slots.len() as u64);
                for s in &g.slots {
                    ss.bytes(&s.encode(&layout)?);
                }
            }
            ls.collection(cid).u64(c.locator.len() as u64);
            for (sid, (g, i)) in &c.locator {
                ls.scrambled(sid).group_id(g).u64(*i);
            }
            ps.collection(cid).u64(c.payload_refs.len() as u64);
            for (sid, at) in &c.payload_refs {
                ps.scrambled(sid);
                at.write(&mut ps);
            }
            out.artefacts.push((*cid, c.artefact.clone()));
        }
        out.meta = m.finish();
        out.collections = cs.finish();
        out.groups = gs.finish();
        out.slots = ss.finish();
        out.locator = ls.finish();
        out.payload_refs = ps.finish();
        Ok(out)
    }

    /// Parses checkpoint streams back into an image. Every stream must list the collections of
    /// `meta.bin`, in order, and be read to its last byte.
    pub fn from_streams(
        s: &CheckpointStreams,
        layout_of: &dyn Fn(&CollectionMeta) -> Layout,
    ) -> Result<(CheckpointMeta, Self), Error> {
        let mut m = Reader::new(&s.meta, "§14.1 meta.bin");
        let meta = CheckpointMeta {
            checkpoint_id: m.u64()?,
            next_wal_seq: m.u64()?,
            next_txn_id: m.u64()?,
            config_hash: m.array()?,
        };
        let n = m.u32()?;
        let mut cids = Vec::new();
        for _ in 0..n {
            cids.push(m.collection()?);
        }
        m.end()?;
        let mut cs = Reader::new(&s.collections, "§14.1 collections.bin");
        let mut gs = Reader::new(&s.groups, "§14.1 groups.bin");
        let mut ss = Reader::new(&s.slots, "§14.1 slots.bin");
        let mut ls = Reader::new(&s.locator, "§14.1 locator.bin");
        let mut ps = Reader::new(&s.payload_refs, "§14.1 payloads.bin");
        let mut img = DbImage::default();
        let mut previous: Option<CollectionId> = None;
        for cid in cids {
            if previous.is_some_and(|p| p >= cid) {
                return Err(bad("§14.1 meta.bin collection order"));
            }
            previous = Some(cid);
            let cmeta = CollectionMeta::read(&mut cs)?;
            if cmeta.cid != cid {
                return Err(bad("§14.1 collections.bin order"));
            }
            let layout = layout_of(&cmeta);
            let artefact = s
                .artefacts
                .iter()
                .find(|(c, _)| *c == cid)
                .map(|(_, a)| a.clone())
                .ok_or(bad("§14.1 partitions missing"))?;
            let mut c = CollectionImage::new(cmeta, artefact);
            c.big_n = cs.u64()?;
            c.k = cs.u64()?;
            if gs.collection()? != cid {
                return Err(bad("§14.1 groups.bin order"));
            }
            for _ in 0..gs.count(MAX_COUNT)? {
                let header = GroupHeader::read(&mut gs, &layout)?;
                if ss.collection()? != cid || ss.group_id()? != header.group_id {
                    return Err(bad("§14.1 slots.bin order"));
                }
                let k = ss.count(MAX_COUNT)?;
                let mut slots = Vec::with_capacity(k.min(1 << 20));
                for _ in 0..k {
                    slots.push(SlotBytes::read(&mut ss, &layout)?);
                }
                c.push_group(GroupImage { header, slots })?;
            }
            if ls.collection()? != cid {
                return Err(bad("§14.1 locator.bin order"));
            }
            let mut prev: Option<ScrambledId> = None;
            for _ in 0..ls.count(MAX_COUNT)? {
                let sid = ls.scrambled()?;
                if prev.is_some_and(|p| p >= sid) {
                    return Err(bad("§14.1 locator.bin order"));
                }
                prev = Some(sid);
                let g = ls.group_id()?;
                c.locator.insert(sid, (g, ls.u64()?));
            }
            if ps.collection()? != cid {
                return Err(bad("§14.1 payloads.bin order"));
            }
            let mut prev: Option<ScrambledId> = None;
            for _ in 0..ps.count(MAX_COUNT)? {
                let sid = ps.scrambled()?;
                if prev.is_some_and(|p| p >= sid) {
                    return Err(bad("§14.1 payloads.bin order"));
                }
                prev = Some(sid);
                c.payload_refs.insert(sid, PayloadRef::read(&mut ps)?);
            }
            img.collections.insert(cid, c);
        }
        if s.artefacts.len() != img.collections.len() {
            return Err(bad("§14.1 partitions extra"));
        }
        cs.end()?;
        gs.end()?;
        ss.end()?;
        ls.end()?;
        ps.end()?;
        Ok((meta, img))
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use crate::group::encode_accumulator;
    use crate::slot::SlotPayload;
    use sever_spec::spec;
    use sever_types::RecordId;

    pub(crate) fn meta(cid: CollectionId, d: u16) -> CollectionMeta {
        CollectionMeta {
            cid,
            d,
            spawn_target: 8,
            spawning_enabled: true,
            store_passages: false,
            artefact_sha256: [1; 32],
        }
    }

    fn header(id: GroupId, d: usize, n: u64) -> GroupHeader {
        let holding = id == GroupId::Holding;
        GroupHeader {
            group_id: id,
            seal_version: 0,
            n,
            ext_public: vec![],
            centroid: vec![if holding { 0.0 } else { 0.25 }; d],
            sealed_accumulator: if holding {
                vec![]
            } else {
                encode_accumulator(&vec![n as i64; d], &[])
            },
        }
    }

    fn slot(l: &Layout, tag: u8) -> SlotBytes {
        SlotBytes {
            scrambled_id: ScrambledId::from_bytes([tag; 64]),
            envelope: vec![],
            sealed_payload: SlotPayload {
                record_id: RecordId::new(format!("r{tag}")).unwrap(),
                x: vec![i32::from(tag); l.d],
                ext_secret: vec![],
            }
            .encode(l)
            .unwrap(),
        }
    }

    /// A small database built only through `apply`.
    pub(crate) fn sample() -> (DbImage, Layout) {
        let l = Layout::plain(8);
        let mut img = DbImage::default();
        for c in [2u8, 1] {
            let cid = CollectionId::from_bytes([c; 16]);
            let g0 = GroupId::frozen(0).unwrap();
            let recs = vec![
                CoreRecord::CollectionCreate {
                    meta: meta(cid, 8),
                    artefact: vec![c; 10],
                },
                CoreRecord::GroupCreate {
                    cid,
                    header: header(g0, 8, 0),
                    bucket_block: vec![],
                },
                CoreRecord::GroupCreate {
                    cid,
                    header: header(GroupId::Holding, 8, 0),
                    bucket_block: vec![],
                },
                CoreRecord::SlotPut {
                    cid,
                    group: g0,
                    index: 0,
                    slot: slot(&l, 10 + c),
                },
                CoreRecord::SlotPut {
                    cid,
                    group: GroupId::Holding,
                    index: 0,
                    slot: slot(&l, 20 + c),
                },
                CoreRecord::LocatorPut {
                    cid,
                    scrambled_id: ScrambledId::from_bytes([10 + c; 64]),
                    group: g0,
                    index: 0,
                },
                CoreRecord::LocatorPut {
                    cid,
                    scrambled_id: ScrambledId::from_bytes([20 + c; 64]),
                    group: GroupId::Holding,
                    index: 0,
                },
                CoreRecord::PayloadRef {
                    cid,
                    scrambled_id: ScrambledId::from_bytes([10 + c; 64]),
                    at: PayloadRef {
                        segment: 1,
                        offset: 16,
                        len: 5,
                    },
                },
                CoreRecord::GroupHeader {
                    cid,
                    header: header(g0, 8, 1),
                },
                CoreRecord::Counters {
                    cid,
                    big_n: 1,
                    k: 1,
                },
            ];
            for r in &recs {
                img.apply(r).unwrap();
            }
        }
        (img, l)
    }

    #[test]
    #[spec("SR-15.6-1")]
    fn p2_format_checkpoint_streams_round_trip() {
        let (img, l) = sample();
        let cm = CheckpointMeta {
            checkpoint_id: 4,
            next_wal_seq: 100,
            next_txn_id: 9,
            config_hash: [7; 32],
        };
        let s = img.to_streams(&cm, &|_| l).unwrap();
        let (cm2, img2) = DbImage::from_streams(&s, &|_| l).unwrap();
        assert_eq!(cm2, cm);
        assert_eq!(img2, img);
    }

    #[test]
    fn p2_format_checkpoint_streams_reject_truncation_and_extra_bytes() {
        let (img, l) = sample();
        let cm = CheckpointMeta {
            checkpoint_id: 1,
            next_wal_seq: 1,
            next_txn_id: 1,
            config_hash: [0; 32],
        };
        let s = img.to_streams(&cm, &|_| l).unwrap();
        type Field = fn(&mut CheckpointStreams) -> &mut Vec<u8>;
        let fields: [Field; 6] = [
            |s| &mut s.meta,
            |s| &mut s.collections,
            |s| &mut s.groups,
            |s| &mut s.slots,
            |s| &mut s.locator,
            |s| &mut s.payload_refs,
        ];
        for f in fields {
            let mut short = s.clone();
            f(&mut short).pop();
            assert!(DbImage::from_streams(&short, &|_| l).is_err());
            let mut long = s.clone();
            f(&mut long).push(0);
            assert!(DbImage::from_streams(&long, &|_| l).is_err());
        }
        let mut missing = s.clone();
        missing.artefacts.pop();
        assert!(DbImage::from_streams(&missing, &|_| l).is_err());
    }

    #[test]
    #[spec("SR-12.3-1")]
    fn p2_format_apply_is_strict() {
        let (img, l) = sample();
        let cid = CollectionId::from_bytes([1; 16]);
        let g0 = GroupId::frozen(0).unwrap();
        let bad_records = [
            CoreRecord::SlotPut {
                cid,
                group: g0,
                index: 5,
                slot: slot(&l, 1),
            },
            CoreRecord::SlotTruncate {
                cid,
                group: g0,
                len: 9,
            },
            CoreRecord::GroupHeader {
                cid,
                header: header(GroupId::Spawned([1; 8]), 8, 0),
            },
            CoreRecord::LocatorDel {
                cid,
                scrambled_id: ScrambledId::from_bytes([99; 64]),
            },
            CoreRecord::Counters {
                cid: CollectionId::from_bytes([9; 16]),
                big_n: 0,
                k: 0,
            },
            CoreRecord::CollectionCreate {
                meta: meta(cid, 8),
                artefact: vec![],
            },
            CoreRecord::GroupCreate {
                cid,
                header: header(g0, 8, 0),
                bucket_block: vec![],
            },
        ];
        for r in bad_records {
            let mut copy = img.clone();
            assert!(copy.apply(&r).is_err(), "{r:?}");
        }
    }

    #[test]
    fn p2_format_locator_delete_drops_the_payload_reference() {
        let (mut img, _) = sample();
        let cid = CollectionId::from_bytes([1; 16]);
        let sid = ScrambledId::from_bytes([11; 64]);
        assert!(
            img.collection(&cid)
                .unwrap()
                .payload_refs
                .contains_key(&sid)
        );
        img.apply(&CoreRecord::LocatorDel {
            cid,
            scrambled_id: sid,
        })
        .unwrap();
        assert!(
            !img.collection(&cid)
                .unwrap()
                .payload_refs
                .contains_key(&sid)
        );
    }

    #[test]
    fn p2_format_collection_meta_rejects_bad_parameters() {
        let mut w = Writer::new();
        meta(CollectionId::from_bytes([1; 16]), 12).write(&mut w);
        assert!(
            CollectionMeta::read(&mut Reader::new(&w.0, "t")).is_err(),
            "d = 12"
        );
        let mut w = Writer::new();
        meta(CollectionId::from_bytes([1; 16]), 16).write(&mut w);
        w.0[22] = 2; // spawning flag
        assert!(CollectionMeta::read(&mut Reader::new(&w.0, "t")).is_err());
    }

    // §14.9 stream table: offsets below are the spec's. Collections ascend by ID in every file;
    // every parser rejects a wrong order, count or trailing byte.
    const CM: CheckpointMeta = CheckpointMeta {
        checkpoint_id: 1,
        next_wal_seq: 1,
        next_txn_id: 1,
        config_hash: [0; 32],
    };

    fn streams() -> CheckpointStreams {
        let (img, l) = sample();
        img.to_streams(&CM, &|_| l).unwrap()
    }

    fn refused_for(s: &CheckpointStreams, rule: &str) {
        let l = Layout::plain(8);
        match DbImage::from_streams(s, &|_| l) {
            Err(Error::IntegrityViolation { invariant }) => {
                assert!(
                    invariant.contains(rule),
                    "refused for {invariant}, not {rule}"
                )
            }
            other => panic!("accepted or wrong error ({other:?}); wanted {rule}"),
        }
    }

    #[test]
    #[spec("SR-14-2")]
    fn p2_format_checkpoint_streams_refuse_a_wrong_collection_order() {
        let s = streams();
        // meta.bin: 8 + 8 + 8 + 32 + u32 count, then the IDs ascending.
        assert_eq!(&s.meta[56..60], &2u32.to_be_bytes());
        assert_eq!(&s.meta[60..76], &[1; 16]);
        let mut m = s.clone();
        m.meta[76..92].copy_from_slice(&[1; 16]); // [1, 1]: not strictly ascending
        refused_for(&m, "§14.1 meta.bin collection order");
        // Each per-collection stream starts with the first collection's ID.
        let other = [7u8; 16];
        for (name, rule) in [
            ("collections", "§14.1 collections.bin order"),
            ("groups", "§14.1 groups.bin order"),
            ("slots", "§14.1 slots.bin order"),
            ("locator", "§14.1 locator.bin order"),
            ("payloads", "§14.1 payloads.bin order"),
        ] {
            let mut m = s.clone();
            let stream = match name {
                "collections" => &mut m.collections,
                "groups" => &mut m.groups,
                "slots" => &mut m.slots,
                "locator" => &mut m.locator,
                _ => &mut m.payload_refs,
            };
            assert_eq!(&stream[..16], &[1; 16], "{name} starts with collection 1");
            stream[..16].copy_from_slice(&other);
            refused_for(&m, rule);
        }
    }

    #[test]
    #[spec("SR-14-2")]
    fn p2_format_checkpoint_streams_refuse_unsorted_locator_entries() {
        let (mut img, l) = sample();
        // A second locator entry in collection 1, so the order of two entries can be broken.
        let c = img
            .collections
            .get_mut(&CollectionId::from_bytes([1; 16]))
            .unwrap();
        c.locator
            .insert(ScrambledId::from_bytes([99; 64]), (GroupId::Holding, 0));
        c.payload_refs.insert(
            ScrambledId::from_bytes([98; 64]),
            PayloadRef {
                segment: 1,
                offset: 0,
                len: 1,
            },
        );
        let s = img.to_streams(&CM, &|_| l).unwrap();
        // Per collection: ID (16), u64 count, then entries ascending by scrambled_id.
        for (field, entry, rule) in [
            ("locator", 64 + 32 + 8, "§14.1 locator.bin order"),
            ("payloads", 64 + 8 + 8 + 4, "§14.1 payloads.bin order"),
        ] {
            let mut m = s.clone();
            let st = if field == "locator" {
                &mut m.locator
            } else {
                &mut m.payload_refs
            };
            let n = u64::from_be_bytes(st[16..24].try_into().unwrap());
            assert!(n >= 2, "{field}: at least two entries");
            let (a, b) = (24, 24 + entry);
            let first = st[a..b].to_vec();
            let second = st[b..b + entry].to_vec();
            st[a..b].copy_from_slice(&second);
            st[b..b + entry].copy_from_slice(&first);
            refused_for(&m, rule);
        }
    }

    #[test]
    fn p2_format_slot_truncate_to_the_current_count_changes_nothing() {
        // §14.6 SLOT_TRUNCATE carries the new slot count: equal to the current one is valid (and
        // changes nothing); larger is not a truncation and is refused.
        let (mut img, _) = sample();
        let cid = CollectionId::from_bytes([1; 16]);
        let before = img.clone();
        let g0 = GroupId::frozen(0).unwrap();
        img.apply(&CoreRecord::SlotTruncate {
            cid,
            group: g0,
            len: 1,
        })
        .unwrap();
        assert_eq!(img, before);
        assert!(
            img.apply(&CoreRecord::SlotTruncate {
                cid,
                group: g0,
                len: 2
            })
            .is_err()
        );
        img.apply(&CoreRecord::SlotTruncate {
            cid,
            group: g0,
            len: 0,
        })
        .unwrap();
        assert!(img.collections[&cid].group(&g0).unwrap().slots.is_empty());
    }

    #[test]
    #[spec("SR-14-2")]
    fn p2_format_checkpoint_streams_refuse_missing_extra_or_trailing_bytes() {
        let s = streams();
        let mut m = s.clone();
        m.artefacts.pop();
        refused_for(&m, "§14.1 partitions missing");
        let mut m = s.clone();
        m.artefacts
            .push((CollectionId::from_bytes([5; 16]), vec![1]));
        refused_for(&m, "§14.1 partitions extra");
        let mut m = s.clone();
        m.meta.push(0);
        refused_for(&m, "§14.1 meta.bin");
        let mut m = s.clone();
        m.collections.push(0);
        refused_for(&m, "§14.1 collections.bin");
    }
}
