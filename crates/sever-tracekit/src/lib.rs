//! `sever-tracekit`: read and replay trace files (Part 1, Build §2.4).
//!
//! The reference model writes a trace; this crate runs the same operations through the Rust index
//! and compares every value: placements, outcomes, the SHA-256 of every touched group's canonical
//! blob after every operation, and at each checkpoint every group's blob hash, the stats and the
//! top-k results for every query. The two implementations never call each other.
//!
//! This is test tooling, not the core: it reads files (the core crates do not, CLAUDE.md §7).

// `serde_json::Value` indexing (`v["key"]`, `v[0]`) returns `Null` for a missing key or index and
// never panics; that is the only indexing this crate does.
#![allow(clippy::indexing_slicing)]

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs::File;
use std::io::{BufRead, BufReader, Read};
use std::os::unix::fs::FileExt;
use std::path::{Path, PathBuf};

use serde_json::Value;
use sever_index::blob::{parse_blob, snapshot_from_members};
use sever_index::{
    DeleteRequest, GroupExtension, HmacSha512Scrambler, Index, IndexConfig, InsertRequest,
    NoExtension, Outcome, Placement,
};
use sever_partition::PartitionArtefact;
use sever_quant::QVec;
use sever_types::RecordId;
use sever_types::{CollectionId, Error, GroupId};
use sha2::{Digest, Sha256};

/// The fixed scrambling key of the test-only `IdScrambler` variant (Build §3.3 EP-2). Scrambled IDs
/// are never compared with the model, so any key gives the same observable results; production
/// keys come from the OS (§9.7).
pub const TEST_SCRAMBLE_KEY: [u8; 64] = [0x5a; 64];

type Ix = Index<NoExtension, HmacSha512Scrambler>;

/// A tracekit failure that stops the replay (not a mismatch).
#[derive(Debug)]
pub struct ReplayError(pub String);

fn fail(msg: impl Into<String>) -> ReplayError {
    ReplayError(msg.into())
}

/// Row-addressable float32 matrix in a `.npy` file (format 1.0, `'<f4'`, C order, 2-D).
pub struct Npy {
    file: File,
    data_offset: u64,
    /// Rows.
    pub rows: usize,
    /// Columns.
    pub cols: usize,
}

impl Npy {
    /// Opens and checks the header.
    pub fn open(path: &Path) -> Result<Self, ReplayError> {
        let mut file = File::open(path).map_err(|e| fail(format!("{}: {e}", path.display())))?;
        let mut pre = [0u8; 10];
        file.read_exact(&mut pre)
            .map_err(|e| fail(format!("npy header: {e}")))?;
        if pre.get(..6) != Some(b"\x93NUMPY".as_slice()) {
            return Err(fail("not a .npy file"));
        }
        let hlen = usize::from(u16::from_le_bytes([pre[8], pre[9]]));
        let mut header = vec![0u8; hlen];
        file.read_exact(&mut header)
            .map_err(|e| fail(format!("npy header: {e}")))?;
        let h = String::from_utf8_lossy(&header);
        if !h.contains("'descr': '<f4'") || !h.contains("'fortran_order': False") {
            return Err(fail("npy must be '<f4' in C order"));
        }
        let shape = h
            .split("'shape': (")
            .nth(1)
            .and_then(|s| s.split(')').next())
            .ok_or_else(|| fail("npy shape"))?;
        let dims: Vec<usize> = shape
            .split(',')
            .filter_map(|s| s.trim().parse().ok())
            .collect();
        let (rows, cols) = match dims.as_slice() {
            [r, c] => (*r, *c),
            _ => return Err(fail("npy must be 2-D")),
        };
        Ok(Self {
            file,
            data_offset: 10 + hlen as u64,
            rows,
            cols,
        })
    }

    /// Row `i` as float32.
    pub fn row(&self, i: usize) -> Result<Vec<f32>, ReplayError> {
        if i >= self.rows {
            return Err(fail("npy row out of range"));
        }
        let mut buf = vec![0u8; self.cols * 4];
        let at = self.data_offset + (i * self.cols * 4) as u64;
        self.file
            .read_exact_at(&mut buf, at)
            .map_err(|e| fail(format!("npy read: {e}")))?;
        Ok(buf
            .chunks_exact(4)
            .map(|c| f32::from_le_bytes(c.try_into().unwrap_or([0; 4])))
            .collect())
    }
}

