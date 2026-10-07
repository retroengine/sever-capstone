//! The transaction protocol (Build §5.4), defined once; later parts only add participants.
//!
//! ```text
//!  1  plan            the caller: a ChangeSet and its after-image records (all validation here)
//!  2  prepare         each participant adds WAL records, store bytes and phase-A actions
//!  3  append stores   their bytes are made durable (fsync)
//!  4  phase A         each participant's durable pre-commit actions
//!  5  WAL             BEGIN, core records, participant records, COMMIT; fsync  ── commit point ──
//!  6  apply           the caller installs the change under the exclusive lock
//!  7  phase C         each participant's after_commit
//!  8  acknowledge     only now does the caller see success (§15.8)
//! ```
//!
//! Nothing reaches memory before the commit point (§12.3: replay applies only committed
//! transactions, so memory must never be ahead of the disk). A failure before the commit point
//! changes nothing in memory; a `DurabilityFailure` means the caller must abort (§12.7).

use sever_appendstore::AppendStore;
use sever_format::{CoreRecord, Layout, RecordType};
use sever_index::GroupExtension;
use sever_types::Error;
use sever_wal::{Committed, Wal};

use crate::participant::{Participants, TxnDraft};

/// A boundary between protocol steps, reported to a test hook (deterministic interleavings:
/// a reader runs at every boundary, P2-T4; crash points are the VFS operations in between).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Step {
    /// After step 2.
    Prepared,
    /// After step 3.
    StoresSynced,
    /// After step 4.
    PhaseA,
    /// Right before the WAL write of step 5.
    WalWriting,
    /// After step 5: the commit point has passed.
    Committed,
    /// After step 6.
    Applied,
    /// After step 7.
    PhaseC,
}

/// The durable side of one transaction.
pub struct Durable<'a> {
    /// The log.
    pub wal: &'a mut Wal,
    /// The core's payload store (passage text).
    pub store: &'a mut dyn AppendStore,
}

/// What a committed transaction gives back.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Acknowledged {
    /// Where it is in the WAL.
    pub committed: Committed,
    /// Participant outputs `(participant ID, request index, bytes)` (Part 3: certificates).
    pub outputs: Vec<(u16, usize, Vec<u8>)>,
}

/// Runs steps 2–8 for `draft`. `apply` installs the core records (and the change set they came
/// from) in memory; it is called exactly once, after the commit point, and cannot fail.
pub fn commit<E: GroupExtension>(
    mut draft: TxnDraft<'_, E>,
    layout: &Layout,
    participants: &mut Participants<E>,
    durable: Durable<'_>,
    apply: impl FnOnce(&[CoreRecord]),
    hook: &mut dyn FnMut(Step),
) -> Result<Acknowledged, Error> {
    let abort = |ps: &mut Participants<E>| ps.iter_mut().for_each(|p| p.abort());
    // 2. prepare
    for i in 0..participants.len() {
        let r = participants
            .get_mut(i)
            .map_or(Ok(()), |p| p.prepare(&mut draft));
        if let Err(e) = r {
            abort(participants);
            return Err(e);
        }
    }
    hook(Step::Prepared);
    // Encode before anything durable happens: an encoding error is a plan error.
    let mut wal_records: Vec<(RecordType, Vec<u8>)> = Vec::with_capacity(draft.records.len());
    for r in &draft.records {
        match r.encode_payload(layout) {
            Ok(p) => wal_records.push((r.ty(), p)),
            Err(e) => {
                abort(participants);
                return Err(e);
            }
        }
    }
    wal_records.extend(draft.participant_records.iter().cloned());
    // 3. append stores
    let stores = durable
        .store
        .sync()
        .and_then(|()| participants.iter_mut().try_for_each(|p| p.sync_stores()));
    if let Err(e) = stores {
        abort(participants);
        return Err(e);
    }
    hook(Step::StoresSynced);
    // 4. phase A
    if let Err(e) = participants.iter_mut().try_for_each(|p| p.phase_a()) {
        abort(participants);
        return Err(e);
    }
    hook(Step::PhaseA);
    // SB-15: apply the change to memory before its COMMIT is durable.
    let mut apply = Some(apply);
    if cfg!(feature = "sabotage-SB-15") {
        if let Some(f) = apply.take() {
            f(&draft.records);
        }
    }
    hook(Step::WalWriting);
    // 5. WAL: the commit point.
    let committed = match durable.wal.commit(&wal_records) {
        Ok(c) => c,
        Err(e) => {
            abort(participants);
            return Err(e);
        }
    };
    hook(Step::Committed);
    // 6. apply
    if let Some(f) = apply.take() {
        f(&draft.records);
    }
    hook(Step::Applied);
    // 7. phase C: the transaction is committed; a failure here is a durability failure.
    participants.iter_mut().try_for_each(|p| p.after_commit())?;
    hook(Step::PhaseC);
    // 8. acknowledge
    Ok(Acknowledged {
        committed,
        outputs: draft.outputs,
    })
}
