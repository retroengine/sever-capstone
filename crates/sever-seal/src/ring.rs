//! The key ring: every domain's keys and every live record's current envelope, shared by the
//! [`crate::AeadSealer`] (EP-6) and the key-rotation participant (EP-7, `sever-erasure`).
//!
//! **Committed state:** per domain its group key with version and its 64 bucket keys with versions;
//! per live record its current envelope (§14.4, DB-91), whether that envelope lives in the
//! wrapped-key store, and each bucket's members (to find the survivors a rotation re-wraps). The
//! envelopes are learned from the engine itself: at startup every slot is opened through the
//! sealer, and afterwards every seal and re-wrap goes through it.
//!
//! **The stage:** what the current transaction changes. The sealer stages while the core plans (a
//! new domain's keys when a group is created, a rotated group key when the core asks for the next
//! version after a departure, the envelopes of records that join a domain); the participant stages
//! the rest in `prepare` ([`KeyRing::rotate`]: the departures, the rotated buckets' new keys and the
//! survivors' re-wrapped envelopes), adopts the stage after the commit ([`KeyRing::adopt`]) or
//! discards it ([`KeyRing::discard`]). Lookups see the stage first, so the transaction reads its own
//! writes.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::sync::{Mutex, MutexGuard, PoisonError};

use sever_keys::{BUCKETS, Domain, Key, bucket_of};
use sever_types::Error;

use crate::ad::Sid;
use crate::block::{self, BucketKey, Envelope};

/// A domain's keys.
#[derive(Debug)]
pub struct DomainKeys {
    /// The group key's version.
    pub version: u64,
    /// The group key `GK_g`.
    pub key: Key,
    /// The 64 bucket keys `BK_{g,b}` with their versions.
    pub buckets: Vec<BucketKey>,
}

impl DomainKeys {
    /// Fresh keys for a new domain: every key at version 1 (§13.3: a new group starts fresh).
    pub fn fresh() -> Self {
        Self {
            version: 1,
            key: Key::generate(),
            buckets: (0..BUCKETS).map(|_| BucketKey::generate(1)).collect(),
        }
    }
}

/// A live record's current envelope.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Entry {
    env: Envelope,
    /// `Some(bucket_version)` when the envelope lives in the wrapped-key store (a re-wrap).
    stored: Option<u64>,
}

#[derive(Default)]
struct Stage {
    new: BTreeMap<Domain, DomainKeys>,
    rotate: BTreeMap<Domain, (u64, Key)>,
    buckets: BTreeMap<(Domain, u8), BucketKey>,
    put: HashMap<(Domain, Sid), Entry>,
    del: HashSet<(Domain, Sid)>,
    drop: BTreeSet<[u8; 16]>,
}

impl Stage {
    fn is_empty(&self) -> bool {
        self.new.is_empty()
            && self.rotate.is_empty()
            && self.buckets.is_empty()
            && self.put.is_empty()
            && self.del.is_empty()
            && self.drop.is_empty()
    }
}

#[derive(Default)]
struct Inner {
    domains: BTreeMap<Domain, DomainKeys>,
    envelopes: HashMap<(Domain, Sid), Entry>,
    members: HashMap<(Domain, u8), BTreeSet<Sid>>,
    /// Envelopes read from the wrapped-key store during recovery, used when the slot is first
    /// opened and then dropped.
    overrides: HashMap<(Domain, Sid), (u64, Envelope)>,
    stage: Stage,
}

/// What a rotation staged for one domain (§13.3 steps 1–4).
#[derive(Debug)]
pub struct Rotation {
    /// The domain.
    pub domain: Domain,
    /// The new group key version.
    pub version: u64,
    /// The survivors' re-wrapped envelopes: `(scrambled_id, bucket_version, envelope)`.
    pub envelopes: Vec<(Sid, u64, Envelope)>,
}

/// What adopting a stage changed, for phase C.
#[derive(Debug, Default)]
pub struct Adopted {
    /// Domains created: `(domain, version)`.
    pub created: Vec<(Domain, u64)>,
    /// Domains rotated: `(domain, old version, new version)`.
    pub rotated: Vec<(Domain, u64, u64)>,
    /// Collections dropped, with the domains they had.
    pub dropped: Vec<([u8; 16], Vec<Domain>)>,
}

