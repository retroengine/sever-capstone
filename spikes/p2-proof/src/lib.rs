//! THROWAWAY proof spike (Build §3.4) before Part 2 freezes. It proves that Part 2's extension
//! points can express what Parts 3 and 4 need, without editing a frozen file:
//!
//! - EP-6: `AeadSealer`, AES-256-GCM-SIV with the associated data of spec §13.2, passes the frozen
//!   `ep6_sealer_contract`, and its sizes give the slot and header sizes of §14.3, §14.4 and
//!   Appendix A (the expected numbers are copied from the spec, not computed from this code).
//! - EP-7: `LogSpike` appends one log leaf per transaction atomically (Part 3, §10, §12.6);
//!   `RotationSpike` rotates a key with phase A (new key durable before the commit) and phase C
//!   (old key erased after it) (Part 4, §13.3, §13.4). Both pass the frozen
//!   `ep7_participant_contract`; a rotation without phase A fails it.
//!
//! Simplifications, acceptable for a spike: two key levels (group key wraps the record key; the
//! bucket level of §13.1 is the same shape one level down) and keys held in memory.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use aes_gcm_siv::aead::{Aead, KeyInit, Payload};
use aes_gcm_siv::{Aes256GcmSiv, Nonce};
use rand_core::{OsRng, RngCore};
use sever_format::{RecordType, WalRecord};
use sever_index::NoExtension;
use sever_txn::contract::ProbedParticipant;
use sever_txn::{GroupOwner, RecordOwner, Sealer, TxnDraft, TxnParticipant};
use sever_types::{CollectionId, Error, GroupId};
use sever_vfs::{OpenMode, Vfs, VfsError, VfsFile, durable, read_all};
use sha2::{Digest, Sha256};
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
    fn unwrap_rk(&self, o: &RecordOwner<'_>, envelope: &[u8]) -> Result<Zeroizing<Vec<u8>>, Error> {
        let (v, gk) = self.current(o.collection, o.group);
        let rk = open(&gk, &Self::wrap_ad(o, v), envelope)?;
        if rk.len() != 32 {
            return Err(bad("record key length"));
        }
        Ok(rk)
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

// ----- EP-7 spikes -----

fn io(_: VfsError) -> Error {
    Error::DurabilityFailure
}

/// Opens `path`, creating it durably (file and directory entry synced) if it does not exist.
fn open_or_create(vfs: &dyn Vfs, path: &str) -> Result<Box<dyn VfsFile>, Error> {
    match vfs.open(path, OpenMode::Existing) {
        Ok(f) => Ok(f),
        Err(VfsError::NotFound) => durable::create(vfs, path).map_err(io),
        Err(e) => Err(io(e)),
    }
}

fn read_file(vfs: &dyn Vfs, path: &str) -> Result<Vec<u8>, Error> {
    match vfs.open(path, OpenMode::Existing) {
        Ok(f) => read_all(f.as_ref()).map_err(io),
        Err(VfsError::NotFound) => Ok(Vec::new()),
        Err(e) => Err(io(e)),
    }
}

const LOG: &str = "spike-log";

fn leaf(i: u64) -> [u8; 32] {
    Sha256::new()
        .chain_update(b"SPIKE-LEAF")
        .chain_update(i.to_be_bytes())
        .finalize()
        .into()
}

/// Part 3's shape: one log leaf per transaction, in its own file, appended atomically with the
/// transaction. The leaf is made durable before the commit point (`sync_stores`); the WAL's
/// `LOG_LEAF` record says which leaves are committed; recovery cuts any leaf past that.
pub struct LogSpike {
    vfs: Arc<dyn Vfs>,
    committed: u64,
    pending: Option<[u8; 32]>,
}

impl LogSpike {
    pub fn new(vfs: Arc<dyn Vfs>) -> Self {
        Self {
            vfs,
            committed: 0,
            pending: None,
        }
    }
}

impl TxnParticipant<NoExtension> for LogSpike {
    fn id(&self) -> u16 {
        30
    }
    fn owned_types(&self) -> &[RecordType] {
        &[RecordType::LogLeaf]
    }
    fn prepare(&mut self, d: &mut TxnDraft<'_, NoExtension>) -> Result<(), Error> {
        let l = leaf(self.committed);
        self.pending = Some(l);
        let payload = [self.committed.to_be_bytes().as_slice(), &l].concat();
        d.participant_records.push((RecordType::LogLeaf, payload));
        Ok(())
    }
    fn sync_stores(&mut self) -> Result<(), Error> {
        let l = self.pending.ok_or(bad("no pending leaf"))?;
        let mut f = open_or_create(self.vfs.as_ref(), LOG)?;
        let end = self.committed * 32;
        f.write_at(end, &l).map_err(io)?;
        f.truncate(end + 32).map_err(io)?;
        durable::sync(f.as_mut()).map_err(io)
    }
    fn abort(&mut self) {
        self.pending = None;
    }
    fn after_commit(&mut self) -> Result<(), Error> {
        self.committed += 1;
        self.pending = None;
        Ok(())
    }
    fn replay(&mut self, r: &WalRecord) -> Result<(), Error> {
        let i: [u8; 8] = r
            .payload
            .get(..8)
            .and_then(|b| b.try_into().ok())
            .ok_or(bad("leaf record"))?;
        self.committed = self.committed.max(u64::from_be_bytes(i) + 1);
        Ok(())
    }
    fn recover(&mut self) -> Result<(), Error> {
        let have = read_file(self.vfs.as_ref(), LOG)?.len() as u64;
        let want = self.committed * 32;
        if have < want {
            return Err(bad("a committed leaf is missing"));
        }
        if have > want {
            let mut f = open_or_create(self.vfs.as_ref(), LOG)?;
            f.truncate(want).map_err(io)?;
            durable::sync(f.as_mut()).map_err(io)?;
        }
        Ok(())
    }
    fn check_invariants(&self) -> Result<(), Error> {
        let bytes = read_file(self.vfs.as_ref(), LOG)?;
        let want: Vec<u8> = (0..self.committed).flat_map(leaf).collect();
        if bytes == want {
            Ok(())
        } else {
            Err(bad("log file differs from the committed leaves"))
        }
    }
}

impl ProbedParticipant for LogSpike {
    fn digest(&self) -> Vec<u8> {
        let mut d = self.committed.to_be_bytes().to_vec();
        d.extend(read_file(self.vfs.as_ref(), LOG).unwrap_or_default());
        d
    }
}

const KEYS: &str = "spike-keys";
const SLOT: usize = 8 + 32;

/// Part 4's shape (§13.3, §13.4): a two-slot key file. Phase A writes the new key version into
/// the spare slot and syncs it before the commit point; phase C (after the commit) erases the old
/// slot. Recovery keeps only the committed version's slot and erases the other.
pub struct RotationSpike {
    vfs: Arc<dyn Vfs>,
    version: u64,
    pending: Option<u64>,
    /// A deliberately wrong variant skips phase A: the new key is written only after the commit.
    phase_a: bool,
}

impl RotationSpike {
    pub fn new(vfs: Arc<dyn Vfs>, phase_a: bool) -> Self {
        Self {
            vfs,
            version: 0,
            pending: None,
            phase_a,
        }
    }
    fn slots(&self) -> Result<[u64; 2], Error> {
        let b = read_file(self.vfs.as_ref(), KEYS)?;
        let v = |i: usize| {
            b.get(i * SLOT..i * SLOT + 8)
                .map_or(0, |s| u64::from_be_bytes(s.try_into().unwrap_or([0; 8])))
        };
        Ok([v(0), v(1)])
    }
    fn write_slot(&self, i: usize, version: u64, k: &[u8; 32]) -> Result<(), Error> {
        let mut f = open_or_create(self.vfs.as_ref(), KEYS)?;
        if f.len().map_err(io)? < (2 * SLOT) as u64 {
            f.write_at(0, &[0u8; 2 * SLOT]).map_err(io)?;
        }
        let bytes = [version.to_be_bytes().as_slice(), k].concat();
        f.write_at((i * SLOT) as u64, &bytes).map_err(io)?;
        durable::sync(f.as_mut()).map_err(io)
    }
    fn write_new(&self, v: u64) -> Result<(), Error> {
        let slots = self.slots()?;
        let spare = usize::from(slots[0] == self.version && self.version != 0);
        self.write_slot(spare, v, &key())
    }
    fn erase_all_but(&self, keep: u64) -> Result<(), Error> {
        for (i, v) in self.slots()?.into_iter().enumerate() {
            if v != 0 && v != keep {
                self.write_slot(i, 0, &[0; 32])?;
            }
        }
        Ok(())
    }
}

impl TxnParticipant<NoExtension> for RotationSpike {
    fn id(&self) -> u16 {
        31
    }
    fn prepare(&mut self, d: &mut TxnDraft<'_, NoExtension>) -> Result<(), Error> {
        let v = self.version + 1;
        self.pending = Some(v);
        let payload = [31u16.to_be_bytes().as_slice(), &v.to_be_bytes()].concat();
        d.participant_records.push((RecordType::Extension, payload));
        Ok(())
    }
    /// Phase A: the new key is durable before the commit point.
    fn phase_a(&mut self) -> Result<(), Error> {
        match (self.phase_a, self.pending) {
            (true, Some(v)) => self.write_new(v),
            _ => Ok(()),
        }
    }
    fn abort(&mut self) {
        self.pending = None;
    }
    /// Phase C: the old key is erased after the commit point.
    fn after_commit(&mut self) -> Result<(), Error> {
        let v = self.pending.take().ok_or(bad("no pending rotation"))?;
        if !self.phase_a {
            self.write_new(v)?;
        }
        self.version = v;
        self.erase_all_but(v)
    }
    fn replay(&mut self, r: &WalRecord) -> Result<(), Error> {
        let v: [u8; 8] = r
            .payload
            .get(2..10)
            .and_then(|b| b.try_into().ok())
            .ok_or(bad("rotation record"))?;
        self.version = self.version.max(u64::from_be_bytes(v));
        Ok(())
    }
    fn recover(&mut self) -> Result<(), Error> {
        if self.version != 0 && !self.slots()?.contains(&self.version) {
            return Err(bad("the committed key version is missing"));
        }
        self.erase_all_but(self.version)
    }
    fn check_invariants(&self) -> Result<(), Error> {
        let live: Vec<u64> = self.slots()?.into_iter().filter(|v| *v != 0).collect();
        let want = if self.version == 0 {
            vec![]
        } else {
            vec![self.version]
        };
        if live == want {
            Ok(())
        } else {
            Err(bad("key file holds a key other than the committed one"))
        }
    }
}

impl ProbedParticipant for RotationSpike {
    fn digest(&self) -> Vec<u8> {
        // Key bytes are random; the state is the committed version and the live versions.
        let mut live: Vec<u64> = self
            .slots()
            .unwrap_or_default()
            .into_iter()
            .filter(|v| *v != 0)
            .collect();
        live.sort_unstable();
        let mut d = self.version.to_be_bytes().to_vec();
        d.extend(live.iter().flat_map(|v| v.to_be_bytes()));
        d
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sever_format::Layout;
    use sever_txn::contract::{ContractViolation, ep6_sealer_contract, ep7_participant_contract};

    #[test]
    fn spike_ep6_aead_sealer_passes_contract() {
        assert_eq!(ep6_sealer_contract(&AeadSealer::default()), Ok(()));
    }

    /// §14.3, §14.4 and Appendix A, with the released system's extension sizes (DB-46: `C_S` 32,
    /// `r_agg` 32, record secret 41) and the spike sealer's sizes. Expected values are the spec's.
    #[test]
    fn spike_appendix_a_sizes_with_aead_sealer() {
        let s = AeadSealer::default();
        let full = Layout {
            d: 384,
            ext_public: 32,
            ext_group_secret: 32,
            ext_record_secret: 41,
            envelope: s.envelope_len(),
            seal_overhead: s.seal_overhead(),
        };
        assert_eq!(full.payload_len(), 1_835); // Appendix A, slot payload plaintext
        assert_eq!(full.slot_len(), 1_992); // §14.4 total
        assert_eq!(full.accumulator_len(), 3_104); // Appendix A, accumulator plaintext
        assert_eq!(full.accumulator_len() + s.seal_overhead(), 3_132); // and ciphertext
        assert_eq!(full.header_len(false), 6_285); // §14.3 total
        // Part 2's no-extension payload under the AEAD sealer: 64 + 60 + (1,794 + 28) = 1,946,
        // 8-aligned to 1,952 (§14.4's formula, by hand).
        let p2 = Layout {
            ext_public: 0,
            ext_group_secret: 0,
            ext_record_secret: 0,
            ..full
        };
        assert_eq!(p2.payload_len(), 1_794);
        assert_eq!(p2.slot_len(), 1_952);
    }

    #[test]
    fn spike_ep7_log_participant_passes_contract() {
        let make = |v: Arc<dyn Vfs>| -> Box<dyn ProbedParticipant> { Box::new(LogSpike::new(v)) };
        assert_eq!(ep7_participant_contract(&make), Ok(()));
    }

    #[test]
    fn spike_ep7_key_rotation_participant_passes_contract() {
        let make = |v: Arc<dyn Vfs>| -> Box<dyn ProbedParticipant> {
            Box::new(RotationSpike::new(v, true))
        };
        assert_eq!(ep7_participant_contract(&make), Ok(()));
    }

    /// Must fail: without phase A, a crash right after the commit point loses the committed key.
    #[test]
    fn spike_ep7_rotation_without_phase_a_fails_contract() {
        let make = |v: Arc<dyn Vfs>| -> Box<dyn ProbedParticipant> {
            Box::new(RotationSpike::new(v, false))
        };
        assert_eq!(
            ep7_participant_contract(&make),
            Err(ContractViolation::Failed("recover"))
        );
    }
}
