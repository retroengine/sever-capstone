//! P4-T3 and P4-T4 (Build 3-4 §2.8 L8; overview EX-1, T-1 on the final build): Part 3's crash
//! campaign on the final engine, with every participant, and with crash points on **both** disks
//! (phases A and C of a deletion write the key file, §13.4). The oracle stream of
//! `sever_refmodel_durable` runs on a main engine; for every operation, the disks are forked and
//! the operation is replayed with a crash at each mutating VFS operation of either disk (rotating
//! `DropAll`, `KeepAll`, `Random`), at every 512-byte offset of sampled WAL writes, at torn writes
//! of the key file's slots (`keytear`, §15.4 row 4), at random points, and every n-th time during
//! recovery too.
//!
//! After every crash the engine recovers (the full invariant check, INV-3, INV-14 and INV-15
//! included, runs at open), and Part 3's checks hold (the oracle's allowed states, no orphaned
//! leaf, no certificate for a rolled-back deletion, every certificate passes §11.3, the retry
//! behaves), and Part 4's:
//! - **no stale key slot**: every domain of the key file has exactly one valid slot, at the
//!   version the recovered key ring holds, and no slot names a domain the ring does not hold;
//! - **every live record readable**: the passages of the operation's records, where live, open.
//!
//! At the end, **active-key losses**: the active slot of sampled domains is zeroed or torn on a
//! copy of the final disks, and the engine must refuse to start every time (INV-14).
//!
//! Writes one JSON line per crash point and a summary line.

use std::cell::RefCell;
use std::collections::HashSet;
use std::io::Write;
use std::sync::Arc;
use std::time::Instant;

use serde_json::json;
use sever_crashkit::campaign::Settings;
use sever_crashkit::oracle::{Oracle, OracleOp, hex};
use sever_crashkit::rows::Rows;
use sever_db::{Db, Deleted};
use sever_engine::{CollectionOptions, EngineConfig, InsertRequest};
use sever_keys::file::{HEADER_BYTES, KeyFile, PAIR_BYTES, SLOT_BYTES, SlotState};
use sever_types::{CollectionId, Error};
use sever_vfs::rng::SplitMix64;
use sever_vfs::{CrashPolicy, FaultPlan, Vfs};
use sha2::{Digest, Sha256};

use crate::check::accept;
use crate::core::core_digest;
use crate::snap::{Disk, Point, SnapVfs, listing};
use crate::world::{Cred, Disks, World};

/// Domains whose active key is lost at the end, twice each (zeroed, then torn): P4-T3's
/// "refusal to start in 100 % of injected active-key losses".
pub const KEY_LOSSES: usize = 50;

/// What the campaign saw.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Summary {
    /// Operations of the stream.
    pub ops: u64,
    /// Crash points by kind.
    pub step: u64,
    /// See above.
    pub offset: u64,
    /// See above.
    pub random: u64,
    /// Of which also crashed during recovery.
    pub double: u64,
    /// Main-line states that differ from the oracle.
    pub main_mismatches: u64,
    /// Recovered states that are neither allowed state.
    pub not_oracle_state: u64,
    /// Recoveries that refused to start.
    pub refusals: u64,
    /// Retries that did not behave as §15.1 and §15.4 say.
    pub bad_retries: u64,
    /// Double crashes that recovered to another state.
    pub double_mismatches: u64,
    /// Crash points a replay never reached.
    pub skipped: u64,
    /// Recovered logs whose size is not the recovered state's (orphaned or lost leaves).
    pub orphaned_leaves: u64,
    /// Certificates present for a deletion the recovery rolled back.
    pub rolled_back_certificates: u64,
    /// Delete leaves without a retrievable certificate, or certificates failing §11.3.
    pub bad_certificates: u64,
    /// Certificates checked.
    pub certificates_checked: u64,
    /// `--method compare`: points where the snapshot and the replay of the operation gave
    /// different files, lengths, recovered states or logs.
    pub method_mismatches: u64,
    /// Crash points made both ways and compared (`--method compare`, `--compare-every`).
    pub compared: u64,
    /// Torn writes of key-file slots (§15.4 row 4).
    pub keytear: u64,
    /// Recoveries after which a domain has no, or more than one, valid key slot, a slot whose
    /// version is not the ring's, or a slot of a domain the ring does not hold.
    pub stale_key_slots: u64,
    /// Live records whose passage did not open after a recovery.
    pub unreadable_records: u64,
    /// Active-key losses injected at the end (zeroed or torn active slots).
    pub key_loss_injected: u64,
    /// Of which the engine refused to start (INV-14).
    pub key_loss_refused: u64,
    /// Wall-clock seconds.
    pub seconds: u64,
}

