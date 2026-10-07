//! `sever-txn`: the transaction layer (Part 2, Build §5.5; spec §12.5, §15).
//!
//! Declares three extension points (Build §3.3):
//! - EP-6 [`Sealer`], with [`PlaintextSealer`] (DB-48: no confidentiality before Part 4);
//! - EP-7 [`TxnParticipant`], none registered in Part 2;
//! - EP-9 [`Clock`], with [`SystemClock`] and [`SimClock`].
//!
//! It turns a Part 1 `ChangeSet` into the after-image records the WAL carries
//! ([`changeset_records`]) and runs the commit protocol of Build §5.4 ([`commit`]). The writer
//! mutex and the reader lock live in the engine, which owns the state they protect.

pub mod clock;
pub mod decode;
pub mod ext;
pub mod participant;
pub mod protocol;
pub mod records;
pub mod sealer;

#[cfg(any(test, feature = "contract-tests"))]
pub mod contract;

pub use clock::{Clock, SimClock, SystemClock};
pub use decode::{DecodedGroup, decode_collection, rebuild_changeset};
pub use ext::StoredExtension;
pub use participant::{Participants, PreTxn, TxnDraft, TxnKind, TxnParticipant};
pub use protocol::{Acknowledged, Durable, Step, commit};
pub use records::{changeset_records, collection_records, layout_for};
pub use sealer::{GroupOwner, PlaintextSealer, RecordOwner, Sealer};

#[cfg(test)]
mod tests;
