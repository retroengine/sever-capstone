//! P3-T4 (Build 3-4 §1.8 L8; overview EX-1, T-1 with certificates): Part 2's crash campaign on
//! the Part 3 engine. The oracle stream of `sever_refmodel_durable` runs on a main engine; for
//! every operation, the disks are forked and the operation is replayed with a crash at each of its
//! VFS operations (rotating `DropAll`, `KeepAll`, `Random`), at every 512-byte offset of sampled WAL
//! writes, at random points, and every n-th time during recovery too.
//!
//! After every crash the engine recovers (the full invariant check, INV-3 and INV-15 included,
//! runs at open), and:
//! - the recovered state's core digest must be one of the oracle's two allowed states (Part 2);
//! - **no orphaned leaf**: the log holds exactly the leaves of the state it recovered to;
//! - **no certificate for a rolled-back deletion**: no certificate beyond the log's size, and every
//!   delete leaf of the recovered log has its certificate, retrievable by its `database_lsn`, and
//!   it passes §11.3;
//! - the retry of the operation in flight behaves as §15.1 and §15.4 say (an insert is retried with
//!   the same credential).
//!
//! Writes one JSON line per crash point (`sever_refmodel_durable.oracle check` reads the states)
//! and a summary line with the Part 3 counts.

use std::cell::RefCell;
use std::io::Write;
use std::time::Instant;

use serde_json::json;
use sever_crashkit::campaign::Settings;
use sever_crashkit::oracle::{Oracle, OracleOp, hex};
use sever_crashkit::rows::Rows;
use sever_engine::{CollectionOptions, EngineConfig, InsertRequest};
use sever_p3::{Db, Deleted};
use sever_types::{CollectionId, Error};
use sever_vfs::rng::SplitMix64;
use sever_vfs::{CrashPolicy, FaultPlan};

use crate::check::accept;
use crate::core::core_digest;
use crate::world::{Cred, Disks, World};

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
    /// Wall-clock seconds.
    pub seconds: u64,
}

impl Summary {
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
                Ok(Some(c)) if accept(&db.anchors(), db.generators(), &c).is_ok() => {}
                _ => self.sum.bad_certificates += 1,
            }
        }
        for lsn in size..size + 4 {
            if !matches!(db.certificate(lsn), Ok(None)) {
                self.sum.rolled_back_certificates += 1;
            }
        }
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

    #[allow(clippy::too_many_arguments)]
    fn crash(
        &mut self,
        base: &Disks,
        cid: CollectionId,
        i: usize,
        k: u64,
        tear: usize,
        policy: CrashPolicy,
        kind: &str,
    ) -> Result<(), String> {
        let d = base.fork();
        {
            let db = self
                .world
                .open(&d)
                .map_err(|e| format!("op {i}: base did not open: {e}"))?;
            d.data.set_faults(FaultPlan {
                crash_at_op: Some(k),
                tear_bytes: tear,
                ..FaultPlan::default()
            });
            if self.exec(&db, cid, i).is_ok() {
                self.sum.skipped += 1;
                return Ok(());
            }
        }
        d.restart(policy);
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
        let (state, retry) = match self.world.open(&d) {
            Ok(db) => {
                let st = Self::digest(&db, cid, dim);
                let committed = st.as_ref() == self.oracle.digests.get(i + 1);
                let from = self.leaves.get(i).copied().unwrap_or(0);
                self.check_log(&db, if committed { i + 1 } else { i }, from);
                let retry = self.retry_ok(&db, cid, i, committed);
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

/// Runs the campaign on dimension `d`; one JSON line per crash point, then the summary line.
/// Operations before `crash_from` run on the main line only (smoke runs; the gate uses 0).
pub fn run(
    oracle: &Oracle,
    rows: &dyn Rows,
    artefact: &[u8],
    d: usize,
    s: &Settings,
    crash_from: usize,
    out: &mut dyn Write,
) -> Result<Summary, String> {
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
    };
    let main = Disks::new();
    let db = run.world.open(&main).map_err(|e| format!("create: {e}"))?;
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
    for i in 0..n {
        let base = main.fork();
        main.data.set_faults(FaultPlan::default());
        run.exec(&db, cid, i)
            .map_err(|e| format!("main line, op {i}: {e}"))?;
        let m = main.data.ops_since_plan();
        let writes = main.data.write_log();
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
                run.crash(&base, cid, i, k, 0, policy, "step")?;
            }
        }
        if offset_ops.binary_search(&i).is_ok() {
            let wal = |p: &Option<String>| p.as_deref().is_some_and(|p| p.starts_with("wal/"));
            for (k, (path, size)) in writes.iter().enumerate() {
                if !wal(path) {
                    continue;
                }
                for tear in (512..*size).step_by(512) {
                    run.crash(
                        &base,
                        cid,
                        i,
                        k as u64 + 1,
                        tear,
                        CrashPolicy::KeepAll,
                        "offset",
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
            run.crash(&base, cid, i, k, tear, policy, "random")?;
        }
    }
    // The main line's own certificates, all of them, at the end.
    let size = Run::size(&db).ok_or("log")?;
    let before = run.sum.bad_certificates;
    run.check_log(&db, n, 0);
    if run.sum.bad_certificates != before || Run::size(&db) != Some(size) {
        run.sum.main_mismatches += 1;
    }
    run.sum.seconds = t0.elapsed().as_secs();
    let sum = run.sum.clone();
    let line = json!({
        "t": "summary", "ops": sum.ops, "step": sum.step, "offset": sum.offset,
        "random": sum.random, "double": sum.double, "main_mismatches": sum.main_mismatches,
        "not_oracle_state": sum.not_oracle_state, "refusals": sum.refusals,
        "bad_retries": sum.bad_retries, "double_mismatches": sum.double_mismatches,
        "skipped": sum.skipped, "orphaned_leaves": sum.orphaned_leaves,
        "rolled_back_certificates": sum.rolled_back_certificates,
        "bad_certificates": sum.bad_certificates,
        "certificates_checked": sum.certificates_checked, "seconds": sum.seconds,
    });
    writeln!(run.out, "{line}").map_err(|e| e.to_string())?;
    Ok(sum)
}
