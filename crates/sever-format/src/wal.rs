//! WAL records (spec §14.6): `u32be len ‖ u8 type ‖ u64be wal_seq ‖ u64be txn_id ‖ payload ‖
//! u32be crc32c`, where `len` is the length of the whole record (25 + payload) and the CRC covers
//! every byte before it (G-14, DB-66).
//!
//! Change records carry after-images (§12.3). Every payload that changes a collection starts with
//! its `collection_id` (G-14). The record types whose payload belongs to a transaction participant
//! (bucket blocks, log leaves, log checkpoints, certificate references, `EXTENSION`) are carried as
//! opaque bytes and never interpreted here (DB-45).

use sever_types::{CollectionId, Error, GroupId, ScrambledId};

use crate::Layout;
use crate::codec::{Reader, Writer, bad, crc};
use crate::group::GroupHeader;
use crate::image::{CollectionMeta, PayloadRef};
use crate::slot::SlotBytes;

/// Fixed bytes of a record around its payload: len 4, type 1, wal_seq 8, txn_id 8, crc 4.
pub const RECORD_OVERHEAD: usize = 25;

/// The largest record: a whole 64 MiB segment minus its 32-byte header (§12.3, §18.1).
pub const MAX_RECORD: usize = 64 * 1024 * 1024 - 32;

/// The record types of §14.6, plus the collection records of G-14.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[repr(u8)]
pub enum RecordType {
    /// Starts a transaction.
    Begin = 1,
    /// A new group: header and bucket block.
    GroupCreate = 2,
    /// A replacement group header.
    GroupHeader = 3,
    /// A replacement bucket block (participant-owned, Part 4).
    BucketBlock = 4,
    /// A slot after-image.
    SlotPut = 5,
    /// A new slot count.
    SlotTruncate = 6,
    /// A locator entry after-image.
    LocatorPut = 7,
    /// A locator entry removed.
    LocatorDel = 8,
    /// A log leaf (participant-owned, Part 3).
    LogLeaf = 9,
    /// A log checkpoint (participant-owned, Part 3).
    LogCheckpoint = 10,
    /// A certificate reference (participant-owned, Part 3).
    CertRef = 11,
    /// Where a record's passage text lies in the payload store.
    PayloadRef = 12,
    /// `N` and `k` of a collection.
    Counters = 13,
    /// `u16be participant_id ‖ bytes` (DB-45).
    Extension = 14,
    /// Ends a transaction: committed once this record is durable with a valid CRC (§12.3).
    Commit = 15,
    /// A new collection (G-14).
    CollectionCreate = 16,
    /// A dropped collection (G-14).
    CollectionDrop = 17,
}

impl RecordType {
    /// The type for a byte, or `None` for an unknown one.
    pub fn from_byte(b: u8) -> Option<Self> {
        use RecordType::*;
        Some(match b {
            1 => Begin,
            2 => GroupCreate,
            3 => GroupHeader,
            4 => BucketBlock,
            5 => SlotPut,
            6 => SlotTruncate,
            7 => LocatorPut,
            8 => LocatorDel,
            9 => LogLeaf,
            10 => LogCheckpoint,
            11 => CertRef,
            12 => PayloadRef,
            13 => Counters,
            14 => Extension,
            15 => Commit,
            16 => CollectionCreate,
            17 => CollectionDrop,
            _ => return None,
        })
    }

    /// True for the types whose payload belongs to a transaction participant (DB-45).
    pub fn is_participant(self) -> bool {
        matches!(
            self,
            Self::BucketBlock
                | Self::LogLeaf
                | Self::LogCheckpoint
                | Self::CertRef
                | Self::Extension
        )
    }
}

/// One framed record.
#[derive(Clone, PartialEq, Eq)]
pub struct WalRecord {
    /// The type.
    pub ty: RecordType,
    /// Its position in the WAL.
    pub wal_seq: u64,
    /// Its transaction.
    pub txn_id: u64,
    /// The payload.
    pub payload: Vec<u8>,
}

impl core::fmt::Debug for WalRecord {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(
            f,
            "WalRecord({:?}, seq {}, txn {}, {} bytes)",
            self.ty,
            self.wal_seq,
            self.txn_id,
            self.payload.len()
        )
    }
}

