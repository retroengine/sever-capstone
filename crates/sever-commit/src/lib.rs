//! `sever-commit`: the commitment extension, EP-1 `GroupExtension` and Part 2's `StoredExtension`
//! (Build 3-4 §1.5; spec §5.3, §9.3–9.4, §14.4, §15.1 step 2, §15.3 step 2).
//!
//! - Group public state `C_S`; group secret state `r_agg`; record secret
//!   `u64be insert_leaf_index ‖ u8 has_rt ‖ r_t` (41 bytes, DB-46).
//! - `admit` recomputes `C_t` from `x̃` and the supplied `r_t` (`CommitmentMismatch` otherwise) and
//!   verifies the user's insert signature with `verify_strict` (`BadUserSignature`). A malformed
//!   credential (a non-canonical `C_t` or `r_t`, or the identity as `C_t`, §9.9) is a
//!   `CommitmentMismatch` too (DB-78).
//! - `add`/`remove` move `S`, `n` (in the index), `r_agg` and `C_S` together (§5.3); `remove` is
//!   the exact inverse of `add`.
//! - `check_removal` re-derives `C_t` from the stored `x̃` and `r_t` and compares it with the
//!   `C_t` of the record's insert leaf, read through a [`LeafLog`] handle; any difference, or
//!   `has_rt ≠ 1`, is an `IntegrityViolation` (§15.3 step 2, §14.4).
//! - Both hand the log what the `ChangeSet` does not carry ([`LeafLog::stage_insert`],
//!   [`LeafLog::stage_removal`]): the admitted insert's user key and signature for its leaf, and a
//!   removed record's `x̃` and `r_t` for its certificate.
//! - The blob's extension region is `C_S ‖ r_agg` with magic `SEVERG` (§5.5, DB-47); `check_group`
//!   is INV-3.

#![forbid(unsafe_code)]

use std::sync::Arc;

use sever_crypto::{
    Generators, RistrettoPoint, Scalar, commit_group, commit_record, decode_point,
    decode_record_commitment, decode_scalar, encode_point, encode_scalar, insert_message,
    verify_signature,
};
use sever_index::GroupExtension;
use sever_quant::QVec;
use sever_txn::StoredExtension;
use sever_types::Error;
use zeroize::Zeroize;

/// What the commitment extension needs from the transparency log (implemented by `sever-log`).
pub trait LeafLog: Send + Sync {
    /// The index the next appended leaf will get (the current tree size). One writer at a time
    /// (§12.5), so an insert admitted now gets exactly this index for its insert leaf.
    fn next_leaf_index(&self) -> u64;
    /// The `C_t` field of the insert leaf at `index` (§10.2), or `None` if there is no insert leaf
    /// there. A stored leaf that cannot be read or verified is that error (§17, G-41).
    fn insert_leaf_c_t(&self, index: u64) -> Result<Option<[u8; 32]>, Error>;
    /// `admit` accepted an insert: the fields of its insert leaf that the `ChangeSet` does not
    /// carry (§10.2, §15.1 step 6). The log participant builds the leaf from them.
    fn stage_insert(&self, _insert: StagedInsert) {}
    /// `check_removal` passed for a record about to be deleted: its leaf index, `x̃` and `r_t`, so
    /// the log participant can build each deletion's certificate on the state the previous one
    /// left (§15.3 step 4). Called once per deleted record, in request order.
    fn stage_removal(&self, _removal: StagedRemoval) {}
}

/// An admitted insert's public leaf fields (§10.2).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StagedInsert {
    /// The leaf index the insert's leaf will take.
    pub insert_leaf_index: u64,
    /// The collection.
    pub collection_id: [u8; 16],
    /// The record commitment (recomputed and checked by `admit`).
    pub c_t: [u8; 32],
    /// The account's public key.
    pub user_public_key: [u8; 32],
    /// The verified insert signature.
    pub signature: [u8; 64],
}

/// A record about to be removed: what its certificate's proof needs (§9.5); zeroed when dropped.
#[derive(Clone, PartialEq, Eq)]
pub struct StagedRemoval {
    /// The leaf index of its insert leaf.
    pub insert_leaf_index: u64,
    /// Its quantised vector `x̃`.
    pub x: Vec<i32>,
    /// Its blinding scalar.
    pub r_t: Scalar,
}