/// A live entry of the wrapped-key store (for compaction): `(domain, scrambled_id,
/// bucket_version, envelope)`.
pub type StoredEnvelope = (Domain, Sid, u64, Envelope);

fn missing(what: &'static str) -> Error {
    Error::IntegrityViolation { invariant: what }
}

/// The shared key state.
#[derive(Default)]
pub struct KeyRing {
    inner: Mutex<Inner>,
}

impl core::fmt::Debug for KeyRing {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.write_str("KeyRing(<redacted>)")
    }
}

impl Inner {
    /// The bucket key a value of `d`'s bucket `b` is wrapped under, as of the stage.
    fn bucket(&self, d: &Domain, b: u8) -> Result<&BucketKey, Error> {
        if let Some(k) = self.stage.buckets.get(&(*d, b)) {
            return Ok(k);
        }
        self.committed_bucket(d, b)
    }

    /// The bucket key before this transaction's rotation of it.
    fn committed_bucket(&self, d: &Domain, b: u8) -> Result<&BucketKey, Error> {
        let keys = self
            .stage
            .new
            .get(d)
            .or_else(|| self.domains.get(d))
            .ok_or(missing("§13.1 unknown key domain"))?;
        keys.buckets
            .get(usize::from(b))
            .ok_or(missing("§13.1 bucket"))
    }

    /// The envelope of `(d, sid)` as of the stage. A record never seen is learned from `slot`
    /// (its slot's envelope): the wrapped-key store's entry when its version is the bucket's
    /// current one (§14.4, DB-91), otherwise the slot's; the second value is that entry, to be
    /// remembered once the envelope has opened.
    fn envelope(
        &self,
        d: &Domain,
        sid: &Sid,
        slot: &[u8],
    ) -> Result<(Envelope, Option<Entry>), Error> {
        if let Some(e) = self.stage.put.get(&(*d, *sid)) {
            return Ok((e.env, None));
        }
        if self.stage.del.contains(&(*d, *sid)) {
            // The record left `d` in this transaction (a flush): the core may still name it by the
            // envelope it was sealed with (its passage is sealed after the move). That envelope
            // opens only under the keys it was wrapped with, which the rotation retires.
            let env = slot.try_into().map_err(|_| missing("§14.4 envelope"))?;
            return Ok((env, None));
        }
        if let Some(e) = self.envelopes.get(&(*d, *sid)) {
            return Ok((e.env, None));
        }
        let current = self.committed_bucket(d, bucket_of(sid))?.version;
        let entry = match self.overrides.get(&(*d, *sid)) {
            Some((v, env)) if *v == current => Entry {
                env: *env,
                stored: Some(*v),
            },
            _ => Entry {
                env: slot.try_into().map_err(|_| missing("§14.4 envelope"))?,
                stored: None,
            },
        };
        Ok((entry.env, Some(entry)))
    }

    /// Remembers a record learned by [`Inner::envelope`].
    fn learn(&mut self, d: &Domain, sid: &Sid, entry: Entry) {
        self.overrides.remove(&(*d, *sid));
        self.envelopes.insert((*d, *sid), entry);
        self.members
            .entry((*d, bucket_of(sid)))
            .or_default()
            .insert(*sid);
    }

    fn group_key(&self, d: &Domain, version: u64) -> Option<&Key> {
        if let Some((v, k)) = self.stage.rotate.get(d) {
            if *v == version {
                return Some(k);
            }
        }
        self.stage
            .new
            .get(d)
            .or_else(|| self.domains.get(d))
            .filter(|k| k.version == version)
            .map(|k| &k.key)
    }
}

impl KeyRing {
    /// An empty ring.
    pub fn new() -> Self {
        Self::default()
    }

    fn lock(&self) -> MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    // --- the sealer's side (while the core plans) --------------------------------------------

