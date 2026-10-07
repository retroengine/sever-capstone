//! `sever-wal`: the write-ahead log (Part 2, Build §5.5; spec §12.3, §14.6).
//!
//! - Segment files `wal/<seq>.wal`, 64 MiB each by default, append-only, each starting with a
//!   32-byte header (§14.9).
//! - A transaction is `BEGIN`, change records, `COMMIT`. It is **committed exactly when its
//!   `COMMIT` record, with a valid CRC, is durable** (§12.3). [`Wal::commit`] writes the whole
//!   transaction with one append per segment and returns only after the `fsync`.
//! - On recovery a transaction without a valid `COMMIT`, including a torn or CRC-failing tail, is
//!   discarded whole and never repaired. The tail is cut off the file, so the next transaction
//!   never follows garbage.
//! - Any I/O failure while writing makes the log unusable and is reported as `DurabilityFailure`:
//!   the caller aborts and recovery runs at the restart (§12.7; owner decision of 7 October 2026).

use std::sync::Arc;

use sever_format::codec::bad;
use sever_format::{RecordType, SegmentHeader, WalParse, WalRecord};
use sever_types::Error;
use sever_vfs::{OpenMode, Vfs, VfsFile, durable, read_all};

/// The WAL directory.
pub const WAL_DIR: &str = "wal";
/// Default segment size (§12.3, §18.1 `wal_segment_bytes`).
pub const DEFAULT_SEGMENT_BYTES: u64 = 64 * 1024 * 1024;

/// WAL settings.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct WalConfig {
    /// The sealer of every segment (DB-48).
    pub sealer_id: u16,
    /// A segment is closed when the next record would make it longer than this.
    pub segment_bytes: u64,
}

impl WalConfig {
    /// Default segment size for `sealer_id`.
    pub fn new(sealer_id: u16) -> Self {
        Self {
            sealer_id,
            segment_bytes: DEFAULT_SEGMENT_BYTES,
        }
    }
}

/// The file name of segment `seq`: 20 zero-padded digits, so names sort by number.
pub fn segment_path(seq: u64) -> String {
    format!("{WAL_DIR}/{seq:020}.wal")
}

fn parse_segment_name(name: &str) -> Option<u64> {
    let digits = name.strip_suffix(".wal")?;
    if digits.len() == 20 && digits.bytes().all(|b| b.is_ascii_digit()) {
        digits.parse().ok()
    } else {
        None
    }
}

/// A committed transaction, without its `BEGIN` and `COMMIT` records.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Txn {
    /// Its ID.
    pub txn_id: u64,
    /// Its change records, in order.
    pub records: Vec<WalRecord>,
}

/// Where a committed transaction landed.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Committed {
    /// Its ID.
    pub txn_id: u64,
    /// `wal_seq` of its `BEGIN`.
    pub first_wal_seq: u64,
    /// `wal_seq` of its `COMMIT`.
    pub commit_wal_seq: u64,
}

/// What recovery found and did.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct RecoveryReport {
    /// Bytes cut off the end of the log (a torn or uncommitted tail).
    pub truncated_bytes: u64,
    /// True when an uncommitted transaction was discarded.
    pub discarded_txn: bool,
    /// Segment files removed (covered by the checkpoint, or holding only discarded bytes).
    pub removed_segments: u64,
}

fn io(_: sever_vfs::VfsError) -> Error {
    Error::DurabilityFailure
}

/// The open log.
pub struct Wal {
    vfs: Arc<dyn Vfs>,
    cfg: WalConfig,
    file: Box<dyn VfsFile>,
    /// Live segments, oldest first: `(segment_seq, first_wal_seq)`.
    segments: Vec<(u64, u64)>,
    seg_len: u64,
    next_wal_seq: u64,
    next_txn_id: u64,
    appended: u64,
    failed: bool,
}

impl core::fmt::Debug for Wal {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(
            f,
            "Wal(segments {:?}, next_wal_seq {}, next_txn_id {})",
            self.segments, self.next_wal_seq, self.next_txn_id
        )
    }
}