impl Drop for StagedRemoval {
    fn drop(&mut self) {
        self.x.zeroize();
        self.r_t.zeroize();
    }
}

impl core::fmt::Debug for StagedRemoval {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "StagedRemoval(leaf {})", self.insert_leaf_index) // §17: no x̃, no r_t
    }
}

/// `C_S`, the group's public state. The default is the identity (an empty group, §5.4).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct GroupCommitment(pub RistrettoPoint);

impl Default for GroupCommitment {
    fn default() -> Self {
        Self(commit_identity())
    }
}

fn commit_identity() -> RistrettoPoint {
    use sever_crypto::RistrettoPoint as P;
    P::default()
}

/// `r_agg`, the group's secret blinding total (`Σ r_t mod ℓ`, §2.1); zeroed when dropped.
#[derive(Clone, Default, PartialEq, Eq)]
pub struct BlindingTotal(pub Scalar);

impl Drop for BlindingTotal {
    fn drop(&mut self) {
        self.0.zeroize();
    }
}

/// The record secret of the slot payload (§14.4, DB-46); zeroed when dropped.
#[derive(Clone, PartialEq, Eq)]
pub struct RecordBlind {
    /// The leaf index of the record's insert leaf (§10.2).
    pub insert_leaf_index: u64,
    /// Always 1 (§14.4): the engine stores `r_t` for every record.
    pub has_rt: u8,
    /// The record's blinding scalar (§9.4).
    pub r_t: Scalar,
}

impl Drop for RecordBlind {
    fn drop(&mut self) {
        self.r_t.zeroize();
    }
}

impl core::fmt::Debug for RecordBlind {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "RecordBlind(leaf {}, <r_t>)", self.insert_leaf_index) // §17: never print r_t
    }
}

/// What an insert presents (§3.3, §15.1 step 2): built by the SDK's `prepare_insert` (§16.2).
pub struct InsertCredential {
    /// The collection (bound into the signature, §9.8).
    pub collection_id: [u8; 16],
    /// The supplied record commitment.
    pub c_t: [u8; 32],
    /// The supplied blinding scalar (32 bytes, little-endian mod ℓ); zeroed when dropped.
    pub r_t: [u8; 32],
    /// The account's Ed25519 public key (published in the insert leaf).
    pub user_public_key: [u8; 32],
    /// The user signature over `DST_INSERT ‖ collection_id ‖ C_t`.
    pub signature: [u8; 64],
}

impl Drop for InsertCredential {
    fn drop(&mut self) {
        self.r_t.zeroize();
    }
}

/// EP-1 commitment extension. Cheap to clone (shared generators and log handle).
#[derive(Clone)]
pub struct CommitmentExtension {
    gens: Arc<Generators>,
    log: Arc<dyn LeafLog>,
}

impl CommitmentExtension {
    /// An extension over `gens` (already self-checked, §9.2) reading leaves through `log`.
    pub fn new(gens: Arc<Generators>, log: Arc<dyn LeafLog>) -> Self {
        Self { gens, log }
    }

    /// The generators.
    pub fn generators(&self) -> &Generators {
        &self.gens
    }

    /// `C_t = r_t·H + Σ scalar(x̃_i)·G_i` (§9.3).
    pub fn record_commitment(&self, x: &QVec, r_t: &Scalar) -> Result<RistrettoPoint, Error> {
        commit_record(&self.gens, x.as_slice(), r_t).map_err(|_| Error::WrongDimension)
    }
}

impl core::fmt::Debug for CommitmentExtension {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "CommitmentExtension(d = {})", self.gens.d())
    }
}

const MISMATCH: Error = Error::CommitmentMismatch;

fn integrity(rule: &'static str) -> Error {
    Error::IntegrityViolation { invariant: rule }
}

impl GroupExtension for CommitmentExtension {
    type GroupPublic = GroupCommitment;
    type GroupSecret = BlindingTotal;
    type RecordSecret = RecordBlind;
    type Credential = InsertCredential;
    const BLOB_MAGIC: [u8; 6] = *b"SEVERG";

