//! Contract suites for EP-1 and EP-2 (Build §3.4, test level L7). Enabled by `contract-tests`, so
//! implementations written after Part 1 freezes (Part 3's `CommitmentExtension`) run the same
//! checks unchanged.

use sever_quant::QVec;
use sever_types::{CollectionId, RecordId};

use crate::ext::GroupExtension;
use crate::scramble::IdScrambler;

/// Why an extension failed the EP-1 contract.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ep1Violation {
    /// Adding then removing every record did not restore the initial state exactly.
    RemoveIsNotInverse,
    /// Adding the same records in another order gave different state or blob bytes.
    OrderDependent,
    /// A record the extension itself admitted was refused at removal.
    RefusesItsOwnRecord,
}

/// EP-1: add-then-remove restores the extension state exactly; state and blob region do not depend
/// on the order of adds; every honest record passes the removal integrity check.
pub fn ep1_contract<E: GroupExtension>(
    ext: &E,
    records: &[(QVec, E::RecordSecret)],
) -> Result<(), Ep1Violation> {
    let fresh = || (E::GroupPublic::default(), E::GroupSecret::default());
    let (mut p, mut s) = fresh();
    for (x, r) in records {
        ext.add(&mut p, &mut s, x, r);
    }
    let (mut p2, mut s2) = fresh();
    for (x, r) in records.iter().rev() {
        ext.add(&mut p2, &mut s2, x, r);
    }
    let (mut b1, mut b2) = (Vec::new(), Vec::new());
    ext.blob_region(&p, &s, &mut b1);
    ext.blob_region(&p2, &s2, &mut b2);
    if p != p2 || s != s2 || b1 != b2 {
        return Err(Ep1Violation::OrderDependent);
    }
    for (x, r) in records {
        if ext.check_removal(x, r).is_err() {
            return Err(Ep1Violation::RefusesItsOwnRecord);
        }
        ext.remove(&mut p, &mut s, x, r);
    }
    let (p0, s0) = fresh();
    if p != p0 || s != s0 {
        return Err(Ep1Violation::RemoveIsNotInverse);
    }
    Ok(())
}

/// Why a scrambler failed the EP-2 contract.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ep2Violation {
    /// The same input gave two outputs.
    NotDeterministic,
    /// Two different record IDs gave the same output.
    IdCollision,
    /// The same record ID in two collections gave the same output.
    CollectionIgnored,
}

/// EP-2: deterministic, and distinct across record IDs and across collections.
pub fn ep2_contract<S: IdScrambler>(scrambler: &S) -> Result<(), Ep2Violation> {
    let (c1, c2) = (
        CollectionId::from_bytes([1; 16]),
        CollectionId::from_bytes([2; 16]),
    );
    let ids: Vec<RecordId> = ["doc0", "doc1", "Doc0", "é", "nq-1234"]
        .into_iter()
        .filter_map(|s| RecordId::new(s).ok())
        .collect();
    let mut seen = Vec::new();
    for id in &ids {
        let a = scrambler.scramble(&c1, id);
        if a != scrambler.scramble(&c1, id) {
            return Err(Ep2Violation::NotDeterministic);
        }
        if a == scrambler.scramble(&c2, id) {
            return Err(Ep2Violation::CollectionIgnored);
        }
        if seen.contains(&a) {
            return Err(Ep2Violation::IdCollision);
        }
        seen.push(a);
    }
    Ok(())
}
