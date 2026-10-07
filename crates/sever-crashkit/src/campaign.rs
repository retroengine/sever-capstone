//! The index-record crash campaign (Build §5.7 L10 step 2–3; overview EX-1).
//!
//! The stream runs on a "main" engine. Before each operation the simulated disks are forked; the
//! operation runs on main while the fork records how many VFS operations it performs. Then, from
//! the fork, the campaign replays the operation with a crash at each of those points:
//!
//! - **step**: every VFS operation of every operation (each protocol step boundary of Build §5.4
//!   lies between two of them), each with one crash policy, rotating `DropAll`, `KeepAll`,
//!   `Random(seed)`;
//! - **offset**: for a seeded sample of operations, every write torn at every 512-byte offset,
//!   with `KeepAll` so the torn prefix reaches the disk;
//! - **random**: seeded random (operation, point, tear, policy) choices;
//! - **double**: every n-th crash point also crashes during recovery, then recovers again.
//!
//! After each crash the engine is opened (recovery and the full invariant check), the recovered
//! state's digest is recorded, and the operation in flight is retried (§15.1, §15.4): a retry of
//! a committed operation must be a harmless duplicate, of an uncommitted one a normal success.
//! The results are written as JSONL; `sever_refmodel_durable.oracle check` is the verdict.

use std::io::Write;
use std::sync::Arc;
use std::time::Instant;

use serde_json::json;
use sever_engine::{
    CollectionOptions, DeleteOutcome, Engine, EngineConfig, FailurePolicy, InsertRequest,
};
use sever_index::NoExtension;
use sever_txn::PlaintextSealer;
use sever_types::{CollectionId, Error};
use sever_vfs::rng::SplitMix64;
use sever_vfs::{CrashPolicy, FaultPlan, SimVfs};

use crate::oracle::{Oracle, OracleOp, hex, state_digest};
use crate::rows::Rows;

type Db = Engine<NoExtension, PlaintextSealer>;

/// Campaign settings.
#[derive(Clone, Debug)]
pub struct Settings {
    /// Storage checkpoint threshold (small, so checkpoints happen inside the stream).
    pub checkpoint_every: u64,
    /// WAL segment size (small, so segments roll over).
    pub wal_segment: u64,
    /// Payload store segment size.
    pub store_segment: u64,
    /// The collection's spawn target (200 in v1; 8 for the small fixture).
    pub spawn_target: usize,
    /// Operations sampled for the 512-byte offset crashes (Build §5.7: 200).
    pub offset_samples: usize,
    /// Random crash points (Build §5.7: 1,000).
    pub random_points: usize,
    /// Every n-th crash point also crashes during recovery (0: never).
    pub double_every: u64,
    /// Seed of every campaign choice (never of keys: those come from the OS).
    pub seed: u64,
    /// Crash at every VFS operation of every `step_every`-th operation (1: all).
    pub step_every: usize,
    /// Stop after this many operations of the stream (smoke runs).
    pub limit_ops: Option<usize>,
}

/// What the campaign did and what it saw (the Rust side's own check; the Python oracle's check
/// of the results file is the gate's verdict).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Summary {
    /// Operations of the stream run on main.
    pub ops: u64,
    /// Crash points, by kind: step, offset, random.
    pub step: u64,
    /// See above.
    pub offset: u64,
    /// See above.
    pub random: u64,
    /// Of which also crashed during recovery.
    pub double: u64,
    /// Main-line states that differ from the oracle (engine ≠ model, no crash involved).
    pub main_mismatches: u64,
    /// Recovered states that are neither allowed state.
    pub not_oracle_state: u64,
    /// Recoveries that refused to start.
    pub refusals: u64,
    /// Retries that did not behave as §15.1 and §15.4 say.
    pub bad_retries: u64,
    /// Double crashes that recovered to a different state.
    pub double_mismatches: u64,
    /// Crash points a replay never reached (it did fewer VFS operations than the main line).
    pub skipped: u64,
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
    }
}

#[derive(Clone)]
struct Disks {
    data: SimVfs,
    keys: SimVfs,
}

impl Disks {
    fn fork(&self) -> Self {
        Self {
            data: self.data.fork(),
            keys: self.keys.fork(),
        }
    }
    fn restart(&self, p: CrashPolicy) {
        self.data.restart(p);
        self.keys.restart(p);
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
    oracle: &'a Oracle,
    rows: &'a dyn Rows,
    s: &'a Settings,
    cfg: EngineConfig,
    out: &'a mut dyn Write,
    sum: Summary,
    rng: SplitMix64,
    points: u64,
}

impl Run<'_> {
    fn open(&self, d: &Disks) -> Result<Db, Error> {
        Engine::open(
            Arc::new(d.data.clone()),
            Arc::new(d.keys.clone()),
            PlaintextSealer,
            NoExtension,
            Vec::new(),
            self.cfg.clone(),
        )
    }

    fn exec(&self, db: &Db, cid: CollectionId, op: &OracleOp) -> Result<Vec<DeleteOutcome>, Error> {
        match op {
            OracleOp::Insert { id, row } => {
                let vector = self.rows.row(*row).map_err(|_| Error::WrongDimension)?;
                db.insert(
                    cid,
                    InsertRequest {
                        record_id: id.clone(),
                        vector,
                        credential: (),
                        passage: Some(format!("passage {id}").into_bytes()),
                    },
                )
                .map(|_| Vec::new())
            }
            OracleOp::DeleteUser(ids) => {
                let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
                db.delete_user(cid, &refs)
            }
            OracleOp::Delete(id) => db.delete(cid, id).map(|o| vec![o]),
        }
    }