/// What [`WalRecord::parse_next`] found.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum WalParse {
    /// A valid record and its encoded length.
    Record(WalRecord, usize),
    /// No bytes left: a clean end.
    End,
    /// The bytes do not start with a valid record (torn, zeroed, CRC failure, unknown type).
    Invalid,
}

impl WalRecord {
    /// The encoded record.
    pub fn encode(&self) -> Vec<u8> {
        let len = RECORD_OVERHEAD + self.payload.len();
        let mut w = Writer(Vec::with_capacity(len));
        w.u32(u32::try_from(len).unwrap_or(u32::MAX))
            .u8(self.ty as u8)
            .u64(self.wal_seq)
            .u64(self.txn_id)
            .bytes(&self.payload);
        let c = crc(&w.0);
        w.u32(c);
        w.finish()
    }

    /// Parses the record at the start of `buf`. Never fails: anything that is not a complete,
    /// valid record is [`WalParse::Invalid`] (§12.3: a torn or CRC-failing tail is discarded).
    pub fn parse_next(buf: &[u8]) -> WalParse {
        if buf.is_empty() {
            return WalParse::End;
        }
        let Some(len_bytes) = buf.first_chunk::<4>() else {
            return WalParse::Invalid;
        };
        let len = u32::from_be_bytes(*len_bytes) as usize;
        if !(RECORD_OVERHEAD..=MAX_RECORD).contains(&len) {
            return WalParse::Invalid;
        }
        let Some(rec) = buf.get(..len) else {
            return WalParse::Invalid;
        };
        let Some((body, tail)) = rec.split_last_chunk::<4>() else {
            return WalParse::Invalid;
        };
        // SB-11: accept a record whose CRC does not match.
        if crc(body) != u32::from_be_bytes(*tail) && !cfg!(feature = "sabotage-SB-11") {
            return WalParse::Invalid;
        }
        let mut r = Reader::new(body.get(4..).unwrap_or_default(), "§14.6 WAL record");
        let parsed = (|| -> Result<WalRecord, Error> {
            let ty = RecordType::from_byte(r.u8()?).ok_or(bad("§14.6 record type"))?;
            let wal_seq = r.u64()?;
            let txn_id = r.u64()?;
            let payload = r.take(r.remaining())?.to_vec();
            Ok(WalRecord {
                ty,
                wal_seq,
                txn_id,
                payload,
            })
        })();
        match parsed {
            Ok(rec) => WalParse::Record(rec, len),
            Err(_) => WalParse::Invalid,
        }
    }
}

