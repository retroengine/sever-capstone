//! `sever-index`: the SEVER index (Part 1, Build §4.4; spec §5, §7, §9.7).
//!
//! Groups keep exact integer sums `S` and counts `n`, so a deletion returns its group, bit for bit,
//! to the state it would have had without the record (§5.3). Every mutation is a pure `plan` that
//! returns a [`ChangeSet`] and an `apply` that cannot fail (Build §1.1).
//!
//! Declares EP-1 ([`GroupExtension`]), EP-2 ([`IdScrambler`]) and EP-3 ([`ChangeSet`]).
//! No file I/O, clock or randomness here (CLAUDE.md §7): the scrambling key is handed in.

pub mod blob;
pub mod changeset;
pub mod ext;
pub mod index;
pub mod route;
pub mod scramble;

#[cfg(any(test, feature = "contract-tests"))]
pub mod contract;

#[cfg(test)]
mod tests;

pub use blob::{Field, GroupSnapshot, assert_state_equivalent};
pub use changeset::{ChangeSet, Counters, Outcome, Placement, Slot};
pub use ext::{GroupExtension, NoExtension};
pub use index::{
    DeleteRequest, GroupKind, Index, IndexConfig, InsertRequest, SearchGroup, Stats, has_room,
    spawn_id,
};
pub use scramble::{HmacSha512Scrambler, IdScrambler};
