//! `sever-scan`: the forensic scanner of overview EX-2 (Build 3-4 §2.8 Forensics, spec §16.3).
//!
//! It plays an attacker who holds the raw disk image, free space included, and nothing else:
//!
//! 1. **Known plaintext.** Every byte offset is checked for the deleted records' quantised vectors
//!    (`i32`, and widened to `i64`, both byte orders), their original `f32` vectors (both orders),
//!    every 32-byte window of their passage text, their `r_t`, and every retired key (the targets
//!    file; keys come from a `key-export` build, DB-54).
//! 2. **Carving.** Every WAL record (length, type, plausible sequence numbers and its CRC, §14.6)
//!    and every key-file slot (magic and CRC, §14.7) is cut out wherever it lies.
//! 3. **Every carved key on every carved ciphertext.** Group keys open accumulators and bucket
//!    blocks; bucket keys unwrap record keys; record keys open slot payloads. A finding is an old
//!    accumulator version that still opens, or a deleted record whose key or vector is recovered.
//!    The same pipeline recovering a **live** record's vector is the positive control.
//! 4. **Nonces.** Two distinct carved ciphertexts with one nonce are a finding (§13.2).
//!
//! Group keys of live domains are on the image by design (§13.1): erasure protects what was
//! deleted, not what is live.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::io::Read;
use std::path::Path;

use sever_commit::CommitmentExtension;
use sever_format::{CoreRecord, RecordType, WalParse, WalRecord};
use sever_keys::Domain;
use sever_keys::file::{SLOT_BYTES, SlotState, decode_slot};
use sever_seal::ad::Sid;
use sever_seal::block::{self, BucketKey};
use sever_seal::{AeadSealer, KeyRing, ad, aead};

/// What the scanner looks for. Deleted records are searched for; control records are live and
/// must be recovered through the carving pipeline (the scanner can see).
#[derive(Clone, Debug, Default)]
pub struct Targets {
    /// The vector dimension.
    pub d: usize,
    /// Records that were deleted.
    pub deleted: Vec<Target>,
    /// Live records the scanner must recover (positive controls).
    pub controls: Vec<Target>,
    /// Keys that must no longer exist anywhere (retired group, bucket and record keys).
    pub retired_keys: Vec<[u8; 32]>,
}

/// One record.
#[derive(Clone, Debug, Default)]
pub struct Target {
    /// Its scrambled ID (§9.7).
    pub sid: Vec<u8>,
    /// Its quantised vector.
    pub x: Vec<i32>,
    /// Its original vector.
    pub vector: Vec<f32>,
    /// Its passage text.
    pub passage: Vec<u8>,
    /// Its `r_t`.
    pub r_t: Option<[u8; 32]>,
}

/// The kind of a finding.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Kind {
    /// A deleted `x̃` as `i32`.
    PlaintextVector,
    /// A deleted `x̃` widened to `i64`.
    WidenedVector,
    /// A deleted original `f32` vector.
    FloatVector,
    /// 32 bytes of deleted passage text.
    PassageText,
    /// A deleted `r_t`.
    RecordScalar,
    /// A retired key.
    RetiredKey,
    /// An accumulator of a retired version opens under a key on the image.
    RetiredAccumulator,
    /// A deleted record's key is unwrapped by a bucket key on the image.
    DeletedRecordKey,
    /// A deleted record's vector is decrypted.
    DeletedPayload,
    /// Two distinct ciphertexts share one nonce.
    NonceReuse,
}

impl Kind {
    /// The kind's name in reports.
    pub fn name(self) -> &'static str {
        match self {
            Kind::PlaintextVector => "plaintext_vector",
            Kind::WidenedVector => "widened_vector",
            Kind::FloatVector => "float_vector",
            Kind::PassageText => "passage_text",
            Kind::RecordScalar => "r_t",
            Kind::RetiredKey => "retired_key",
            Kind::RetiredAccumulator => "retired_accumulator",
            Kind::DeletedRecordKey => "deleted_record_key",
            Kind::DeletedPayload => "deleted_payload",
            Kind::NonceReuse => "nonce_reuse",
        }
    }
}