/// The summary's fields by name, in the order of the summary line.
macro_rules! summary_fields {
    ($m:ident) => {
        $m!(
            ops,
            step,
            offset,
            random,
            double,
            main_mismatches,
            not_oracle_state,
            refusals,
            bad_retries,
            double_mismatches,
            skipped,
            orphaned_leaves,
            rolled_back_certificates,
            bad_certificates,
            certificates_checked,
            method_mismatches,
            compared,
            keytear,
            stale_key_slots,
            unreadable_records,
            key_loss_injected,
            key_loss_refused,
            seconds
        )
    };
}

impl Summary {
    /// Every field by name (the summary line, and the saved progress).
    pub fn to_json(&self) -> serde_json::Map<String, serde_json::Value> {
        let mut m = serde_json::Map::new();
        macro_rules! put {
            ($($f:ident),*) => { $( m.insert(stringify!($f).into(), self.$f.into()); )* };
        }
        summary_fields!(put);
        m
    }

    /// Parses [`Summary::to_json`]; every field must be present.
    pub fn from_json(v: &serde_json::Value) -> Option<Self> {
        let u = |k: &str| v.get(k).and_then(serde_json::Value::as_u64);
        macro_rules! get {
            ($($f:ident),*) => { Some(Self { $( $f: u(stringify!($f))?, )* }) };
        }
        summary_fields!(get)
    }

    /// Every failure count.
    pub fn failures(&self) -> u64 {
        self.main_mismatches
            + self.not_oracle_state
            + self.refusals
            + self.bad_retries
            + self.double_mismatches
            + self.orphaned_leaves
            + self.rolled_back_certificates
            + self.bad_certificates
            + self.method_mismatches
            + self.stale_key_slots
            + self.unreadable_records
            + (self.key_loss_injected - self.key_loss_refused.min(self.key_loss_injected))
    }
}

/// How a crash point's disks are made (DB-88).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Method {
    /// From the main line's snapshot before the crashing operation (a torn write: by replay).
    Snapshot,
    /// Reopen the disks before the operation and run it with a crash at its `k`-th operation.
    Replay,
    /// Both, reporting the replay's result and counting every difference.
    Compare,
}

impl Method {
    /// `snapshot`, `replay` or `compare`.
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "snapshot" => Some(Self::Snapshot),
            "replay" => Some(Self::Replay),
            "compare" => Some(Self::Compare),
            _ => None,
        }
    }
}

fn policy_name(p: CrashPolicy) -> String {
    match p {
        CrashPolicy::DropAll => "drop".into(),
        CrashPolicy::KeepAll => "keep".into(),
        CrashPolicy::Random(s) => format!("random:{s}"),
    }
}

struct Run<'a> {
    world: World,
    oracle: &'a Oracle,
    rows: &'a dyn Rows,
    s: &'a Settings,
    out: &'a mut dyn Write,
    sum: Summary,
    rng: SplitMix64,
    points: u64,
    /// One credential per insert, reused by the main line, every replay and every retry.
    creds: RefCell<Vec<Option<Cred>>>,
    /// Leaves after the first `i` operations on the main line.
    leaves: Vec<u64>,
    /// Seconds per phase of a crash point (`SEVER_KIT_TIMING`): base open, the crashing
    /// operation, the recovery, the log check, the retry.
    phases: [f64; 5],
    method: Method,
    /// With [`Method::Snapshot`]: every n-th operation's points are made both ways (0: none).
    compare_every: usize,
    /// Certificates (with their anchors) that passed §11.3 in this run.
    accepted: RefCell<HashSet<[u8; 32]>>,
    /// The current operation's mutating VFS operations, in order: disk and index on it.
    seq: Vec<(Disk, u64)>,
}

enum Done {
    Insert,
    Deletes(Vec<Deleted>),
}

