//! Contract suites for EP-6, EP-7 and EP-9 (Build §3.4, test level L7). Later parts run them
//! unchanged: Part 4's `AeadSealer` passes [`ep6_sealer_contract`], Parts 3 and 4's participants
//! pass [`ep7_participant_contract`].

use std::sync::Arc;

use sever_appendstore::{FileStore, StoreConfig};
use sever_format::Layout;
use sever_index::NoExtension;
use sever_types::{CollectionId, GroupId, ScrambledId};
use sever_vfs::{CrashPolicy, FaultPlan, SimVfs, Vfs};
use sever_wal::{Wal, WalConfig};

use crate::clock::Clock;
use crate::participant::{TxnDraft, TxnKind, TxnParticipant};
use crate::protocol::{Durable, commit};
use crate::sealer::{GroupOwner, RecordOwner, Sealer};

/// Why an implementation failed its contract.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ContractViolation {
    /// A call that must succeed failed.
    Failed(&'static str),
    /// Opened bytes differ from the sealed plaintext.
    RoundTrip(&'static str),
    /// A sealed value or envelope has a size other than the declared one.
    WrongSize(&'static str),
    /// An encrypting sealer opened a value under the wrong owner or version.
    OwnerNotBound,
    /// An encrypting sealer did not change the version on a departure (§13.3).
    NoRotation,
    /// The clock went backwards.
    ClockWentBack,
    /// After a crash and recovery, the participant's state is not the state of the acknowledged
    /// transactions (or of those plus the one in flight).
    StateNotRecovered,
    /// The participant's invariant check failed after recovery.
    InvariantFailed,
}

type Result = core::result::Result<(), ContractViolation>;

fn owner<'a>(c: &'a CollectionId, g: &'a GroupId, s: &'a ScrambledId) -> RecordOwner<'a> {
    RecordOwner {
        collection: c,
        group: g,
        scrambled_id: s,
    }
}

/// EP-6: every kind round-trips with exactly the declared overhead; a flush re-wrap opens under
/// the new owner; an encrypting sealer (`sealer_id ≠ 0`) binds owner and version and rotates on
/// a departure.
pub fn ep6_sealer_contract(s: &dyn Sealer) -> Result {
    let cid = CollectionId::from_bytes([3; 16]);
    let (g, h) = (GroupId::Spawned([1; 8]), GroupId::Holding);
    let (sid, other) = (
        ScrambledId::from_bytes([4; 64]),
        ScrambledId::from_bytes([5; 64]),
    );
    let fail = ContractViolation::Failed;
    for len in [0usize, 1, 100, Layout::plain(384).payload_len()] {
        let payload: Vec<u8> = (0..len).map(|i| (i * 7 % 251) as u8).collect();
        let (env, sealed) = s
            .seal_record(&owner(&cid, &h, &sid), &payload)
            .map_err(|_| fail("seal_record"))?;
        if env.len() != s.envelope_len() || sealed.len() != len + s.seal_overhead() {
            return Err(ContractViolation::WrongSize("record"));
        }
        let opened = s
            .open_record(&owner(&cid, &h, &sid), &env, &sealed)
            .map_err(|_| fail("open_record"))?;
        if *opened != payload {
            return Err(ContractViolation::RoundTrip("record"));
        }
        // A flush moves the record from the holding area into a group (§15.2 step 3).
        let moved = s
            .rewrap_record(&owner(&cid, &h, &sid), &owner(&cid, &g, &sid), &env)
            .map_err(|_| fail("rewrap_record"))?;
        if moved.len() != s.envelope_len() {
            return Err(ContractViolation::WrongSize("envelope"));
        }
        let opened = s
            .open_record(&owner(&cid, &g, &sid), &moved, &sealed)
            .map_err(|_| fail("open after rewrap"))?;
        if *opened != payload {
            return Err(ContractViolation::RoundTrip("rewrap"));
        }
        let text = b"passage text".repeat(len % 7 + 1);
        let sp = s
            .seal_passage(&owner(&cid, &g, &sid), &moved, &text)
            .map_err(|_| fail("seal_passage"))?;
        if sp.len() != text.len() + s.seal_overhead() {
            return Err(ContractViolation::WrongSize("passage"));
        }
        let op = s
            .open_passage(&owner(&cid, &g, &sid), &moved, &sp)
            .map_err(|_| fail("open_passage"))?;
        if *op != text {
            return Err(ContractViolation::RoundTrip("passage"));
        }
        if s.sealer_id() != 0
            && (s
                .open_record(&owner(&cid, &g, &other), &moved, &sealed)
                .is_ok()
                || s.open_record(&owner(&cid, &h, &sid), &moved, &sealed)
                    .is_ok())
        {
            return Err(ContractViolation::OwnerNotBound);
        }
    }
    let go = GroupOwner {
        collection: &cid,
        group: &g,
        n: 3,
    };
    let v0 = s.next_version(&go, None, false);
    let acc: Vec<u8> = (0..3_104u32).map(|i| (i % 256) as u8).collect();
    let sealed = s
        .seal_accumulator(&go, v0, &acc)
        .map_err(|_| fail("seal_accumulator"))?;
    if sealed.len() != acc.len() + s.seal_overhead() {
        return Err(ContractViolation::WrongSize("accumulator"));
    }
    let opened = s
        .open_accumulator(&go, v0, &sealed)
        .map_err(|_| fail("open_accumulator"))?;
    if *opened != acc {
        return Err(ContractViolation::RoundTrip("accumulator"));
    }
    if s.sealer_id() != 0 {
        let v1 = s.next_version(&go, Some(v0), true);
        if v1 <= v0 {
            return Err(ContractViolation::NoRotation);
        }
        let wrong_n = GroupOwner { n: 4, ..go };
        if s.open_accumulator(&wrong_n, v0, &sealed).is_ok()
            || s.open_accumulator(&go, v1, &sealed).is_ok()
        {
            return Err(ContractViolation::OwnerNotBound);
        }
    }
    Ok(())
}

