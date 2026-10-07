//! P2-T5 (Build §5.7 L4, F-5 regression by reuse): Part 1's frozen traces, written by the
//! reference model from the specification alone, replayed through the Part 2 engine. Every value
//! the trace records is compared: placements, error kinds, deletion outcomes, the SHA-256 of every
//! touched group's canonical blob after every operation, and at every rung the stats, every
//! group's blob hash and the top-k results with their score bits. The expected values come only
//! from the trace; the engine is never its own oracle.
//!
//! Three modes: `plain` (one engine, no restart); `close` (a clean close and reopen after every
//! rung); `crash` (after every rung the process "dies" without closing, unsynced writes are
//! dropped, and the engine recovers). After a reopen the collection's canonical state must equal
//! the state before it, and the replay goes on against the same trace.

#![allow(clippy::indexing_slicing)] // serde_json::Value indexing only: returns Null, never panics

use std::collections::BTreeMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::sync::Arc;

use serde_json::Value;
use sever_engine::{
    CollectionOptions, DeleteOutcome, Engine, EngineConfig, FailurePolicy, InsertRequest,
};
use sever_index::{NoExtension, Placement, assert_state_equivalent};
use sever_tracekit::Npy;
use sever_txn::PlaintextSealer;
use sever_types::{CollectionId, Error, GroupId};
use sever_vfs::{CrashPolicy, SimVfs};
use sha2::{Digest, Sha256};

type Db = Engine<NoExtension, PlaintextSealer>;

/// What happens after every rung.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    /// Nothing: one engine for the whole trace.
    Plain,
    /// A clean `close`, then `open`.
    Close,
    /// No close: the disks drop every unsynced write (`CrashPolicy::DropAll`), then `open`.
    Crash,
}

impl Mode {
    /// Parses `plain`, `close` or `crash`.
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "plain" => Some(Self::Plain),
            "close" => Some(Self::Close),
            "crash" => Some(Self::Crash),
            _ => None,
        }
    }
}

/// The outcome of one replay.
#[derive(Debug, Default)]
pub struct Report {
    /// Trace operations replayed (insert, delete and rung lines).
    pub ops: u64,
    /// Values compared.
    pub checks: u64,
    /// Values that differ from the trace.
    pub mismatches: u64,
    /// The first mismatches, for the log (no vector values; IDs are synthetic dataset IDs).
    pub first: Vec<String>,
    /// Reopens done (close or crash mode).
    pub reopens: u64,
    /// Reopens after which the canonical state differed from the one before.
    pub reopen_state_changed: u64,
    /// Survivors checks run on touched groups (Build §4.7 L6), and how many failed.
    pub survivors_checked: u64,
    /// See [`Report::survivors_checked`].
    pub survivors_failed: u64,
    /// Deleted records returned by a search.
    pub deleted_returned: u64,
}

impl Report {
    fn check(&mut self, ok: bool, msg: impl FnOnce() -> String) {
        self.checks += 1;
        if !ok {
            self.mismatches += 1;
            if self.first.len() < 20 {
                self.first.push(msg());
            }
        }
    }
    /// Every check passed and something was checked.
    pub fn passed(&self) -> bool {
        self.mismatches == 0
            && self.reopen_state_changed == 0
            && self.survivors_failed == 0
            && self.deleted_returned == 0
            && self.checks > 0
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// The §17 name of an error, as the model writes it.
fn error_kind(e: &Error) -> String {
    format!("{e:?}")
        .split([' ', '(', '{'])
        .next()
        .unwrap_or("")
        .to_owned()
}

fn placement_text(p: &Placement) -> String {
    match p {
        Placement::Frozen(g) | Placement::Spawned(g) => g.as_text(),
        Placement::Holding => "holding".to_owned(),
    }
}

fn blob_hash(db: &Db, cid: CollectionId, g: &GroupId) -> String {
    db.group_snapshot(cid, g)
        .map_or_else(String::new, |s| hex(&Sha256::digest(&s.blob)))
}

fn compare_hashes(db: &Db, cid: CollectionId, want: &Value, rep: &mut Report, what: &str) {
    if let Some(obj) = want.as_object() {
        for (g, h) in obj {
            let got = GroupId::parse(g)
                .map(|g| blob_hash(db, cid, &g))
                .unwrap_or_default();
            rep.check(Some(got.as_str()) == h.as_str(), || {
                format!("{what}: blob of {g} differs")
            });
        }
    }
}

struct Disks {
    data: SimVfs,
    keys: SimVfs,
}

impl Disks {
    fn open(&self) -> Result<Db, String> {
        Engine::open(
            Arc::new(self.data.clone()),
            Arc::new(self.keys.clone()),
            PlaintextSealer,
            NoExtension,
            Vec::new(),
            EngineConfig {
                on_failure: FailurePolicy::Poison,
                ..EngineConfig::default()
            },
        )
        .map_err(|e| format!("open: {e}"))
    }
}

fn strings(v: &Value) -> Vec<String> {
    v.as_array()
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(str::to_owned))
                .collect()
        })
        .unwrap_or_default()
}