/// The result of one replay.
#[derive(Debug, Default)]
pub struct Report {
    /// Operations replayed (inserts, delete_user calls, checkpoints).
    pub ops: u64,
    /// Values compared.
    pub compared: u64,
    /// Values that differed. Gate P1-T2: must be 0.
    pub mismatches: u64,
    /// Search results that named a deleted record. Gate P1-T5: must be 0.
    pub deleted_returned: u64,
    /// Touched groups checked after a deletion against the group rebuilt from its surviving
    /// members' own vectors (the survivors check, Build §4.7 L6; gate P1-T1).
    pub survivor_groups_checked: u64,
    /// Survivors checks that failed. Gate P1-T1: must be 0.
    pub survivor_failures: u64,
    /// Query–vector pairs scored by both kernels at the checkpoints (gate P1-T4).
    pub kernel_pairs: u64,
    /// Pairs whose scalar and dispatched (AVX2 when present) scores differ in any bit. P1-T4: 0.
    pub kernel_mismatches: u64,
    /// The first mismatches, for the log.
    pub first: Vec<String>,
}

impl Report {
    fn check(&mut self, ok: bool, what: impl FnOnce() -> String) {
        self.compared += 1;
        if !ok {
            self.mismatches += 1;
            if self.first.len() < 20 {
                self.first.push(what());
            }
        }
    }
}