    fn admit(&self, x: &QVec, credential: InsertCredential) -> Result<RecordBlind, Error> {
        // §15.1 step 2 and §9.3: recompute C_t from x̃ and r_t; it must equal the supplied C_t.
        let supplied = decode_record_commitment(&credential.c_t).map_err(|_| MISMATCH)?; // §9.9, DB-78
        let r_t = decode_scalar(&credential.r_t).map_err(|_| MISMATCH)?;
        if self.record_commitment(x, &r_t)? != supplied {
            return Err(MISMATCH);
        }
        // §15.1 step 2, §9.8: the user signature over DST_INSERT ‖ collection_id ‖ C_t.
        let msg = insert_message(&credential.collection_id, &credential.c_t);
        verify_signature(&credential.user_public_key, &msg, &credential.signature)
            .map_err(|_| Error::BadUserSignature)?;
        let insert_leaf_index = self.log.next_leaf_index();
        self.log.stage_insert(StagedInsert {
            insert_leaf_index,
            collection_id: credential.collection_id,
            c_t: credential.c_t,
            user_public_key: credential.user_public_key,
            signature: credential.signature,
        });
        Ok(RecordBlind {
            insert_leaf_index,
            has_rt: 1,
            r_t,
        })
    }

    fn add(
        &self,
        public: &mut GroupCommitment,
        secret: &mut BlindingTotal,
        x: &QVec,
        record: &RecordBlind,
    ) {
        // §5.3: r_agg ← r_agg + r_t mod ℓ; C_S ← C_S + C_t. The dimension was checked at admission.
        if let Ok(c_t) = self.record_commitment(x, &record.r_t) {
            public.0 += c_t;
            secret.0 += record.r_t;
        }
    }

    fn remove(
        &self,
        public: &mut GroupCommitment,
        secret: &mut BlindingTotal,
        x: &QVec,
        record: &RecordBlind,
    ) {
        // §5.3: the exact inverse of `add`.
        if let Ok(c_t) = self.record_commitment(x, &record.r_t) {
            public.0 -= c_t;
            secret.0 -= record.r_t;
        }
    }

    fn check_removal(&self, x: &QVec, record: &RecordBlind) -> Result<(), Error> {
        // §14.4: has_rt must be 1. §15.3 step 2: the stored x̃ and r_t reproduce the logged C_t.
        if record.has_rt != 1 {
            return Err(integrity("§14.4 has_rt"));
        }
        let logged = self
            .log
            .insert_leaf_c_t(record.insert_leaf_index)?
            .ok_or(integrity("§15.3 insert leaf"))?;
        let c_t = self.record_commitment(x, &record.r_t)?;
        if encode_point(&c_t) != logged {
            return Err(integrity("§15.3 C_t"));
        }
        self.log.stage_removal(StagedRemoval {
            insert_leaf_index: record.insert_leaf_index,
            x: x.as_slice().to_vec(),
            r_t: record.r_t,
        });
        Ok(())
    }

    fn blob_region(&self, public: &GroupCommitment, secret: &BlindingTotal, out: &mut Vec<u8>) {
        // §5.5 full form (DB-47): C_S (32) ‖ r_agg (32).
        out.extend_from_slice(&encode_point(&public.0));
        out.extend_from_slice(&encode_scalar(&secret.0));
    }

    fn check_group(
        &self,
        s: &[i64],
        public: &GroupCommitment,
        secret: &BlindingTotal,
    ) -> Result<(), Error> {
        // INV-3: C_S = r_agg·H + Σ scalar(S_i)·G_i.
        #[cfg(feature = "memo-checks")]
        let key = memo::key(s, public, secret);
        #[cfg(feature = "memo-checks")]
        if memo::seen(&key) {
            return Ok(());
        }
        let want = commit_group(&self.gens, s, &secret.0).map_err(|_| integrity("INV-3"))?;
        if want == public.0 {
            #[cfg(feature = "memo-checks")]
            memo::remember(key);
            Ok(())
        } else {
            Err(integrity("INV-3"))
        }
    }

