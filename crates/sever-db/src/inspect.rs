//! DB-107: an `inspect` build reports each committed change's public fields (spec §16.1).
//!
//! `InspectParticipant` takes part in every transaction through EP-7, after the log and key-rotation
//! participants. In `prepare` it copies from the change set (EP-3) only values spec §13.2 allows in
//! plaintext: groups created by a flush with their centroid, each touched group's `n` and `C_S`
//! before and after, `N` and `k` before and after, arrivals and departures as `(group ID,
//! scrambled_id)`, and each request's outcome. It never reads `S`, `r_agg`, slots or payloads, so it
//! cannot copy `x̃`, `r_t`, a record ID or passage text. It publishes in `after_commit` and drops in
//! `abort`, so a transaction that does not commit reports nothing. Events live in memory only; it
//! writes no WAL record, so a database opened with or without the feature is the same database.

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use sever_commit::CommitmentExtension;
use sever_crypto::encode_point;
use sever_index::{ChangeSet, Outcome};
use sever_p3::{cid_hex, placement_text};
use sever_txn::{TxnDraft, TxnKind, TxnParticipant};
use sever_types::{Error, GroupId, ScrambledId};

/// Its EP-7 participant ID. It owns no WAL record type and writes no `EXTENSION` record.
pub const INSPECT_PARTICIPANT_ID: u16 = 0x7E;

/// The newest events kept; older ones are dropped (a viewer that falls this far behind re-reads
/// the log).
const KEPT: usize = 100_000;

/// One touched group: its size and commitment before and after (§5.3).
#[derive(Clone, Debug, PartialEq)]
pub struct GroupMove {
    /// The group, §5.1 text form.
    pub group: String,
    /// `n` before.
    pub n_before: u64,
    /// `n` after.
    pub n_after: u64,
    /// `C_S` before (32-byte canonical encoding, §0.2).
    pub c_s_before: [u8; 32],
    /// `C_S` after.
    pub c_s_after: [u8; 32],
}

/// One committed transaction, as far as spec §13.2 lets it be shown.
#[derive(Clone, Debug, PartialEq)]
pub struct Event {
    /// Its position among this process's events, from 0.
    pub seq: u64,
    /// `insert`, `delete`, `create_collection` or `drop_collection`.
    pub kind: &'static str,
    /// The collection, as hex.
    pub collection: String,
    /// Groups a flush created, with the centroid the engine computed (§7.5).
    pub created: Vec<(String, Vec<f64>)>,
    /// Every touched group.
    pub groups: Vec<GroupMove>,
    /// `(N, k)` before (§7.6).
    pub counters_before: (u64, u64),
    /// `(N, k)` after.
    pub counters_after: (u64, u64),
    /// `(group, scrambled_id)` of each record that joined a group or the holding area.
    pub arrivals: Vec<(String, [u8; 64])>,
    /// `(group, scrambled_id)` of each record that left one.
    pub departures: Vec<(String, [u8; 64])>,
    /// Per request: `placed <group>`, `deleted from <group>` or `absent`.
    pub outcomes: Vec<String>,
}

/// The events, shared between the participant and the database's readers.
#[derive(Debug, Default)]
pub struct InspectHandle {
    events: Mutex<(u64, VecDeque<Event>)>,
}

impl InspectHandle {
    /// Every kept event with `seq >= since`, in commit order.
    pub fn since(&self, since: u64) -> Vec<Event> {
        let guard = self.events.lock().unwrap_or_else(|p| p.into_inner());
        guard.1.iter().filter(|e| e.seq >= since).cloned().collect()
    }

    fn publish(&self, mut e: Event) {
        let mut guard = self.events.lock().unwrap_or_else(|p| p.into_inner());
        e.seq = guard.0;
        guard.0 += 1;
        guard.1.push_back(e);
        while guard.1.len() > KEPT {
            guard.1.pop_front();
        }
    }
}

/// The EP-7 participant (DB-107).
pub struct InspectParticipant {
    handle: Arc<InspectHandle>,
    pending: Option<Event>,
}

impl InspectParticipant {
    /// A participant and the handle its events are read from.
    pub fn new() -> (Self, Arc<InspectHandle>) {
        let handle = Arc::new(InspectHandle::default());
        let p = Self {
            handle: Arc::clone(&handle),
            pending: None,
        };
        (p, handle)
    }
}

fn kind(k: TxnKind) -> &'static str {
    match k {
        TxnKind::Insert => "insert",
        TxnKind::Delete => "delete",
        TxnKind::CreateCollection => "create_collection",
        TxnKind::DropCollection => "drop_collection",
    }
}

fn moves(domain: &[(GroupId, ScrambledId)]) -> Vec<(String, [u8; 64])> {
    domain
        .iter()
        .map(|(g, s)| (g.as_text(), *s.as_bytes()))
        .collect()
}

fn empty() -> Event {
    Event {
        seq: 0,
        kind: "",
        collection: String::new(),
        created: Vec::new(),
        groups: Vec::new(),
        counters_before: (0, 0),
        counters_after: (0, 0),
        arrivals: Vec::new(),
        departures: Vec::new(),
        outcomes: Vec::new(),
    }
}

fn public_fields(cs: &ChangeSet<CommitmentExtension>) -> Event {
    Event {
        created: cs
            .created
            .iter()
            .map(|c| (c.id.as_text(), c.centroid.clone()))
            .collect(),
        groups: cs
            .groups
            .iter()
            .map(|g| GroupMove {
                group: g.group.as_text(),
                n_before: g.before.n,
                n_after: g.after.n,
                c_s_before: encode_point(&g.before.ext_public.0),
                c_s_after: encode_point(&g.after.ext_public.0),
            })
            .collect(),
        counters_before: (cs.counters_before.big_n, cs.counters_before.k),
        counters_after: (cs.counters_after.big_n, cs.counters_after.k),
        arrivals: moves(&cs.arrivals),
        departures: moves(&cs.departures),
        outcomes: cs
            .outcomes
            .iter()
            .map(|o| match o {
                Outcome::Placed(p) => format!("placed {}", placement_text(p)),
                Outcome::Deleted { from } => format!("deleted from {}", from.as_text()),
                Outcome::AlreadyAbsent => "absent".to_owned(),
            })
            .collect(),
        ..empty()
    }
}

impl TxnParticipant<CommitmentExtension> for InspectParticipant {
    fn id(&self) -> u16 {
        INSPECT_PARTICIPANT_ID
    }

    fn prepare(&mut self, draft: &mut TxnDraft<'_, CommitmentExtension>) -> Result<(), Error> {
        let mut e = draft.changeset.map_or_else(empty, public_fields);
        e.kind = kind(draft.kind);
        e.collection = cid_hex(&draft.collection);
        self.pending = Some(e);
        Ok(())
    }

    fn abort(&mut self) {
        self.pending = None;
    }

    fn after_commit(&mut self) -> Result<(), Error> {
        if let Some(e) = self.pending.take() {
            self.handle.publish(e);
        }
        Ok(())
    }
}

/// Adds the participant last, keeping Build 3-4 §2.5's order for the others.
pub fn register(
    mut participants: Vec<Box<dyn TxnParticipant<CommitmentExtension>>>,
) -> (
    Vec<Box<dyn TxnParticipant<CommitmentExtension>>>,
    Arc<InspectHandle>,
) {
    let (p, handle) = InspectParticipant::new();
    participants.push(Box::new(p));
    (participants, handle)
}