/// One finding: what, where on the image, and for which deleted target (by index).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Finding {
    /// What was found.
    pub kind: Kind,
    /// The byte offset on the image.
    pub offset: u64,
    /// The deleted target it belongs to, if any.
    pub target: Option<usize>,
}

/// What a scan found.
#[derive(Clone, Debug, Default)]
pub struct Report {
    /// Every finding.
    pub findings: Vec<Finding>,
    /// For each control target: whether its vector was recovered.
    pub controls_recovered: Vec<bool>,
    /// WAL records carved.
    pub records: usize,
    /// Valid key-file slots carved.
    pub key_slots: usize,
    /// Accumulators, bucket blocks and envelopes carved.
    pub accumulators: usize,
    /// See [`Report::accumulators`].
    pub blocks: usize,
    /// See [`Report::accumulators`].
    pub envelopes: usize,
    /// Bytes scanned.
    pub bytes: u64,
}

impl Report {
    /// Findings by kind name.
    pub fn counts(&self) -> BTreeMap<&'static str, usize> {
        let mut m = BTreeMap::new();
        for f in &self.findings {
            *m.entry(f.kind.name()).or_default() += 1;
        }
        m
    }

    /// The report as JSON.
    pub fn to_json(&self) -> serde_json::Value {
        serde_json::json!({
            "bytes": self.bytes,
            "findings": self.findings.len(),
            "by_kind": self.counts(),
            "controls_recovered": self.controls_recovered,
            "carved": {
                "records": self.records,
                "key_slots": self.key_slots,
                "accumulators": self.accumulators,
                "blocks": self.blocks,
                "envelopes": self.envelopes,
            },
            "first": self.findings.iter().take(20).map(|f| serde_json::json!({
                "kind": f.kind.name(), "offset": f.offset, "target": f.target,
            })).collect::<Vec<_>>(),
        })
    }
}

const NEEDLE: usize = 32;
/// Bytes kept from the end of one chunk to the start of the next: a record or needle that starts
/// in a chunk is read whole if it is shorter than this.
pub const OVERLAP: usize = 4 << 20;

#[derive(Clone)]
struct Needle {
    bytes: [u8; NEEDLE],
    kind: Kind,
    target: Option<usize>,
}

/// A carved group header: `(domain, seal_version, n, sealed accumulator, offset)`.
type Header = (Domain, u64, u64, Vec<u8>, u64);

/// A carved slot payload: `(collection_id, sealed payload)`.
type Payload = ([u8; 16], Vec<u8>);

struct Carved {
    /// Every carved group header with an accumulator.
    headers: Vec<Header>,
    /// `(domain, group_key_version, block)`.
    blocks: Vec<(Domain, u64, Vec<u8>)>,
    /// `(domain, scrambled_id, envelope, offset)`.
    envelopes: Vec<(Domain, Sid, Vec<u8>, u64)>,
    /// Each scrambled ID's sealed payloads, with their collection.
    payloads: HashMap<Sid, Vec<Payload>>,
    /// `(domain → [(version, key bytes)])`.
    keys: BTreeMap<Domain, BTreeSet<(u64, [u8; 32])>>,
    /// nonce → first ciphertext digest seen with it, and the offset.
    nonces: HashMap<[u8; 12], (u64, u64)>,
    seen: BTreeSet<u64>,
}

/// An incremental scan: feed the image in chunks, then [`Scanner::finish`].
pub struct Scanner {
    targets: Targets,
    needles: HashMap<u64, Vec<Needle>>,
    first2: Vec<bool>,
    carved: Carved,
    layout: sever_format::Layout,
    report: Report,
}

fn key8(b: &[u8]) -> u64 {
    let mut a = [0u8; 8];
    a.copy_from_slice(b.get(..8).unwrap_or(&[0; 8]));
    u64::from_le_bytes(a)
}

fn fnv(b: &[u8]) -> u64 {
    b.iter().fold(0xcbf2_9ce4_8422_2325u64, |h, x| {
        (h ^ u64::from(*x)).wrapping_mul(0x0100_0000_01b3)
    })
}

