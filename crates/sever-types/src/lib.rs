//! `sever-types`: the vocabulary every other SEVER-DB crate speaks (Part 1, Build §4.4).
//!
//! Responsibility: record, group and collection IDs with their validation, scrambled IDs, the
//! constants of §2, the core error types and `SecretBuf`.
//!
//! Spec: §2 (notation and constants), §3.2 (record IDs), §17 (errors, the subset Part 1 raises).
//! Declares extension point EP-4, the secret-memory provider (Build §3.3).
//!
//! No file I/O, clock or randomness here (CLAUDE.md §7).

pub mod constants;
pub mod error;
pub mod id;
pub mod secret;

#[cfg(any(test, feature = "contract-tests"))]
pub mod contract;

pub use error::{Error, InvalidRecordIdReason};
pub use id::{CollectionId, FrozenLabel, GroupId, RecordId, ScrambledId};
pub use secret::{
    HeapProvider, ProviderAlreadyInstalled, SecretBuf, SecretMemory, SecretRegion, install_provider,
};
