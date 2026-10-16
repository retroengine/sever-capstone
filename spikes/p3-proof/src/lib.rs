//! THROWAWAY proof spike (Build 3-4 §1.11) before Part 3 freezes: Part 4 can be added without
//! touching Part 3.
//!
//! - `AeadSealer` (EP-6; the Part 2 spike's, AES-256-GCM-SIV with the associated data of §13.2)
//!   seals the commitment extension's secret state: each record's `r_t` (in the slot payload) and
//!   each group's `r_agg` (in the sealed accumulator), with the Part 3 build unchanged.
//! - `StubRotation` (EP-7), registered after `LogParticipant`, sees every departure of every
//!   transaction (§13.3: the domains Part 4 rotates) and runs phases A and C around the commit.
//!
//! Its only output is the `gates p3-spikes` ledger entry; then it is deleted.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use aes_gcm_siv::aead::{Aead, KeyInit, Payload};
use aes_gcm_siv::{Aes256GcmSiv, Nonce};
use rand_core::{OsRng, RngCore};
use sever_commit::CommitmentExtension;
use sever_txn::{GroupOwner, RecordOwner, Sealer, TxnDraft, TxnParticipant};
use sever_types::{CollectionId, Error, GroupId};
use zeroize::Zeroizing;

fn bad(what: &'static str) -> Error {
    Error::IntegrityViolation { invariant: what }
}

fn key() -> [u8; 32] {
    let mut k = [0u8; 32];
    OsRng.fill_bytes(&mut k); // keys and nonces from the OS, never a seed (CLAUDE.md §6.2)
    k
}

/// §13.2: `nonce(12) ‖ AES-GCM-SIV(pt) ‖ tag(16)`.
fn seal(k: &[u8; 32], ad: &[u8], pt: &[u8]) -> Result<Vec<u8>, Error> {
    let mut nonce = [0u8; 12];
    OsRng.fill_bytes(&mut nonce);
    let ct = Aes256GcmSiv::new(k.into())
        .encrypt(Nonce::from_slice(&nonce), Payload { msg: pt, aad: ad })
        .map_err(|_| bad("seal"))?;
    Ok([nonce.as_slice(), &ct].concat())
}

fn open(k: &[u8; 32], ad: &[u8], sealed: &[u8]) -> Result<Zeroizing<Vec<u8>>, Error> {
    if sealed.len() < 28 {
        return Err(bad("short ciphertext"));
    }
    let (nonce, ct) = sealed.split_at(12);
    Aes256GcmSiv::new(k.into())
        .decrypt(Nonce::from_slice(nonce), Payload { msg: ct, aad: ad })
        .map(Zeroizing::new)
        .map_err(|_| bad("open"))
}

fn gid32(g: &GroupId) -> [u8; 32] {
    g.to_padded_bytes().0
}

type Domain = ([u8; 16], [u8; 32]);

/// The spike sealer: per domain (collection, group) a current version and its keys.
#[derive(Default)]
pub struct AeadSealer {
    keys: Mutex<HashMap<Domain, (u64, HashMap<u64, [u8; 32]>)>>,
}