    fn same_commitment(
        &self,
        live_x: &QVec,
        live: &RecordBlind,
        _new_x: &QVec,
        new: &InsertCredential,
    ) -> bool {
        // §17 DuplicateRecord { same_commitment }: the live record has the supplied C_t.
        self.record_commitment(live_x, &live.r_t)
            .is_ok_and(|c| encode_point(&c) == new.c_t)
    }
}

impl StoredExtension for CommitmentExtension {
    const PUBLIC_LEN: usize = 32;
    const GROUP_SECRET_LEN: usize = 32;
    const RECORD_SECRET_LEN: usize = 41;

    fn encode_public(p: &GroupCommitment) -> Vec<u8> {
        encode_point(&p.0).to_vec()
    }

    fn decode_public(b: &[u8]) -> Result<GroupCommitment, Error> {
        decode_point(b)
            .map(GroupCommitment)
            .map_err(|_| integrity("§9.9 C_S"))
    }

    fn encode_group_secret(s: &BlindingTotal) -> Vec<u8> {
        encode_scalar(&s.0).to_vec()
    }

    fn decode_group_secret(b: &[u8]) -> Result<BlindingTotal, Error> {
        decode_scalar(b)
            .map(BlindingTotal)
            .map_err(|_| integrity("§9.9 r_agg"))
    }

    fn encode_record_secret(r: &RecordBlind) -> Vec<u8> {
        // §14.4, DB-46: u64be insert_leaf_index ‖ u8 has_rt ‖ r_t (32).
        let mut out = Vec::with_capacity(41);
        out.extend_from_slice(&r.insert_leaf_index.to_be_bytes());
        out.push(r.has_rt);
        out.extend_from_slice(&encode_scalar(&r.r_t));
        out
    }

    fn decode_record_secret(b: &[u8]) -> Result<RecordBlind, Error> {
        let bad = || integrity("DB-46 record secret");
        let (idx, rest) = b.split_first_chunk::<8>().ok_or_else(bad)?;
        let (has_rt, r_t) = rest.split_first().ok_or_else(bad)?;
        if *has_rt != 1 {
            return Err(integrity("§14.4 has_rt")); // SR-14.4-3
        }
        if r_t.len() != 32 {
            return Err(bad());
        }
        Ok(RecordBlind {
            insert_leaf_index: u64::from_be_bytes(*idx),
            has_rt: 1,
            r_t: decode_scalar(r_t).map_err(|_| bad())?,
        })
    }
}

#[cfg(test)]
mod tests;

/// Test tooling (`memo-checks`): group states that passed INV-3 in this process, by SHA-256 of
/// `C_S ‖ r_agg ‖ S`; the same state passes again without recomputing `C_S`.
#[cfg(feature = "memo-checks")]
mod memo {
    use std::collections::HashSet;
    use std::sync::{Mutex, OnceLock};

    use sever_crypto::{encode_point, encode_scalar};
    use sha2::{Digest, Sha256};

    use super::{BlindingTotal, GroupCommitment};

    fn set() -> &'static Mutex<HashSet<[u8; 32]>> {
        static SET: OnceLock<Mutex<HashSet<[u8; 32]>>> = OnceLock::new();
        SET.get_or_init(|| Mutex::new(HashSet::new()))
    }

    pub(super) fn key(s: &[i64], public: &GroupCommitment, secret: &BlindingTotal) -> [u8; 32] {
        let mut h = Sha256::new();
        h.update(b"SEVERDB-INV3-MEMO");
        h.update(encode_point(&public.0));
        h.update(encode_scalar(&secret.0));
        for v in s {
            h.update(v.to_be_bytes());
        }
        h.finalize().into()
    }

    pub(super) fn seen(k: &[u8; 32]) -> bool {
        set().lock().is_ok_and(|m| m.contains(k))
    }

    pub(super) fn remember(k: [u8; 32]) {
        if let Ok(mut m) = set().lock() {
            if m.len() >= 1 << 20 {
                m.clear();
            }
            m.insert(k);
        }
    }
}
