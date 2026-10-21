//! `LogParticipant`, EP-7 (Build 3-4 §1.5; spec §10, §15.1 step 6, §15.3 steps 3–6): the log as
//! a transaction participant. It lives here, beside the certificate builder it calls, rather than
//! in `sever-log` (DB-81).
//!
//! - `pre_transaction`: log checkpoints, each over committed leaves only and committed on its own
//!   before the operation (DB-82): one at every multiple of 10,000 leaves not yet checkpointed
//!   (§10.3), and before a deletion one at the current size if a witnessed checkpoint does not
//!   cover every leaf (§15.3 step 3; DB-80: the hook does not say which record, so "every leaf"
//!   stands for "the record's insert leaf").
//! - `prepare`: an insert's leaf (§15.1 step 6) and its `database_lsn` as the output (step 9); a
//!   deletion's certificate, built on the state the
//!   previous deletion of the same transaction left (§15.3 step 4, `delete_user` chains), its
//!   delete leaf and the certificate reference; the certificates are the operation's outputs.
//! - `sync_stores`, `after_commit`, `abort`, `replay`, `recover`, `check_invariants`: the
//!   [`LogStore`].
//!
//! The commitment extension hands over what the `ChangeSet` does not carry: the validated insert
//! (its user key and signature) and each removed record's `x̃` and `r_t`, through [`LogHandle`],
//! the extension's [`LeafLog`].

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, MutexGuard};

use sever_commit::{CommitmentExtension, LeafLog, StagedInsert, StagedRemoval};
use sever_crypto::{Generators, Scalar, StrictProofRng, commit_record, encode_point};
use sever_format::{RecordType, WalRecord};
use sever_index::changeset::SlotOp;
use sever_index::{ChangeSet, Outcome};
use sever_log::checkpoint::{CHECKPOINT_EVERY, LogCheckpoint, is_witnessed};
use sever_log::keys::{Keyring, OperatorKeys};
use sever_log::leaf::{InsertLeaf, Placement};
use sever_log::store::{LogStore, LogStoreConfig, Witnessed};
use sever_log::witness::Witness;
use sever_txn::{Clock, PreTxn, TxnDraft, TxnKind, TxnParticipant};
use sever_types::{CollectionId, Error, GroupId};
use sever_vfs::Vfs;

use crate::builder::{Deletion, Removal, build};
use crate::encoding::InsertInclusion;

/// The log participant's ID in transaction outputs (EP-7).
pub const LOG_PARTICIPANT_ID: u16 = 3;

const OWNED: [RecordType; 3] = [
    RecordType::LogLeaf,
    RecordType::LogCheckpoint,
    RecordType::CertRef,
];

fn inv(rule: &'static str) -> Error {
    Error::IntegrityViolation { invariant: rule }
}

/// What the composition root gives the log.
pub struct LogParts {
    /// The generators (self-checked, §9.2).
    pub gens: Arc<Generators>,
    /// EP-9: checkpoint timestamps and epochs.
    pub clock: Arc<dyn Clock>,
    /// The operator's signing keys by epoch (§9.8), kept durably by the composition root.
    pub operator: Box<dyn OperatorKeys>,
    /// The witnesses (EP-10), one per index `0 … 4`.
    pub witnesses: Vec<Box<dyn Witness>>,
    /// The stores' settings.
    pub store: LogStoreConfig,
}

struct Inner {
    vfs: Arc<dyn Vfs>,
    parts: LogParts,
    log: Option<LogStore>,
    replayed: Vec<WalRecord>,
    inserts: Vec<StagedInsert>,
    removals: Vec<StagedRemoval>,
}

fn lock(m: &Mutex<Inner>) -> MutexGuard<'_, Inner> {
    match m.lock() {
        Ok(g) => g,
        Err(p) => p.into_inner(),
    }
}

/// EP-7 `TxnParticipant` for the commitment extension.
pub struct LogParticipant(Arc<Mutex<Inner>>);