fn window(bytes: &[u8]) -> Option<[u8; NEEDLE]> {
    let w: [u8; NEEDLE] = bytes.get(..NEEDLE)?.try_into().ok()?;
    (w.iter().any(|b| *b != 0)).then_some(w)
}

impl Scanner {
    /// A scanner for `targets`.
    pub fn new(targets: Targets) -> Self {
        let mut list: Vec<Needle> = Vec::new();
        let mut add = |bytes: Vec<u8>, kind: Kind, target: Option<usize>| {
            if let Some(w) = window(&bytes) {
                list.push(Needle {
                    bytes: w,
                    kind,
                    target,
                });
            }
        };
        for (i, t) in targets.deleted.iter().enumerate() {
            let x8 = t.x.get(..8).unwrap_or(&t.x);
            add(
                x8.iter().flat_map(|c| c.to_le_bytes()).collect(),
                Kind::PlaintextVector,
                Some(i),
            );
            add(
                x8.iter().flat_map(|c| c.to_be_bytes()).collect(),
                Kind::PlaintextVector,
                Some(i),
            );
            let x4 = t.x.get(..4).unwrap_or(&t.x);
            add(
                x4.iter()
                    .flat_map(|c| i64::from(*c).to_le_bytes())
                    .collect(),
                Kind::WidenedVector,
                Some(i),
            );
            add(
                x4.iter()
                    .flat_map(|c| i64::from(*c).to_be_bytes())
                    .collect(),
                Kind::WidenedVector,
                Some(i),
            );
            let v8 = t.vector.get(..8).unwrap_or(&t.vector);
            add(
                v8.iter().flat_map(|c| c.to_le_bytes()).collect(),
                Kind::FloatVector,
                Some(i),
            );
            add(
                v8.iter().flat_map(|c| c.to_be_bytes()).collect(),
                Kind::FloatVector,
                Some(i),
            );
            for w in t.passage.windows(NEEDLE) {
                add(w.to_vec(), Kind::PassageText, Some(i));
            }
            if let Some(r) = t.r_t {
                add(r.to_vec(), Kind::RecordScalar, Some(i));
            }
        }
        for k in &targets.retired_keys {
            add(k.to_vec(), Kind::RetiredKey, None);
        }
        let mut needles: HashMap<u64, Vec<Needle>> = HashMap::new();
        let mut first2 = vec![false; 1 << 16];
        for n in list {
            if let Some(f) =
                first2.get_mut(usize::from(u16::from_le_bytes([n.bytes[0], n.bytes[1]])))
            {
                *f = true;
            }
            needles.entry(key8(&n.bytes)).or_default().push(n);
        }
        let layout = sever_txn::layout_for::<CommitmentExtension>(
            targets.d,
            &AeadSealer::new(std::sync::Arc::new(KeyRing::new())),
        );
        let controls = targets.controls.len();
        Self {
            targets,
            needles,
            first2,
            carved: Carved {
                headers: Vec::new(),
                blocks: Vec::new(),
                envelopes: Vec::new(),
                payloads: HashMap::new(),
                keys: BTreeMap::new(),
                nonces: HashMap::new(),
                seen: BTreeSet::new(),
            },
            layout,
            report: Report {
                controls_recovered: vec![false; controls],
                ..Report::default()
            },
        }
    }

    fn finding(&mut self, kind: Kind, offset: u64, target: Option<usize>) {
        self.report.findings.push(Finding {
            kind,
            offset,
            target,
        });
    }

    fn nonce(&mut self, sealed: &[u8], offset: u64) {
        let Some(n) = sealed
            .get(..aead::NONCE_BYTES)
            .and_then(|n| <[u8; 12]>::try_from(n).ok())
        else {
            return;
        };
        let h = fnv(sealed);
        match self.carved.nonces.get(&n) {
            Some((h0, _)) if *h0 != h => self.finding(Kind::NonceReuse, offset, None),
            Some(_) => {}
            None => {
                self.carved.nonces.insert(n, (h, offset));
            }
        }
    }

