//! EP-7 `KeyRotationParticipant` (spec §13.3, §13.4, §15.3, §15.9; Build 3-4 §2.5).
//!
//! | Protocol step | What it does |
//! |---|---|
//! | `prepare` | keeps only the stage this transaction justifies; rotates every domain a record leaves (§13.3 steps 2–4, through the [`KeyRing`]); logs each new or rotated domain's bucket block (`BUCKET_BLOCK`) and the survivors' re-wrapped envelopes (`EXTENSION`, kind 2), or a drop (kind 3) |
//! | `phase_a` | writes every new group key into the key file before the `COMMIT` (§13.4): a new domain's pair is appended, a rotated domain's key goes to its inactive slot; each `fsync`ed |
//! | `abort` | drops the stage; a pair appended in phase A is remembered, so a retry of the same domain reuses it (its slot is never erased here: the `COMMIT` may have reached the disk, §15.4) |
//! | `after_commit` | adopts the stage; overwrites each retired key's slot with zeros and `fsync`s it (INV-13: only after the `COMMIT` is durable); for a drop, erases every slot of the collection (G-26); appends the transaction's entries to the wrapped-key store |
//! | `replay`, `recover` | merges the WAL tail and the store (monotonic rules, §14.8), applies INV-14 to the key file ([`sever_keys::recovery`]), erases what it says, loads the keys and the stored envelopes into the ring |

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::sync::Arc;

use sever_format::{CoreRecord, RecordType, WalRecord};
use sever_index::GroupExtension;
use sever_keys::Domain;
use sever_keys::file::KeyFile;
use sever_keys::recovery;
use sever_seal::ad::Sid;
use sever_seal::{KeyRing, domain};
use sever_txn::{TxnDraft, TxnKind, TxnParticipant};
use sever_types::Error;
use sever_vfs::Vfs;

use crate::records::{self, Durable, KEY_PARTICIPANT_ID, Value};
use crate::store::WrappedStore;

/// The key file's name in the key directory (§14.1).
pub const KEYS_PATH: &str = "KEYS";

/// Compaction starts when the store holds this many bytes and four times its live bytes (§14.8).
pub const COMPACT_MIN_BYTES: u64 = 1 << 20;

fn missing(what: &'static str) -> Error {
    Error::IntegrityViolation { invariant: what }
}

/// Where a domain's active key lies in the key file.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Slot {
    pair: u64,
    slot: u8,
}

/// What the transaction in flight will do in phase A and phase C.
#[derive(Debug, Default)]
struct Pending {
    /// Store values to append in phase C.
    values: Vec<Vec<u8>>,
    /// Phase A of new domains: `(domain, pair)`.
    created: Vec<(Domain, u64)>,
    /// Phase A of rotations: `(domain, pair, new slot, old slot)`.
    rotated: Vec<(Domain, u64, u8, u8)>,
    /// The collection this transaction drops.
    dropped: Option<[u8; 16]>,
}

/// The key-rotation participant.
pub struct KeyRotationParticipant {
    data: Arc<dyn Vfs>,
    keys_dir: Arc<dyn Vfs>,
    ring: Arc<KeyRing>,
    segment_bytes: u64,
    compact_min: u64,
    keys: Option<KeyFile>,
    store: Option<WrappedStore>,
    slots: BTreeMap<Domain, Slot>,
    /// Pairs appended by a phase A whose transaction aborted, by domain.
    orphans: BTreeMap<Domain, u64>,
    durable: Durable,
    pending: Pending,
}

impl core::fmt::Debug for KeyRotationParticipant {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "KeyRotationParticipant({} domains)", self.slots.len())
    }
}

impl KeyRotationParticipant {
    /// A participant over the data directory `data` (the wrapped-key store) and the key directory
    /// `keys_dir` (`KEYS`), sharing `ring` with the [`sever_seal::AeadSealer`].
    pub fn new(
        data: Arc<dyn Vfs>,
        keys_dir: Arc<dyn Vfs>,
        ring: Arc<KeyRing>,
        segment_bytes: u64,
    ) -> Self {
        Self {
            data,
            keys_dir,
            ring,
            segment_bytes,
            compact_min: COMPACT_MIN_BYTES,
            keys: None,
            store: None,
            slots: BTreeMap::new(),
            orphans: BTreeMap::new(),
            durable: Durable::default(),
            pending: Pending::default(),
        }
    }