impl Run<'_> {
    fn cred(&self, cid: CollectionId, i: usize, row: usize) -> Result<Cred, Error> {
        if let Some(Some(c)) = self.creds.borrow().get(i) {
            return Ok(*c);
        }
        let v = self.rows.row(row).map_err(|_| Error::WrongDimension)?;
        let c = self.world.credential(cid, &v)?;
        let mut all = self.creds.borrow_mut();
        if all.len() <= i {
            all.resize(i + 1, None);
        }
        if let Some(slot) = all.get_mut(i) {
            *slot = Some(c);
        }
        Ok(c)
    }

    fn exec(&self, db: &Db, cid: CollectionId, i: usize) -> Result<Done, Error> {
        match self.oracle.ops.get(i).ok_or(Error::UnknownCollection)? {
            OracleOp::Insert { id, row } => {
                let vector = self.rows.row(*row).map_err(|_| Error::WrongDimension)?;
                let cred = self.cred(cid, i, *row)?;
                db.insert(
                    cid,
                    InsertRequest {
                        record_id: id.clone(),
                        vector,
                        credential: cred.credential(),
                        passage: Some(format!("passage {id}").into_bytes()),
                    },
                )
                .map(|_| Done::Insert)
            }
            OracleOp::DeleteUser(ids) => {
                let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
                db.delete_user(cid, &refs).map(Done::Deletes)
            }
            OracleOp::Delete(id) => db.delete(cid, id).map(|o| Done::Deletes(vec![o])),
        }
    }

    fn digest(db: &Db, cid: CollectionId, d: usize) -> Option<[u8; 32]> {
        db.engine
            .canonical_state(cid)
            .ok()
            .and_then(|s| core_digest(&s, d))
    }

    fn size(db: &Db) -> Option<u64> {
        db.log.with(|l| l.tree().size())
    }

    /// The log after a recovery to the state after `ops` operations: its size is the main
    /// line's, every delete leaf from `from` on has a certificate that passes §11.3, and nothing
    /// lies beyond the log.
    fn check_log(&mut self, db: &Db, ops: usize, from: u64) {
        let want = self.leaves.get(ops).copied();
        let size = Self::size(db);
        if size != want {
            self.sum.orphaned_leaves += 1;
        }
        let Some(size) = size else { return };
        for lsn in from..size {
            let is_delete = db
                .log
                .with(|l| l.insert_leaf(lsn))
                .is_some_and(|r| matches!(r, Ok(None)));
            if !is_delete {
                continue;
            }
            self.sum.certificates_checked += 1;
            match db.certificate(lsn) {
                Ok(Some(c)) if self.accepts(db, &c) => {}
                _ => self.sum.bad_certificates += 1,
            }
        }
        for lsn in size..size + 4 {
            if !matches!(db.certificate(lsn), Ok(None)) {
                self.sum.rolled_back_certificates += 1;
            }
        }
    }

    /// §11.3 on `cert`. The check is a pure function of the anchors and the bytes, and a point
    /// that recovers to the committed state holds the main line's own certificate, so a verdict
    /// is remembered by the SHA-256 of both (DB-88); only acceptances are remembered.
    fn accepts(&self, db: &Db, cert: &[u8]) -> bool {
        let a = db.anchors();
        let mut h = Sha256::new();
        h.update(format!("{a:?}").as_bytes());
        h.update(cert);
        let key: [u8; 32] = h.finalize().into();
        if self.accepted.borrow().contains(&key) {
            return true;
        }
        let ok = accept(&a, db.generators(), cert).is_ok();
        if ok {
            self.accepted.borrow_mut().insert(key);
        }
        ok
    }

    /// §15.1, §15.4: the retry of operation `i` after a recovery.
    fn retry_ok(&self, db: &Db, cid: CollectionId, i: usize, committed: bool) -> bool {
        let Some(op) = self.oracle.ops.get(i) else {
            return false;
        };
        let r = self.exec(db, cid, i);
        let behaved = match (op, &r, committed) {
            (OracleOp::Insert { .. }, Ok(_), false) => true,
            (
                OracleOp::Insert { .. },
                Err(Error::DuplicateRecord {
                    same_commitment: true,
                }),
                true,
            ) => true,
            (OracleOp::Insert { .. }, _, _) => false,
            (_, Ok(Done::Deletes(outs)), true) => outs.iter().all(|o| *o == Deleted::AlreadyAbsent),
            (_, Ok(Done::Deletes(outs)), false) => {
                outs.iter().any(|o| *o != Deleted::AlreadyAbsent)
            }
            _ => false,
        };
        behaved
            && Self::digest(db, cid, self.world.d()).as_ref() == self.oracle.digests.get(i + 1)
            && Self::size(db) == self.leaves.get(i + 1).copied()
    }

    /// No stale key slot after a recovery: the key file (read back on a copy of the key disk)
    /// holds exactly one valid slot per domain of the recovered ring, at the ring's version.
    fn check_keys(&mut self, db: &Db, d: &Disks) {
        let Ok((_, all)) = KeyFile::open(Arc::new(d.keys.fork()), sever_erasure::KEYS_PATH) else {
            self.sum.stale_key_slots += 1;
            return;
        };
        let mut held: std::collections::BTreeMap<sever_keys::Domain, Vec<u64>> =
            std::collections::BTreeMap::new();
        for two in all {
            for s in two {
                if let SlotState::Valid(r) = s {
                    held.entry(r.domain).or_default().push(r.key_version);
                }
            }
        }
        let ring = db.key_ring().active_versions();
        let same = held.len() == ring.len()
            && ring
                .iter()
                .all(|(dom, v)| held.get(dom).map(Vec::as_slice) == Some(&[*v][..]));
        if !same {
            self.sum.stale_key_slots += 1;
        }
    }

    /// Every live record of operation `i` still opens (its passage, through its record key).
    fn check_readable(&mut self, db: &Db, cid: CollectionId, i: usize) {
        let ids: Vec<&str> = match self.oracle.ops.get(i) {
            Some(OracleOp::Insert { id, .. }) | Some(OracleOp::Delete(id)) => vec![id.as_str()],
            Some(OracleOp::DeleteUser(ids)) => ids.iter().map(String::as_str).collect(),
            None => vec![],
        };
        for id in ids {
            if db.engine.passage(cid, id).is_err() {
                self.sum.unreadable_records += 1;
            }
        }
    }

    /// The old way: the disks before operation `i`, reopened, and the operation run with a crash
    /// during its `k`-th mutating VFS operation; `None` if it completed.
    fn replay_point(
        &mut self,
        base: &Disks,
        cid: CollectionId,
        i: usize,
        k: u64,
        tear: usize,
    ) -> Result<Option<Disks>, String> {
        let d = base.fork();
        let t = Instant::now();
        let db = self
            .world
            .open(&d)
            .map_err(|e| format!("op {i}: base did not open: {e}"))?;
        self.phases[0] += t.elapsed().as_secs_f64();
        let t = Instant::now();
        let (disk, local) = usize::try_from(k)
            .ok()
            .and_then(|k| k.checked_sub(1))
            .and_then(|k| self.seq.get(k))
            .copied()
            .unwrap_or((Disk::Data, k));
        let plan = FaultPlan {
            crash_at_op: Some(local),
            tear_bytes: tear,
            ..FaultPlan::default()
        };
        match disk {
            Disk::Data => d.data.set_faults(plan),
            Disk::Keys => d.keys.set_faults(plan),
        }
        let ran = self.exec(&db, cid, i);
        self.phases[1] += t.elapsed().as_secs_f64();
        Ok(if ran.is_ok() { None } else { Some(d) })
    }

    /// One crash point: operation `i` with a crash during its `k`-th mutating VFS operation.
    /// `pre` is the main line's snapshot before that operation, `torn` whether the operation is a
    /// write that `tear` bytes of would reach the page cache.
    #[allow(clippy::too_many_arguments)]
    fn crash(
        &mut self,
        base: &Disks,
        pre: Option<&Disks>,
        cid: CollectionId,
        i: usize,
        k: u64,
        tear: usize,
        torn: bool,
        policy: CrashPolicy,
        kind: &str,
    ) -> Result<(), String> {
        let snap = pre.filter(|_| tear == 0 || !torn);
        let method = match self.method {
            Method::Snapshot if self.compare_every > 0 && i % self.compare_every == 0 => {
                Method::Compare
            }
            m => m,
        };
        let (d, twin) = match (snap, method) {
            (Some(p), Method::Snapshot) => (p.fork(), None),
            (p, m) => {
                let Some(d) = self.replay_point(base, cid, i, k, tear)? else {
                    self.sum.skipped += 1;
                    if p.is_some() && m == Method::Compare {
                        self.sum.method_mismatches += 1;
                    }
                    return Ok(());
                };
                (d, p.filter(|_| m == Method::Compare).map(Disks::fork))
            }
        };
        d.restart(policy);
        if let Some(t) = &twin {
            self.sum.compared += 1;
            t.restart(policy);
            if listing(&t.data) != listing(&d.data) || listing(&t.keys) != listing(&d.keys) {
                self.sum.method_mismatches += 1;
            }
        }
        self.points += 1;
        let dim = self.world.d();
        let double_now = self.s.double_every > 0 && self.points % self.s.double_every == 0;
        let double = if double_now {
            let d2 = d.fork();
            d2.data.set_faults(FaultPlan {
                crash_at_op: Some(1 + self.rng.below(4)),
                ..FaultPlan::default()
            });
            drop(self.world.open(&d2));
            d2.restart(CrashPolicy::Random(self.rng.next_u64()));
            self.sum.double += 1;
            Some(
                self.world
                    .open(&d2)
                    .ok()
                    .and_then(|db| Self::digest(&db, cid, dim)),
            )
        } else {
            None
        };
        let t = Instant::now();
        if let Some(t) = &twin {
            let other = self
                .world
                .open(t)
                .ok()
                .map(|db| (Self::digest(&db, cid, dim), Self::size(&db)));
            let this = self
                .world
                .open(&d.fork())
                .ok()
                .map(|db| (Self::digest(&db, cid, dim), Self::size(&db)));
            if other != this {
                self.sum.method_mismatches += 1;
            }
        }
        let (state, retry) = match self.world.open(&d) {
            Ok(db) => {
                self.phases[2] += t.elapsed().as_secs_f64();
                let t = Instant::now();
                let st = Self::digest(&db, cid, dim);
                let committed = st.as_ref() == self.oracle.digests.get(i + 1);
                let from = self.leaves.get(i).copied().unwrap_or(0);
                self.check_log(&db, if committed { i + 1 } else { i }, from);
                self.phases[3] += t.elapsed().as_secs_f64();
                self.check_keys(&db, &d);
                self.check_readable(&db, cid, i);
                let t = Instant::now();
                let retry = self.retry_ok(&db, cid, i, committed);
                self.phases[4] += t.elapsed().as_secs_f64();
                (st, retry)
            }
            Err(_) => (None, false),
        };
        let allowed = |s: &[u8; 32]| {
            self.oracle.digests.get(i) == Some(s) || self.oracle.digests.get(i + 1) == Some(s)
        };
        match &state {
            None => self.sum.refusals += 1,
            Some(s) if !allowed(s) => self.sum.not_oracle_state += 1,
            Some(_) => {}
        }
        if state.is_some() && !retry {
            self.sum.bad_retries += 1;
        }
        if let Some(dbl) = &double {
            if *dbl != state {
                self.sum.double_mismatches += 1;
            }
        }
        match kind {
            "step" => self.sum.step += 1,
            "offset" => self.sum.offset += 1,
            "keytear" => self.sum.keytear += 1,
            _ => self.sum.random += 1,
        }
        let line = json!({
            "t": "crash", "kind": kind, "op": i, "k": k, "tear": tear,
            "policy": policy_name(policy), "acked": i,
            "state": state.map(|s| hex(&s)),
            "retry": if retry { "ok" } else { "bad" },
            "double": double.map(|o| o.map(|s| hex(&s))),
        });
        writeln!(self.out, "{line}").map_err(|e| e.to_string())
    }
}

