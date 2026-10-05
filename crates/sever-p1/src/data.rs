//! Demo data (Build §2.7, §4.9): the `nq-10k` and `nq-100k` slices of the P0 corpus, or the
//! offline small fixture. Passage text is never read (CLAUDE.md §8).

use std::fs::File;
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom};
use std::path::Path;

use sever_partition::PartitionArtefact;
use sha2::{Digest, Sha256};

/// A demo failure: a missing file, a malformed input, or an engine error.
#[derive(Debug)]
pub struct DemoError(pub String);

impl core::fmt::Display for DemoError {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for DemoError {}

impl From<sever_types::Error> for DemoError {
    fn from(e: sever_types::Error) -> Self {
        Self(format!("engine: {e}"))
    }
}

fn err(msg: impl Into<String>) -> DemoError {
    DemoError(msg.into())
}

/// Everything the demo streams, in stream order.
pub struct Dataset {
    /// `nq-10k`, `nq-100k` or `synthetic`.
    pub name: String,
    /// The run seed (selects the partition artefact; overview §10.6).
    pub seed: u64,
    /// Dimension.
    pub d: usize,
    /// Record IDs in stream order.
    pub ids: Vec<String>,
    /// Each record's cohort (article title, overview §10.8), row for row with `ids`.
    pub cohorts: Vec<String>,
    /// Vectors, `d` float32 per record, row for row with `ids`.
    pub vectors: Vec<f32>,
    /// Queries, `d` float32 each (empty for the synthetic fixture).
    pub queries: Vec<f32>,
    /// The frozen partition.
    pub artefact: PartitionArtefact,
    /// SHA-256 of the artefact file.
    pub artefact_sha256: String,
    /// §7.4 flush size (200 in v1; 8 for the small fixture, gap G-10).
    pub spawn_target: usize,
    /// How the stream is ordered, for the report.
    pub stream_order: &'static str,
}

impl Dataset {
    /// Row `i`'s vector.
    pub fn vector(&self, i: usize) -> Option<&[f32]> {
        self.vectors.get(i * self.d..(i + 1) * self.d)
    }

    /// Number of queries.
    pub fn n_queries(&self) -> usize {
        self.queries.len() / self.d.max(1)
    }

