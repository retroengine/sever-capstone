//! `sever-ex2`: overview EX-2's engine side (Build 3-4 §2.8 "Forensics"; DB-54 `key-export`). The
//! database lives on a mounted disk image; the orchestrator (`sever_experiments.ex2`) mounts,
//! runs one command, unmounts and scans the raw image with `sever-scan`.
//!
//! ```text
//! sever-ex2 ingest --dir MNT --work DIR --artefact FILE [--allow-unsafe-memory] [--allow-unsafe-fs]
//! sever-ex2 rung   --dir MNT --work DIR --cohorts FILE  [--allow-unsafe-memory] [--allow-unsafe-fs]
//! sever-ex2 targets --dir MNT --work DIR --controls N --out FILE
//! ```
//!
//! `ingest` inserts every row of `DIR/stream.f32` (row-major `f32`) with the passage of the same
//! line of `DIR/stream.jsonl` (`{"id", "passage"}`); `rung` deletes each cohort of the file (a JSON
//! list of ID lists) with one `delete_user` and checks every certificate's signature; both end
//! with a storage checkpoint and a clean shutdown. `targets` writes the scanner's targets: every
//! record deleted so far, `N` live records as positive controls, and every key the build ever
//! generated that is not in a key-file slot now (no such key may be on the image in the clear).
//!
//! Instrumentation outside the image, in `--work` (mode 0600, deleted by the orchestrator after
//! the scan): each record's `r_t` (the scanner looks for it) and every generated key. Nothing is
//! printed but counts.

use std::collections::{BTreeSet, HashMap};
use std::fs::{File, OpenOptions as FsOpen};
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::Mutex;

use rand_core::{OsRng, RngCore};
use sever_commit::InsertCredential;
use sever_crypto::{KeyPair, Scalar, commit_record, encode_point, insert_message};
use sever_db::{Deleted, OpenOptions, cid_hex, open, parse_cid};
use sever_engine::{CollectionOptions, InsertRequest};
use sever_index::IdScrambler;
use sever_keys::file::{HEADER_BYTES, SLOT_BYTES, SlotState, decode_slot};
use sever_platform::Overrides;
use sever_types::{CollectionId, RecordId};

type Fail = Box<dyn std::error::Error>;

const D: usize = 384;

struct Args(HashMap<String, String>);

impl Args {
    fn parse(it: impl Iterator<Item = String>) -> Self {
        let mut m = HashMap::new();
        let mut it = it.peekable();
        while let Some(k) = it.next() {
            if let Some(name) = k.strip_prefix("--") {
                let v = match it.peek() {
                    Some(n) if !n.starts_with("--") => it.next().unwrap_or_default(),
                    _ => String::new(),
                };
                m.insert(name.to_owned(), v);
            }
        }
        Self(m)
    }
    fn get(&self, k: &str) -> Result<&str, Fail> {
        Ok(self
            .0
            .get(k)
            .map(String::as_str)
            .ok_or(format!("--{k} is required"))?)
    }
    fn path(&self, k: &str) -> Result<PathBuf, Fail> {
        Ok(PathBuf::from(self.get(k)?))
    }
}

fn private_append(path: &Path) -> Result<File, Fail> {
    Ok(FsOpen::new()
        .create(true)
        .append(true)
        .mode(0o600)
        .open(path)?)
}

/// Every generated key goes to `work/keys.bin` (DB-54 `key-export`).
fn export_keys(work: &Path) -> Result<(), Fail> {
    let f = Mutex::new(private_append(&work.join("keys.bin"))?);
    sever_keys::export::set_sink(Box::new(move |k: &[u8]| {
        if let Ok(mut f) = f.lock() {
            let _ = f.write_all(k);
        }
    }));
    Ok(())
}

/// Diagnosis only (`--poison`): prints every failing file operation (operation, path, error).
struct Trace(std::sync::Arc<dyn sever_vfs::Vfs>);
struct TraceFile(Box<dyn sever_vfs::VfsFile>, String);

fn tr<T>(
    op: &str,
    path: &str,
    r: Result<T, sever_vfs::VfsError>,
) -> Result<T, sever_vfs::VfsError> {
    if let Err(e) = &r {
        eprintln!("vfs: {op} {path}: {e:?}");
    }
    r
}