    /// EP-6 `next_version`: a new domain's keys are created (version 1); a departure stages a new
    /// group key at version + 1 (§13.3 step 1); otherwise the version is unchanged.
    pub fn next_version(&self, d: &Domain, prev: Option<u64>, departure: bool) -> u64 {
        let mut st = self.lock();
        let inner = &mut *st;
        match (prev, departure) {
            (None, _) => {
                inner
                    .stage
                    .new
                    .entry(*d)
                    .or_insert_with(DomainKeys::fresh)
                    .version
            }
            (Some(v), false) => v,
            (Some(v), true) => {
                let next = v.saturating_add(1);
                // A key staged for this version by an attempt that never committed is reused: it
                // was never written anywhere a commit could read it.
                if inner.stage.rotate.get(d).map(|(s, _)| *s) != Some(next) {
                    let key = match inner.domains.get(d) {
                        // SB-24: the group key is not rotated; its version moves on, its bytes stay.
                        Some(k) if cfg!(feature = "sabotage-SB-24") => k.key.duplicate(),
                        _ => Key::generate(),
                    };
                    inner.stage.rotate.insert(*d, (next, key));
                }
                next
            }
        }
    }

    /// The group key of `d` at `version` (staged or committed), copied.
    pub fn group_key(&self, d: &Domain, version: u64) -> Result<Key, Error> {
        self.lock()
            .group_key(d, version)
            .map(Key::duplicate)
            .ok_or(missing("§13.1 group key version"))
    }

    /// A record joins `d` with record key `rk` (a new slot, §13.3: under the current keys). A
    /// domain the ring does not know gets fresh keys, as `next_version(None)` gives a new group.
    pub fn join(&self, d: &Domain, sid: &Sid, rk: &Key) -> Result<Envelope, Error> {
        let mut st = self.lock();
        if !st.domains.contains_key(d) {
            st.stage.new.entry(*d).or_insert_with(DomainKeys::fresh);
        }
        let bk = st.bucket(d, bucket_of(sid))?;
        let env = block::wrap_record_key(bk, d, sid, rk)?;
        st.stage.put.insert((*d, *sid), Entry { env, stored: None });
        st.stage.del.remove(&(*d, *sid));
        Ok(env)
    }

    /// The record key of `(d, sid)`, whose slot carries envelope `slot`.
    pub fn record_key(&self, d: &Domain, sid: &Sid, slot: &[u8]) -> Result<Key, Error> {
        let mut st = self.lock();
        let (env, learned) = st.envelope(d, sid, slot)?;
        let bk = st.bucket(d, bucket_of(sid))?;
        let rk = block::unwrap_record_key(bk, d, sid, &env)?;
        if let Some(entry) = learned {
            st.learn(d, sid, entry);
        }
        Ok(rk)
    }

    /// A record moves from `from` to `to` (a flush): its record key, re-wrapped for `to`.
    pub fn move_record(
        &self,
        from: &Domain,
        to: &Domain,
        sid: &Sid,
        slot: &[u8],
    ) -> Result<Envelope, Error> {
        let rk = self.record_key(from, sid, slot)?;
        self.depart(from, sid);
        self.join(to, sid, &rk)
    }

    // --- the participant's side ----------------------------------------------------------------

    /// Stages the rotation of `d` after the departure of `departed` (§13.3 steps 2–4): new bucket
    /// keys for every bucket that lost a record, and every survivor of those buckets re-wrapped.
    /// The core must already have asked for the domain's next version (step 1).
    pub fn rotate(&self, d: &Domain, departed: &[Sid]) -> Result<Rotation, Error> {
        let mut st = self.lock();
        let inner = &mut *st;
        let version = inner
            .stage
            .rotate
            .get(d)
            .map(|(v, _)| *v)
            .ok_or(missing("§13.3 a departure without a new group key version"))?;
        for sid in departed {
            inner.stage.del.insert((*d, *sid));
            inner.stage.put.remove(&(*d, *sid));
        }
        let lost: BTreeSet<u8> = departed.iter().map(bucket_of).collect();
        let mut envelopes = Vec::new();
        for b in lost {
            let old = inner.committed_bucket(d, b)?.duplicate();
            let new = BucketKey::generate(old.version.saturating_add(1));
            let mut survivors: BTreeSet<Sid> =
                inner.members.get(&(*d, b)).cloned().unwrap_or_default();
            survivors.extend(
                inner
                    .stage
                    .put
                    .keys()
                    .filter(|(dd, s)| dd == d && bucket_of(s) == b)
                    .map(|(_, s)| *s),
            );
            for sid in survivors {
                if inner.stage.del.contains(&(*d, sid)) {
                    continue;
                }
                let env = match inner.stage.put.get(&(*d, sid)) {
                    Some(e) => e.env,
                    None => {
                        inner
                            .envelopes
                            .get(&(*d, sid))
                            .ok_or(missing("§14.4 survivor's envelope"))?
                            .env
                    }
                };
                let rk = block::unwrap_record_key(&old, d, &sid, &env)?;
                let env = block::wrap_record_key(&new, d, &sid, &rk)?;
                inner.stage.put.insert(
                    (*d, sid),
                    Entry {
                        env,
                        stored: Some(new.version),
                    },
                );
                envelopes.push((sid, new.version, env));
            }
            inner.stage.buckets.insert((*d, b), new);
        }
        Ok(Rotation {
            domain: *d,
            version,
            envelopes,
        })
    }