    /// Query `q`.
    pub fn query(&self, q: usize) -> Option<&[f32]> {
        self.queries.get(q * self.d..(q + 1) * self.d)
    }
}

fn read_file(path: &Path) -> Result<Vec<u8>, DemoError> {
    std::fs::read(path).map_err(|e| err(format!("{}: {e}", path.display())))
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn load_artefact(path: &Path) -> Result<(PartitionArtefact, String), DemoError> {
    let bytes = read_file(path).map_err(|e| {
        err(format!(
            "{e}\n  build it with: PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m \
             sever_partition.build --seed <seed>"
        ))
    })?;
    let sha = hex(&Sha256::digest(&bytes));
    Ok((PartitionArtefact::parse(&bytes)?, sha))
}

/// The first `rows` rows of a 2-D little-endian float32 `.npy` file (format 1.0, C order).
pub fn read_npy_prefix(path: &Path, rows: Option<usize>) -> Result<(Vec<f32>, usize), DemoError> {
    let mut f = File::open(path).map_err(|e| err(format!("{}: {e}", path.display())))?;
    let mut pre = [0u8; 10];
    f.read_exact(&mut pre)
        .map_err(|e| err(format!("npy: {e}")))?;
    let [m0, m1, m2, m3, m4, m5, _, _, l0, l1] = pre;
    if [m0, m1, m2, m3, m4, m5] != *b"\x93NUMPY" {
        return Err(err("not a .npy file"));
    }
    let mut header = vec![0u8; usize::from(u16::from_le_bytes([l0, l1]))];
    f.read_exact(&mut header)
        .map_err(|e| err(format!("npy: {e}")))?;
    let h = String::from_utf8_lossy(&header);
    if !h.contains("'descr': '<f4'") || !h.contains("'fortran_order': False") {
        return Err(err("npy must be '<f4' in C order"));
    }
    let dims: Vec<usize> = h
        .split("'shape': (")
        .nth(1)
        .and_then(|s| s.split(')').next())
        .unwrap_or("")
        .split(',')
        .filter_map(|s| s.trim().parse().ok())
        .collect();
    let [total, cols] = dims.as_slice() else {
        return Err(err("npy must be 2-D"));
    };
    let n = rows.unwrap_or(*total);
    if n > *total {
        return Err(err(format!("npy has {total} rows, {n} requested")));
    }
    let start = 10 + header.len() as u64;
    f.seek(SeekFrom::Start(start))
        .map_err(|e| err(format!("npy: {e}")))?;
    let mut buf = vec![0u8; n * cols * 4];
    f.read_exact(&mut buf)
        .map_err(|e| err(format!("npy: {e}")))?;
    let out = buf
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes(c.try_into().unwrap_or([0; 4]))) // chunks are exactly 4
        .collect();
    Ok((out, *cols))
}

/// The pinned SHA-256 of `datasets/<rel>` from `datasets/MANIFEST.sha256`.
fn manifest_sha(root: &Path, rel: &str) -> Result<String, DemoError> {
    let text = std::fs::read_to_string(root.join("datasets/MANIFEST.sha256"))
        .map_err(|e| err(format!("datasets/MANIFEST.sha256: {e}")))?;
    text.lines()
        .find_map(|l| {
            l.split_once("  ")
                .filter(|(_, name)| *name == rel)
                .map(|(sha, _)| sha.to_owned())
        })
        .ok_or_else(|| err(format!("{rel} is not in the manifest")))
}

/// The `id` and `cohort` of the first `rows` passages (DB-59: every slice is a prefix), from the
/// export written by `python -m sever_testkit.slices`. The export must name the manifest hash of the
/// passages file it was made from.
fn read_ids_cohorts(root: &Path, rows: usize) -> Result<(Vec<String>, Vec<String>), DemoError> {
    let path = root.join("artefacts/nq_1m.ids.jsonl");
    let file = File::open(&path).map_err(|e| {
        err(format!(
            "{}: {e}\n  export it with: PYTHONPATH=python uv run python -m sever_testkit.slices",
            path.display()
        ))
    })?;
    let mut lines = BufReader::new(file).lines();
    let header: serde_json::Value = lines
        .next()
        .and_then(Result::ok)
        .and_then(|l| serde_json::from_str(&l).ok())
        .ok_or_else(|| err("id export: no header"))?;
    let pinned = manifest_sha(root, "processed/nq_1m/passages.parquet")?;
    if header.get("format").and_then(|v| v.as_str()) != Some("sever-ids-1")
        || header.get("passages_sha256").and_then(|v| v.as_str()) != Some(pinned.as_str())
    {
        return Err(err(
            "id export does not match the pinned passages file; re-run sever_testkit.slices",
        ));
    }
    let mut ids = Vec::with_capacity(rows);
    let mut cohorts = Vec::with_capacity(rows);
    for line in lines.take(rows) {
        let line = line.map_err(|e| err(format!("id export: {e}")))?;
        let (id, cohort): (String, String) =
            serde_json::from_str(&line).map_err(|e| err(format!("id export: {e}")))?;
        ids.push(id);
        cohorts.push(cohort);
    }
    if ids.len() != rows {
        return Err(err("id export is shorter than the slice"));
    }
    Ok((ids, cohorts))
}

/// `nq-10k` or `nq-100k` (overview §10.4, DB-59) with `artefacts/partition-seed<seed>.svp`.
/// The stream is in corpus order: the demo shows one deletion, not an experiment, so it does not
/// use the experiments' seed-derived stream order (overview §10.7).
pub fn load_nq(root: &Path, name: &str, seed: u64) -> Result<Dataset, DemoError> {
    let rows = match name {
        "nq-10k" => 10_000,
        "nq-100k" => 100_000,
        _ => return Err(err(format!("unknown data slice {name:?}"))),
    };
    let (artefact, artefact_sha256) =
        load_artefact(&root.join(format!("artefacts/partition-seed{seed}.svp")))?;
    let (ids, cohorts) = read_ids_cohorts(root, rows)?;
    let (vectors, d) = read_npy_prefix(
        &root.join("datasets/processed/nq_1m/embeddings.npy"),
        Some(rows),
    )?;
    let (queries, dq) = read_npy_prefix(
        &root.join("datasets/processed/nq_queries/embeddings.npy"),
        None,
    )?;
    if d != artefact.d || dq != d {
        return Err(err("vector dimension does not match the artefact"));
    }
    Ok(Dataset {
        name: name.to_owned(),
        seed,
        d,
        ids,
        cohorts,
        vectors,
        queries,
        artefact,
        artefact_sha256,
        spawn_target: sever_types::constants::SPAWN_TARGET_SIZE,
        stream_order: "corpus order",
    })
}

fn hex_f32_row(s: &str, d: usize) -> Result<Vec<f32>, DemoError> {
    let b = s.as_bytes();
    if b.len() != 8 * d {
        return Err(err("fixture row has the wrong length"));
    }
    let byte = |i: usize| -> Result<u8, DemoError> {
        let pair = b.get(2 * i..2 * i + 2).ok_or_else(|| err("fixture hex"))?;
        let s = core::str::from_utf8(pair).map_err(|_| err("fixture hex"))?;
        u8::from_str_radix(s, 16).map_err(|_| err("fixture hex"))
    };
    (0..d)
        .map(|j| {
            Ok(f32::from_le_bytes([
                byte(4 * j)?,
                byte(4 * j + 1)?,
                byte(4 * j + 2)?,
                byte(4 * j + 3)?,
            ]))
        })
        .collect()
}

/// The offline small fixture (Build §2.7: `d = 16`, 4 frozen groups, spawn size 8): the golden
/// artefact and the golden fixture vectors. 120 in-distribution rows (`syn-ref-NNN`) and 120
/// out-of-distribution rows (`syn-live-NNN`) are interleaved, so flushes happen mid-stream. Cohort
/// `c` holds the rows whose number is `c` mod 40: three of each kind.
pub fn load_synthetic(root: &Path) -> Result<Dataset, DemoError> {
    let (artefact, artefact_sha256) = load_artefact(&root.join("golden/p1_partition_small.svp"))?;
    let raw = read_file(&root.join("golden/p1_fixture_vectors.json"))?;
    let v: serde_json::Value =
        serde_json::from_slice(&raw).map_err(|e| err(format!("fixture json: {e}")))?;
    let d = artefact.d;
    let rows = |key: &str| -> Result<Vec<Vec<f32>>, DemoError> {
        v.get(key)
            .and_then(|r| r.as_array())
            .ok_or_else(|| err(format!("fixture has no {key:?} rows")))?
            .iter()
            .map(|r| hex_f32_row(r.as_str().unwrap_or(""), d))
            .collect()
    };
    let (refs, live) = (rows("ref")?, rows("live")?);
    let mut ids = Vec::new();
    let mut cohorts = Vec::new();
    let mut vectors = Vec::new();
    for (i, (a, b)) in refs.iter().zip(&live).enumerate() {
        for (kind, x) in [("ref", a), ("live", b)] {
            ids.push(format!("syn-{kind}-{i:03}"));
            cohorts.push(format!("cohort-{:02}", i % 40));
            vectors.extend_from_slice(x);
        }
    }
    Ok(Dataset {
        name: "synthetic".to_owned(),
        seed: artefact.seed,
        d,
        ids,
        cohorts,
        vectors,
        queries: Vec::new(),
        artefact,
        artefact_sha256,
        spawn_target: 8,
        stream_order: "ref and live rows interleaved",
    })
}