impl sever_vfs::VfsFile for TraceFile {
    fn read_at(&self, o: u64, b: &mut [u8]) -> Result<usize, sever_vfs::VfsError> {
        tr("read_at", &self.1, self.0.read_at(o, b))
    }
    fn write_at(&mut self, o: u64, d: &[u8]) -> Result<(), sever_vfs::VfsError> {
        tr("write_at", &self.1, self.0.write_at(o, d))
    }
    fn append(&mut self, d: &[u8]) -> Result<u64, sever_vfs::VfsError> {
        tr("append", &self.1, self.0.append(d))
    }
    fn truncate(&mut self, l: u64) -> Result<(), sever_vfs::VfsError> {
        tr("truncate", &self.1, self.0.truncate(l))
    }
    fn len(&self) -> Result<u64, sever_vfs::VfsError> {
        tr("len", &self.1, self.0.len())
    }
    fn fsync(&mut self) -> Result<(), sever_vfs::VfsError> {
        tr("fsync", &self.1, self.0.fsync())
    }
}

impl sever_vfs::Vfs for Trace {
    fn open(
        &self,
        p: &str,
        m: sever_vfs::OpenMode,
    ) -> Result<Box<dyn sever_vfs::VfsFile>, sever_vfs::VfsError> {
        let f = tr("open", p, self.0.open(p, m))?;
        Ok(Box::new(TraceFile(f, p.to_owned())))
    }
    fn fsync_dir(&self, d: &str) -> Result<(), sever_vfs::VfsError> {
        tr("fsync_dir", d, self.0.fsync_dir(d))
    }
    fn rename(&self, f: &str, t: &str) -> Result<(), sever_vfs::VfsError> {
        tr("rename", &format!("{f} -> {t}"), self.0.rename(f, t))
    }
    fn unlink(&self, p: &str) -> Result<(), sever_vfs::VfsError> {
        tr("unlink", p, self.0.unlink(p))
    }
    fn list(&self, d: &str) -> Result<Vec<String>, sever_vfs::VfsError> {
        tr("list", d, self.0.list(d))
    }
    fn create_dir(&self, p: &str) -> Result<(), sever_vfs::VfsError> {
        tr("create_dir", p, self.0.create_dir(p))
    }
    fn remove_dir(&self, p: &str) -> Result<(), sever_vfs::VfsError> {
        tr("remove_dir", p, self.0.remove_dir(p))
    }
}

fn open_db(a: &Args) -> Result<sever_db::Opened, Fail> {
    if a.0.contains_key("trace-vfs") {
        let dir = a.path("dir")?;
        let v = |p: PathBuf| -> Result<std::sync::Arc<dyn sever_vfs::Vfs>, Fail> {
            Ok(std::sync::Arc::new(Trace(std::sync::Arc::new(
                sever_vfs::PosixVfs::new(p)?,
            ))))
        };
        let mut st = sever_db::Settings::new(D);
        st.engine.on_failure = sever_engine::FailurePolicy::Poison;
        let db = sever_db::open_on(v(dir.join("data"))?, v(dir.join("keys"))?, st)?;
        let lock = sever_engine::EngineLock::acquire(&dir.join("data"))?;
        return Ok(sever_db::Opened::new(
            db,
            lock,
            &dir.join("data"),
            vec![],
            false,
        )?);
    }
    let dir = a.path("dir")?;
    let mut o = OpenOptions::new(dir.join("data"), dir.join("keys"));
    o.d = D;
    if a.0.contains_key("poison") {
        // Diagnosis only: a storage failure is returned (and printed) instead of aborting.
        o.on_failure = sever_engine::FailurePolicy::Poison;
    }
    o.overrides = Overrides {
        allow_unsafe_memory: a.0.contains_key("allow-unsafe-memory"),
        allow_unsafe_fs: a.0.contains_key("allow-unsafe-fs"),
    };
    Ok(open(&o)?)
}

/// The stream: row-major vectors, and each row's `(record ID, passage)`.
type Stream = (Vec<f32>, Vec<(String, String)>);

fn rows(work: &Path) -> Result<Stream, Fail> {
    let mut raw = Vec::new();
    File::open(work.join("stream.f32"))?.read_to_end(&mut raw)?;
    let v = raw
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes(c.try_into().unwrap_or([0; 4])))
        .collect::<Vec<_>>();
    let mut meta = Vec::new();
    for line in BufReader::new(File::open(work.join("stream.jsonl"))?).lines() {
        let j: serde_json::Value = serde_json::from_str(&line?)?;
        meta.push((
            j.get("id").and_then(|x| x.as_str()).ok_or("id")?.to_owned(),
            j.get("passage")
                .and_then(|x| x.as_str())
                .ok_or("passage")?
                .to_owned(),
        ));
    }
    if v.len() != meta.len() * D {
        return Err("stream.f32 and stream.jsonl differ in length".into());
    }
    Ok((v, meta))
}

