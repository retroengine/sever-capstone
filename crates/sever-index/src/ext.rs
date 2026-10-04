//! EP-1 `GroupExtension` (Build §3.3): per-group and per-record state that changes in lockstep
//! with `S` and `n`. Part 1 ships [`NoExtension`]; Part 3 plugs in the commitment extension
//! (`C_S`, `r_agg`, `C_t`, `r_t`) without editing this crate.

use core::fmt::Debug;

use sever_quant::QVec;
use sever_types::Error;

/// EP-1. Each method maps to one capability of Build §3.3 (numbered there 1–9).
pub trait GroupExtension: Clone + Send + Sync {
    /// (1) Public group state, stored in plaintext (Part 3: `C_S`).
    type GroupPublic: Clone + PartialEq + Default + Debug + Send + Sync;
    /// (1) Secret group state, sealed with `S` (Part 3: `r_agg`).
    type GroupSecret: Clone + PartialEq + Default + Send + Sync;
    /// (2) A fixed-size secret per record (Part 3: insert leaf index, `has_rt`, `r_t`).
    type RecordSecret: Clone + PartialEq + Send + Sync;
    /// (3) What an insert must present to be admitted (Part 3: `C_t`, `r_t`, user key, signature).
    type Credential;

    /// (7) The canonical blob's 6-byte magic (DB-47).
    const BLOB_MAGIC: [u8; 6];

    /// (3) Admit or reject an insert of `x` with `credential`; on success, the record's secret.
    fn admit(&self, x: &QVec, credential: Self::Credential) -> Result<Self::RecordSecret, Error>;

    /// (4, 6) A record joins a group (insert, spillover or flush): update in lockstep with `S`.
    fn add(
        &self,
        public: &mut Self::GroupPublic,
        secret: &mut Self::GroupSecret,
        x: &QVec,
        record: &Self::RecordSecret,
    );

    /// (4) A record leaves a group: the exact inverse of [`GroupExtension::add`].
    fn remove(
        &self,
        public: &mut Self::GroupPublic,
        secret: &mut Self::GroupSecret,
        x: &QVec,
        record: &Self::RecordSecret,
    );

    /// (5) Before a removal: the stored `x` and record secret must be consistent (Part 3: they
    /// reproduce the logged `C_t`), otherwise `IntegrityViolation`. Takes no credential (DB-55).
    fn check_removal(&self, x: &QVec, record: &Self::RecordSecret) -> Result<(), Error>;

    /// (7) The blob's extension region, between `S` and `member_count` (DB-47).
    fn blob_region(
        &self,
        public: &Self::GroupPublic,
        secret: &Self::GroupSecret,
        out: &mut Vec<u8>,
    );

    /// (8) The extension's own invariants for one group (Part 3: INV-3).
    fn check_group(
        &self,
        s: &[i64],
        public: &Self::GroupPublic,
        secret: &Self::GroupSecret,
    ) -> Result<(), Error>;

    /// (9) For `DuplicateRecord { same_commitment }`: is this insert a retry of the live record?
    fn same_commitment(
        &self,
        live_x: &QVec,
        live: &Self::RecordSecret,
        new_x: &QVec,
        new: &Self::Credential,
    ) -> bool;
}

/// Part 1's extension: no extra state. The blob is the core form `SEVERC` with an empty region
/// (DB-47). Without commitments, a retried insert is recognised by an identical quantised vector.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct NoExtension;

impl GroupExtension for NoExtension {
    type GroupPublic = ();
    type GroupSecret = ();
    type RecordSecret = ();
    type Credential = ();
    const BLOB_MAGIC: [u8; 6] = *b"SEVERC";

    fn admit(&self, _x: &QVec, _credential: ()) -> Result<(), Error> {
        Ok(())
    }
    fn add(&self, _public: &mut (), _secret: &mut (), _x: &QVec, _record: &()) {}
    fn remove(&self, _public: &mut (), _secret: &mut (), _x: &QVec, _record: &()) {}
    fn check_removal(&self, _x: &QVec, _record: &()) -> Result<(), Error> {
        Ok(())
    }
    fn blob_region(&self, _public: &(), _secret: &(), _out: &mut Vec<u8>) {}
    fn check_group(&self, _s: &[i64], _public: &(), _secret: &()) -> Result<(), Error> {
        Ok(())
    }
    fn same_commitment(&self, live_x: &QVec, _live: &(), new_x: &QVec, _new: &()) -> bool {
        live_x == new_x
    }
}