impl Wal {
    /// Creates the WAL of a new database: the directory and its first segment, both durable.
    pub fn create(
        vfs: Arc<dyn Vfs>,
        cfg: WalConfig,
        first_wal_seq: u64,
        next_txn_id: u64,
    ) -> Result<Self, Error> {
        durable::create_dir(vfs.as_ref(), WAL_DIR).map_err(io)?;
        let file = new_segment(vfs.as_ref(), &cfg, 1, first_wal_seq)?;
        Ok(Self {
            vfs,
            cfg,
            file,
            segments: vec![(1, first_wal_seq)],
            seg_len: SegmentHeader::LEN as u64,
            next_wal_seq: first_wal_seq,
            next_txn_id,
            appended: 0,
            failed: false,
        })
    }

    /// The `wal_seq` the next record gets.
    pub fn next_wal_seq(&self) -> u64 {
        self.next_wal_seq
    }

    /// The ID the next transaction gets.
    pub fn next_txn_id(&self) -> u64 {
        self.next_txn_id
    }

    /// Bytes appended since the log was opened or [`Wal::reset_appended`] (the storage checkpoint
    /// trigger, §12.4).
    pub fn appended(&self) -> u64 {
        self.appended
    }

    /// Restarts the appended-bytes count (after a storage checkpoint).
    pub fn reset_appended(&mut self) {
        self.appended = 0;
    }

    /// The live segments, oldest first, as `(segment_seq, first_wal_seq)`.
    pub fn segments(&self) -> &[(u64, u64)] {
        &self.segments
    }

    /// Writes one transaction: `BEGIN`, `records` in order, `COMMIT`, then `fsync`. The
    /// transaction is committed when this returns `Ok` (§12.3). On any failure the log refuses all
    /// further writes (`DurabilityFailure`) and the caller must abort (§12.7).
    pub fn commit(&mut self, records: &[(RecordType, Vec<u8>)]) -> Result<Committed, Error> {
        if self.failed {
            return Err(Error::DurabilityFailure);
        }
        let max = self.cfg.segment_bytes - SegmentHeader::LEN as u64;
        if records
            .iter()
            .any(|(_, p)| (p.len() + sever_format::wal::RECORD_OVERHEAD) as u64 > max)
        {
            return Err(bad("§12.3 record larger than a segment"));
        }
        let r = self.write_txn(records);
        if r.is_err() {
            self.failed = true;
        }
        r
    }

    fn write_txn(&mut self, records: &[(RecordType, Vec<u8>)]) -> Result<Committed, Error> {
        let txn_id = self.next_txn_id;
        let first = self.next_wal_seq;
        let mut seq = first;
        let begin = (RecordType::Begin, Vec::new());
        let commit = (RecordType::Commit, Vec::new());
        let mut buf = Vec::new();
        for (ty, payload) in core::iter::once(&begin)
            .chain(records)
            .chain(core::iter::once(&commit))
        {
            let enc = WalRecord {
                ty: *ty,
                wal_seq: seq,
                txn_id,
                payload: payload.clone(),
            }
            .encode();
            if self.seg_len + (buf.len() + enc.len()) as u64 > self.cfg.segment_bytes {
                self.append(&buf)?;
                buf.clear();
                durable::sync(self.file.as_mut()).map_err(io)?;
                let next = self.segments.last().map_or(1, |s| s.0 + 1);
                self.file = new_segment(self.vfs.as_ref(), &self.cfg, next, seq)?;
                self.segments.push((next, seq));
                self.seg_len = SegmentHeader::LEN as u64;
            }
            buf.extend_from_slice(&enc);
            seq += 1;
        }
        self.append(&buf)?;
        durable::sync(self.file.as_mut()).map_err(io)?;
        self.next_wal_seq = seq;
        self.next_txn_id = txn_id + 1;
        Ok(Committed {
            txn_id,
            first_wal_seq: first,
            commit_wal_seq: seq - 1,
        })
    }

    fn append(&mut self, bytes: &[u8]) -> Result<(), Error> {
        if bytes.is_empty() {
            return Ok(());
        }
        let at = self.file.append(bytes).map_err(io)?;
        if at != self.seg_len {
            return Err(Error::DurabilityFailure);
        }
        self.seg_len += bytes.len() as u64;
        self.appended += bytes.len() as u64;
        Ok(())
    }