    /// Scans `chunk`, which starts at image offset `base`. Positions from `limit` on are left to
    /// the next chunk (which repeats them), so nothing is counted twice.
    pub fn feed(&mut self, base: u64, chunk: &[u8], limit: usize) {
        let limit = limit.min(chunk.len());
        for p in 0..limit {
            let rest = chunk.get(p..).unwrap_or_default();
            let at = base + p as u64;
            // 1. Known plaintext.
            let two = rest
                .first_chunk::<2>()
                .map_or(0, |b| usize::from(u16::from_le_bytes(*b)));
            if rest.len() >= NEEDLE && self.first2.get(two).copied().unwrap_or(false) {
                if let Some(ns) = self.needles.get(&key8(rest)) {
                    let hits: Vec<(Kind, Option<usize>)> = ns
                        .iter()
                        .filter(|n| rest.get(..NEEDLE) == Some(&n.bytes[..]))
                        .map(|n| (n.kind, n.target))
                        .collect();
                    for (k, t) in hits {
                        self.finding(k, at, t);
                    }
                }
            }
            // 2a. Key-file slots: sector-aligned, magic first.
            if at % SLOT_BYTES as u64 == 0 && rest.get(..4) == Some(b"SVKS") {
                if let Some(s) = rest.get(..SLOT_BYTES) {
                    let idx = u64::from_be_bytes(
                        s.get(4..12)
                            .and_then(|b| b.try_into().ok())
                            .unwrap_or([0; 8]),
                    );
                    if let SlotState::Valid(r) = decode_slot(s, idx) {
                        let mut k = [0u8; 32];
                        k.copy_from_slice(r.key.as_bytes());
                        self.carved
                            .keys
                            .entry(r.domain)
                            .or_default()
                            .insert((r.key_version, k));
                        self.report.key_slots += 1;
                    }
                }
            }
            // 2b. WAL records: cheap filters before the CRC.
            if let Some(h) = rest.first_chunk::<16>() {
                let [l0, l1, l2, l3, ty, s0, s1, s2, _, _, _, _, _, t0, t1, t2] = *h;
                let len = u32::from_be_bytes([l0, l1, l2, l3]) as usize;
                // wal_seq and txn_id are far below 2^40: their top three bytes are zero.
                let plausible = len >= sever_format::wal::RECORD_OVERHEAD
                    && len <= rest.len()
                    && RecordType::from_byte(ty).is_some()
                    && [s0, s1, s2, t0, t1, t2] == [0; 6];
                if plausible {
                    if let WalParse::Record(r, _) = WalRecord::parse_next(rest) {
                        self.carve(&r, at);
                    }
                }
            }
        }
        self.report.bytes = self.report.bytes.max(base + limit as u64);
    }

    fn carve(&mut self, r: &WalRecord, at: u64) {
        let h = fnv(&r.encode());
        if !self.carved.seen.insert(h) {
            return;
        }
        self.report.records += 1;
        if let Some(v) = sever_erasure::parse_wal(r) {
            match v {
                sever_erasure::records::Value::Block(d, version, blk) => {
                    self.report.blocks += 1;
                    self.carved.blocks.push((d, version, blk));
                }
                sever_erasure::records::Value::Envelopes(d, entries) => {
                    for (sid, _, env) in entries {
                        self.report.envelopes += 1;
                        self.nonce(&env, at);
                        self.carved.envelopes.push((d, sid, env.to_vec(), at));
                    }
                }
                sever_erasure::records::Value::Drop(_) => {}
            }
            return;
        }
        if r.ty.is_participant() {
            return;
        }
        let layout = self.layout;
        let Ok(core) = CoreRecord::parse(r.ty, &r.payload, &|_| Some(layout)) else {
            return;
        };
        match core {
            CoreRecord::GroupHeader { cid, header }
            | CoreRecord::GroupCreate { cid, header, .. } => {
                if !header.sealed_accumulator.is_empty() {
                    self.report.accumulators += 1;
                    self.nonce(&header.sealed_accumulator, at);
                    let d = sever_seal::domain(&cid, &header.group_id);
                    self.carved.headers.push((
                        d,
                        header.seal_version,
                        header.n,
                        header.sealed_accumulator.clone(),
                        at,
                    ));
                }
            }
            CoreRecord::SlotPut {
                cid, group, slot, ..
            } => {
                let sid = *slot.scrambled_id.as_bytes();
                self.report.envelopes += 1;
                self.nonce(&slot.envelope, at);
                self.nonce(&slot.sealed_payload, at);
                let d = sever_seal::domain(&cid, &group);
                self.carved
                    .envelopes
                    .push((d, sid, slot.envelope.clone(), at));
                self.carved
                    .payloads
                    .entry(sid)
                    .or_default()
                    .push((*cid.as_bytes(), slot.sealed_payload.clone()));
            }
            _ => {}
        }
    }