fn blob_hash(ix: &Ix, g: &GroupId) -> String {
    ix.blob(g)
        .map_or_else(String::new, |b| hex(&Sha256::digest(b)))
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

/// Replays `trace` with paths resolved against `root`.
pub fn replay(trace: &Path, root: &Path) -> Result<Report, ReplayError> {
    let file = File::open(trace).map_err(|e| fail(format!("{}: {e}", trace.display())))?;
    let mut lines = BufReader::new(file).lines();
    let header: Value = match lines.next() {
        Some(Ok(l)) => serde_json::from_str(&l).map_err(|e| fail(format!("header: {e}")))?,
        _ => return Err(fail("empty trace")),
    };
    let s = |k: &str| {
        header[k]
            .as_str()
            .map(str::to_owned)
            .ok_or_else(|| fail(format!("header.{k}")))
    };
    let art_path: PathBuf = root.join(s("artefact")?);
    let art_bytes =
        std::fs::read(&art_path).map_err(|e| fail(format!("{}: {e}", art_path.display())))?;
    if hex(&Sha256::digest(&art_bytes)) != s("artefact_sha256")? {
        return Err(fail("artefact hash differs from the trace header"));
    }
    let art = PartitionArtefact::parse(&art_bytes).map_err(|e| fail(format!("artefact: {e}")))?;
    let cfg = IndexConfig {
        spawning_enabled: header["spawning"].as_bool().unwrap_or(true),
        spawn_target: header["spawn_target"].as_u64().unwrap_or(200) as usize,
    };
    let mut ix: Ix = Index::new(
        &art,
        cfg,
        NoExtension,
        HmacSha512Scrambler::new(&TEST_SCRAMBLE_KEY),
        CollectionId::from_bytes([0; 16]),
    )
    .map_err(|e| fail(format!("index: {e}")))?;
    let vectors = Npy::open(&root.join(s("vectors")?))?;
    let queries_npy = Npy::open(&root.join(s("queries")?))?;
    let n_queries = header["n_queries"].as_u64().unwrap_or(0) as usize;
    let queries: Vec<Vec<f32>> = (0..n_queries)
        .map(|i| queries_npy.row(i))
        .collect::<Result<_, _>>()?;
    let top_k = header["top_k"].as_u64().unwrap_or(100) as usize;

    let mut rep = Report::default();
    let mut deleted: HashSet<String> = HashSet::new();
    // Every live record's x̃, quantised here from its row, for the survivors check.
    let mut live: HashMap<String, QVec> = HashMap::new();
    let d = art.d;
    for line in lines {
        let line = line.map_err(|e| fail(format!("read: {e}")))?;
        let op: Value = serde_json::from_str(&line).map_err(|e| fail(format!("line: {e}")))?;
        rep.ops += 1;
        match op["t"].as_str() {
            Some("i") => {
                let id = op["id"].as_str().unwrap_or_default().to_owned();
                let row = op["row"].as_u64().unwrap_or(0) as usize;
                let vector = vectors.row(row)?;
                let xq = sever_quant::quantise(&vector, d).ok();
                let req = InsertRequest {
                    record_id: id.clone(),
                    vector,
                    credential: (),
                };
                match (ix.insert(req), op["e"].as_str()) {
                    (Ok(p), None) => {
                        let want = op["p"].as_str().unwrap_or_default();
                        rep.check(placement_text(&p) == want, || {
                            format!("insert {id}: placement {} vs {want}", placement_text(&p))
                        });
                        deleted.remove(&id);
                        if let Some(x) = xq {
                            live.insert(id.clone(), x);
                        }
                    }
                    (Err(e), Some(want)) => rep.check(error_kind(&e) == want, || {
                        format!("insert {id}: error {e:?} vs {want}")
                    }),
                    (got, want) => {
                        rep.check(false, || format!("insert {id}: {got:?} vs model {want:?}"))
                    }
                }
                compare_hashes(&ix, &op["g"], &mut rep, &id);
            }
            Some("d") => {
                let ids: Vec<String> = op["ids"]
                    .as_array()
                    .map(|a| {
                        a.iter()
                            .filter_map(|v| v.as_str().map(str::to_owned))
                            .collect()
                    })
                    .unwrap_or_default();
                let reqs = ids
                    .iter()
                    .map(|r| DeleteRequest {
                        record_id: r.clone(),
                    })
                    .collect();
                let outs = ix
                    .delete_many(reqs)
                    .map_err(|e| fail(format!("delete_many: {e}")))?;
                let want = op["o"].as_array().cloned().unwrap_or_default();
                rep.check(outs.len() == want.len(), || {
                    "delete_user: outcome count".to_owned()
                });
                for ((o, w), id) in outs.iter().zip(&want).zip(&ids) {
                    let got = match o {
                        Outcome::Deleted { from } => {
                            deleted.insert(id.clone());
                            live.remove(id);
                            from.as_text()
                        }
                        Outcome::AlreadyAbsent => "absent".to_owned(),
                        Outcome::Placed(_) => "placed?".to_owned(),
                    };
                    let w = w.as_str().unwrap_or_default();
                    rep.check(got == w, || format!("delete {id}: {got} vs {w}"));
                }
                compare_hashes(&ix, &op["g"], &mut rep, "delete_user");
                if let Some(obj) = op["g"].as_object() {
                    for g in obj.keys().filter_map(|g| GroupId::parse(g)) {
                        survivors_check(&ix, &g, &live, d, &mut rep);
                    }
                }
            }
            Some("c") => {
                let rung = op["rung"].as_u64().unwrap_or(0);
                let st = ix.stats();
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
                let got: BTreeMap<String, String> = ix
                    .group_ids()
                    .iter()
                    .map(|g| (g.as_text(), blob_hash(&ix, g)))
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
                for q in queries.iter().take(results.len()) {
                    kernel_check(&ix, q, &mut rep);
                }
                for (qi, (q, want)) in queries.iter().zip(&results).enumerate() {
                    let hits = sever_search::search(&ix, q, top_k)
                        .map_err(|e| fail(format!("search: {e}")))?;
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
                // An invariant failure is a mismatch like any other: counted, and the replay goes on.
                let inv = ix.check_invariants();
                rep.check(inv.is_ok(), || format!("rung {rung}: {inv:?}"));
            }
            _ => return Err(fail("unknown trace line")),
        }
    }
    Ok(rep)
}

/// The survivors check (Build §4.7 L6): the group's blob equals the blob of a group built from its
/// surviving members alone, each member's x̃ quantised here from the row it was inserted with.
fn survivors_check(ix: &Ix, g: &GroupId, live: &HashMap<String, QVec>, d: usize, rep: &mut Report) {
    rep.survivor_groups_checked += 1;
    let rebuilt = ix.blob(g).and_then(|blob| {
        let parsed = parse_blob(&blob, &<NoExtension as GroupExtension>::BLOB_MAGIC, 0).ok()?;
        let mut members = Vec::with_capacity(parsed.members.len());
        for (id, _) in &parsed.members {
            let rid = RecordId::from_bytes(id).ok()?;
            let x = live.get(rid.as_str())?;
            members.push((rid, x));
        }
        let refs: Vec<(&RecordId, &QVec, &())> =
            members.iter().map(|(r, x)| (r, *x, &())).collect();
        Some(snapshot_from_members(&NoExtension, d, &refs).blob == blob)
    });
    if rebuilt != Some(true) {
        rep.survivor_failures += 1;
        rep.check(false, || {
            format!("survivors check failed for {}", g.as_text())
        });
    }
}

/// P1-T4: every query–vector pair the search scores, scored by the scalar kernel and by the
/// dispatched kernel (AVX2 when the CPU has it), bit for bit.
fn kernel_check(ix: &Ix, q: &[f32], rep: &mut Report) {
    let probed: HashSet<GroupId> = sever_search::probed_groups(ix, q).into_iter().collect();
    let d = q.len();
    for g in ix.search_groups().filter(|g| probed.contains(&g.id)) {
        for row in g.rows.chunks_exact(d) {
            rep.kernel_pairs += 1;
            let (a, b) = (
                sever_search::kernel::score_scalar(q, row),
                sever_search::kernel::score(q, row),
            );
            if a.to_bits() != b.to_bits() {
                rep.kernel_mismatches += 1;
                rep.check(false, || format!("kernel: scalar {a} vs dispatched {b}"));
            }
        }
    }
}

fn compare_hashes(ix: &Ix, want: &Value, rep: &mut Report, what: &str) {
    if let Some(obj) = want.as_object() {
        for (g, h) in obj {
            let gid = GroupId::parse(g);
            let got = gid.map(|g| blob_hash(ix, &g)).unwrap_or_default();
            rep.check(Some(got.as_str()) == h.as_str(), || {
                format!("{what}: blob of {g} differs")
            });
        }
    }
}