impl AeadSealer {
    fn domain(c: &CollectionId, g: &GroupId) -> Domain {
        (*c.as_bytes(), gid32(g))
    }
    /// The domain's current `(version, key)`, created at version 1 on first use.
    fn current(&self, c: &CollectionId, g: &GroupId) -> (u64, [u8; 32]) {
        let mut m = self.keys.lock().unwrap();
        let e = m
            .entry(Self::domain(c, g))
            .or_insert_with(|| (1, HashMap::from([(1, key())])));
        (e.0, e.1[&e.0])
    }
    fn at(&self, c: &CollectionId, g: &GroupId, v: u64) -> Result<[u8; 32], Error> {
        let m = self.keys.lock().unwrap();
        m.get(&Self::domain(c, g))
            .and_then(|e| e.1.get(&v).copied())
            .ok_or(bad("no key"))
    }
    /// §13.2 wrapped record key AD: `collection_id ‖ group_id(32) ‖ scrambled_id ‖ u64be version`.
    fn wrap_ad(o: &RecordOwner<'_>, v: u64) -> Vec<u8> {
        [
            o.collection.as_bytes().as_slice(),
            &gid32(o.group),
            o.scrambled_id.as_bytes(),
            &v.to_be_bytes(),
        ]
        .concat()
    }
    /// §13.2 slot payload (`0x01`) and passage (`0x02`) AD: `collection_id ‖ scrambled_id ‖ tag`.
    fn data_ad(o: &RecordOwner<'_>, tag: u8) -> Vec<u8> {
        [
            o.collection.as_bytes().as_slice(),
            o.scrambled_id.as_bytes(),
            &[tag],
        ]
        .concat()
    }
    /// §13.2 accumulator AD: `collection_id ‖ group_id ‖ u64be version ‖ u64be n`.
    fn acc_ad(o: &GroupOwner<'_>, v: u64) -> Vec<u8> {
        [
            o.collection.as_bytes().as_slice(),
            &gid32(o.group),
            &v.to_be_bytes(),
            &o.n.to_be_bytes(),
        ]
        .concat()
    }
    /// The record key, unwrapped with the domain's newest key that opens it: the stub rotation
    /// does not re-wrap the members that stay (Part 4's `KeyRotationParticipant` does), so the
    /// spike keeps every version.
    fn unwrap_rk(&self, o: &RecordOwner<'_>, envelope: &[u8]) -> Result<Zeroizing<Vec<u8>>, Error> {
        let versions: Vec<(u64, [u8; 32])> = {
            self.current(o.collection, o.group);
            let m = self.keys.lock().unwrap();
            let mut v: Vec<_> = m
                .get(&Self::domain(o.collection, o.group))
                .map(|e| e.1.iter().map(|(k, x)| (*k, *x)).collect())
                .unwrap_or_default();
            v.sort_by(|a, b| b.0.cmp(&a.0));
            v
        };
        for (v, gk) in versions {
            if let Ok(rk) = open(&gk, &Self::wrap_ad(o, v), envelope) {
                if rk.len() == 32 {
                    return Ok(rk);
                }
            }
        }
        Err(bad("record key"))
    }
    fn rk(rk: &[u8]) -> [u8; 32] {
        let mut k = [0u8; 32];
        k.copy_from_slice(rk);
        k
    }
}