/// The extension's view of the log ([`LeafLog`]).
pub struct LogHandle(Arc<Mutex<Inner>>);

impl LogParticipant {
    /// A participant over the data directory `vfs`; the log's stores are opened (or created) at
    /// [`TxnParticipant::recover`], after the engine has opened (or created) the database.
    pub fn new(vfs: Arc<dyn Vfs>, parts: LogParts) -> (Self, Arc<LogHandle>) {
        let inner = Arc::new(Mutex::new(Inner {
            vfs,
            parts,
            log: None,
            replayed: Vec::new(),
            inserts: Vec::new(),
            removals: Vec::new(),
        }));
        (Self(Arc::clone(&inner)), Arc::new(LogHandle(inner)))
    }
}

impl LogHandle {
    /// Runs `f` on the committed log (after recovery).
    pub fn with<T>(&self, f: impl FnOnce(&LogStore) -> T) -> Option<T> {
        lock(&self.0).log.as_ref().map(f)
    }
}

impl LogHandle {
    /// The public keys a verifier trusts (§11.3 anchors): the operator's by epoch, and each
    /// witness's by epoch (indexed by witness).
    pub fn anchors(&self) -> (Keyring, Vec<Keyring>) {
        let g = lock(&self.0);
        (
            g.parts.operator.keyring().clone(),
            rings(&g.parts.witnesses),
        )
    }
}

impl LeafLog for LogHandle {
    fn next_leaf_index(&self) -> u64 {
        lock(&self.0).log.as_ref().map_or(0, LogStore::next_index)
    }

    fn insert_leaf_c_t(&self, index: u64) -> Result<Option<[u8; 32]>, Error> {
        // §17 (G-41): a leaf that cannot be read or verified is reported as that failure.
        let g = lock(&self.0);
        let Some(log) = g.log.as_ref() else {
            return Ok(None);
        };
        Ok(log.insert_leaf(index)?.map(|l| l.c_t))
    }

    fn stage_insert(&self, insert: StagedInsert) {
        lock(&self.0).inserts.push(insert);
    }

    fn stage_removal(&self, removal: StagedRemoval) {
        lock(&self.0).removals.push(removal);
    }
}

/// The checkpoint sizes to issue before an operation (§10.3, §15.3 step 3; DB-80, DB-82): every
/// multiple of 10,000 in `(last, size]`, and `size` itself before a deletion if the latest
/// witnessed checkpoint covers fewer than `size` leaves.
pub fn due_checkpoints(last: u64, last_witnessed: u64, size: u64, kind: TxnKind) -> Vec<u64> {
    let mut due: Vec<u64> = (last / CHECKPOINT_EVERY + 1..=size / CHECKPOINT_EVERY)
        .map(|k| k * CHECKPOINT_EVERY)
        .collect();
    if kind == TxnKind::Delete && last_witnessed < size && due.last() != Some(&size) {
        due.push(size);
    }
    due
}

fn rings(witnesses: &[Box<dyn Witness>]) -> Vec<Keyring> {
    let mut out = vec![Keyring::new(); witnesses.len()];
    for w in witnesses {
        if let Some(r) = out.get_mut(usize::from(w.index())) {
            *r = w.keyring().clone();
        }
    }
    out
}

impl Inner {
    fn log(&mut self) -> Result<&mut LogStore, Error> {
        self.log.as_mut().ok_or(inv("§15.7 log not recovered"))
    }

    /// Signs a checkpoint of the first `size` committed leaves and collects cosignatures.
    fn issue(&mut self, size: u64) -> Result<Witnessed, Error> {
        let now = self.parts.clock.now_ms();
        let log = self.log.as_ref().ok_or(inv("§15.7 log not recovered"))?;
        let root = log.tree().root(size).ok_or(inv("§10.3 checkpoint size"))?;
        let checkpoint = LogCheckpoint::sign(&mut *self.parts.operator, size, root, now)?;
        let mut cosignatures = Vec::new();
        for w in &mut self.parts.witnesses {
            let last = w.last().tree_size;
            let proof = if last == 0 || last >= size {
                Vec::new()
            } else {
                log.tree().consistency_proof(last, size).unwrap_or_default()
            };
            if let Ok(c) = w.cosign(&checkpoint, &proof, now) {
                cosignatures.push(c);
            }
        }
        Ok(Witnessed {
            checkpoint,
            cosignatures,
        })
    }