/// Which crash points are made, and how (beside Part 2's [`Settings`]).
#[derive(Clone, Copy, Debug)]
pub struct Points {
    /// Operations before this one run on the main line only (smoke runs; the gate uses 0).
    pub crash_from: usize,
    /// How each point's disks are made.
    pub method: Method,
    /// With [`Method::Snapshot`]: every n-th operation's points are made both ways (0: none).
    pub compare_every: usize,
}

/// Where a campaign stands after a whole operation: enough to continue it in a new process with
/// the same results as an uninterrupted run (as Part 2's `sever_crashkit::campaign::Progress`; the
/// results file is cut back to the same point). A resumed main line draws new `r_t` from the OS,
/// which changes no result line: states are compared in the core form, without `C_S ‖ r_agg`.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Progress {
    /// Operations whose crash points are all written.
    pub done: usize,
    /// The step-policy rotation counter.
    pub rotate: u64,
    /// Crash points so far (drives the double-crash choice).
    pub points: u64,
    /// The campaign generator's state.
    pub rng: u64,
    /// The summary so far (`seconds` includes earlier attempts).
    pub sum: Summary,
}

impl Progress {
    /// One JSON object.
    pub fn to_json(&self) -> serde_json::Value {
        json!({"done": self.done, "rotate": self.rotate, "points": self.points, "rng": self.rng,
            "sum": self.sum.to_json()})
    }