    /// Tries every carved key on every carved ciphertext and returns the report.
    pub fn finish(mut self) -> Report {
        let keys = std::mem::take(&mut self.carved.keys);
        let live: BTreeMap<Domain, u64> = keys
            .iter()
            .filter_map(|(d, ks)| ks.iter().map(|(v, _)| *v).max().map(|v| (*d, v)))
            .collect();
        let gk = |k: &[u8; 32]| sever_keys::Key::from_bytes(k);
        // Accumulators of retired versions.
        let headers = std::mem::take(&mut self.carved.headers);
        for (d, v, n, ct, at) in &headers {
            let opened = keys.get(d).is_some_and(|ks| {
                ks.iter()
                    .any(|(_, k)| aead::open(&gk(k), &ad::accumulator(d, *v, *n), ct).is_ok())
            });
            if opened && live.get(d).is_some_and(|lv| v < lv) {
                self.finding(Kind::RetiredAccumulator, *at, None);
            }
        }
        // Bucket keys from every block a carved group key opens.
        let mut bks: BTreeMap<Domain, Vec<BucketKey>> = BTreeMap::new();
        for (d, v, blk) in std::mem::take(&mut self.carved.blocks) {
            for (_, k) in keys.get(&d).into_iter().flatten() {
                if let Ok(b) = block::decode_block(&gk(k), &d, v, &blk) {
                    bks.entry(d).or_default().extend(b);
                }
            }
        }
        // Record keys, then payloads.
        let deleted: HashMap<Vec<u8>, usize> = self
            .targets
            .deleted
            .iter()
            .enumerate()
            .map(|(i, t)| (t.sid.clone(), i))
            .collect();
        let controls: HashMap<Vec<u8>, usize> = self
            .targets
            .controls
            .iter()
            .enumerate()
            .map(|(i, t)| (t.sid.clone(), i))
            .collect();
        let envelopes = std::mem::take(&mut self.carved.envelopes);
        let mut reported: BTreeSet<(usize, Kind)> = BTreeSet::new();
        for (d, sid, env, at) in &envelopes {
            let del = deleted.get(&sid[..]).copied();
            let ctl = controls.get(&sid[..]).copied();
            if del.is_none() && ctl.is_none() {
                continue;
            }
            let b = usize::from(sever_keys::bucket_of(sid));
            let Some(rk) = bks.get(d).and_then(|ks| {
                ks.iter()
                    .enumerate()
                    .filter(|(i, _)| i % 64 == b)
                    .find_map(|(_, bk)| block::unwrap_record_key(bk, d, sid, env).ok())
            }) else {
                continue;
            };
            if let Some(i) = del {
                if reported.insert((i, Kind::DeletedRecordKey)) {
                    self.finding(Kind::DeletedRecordKey, *at, Some(i));
                }
            }
            for (cid, sealed) in self.carved.payloads.get(sid).cloned().unwrap_or_default() {
                let Ok(plain) = aead::open(&rk, &ad::slot_payload(&cid, sid), &sealed) else {
                    continue;
                };
                let t = match (del, ctl) {
                    (Some(i), _) => self.targets.deleted.get(i),
                    (_, Some(i)) => self.targets.controls.get(i),
                    _ => None,
                };
                let Some(t) = t else { continue };
                let x8 = t.x.get(..8).unwrap_or(&t.x);
                let le: Vec<u8> = x8.iter().flat_map(|c| c.to_le_bytes()).collect();
                let be: Vec<u8> = x8.iter().flat_map(|c| c.to_be_bytes()).collect();
                let has = |n: &[u8]| plain.windows(n.len()).any(|w| w == n);
                if has(&le) || has(&be) {
                    match (del, ctl) {
                        (Some(i), _) => {
                            if reported.insert((i, Kind::DeletedPayload)) {
                                self.finding(Kind::DeletedPayload, *at, Some(i));
                            }
                        }
                        (_, Some(i)) => {
                            if let Some(c) = self.report.controls_recovered.get_mut(i) {
                                *c = true;
                            }
                        }
                        _ => {}
                    }
                }
            }
        }
        self.report
    }
}