/// EP-9: 10,000 reads never decrease.
pub fn ep9_clock_contract(c: &dyn Clock) -> Result {
    let mut last = c.now_ms();
    for _ in 0..10_000 {
        let t = c.now_ms();
        if t < last {
            return Err(ContractViolation::ClockWentBack);
        }
        last = t;
    }
    Ok(())
}

/// A participant with a state digest, for [`ep7_participant_contract`].
pub trait ProbedParticipant: TxnParticipant<NoExtension> {
    /// A digest of everything its state holds.
    fn digest(&self) -> Vec<u8>;
}

/// Builds a fresh participant over a data directory (it may keep durable files there).
pub type MakeParticipant<'a> = &'a dyn Fn(Arc<dyn Vfs>) -> Box<dyn ProbedParticipant>;

const TXNS: usize = 5;

fn store_cfg() -> StoreConfig {
    StoreConfig {
        dir: "payloads".into(),
        sealer_id: 0,
        segment_bytes: sever_appendstore::DEFAULT_SEGMENT_BYTES,
    }
}

/// Shares one participant between the protocol and the probe that reads its live digest.
struct Shared(Arc<std::sync::Mutex<Box<dyn ProbedParticipant>>>);

impl Shared {
    fn with<T>(&self, f: impl FnOnce(&mut Box<dyn ProbedParticipant>) -> T) -> T {
        f(&mut self.0.lock().unwrap_or_else(|p| p.into_inner()))
    }
}

impl TxnParticipant<NoExtension> for Shared {
    fn id(&self) -> u16 {
        self.with(|p| p.id())
    }
    fn pre_transaction(
        &mut self,
        kind: TxnKind,
        c: &CollectionId,
    ) -> core::result::Result<Option<crate::PreTxn>, sever_types::Error> {
        self.with(|p| p.pre_transaction(kind, c))
    }
    fn prepare(
        &mut self,
        d: &mut TxnDraft<'_, NoExtension>,
    ) -> core::result::Result<(), sever_types::Error> {
        self.with(|p| p.prepare(d))
    }
    fn sync_stores(&mut self) -> core::result::Result<(), sever_types::Error> {
        self.with(|p| p.sync_stores())
    }
    fn phase_a(&mut self) -> core::result::Result<(), sever_types::Error> {
        self.with(|p| p.phase_a())
    }
    fn abort(&mut self) {
        self.with(|p| p.abort());
    }
    fn after_commit(&mut self) -> core::result::Result<(), sever_types::Error> {
        self.with(|p| p.after_commit())
    }
}