/// A typed record payload.
#[derive(Clone, PartialEq)]
pub enum CoreRecord {
    /// `BEGIN`: empty.
    Begin,
    /// `COMMIT`: empty.
    Commit,
    /// `COLLECTION_CREATE`: `collection meta ‖ u32be artefact_len ‖ artefact (§6.3 bytes)`.
    CollectionCreate {
        /// The collection's metadata.
        meta: CollectionMeta,
        /// The partition artefact, verbatim.
        artefact: Vec<u8>,
    },
    /// `COLLECTION_DROP`: `collection_id`.
    CollectionDrop {
        /// The collection.
        cid: CollectionId,
    },
    /// `GROUP_CREATE`: `collection_id ‖ header ‖ u32be bucket_block_len ‖ bucket block` (the
    /// bucket block is empty before Part 4).
    GroupCreate {
        /// The collection.
        cid: CollectionId,
        /// The new group's header.
        header: GroupHeader,
        /// Its bucket block, opaque here.
        bucket_block: Vec<u8>,
    },
    /// `GROUP_HEADER`: `collection_id ‖ header`.
    GroupHeader {
        /// The collection.
        cid: CollectionId,
        /// The replacement header.
        header: GroupHeader,
    },
    /// `SLOT_PUT`: `collection_id ‖ group_id ‖ u64be slot index ‖ slot`.
    SlotPut {
        /// The collection.
        cid: CollectionId,
        /// The group (or the holding area).
        group: GroupId,
        /// The slot's position.
        index: u64,
        /// The slot bytes.
        slot: SlotBytes,
    },
    /// `SLOT_TRUNCATE`: `collection_id ‖ group_id ‖ u64be new slot count`.
    SlotTruncate {
        /// The collection.
        cid: CollectionId,
        /// The group.
        group: GroupId,
        /// The new count.
        len: u64,
    },
    /// `LOCATOR_PUT`: `collection_id ‖ scrambled_id ‖ group_id ‖ u64be slot index`.
    LocatorPut {
        /// The collection.
        cid: CollectionId,
        /// The record.
        scrambled_id: ScrambledId,
        /// Its group.
        group: GroupId,
        /// Its slot.
        index: u64,
    },
    /// `LOCATOR_DEL`: `collection_id ‖ scrambled_id`. Also drops the record's payload reference.
    LocatorDel {
        /// The collection.
        cid: CollectionId,
        /// The record.
        scrambled_id: ScrambledId,
    },
    /// `PAYLOAD_REF`: `collection_id ‖ scrambled_id ‖ u64be store segment ‖ u64be offset ‖
    /// u32be length`.
    PayloadRef {
        /// The collection.
        cid: CollectionId,
        /// The record.
        scrambled_id: ScrambledId,
        /// Where its passage text lies.
        at: PayloadRef,
    },
    /// `COUNTERS`: `collection_id ‖ u64be N ‖ u64be k` (G-14: `database_lsn` belongs to the log
    /// participant of Part 3).
    Counters {
        /// The collection.
        cid: CollectionId,
        /// `N`.
        big_n: u64,
        /// `k`.
        k: u64,
    },
    /// A participant-owned record (`BUCKET_BLOCK`, `LOG_LEAF`, `LOG_CHECKPOINT`, `CERT_REF`,
    /// `EXTENSION`), carried verbatim.
    Participant {
        /// Which of the participant types.
        ty: RecordType,
        /// The payload, never interpreted here.
        bytes: Vec<u8>,
    },
}

impl core::fmt::Debug for CoreRecord {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "CoreRecord({:?})", self.ty())
    }
}

impl CoreRecord {
    /// The record type.
    pub fn ty(&self) -> RecordType {
        match self {
            Self::Begin => RecordType::Begin,
            Self::Commit => RecordType::Commit,
            Self::CollectionCreate { .. } => RecordType::CollectionCreate,
            Self::CollectionDrop { .. } => RecordType::CollectionDrop,
            Self::GroupCreate { .. } => RecordType::GroupCreate,
            Self::GroupHeader { .. } => RecordType::GroupHeader,
            Self::SlotPut { .. } => RecordType::SlotPut,
            Self::SlotTruncate { .. } => RecordType::SlotTruncate,
            Self::LocatorPut { .. } => RecordType::LocatorPut,
            Self::LocatorDel { .. } => RecordType::LocatorDel,
            Self::PayloadRef { .. } => RecordType::PayloadRef,
            Self::Counters { .. } => RecordType::Counters,
            Self::Participant { ty, .. } => *ty,
        }
    }

    /// The collection a change record belongs to.
    pub fn collection(&self) -> Option<CollectionId> {
        match self {
            Self::CollectionCreate { meta, .. } => Some(meta.cid),
            Self::CollectionDrop { cid }
            | Self::GroupCreate { cid, .. }
            | Self::GroupHeader { cid, .. }
            | Self::SlotPut { cid, .. }
            | Self::SlotTruncate { cid, .. }
            | Self::LocatorPut { cid, .. }
            | Self::LocatorDel { cid, .. }
            | Self::PayloadRef { cid, .. }
            | Self::Counters { cid, .. } => Some(*cid),
            Self::Begin | Self::Commit | Self::Participant { .. } => None,
        }
    }