    /// Parses [`Progress::to_json`].
    pub fn from_json(v: &serde_json::Value) -> Option<Self> {
        let u = |k: &str| v.get(k).and_then(serde_json::Value::as_u64);
        Some(Self {
            done: usize::try_from(u("done")?).ok()?,
            rotate: u("rotate")?,
            points: u("points")?,
            rng: u("rng")?,
            sum: Summary::from_json(v.get("sum")?)?,
        })
    }
}

/// Continuing from saved progress, and saving it as the campaign goes.
pub struct Checkpointing<'a> {
    /// The progress to continue from (`None`: a fresh run).
    pub from: Option<Progress>,
    /// How often to save.
    pub every: std::time::Duration,
    /// Called with the progress and `out`, so it can flush and sync `out` first.
    pub save: &'a mut dyn FnMut(&Progress, &mut dyn Write) -> Result<(), String>,
}

/// How often the campaign saves its progress.
pub const PROGRESS_EVERY: std::time::Duration = std::time::Duration::from_secs(30);

/// Runs the campaign; one JSON line per crash point, then the summary line.
pub fn run(
    oracle: &Oracle,
    rows: &dyn Rows,
    artefact: &[u8],
    s: &Settings,
    points: Points,
    out: &mut dyn Write,
    ck: Checkpointing<'_>,
) -> Result<Summary, String> {
    let Points {
        crash_from,
        method,
        compare_every,
    } = points;
    let Checkpointing {
        from: resume,
        every,
        save,
    } = ck;
    let d = sever_partition::PartitionArtefact::parse(artefact)
        .map_err(|e| format!("artefact: {e}"))?
        .d;
    let t0 = Instant::now();
    let cfg = EngineConfig {
        wal_segment_bytes: s.wal_segment,
        store_segment_bytes: s.store_segment,
        checkpoint_every_wal_bytes: s.checkpoint_every,
        ..EngineConfig::default()
    };
    let mut run = Run {
        world: World::new(d, cfg, s.store_segment)?,
        oracle,
        rows,
        s,
        out,
        sum: Summary::default(),
        rng: SplitMix64::new(s.seed),
        points: 0,
        creds: RefCell::new(Vec::new()),
        leaves: vec![0],
        phases: [0.0; 5],
        method,
        compare_every,
        accepted: RefCell::new(HashSet::new()),
        seq: Vec::new(),
    };
    let main = Disks::new();
    let snapper = SnapVfs::new(&main);
    let db = run
        .world
        .open_vfs(Arc::new(snapper.clone()), Arc::new(snapper.keys()))
        .map_err(|e| format!("create: {e}"))?;
    let cid = db
        .create_collection(
            artefact,
            CollectionOptions {
                spawn_target: s.spawn_target,
                spawning_enabled: true,
                store_passages: true,
            },
        )
        .map_err(|e| format!("create_collection: {e}"))?;
    if Run::digest(&db, cid, d).as_ref() != oracle.digests.first() {
        return Err("the empty collection differs from the oracle's initial state".into());
    }
    let n = s
        .limit_ops
        .unwrap_or(oracle.ops.len())
        .min(oracle.ops.len());
    let mut offset_ops: Vec<usize> = (0..s.offset_samples)
        .map(|_| run.rng.below(n as u64) as usize)
        .collect();
    offset_ops.sort_unstable();
    offset_ops.dedup();
    let mut random: Vec<(usize, u64, usize, u64)> = (0..s.random_points)
        .map(|_| {
            (
                run.rng.below(n as u64) as usize,
                run.rng.next_u64(),
                run.rng.below(8_192) as usize,
                run.rng.next_u64(),
            )
        })
        .collect();
    random.sort_unstable();
    let mut rotate = 0u64;
    let mut done = 0;
    let mut earlier_seconds = 0;
    if let Some(p) = resume {
        // Every seeded choice above was drawn again identically; restore what came after.
        done = p.done;
        rotate = p.rotate;
        run.points = p.points;
        run.rng = SplitMix64::new(p.rng);
        earlier_seconds = p.sum.seconds;
        run.sum = p.sum;
    }
    let mut last_save = Instant::now();
    for i in 0..n {
        if i < done {
            // Already done: only rebuild the main line's state and log (no crash points, no
            // counts).
            run.exec(&db, cid, i)
                .map_err(|e| format!("main line (resume), op {i}: {e}"))?;
            run.leaves.push(Run::size(&db).ok_or("log")?);
            continue;
        }
        let base = main.fork();
        main.data.set_faults(FaultPlan::default());
        main.keys.set_faults(FaultPlan::default());
        let snapping = i >= crash_from && method != Method::Replay;
        snapper.record(i >= crash_from, snapping);
        run.exec(&db, cid, i)
            .map_err(|e| format!("main line, op {i}: {e}"))?;
        let m = main.data.ops_since_plan() + main.keys.ops_since_plan();
        let writes = main.data.write_log();
        let kwrites = main.keys.write_log();
        let snaps: Vec<Point> = snapper.take();
        snapper.record(false, false);
        if i >= crash_from && snaps.len() as u64 != m {
            return Err(format!(
                "op {i}: {} recorded operations for {m} operations",
                snaps.len()
            ));
        }
        run.seq = snaps.iter().map(|p| (p.disk, p.local)).collect();
        let point = |k: u64| snaps.get(usize::try_from(k).ok()?.checked_sub(1)?);
        let pre = |k: u64| point(k).and_then(|p| p.disks.as_ref());
        let write_of = |k: u64| {
            point(k).and_then(|p| {
                let log = match p.disk {
                    Disk::Data => &writes,
                    Disk::Keys => &kwrites,
                };
                usize::try_from(p.local)
                    .ok()?
                    .checked_sub(1)
                    .and_then(|j| log.get(j))
            })
        };
        let torn = |k: u64| write_of(k).is_some_and(|w| w.1 > 0);
        run.sum.ops += 1;
        run.leaves.push(Run::size(&db).ok_or("log")?);
        if Run::digest(&db, cid, d).as_ref() != oracle.digests.get(i + 1) {
            run.sum.main_mismatches += 1;
        }
        if i < crash_from {
            continue;
        }
        if i % s.step_every.max(1) == 0 {
            for k in 1..=m {
                rotate += 1;
                let policy = match rotate % 3 {
                    0 => CrashPolicy::DropAll,
                    1 => CrashPolicy::KeepAll,
                    _ => CrashPolicy::Random(s.seed ^ rotate),
                };
                run.crash(&base, pre(k), cid, i, k, 0, torn(k), policy, "step")?;
            }
        }
        if offset_ops.binary_search(&i).is_ok() {
            let wal = |p: &Option<String>| p.as_deref().is_some_and(|p| p.starts_with("wal/"));
            for k in 1..=m {
                let Some((path, size)) =
                    write_of(k).filter(|_| point(k).is_some_and(|p| p.disk == Disk::Data))
                else {
                    continue;
                };
                if !wal(path) {
                    continue;
                }
                for tear in (512..*size).step_by(512) {
                    let (p, t) = (pre(k), torn(k));
                    run.crash(&base, p, cid, i, k, tear, t, CrashPolicy::KeepAll, "offset")?;
                }
            }
        }
        // §15.4 row 4: torn writes of the key file's slots (a slot is one 512-byte write).
        for k in 1..=m {
            let slot_write = point(k).is_some_and(|p| p.disk == Disk::Keys)
                && write_of(k).is_some_and(|w| w.1 == SLOT_BYTES);
            if slot_write {
                for tear in [1, 100, 256, 511] {
                    run.crash(
                        &base,
                        None,
                        cid,
                        i,
                        k,
                        tear,
                        true,
                        CrashPolicy::KeepAll,
                        "keytear",
                    )?;
                }
            }
        }
        for &(_, u, tear, p) in random.iter().filter(|r| r.0 == i) {
            let k = 1 + u % m.max(1);
            let policy = match p % 3 {
                0 => CrashPolicy::DropAll,
                1 => CrashPolicy::KeepAll,
                _ => CrashPolicy::Random(p),
            };
            run.crash(&base, pre(k), cid, i, k, tear, torn(k), policy, "random")?;
        }
        if last_save.elapsed() >= every {
            let mut sum = run.sum.clone();
            sum.seconds = earlier_seconds + t0.elapsed().as_secs();
            let p = Progress {
                done: i + 1,
                rotate,
                points: run.points,
                rng: run.rng.state(),
                sum,
            };
            save(&p, run.out)?;
            last_save = Instant::now();
        }
    }
    // Active-key losses (INV-14): on copies of the final disks, zero or tear the active slot of
    // sampled domains; the engine must refuse to start every time.
    drop(db);
    let ring_db = run
        .world
        .open(&main.fork())
        .map_err(|e| format!("final reopen: {e}"))?;
    let (_, slots) = KeyFile::open(Arc::new(main.keys.fork()), sever_erasure::KEYS_PATH)
        .map_err(|e| format!("KEYS: {e}"))?;
    let active = ring_db.key_ring().active_versions();
    drop(ring_db);
    let mut victims: Vec<(u64, u8)> = Vec::new();
    for (pair, two) in (0u64..).zip(&slots) {
        for (slot, st) in (0u8..).zip(two) {
            if let SlotState::Valid(r) = st {
                if active.get(&r.domain) == Some(&r.key_version) {
                    victims.push((pair, slot));
                }
            }
        }
    }
    let stride = (victims.len() / KEY_LOSSES.max(1)).max(1);
    for (pair, slot) in victims.iter().step_by(stride).take(KEY_LOSSES) {
        for zero in [true, false] {
            let t = main.fork();
            let at = HEADER_BYTES as u64
                + pair * PAIR_BYTES as u64
                + u64::from(*slot) * SLOT_BYTES as u64;
            let mut f = t
                .keys
                .open(sever_erasure::KEYS_PATH, sever_vfs::OpenMode::Existing)
                .map_err(|e| format!("KEYS: {e:?}"))?;
            let bytes = if zero {
                vec![0u8; SLOT_BYTES]
            } else {
                vec![0xA5u8; 8]
            };
            f.write_at(at + if zero { 0 } else { 100 }, &bytes)
                .and_then(|()| f.fsync())
                .map_err(|e| format!("KEYS: {e:?}"))?;
            drop(f);
            run.sum.key_loss_injected += 1;
            if run.world.open(&t).is_err() {
                run.sum.key_loss_refused += 1;
            }
        }
    }
    let db = run
        .world
        .open(&main.fork())
        .map_err(|e| format!("final reopen: {e}"))?;
    // The main line's own certificates, all of them, at the end.
    let size = Run::size(&db).ok_or("log")?;
    let before = run.sum.bad_certificates;
    run.check_log(&db, n, 0);
    if run.sum.bad_certificates != before || Run::size(&db) != Some(size) {
        run.sum.main_mismatches += 1;
    }
    run.sum.seconds = earlier_seconds + t0.elapsed().as_secs();
    if std::env::var_os("SEVER_KIT_TIMING").is_some() {
        let [a, b, c, e, f] = run.phases;
        eprintln!(
            "timing: base open {a:.1} s, crashing op {b:.1} s, recovery {c:.1} s, log check {e:.1} s, retry {f:.1} s"
        );
    }
    let sum = run.sum.clone();
    let mut line = sum.to_json();
    line.insert("t".into(), "summary".into());
    writeln!(run.out, "{}", serde_json::Value::Object(line)).map_err(|e| e.to_string())?;
    Ok(sum)
}