/// Opens the database on `v` and runs up to `n` transactions through the protocol with one
/// fresh participant; returns its live digest before the first and after each acknowledged one.
fn drive(v: &SimVfs, make: MakeParticipant<'_>, n: usize) -> Vec<Vec<u8>> {
    let vfs: Arc<dyn Vfs> = Arc::new(v.clone());
    let shared = Arc::new(std::sync::Mutex::new(make(Arc::clone(&vfs))));
    let probe = Shared(Arc::clone(&shared));
    let mut digests = vec![probe.with(|p| p.digest())];
    let Ok((mut wal, _, _)) = Wal::recover(Arc::clone(&vfs), WalConfig::new(0), 1, 1) else {
        return digests;
    };
    let Ok(mut store) = FileStore::open(Arc::clone(&vfs), store_cfg()) else {
        return digests;
    };
    let mut ps: Vec<Box<dyn TxnParticipant<NoExtension>>> = vec![Box::new(Shared(shared))];
    for i in 0..n {
        let draft = TxnDraft::<NoExtension> {
            kind: if i % 2 == 0 {
                TxnKind::Insert
            } else {
                TxnKind::Delete
            },
            collection: CollectionId::from_bytes([1; 16]),
            changeset: None,
            records: Vec::new(),
            participant_records: Vec::new(),
            outputs: Vec::new(),
        };
        let r = commit(
            draft,
            &Layout::plain(8),
            &mut ps,
            Durable {
                wal: &mut wal,
                store: &mut store,
            },
            |_| {},
            &mut |_| {},
        );
        if r.is_err() {
            return digests;
        }
        digests.push(probe.with(|p| p.digest()));
    }
    digests
}

/// Recovers a participant from the disk: WAL replay of the records it owns, then `recover` and
/// the invariant check.
fn recovered(
    v: &SimVfs,
    make: MakeParticipant<'_>,
) -> core::result::Result<Box<dyn ProbedParticipant>, ContractViolation> {
    let vfs: Arc<dyn Vfs> = Arc::new(v.clone());
    let (_, txns, _) = Wal::recover(Arc::clone(&vfs), WalConfig::new(0), 1, 1)
        .map_err(|_| ContractViolation::Failed("WAL recovery"))?;
    let mut p = make(vfs);
    for r in txns.iter().flat_map(|t| &t.records) {
        if p.owns(r) {
            p.replay(r)
                .map_err(|_| ContractViolation::Failed("replay"))?;
        }
    }
    p.recover()
        .map_err(|_| ContractViolation::Failed("recover"))?;
    p.check_invariants()
        .map_err(|_| ContractViolation::InvariantFailed)?;
    Ok(p)
}

/// EP-7: across a crash at every VFS operation of five transactions, under three crash policies,
/// a participant recovered from the WAL (replay, then `recover`) has the state of the
/// acknowledged transactions, or of those plus the one in flight, and passes its invariant check.
pub fn ep7_participant_contract(make: MakeParticipant<'_>) -> Result {
    let base = SimVfs::new();
    let vfs: Arc<dyn Vfs> = Arc::new(base.clone());
    Wal::create(Arc::clone(&vfs), WalConfig::new(0), 1, 1)
        .map_err(|_| ContractViolation::Failed("create WAL"))?;
    FileStore::create(Arc::clone(&vfs), store_cfg())
        .map_err(|_| ContractViolation::Failed("create store"))?;
    // The live state after each acknowledged transaction of a run without faults; a clean
    // restart must recover the last one.
    let want = drive(&base.fork(), make, TXNS);
    if want.len() != TXNS + 1 {
        return Err(ContractViolation::Failed("transaction"));
    }
    let clean = base.fork();
    drive(&clean, make, TXNS);
    clean.restart(CrashPolicy::DropAll);
    if want.last() != Some(&recovered(&clean, make)?.digest()) {
        return Err(ContractViolation::StateNotRecovered);
    }
    let dry = base.fork();
    dry.set_faults(FaultPlan::default());
    drive(&dry, make, TXNS);
    for k in 1..=dry.ops_since_plan() {
        for policy in [
            CrashPolicy::DropAll,
            CrashPolicy::KeepAll,
            CrashPolicy::Random(k),
        ] {
            let v = base.fork();
            v.set_faults(FaultPlan {
                crash_at_op: Some(k),
                tear_bytes: 5,
                ..FaultPlan::default()
            });
            let acked = drive(&v, make, TXNS).len() - 1;
            v.restart(policy);
            let got = recovered(&v, make)?.digest();
            let ok = want.get(acked) == Some(&got)
                || (acked < TXNS && want.get(acked + 1) == Some(&got));
            if !ok {
                return Err(ContractViolation::StateNotRecovered);
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests;
