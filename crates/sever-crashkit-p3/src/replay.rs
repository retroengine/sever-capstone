//! P3-T5 (Build 3-4 §1.8 L4, F-5): Part 1's frozen traces, written by the reference model from the
//! spec alone, replayed through the Part 3 engine. Everything the trace records is compared, the
//! blobs in their core form (the full form adds `C_S ‖ r_agg`, which no Part 1 model knows); and
//! what Part 3 adds is checked against the commitment model ([`crate::check::Model`]):
//!
//! - every certificate passes §11.3 and its `C_S_pre` is the sum of the group's members' `C_t`;
//! - after every rung, every group's `C_S` equals that sum, and the five-field equivalence
//!   (`S`, `n`, `C_S`, the full-form blob with `r_agg`, the member list) holds between the
//!   group's state and the state rebuilt from its survivors (§5.5);
//! - in `close` and `crash` modes, the state, the log and the certificates survive the reopen.

#![allow(clippy::indexing_slicing)] // serde_json::Value indexing only: returns Null, never panics

use std::collections::{BTreeMap, HashSet};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

use serde_json::Value;
use sever_engine::{CollectionOptions, EngineConfig, InsertRequest};
use sever_index::{Placement, assert_state_equivalent};
use sever_p3::{Db, Deleted};
use sever_tracekit::Npy;
use sever_types::{CollectionId, Error, GroupId};
use sever_vfs::CrashPolicy;
use sha2::{Digest, Sha256};

use crate::check::{Model, accept};
use crate::core::core_blob;
use crate::world::{Cred, Disks, World};

/// What happens after every rung.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    /// One engine for the whole trace.
    Plain,
    /// A clean `close`, then `open`.
    Close,
    /// No close: unsynced writes dropped, then `open` (recovery).
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
    /// Trace lines replayed.
    pub ops: u64,
    /// Values compared with the trace.
    pub checks: u64,
    /// Values that differ from the trace.
    pub mismatches: u64,
    /// Certificates checked (§11.3 and the model).
    pub certificates: u64,
    /// Certificates that failed a check.
    pub certificate_failures: u64,
    /// Five-field equivalence checks run on groups, and how many failed.
    pub five_field_checked: u64,
    /// See above.
    pub five_field_failed: u64,
    /// Groups whose `C_S` differs from the sum of their members' `C_t`.
    pub commitment_mismatches: u64,
    /// Reopens done, and after how many the state, log or certificates changed.
    pub reopens: u64,
    /// See above.
    pub reopen_changed: u64,
    /// Deleted records returned by a search.
    pub deleted_returned: u64,
    /// The first problems, for the log (no vector values).
    pub first: Vec<String>,
}

impl Report {
    fn note(&mut self, msg: String) {
        if self.first.len() < 20 {
            self.first.push(msg);
        }
    }
    fn check(&mut self, ok: bool, msg: impl FnOnce() -> String) {
        self.checks += 1;
        if !ok {
            self.mismatches += 1;
            let m = msg();
            self.note(m);
        }
    }
    /// Every check passed, and something was checked.
    pub fn passed(&self) -> bool {
        self.mismatches == 0
            && self.certificate_failures == 0
            && self.five_field_failed == 0
            && self.commitment_mismatches == 0
            && self.reopen_changed == 0
            && self.deleted_returned == 0
            && self.checks > 0
            && self.certificates > 0
    }
    /// One JSON object.
    pub fn to_json(&self) -> Value {
        serde_json::json!({
            "ops": self.ops, "checks": self.checks, "mismatches": self.mismatches,
            "certificates": self.certificates, "certificate_failures": self.certificate_failures,
            "five_field_checked": self.five_field_checked,
            "five_field_failed": self.five_field_failed,
            "commitment_mismatches": self.commitment_mismatches, "reopens": self.reopens,
            "reopen_changed": self.reopen_changed, "deleted_returned": self.deleted_returned,
            "first": self.first, "passed": self.passed(),
        })
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

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

fn strings(v: &Value) -> Vec<String> {
    v.as_array()
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(str::to_owned))
                .collect()
        })
        .unwrap_or_default()
}

/// The SHA-256 of a group's blob in core form (what Part 1's trace records).
fn core_hash(db: &Db, cid: CollectionId, g: &GroupId, d: usize) -> String {
    db.engine
        .group_snapshot(cid, g)
        .and_then(|s| core_blob(&s.blob, d))
        .map_or_else(String::new, |b| hex(&Sha256::digest(&b)))
}