impl Sealer for AeadSealer {
    fn sealer_id(&self) -> u16 {
        1
    }
    fn seal_overhead(&self) -> usize {
        12 + 16 // §13.2: 28 bytes per ciphertext
    }
    fn envelope_len(&self) -> usize {
        12 + 32 + 16 // §14.4: wrapped record key, 60 bytes
    }
    fn seal_record(
        &self,
        o: &RecordOwner<'_>,
        payload: &[u8],
    ) -> Result<(Vec<u8>, Vec<u8>), Error> {
        let rk = Zeroizing::new(key());
        let (v, gk) = self.current(o.collection, o.group);
        let envelope = seal(&gk, &Self::wrap_ad(o, v), rk.as_slice())?;
        Ok((envelope, seal(&rk, &Self::data_ad(o, 0x01), payload)?))
    }
    fn open_record(
        &self,
        o: &RecordOwner<'_>,
        envelope: &[u8],
        sealed: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>, Error> {
        let rk = self.unwrap_rk(o, envelope)?;
        open(&Self::rk(&rk), &Self::data_ad(o, 0x01), sealed)
    }
    fn rewrap_record(
        &self,
        from: &RecordOwner<'_>,
        to: &RecordOwner<'_>,
        envelope: &[u8],
    ) -> Result<Vec<u8>, Error> {
        let rk = self.unwrap_rk(from, envelope)?;
        let (v, gk) = self.current(to.collection, to.group);
        seal(&gk, &Self::wrap_ad(to, v), &rk)
    }
    fn seal_passage(
        &self,
        o: &RecordOwner<'_>,
        envelope: &[u8],
        text: &[u8],
    ) -> Result<Vec<u8>, Error> {
        let rk = self.unwrap_rk(o, envelope)?;
        seal(&Self::rk(&rk), &Self::data_ad(o, 0x02), text)
    }
    fn open_passage(
        &self,
        o: &RecordOwner<'_>,
        envelope: &[u8],
        sealed: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>, Error> {
        let rk = self.unwrap_rk(o, envelope)?;
        open(&Self::rk(&rk), &Self::data_ad(o, 0x02), sealed)
    }
    /// §13.3: a departure rotates the domain (version + 1, fresh key); a join keeps the version.
    fn next_version(&self, o: &GroupOwner<'_>, prev: Option<u64>, departure: bool) -> u64 {
        let (cur, _) = self.current(o.collection, o.group);
        match prev {
            Some(v) if departure => {
                let mut m = self.keys.lock().unwrap();
                let e = m.entry(Self::domain(o.collection, o.group)).or_default();
                let next = v.max(cur) + 1;
                e.0 = next;
                e.1.insert(next, key());
                next
            }
            Some(v) => v,
            None => cur,
        }
    }
    fn seal_accumulator(
        &self,
        o: &GroupOwner<'_>,
        version: u64,
        plaintext: &[u8],
    ) -> Result<Vec<u8>, Error> {
        let k = self.at(o.collection, o.group, version)?;
        seal(&k, &Self::acc_ad(o, version), plaintext)
    }
    fn open_accumulator(
        &self,
        o: &GroupOwner<'_>,
        version: u64,
        sealed: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>, Error> {
        let k = self.at(o.collection, o.group, version)?;
        open(&k, &Self::acc_ad(o, version), sealed)
    }
}

// ----- EP-7: the key-rotation participant's place, as a stub -----

/// What the stub saw, for the test.
#[derive(Default, Debug)]
pub struct Seen {
    /// Departures `(group, scrambled_id)` per transaction.
    pub departures: Vec<Vec<(GroupId, [u8; 64])>>,
    /// Phase A and phase C calls.
    pub phase_a: u64,
    /// See above.
    pub phase_c: u64,
}

/// Part 4's `KeyRotationParticipant`, reduced to recording what it would rotate.
pub struct StubRotation(pub Arc<Mutex<Seen>>);

impl TxnParticipant<CommitmentExtension> for StubRotation {
    fn id(&self) -> u16 {
        4
    }
    fn prepare(&mut self, draft: &mut TxnDraft<'_, CommitmentExtension>) -> Result<(), Error> {
        if let Some(cs) = draft.changeset {
            let d: Vec<(GroupId, [u8; 64])> =
                cs.departures.iter().map(|(g, s)| (*g, *s.as_bytes())).collect();
            if !d.is_empty() {
                self.0.lock().unwrap().departures.push(d);
            }
        }
        Ok(())
    }
    fn phase_a(&mut self) -> Result<(), Error> {
        self.0.lock().unwrap().phase_a += 1;
        Ok(())
    }
    fn after_commit(&mut self) -> Result<(), Error> {
        self.0.lock().unwrap().phase_c += 1;
        Ok(())
    }
}

/// The sealer behind an `Arc`, so a reopened engine keeps the in-memory keys.
pub struct Shared(pub Arc<AeadSealer>);

impl Sealer for Shared {
    fn sealer_id(&self) -> u16 {
        self.0.sealer_id()
    }
    fn seal_overhead(&self) -> usize {
        self.0.seal_overhead()
    }
    fn envelope_len(&self) -> usize {
        self.0.envelope_len()
    }
    fn seal_record(&self, o: &RecordOwner<'_>, p: &[u8]) -> Result<(Vec<u8>, Vec<u8>), Error> {
        self.0.seal_record(o, p)
    }
    fn open_record(&self, o: &RecordOwner<'_>, e: &[u8], s: &[u8]) -> Result<Zeroizing<Vec<u8>>, Error> {
        self.0.open_record(o, e, s)
    }
    fn rewrap_record(&self, f: &RecordOwner<'_>, t: &RecordOwner<'_>, e: &[u8]) -> Result<Vec<u8>, Error> {
        self.0.rewrap_record(f, t, e)
    }
    fn seal_passage(&self, o: &RecordOwner<'_>, e: &[u8], t: &[u8]) -> Result<Vec<u8>, Error> {
        self.0.seal_passage(o, e, t)
    }
    fn open_passage(&self, o: &RecordOwner<'_>, e: &[u8], s: &[u8]) -> Result<Zeroizing<Vec<u8>>, Error> {
        self.0.open_passage(o, e, s)
    }
    fn next_version(&self, o: &GroupOwner<'_>, prev: Option<u64>, departure: bool) -> u64 {
        self.0.next_version(o, prev, departure)
    }
    fn seal_accumulator(&self, o: &GroupOwner<'_>, v: u64, p: &[u8]) -> Result<Vec<u8>, Error> {
        self.0.seal_accumulator(o, v, p)
    }
    fn open_accumulator(&self, o: &GroupOwner<'_>, v: u64, s: &[u8]) -> Result<Zeroizing<Vec<u8>>, Error> {
        self.0.open_accumulator(o, v, s)
    }
}
