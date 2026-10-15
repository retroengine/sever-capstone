//! EP-7 `TxnParticipant` (Build §3.3): takes part in every transaction, in protocol order (§5.4
//! of the build plan): it adds WAL records and append-store bytes, acts durably before the commit
//! (phase A) and after it (phase C), replays its records at recovery, and checks its invariants.
//!
//! Part 2 registers no participant. Part 3 adds the `LogParticipant` (leaves, certificates, log
//! checkpoints), Part 4 the `KeyRotationParticipant` (new keys in phase A, old keys erased in
//! phase C). The storage engine carries their records verbatim (DB-45).

use sever_format::{CoreRecord, RecordType, WalRecord};
use sever_index::{ChangeSet, GroupExtension};
use sever_types::{CollectionId, Error};

/// What a transaction does, for participants that need to know.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TxnKind {
    /// One insert (with its flush, if any).
    Insert,
    /// One delete, or a `delete_user` (one transaction for the whole list, §12.5).
    Delete,
    /// `create_collection`.
    CreateCollection,
    /// `drop_collection`.
    DropCollection,
}

/// A transaction between `plan` and the WAL write: what the core will log and apply.
pub struct TxnDraft<'a, E: GroupExtension> {
    /// What the transaction does.
    pub kind: TxnKind,
    /// The collection it changes.
    pub collection: CollectionId,
    /// The index change set (absent for collection creation and drop).
    pub changeset: Option<&'a ChangeSet<E>>,
    /// The core after-images, in replay order. A participant may replace or add records (Part 4
    /// re-seals accumulators and re-wraps survivors' envelopes here); the image applies exactly
    /// these at commit and at replay.
    pub records: Vec<CoreRecord>,
    /// Participant-owned records (`EXTENSION`, or a type the participant owns), logged after the
    /// core records.
    pub participant_records: Vec<(RecordType, Vec<u8>)>,
    /// What participants return to the caller with the acknowledgement (Part 3: one certificate
    /// per deleted record), as `(participant ID, request index, bytes)`; the request index is the
    /// position in a `delete_user` list (0 for a single operation).
    pub outputs: Vec<(u16, usize, Vec<u8>)>,
}

impl<E: GroupExtension> core::fmt::Debug for TxnDraft<'_, E> {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(
            f,
            "TxnDraft({:?}, {} core records, {} participant records)",
            self.kind,
            self.records.len(),
            self.participant_records.len()
        )
    }
}

/// A transaction a participant asks for before the planned one is prepared (Part 3: an on-demand
/// log checkpoint, spec §15.3 step 3). It is committed on its own, first (E-2).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PreTxn {
    /// Its participant records.
    pub records: Vec<(RecordType, Vec<u8>)>,
}

/// EP-7. Every hook has a do-nothing default, so a participant implements only what it uses.
pub trait TxnParticipant<E: GroupExtension>: Send {
    /// Its ID in `EXTENSION` records (`u16be participant_id`).
    fn id(&self) -> u16;

    /// The WAL record types it owns besides `EXTENSION` records with its ID.
    fn owned_types(&self) -> &[RecordType] {
        &[]
    }

    /// After planning (and only if there is something to do), before `prepare`: may request a
    /// separate transaction, which the engine commits on its own first and confirms with
    /// `after_commit` (or `abort` if its WAL write fails) (E-2; spec §15.3 steps 1–3).
    fn pre_transaction(
        &mut self,
        _kind: TxnKind,
        _collection: &CollectionId,
    ) -> Result<Option<PreTxn>, Error> {
        Ok(None)
    }

    /// After `plan`, before any write: add records and outputs, edit core records, append
    /// store bytes. Any error aborts the transaction with nothing written.
    fn prepare(&mut self, _draft: &mut TxnDraft<'_, E>) -> Result<(), Error> {
        Ok(())
    }

    /// Makes the store bytes appended in `prepare` durable (protocol step 3).
    fn sync_stores(&mut self) -> Result<(), Error> {
        Ok(())
    }

    /// Durable side effects that must precede `COMMIT` (Part 4: the new key slot).
    fn phase_a(&mut self) -> Result<(), Error> {
        Ok(())
    }

    /// The transaction did not commit (an error before or at the WAL write): undo in-memory
    /// effects of `prepare` (durable effects of phase A are resolved by `recover`).
    fn abort(&mut self) {}

    /// After `COMMIT` is durable and memory is applied (phase C; Part 4: erase the old key).
    fn after_commit(&mut self) -> Result<(), Error> {
        Ok(())
    }

    /// Recovery: one committed record it owns, in log order.
    fn replay(&mut self, _record: &WalRecord) -> Result<(), Error> {
        Ok(())
    }

    /// Recovery: after every committed record was replayed.
    fn recover(&mut self) -> Result<(), Error> {
        Ok(())
    }

    /// Its invariants (at startup, and at commit in debug builds).
    fn check_invariants(&self) -> Result<(), Error> {
        Ok(())
    }

    /// A collection is dropped (Part 4: erase every group key of it).
    fn on_drop_collection(&mut self, _collection: &CollectionId) -> Result<(), Error> {
        Ok(())
    }

    /// True if this participant owns `record` (its `EXTENSION` ID, or an owned type).
    fn owns(&self, record: &WalRecord) -> bool {
        if record.ty == RecordType::Extension {
            record.payload.get(..2) == Some(&self.id().to_be_bytes()[..])
        } else {
            self.owned_types().contains(&record.ty)
        }
    }
}

/// The registered participants (`P` in `Engine<E, S, P>`).
pub type Participants<E> = Vec<Box<dyn TxnParticipant<E>>>;