fn compare_hashes(
    db: &Db,
    cid: CollectionId,
    want: &Value,
    rep: &mut Report,
    what: &str,
    d: usize,
) {
    if let Some(obj) = want.as_object() {
        for (g, h) in obj {
            let got = GroupId::parse(g)
                .map(|g| core_hash(db, cid, &g, d))
                .unwrap_or_default();
            rep.check(Some(got.as_str()) == h.as_str(), || {
                format!("{what}: core blob of {g} differs")
            });
        }
    }
}

/// Everything a reopen must keep: the canonical state, the log's size and root, every certificate.
fn durable_view(db: &Db, cid: CollectionId) -> Result<Vec<u8>, String> {
    let mut v = format!(
        "{:?}",
        db.engine.canonical_state(cid).map_err(|e| e.to_string())?
    )
    .into_bytes();
    let (size, root) = db
        .log
        .with(|l| (l.tree().size(), l.tree().root(l.tree().size())))
        .ok_or("log")?;
    v.extend(size.to_be_bytes());
    v.extend(root.unwrap_or_default());
    for lsn in 0..size {
        v.extend(
            db.certificate(lsn)
                .map_err(|e| e.to_string())?
                .unwrap_or_default(),
        );
    }
    Ok(v)
}

/// The rung checks Part 3 adds: `C_S` = Σ `C_t` and the five-field equivalence, every group.
fn group_checks(db: &Db, cid: CollectionId, model: &Model, rep: &mut Report, rung: u64) {
    for g in db.engine.group_ids(cid) {
        let snap = db.engine.group_snapshot(cid, &g);
        let got = snap
            .as_ref()
            .map(|s| sever_crypto::encode_point(&s.ext_public.0));
        if got != model.commitment(&g) {
            rep.commitment_mismatches += 1;
            rep.note(format!("rung {rung}: C_S of {} is not Σ C_t", g.as_text()));
        }
        rep.five_field_checked += 1;
        let ok = matches!(
            (snap, db.engine.survivors_snapshot(cid, &g)),
            (Some(a), Some(b)) if assert_state_equivalent(&a, &b).is_ok()
        );
        if !ok {
            rep.five_field_failed += 1;
            rep.note(format!(
                "rung {rung}: five-field equivalence of {}",
                g.as_text()
            ));
        }
    }
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
    let d = sever_partition::PartitionArtefact::parse(&art)
        .map_err(|e| format!("artefact: {e}"))?
        .d;
    let vectors = Npy::open(&root.join(s("vectors")?)).map_err(|e| e.0)?;
    let queries_npy = Npy::open(&root.join(s("queries")?)).map_err(|e| e.0)?;
    let n_queries = header["n_queries"].as_u64().unwrap_or(0) as usize;
    let queries: Vec<Vec<f32>> = (0..n_queries)
        .map(|i| queries_npy.row(i))
        .collect::<Result<_, _>>()
        .map_err(|e| e.0)?;
    let top_k = header["top_k"].as_u64().unwrap_or(100) as usize;

    let world = World::new(d, EngineConfig::default(), 64 << 20)?;
    let disks = Disks::new();
    let mut db = world.open(&disks).map_err(|e| format!("open: {e}"))?;
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
    let mut model = Model::default();
    let mut deleted = HashSet::new();
    let timing = std::env::var_os("SEVER_KIT_TIMING").is_some();
    let mut spent: BTreeMap<&'static str, std::time::Duration> = BTreeMap::new();
    for line in lines {
        let t0 = std::time::Instant::now();
        let line = line.map_err(|e| format!("read: {e}"))?;
        let op: Value = serde_json::from_str(&line).map_err(|e| format!("line: {e}"))?;
        rep.ops += 1;
        let kind: &'static str = match op["t"].as_str() {
            Some("i") => "insert",
            Some("d") => "delete",
            _ => "rung",
        };
        match op["t"].as_str() {
            Some("i") => {
                let id = op["id"].as_str().unwrap_or_default().to_owned();
                let row = op["row"].as_u64().unwrap_or(0) as usize;
                let vector = vectors.row(row).map_err(|e| e.0)?;
                // A vector §4.1 refuses has no C_t; the engine refuses it before step 2.
                let tc = std::time::Instant::now();
                let cred = world.credential(cid, &vector).unwrap_or(Cred {
                    collection_id: *cid.as_bytes(),
                    c_t: [0; 32],
                    r_t: [0; 32],
                    user_public_key: [0; 32],
                    signature: [0; 64],
                });
                let req = InsertRequest {
                    record_id: id.clone(),
                    vector,
                    credential: cred.credential(),
                    passage: None,
                };
                if timing {
                    *spent.entry("i.cred").or_default() += tc.elapsed();
                }
                let ti = std::time::Instant::now();
                let res = db.insert(cid, req);
                if timing {
                    *spent.entry("i.engine").or_default() += ti.elapsed();
                }
                match (res, op["e"].as_str()) {
                    (Ok((lsn, p)), None) => {
                        let want = op["p"].as_str().unwrap_or_default();
                        let got = placement_text(&p);
                        rep.check(got == want, || format!("insert {id}: {got} vs {want}"));
                        let leaf = db
                            .log
                            .with(|l| l.insert_leaf(lsn))
                            .ok_or("log")?
                            .map_err(|e| e.to_string())?
                            .ok_or("insert leaf")?;
                        rep.check(leaf.c_t == cred.c_t, || format!("insert {id}: leaf C_t"));
                        model.insert(&p, leaf.scrambled_id, leaf.c_t);
                        deleted.remove(&id);
                    }
                    (Err(e), Some(want)) => rep.check(error_kind(&e) == want, || {
                        format!("insert {id}: error {} vs {want}", error_kind(&e))
                    }),
                    (got, want) => rep.check(false, || {
                        format!(
                            "insert {id}: {:?} vs model {want:?}",
                            got.map(|(_, p)| placement_text(&p))
                                .map_err(|e| error_kind(&e))
                        )
                    }),
                }
                let th = std::time::Instant::now();
                compare_hashes(&db, cid, &op["g"], &mut rep, &id, d);
                if timing {
                    *spent.entry("i.hash").or_default() += th.elapsed();
                }
            }
            Some("d") => {
                let ids = strings(&op["ids"]);
                let from: Vec<Option<String>> =
                    ids.iter().map(|r| db.engine.location(cid, r)).collect();
                let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
                let outs = db
                    .delete_user(cid, &refs)
                    .map_err(|e| format!("delete_user: {e}"))?;
                let want = strings(&op["o"]);
                rep.check(outs.len() == want.len(), || "delete_user: count".to_owned());
                for (((o, w), id), f) in outs.iter().zip(&want).zip(&ids).zip(&from) {
                    let got = match o {
                        Deleted::Deleted { certificate, .. } => {
                            deleted.insert(id.clone());
                            rep.certificates += 1;
                            let g = f.as_deref().and_then(GroupId::parse);
                            let verdict = accept(&db.anchors(), db.generators(), certificate)
                                .and_then(|c| match &g {
                                    Some(g) => model.delete(g, &c),
                                    None => Err("no group"),
                                });
                            if let Err(why) = verdict {
                                rep.certificate_failures += 1;
                                rep.note(format!("delete {id}: {why}"));
                            }
                            f.clone().unwrap_or_else(|| "?".to_owned())
                        }
                        Deleted::AlreadyAbsent => "absent".to_owned(),
                    };
                    rep.check(&got == w, || format!("delete {id}: {got} vs {w}"));
                }
                compare_hashes(&db, cid, &op["g"], &mut rep, "delete_user", d);
            }
            Some("c") => {
                let rung = op["rung"].as_u64().unwrap_or(0);
                let st = db.engine.stats(cid).map_err(|e| format!("stats: {e}"))?;
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
                    .engine
                    .group_ids(cid)
                    .iter()
                    .map(|g| (g.as_text(), core_hash(&db, cid, g, d)))
                    .collect();
                rep.check(want == got, || format!("rung {rung}: group blobs differ"));
                group_checks(&db, cid, &model, &mut rep, rung);
                let results = op["r"].as_array().cloned().unwrap_or_default();
                for (qi, (q, want)) in queries.iter().zip(&results).enumerate() {
                    let hits = db
                        .engine
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
                            format!("rung {rung} q{qi}: {} vs {wid}", h.record_id.as_str())
                        });
                        if deleted.contains(h.record_id.as_str()) {
                            rep.deleted_returned += 1;
                        }
                    }
                }
                if mode != Mode::Plain {
                    let before = durable_view(&db, cid)?;
                    if mode == Mode::Close {
                        db.engine.close().map_err(|e| format!("close: {e}"))?;
                    } else {
                        drop(db);
                        disks.restart(CrashPolicy::DropAll);
                    }
                    db = world.open(&disks).map_err(|e| format!("reopen: {e}"))?;
                    rep.reopens += 1;
                    if durable_view(&db, cid)? != before {
                        rep.reopen_changed += 1;
                        rep.note(format!("rung {rung}: the reopen changed the state or log"));
                    }
                }
            }
            _ => return Err("unknown trace line".into()),
        }
        if timing {
            *spent.entry(kind).or_default() += t0.elapsed();
            if rep.ops % 2000 == 0 || kind == "rung" {
                eprintln!("ops {} {spent:?}", rep.ops);
            }
        }
    }
    Ok(rep)
}
