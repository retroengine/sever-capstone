//! EP-6 [`Sealer`] for sealer 1, AES-256-GCM-SIV (spec §13.2, §14 sealer marker): every stored
//! secret becomes ciphertext, with the layouts of §14.3–14.4 (an overhead of 28 bytes per sealed
//! value and a 60-byte record-key envelope).

use std::sync::Arc;

use sever_keys::{Domain, Key};
use sever_txn::sealer::{GroupOwner, RecordOwner, Sealer};
use sever_types::{CollectionId, Error, GroupId};
use zeroize::Zeroizing;

use crate::ad;
use crate::aead;
use crate::block::ENVELOPE_BYTES;
use crate::ring::KeyRing;

/// The key domain of a group (§13.1): its collection and its group ID zero-padded to 32 bytes.
pub fn domain(collection: &CollectionId, group: &GroupId) -> Domain {
    Domain {
        collection_id: *collection.as_bytes(),
        group_id: group.to_padded_bytes().0,
    }
}

/// The AES-256-GCM-SIV sealer, reading and staging keys in a [`KeyRing`] it shares with the
/// key-rotation participant.
#[derive(Clone, Debug)]
pub struct AeadSealer {
    ring: Arc<KeyRing>,
}

impl AeadSealer {
    /// A sealer over `ring`.
    pub fn new(ring: Arc<KeyRing>) -> Self {
        Self { ring }
    }

    /// The ring.
    pub fn ring(&self) -> &Arc<KeyRing> {
        &self.ring
    }

    fn record_key(&self, owner: &RecordOwner<'_>, envelope: &[u8]) -> Result<Key, Error> {
        self.ring.record_key(
            &domain(owner.collection, owner.group),
            owner.scrambled_id.as_bytes(),
            envelope,
        )
    }
}

impl Sealer for AeadSealer {
    fn sealer_id(&self) -> u16 {
        sever_format::SEALER_AES_GCM_SIV
    }

    fn seal_overhead(&self) -> usize {
        aead::OVERHEAD
    }

    fn envelope_len(&self) -> usize {
        ENVELOPE_BYTES
    }

    fn seal_record(
        &self,
        owner: &RecordOwner<'_>,
        payload: &[u8],
    ) -> Result<(Vec<u8>, Vec<u8>), Error> {
        let sid = owner.scrambled_id.as_bytes();
        let rk = Key::generate();
        let env = self
            .ring
            .join(&domain(owner.collection, owner.group), sid, &rk)?;
        let sealed = aead::seal(
            &rk,
            &ad::slot_payload(owner.collection.as_bytes(), sid),
            payload,
        )?;
        // SB-28: the slot payload goes to disk in the clear (padded to the sealed length).
        #[cfg(feature = "sabotage-SB-28")]
        let sealed = {
            let mut v = payload.to_vec();
            v.resize(sealed.len(), 0);
            v
        };
        Ok((env.to_vec(), sealed))
    }

    fn open_record(
        &self,
        owner: &RecordOwner<'_>,
        envelope: &[u8],
        sealed: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>, Error> {
        let rk = self.record_key(owner, envelope)?;
        #[cfg(feature = "sabotage-SB-28")]
        let _ = &rk;
        #[cfg(feature = "sabotage-SB-28")]
        return Ok(Zeroizing::new(
            sealed
                .get(..sealed.len().saturating_sub(self.seal_overhead()))
                .unwrap_or_default()
                .to_vec(),
        ));
        #[allow(unreachable_code)]
        aead::open(
            &rk,
            &ad::slot_payload(owner.collection.as_bytes(), owner.scrambled_id.as_bytes()),
            sealed,
        )
    }

    fn rewrap_record(
        &self,
        from: &RecordOwner<'_>,
        to: &RecordOwner<'_>,
        envelope: &[u8],
    ) -> Result<Vec<u8>, Error> {
        let env = self.ring.move_record(
            &domain(from.collection, from.group),
            &domain(to.collection, to.group),
            from.scrambled_id.as_bytes(),
            envelope,
        )?;
        Ok(env.to_vec())
    }

    fn seal_passage(
        &self,
        owner: &RecordOwner<'_>,
        envelope: &[u8],
        text: &[u8],
    ) -> Result<Vec<u8>, Error> {
        let rk = self.record_key(owner, envelope)?;
        aead::seal(
            &rk,
            &ad::passage(owner.collection.as_bytes(), owner.scrambled_id.as_bytes()),
            text,
        )
    }

    fn open_passage(
        &self,
        owner: &RecordOwner<'_>,
        envelope: &[u8],
        sealed: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>, Error> {
        let rk = self.record_key(owner, envelope)?;
        aead::open(
            &rk,
            &ad::passage(owner.collection.as_bytes(), owner.scrambled_id.as_bytes()),
            sealed,
        )
    }

    fn next_version(&self, owner: &GroupOwner<'_>, prev: Option<u64>, departure: bool) -> u64 {
        self.ring
            .next_version(&domain(owner.collection, owner.group), prev, departure)
    }

    fn seal_accumulator(
        &self,
        owner: &GroupOwner<'_>,
        version: u64,
        plaintext: &[u8],
    ) -> Result<Vec<u8>, Error> {
        let d = domain(owner.collection, owner.group);
        let gk = self.ring.group_key(&d, version)?;
        aead::seal(&gk, &ad::accumulator(&d, version, owner.n), plaintext)
    }

    fn open_accumulator(
        &self,
        owner: &GroupOwner<'_>,
        version: u64,
        sealed: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>, Error> {
        let d = domain(owner.collection, owner.group);
        let gk = self.ring.group_key(&d, version)?;
        aead::open(&gk, &ad::accumulator(&d, version, owner.n), sealed)
    }
}