    /// Removes the segments whose every record is below `wal_seq` (covered by a storage
    /// checkpoint, §15.6 step 4), oldest first; never the current segment.
    pub fn remove_covered(&mut self, wal_seq: u64) -> Result<u64, Error> {
        let mut removed = 0;
        while self.segments.len() > 1 {
            let covered = self.segments.get(1).is_some_and(|next| next.1 <= wal_seq);
            if !covered {
                break;
            }
            let (seq, _) = self.segments.remove(0);
            self.vfs.unlink(&segment_path(seq)).map_err(io)?;
            removed += 1;
        }
        if removed > 0 {
            durable::sync_dir(self.vfs.as_ref(), WAL_DIR).map_err(io)?;
        }
        Ok(removed)
    }

    /// Opens the log of an existing database and returns every committed transaction from
    /// `first_wal_seq` on (§15.7 step 3). An uncommitted or torn tail is discarded and cut off;
    /// segments covered by the checkpoint are removed. Anything else that does not fit (a hole
    /// inside the log, a broken transaction structure) is an `IntegrityViolation`.
    pub fn recover(
        vfs: Arc<dyn Vfs>,
        cfg: WalConfig,
        first_wal_seq: u64,
        next_txn_id_floor: u64,
    ) -> Result<(Self, Vec<Txn>, RecoveryReport), Error> {
        let names = vfs.list(WAL_DIR).map_err(|_| bad("§12.3 WAL directory"))?;
        let mut seqs = Vec::new();
        for name in &names {
            seqs.push(parse_segment_name(name).ok_or(bad("§12.3 WAL file name"))?);
        }
        seqs.sort_unstable();
        let mut report = RecoveryReport::default();

        // Headers. Only the newest segment may have a missing or torn header: it was being
        // created when the crash came, and no record in it was ever made durable.
        let mut segs: Vec<(u64, SegmentHeader, Vec<u8>)> = Vec::new();
        let last_seq = seqs.last().copied();
        for seq in &seqs {
            let path = segment_path(*seq);
            let bytes = read_all(
                vfs.open(&path, OpenMode::Existing)
                    .map_err(|_| bad("§12.3 WAL segment"))?
                    .as_ref(),
            )
            .map_err(|_| bad("§12.3 WAL segment"))?;
            let header = bytes
                .get(..SegmentHeader::LEN)
                .ok_or(bad("§12.3 segment header"))
                .and_then(|h| SegmentHeader::parse(h, cfg.sealer_id));
            match header {
                Ok(h) if h.segment_seq == *seq => segs.push((*seq, h, bytes)),
                Err(Error::IntegrityViolation {
                    invariant: "DB-48 sealer_id",
                }) => return Err(bad("DB-48 sealer_id")),
                _ if Some(*seq) == last_seq && !segs.is_empty() => {
                    vfs.unlink(&path).map_err(io)?;
                    report.removed_segments += 1;
                }
                _ => return Err(bad("§12.3 segment header")),
            }
        }

        // The segment holding `first_wal_seq`; older ones are covered leftovers.
        let start = segs
            .iter()
            .rposition(|(_, h, _)| h.first_wal_seq <= first_wal_seq)
            .ok_or(bad("§12.3 WAL position missing"))?;
        for (seq, _, _) in segs.drain(..start) {
            vfs.unlink(&segment_path(seq)).map_err(io)?;
            report.removed_segments += 1;
        }
        for pair in segs.windows(2) {
            if let [(a, _, _), (b, _, _)] = pair {
                if *b != a + 1 {
                    return Err(bad("§12.3 segment sequence"));
                }
            }
        }

        // Records. `cut` is the end of the last complete transaction: (segment index, offset,
        // next wal_seq there).
        let first_header = segs.first().map(|s| s.1).ok_or(bad("§12.3 no segment"))?;
        let mut cut = (0usize, SegmentHeader::LEN, first_header.first_wal_seq);
        let mut committed = Vec::new();
        let mut open: Option<Txn> = None;
        let mut last_txn: Option<u64> = None;
        let n = segs.len();
        let mut expect = first_header.first_wal_seq;
        'segments: for (i, (_, header, bytes)) in segs.iter().enumerate() {
            let tail_segment = i + 1 == n;
            let mut off = SegmentHeader::LEN;
            // A segment starts exactly where the previous one ended: it is created only after
            // the previous one was fsynced whole.
            if header.first_wal_seq != expect {
                return Err(bad("§12.3 wal_seq continuity"));
            }
            loop {
                let rest = bytes.get(off..).unwrap_or_default();
                let (rec, len) = match WalRecord::parse_next(rest) {
                    WalParse::End => break,
                    WalParse::Record(r, len) if r.wal_seq == expect => (r, len),
                    _ if tail_segment => break 'segments,
                    _ => return Err(bad("§12.3 hole inside the log")),
                };
                off += len;
                expect += 1;
                if rec.wal_seq < first_wal_seq {
                    cut = (i, off, expect);
                    continue;
                }
                match (rec.ty, &mut open) {
                    (RecordType::Begin, None) => {
                        if last_txn.is_some_and(|t| rec.txn_id <= t)
                            || rec.txn_id < next_txn_id_floor
                        {
                            return Err(bad("§12.3 transaction order"));
                        }
                        open = Some(Txn {
                            txn_id: rec.txn_id,
                            records: Vec::new(),
                        });
                    }
                    (RecordType::Commit, Some(t)) if t.txn_id == rec.txn_id => {
                        last_txn = Some(t.txn_id);
                        committed.extend(open.take());
                        cut = (i, off, expect);
                    }
                    (RecordType::Begin | RecordType::Commit, _) => {
                        return Err(bad("§12.3 transaction structure"));
                    }
                    (_, Some(t)) if t.txn_id == rec.txn_id => t.records.push(rec),
                    _ => return Err(bad("§12.3 transaction structure")),
                }
            }
        }
        if let Some(t) = open.take() {
            report.discarded_txn = true;
            // SB-13: replay an uncommitted transaction.
            if cfg!(feature = "sabotage-SB-13") {
                committed.push(t);
            }
        }

