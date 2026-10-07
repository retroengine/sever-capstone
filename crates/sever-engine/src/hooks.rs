//! Inspection hooks for tests, the crash kit and the demo (§16.1 `#[cfg(feature =
//! "test-hooks")]`): never compiled into release or measured builds.

use sever_format::SlotPayload;
use sever_index::GroupSnapshot;
use sever_txn::{RecordOwner, Sealer, Step, StoredExtension};
use sever_types::{CollectionId, Error, GroupId, RecordId};

use crate::engine::Engine;

/// A collection's whole logical state, in a canonical order: what a crash test compares with
/// the oracle (Build §5.5: "the recovered state MUST equal exactly one of two states").
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CanonicalState {
    /// Every frozen and spawned group's ID and canonical blob (§5.5), ascending by ID bytes.
    pub groups: Vec<(String, Vec<u8>)>,
    /// The holding area's record IDs, ascending by bytes.
    pub holding: Vec<String>,
    /// `N`.
    pub big_n: u64,
    /// `k`.
    pub k: u64,
}

impl<E: StoredExtension, S: Sealer> Engine<E, S> {
    /// Installs a function called at every protocol step boundary of every write (P2-T4: a
    /// reader runs there). The function runs on the writer's thread without the state lock, so
    /// it may call `search`, `stats` and the other read methods.
    pub fn set_step_hook(&self, hook: Option<Box<dyn FnMut(Step) + Send>>) {
        self.writer.lock().unwrap_or_else(|p| p.into_inner()).hook = hook;
    }

    /// Where a live record is (its group's text form), or `None`.
    pub fn location(&self, cid: CollectionId, record_id: &str) -> Option<String> {
        let st = self.read();
        st.live
            .get(&cid)
            .and_then(|ix| ix.location(record_id))
            .map(|g| g.as_text())
    }

    /// §16.1 `group_snapshot`: `S`, `n`, extension state, canonical blob, member IDs.
    pub fn group_snapshot(&self, cid: CollectionId, group: &GroupId) -> Option<GroupSnapshot<E>> {
        self.read().live.get(&cid)?.group_snapshot(group)
    }

    /// The survivors check's other side (Build §4.7 L6): the group rebuilt from its members.
    pub fn survivors_snapshot(
        &self,
        cid: CollectionId,
        group: &GroupId,
    ) -> Option<GroupSnapshot<E>> {
        self.read().live.get(&cid)?.survivors_snapshot(group)
    }

    /// Every frozen and spawned group ID.
    pub fn group_ids(&self, cid: CollectionId) -> Vec<GroupId> {
        self.read()
            .live
            .get(&cid)
            .map(|ix| ix.group_ids())
            .unwrap_or_default()
    }

    /// The collection's [`CanonicalState`].
    pub fn canonical_state(&self, cid: CollectionId) -> Result<CanonicalState, Error> {
        let st = self.read();
        let ix = st.live.get(&cid).ok_or(Error::UnknownCollection)?;
        let coll = st.image.collection(&cid).ok_or(Error::UnknownCollection)?;
        let mut groups: Vec<(String, Vec<u8>)> = ix
            .group_ids()
            .into_iter()
            .filter_map(|g| ix.blob(&g).map(|b| (g.as_text(), b)))
            .collect();
        groups.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
        let layout = self.layout(ix.d());
        let mut holding = Vec::new();
        if let Some(h) = coll.group(&GroupId::Holding) {
            for sb in &h.slots {
                let owner = RecordOwner {
                    collection: &cid,
                    group: &GroupId::Holding,
                    scrambled_id: &sb.scrambled_id,
                };
                let plain = self
                    .sealer
                    .open_record(&owner, &sb.envelope, &sb.sealed_payload)?;
                holding.push(
                    SlotPayload::parse(&plain, &layout)?
                        .record_id
                        .as_str()
                        .to_owned(),
                );
            }
        }
        holding.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
        let s = ix.stats();
        Ok(CanonicalState {
            groups,
            holding,
            big_n: s.big_n,
            k: s.k,
        })
    }

    /// The stored passage text of a live record, read back through the sealer.
    pub fn passage(&self, cid: CollectionId, record_id: &str) -> Result<Option<Vec<u8>>, Error> {
        use sever_appendstore::AppendStore;
        use sever_index::IdScrambler;
        let rid = RecordId::new(record_id)?;
        let sid = sever_index::HmacSha512Scrambler::new(&self.k_scramble).scramble(&cid, &rid);
        let (at, envelope, group) = {
            let st = self.read();
            let coll = st.image.collection(&cid).ok_or(Error::UnknownCollection)?;
            let Some(at) = coll.payload_refs.get(&sid).copied() else {
                return Ok(None);
            };
            let (g, i) = coll
                .locator
                .get(&sid)
                .copied()
                .ok_or(Error::IntegrityViolation { invariant: "INV-7" })?;
            let slot = coll
                .group(&g)
                .and_then(|gi| gi.slots.get(i as usize))
                .ok_or(Error::IntegrityViolation { invariant: "INV-7" })?;
            (at, slot.envelope.clone(), g)
        };
        let rec = self
            .writer
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .store
            .read(&at)?;
        let owner = RecordOwner {
            collection: &cid,
            group: &group,
            scrambled_id: &sid,
        };
        Ok(Some(
            self.sealer
                .open_passage(&owner, &envelope, &rec.bytes)?
                .to_vec(),
        ))
    }
}