    fn digest(db: &Db, cid: CollectionId) -> Option<[u8; 32]> {
        db.canonical_state(cid).ok().map(|s| state_digest(&s))
    }

    /// §15.1, §15.4: retrying the operation in flight after recovery.
    fn retry_ok(&self, db: &Db, cid: CollectionId, i: usize, committed: bool) -> bool {
        let Some(op) = self.oracle.ops.get(i) else {
            return false;
        };
        let r = self.exec(db, cid, op);
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
            (_, Ok(outs), true) => outs.iter().all(|o| *o == DeleteOutcome::AlreadyAbsent),
            (_, Ok(outs), false) => outs.iter().any(|o| *o != DeleteOutcome::AlreadyAbsent),
            (_, Err(_), _) => false,
        };
        behaved && Self::digest(db, cid).as_ref() == self.oracle.digests.get(i + 1)
    }

    /// One crash point: op `i` replayed from `base` with a crash during its `k`-th VFS operation.
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
        let op = self.oracle.ops.get(i).ok_or("op")?;
        let d = base.fork();
        {
            let db = self
                .open(&d)
                .map_err(|e| format!("op {i}: base did not open: {e}"))?;
            d.data.set_faults(FaultPlan {
                crash_at_op: Some(k),
                tear_bytes: tear,
                ..FaultPlan::default()
            });
            if self.exec(&db, cid, op).is_ok() {
                self.sum.skipped += 1;
                return Ok(());
            }
        }
        d.restart(policy);
        self.points += 1;
        let double_now = self.s.double_every > 0 && self.points % self.s.double_every == 0;
        let double = if double_now {
            let d2 = d.fork();
            d2.data.set_faults(FaultPlan {
                crash_at_op: Some(1 + self.rng.below(4)),
                ..FaultPlan::default()
            });
            drop(self.open(&d2));
            d2.restart(CrashPolicy::Random(self.rng.next_u64()));
            self.sum.double += 1;
            Some(self.open(&d2).ok().and_then(|db| Self::digest(&db, cid)))
        } else {
            None
        };
        let (state, retry) = match self.open(&d) {
            Ok(db) => {
                let st = Self::digest(&db, cid);
                let committed = st.as_ref() == self.oracle.digests.get(i + 1);
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

/// Runs the campaign; writes one JSON line per crash point and a final summary line.
pub fn run(
    oracle: &Oracle,
    rows: &dyn Rows,
    artefact: &[u8],
    s: &Settings,
    out: &mut dyn Write,
) -> Result<Summary, String> {
    let t0 = Instant::now();
    let cfg = EngineConfig {
        wal_segment_bytes: s.wal_segment,
        store_segment_bytes: s.store_segment,
        checkpoint_every_wal_bytes: s.checkpoint_every,
        on_failure: FailurePolicy::Poison,
        config_hash: [0; 32],
    };
    let mut run = Run {
        oracle,
        rows,
        s,
        cfg,
        out,
        sum: Summary::default(),
        rng: SplitMix64::new(s.seed),
        points: 0,
    };
    let main = Disks {
        data: SimVfs::new(),
        keys: SimVfs::new(),
    };
    let db = run.open(&main).map_err(|e| format!("create: {e}"))?;
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
    if Run::digest(&db, cid).as_ref() != oracle.digests.first() {
        return Err("the empty collection differs from the oracle's initial state".into());
    }
    let n = s
        .limit_ops
        .unwrap_or(oracle.ops.len())
        .min(oracle.ops.len());
    // Seeded choices: the operations sampled for byte offsets, and the random points.
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
        let op = oracle.ops.get(i).ok_or("op")?.clone();
        let base = main.fork();
        // The crash points of op i: the VFS operations it performs. A replay on an engine
        // reopened from `base` performs the same ones (the engine's state is a function of the
        // disk, including the checkpoint trigger); a point it never reaches is counted as skipped.
        main.data.set_faults(FaultPlan::default());
        run.exec(&db, cid, &op)
            .map_err(|e| format!("main line, op {i}: {e}"))?;
        let m = main.data.ops_since_plan();
        let writes = main.data.write_log();
        run.sum.ops += 1;
        if Run::digest(&db, cid).as_ref() != oracle.digests.get(i + 1) {
            run.sum.main_mismatches += 1;
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
            // Build §5.7: every 512-byte offset of the sampled operations' WAL writes.
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
    run.sum.seconds = t0.elapsed().as_secs();
    let sum = run.sum.clone();
    let line = json!({
        "t": "summary", "ops": sum.ops, "step": sum.step, "offset": sum.offset,
        "random": sum.random, "double": sum.double, "main_mismatches": sum.main_mismatches,
        "not_oracle_state": sum.not_oracle_state, "refusals": sum.refusals,
        "bad_retries": sum.bad_retries, "double_mismatches": sum.double_mismatches,
        "skipped": sum.skipped, "seconds": sum.seconds,
    });
    writeln!(run.out, "{line}").map_err(|e| e.to_string())?;
    Ok(sum)
}