    /// Encodes the payload. `layout` is the collection's layout (ignored by records without a
    /// header or slot).
    pub fn encode_payload(&self, layout: &Layout) -> Result<Vec<u8>, Error> {
        let mut w = Writer::new();
        match self {
            Self::Begin | Self::Commit => {}
            Self::CollectionCreate { meta, artefact } => {
                meta.write(&mut w);
                w.var(artefact);
            }
            Self::CollectionDrop { cid } => {
                w.collection(cid);
            }
            Self::GroupCreate {
                cid,
                header,
                bucket_block,
            } => {
                w.collection(cid)
                    .bytes(&header.encode(layout)?)
                    .var(bucket_block);
            }
            Self::GroupHeader { cid, header } => {
                w.collection(cid).bytes(&header.encode(layout)?);
            }
            Self::SlotPut {
                cid,
                group,
                index,
                slot,
            } => {
                w.collection(cid)
                    .group_id(group)
                    .u64(*index)
                    .bytes(&slot.encode(layout)?);
            }
            Self::SlotTruncate { cid, group, len } => {
                w.collection(cid).group_id(group).u64(*len);
            }
            Self::LocatorPut {
                cid,
                scrambled_id,
                group,
                index,
            } => {
                w.collection(cid)
                    .scrambled(scrambled_id)
                    .group_id(group)
                    .u64(*index);
            }
            Self::LocatorDel { cid, scrambled_id } => {
                w.collection(cid).scrambled(scrambled_id);
            }
            Self::PayloadRef {
                cid,
                scrambled_id,
                at,
            } => {
                w.collection(cid).scrambled(scrambled_id);
                at.write(&mut w);
            }
            Self::Counters { cid, big_n, k } => {
                w.collection(cid).u64(*big_n).u64(*k);
            }
            Self::Participant { bytes, .. } => {
                w.bytes(bytes);
            }
        }
        Ok(w.finish())
    }

