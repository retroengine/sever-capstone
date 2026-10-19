//! Inspection helpers: the key file as it is on disk, and every ciphertext the engine ever wrote to
//! the WAL (the rotation shadow model of Build 3-4 §2.8 L2 reads them back with the keys the
//! database still holds).

use std::collections::BTreeMap;
use std::sync::Arc;

use sever_format::{CoreRecord, RecordType};
use sever_index::NoExtension;
use sever_keys::Domain;
use sever_keys::file::{KeyFile, SlotState};
use sever_seal::block::{self, BucketKey};
use sever_seal::{AeadSealer, KeyRing, ad, aead};
use sever_types::CollectionId;
use sever_vfs::SimVfs;
use sever_wal::{Wal, WalConfig};

use crate::parse_wal;
use crate::records::Value;

/// The domain of a group named by its text form (what `Engine::location` returns).
pub fn domain_of(cid: CollectionId, text: &str) -> Domain {
    let mut group_id = [0u8; 32];
    group_id[..text.len()].copy_from_slice(text.as_bytes());
    Domain {
        collection_id: *cid.as_bytes(),
        group_id,
    }
}

/// The key file's slots as a fresh open reads them (on a copy of the key disk).
pub fn key_slots(keys: &SimVfs) -> Vec<[SlotState; 2]> {
    KeyFile::open(Arc::new(keys.fork()), crate::KEYS_PATH)
        .unwrap()
        .1
}

/// Every valid slot naming `d`: `(pair, slot, version)`.
pub fn slots_of(keys: &SimVfs, d: &Domain) -> Vec<(u64, u8, u64)> {
    let mut out = Vec::new();
    for (pair, two) in (0u64..).zip(key_slots(keys)) {
        for (slot, s) in (0u8..).zip(two) {
            if let SlotState::Valid(r) = s {
                if r.domain == *d {
                    out.push((pair, slot, r.key_version));
                }
            }
        }
    }
    out
}

/// What the WAL ever held, for one domain.
#[derive(Default)]
pub struct Logged {
    /// Every slot envelope written: `(scrambled_id, envelope)`.
    pub slot_envelopes: Vec<([u8; 64], Vec<u8>)>,
    /// Every re-wrapped envelope: `(scrambled_id, bucket_version, envelope)`.
    pub rewrapped: Vec<([u8; 64], u64, Vec<u8>)>,
    /// Every sealed accumulator: `(version, n, ciphertext)`.
    pub accumulators: Vec<(u64, u64, Vec<u8>)>,
}

/// Everything the WAL on `data` holds about domain `d` (no checkpoint must have truncated it).
pub fn logged(data: &SimVfs, d: &Domain) -> Logged {
    let v: Arc<dyn sever_vfs::Vfs> = Arc::new(data.fork());
    let first = sever_checkpoint::read_manifest(v.as_ref(), 1)
        .unwrap()
        .unwrap()
        .first_wal_seq;
    let (_, txns, _) = Wal::recover(Arc::clone(&v), WalConfig::new(1), first, 1).unwrap();
    let layout =
        sever_txn::layout_for::<NoExtension>(16, &AeadSealer::new(Arc::new(KeyRing::new())));
    let mut out = Logged::default();
    let ours = |cid: &CollectionId, g: &sever_types::GroupId| sever_seal::domain(cid, g) == *d;
    for r in txns.iter().flat_map(|t| &t.records) {
        if let Some(Value::Envelopes(dd, entries)) = parse_wal(r) {
            if dd == *d {
                for (sid, bv, env) in entries {
                    out.rewrapped.push((sid, bv, env.to_vec()));
                }
            }
            continue;
        }
        if r.ty.is_participant() || r.ty == RecordType::Begin || r.ty == RecordType::Commit {
            continue;
        }
        let Ok(core) = CoreRecord::parse(r.ty, &r.payload, &|_| Some(layout)) else {
            continue;
        };
        match core {
            CoreRecord::SlotPut {
                cid, group, slot, ..
            } if ours(&cid, &group) => {
                out.slot_envelopes
                    .push((*slot.scrambled_id.as_bytes(), slot.envelope.clone()));
            }
            CoreRecord::GroupHeader { cid, header }
            | CoreRecord::GroupCreate { cid, header, .. }
                if ours(&cid, &header.group_id) && !header.sealed_accumulator.is_empty() =>
            {
                out.accumulators.push((
                    header.seal_version,
                    header.n,
                    header.sealed_accumulator.clone(),
                ));
            }
            _ => {}
        }
    }
    out
}

/// The keys the database holds for `d` now: its group key and its 64 bucket keys.
pub fn current_keys(ring: &KeyRing, d: &Domain) -> (u64, sever_keys::Key, Vec<BucketKey>) {
    let version = ring.active_versions()[d];
    let gk = ring.group_key(d, version).unwrap();
    let (_, blk) = ring.committed_block(d).unwrap();
    let bks = block::decode_block(&gk, d, version, &blk).unwrap();
    (version, gk, bks)
}

/// INV-12 for one domain: the accumulator versions and the record envelopes in the WAL that the
/// domain's current keys open. Returns `(accumulator versions opened, records whose envelope
/// opened, by scrambled ID)`.
pub fn openable(ring: &KeyRing, d: &Domain, log: &Logged) -> (Vec<u64>, BTreeMap<[u8; 64], usize>) {
    let (_, gk, bks) = current_keys(ring, d);
    let mut acc = Vec::new();
    for (v, n, ct) in &log.accumulators {
        if aead::open(&gk, &ad::accumulator(d, *v, *n), ct).is_ok() {
            acc.push(*v);
        }
    }
    let mut recs: BTreeMap<[u8; 64], usize> = BTreeMap::new();
    let mut try_env = |sid: &[u8; 64], env: &[u8]| {
        let bk = &bks[usize::from(sever_keys::bucket_of(sid))];
        if block::unwrap_record_key(bk, d, sid, env).is_ok() {
            *recs.entry(*sid).or_default() += 1;
        }
    };
    for (sid, env) in &log.slot_envelopes {
        try_env(sid, env);
    }
    for (sid, _, env) in &log.rewrapped {
        try_env(sid, env);
    }
    (acc, recs)
}