    /// A record leaves `d` (it is staged as gone; the rotation of `d` is [`KeyRing::rotate`]).
    pub fn depart(&self, d: &Domain, sid: &Sid) {
        let mut st = self.lock();
        st.stage.del.insert((*d, *sid));
        st.stage.put.remove(&(*d, *sid));
    }

    /// Keeps only what the current transaction justifies: the domains it creates (`new`) and
    /// rotates (`rotated`), the records that join a domain (`joined`) and leave one (`left`).
    /// Anything else was staged by an attempt that failed while the core planned (no participant
    /// hook runs then) and is dropped, so it can never be adopted with a later transaction.
    pub fn retain_stage(
        &self,
        new: &BTreeSet<Domain>,
        rotated: &BTreeSet<Domain>,
        joined: &HashSet<(Domain, Sid)>,
        left: &HashSet<(Domain, Sid)>,
    ) {
        let mut st = self.lock();
        let stage = &mut st.stage;
        stage.new.retain(|d, _| new.contains(d));
        stage.rotate.retain(|d, _| rotated.contains(d));
        stage.buckets.clear();
        stage.put.retain(|k, _| joined.contains(k));
        stage.del.retain(|k| left.contains(k));
        stage.drop.clear();
    }

    /// Stages the drop of collection `cid` (§15.9).
    pub fn drop_collection(&self, cid: &[u8; 16]) {
        self.lock().stage.drop.insert(*cid);
    }

    /// The domains this transaction creates, with their keys (phase A appends their key-file pairs).
    pub fn staged_new(&self) -> Vec<(Domain, u64, Key)> {
        self.lock()
            .stage
            .new
            .iter()
            .map(|(d, k)| (*d, k.version, k.key.duplicate()))
            .collect()
    }

    /// The domains this transaction rotates: `(domain, old version, new version, new key)`.
    pub fn staged_rotations(&self) -> Result<Vec<(Domain, u64, u64, Key)>, Error> {
        let st = self.lock();
        st.stage
            .rotate
            .iter()
            .map(|(d, (v, k))| {
                let old = st
                    .domains
                    .get(d)
                    .ok_or(missing("§13.3 rotation of an unknown domain"))?
                    .version;
                Ok((*d, old, *v, k.duplicate()))
            })
            .collect()
    }

    /// The bucket block of a domain created or rotated in this transaction, under its new group
    /// key (§13.3 step 3: all 64 bucket keys re-wrapped), with that key's version.
    pub fn staged_block(&self, d: &Domain) -> Result<(u64, Vec<u8>), Error> {
        let st = self.lock();
        if let Some(k) = st.stage.new.get(d) {
            return Ok((
                k.version,
                block::encode_block(&k.key, d, k.version, &k.buckets)?,
            ));
        }
        let (v, gk) = st
            .stage
            .rotate
            .get(d)
            .ok_or(missing("§13.3 no staged keys"))?;
        let buckets: Vec<BucketKey> = (0..BUCKETS)
            .map(|b| st.bucket(d, b).map(BucketKey::duplicate))
            .collect::<Result<_, _>>()?;
        Ok((*v, block::encode_block(gk, d, *v, &buckets)?))
    }

    /// True when nothing is staged.
    pub fn stage_is_empty(&self) -> bool {
        self.lock().stage.is_empty()
    }

