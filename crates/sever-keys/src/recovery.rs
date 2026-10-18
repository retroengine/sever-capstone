//! The recovery rule INV-14 (spec §13.4) as a pure function.
//!
//! After the storage checkpoint and the WAL are replayed, every domain has an active key version
//! `v`. For each such domain the slot holding `v` MUST exist with a valid CRC, otherwise the engine
//! refuses to start (that data can no longer be decrypted); every other slot of that domain is
//! erased; slots that belong to no domain are erased. A slot names its domain (DB-90), so slots map
//! to domains directly. Two valid slots naming one domain at its active version cannot arise from
//! the protocol (a pair is written only for a new domain, and recovery erases unclaimed pairs before
//! any new transaction), and the engine could not tell which key encrypts the data, so that too
//! refuses to start.

use std::collections::BTreeMap;

use sever_types::Error;

use crate::file::{SlotRecord, SlotState};
use crate::{Domain, Key};

/// Where a domain's active key was found, and the key.
#[derive(Debug)]
pub struct ActiveKey {
    /// The pair (the domain's index).
    pub pair: u64,
    /// The slot within the pair (0 or 1).
    pub slot: u8,
    /// The key's version (the domain's active version).
    pub key_version: u64,
    /// The group key.
    pub key: Key,
}

/// What recovery keeps and what it erases.
#[derive(Debug, Default)]
pub struct Recovery {
    /// Every active domain's key.
    pub keys: BTreeMap<Domain, ActiveKey>,
    /// The slots to overwrite with zeros, as `(pair, slot)`, in file order.
    pub erase: Vec<(u64, u8)>,
}

/// Applies INV-14 to the slots read back (`slots[i]` is pair `i`) given each domain's active
/// version. `IntegrityViolation` ("INV-14") if a domain's active slot is missing or torn, or found
/// twice.
pub fn plan(active: &BTreeMap<Domain, u64>, slots: Vec<[SlotState; 2]>) -> Result<Recovery, Error> {
    let mut out = Recovery::default();
    for (pair, two) in (0u64..).zip(slots) {
        for (slot, state) in (0u8..).zip(two) {
            match state {
                SlotState::Erased => {}
                SlotState::Torn => out.erase.push((pair, slot)),
                SlotState::Valid(SlotRecord {
                    key_version,
                    domain,
                    key,
                    ..
                }) => {
                    if active.get(&domain) != Some(&key_version) {
                        out.erase.push((pair, slot));
                        continue;
                    }
                    let found = ActiveKey {
                        pair,
                        slot,
                        key_version,
                        key,
                    };
                    if out.keys.insert(domain, found).is_some() {
                        return Err(inv14());
                    }
                }
            }
        }
    }
    if active.keys().any(|d| !out.keys.contains_key(d)) {
        return Err(inv14());
    }
    Ok(out)
}

fn inv14() -> Error {
    Error::IntegrityViolation {
        invariant: "INV-14",
    }
}