fn state(work: &Path) -> Result<serde_json::Value, Fail> {
    Ok(serde_json::from_str(&std::fs::read_to_string(
        work.join("state.json"),
    )?)?)
}

fn shut_down(o: sever_db::Opened) -> Result<(), Fail> {
    o.db.engine.storage_checkpoint_now()?;
    drop(o);
    Ok(())
}

fn ingest(a: &Args) -> Result<(), Fail> {
    let work = a.path("work")?;
    export_keys(&work)?;
    let (v, meta) = rows(&work)?;
    let o = open_db(a)?;
    let artefact = std::fs::read(a.get("artefact")?)?;
    let cid = o.db.create_collection(
        &artefact,
        CollectionOptions {
            spawn_target: 200,
            spawning_enabled: true,
            store_passages: true,
        },
    )?;
    let user = KeyPair::generate();
    let mut rt = private_append(&work.join("rt.jsonl"))?;
    let (mut inserted, mut refused) = (0u64, 0u64);
    for (i, (id, passage)) in meta.iter().enumerate() {
        let x = v.get(i * D..(i + 1) * D).ok_or("row")?;
        let q = sever_quant::quantise(x, D)?;
        let mut wide = [0u8; 64];
        OsRng.fill_bytes(&mut wide);
        let r_t = Scalar::from_bytes_mod_order_wide(&wide);
        let c_t = encode_point(
            &commit_record(o.db.generators(), q.as_slice(), &r_t).map_err(|_| "commit_record")?,
        );
        let req = InsertRequest {
            record_id: id.clone(),
            vector: x.to_vec(),
            credential: InsertCredential {
                collection_id: *cid.as_bytes(),
                c_t,
                r_t: r_t.to_bytes(),
                user_public_key: user.public(),
                signature: user.sign(&insert_message(cid.as_bytes(), &c_t)),
            },
            passage: Some(passage.clone().into_bytes()),
        };
        match o.db.insert(cid, req) {
            Ok(_) => {
                inserted += 1;
                let hex: String = r_t.to_bytes().iter().map(|b| format!("{b:02x}")).collect();
                writeln!(rt, "{}", serde_json::json!({"id": id, "r_t": hex}))?;
            }
            Err(_) => refused += 1,
        }
    }
    std::fs::write(
        work.join("state.json"),
        serde_json::json!({"cid": cid_hex(&cid)}).to_string(),
    )?;
    shut_down(o)?;
    println!(
        "{}",
        serde_json::json!({"inserted": inserted, "refused": refused})
    );
    Ok(())
}