    fn pre(&mut self, kind: TxnKind) -> Result<Option<PreTxn>, Error> {
        let rings = rings(&self.parts.witnesses);
        let log = self.log()?;
        let size = log.tree().size();
        let last = log
            .checkpoints()
            .last()
            .map_or(0, |w| w.checkpoint.tree_size);
        let last_witnessed = log
            .checkpoints()
            .iter()
            .rev()
            .find(|w| is_witnessed(&w.checkpoint, &w.cosignatures, &rings))
            .map_or(0, |w| w.checkpoint.tree_size);
        let due = due_checkpoints(last, last_witnessed, size, kind);
        if due.is_empty() {
            return Ok(None);
        }
        let mut records = Vec::new();
        for s in due {
            let w = self.issue(s)?;
            // A witness may create its epoch key when it first cosigns: read the keys now.
            let now_rings = self::rings(&self.parts.witnesses);
            let witnessed = is_witnessed(&w.checkpoint, &w.cosignatures, &now_rings);
            if kind == TxnKind::Delete && s == size && !witnessed {
                self.log()?.abort();
                // §10.4: an honest checkpoint of committed leaves that four witnesses refuse means
                // the log forked from what they saw (DB-82).
                return Err(inv("§10.4 witnesses"));
            }
            records.push(self.log()?.stage_checkpoint(w)?.encode());
        }
        Ok(Some(PreTxn { records }))
    }

    fn prepare_insert(
        &mut self,
        draft: &mut TxnDraft<'_, CommitmentExtension>,
    ) -> Result<(), Error> {
        let cs = draft.changeset.ok_or(inv("§15.1 step 6 change set"))?;
        let staged = self
            .inserts
            .pop()
            .ok_or(inv("§15.1 step 6 staged insert"))?;
        self.inserts.clear();
        let gens = Arc::clone(&self.parts.gens);
        let log = self.log()?;
        let index = log.next_index();
        let slot = cs
            .slots
            .iter()
            .find_map(|op| match op {
                SlotOp::Put { slot, .. } if slot.ext.insert_leaf_index == index => Some(slot),
                _ => None,
            })
            .ok_or(inv("§15.1 step 6 inserted slot"))?;
        let c_t = commit_record(&gens, slot.x.as_slice(), &slot.ext.r_t)
            .map(|p| encode_point(&p))
            .map_err(|_| inv("§15.1 step 6 C_t"))?;
        if staged.insert_leaf_index != index
            || staged.collection_id != *draft.collection.as_bytes()
            || staged.c_t != c_t
        {
            return Err(inv("§15.1 step 6 staged insert"));
        }
        let leaf = InsertLeaf {
            collection_id: staged.collection_id,
            scrambled_id: *slot.scrambled_id.as_bytes(),
            c_t,
            user_public_key: staged.user_public_key,
            user_signature: staged.signature,
        };
        // DB-86: where the record ended up; a flush (§15.2) moves every holding record, this one
        // included, into the group it creates.
        let put = cs
            .slots
            .iter()
            .rev()
            .find_map(|op| match op {
                SlotOp::Put { group, slot, .. } if slot.ext.insert_leaf_index == index => {
                    Some(*group)
                }
                _ => None,
            })
            .ok_or(inv("§15.1 step 6 inserted slot"))?;
        let flush = cs.created.first().map(|c| c.id);
        let placement = Placement {
            group: match (put, flush) {
                (GroupId::Holding, Some(created)) => created,
                (g, _) => g,
            },
            flush,
        };
        let (index, rec) = log.stage_insert(&leaf, placement)?;
        draft.participant_records.push(rec.encode());
        // §15.1 step 9: the insert returns its database_lsn, the index of its leaf.
        draft
            .outputs
            .push((LOG_PARTICIPANT_ID, 0, index.to_be_bytes().to_vec()));
        Ok(())
    }

