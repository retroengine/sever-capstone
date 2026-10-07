//! `sever-demo-p2 durable` (Build §5.9): a multi-group `delete_user` interrupted by a crash, before
//! and after its commit point, on a simulated disk and with a real `SIGKILL`; after each recovery
//! the invariant check passes, the deletion is all or nothing, and Part 1's survivors check holds
//! for every touched group.
//!
//! The demo shows one deletion; the evidence for crash safety is the campaign (`gates p2-crash`).

#![allow(clippy::indexing_slicing)] // serde_json::Value indexing only: returns Null, never panics

use std::collections::{BTreeMap, BTreeSet};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::time::Instant;

use serde_json::{Value, json};
use sever_engine::{CollectionOptions, Engine, EngineConfig, FailurePolicy, InsertRequest};
use sever_index::{NoExtension, assert_state_equivalent};
use sever_txn::{PlaintextSealer, Step};
use sever_types::{CollectionId, GroupId};
use sever_vfs::{CrashPolicy, SimVfs};

use crate::{OpenOptions, P2Engine, cid_hex, open};

/// A demo failure (setup, not a finding: findings are in the report).
#[derive(Debug)]
pub struct DemoError(pub String);

fn e(msg: impl std::fmt::Display) -> DemoError {
    DemoError(msg.to_string())
}

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
    fn open(&self) -> Result<P2Engine, DemoError> {
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
        .map_err(|x| e(format!("open: {x}")))
    }
}

/// How many of `ids` are live, and in which groups the live ones are.
fn presence(db: &P2Engine, cid: CollectionId, ids: &[String]) -> (usize, BTreeSet<String>) {
    let mut groups = BTreeSet::new();
    let mut n = 0;
    for id in ids {
        if let Some(g) = db.location(cid, id) {
            n += 1;
            groups.insert(g);
        }
    }
    (n, groups)
}

fn stats(db: &P2Engine, cid: CollectionId) -> Value {
    db.stats(cid).map_or(
        json!(null),
        |s| json!({"N": s.big_n, "k": s.k, "spawned": s.spawned, "holding": s.holding}),
    )
}

/// Part 1's survivors check (Build §4.7 L6) on every touched group: the group equals the same
/// group rebuilt from its surviving members alone, on all five fields of §5.5.
fn survivors(db: &P2Engine, cid: CollectionId, touched: &BTreeSet<String>) -> Value {
    let mut ok = 0;
    let mut failed = Vec::new();
    for g in touched {
        let Some(id) = GroupId::parse(g) else {
            continue;
        };
        if id == GroupId::Holding {
            continue;
        }
        match (db.group_snapshot(cid, &id), db.survivors_snapshot(cid, &id)) {
            (Some(a), Some(b)) if assert_state_equivalent(&a, &b).is_ok() => ok += 1,
            _ => failed.push(g.clone()),
        }
    }
    json!({"groups_checked": ok, "failed": failed})
}

fn say(line: &str) {
    println!("{line}");
}

