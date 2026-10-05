//! THROWAWAY proof spike (Build §3.4). Shows, before Part 1 freezes, that:
//! - EP-1 (`GroupExtension`) can carry Part 3's Pedersen commitments (`C_S`, `r_agg`, `C_t`, `r_t`)
//!   with the real ristretto255 library, and passes the EP-1 contract suite;
//! - EP-3 (`ChangeSet`) exposes what Part 4's key rotation needs: the groups a transaction removes
//!   records from (departures) and adds records to (arrivals).
//! Generators here are a stand-in (hash-to-point of a label); the real derivation is §9.2.

use std::collections::BTreeSet;

use curve25519_dalek::ristretto::{CompressedRistretto, RistrettoPoint};
use curve25519_dalek::scalar::Scalar;
use curve25519_dalek::traits::Identity;
use rand_core::OsRng;
use sever_index::{ChangeSet, GroupExtension};
use sever_quant::QVec;
use sever_types::{Error, GroupId};
use sha2::Sha512;

/// §4.5: `v mod ℓ` for `v ≥ 0`, `ℓ − (|v| mod ℓ)` for `v < 0`.
pub fn scalar_of(v: i64) -> Scalar {
    let m = Scalar::from(v.unsigned_abs());
    if v < 0 { -m } else { m }
}

/// A Part 3 extension, minimal: `C_S` public, `r_agg` secret, `(r_t, C_t)` per record.
#[derive(Clone)]
pub struct CommitmentExtension {
    h: RistrettoPoint,
    g: Vec<RistrettoPoint>,
}

/// What an insert presents: the backend's `r_t` and `C_t` (§9.3).
#[derive(Clone)]
pub struct Credential {
    /// Blinding scalar.
    pub r_t: Scalar,
    /// `r_t·H + Σ x̃_i·G_i`.
    pub c_t: CompressedRistretto,
}

/// The per-record secret the engine stores.
#[derive(Clone, PartialEq)]
pub struct RecordSecret {
    r_t: Scalar,
    c_t: CompressedRistretto,
}

impl CommitmentExtension {
    /// Stand-in generators for dimension `d`.
    pub fn new(d: usize) -> Self {
        let h = RistrettoPoint::hash_from_bytes::<Sha512>(b"SEVER-spike-H");
        let g = (0..d)
            .map(|i| {
                let mut label = b"SEVER-spike-G".to_vec();
                label.extend_from_slice(&(i as u16).to_be_bytes());
                RistrettoPoint::hash_from_bytes::<Sha512>(&label)
            })
            .collect();
        Self { h, g }
    }

    fn commit(&self, values: impl Iterator<Item = i64>, r: &Scalar) -> RistrettoPoint {
        values
            .zip(&self.g)
            .fold(r * self.h, |acc, (v, g)| acc + scalar_of(v) * g)
    }

    /// The backend side of an insert: a fresh `r_t` from the OS (never a seed) and its `C_t`.
    pub fn credential(&self, x: &QVec) -> Credential {
        let r_t = Scalar::random(&mut OsRng);
        let c_t = self
            .commit(x.as_slice().iter().map(|&v| i64::from(v)), &r_t)
            .compress();
        Credential { r_t, c_t }
    }
}

impl GroupExtension for CommitmentExtension {
    type GroupPublic = RistrettoPoint; // C_S
    type GroupSecret = Scalar; // r_agg
    type RecordSecret = RecordSecret;
    type Credential = Credential;
    const BLOB_MAGIC: [u8; 6] = *b"SEVERG";

    fn admit(&self, x: &QVec, c: Credential) -> Result<RecordSecret, Error> {
        let expect = self.commit(x.as_slice().iter().map(|&v| i64::from(v)), &c.r_t);
        if expect.compress() != c.c_t || expect == RistrettoPoint::identity() {
            return Err(Error::CommitmentMismatch); // §9.3; C_t ≠ identity
        }
        Ok(RecordSecret {
            r_t: c.r_t,
            c_t: c.c_t,
        })
    }

    fn add(&self, p: &mut RistrettoPoint, s: &mut Scalar, x: &QVec, r: &RecordSecret) {
        *p += self.commit(x.as_slice().iter().map(|&v| i64::from(v)), &r.r_t);
        *s += r.r_t;
    }

    fn remove(&self, p: &mut RistrettoPoint, s: &mut Scalar, x: &QVec, r: &RecordSecret) {
        *p -= self.commit(x.as_slice().iter().map(|&v| i64::from(v)), &r.r_t);
        *s -= r.r_t;
    }

    fn check_removal(&self, x: &QVec, r: &RecordSecret) -> Result<(), Error> {
        let c = self.commit(x.as_slice().iter().map(|&v| i64::from(v)), &r.r_t);
        if c.compress() == r.c_t {
            Ok(())
        } else {
            Err(Error::IntegrityViolation {
                invariant: "§15.3 C_t",
            })
        }
    }

    fn blob_region(&self, p: &RistrettoPoint, s: &Scalar, out: &mut Vec<u8>) {
        out.extend_from_slice(p.compress().as_bytes()); // C_S
        out.extend_from_slice(s.as_bytes()); // r_agg
    }

    fn check_group(&self, s: &[i64], p: &RistrettoPoint, r: &Scalar) -> Result<(), Error> {
        // INV-3: C_S = r_agg·H + Σ S_i·G_i.
        if self.commit(s.iter().copied(), r) == *p {
            Ok(())
        } else {
            Err(Error::IntegrityViolation { invariant: "INV-3" })
        }
    }

    fn same_commitment(&self, _: &QVec, live: &RecordSecret, _: &QVec, new: &Credential) -> bool {
        live.c_t == new.c_t
    }
}

/// A stub of Part 4's rotation step: the groups whose keys a transaction must rotate, read from the
/// `ChangeSet` alone (departures and arrivals; the holding area has no group key).
pub fn groups_to_rotate<E: GroupExtension>(cs: &ChangeSet<E>) -> BTreeSet<GroupId> {
    cs.departures
        .iter()
        .chain(&cs.arrivals)
        .map(|(g, _)| *g)
        .filter(|g| *g != GroupId::Holding)
        .collect()
}