    /// Compacts once the store holds `bytes` (default [`COMPACT_MIN_BYTES`]) and four times its
    /// live bytes.
    pub fn with_compaction_at(mut self, bytes: u64) -> Self {
        self.compact_min = bytes;
        self
    }

    /// The ring.
    pub fn ring(&self) -> &Arc<KeyRing> {
        &self.ring
    }

    /// The merged durable state (for tests and the contract digest).
    pub fn durable(&self) -> &Durable {
        &self.durable
    }

    fn key_file(&mut self) -> Result<&mut KeyFile, Error> {
        if self.keys.is_none() {
            let (f, _) = KeyFile::open(Arc::clone(&self.keys_dir), KEYS_PATH)?;
            self.keys = Some(f);
        }
        self.keys.as_mut().ok_or(missing("§14.7 key file"))
    }

    fn wrapped(&mut self) -> Result<&mut WrappedStore, Error> {
        if self.store.is_none() {
            let (s, values) = WrappedStore::open(Arc::clone(&self.data), self.segment_bytes)?;
            for v in values {
                self.durable.merge(records::parse(&v)?);
            }
            self.store = Some(s);
        }
        self.store
            .as_mut()
            .ok_or(missing("§14.8 wrapped-key store"))
    }

    fn extension(value: Vec<u8>) -> (RecordType, Vec<u8>) {
        let mut p = KEY_PARTICIPANT_ID.to_be_bytes().to_vec();
        p.extend(value);
        (RecordType::Extension, p)
    }

    /// §14.8: compact when the store holds four times its live bytes.
    fn maybe_compact(&mut self) -> Result<(), Error> {
        let live: Vec<Vec<u8>> = {
            let mut d = Durable {
                blocks: self.durable.blocks.clone(),
                envelopes: BTreeMap::new(),
                dropped: self.durable.dropped.clone(),
            };
            for (dom, sid, bv, env) in self.ring.stored_envelopes() {
                d.envelopes.insert((dom, sid), (bv, env));
            }
            d.values()
        };
        let live_bytes: u64 = live.iter().map(|v| (v.len() + 16) as u64).sum();
        let min = self.compact_min;
        let store = self.wrapped()?;
        if store.bytes() < min || store.bytes() <= live_bytes.saturating_mul(4) {
            return Ok(());
        }
        store.compact(&live)?;
        // The store now holds only the live entries; forget the superseded envelopes too.
        let mut fresh = Durable::default();
        for v in &live {
            fresh.merge(records::parse(v)?);
        }
        self.durable = fresh;
        Ok(())
    }
}

/// What a draft justifies (see [`KeyRing::retain_stage`]).
#[derive(Default)]
struct Justified {
    new: BTreeSet<Domain>,
    departures: BTreeMap<Domain, Vec<Sid>>,
    joined: HashSet<(Domain, Sid)>,
    left: HashSet<(Domain, Sid)>,
}

fn justified<E: GroupExtension>(draft: &TxnDraft<'_, E>) -> Justified {
    let mut j = Justified::default();
    let cid = draft.collection;
    if draft.kind == TxnKind::CreateCollection {
        for r in &draft.records {
            if let CoreRecord::GroupCreate { cid, header, .. } = r {
                j.new.insert(domain(cid, &header.group_id));
            }
        }
    }
    if let Some(cs) = draft.changeset {
        for c in &cs.created {
            j.new.insert(domain(&cid, &c.id));
        }
        for (g, sid) in &cs.departures {
            let d = domain(&cid, g);
            j.departures.entry(d).or_default().push(*sid.as_bytes());
            j.left.insert((d, *sid.as_bytes()));
        }
        for (g, sid) in &cs.arrivals {
            j.joined.insert((domain(&cid, g), *sid.as_bytes()));
        }
    }
    j
}

impl<E: GroupExtension> TxnParticipant<E> for KeyRotationParticipant {
    fn id(&self) -> u16 {
        KEY_PARTICIPANT_ID
    }

