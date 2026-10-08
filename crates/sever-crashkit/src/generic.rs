//! Generic records first (overview EX-1 step 1, Build §5.7 L10 step 1): a key–value store of
//! fixed-size records on the WAL and a snapshot file, with no index code, crashed at every VFS
//! operation of every transaction under rotating policies, and compared with an in-memory model.
//!
//! Snapshot `SNAPSHOT`: `b"SVDBKVSN" ‖ u64be first_wal_seq ‖ u64be next_txn ‖ u64be count ‖
//! (u64be key ‖ value (32))* ‖ u32be crc32c`, installed with `durable::replace_file`. A WAL record
//! (`EXTENSION`, participant 0) is `u8 op (1 put, 2 delete) ‖ u64be key ‖ value (32)`.

use std::collections::BTreeMap;
use std::io::Write;
use std::sync::Arc;

use serde_json::json;
use sever_format::RecordType;
use sever_format::codec::{Reader, Writer, crc};
use sever_types::Error;
use sever_vfs::rng::SplitMix64;
use sever_vfs::{CrashPolicy, FaultPlan, OpenMode, SimVfs, Vfs, durable, read_all};
use sever_wal::{Wal, WalConfig};

const SNAP: &str = "SNAPSHOT";
const MAGIC: &[u8; 8] = b"SVDBKVSN";
const SEGMENT: u64 = 2_048;

type Map = BTreeMap<u64, [u8; 32]>;

fn bad(check: &'static str) -> Error {
    Error::IntegrityViolation { invariant: check }
}

fn io<T>(r: Result<T, sever_vfs::VfsError>) -> Result<T, Error> {
    r.map_err(|_| Error::DurabilityFailure)
}

/// The store.
pub struct Kv {
    vfs: Arc<dyn Vfs>,
    wal: Wal,
    /// The current map.
    pub map: Map,
}

fn encode_snapshot(map: &Map, first_wal_seq: u64, next_txn: u64) -> Vec<u8> {
    let mut w = Writer::new();
    w.bytes(MAGIC)
        .u64(first_wal_seq)
        .u64(next_txn)
        .u64(map.len() as u64);
    for (k, v) in map {
        w.u64(*k).bytes(v);
    }
    let c = crc(&w.0);
    w.u32(c);
    w.finish()
}

fn parse_snapshot(b: &[u8]) -> Result<(Map, u64, u64), Error> {
    let (body, tail) = b.split_last_chunk::<4>().ok_or(bad("snapshot"))?;
    if crc(body) != u32::from_be_bytes(*tail) {
        return Err(bad("snapshot crc"));
    }
    let mut r = Reader::new(body, "snapshot");
    if r.array::<8>()? != *MAGIC {
        return Err(bad("snapshot magic"));
    }
    let (first, next) = (r.u64()?, r.u64()?);
    let mut map = Map::new();
    for _ in 0..r.count(1 << 20)? {
        let k = r.u64()?;
        map.insert(k, r.array()?);
    }
    r.end()?;
    Ok((map, first, next))
}

impl Kv {
    /// Opens (recovering) or creates the store.
    pub fn open(vfs: Arc<dyn Vfs>) -> Result<Self, Error> {
        let cfg = WalConfig {
            sealer_id: 0,
            segment_bytes: SEGMENT,
        };
        let snap = match vfs.open(SNAP, OpenMode::Existing) {
            Ok(f) => Some(io(read_all(f.as_ref()))?),
            Err(sever_vfs::VfsError::NotFound) => None,
            Err(_) => return Err(Error::DurabilityFailure),
        };
        let Some(snap) = snap else {
            // A creation interrupted before SNAPSHOT existed holds nothing: start again.
            if let Ok(names) = vfs.list(sever_wal::WAL_DIR) {
                for n in names {
                    io(vfs.unlink(&format!("{}/{n}", sever_wal::WAL_DIR)))?;
                }
                io(vfs.remove_dir(sever_wal::WAL_DIR))?;
                io(durable::sync_dir(vfs.as_ref(), ""))?;
            }
            let wal = Wal::create(Arc::clone(&vfs), cfg, 1, 1)?;
            io(durable::replace_file(
                vfs.as_ref(),
                SNAP,
                &encode_snapshot(&Map::new(), 1, 1),
            ))?;
            return Ok(Self {
                vfs,
                wal,
                map: Map::new(),
            });
        };
        let (mut map, first, next) = parse_snapshot(&snap)?;
        let (wal, txns, _) = Wal::recover(Arc::clone(&vfs), cfg, first, next)?;
        for r in txns.iter().flat_map(|t| &t.records) {
            let mut rd = Reader::new(&r.payload, "kv record");
            let (op, k, v) = (rd.u8()?, rd.u64()?, rd.array::<32>()?);
            rd.end()?;
            match op {
                1 => {
                    map.insert(k, v);
                }
                2 => {
                    map.remove(&k);
                }
                _ => return Err(bad("kv op")),
            }
        }
        Ok(Self { vfs, wal, map })
    }