    fn prepare_delete(
        &mut self,
        draft: &mut TxnDraft<'_, CommitmentExtension>,
    ) -> Result<(), Error> {
        let cs: &ChangeSet<CommitmentExtension> =
            draft.changeset.ok_or(inv("§15.3 step 4 change set"))?;
        let deleted = cs
            .outcomes
            .iter()
            .filter(|o| matches!(o, Outcome::Deleted { .. }))
            .count();
        if self.removals.len() < deleted || cs.departures.len() != deleted {
            return Err(inv("§15.3 step 4 staged removals"));
        }
        let removals = self.removals.split_off(self.removals.len() - deleted);
        self.removals.clear();
        // Each touched group's state, moved one deletion at a time (§5.3).
        let mut track: BTreeMap<GroupId, Track> = cs
            .groups
            .iter()
            .map(|gc| {
                (
                    gc.group,
                    Track {
                        s: gc.before.s.clone(),
                        r: gc.before.ext_secret.0,
                        c_s: encode_point(&gc.before.ext_public.0),
                        n: gc.before.n,
                    },
                )
            })
            .collect();
        let rings = rings(&self.parts.witnesses);
        let now = self.parts.clock.now_ms();
        let gens = Arc::clone(&self.parts.gens);
        let collection: CollectionId = draft.collection;
        let mut done = 0usize;
        for (req, outcome) in cs.outcomes.iter().enumerate() {
            let Outcome::Deleted { from } = outcome else {
                continue;
            };
            let (rem, (group, sid)) = removals
                .get(done)
                .zip(cs.departures.get(done))
                .ok_or(inv("§15.3 step 4 staged removals"))?;
            done += 1;
            let log = self.log.as_ref().ok_or(inv("§15.7 log not recovered"))?;
            let leaf = log
                .insert_leaf(rem.insert_leaf_index)?
                .ok_or(inv("§15.3 insert leaf"))?;
            if group != from
                || leaf.scrambled_id != *sid.as_bytes()
                || leaf.collection_id != *collection.as_bytes()
            {
                return Err(inv("§15.3 step 4 staged removals"));
            }
            let cp = log
                .checkpoints()
                .iter()
                .rev()
                .find(|w| {
                    w.checkpoint.tree_size > rem.insert_leaf_index
                        && is_witnessed(&w.checkpoint, &w.cosignatures, &rings)
                })
                .ok_or(inv("§15.3 step 3 witnessed checkpoint"))?
                .clone();
            let path = log
                .tree()
                .inclusion_proof(rem.insert_leaf_index, cp.checkpoint.tree_size)
                .ok_or(inv("§11.2 inclusion path"))?;
            let lsn = log.next_index();
            let inclusion = InsertInclusion {
                leaf,
                leaf_index: rem.insert_leaf_index,
                checkpoint: cp.checkpoint,
                path,
            };
            let post = if *group == GroupId::Holding {
                None
            } else {
                let t = track.get(group).ok_or(inv("§15.3 step 4 group state"))?;
                let mut s = t.s.clone();
                for (si, &xi) in s.iter_mut().zip(&rem.x) {
                    *si -= i64::from(xi);
                }
                Some(Track {
                    s,
                    r: t.r - rem.r_t,
                    c_s: t.c_s,
                    n: t.n.saturating_sub(1),
                })
            };
            let removal = match (&post, track.get(group)) {
                (Some(p), Some(t)) => Removal::Group {
                    c_s_pre: t.c_s,
                    s_post: &p.s,
                    r_post: &p.r,
                    n_post: p.n,
                },
                _ => Removal::Holding,
            };
            let deletion = Deletion {
                inclusion,
                cosignatures: cp.cosignatures,
                database_lsn: lsn,
                removal,
            };
            let cert = build(
                &gens,
                deletion,
                &mut *self.parts.operator,
                &rings,
                now,
                &mut StrictProofRng::new(),
            )
            .map_err(|_| inv("§11 certificate"))?;
            if let (Some(mut p), Some(g)) = (post, cert.group.as_ref()) {
                p.c_s = g.c_s_post;
                track.insert(*group, p);
            }
            let bytes = cert.to_bytes();
            let placement = Placement {
                group: *group,
                flush: None,
            };
            for r in self.log()?.stage_delete(lsn, &bytes, placement)? {
                draft.participant_records.push(r.encode());
            }
            draft.outputs.push((LOG_PARTICIPANT_ID, req, bytes));
        }
        // The chain ends where the change set says the groups end (§5.3).
        for gc in &cs.groups {
            let t = track.get(&gc.group).ok_or(inv("§5.3 certificate chain"))?;
            if t.s != gc.after.s
                || t.n != gc.after.n
                || t.c_s != encode_point(&gc.after.ext_public.0)
            {
                return Err(inv("§5.3 certificate chain"));
            }
        }
        Ok(())
    }
}