    /// Parses a payload of type `ty`. `layout_of` gives the layout of an existing collection;
    /// `new_layout` the layout for a collection being created (from its metadata).
    pub fn parse(
        ty: RecordType,
        payload: &[u8],
        layout_of: &dyn Fn(&CollectionId) -> Option<Layout>,
    ) -> Result<Self, Error> {
        let mut r = Reader::new(payload, "§14.6 record payload");
        let layout = |cid: &CollectionId| layout_of(cid).ok_or(bad("§14.6 unknown collection"));
        let rec = match ty {
            RecordType::Begin => Self::Begin,
            RecordType::Commit => Self::Commit,
            RecordType::CollectionCreate => {
                let meta = CollectionMeta::read(&mut r)?;
                let artefact = r.var()?.to_vec();
                Self::CollectionCreate { meta, artefact }
            }
            RecordType::CollectionDrop => Self::CollectionDrop {
                cid: r.collection()?,
            },
            RecordType::GroupCreate => {
                let cid = r.collection()?;
                let header = GroupHeader::read(&mut r, &layout(&cid)?)?;
                let bucket_block = r.var()?.to_vec();
                Self::GroupCreate {
                    cid,
                    header,
                    bucket_block,
                }
            }
            RecordType::GroupHeader => {
                let cid = r.collection()?;
                let header = GroupHeader::read(&mut r, &layout(&cid)?)?;
                Self::GroupHeader { cid, header }
            }
            RecordType::SlotPut => {
                let cid = r.collection()?;
                let group = r.group_id()?;
                let index = r.u64()?;
                let slot = SlotBytes::read(&mut r, &layout(&cid)?)?;
                Self::SlotPut {
                    cid,
                    group,
                    index,
                    slot,
                }
            }
            RecordType::SlotTruncate => Self::SlotTruncate {
                cid: r.collection()?,
                group: r.group_id()?,
                len: r.u64()?,
            },
            RecordType::LocatorPut => Self::LocatorPut {
                cid: r.collection()?,
                scrambled_id: r.scrambled()?,
                group: r.group_id()?,
                index: r.u64()?,
            },
            RecordType::LocatorDel => Self::LocatorDel {
                cid: r.collection()?,
                scrambled_id: r.scrambled()?,
            },
            RecordType::PayloadRef => Self::PayloadRef {
                cid: r.collection()?,
                scrambled_id: r.scrambled()?,
                at: PayloadRef::read(&mut r)?,
            },
            RecordType::Counters => Self::Counters {
                cid: r.collection()?,
                big_n: r.u64()?,
                k: r.u64()?,
            },
            ty => Self::Participant {
                ty,
                bytes: r.take(r.remaining())?.to_vec(),
            },
        };
        r.end()?;
        Ok(rec)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::group::encode_accumulator;
    use proptest::prelude::*;
    use sever_spec::spec;

    fn rec(payload: Vec<u8>) -> WalRecord {
        WalRecord {
            ty: RecordType::SlotTruncate,
            wal_seq: 41,
            txn_id: 7,
            payload,
        }
    }

    #[test]
    // oracle: A §14.6 framing by hand; SLOT_TRUNCATE is type 6
    #[spec("SR-14.6-1")]
    fn p2_format_wal_record_layout_by_offset() {
        let b = rec(vec![0xaa, 0xbb]).encode();
        assert_eq!(b.len(), RECORD_OVERHEAD + 2);
        assert_eq!(&b[..4], &27u32.to_be_bytes(), "len counts the whole record");
        assert_eq!(b[4], 6, "SLOT_TRUNCATE is type 6");
        assert_eq!(&b[5..13], &41u64.to_be_bytes(), "wal_seq");
        assert_eq!(&b[13..21], &7u64.to_be_bytes(), "txn_id");
        assert_eq!(&b[21..23], &[0xaa, 0xbb]);
        assert_eq!(
            &b[23..],
            &crc(&b[..23]).to_be_bytes(),
            "crc over everything before"
        );
    }

    #[test]
    // oracle: A §14.6 len and type codes 1–17; §12.3 a torn record is not a record
    #[spec("SR-14.6-1", "SR-12.3-3")]
    fn p2_format_wal_parse_next_stops_at_anything_invalid() {
        let a = rec(vec![1, 2, 3]).encode();
        let b = rec(vec![]).encode();
        let mut buf = a.clone();
        buf.extend_from_slice(&b);
        match WalRecord::parse_next(&buf) {
            WalParse::Record(r, n) => {
                assert_eq!(n, a.len());
                assert_eq!(r.payload, vec![1, 2, 3]);
            }
            other => panic!("{other:?}"),
        }
        assert_eq!(WalRecord::parse_next(&[]), WalParse::End);
        assert_eq!(WalRecord::parse_next(&[0; 3]), WalParse::Invalid, "short");
        assert_eq!(WalRecord::parse_next(&[0; 64]), WalParse::Invalid, "zeroed");
        assert_eq!(
            WalRecord::parse_next(&a[..a.len() - 1]),
            WalParse::Invalid,
            "torn"
        );
        let mut bad_type = a.clone();
        bad_type[4] = 99;
        let n = bad_type.len() - 4;
        let c = crc(&bad_type[..n]);
        bad_type[n..].copy_from_slice(&c.to_be_bytes());
        assert_eq!(
            WalRecord::parse_next(&bad_type),
            WalParse::Invalid,
            "unknown type"
        );
    }

    // SB-11 must turn this red.
    #[test]
    // oracle: A §12.7 every record has a CRC-32C; §12.3 a CRC-failing record is not a record
    #[spec("SR-12.7-4", "SR-12.3-3")]
    fn p2_format_wal_every_single_bit_flip_is_detected() {
        let b = rec((0..40).collect()).encode();
        for i in 0..b.len() * 8 {
            let mut f = b.clone();
            f[i / 8] ^= 1 << (i % 8);
            if let WalParse::Record(r, _) = WalRecord::parse_next(&f) {
                panic!("bit {i}: accepted a corrupted record {r:?}");
            }
        }
    }

    fn sample_records(l: &Layout, cid: CollectionId) -> Vec<CoreRecord> {
        let g = GroupId::frozen(3).unwrap();
        let header = GroupHeader {
            group_id: g,
            seal_version: 0,
            n: 1,
            ext_public: vec![],
            centroid: vec![0.5; l.d],
            sealed_accumulator: encode_accumulator(&vec![9; l.d], &[]),
        };
        let slot = SlotBytes {
            scrambled_id: ScrambledId::from_bytes([3; 64]),
            envelope: vec![],
            sealed_payload: vec![0; l.payload_len()],
        };
        vec![
            CoreRecord::Begin,
            CoreRecord::CollectionCreate {
                meta: CollectionMeta {
                    cid,
                    d: l.d as u16,
                    spawn_target: 8,
                    spawning_enabled: true,
                    store_passages: true,
                    artefact_sha256: [4; 32],
                },
                artefact: vec![1, 2, 3],
            },
            CoreRecord::GroupCreate {
                cid,
                header: header.clone(),
                bucket_block: vec![],
            },
            CoreRecord::GroupHeader { cid, header },
            CoreRecord::SlotPut {
                cid,
                group: g,
                index: 0,
                slot,
            },
            CoreRecord::SlotTruncate {
                cid,
                group: GroupId::Holding,
                len: 0,
            },
            CoreRecord::LocatorPut {
                cid,
                scrambled_id: ScrambledId::from_bytes([3; 64]),
                group: g,
                index: 0,
            },
            CoreRecord::LocatorDel {
                cid,
                scrambled_id: ScrambledId::from_bytes([3; 64]),
            },
            CoreRecord::PayloadRef {
                cid,
                scrambled_id: ScrambledId::from_bytes([3; 64]),
                at: PayloadRef {
                    segment: 1,
                    offset: 16,
                    len: 9,
                },
            },
            CoreRecord::Counters {
                cid,
                big_n: 10,
                k: 4,
            },
            CoreRecord::Participant {
                ty: RecordType::Extension,
                bytes: vec![0, 1, 0xee],
            },
            CoreRecord::CollectionDrop { cid },
            CoreRecord::Commit,
        ]
    }

    #[test]
    // oracle: D round trip (the bytes by hand: tests/spec_bytes.rs)
    #[spec("SR-14.6-2")]
    fn p2_format_every_record_type_round_trips() {
        let l = Layout::plain(8);
        let cid = CollectionId::from_bytes([5; 16]);
        let layout_of = |c: &CollectionId| (*c == cid).then_some(l);
        for r in sample_records(&l, cid) {
            let p = r.encode_payload(&l).unwrap();
            assert_eq!(
                CoreRecord::parse(r.ty(), &p, &layout_of).unwrap(),
                r,
                "{r:?}"
            );
            if !p.is_empty() && !r.ty().is_participant() {
                assert!(
                    CoreRecord::parse(r.ty(), &p[..p.len() - 1], &layout_of).is_err(),
                    "{r:?} short"
                );
                let mut long = p.clone();
                long.push(0);
                assert!(
                    CoreRecord::parse(r.ty(), &long, &layout_of).is_err(),
                    "{r:?} long"
                );
            }
        }
    }

    #[test]
    fn p2_format_change_records_name_their_collection() {
        let l = Layout::plain(8);
        let cid = CollectionId::from_bytes([5; 16]);
        for r in sample_records(&l, cid) {
            let expect = !matches!(
                r,
                CoreRecord::Begin | CoreRecord::Commit | CoreRecord::Participant { .. }
            );
            assert_eq!(r.collection().is_some(), expect, "{r:?}");
            if expect {
                let p = r.encode_payload(&l).unwrap();
                assert_eq!(&p[..16], cid.as_bytes(), "{r:?}: collection first");
            }
        }
        let unknown = |_: &CollectionId| None;
        let r = &sample_records(&l, cid)[3];
        assert!(CoreRecord::parse(r.ty(), &r.encode_payload(&l).unwrap(), &unknown).is_err());
    }

    #[test]
    fn p2_format_record_type_bytes_are_stable() {
        for b in 0..=255u8 {
            if let Some(t) = RecordType::from_byte(b) {
                assert_eq!(t as u8, b);
            }
        }
        assert_eq!(RecordType::from_byte(0), None);
        assert_eq!(RecordType::from_byte(18), None);
    }

    proptest! {
        #[test]
        fn p2_format_prop_wal_record_round_trips(
            ty in 1u8..=17, seq in any::<u64>(), txn in any::<u64>(),
            payload in prop::collection::vec(any::<u8>(), 0..300),
        ) {
            let r = WalRecord { ty: RecordType::from_byte(ty).unwrap(), wal_seq: seq, txn_id: txn, payload };
            let b = r.encode();
            prop_assert_eq!(WalRecord::parse_next(&b), WalParse::Record(r, b.len()));
        }

        #[test]
        fn p2_format_prop_parse_next_never_panics(bytes in prop::collection::vec(any::<u8>(), 0..200)) {
            let _ = WalRecord::parse_next(&bytes);
        }
    }
}