        // Cut everything after the last complete transaction.
        let (keep_i, keep_off, next_wal_seq) = cut;
        if next_wal_seq < first_wal_seq {
            return Err(bad("§12.3 WAL shorter than the checkpoint"));
        }
        while segs.len() > keep_i + 1 {
            if let Some((seq, _, _)) = segs.pop() {
                vfs.unlink(&segment_path(seq)).map_err(io)?;
                report.removed_segments += 1;
            }
        }
        if report.removed_segments > 0 {
            durable::sync_dir(vfs.as_ref(), WAL_DIR).map_err(io)?;
        }
        let (seq, _, bytes) = segs.last().ok_or(bad("§12.3 no segment"))?;
        let mut file = vfs
            .open(&segment_path(*seq), OpenMode::Existing)
            .map_err(io)?;
        if bytes.len() > keep_off {
            report.truncated_bytes = (bytes.len() - keep_off) as u64;
            file.truncate(keep_off as u64).map_err(io)?;
            durable::sync(file.as_mut()).map_err(io)?;
        }
        let next_txn_id = last_txn.map_or(next_txn_id_floor, |t| (t + 1).max(next_txn_id_floor));
        let wal = Self {
            vfs,
            cfg,
            file,
            segments: segs.iter().map(|(s, h, _)| (*s, h.first_wal_seq)).collect(),
            seg_len: keep_off as u64,
            next_wal_seq,
            next_txn_id,
            appended: 0,
            failed: false,
        };
        Ok((wal, committed, report))
    }
}

/// Creates segment `seq`: the file and its directory entry, then its header, all durable.
fn new_segment(
    vfs: &dyn Vfs,
    cfg: &WalConfig,
    seq: u64,
    first_wal_seq: u64,
) -> Result<Box<dyn VfsFile>, Error> {
    let mut f = durable::create(vfs, &segment_path(seq)).map_err(io)?;
    let h = SegmentHeader {
        sealer_id: cfg.sealer_id,
        segment_seq: seq,
        first_wal_seq,
    };
    f.write_at(0, &h.encode()).map_err(io)?;
    durable::sync(f.as_mut()).map_err(io)?;
    Ok(f)
}

#[cfg(test)]
mod tests;