/// Replays `trace` (paths in its header resolved against `root`) in `mode`.
pub fn replay(trace: &Path, root: &Path, mode: Mode) -> Result<Report, String> {
    let file = File::open(trace).map_err(|e| format!("{}: {e}", trace.display()))?;
    let mut lines = BufReader::new(file).lines();
    let header: Value = match lines.next() {
        Some(Ok(l)) => serde_json::from_str(&l).map_err(|e| format!("header: {e}"))?,
        _ => return Err("empty trace".into()),
    };
    let s = |k: &str| {
        header[k]
            .as_str()
            .map(str::to_owned)
            .ok_or_else(|| format!("header.{k}"))
    };
    let art = std::fs::read(root.join(s("artefact")?)).map_err(|e| format!("artefact: {e}"))?;
    if hex(&Sha256::digest(&art)) != s("artefact_sha256")? {
        return Err("artefact hash differs from the trace header".into());
    }
    let vectors = Npy::open(&root.join(s("vectors")?)).map_err(|e| e.0)?;
    let queries_npy = Npy::open(&root.join(s("queries")?)).map_err(|e| e.0)?;
    let n_queries = header["n_queries"].as_u64().unwrap_or(0) as usize;
    let queries: Vec<Vec<f32>> = (0..n_queries)
        .map(|i| queries_npy.row(i))
        .collect::<Result<_, _>>()
        .map_err(|e| e.0)?;
    let top_k = header["top_k"].as_u64().unwrap_or(100) as usize;

    let disks = Disks {
        data: SimVfs::new(),
        keys: SimVfs::new(),
    };
    let mut db = disks.open()?;
    let cid = db
        .create_collection(
            &art,
            CollectionOptions {
                spawn_target: header["spawn_target"].as_u64().unwrap_or(200) as usize,
                spawning_enabled: header["spawning"].as_bool().unwrap_or(true),
                store_passages: false,
            },
        )
        .map_err(|e| format!("create_collection: {e}"))?;

    let mut rep = Report::default();
    let mut deleted = std::collections::HashSet::new();
    for line in lines {
        let line = line.map_err(|e| format!("read: {e}"))?;
        let op: Value = serde_json::from_str(&line).map_err(|e| format!("line: {e}"))?;
        rep.ops += 1;
        match op["t"].as_str() {
            Some("i") => {
                let id = op["id"].as_str().unwrap_or_default().to_owned();
                let row = op["row"].as_u64().unwrap_or(0) as usize;
                let vector = vectors.row(row).map_err(|e| e.0)?;
                let req = InsertRequest {
                    record_id: id.clone(),
                    vector,
                    credential: (),
                    passage: None,
                };
                match (db.insert(cid, req), op["e"].as_str()) {
                    (Ok(r), None) => {
                        let want = op["p"].as_str().unwrap_or_default();
                        let got = placement_text(&r.placement);
                        rep.check(got == want, || format!("insert {id}: {got} vs {want}"));
                        deleted.remove(&id);
                    }
                    (Err(e), Some(want)) => rep.check(error_kind(&e) == want, || {
                        format!("insert {id}: error {} vs {want}", error_kind(&e))
                    }),
                    (got, want) => rep.check(false, || {
                        format!(
                            "insert {id}: {:?} vs model {want:?}",
                            got.map(|r| placement_text(&r.placement))
                                .map_err(|e| error_kind(&e))
                        )
                    }),
                }
                compare_hashes(&db, cid, &op["g"], &mut rep, &id);
            }
            Some("d") => {
                let ids = strings(&op["ids"]);
                // The group each record leaves, read before the deletion (the engine's outcome
                // carries participant outputs, not the group).
                let from: Vec<Option<String>> = ids.iter().map(|r| db.location(cid, r)).collect();
                let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
                let outs = db
                    .delete_user(cid, &refs)
                    .map_err(|e| format!("delete_user: {e}"))?;
                let want = strings(&op["o"]);
                rep.check(outs.len() == want.len(), || {
                    "delete_user: outcome count".to_owned()
                });
                for (((o, w), id), f) in outs.iter().zip(&want).zip(&ids).zip(&from) {
                    let got = match o {
                        DeleteOutcome::Deleted { .. } => {
                            deleted.insert(id.clone());
                            f.clone().unwrap_or_else(|| "?".to_owned())
                        }
                        DeleteOutcome::AlreadyAbsent => "absent".to_owned(),
                    };
                    rep.check(&got == w, || format!("delete {id}: {got} vs {w}"));
                }
                compare_hashes(&db, cid, &op["g"], &mut rep, "delete_user");
                if let Some(obj) = op["g"].as_object() {
                    for g in obj.keys().filter_map(|g| GroupId::parse(g)) {
                        if g == GroupId::Holding {
                            continue;
                        }
                        rep.survivors_checked += 1;
                        let ok = matches!(
                            (db.group_snapshot(cid, &g), db.survivors_snapshot(cid, &g)),
                            (Some(a), Some(b)) if assert_state_equivalent(&a, &b).is_ok()
                        );
                        if !ok {
                            rep.survivors_failed += 1;
                        }
                    }
                }
            }
            Some("c") => {
                let rung = op["rung"].as_u64().unwrap_or(0);
                let st = db.stats(cid).map_err(|e| format!("stats: {e}"))?;
                let ms = &op["stats"];
                for (name, got) in [
                    ("frozen", st.frozen),
                    ("spawned", st.spawned),
                    ("N", st.big_n),
                    ("k", st.k),
                    ("holding", st.holding),
                ] {
                    rep.check(ms[name].as_u64() == Some(got), || {
                        format!("rung {rung}: stats.{name} {got} vs {}", ms[name])
                    });
                }
                let want: BTreeMap<String, String> = op["g"]
                    .as_object()
                    .map(|o| {
                        o.iter()
                            .map(|(k, v)| (k.clone(), v.as_str().unwrap_or_default().to_owned()))
                            .collect()
                    })
                    .unwrap_or_default();
                let got: BTreeMap<String, String> = db
                    .group_ids(cid)
                    .iter()
                    .map(|g| (g.as_text(), blob_hash(&db, cid, g)))
                    .collect();
                rep.check(want.len() == got.len(), || {
                    format!("rung {rung}: {} groups vs {}", got.len(), want.len())
                });
                for (g, h) in &want {
                    rep.check(got.get(g) == Some(h), || {
                        format!("rung {rung}: blob of {g} differs")
                    });
                }
                let results = op["r"].as_array().cloned().unwrap_or_default();
                for (qi, (q, want)) in queries.iter().zip(&results).enumerate() {
                    let hits = db
                        .search(cid, q, top_k)
                        .map_err(|e| format!("search: {e}"))?;
                    let want = want.as_array().cloned().unwrap_or_default();
                    rep.check(hits.len() == want.len(), || {
                        format!("rung {rung} q{qi}: {} hits vs {}", hits.len(), want.len())
                    });
                    for (h, w) in hits.iter().zip(&want) {
                        let wid = w[0].as_str().unwrap_or_default();
                        let wbits = w[1].as_str().unwrap_or_default();
                        let gbits = hex(&h.score.to_bits().to_be_bytes());
                        rep.check(h.record_id.as_str() == wid && gbits == wbits, || {
                            format!(
                                "rung {rung} q{qi}: {} {gbits} vs {wid} {wbits}",
                                h.record_id.as_str()
                            )
                        });
                        if deleted.contains(h.record_id.as_str()) {
                            rep.deleted_returned += 1;
                        }
                    }
                }
                if mode != Mode::Plain {
                    let before = db.canonical_state(cid).map_err(|e| format!("state: {e}"))?;
                    if mode == Mode::Close {
                        db.close().map_err(|e| format!("close: {e}"))?;
                    } else {
                        drop(db);
                        disks.data.restart(CrashPolicy::DropAll);
                        disks.keys.restart(CrashPolicy::DropAll);
                    }
                    // Recovery and the full invariant check run inside open (§12.4).
                    db = disks.open()?;
                    rep.reopens += 1;
                    let after = db.canonical_state(cid).map_err(|e| format!("state: {e}"))?;
                    if after != before {
                        rep.reopen_state_changed += 1;
                        if rep.first.len() < 20 {
                            rep.first
                                .push(format!("rung {rung}: state changed by the reopen"));
                        }
                    }
                }
            }
            _ => return Err("unknown trace line".into()),
        }
    }
    Ok(rep)
}