    fn owned_types(&self) -> &[RecordType] {
        &[RecordType::BucketBlock]
    }

    fn prepare(&mut self, draft: &mut TxnDraft<'_, E>) -> Result<(), Error> {
        self.pending = Pending::default();
        if draft.kind == TxnKind::DropCollection {
            let cid = *draft.collection.as_bytes();
            let none = BTreeSet::new();
            self.ring
                .retain_stage(&none, &none, &HashSet::new(), &HashSet::new());
            self.ring.drop_collection(&cid);
            let v = records::drop_value(&cid);
            draft.participant_records.push(Self::extension(v.clone()));
            self.pending.values.push(v);
            self.pending.dropped = Some(cid);
            return Ok(());
        }
        let j = justified(draft);
        let rotated: BTreeSet<Domain> = j.departures.keys().copied().collect();
        self.ring.retain_stage(&j.new, &rotated, &j.joined, &j.left);
        // §13.3 steps 2–4 for every domain a record leaves.
        let mut blocks: BTreeSet<Domain> = BTreeSet::new();
        for (d, sids) in &j.departures {
            if cfg!(feature = "noerase") {
                // DB-54 `sever-db-noerase` (EX-7): the record leaves; no key rotates, so nothing
                // is erased and its envelope stays openable under the live bucket key.
                for sid in sids {
                    self.ring.depart(d, sid);
                }
                continue;
            }
            let holding =
                d.group_id == domain(&draft.collection, &sever_types::GroupId::Holding).group_id;
            let skip_buckets =
                cfg!(feature = "sabotage-SB-25") || (cfg!(feature = "sabotage-SB-26") && holding);
            let rot = if skip_buckets {
                // SB-25 (every domain) / SB-26 (the holding area): the group key rotates, the
                // buckets the records left keep their keys.
                for sid in sids {
                    self.ring.depart(d, sid);
                }
                self.ring.rotate(d, &[])?
            } else {
                self.ring.rotate(d, sids)?
            };
            if !rot.envelopes.is_empty() {
                let v = records::envelopes_value(d, &rot.envelopes);
                draft.participant_records.push(Self::extension(v.clone()));
                self.pending.values.push(v);
            }
            blocks.insert(*d);
        }
        for (d, _, _) in self.ring.staged_new() {
            blocks.insert(d);
        }
        for d in &blocks {
            let (version, block) = self.ring.staged_block(d)?;
            let value = records::block_value(d, version, &block);
            draft.participant_records.push((
                RecordType::BucketBlock,
                value.get(1..).unwrap_or_default().to_vec(),
            ));
            self.pending.values.push(value);
        }
        Ok(())
    }

    fn phase_a(&mut self) -> Result<(), Error> {
        let new = self.ring.staged_new();
        let rotations = self.ring.staged_rotations()?;
        if new.is_empty() && rotations.is_empty() {
            return Ok(());
        }
        for (d, version, key) in new {
            let reuse = self.orphans.remove(&d);
            let kf = self.key_file()?;
            let pair = match reuse {
                Some(pair) => {
                    kf.write_slot(pair, 0, d, version, &key)?;
                    pair
                }
                None => kf.append(d, version, &key)?,
            };
            self.pending.created.push((d, pair));
        }
        for (d, _old, version, key) in rotations {
            let at = *self
                .slots
                .get(&d)
                .ok_or(missing("§13.4 rotation of a domain without a key slot"))?;
            let inactive = 1 - at.slot;
            self.key_file()?
                .write_slot(at.pair, inactive, d, version, &key)?;
            self.pending.rotated.push((d, at.pair, inactive, at.slot));
            if cfg!(feature = "sabotage-SB-27") {
                // SB-27: erase the old key before the COMMIT is durable.
                self.key_file()?.erase_slot(at.pair, at.slot)?;
            }
        }
        Ok(())
    }

    fn abort(&mut self) {
        self.ring.discard();
        for (d, pair) in std::mem::take(&mut self.pending.created) {
            self.orphans.insert(d, pair);
        }
        self.pending = Pending::default();
    }