struct Track {
    s: Vec<i64>,
    r: Scalar,
    c_s: [u8; 32],
    n: u64,
}

impl TxnParticipant<CommitmentExtension> for LogParticipant {
    fn id(&self) -> u16 {
        LOG_PARTICIPANT_ID
    }

    fn owned_types(&self) -> &[RecordType] {
        &OWNED
    }

    fn pre_transaction(
        &mut self,
        kind: TxnKind,
        _c: &CollectionId,
    ) -> Result<Option<PreTxn>, Error> {
        lock(&self.0).pre(kind)
    }

    fn prepare(&mut self, draft: &mut TxnDraft<'_, CommitmentExtension>) -> Result<(), Error> {
        let mut g = lock(&self.0);
        match draft.kind {
            TxnKind::Insert => g.prepare_insert(draft),
            TxnKind::Delete => g.prepare_delete(draft),
            TxnKind::CreateCollection | TxnKind::DropCollection => Ok(()),
        }
    }

    fn sync_stores(&mut self) -> Result<(), Error> {
        lock(&self.0).log()?.sync()
    }

    fn abort(&mut self) {
        if let Some(log) = lock(&self.0).log.as_mut() {
            log.abort();
        }
    }

    fn after_commit(&mut self) -> Result<(), Error> {
        lock(&self.0).log()?.commit()
    }

    fn replay(&mut self, record: &WalRecord) -> Result<(), Error> {
        let mut g = lock(&self.0);
        match g.log.as_mut() {
            Some(log) => log.replay(record),
            None => {
                g.replayed.push(record.clone());
                Ok(())
            }
        }
    }

    fn recover(&mut self) -> Result<(), Error> {
        let mut g = lock(&self.0);
        if g.log.is_none() {
            // DB-79: the genesis checkpoint, signed at the creation time with epoch 0's key
            // (deterministic, so the same checkpoint at every open; written only when the log is
            // created, after the engine has created the database and its SECRETS).
            let genesis = Witnessed {
                checkpoint: LogCheckpoint::genesis(&mut *g.parts.operator)?,
                cosignatures: Vec::new(),
            };
            g.log = Some(LogStore::open(Arc::clone(&g.vfs), g.parts.store, &genesis)?);
        }
        let replayed = core::mem::take(&mut g.replayed);
        let log = g.log()?;
        for r in &replayed {
            log.replay(r)?;
        }
        log.recover()
    }

    fn check_invariants(&self) -> Result<(), Error> {
        lock(&self.0)
            .log
            .as_ref()
            .map_or(Ok(()), LogStore::check_invariants)
    }
}