/// Runs the demo; returns the report.
pub fn durable(root: &Path, data: &str, seed: u64, work: &Path) -> Result<Value, DemoError> {
    let t0 = Instant::now();
    let ds = match data {
        "synthetic" => sever_p1::data::load_synthetic(root),
        name => sever_p1::data::load_nq(root, name, seed),
    }
    .map_err(|x| e(x.0))?;
    let art_path = if data == "synthetic" {
        root.join("golden/p1_partition_small.svp")
    } else {
        root.join(format!("artefacts/partition-seed{seed}.svp"))
    };
    let artefact = std::fs::read(&art_path).map_err(e)?;
    let opts = CollectionOptions {
        spawn_target: ds.spawn_target,
        spawning_enabled: true,
        store_passages: false,
    };
    let records: Vec<(String, Vec<f32>)> = ds
        .ids
        .iter()
        .enumerate()
        .filter_map(|(i, id)| ds.vector(i).map(|v| (id.clone(), v.to_vec())))
        .collect();
    let insert_all = |db: &P2Engine, cid: CollectionId| -> Result<(), DemoError> {
        for (id, v) in &records {
            db.insert(
                cid,
                InsertRequest {
                    record_id: id.clone(),
                    vector: v.clone(),
                    credential: (),
                    passage: None,
                },
            )
            .map_err(|x| e(format!("insert: {x}")))?;
        }
        Ok(())
    };

    // 1. Load every passage into a database on a simulated disk image.
    say(&format!(
        "1. Loading {} passages ({data}, seed {seed}) into a database on a simulated disk.",
        records.len()
    ));
    let disks = Disks {
        data: SimVfs::new(),
        keys: SimVfs::new(),
    };
    let db = disks.open()?;
    let cid = db.create_collection(&artefact, opts).map_err(e)?;
    insert_all(&db, cid)?;
    db.storage_checkpoint_now().map_err(e)?;
    let loaded = stats(&db, cid);
    say(&format!("   stats: {loaded}"));

    // The cohort (overview §10.8: one article title) whose records span the most groups.
    let mut by_title: BTreeMap<&str, Vec<String>> = BTreeMap::new();
    for (id, title) in ds.ids.iter().zip(&ds.cohorts) {
        by_title.entry(title.as_str()).or_default().push(id.clone());
    }
    let (title, cohort) = by_title
        .iter()
        .max_by_key(|(t, ids)| {
            (
                presence(&db, cid, ids).1.len(),
                ids.len(),
                std::cmp::Reverse(**t),
            )
        })
        .map(|(t, ids)| ((*t).to_owned(), ids.clone()))
        .ok_or(e("no cohort"))?;
    let (n_live, touched) = presence(&db, cid, &cohort);
    say(&format!(
        "   the cohort: {} records in {} groups: {:?}",
        n_live,
        touched.len(),
        touched
    ));
    drop(db);

    // 2–3. delete_user with a crash at a chosen protocol step, then recovery.
    let mut sim = Vec::new();
    for (label, at) in [
        ("before the commit point", Step::WalWriting),
        ("after the commit point", Step::Committed),
    ] {
        let d = disks.fork();
        let db = d.open()?;
        let crash = d.data.clone();
        db.set_step_hook(Some(Box::new(move |s| {
            if s == at {
                crash.crash();
            }
        })));
        let ids: Vec<&str> = cohort.iter().map(String::as_str).collect();
        let result = db.delete_user(cid, &ids);
        drop(db);
        d.data.restart(CrashPolicy::DropAll);
        d.keys.restart(CrashPolicy::DropAll);
        let rec = d.open()?; // recovery and the full invariant check
        let (left, _) = presence(&rec, cid, &cohort);
        let verdict = if left == n_live {
            "none deleted"
        } else if left == 0 {
            "all deleted"
        } else {
            "PARTIAL"
        };
        let check = survivors(&rec, cid, &touched);
        say(&format!(
            "2. delete_user, crash {label}: the call returned {}; after recovery (invariant check passed): {verdict} ({left} of {n_live} left); stats {}; survivors check {check}",
            if result.is_ok() {
                "success (never acknowledged: the process died)"
            } else {
                "an error"
            },
            stats(&rec, cid)
        ));
        sim.push(
            json!({"crash": label, "left": left, "of": n_live, "verdict": verdict,
            "stats_after": stats(&rec, cid), "survivors_check": check}),
        );
    }

    // 4. The same on real files, with a real SIGKILL of a child process.
    let posix_root = work.join(format!("durable-{data}-seed{seed}"));
    let _ = std::fs::remove_dir_all(&posix_root);
    let o = OpenOptions::new(posix_root.join("data"), posix_root.join("keys"));
    let pcid = {
        let opened = open(&o).map_err(e)?;
        let c = opened
            .engine
            .create_collection(&artefact, opts)
            .map_err(e)?;
        insert_all(&opened.engine, c)?;
        opened.engine.close().map_err(e)?;
        c
    };
    let me = std::env::current_exe().map_err(e)?;
    let mut posix = Vec::new();
    for pause in ["wal", "committed"] {
        let mut child = Command::new(&me)
            .args(["child-delete-user", "--data"])
            .arg(&o.data_dir)
            .arg("--keys")
            .arg(&o.key_dir)
            .args(["--cid", &cid_hex(&pcid), "--pause-at", pause, "--ids"])
            .arg(serde_json::to_string(&cohort).map_err(e)?)
            .stdout(Stdio::piped())
            .spawn()
            .map_err(e)?;
        let out = child.stdout.take().ok_or(e("child stdout"))?;
        let mut line = String::new();
        BufReader::new(out).read_line(&mut line).map_err(e)?;
        child.kill().map_err(e)?; // SIGKILL
        let status = child.wait().map_err(e)?;
        let opened = open(&o).map_err(e)?;
        let (left, _) = presence(&opened.engine, pcid, &cohort);
        let verdict = if left == n_live {
            "none deleted"
        } else if left == 0 {
            "all deleted"
        } else {
            "PARTIAL"
        };
        let check = survivors(&opened.engine, pcid, &touched);
        say(&format!(
            "4. real files, SIGKILL while paused at {pause} ({}; {status}): after restart {verdict} ({left} of {n_live} left); survivors check {check}",
            line.trim()
        ));
        posix.push(
            json!({"paused_at": pause, "child": line.trim(), "left": left, "of": n_live,
            "verdict": verdict, "survivors_check": check}),
        );
    }
    let _ = std::fs::remove_dir_all(&posix_root);
    let all_or_nothing = sim.iter().chain(&posix).all(|r| r["verdict"] != "PARTIAL");
    let expected = sim
        .first()
        .map(|r| r["verdict"] == "none deleted")
        .unwrap_or(false)
        && sim
            .get(1)
            .map(|r| r["verdict"] == "all deleted")
            .unwrap_or(false)
        && posix
            .first()
            .map(|r| r["verdict"] == "none deleted")
            .unwrap_or(false)
        && posix
            .get(1)
            .map(|r| r["verdict"] == "all deleted")
            .unwrap_or(false);
    say(&format!(
        "5. all or nothing in every case: {all_or_nothing}; before the commit point nothing, after it everything: {expected}"
    ));
    Ok(json!({
        "demo": "sever-demo-p2 durable", "data": data, "seed": seed,
        "artefact_sha256": ds.artefact_sha256, "records": records.len(),
        "loaded_stats": loaded, "cohort": {"title_chars": title.chars().count(),
            "records": n_live, "groups": touched}, "simulated": sim, "sigkill": posix,
        "all_or_nothing": all_or_nothing, "commit_point_respected": expected,
        "seconds": t0.elapsed().as_secs(),
        "note": "plaintext database (DB-48): no confidentiality claim",
    }))
}

/// The child of step 4: opens the database, pauses at `pause_at` inside `delete_user` (announcing
/// it on stdout) and waits to be killed.
pub fn child_delete_user(
    data: PathBuf,
    keys: PathBuf,
    cid: CollectionId,
    ids: Vec<String>,
    pause_at: &str,
) -> Result<(), DemoError> {
    let at = match pause_at {
        "wal" => Step::WalWriting,
        "committed" => Step::Committed,
        _ => return Err(e("--pause-at wal|committed")),
    };
    let opened = open(&OpenOptions::new(data, keys)).map_err(e)?;
    opened.engine.set_step_hook(Some(Box::new(move |s| {
        if s == at {
            println!("PAUSED at {s:?}");
            std::thread::sleep(std::time::Duration::from_secs(600));
        }
    })));
    let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
    let _ = opened.engine.delete_user(cid, &refs);
    Err(e("the child should have been killed"))
}
