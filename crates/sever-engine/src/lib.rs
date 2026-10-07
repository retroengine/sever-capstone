//! `sever-engine`: the storage engine around Part 1's frozen index (Part 2, Build §5.5; spec
//! §12, §15, §16.1).
//!
//! `Engine<E, S>` is generic over the group extension (EP-1, stored through `StoredExtension`)
//! and the sealer (EP-6), and takes its transaction participants (EP-7) at open. Part 2's
//! composition root uses `Engine<NoExtension, PlaintextSealer>` with no participants.
//!
//! Part 2's claim: Part 1's exactness holds after a crash at any point of any operation; no
//! acknowledged operation is lost; `delete_user` is all-or-nothing; reads are serializable. It
//! makes no confidentiality claim (DB-48).

pub mod config;
pub mod engine;
#[cfg(feature = "test-hooks")]
pub mod hooks;
pub mod platform;
mod recovery;

pub use config::{
    CollectionOptions, DeleteOutcome, EngineConfig, EngineStats, FailurePolicy, Hit, InsertReceipt,
    InsertRequest,
};
pub use engine::{Engine, PAYLOAD_DIR, SECRETS};
pub use platform::{EngineLock, PlatformReport, check_data_dir};