fn rung(a: &Args) -> Result<(), Fail> {
    let work = a.path("work")?;
    export_keys(&work)?;
    let cid = parse_cid(
        state(&work)?
            .get("cid")
            .and_then(|x| x.as_str())
            .ok_or("cid")?,
    )
    .ok_or("cid")?;
    let cohorts: Vec<Vec<String>> =
        serde_json::from_str(&std::fs::read_to_string(a.path("cohorts")?)?)?;
    let o = open_db(a)?;
    let mut del = private_append(&work.join("deleted.txt"))?;
    let (mut deleted, mut absent, mut certs) = (0u64, 0u64, 0u64);
    for c in &cohorts {
        let ids: Vec<&str> = c.iter().map(String::as_str).collect();
        for (id, out) in ids.iter().zip(o.db.delete_user(cid, &ids)?) {
            match out {
                Deleted::Deleted { certificate, .. } => {
                    deleted += 1;
                    certs += u64::from(!certificate.is_empty());
                    writeln!(del, "{id}")?;
                }
                Deleted::AlreadyAbsent => absent += 1,
            }
        }
    }
    shut_down(o)?;
    println!(
        "{}",
        serde_json::json!({"deleted": deleted, "already_absent": absent, "certificates": certs})
    );
    Ok(())
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

/// Every key in a valid slot of `KEYS` now.
fn slot_keys(key_dir: &Path) -> Result<BTreeSet<[u8; 32]>, Fail> {
    let raw = std::fs::read(key_dir.join(sever_platform::KEYS_FILE))?;
    let mut out = BTreeSet::new();
    for s in raw
        .get(HEADER_BYTES..)
        .unwrap_or_default()
        .chunks_exact(SLOT_BYTES)
    {
        // The slot names its pair (§14.7), as the scanner reads it.
        let idx = u64::from_be_bytes(
            s.get(4..12)
                .and_then(|b| b.try_into().ok())
                .unwrap_or([0; 8]),
        );
        if let SlotState::Valid(r) = decode_slot(s, idx) {
            let mut k = [0u8; 32];
            k.copy_from_slice(r.key.as_bytes());
            out.insert(k);
        }
    }
    Ok(out)
}

fn targets(a: &Args) -> Result<(), Fail> {
    let work = a.path("work")?;
    let dir = a.path("dir")?;
    let n_controls: usize = a.get("controls")?.parse()?;
    let cid: CollectionId = parse_cid(
        state(&work)?
            .get("cid")
            .and_then(|x| x.as_str())
            .ok_or("cid")?,
    )
    .ok_or("cid")?;
    let (v, meta) = rows(&work)?;
    let mut rts: HashMap<String, String> = HashMap::new();
    for line in BufReader::new(File::open(work.join("rt.jsonl"))?).lines() {
        let j: serde_json::Value = serde_json::from_str(&line?)?;
        rts.insert(
            j.get("id").and_then(|x| x.as_str()).ok_or("id")?.to_owned(),
            j.get("r_t")
                .and_then(|x| x.as_str())
                .ok_or("r_t")?
                .to_owned(),
        );
    }
    let deleted: BTreeSet<String> = match File::open(work.join("deleted.txt")) {
        Ok(f) => BufReader::new(f).lines().collect::<Result<_, _>>()?,
        Err(_) => BTreeSet::new(),
    };
    let secrets = std::fs::read(dir.join("keys").join("SECRETS"))?;
    let k =
        sever_format::Secrets::parse(&secrets, sever_format::SEALER_AES_GCM_SIV)?.k_scramble()?;
    let scr = sever_index::HmacSha512Scrambler::new(&k);
    let target = |i: usize, id: &str| -> Result<serde_json::Value, Fail> {
        let x = v.get(i * D..(i + 1) * D).ok_or("row")?;
        let q = sever_quant::quantise(x, D)?;
        let sid = scr.scramble(&cid, &RecordId::new(id)?);
        Ok(serde_json::json!({
            "sid": hex(sid.as_bytes()),
            "x": q.as_slice(),
            "vector": x,
            "passage": hex(meta.get(i).ok_or("row")?.1.as_bytes()),
            "r_t": rts.get(id),
        }))
    };
    let mut del_t = Vec::new();
    let mut ctl_t = Vec::new();
    for (i, (id, _)) in meta.iter().enumerate() {
        if deleted.contains(id) {
            del_t.push(target(i, id)?);
        } else if ctl_t.len() < n_controls && rts.contains_key(id) {
            ctl_t.push(target(i, id)?);
        }
    }
    let live = slot_keys(&dir.join("keys"))?;
    let mut raw = Vec::new();
    File::open(work.join("keys.bin"))?.read_to_end(&mut raw)?;
    let all: BTreeSet<[u8; 32]> = raw
        .chunks_exact(32)
        .filter_map(|c| <[u8; 32]>::try_from(c).ok())
        .collect();
    let retired: Vec<String> = all.difference(&live).map(|k| hex(k)).collect();
    let doc = serde_json::json!({
        "d": D,
        "deleted": del_t,
        "controls": ctl_t,
        "retired_keys": retired,
    });
    let mut f = FsOpen::new()
        .create(true)
        .write(true)
        .truncate(true)
        .mode(0o600)
        .open(a.path("out")?)?;
    f.write_all(doc.to_string().as_bytes())?;
    println!(
        "{}",
        serde_json::json!({"deleted": del_t.len(), "controls": ctl_t.len(), "keys_generated": all.len(), "keys_in_slots": live.len(), "keys_searched": retired.len()})
    );
    Ok(())
}

fn main() -> ExitCode {
    let mut it = std::env::args().skip(1);
    let cmd = it.next().unwrap_or_default();
    let a = Args::parse(it);
    let r = match cmd.as_str() {
        "ingest" => ingest(&a),
        "rung" => rung(&a),
        "targets" => targets(&a),
        _ => Err("usage: sever-ex2 ingest|rung|targets ...".into()),
    };
    match r {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("sever-ex2: {e}");
            ExitCode::FAILURE
        }
    }
}