/// Scans an image held in memory.
pub fn scan_bytes(image: &[u8], targets: Targets) -> Report {
    let mut s = Scanner::new(targets);
    s.feed(0, image, image.len());
    s.finish()
}

/// Scans the file at `path` in chunks of `chunk` bytes (each read with [`OVERLAP`] more).
pub fn scan_file(path: &Path, targets: Targets, chunk: usize) -> std::io::Result<Report> {
    let mut f = std::fs::File::open(path)?;
    let mut s = Scanner::new(targets);
    let mut buf: Vec<u8> = Vec::new();
    let mut base = 0u64;
    let mut eof = false;
    loop {
        while !eof && buf.len() < chunk + OVERLAP {
            let mut tmp = vec![0u8; chunk + OVERLAP - buf.len()];
            let n = f.read(&mut tmp)?;
            if n == 0 {
                eof = true;
            }
            buf.extend_from_slice(tmp.get(..n).unwrap_or_default());
        }
        let limit = if eof { buf.len() } else { chunk };
        s.feed(base, &buf, limit);
        if eof {
            break;
        }
        buf.drain(..chunk);
        base += chunk as u64;
    }
    Ok(s.finish())
}

fn hex_bytes(s: &str) -> Option<Vec<u8>> {
    if s.len() % 2 != 0 {
        return None;
    }
    (0..s.len())
        .step_by(2)
        .map(|i| s.get(i..i + 2).and_then(|h| u8::from_str_radix(h, 16).ok()))
        .collect()
}

/// Parses a targets file: `{"d", "deleted": [target], "controls": [target], "retired_keys":
/// [hex]}`, a target being `{"sid": hex, "x": [int], "vector": [float], "passage": hex, "r_t":
/// hex}`.
pub fn parse_targets(text: &str) -> Option<Targets> {
    let v: serde_json::Value = serde_json::from_str(text).ok()?;
    let target = |t: &serde_json::Value| -> Option<Target> {
        Some(Target {
            sid: hex_bytes(t.get("sid")?.as_str()?)?,
            x: t.get("x")?
                .as_array()?
                .iter()
                .map(|c| c.as_i64().and_then(|c| i32::try_from(c).ok()))
                .collect::<Option<_>>()?,
            vector: t
                .get("vector")
                .and_then(|a| a.as_array())
                .map(|a| {
                    a.iter()
                        .filter_map(|c| c.as_f64())
                        .map(|c| c as f32)
                        .collect()
                })
                .unwrap_or_default(),
            passage: t
                .get("passage")
                .and_then(|p| p.as_str())
                .and_then(hex_bytes)
                .unwrap_or_default(),
            r_t: t
                .get("r_t")
                .and_then(|r| r.as_str())
                .and_then(hex_bytes)
                .and_then(|b| b.try_into().ok()),
        })
    };
    let list = |k: &str| -> Option<Vec<Target>> {
        v.get(k)
            .and_then(|a| a.as_array())
            .map(|a| a.iter().map(target).collect::<Option<Vec<_>>>())
            .unwrap_or(Some(Vec::new()))
    };
    Some(Targets {
        d: usize::try_from(v.get("d")?.as_u64()?).ok()?,
        deleted: list("deleted")?,
        controls: list("controls")?,
        retired_keys: v
            .get("retired_keys")
            .and_then(|a| a.as_array())
            .map(|a| {
                a.iter()
                    .filter_map(|k| {
                        k.as_str()
                            .and_then(hex_bytes)
                            .and_then(|b| b.try_into().ok())
                    })
                    .collect()
            })
            .unwrap_or_default(),
    })
}

#[cfg(test)]
mod tests;