    /// Makes the stage the committed state (after the `COMMIT`, §15.3 step 7); returns what changed.
    pub fn adopt(&self) -> Adopted {
        let mut st = self.lock();
        let inner = &mut *st;
        let stage = std::mem::take(&mut inner.stage);
        let mut out = Adopted::default();
        for (d, keys) in stage.new {
            out.created.push((d, keys.version));
            inner.domains.insert(d, keys);
        }
        for (d, (v, key)) in stage.rotate {
            if let Some(keys) = inner.domains.get_mut(&d) {
                out.rotated.push((d, keys.version, v));
                keys.version = v;
                keys.key = key;
            }
        }
        for ((d, b), bk) in stage.buckets {
            if let Some(slot) = inner
                .domains
                .get_mut(&d)
                .and_then(|k| k.buckets.get_mut(usize::from(b)))
            {
                *slot = bk;
            }
        }
        for (d, sid) in stage.del {
            inner.envelopes.remove(&(d, sid));
            if let Some(m) = inner.members.get_mut(&(d, bucket_of(&sid))) {
                m.remove(&sid);
            }
        }
        for ((d, sid), e) in stage.put {
            inner.envelopes.insert((d, sid), e);
            inner
                .members
                .entry((d, bucket_of(&sid)))
                .or_default()
                .insert(sid);
        }
        for cid in stage.drop {
            let gone: Vec<Domain> = inner
                .domains
                .keys()
                .filter(|d| d.collection_id == cid)
                .copied()
                .collect();
            for d in &gone {
                inner.domains.remove(d);
            }
            inner.envelopes.retain(|(d, _), _| d.collection_id != cid);
            inner.members.retain(|(d, _), _| d.collection_id != cid);
            out.dropped.push((cid, gone));
        }
        out
    }

    /// Drops the stage (the transaction did not commit).
    pub fn discard(&self) {
        self.lock().stage = Stage::default();
    }

    // --- recovery ------------------------------------------------------------------------------

    /// Installs a domain's committed keys (recovery): group key `gk` at `version` and its bucket
    /// block.
    pub fn load_domain(&self, d: Domain, version: u64, gk: Key, block: &[u8]) -> Result<(), Error> {
        let buckets = block::decode_block(&gk, &d, version, block)?;
        self.lock().domains.insert(
            d,
            DomainKeys {
                version,
                key: gk,
                buckets,
            },
        );
        Ok(())
    }

    /// An envelope from the wrapped-key store (recovery), used when its slot is first opened if its
    /// version is then the bucket's current one.
    pub fn load_envelope(&self, d: Domain, sid: Sid, bucket_version: u64, env: Envelope) {
        let mut st = self.lock();
        let keep = st
            .overrides
            .get(&(d, sid))
            .is_none_or(|(v, _)| *v < bucket_version);
        if keep {
            st.overrides.insert((d, sid), (bucket_version, env));
        }
    }

    /// Forgets the store's envelopes that no slot claimed (after the engine opened every slot).
    pub fn finish_recovery(&self) {
        self.lock().overrides.clear();
    }

    /// Every committed domain and its group key version (INV-14 at startup).
    pub fn active_versions(&self) -> BTreeMap<Domain, u64> {
        self.lock()
            .domains
            .iter()
            .map(|(d, k)| (*d, k.version))
            .collect()
    }

    /// The committed envelopes that live in the wrapped-key store (its live entries, for
    /// compaction).
    pub fn stored_envelopes(&self) -> Vec<StoredEnvelope> {
        let st = self.lock();
        let mut out: Vec<StoredEnvelope> = st
            .envelopes
            .iter()
            .filter_map(|((d, sid), e)| e.stored.map(|v| (*d, *sid, v, e.env)))
            .collect();
        out.sort_by_key(|a| (a.0, a.1));
        out
    }

    /// The committed bucket block of `d` under its current group key (for compaction).
    pub fn committed_block(&self, d: &Domain) -> Result<(u64, Vec<u8>), Error> {
        let st = self.lock();
        let k = st
            .domains
            .get(d)
            .ok_or(missing("§13.1 unknown key domain"))?;
        Ok((
            k.version,
            block::encode_block(&k.key, d, k.version, &k.buckets)?,
        ))
    }
}