    /// One transaction: every put or delete, all or nothing.
    pub fn txn(&mut self, ops: &[(u64, Option<[u8; 32]>)]) -> Result<(), Error> {
        let records: Vec<(RecordType, Vec<u8>)> = ops
            .iter()
            .map(|(k, v)| {
                let mut w = Writer::new();
                w.u8(if v.is_some() { 1 } else { 2 })
                    .u64(*k)
                    .bytes(&v.unwrap_or([0; 32]));
                (RecordType::Extension, w.finish())
            })
            .collect();
        self.wal.commit(&records)?;
        for (k, v) in ops {
            match v {
                Some(v) => self.map.insert(*k, *v),
                None => self.map.remove(k),
            };
        }
        Ok(())
    }

    /// Snapshot, then drop the covered WAL segments.
    pub fn snapshot(&mut self) -> Result<(), Error> {
        let first = self.wal.next_wal_seq();
        let bytes = encode_snapshot(&self.map, first, self.wal.next_txn_id());
        io(durable::replace_file(self.vfs.as_ref(), SNAP, &bytes))?;
        self.wal.remove_covered(first)?;
        Ok(())
    }
}

/// One step of the generic workload.
#[derive(Clone, Debug)]
enum Step {
    Txn(Vec<(u64, Option<[u8; 32]>)>),
    Snapshot,
}

fn workload(seed: u64, n: usize) -> Vec<Step> {
    let mut r = SplitMix64::new(seed);
    (0..n)
        .map(|i| {
            if i % 25 == 24 {
                Step::Snapshot
            } else {
                Step::Txn(
                    (0..1 + r.below(4))
                        .map(|_| {
                            let k = r.below(50);
                            let v = (!r.one_in(4)).then(|| [r.below(256) as u8; 32]);
                            (k, v)
                        })
                        .collect(),
                )
            }
        })
        .collect()
}

fn exec(kv: &mut Kv, s: &Step) -> Result<(), Error> {
    match s {
        Step::Txn(ops) => kv.txn(ops),
        Step::Snapshot => kv.snapshot(),
    }
}

/// Generic campaign counts.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GenericSummary {
    /// Crash points.
    pub points: u64,
    /// Recovered maps that are neither allowed state.
    pub wrong_states: u64,
    /// Recoveries that refused to start.
    pub refusals: u64,
}

/// Runs the generic campaign: `n` steps, a crash at every VFS operation of each.
pub fn run(seed: u64, n: usize, out: &mut dyn Write) -> Result<GenericSummary, String> {
    let steps = workload(seed, n);
    // The model: the map after each prefix of steps (a snapshot changes nothing).
    let mut models = vec![Map::new()];
    let mut m = Map::new();
    for s in &steps {
        if let Step::Txn(ops) = s {
            for (k, v) in ops {
                match v {
                    Some(v) => m.insert(*k, *v),
                    None => m.remove(k),
                };
            }
        }
        models.push(m.clone());
    }
    let main = SimVfs::new();
    let mut kv = Kv::open(Arc::new(main.clone())).map_err(|e| e.to_string())?;
    let mut sum = GenericSummary::default();
    let mut rotate = seed;
    for (i, s) in steps.iter().enumerate() {
        let base = main.fork();
        let probe = base.fork();
        let mut pk = Kv::open(Arc::new(probe.clone())).map_err(|e| e.to_string())?;
        probe.set_faults(FaultPlan::default());
        exec(&mut pk, s).map_err(|e| e.to_string())?;
        let ops = probe.ops_since_plan();
        exec(&mut kv, s).map_err(|e| e.to_string())?;
        for k in 1..=ops {
            rotate = rotate.wrapping_add(1);
            let policy = match rotate % 3 {
                0 => CrashPolicy::DropAll,
                1 => CrashPolicy::KeepAll,
                _ => CrashPolicy::Random(rotate),
            };
            let d = base.fork();
            {
                let mut ck = Kv::open(Arc::new(d.clone())).map_err(|e| e.to_string())?;
                d.set_faults(FaultPlan {
                    crash_at_op: Some(k),
                    tear_bytes: (rotate % 97) as usize,
                    ..FaultPlan::default()
                });
                if exec(&mut ck, s).is_ok() {
                    return Err(format!("step {i}, point {k}: no crash"));
                }
            }
            d.restart(policy);
            sum.points += 1;
            let ok = match Kv::open(Arc::new(d.clone())) {
                Ok(r) => {
                    let good = Some(&r.map) == models.get(i) || Some(&r.map) == models.get(i + 1);
                    if !good {
                        sum.wrong_states += 1;
                    }
                    good
                }
                Err(_) => {
                    sum.refusals += 1;
                    false
                }
            };
            let line = json!({"t": "generic", "step": i, "k": k, "ok": ok});
            writeln!(out, "{line}").map_err(|e| e.to_string())?;
        }
    }
    Ok(sum)
}

#[cfg(test)]
mod tests {
    use super::*;
    use sever_spec::spec;

    #[test]
    // oracle: A §12.3 recovered = the map after the acknowledged steps or one more (a plain BTreeMap); §12.7 creations, renames and unlinks are durable
    #[spec("SR-12.3-2", "SR-12.3-3", "SR-12.7-1")]
    fn p2_crashkit_generic_records_survive_a_crash_at_every_operation() {
        let mut sink = Vec::new();
        let s = run(42, 120, &mut sink).unwrap();
        assert!(s.points > 300, "{} crash points", s.points);
        assert_eq!((s.wrong_states, s.refusals), (0, 0));
    }
}