    fn after_commit(&mut self) -> Result<(), Error> {
        let pending = std::mem::take(&mut self.pending);
        self.ring.adopt();
        for (d, pair) in &pending.created {
            self.slots.insert(
                *d,
                Slot {
                    pair: *pair,
                    slot: 0,
                },
            );
        }
        // INV-13: the COMMIT is durable, so each retired key's slot is overwritten now (phase C).
        for (d, pair, new, old) in &pending.rotated {
            self.slots.insert(
                *d,
                Slot {
                    pair: *pair,
                    slot: *new,
                },
            );
            self.key_file()?.erase_slot(*pair, *old)?;
        }
        if let Some(cid) = pending.dropped {
            let gone: Vec<(Domain, Slot)> = self
                .slots
                .iter()
                .filter(|(d, _)| d.collection_id == cid)
                .map(|(d, s)| (*d, *s))
                .collect();
            for (d, s) in gone {
                let kf = self.key_file()?;
                kf.erase_slot(s.pair, 0)?;
                kf.erase_slot(s.pair, 1)?;
                self.slots.remove(&d);
            }
        }
        if pending.values.is_empty() {
            return Ok(());
        }
        self.wrapped()?.append(&pending.values)?;
        for v in &pending.values {
            self.durable.merge(records::parse(v)?);
        }
        self.maybe_compact()
    }

    fn replay(&mut self, record: &WalRecord) -> Result<(), Error> {
        let value = match record.ty {
            RecordType::BucketBlock => [&[records::KIND_BLOCK][..], &record.payload].concat(),
            RecordType::Extension => record.payload.get(2..).unwrap_or_default().to_vec(),
            _ => return Ok(()),
        };
        self.durable.merge(records::parse(&value)?);
        Ok(())
    }

    fn recover(&mut self) -> Result<(), Error> {
        // The WAL tail was merged by `replay`; the store merges into the same state (§14.8).
        self.wrapped()?;
        let (kf, slots) = KeyFile::open(Arc::clone(&self.keys_dir), KEYS_PATH)?;
        self.keys = Some(kf);
        let active: BTreeMap<Domain, u64> = self
            .durable
            .blocks
            .iter()
            .map(|(d, (v, _))| (*d, *v))
            .collect();
        let plan = recovery::plan(&active, slots)?;
        for (pair, slot) in &plan.erase {
            self.key_file()?.erase_slot(*pair, *slot)?;
        }
        self.slots.clear();
        for (d, k) in plan.keys {
            let block = &self
                .durable
                .blocks
                .get(&d)
                .ok_or(missing("§14.8 bucket block"))?
                .1;
            self.ring.load_domain(d, k.key_version, k.key, block)?;
            self.slots.insert(
                d,
                Slot {
                    pair: k.pair,
                    slot: k.slot,
                },
            );
        }
        for ((d, sid), (bv, env)) in &self.durable.envelopes {
            self.ring.load_envelope(*d, *sid, *bv, *env);
        }
        Ok(())
    }

    fn check_invariants(&self) -> Result<(), Error> {
        // After the engine opened every slot through the sealer, the store's envelopes that no slot
        // claimed are stale (§14.4); INV-14: every domain the ring knows has its key slot.
        self.ring.finish_recovery();
        let ring_domains: BTreeSet<Domain> = self.ring.active_versions().into_keys().collect();
        let slot_domains: BTreeSet<Domain> = self.slots.keys().copied().collect();
        if ring_domains == slot_domains {
            Ok(())
        } else {
            Err(missing("INV-14"))
        }
    }

    fn on_drop_collection(&mut self, _collection: &sever_types::CollectionId) -> Result<(), Error> {
        // §15.9 (G-26): the erase happens in phase C of the drop transaction.
        Ok(())
    }
}

/// The participant's records in a WAL record list, parsed (for tests and audits).
pub fn parse_wal(r: &WalRecord) -> Option<Value> {
    match r.ty {
        RecordType::BucketBlock => {
            records::parse(&[&[records::KIND_BLOCK][..], &r.payload].concat()).ok()
        }
        RecordType::Extension
            if r.payload.get(..2) == Some(&KEY_PARTICIPANT_ID.to_be_bytes()[..]) =>
        {
            records::parse(r.payload.get(2..)?).ok()
        }
        _ => None,
    }
}
