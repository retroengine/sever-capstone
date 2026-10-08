//! L3 conformance, byte for byte, of the layouts of spec §14.6 (WAL payloads) and §14.9 (file
//! headers, `SECRETS`, collection metadata, storage checkpoint streams), with group headers (§14.3)
//! and slots (§14.4) inside them (CLAUDE.md §6.3, oracle A).
//!
//! Every expected byte is written here from the spec text with a local byte builder; nothing comes
//! from the crate's own writer or CRC. The CRC-32C is an independent bitwise implementation checked
//! against the standard check value. Two spec decisions apply: every `version` is 1 (G-18) and a
//! `group_id` is its §5.1 label zero-padded to 32 bytes wherever it is written (G-19).

#![allow(clippy::unwrap_used, clippy::indexing_slicing)]

use sever_format::{
    CheckpointMeta, CollectionMeta, CoreRecord, DbImage, FileHeader, GroupHeader, Layout, Manifest,
    PayloadRef, RecordType, Secrets, SegmentHeader, SlotBytes,
};
use sever_spec::spec;
use sever_types::{CollectionId, GroupId, ScrambledId};

/// CRC-32C (Castagnoli, reflected polynomial 0x82F63B78), bit by bit.
fn crc32c(bytes: &[u8]) -> u32 {
    let mut c = !0u32;
    for &b in bytes {
        c ^= u32::from(b);
        for _ in 0..8 {
            c = if c & 1 == 1 {
                (c >> 1) ^ 0x82F6_3B78
            } else {
                c >> 1
            };
        }
    }
    !c
}

#[test]
fn crc32c_check_value() {
    assert_eq!(crc32c(b"123456789"), 0xE306_9283); // RFC 3720 B.4
}

/// A byte builder for expected values: big-endian, raw concatenation (§0.2).
#[derive(Default)]
struct B(Vec<u8>);

impl B {
    fn raw(mut self, b: &[u8]) -> Self {
        self.0.extend_from_slice(b);
        self
    }
    fn u8(self, v: u8) -> Self {
        self.raw(&[v])
    }
    fn u16(self, v: u16) -> Self {
        self.raw(&v.to_be_bytes())
    }
    fn u32(self, v: u32) -> Self {
        self.raw(&v.to_be_bytes())
    }
    fn u64(self, v: u64) -> Self {
        self.raw(&v.to_be_bytes())
    }
    fn zeros(self, n: usize) -> Self {
        self.raw(&vec![0; n])
    }
    /// A §5.1 group label zero-padded to 32 bytes (§14.3, G-19).
    fn gid(self, label: &str) -> Self {
        assert!(label.len() <= 32);
        let n = 32 - label.len();
        self.raw(label.as_bytes()).zeros(n)
    }
    /// Appends `u32be crc32c` over every preceding byte (§14.9).
    fn crc(self) -> Vec<u8> {
        let c = crc32c(&self.0);
        self.u32(c).0
    }
    fn done(self) -> Vec<u8> {
        self.0
    }
}

const D: usize = 8;
const CID: [u8; 16] = [0xc1; 16];

// ---------------------------------------------------------------------------------------------
// §14.9 file headers and SECRETS
// ---------------------------------------------------------------------------------------------

#[test]
// oracle: A §14.9 file header row, §14 sealer marker (DB-48), version 1 (G-18)
#[spec("SR-14-1", "SR-14.9-1")]
fn p2_format_append_store_file_header_bytes_are_the_spec_s() {
    let want = B::default().raw(b"SVDBSTOR").u16(1).u16(0).zeros(0).crc();
    assert_eq!(want.len(), 16, "§14.9: 16 bytes");
    let h = FileHeader {
        magic: *b"SVDBSTOR",
        sealer_id: 0,
    };
    assert_eq!(h.encode(), want);
    assert_eq!(FileHeader::parse(&want, b"SVDBSTOR", 0).unwrap(), h);
}

#[test]
// oracle: A §14.9 MANIFEST row, version 1 (G-18)
#[spec("SR-14-1", "SR-14.9-1")]
fn p2_format_manifest_bytes_are_the_spec_s() {
    let want = B::default()
        .raw(b"SVDBMANI")
        .u16(1)
        .u16(0)
        .u64(0x0102_0304_0506_0708)
        .u64(77)
        .crc();
    assert_eq!(want.len(), 32, "§14.9: 32 bytes");
    let m = Manifest {
        sealer_id: 0,
        checkpoint_id: 0x0102_0304_0506_0708,
        first_wal_seq: 77,
    };
    assert_eq!(m.encode(), want);
    assert_eq!(Manifest::parse(&want, 0).unwrap(), m);
}

#[test]
// oracle: A §14.9 WAL segment header row, version 1 (G-18)
#[spec("SR-14-1", "SR-14.9-1")]
fn p2_format_wal_segment_header_bytes_are_the_spec_s() {
    let want = B::default()
        .raw(b"SVDBWALS")
        .u16(1)
        .u16(0)
        .u64(5)
        .u64(4_096)
        .crc();
    assert_eq!(want.len(), 32, "§14.9: 32 bytes");
    let s = SegmentHeader {
        sealer_id: 0,
        segment_seq: 5,
        first_wal_seq: 4_096,
    };
    assert_eq!(s.encode(), want);
    assert_eq!(SegmentHeader::parse(&want, 0).unwrap(), s);
}

#[test]
// oracle: A §14.9 SECRETS row (kind 1 is k_scramble, exactly one, 64 bytes), version 1 (G-18)
#[spec("SR-14-1", "SR-14.9-1")]
fn p2_format_secrets_bytes_are_the_spec_s() {
    let key: Vec<u8> = (0..64).collect();
    let want = B::default()
        .raw(b"SVDBSECR")
        .u16(1)
        .u16(0)
        .u32(1)
        .u16(1)
        .u32(64)
        .raw(&key)
        .crc();
    let s = Secrets {
        sealer_id: 0,
        entries: vec![(1, key.clone())],
    };
    assert_eq!(s.encode(), want);
    let p = Secrets::parse(&want, 0).unwrap();
    assert_eq!(p.k_scramble().unwrap().to_vec(), key);
}

#[test]
// oracle: A §14.9 "every parser rejects a wrong magic, version, sealer_id, CRC … or trailing byte"
#[spec("SR-14-2")]
fn p2_format_headers_refuse_what_the_spec_refuses() {
    let good = |version: u16, sealer: u16| {
        B::default()
            .raw(b"SVDBMANI")
            .u16(version)
            .u16(sealer)
            .u64(1)
            .u64(1)
            .crc()
    };
    assert!(Manifest::parse(&good(1, 0), 0).is_ok());
    assert!(Manifest::parse(&good(2, 0), 0).is_err(), "version 2");
    assert!(Manifest::parse(&good(0, 0), 0).is_err(), "version 0");
    assert!(
        Manifest::parse(&good(1, 1), 0).is_err(),
        "sealer 1 read by a sealer-0 build"
    );
    assert!(
        Manifest::parse(&good(1, 0), 1).is_err(),
        "sealer 0 read by a sealer-1 build"
    );
    let mut magic = good(1, 0);
    magic[..8].copy_from_slice(b"SVDBWALS");
    let n = magic.len() - 4;
    let c = crc32c(&magic[..n]);
    magic[n..].copy_from_slice(&c.to_be_bytes());
    assert!(Manifest::parse(&magic, 0).is_err(), "another file's magic");
    let mut long = good(1, 0);
    long.push(0);
    assert!(Manifest::parse(&long, 0).is_err(), "trailing byte");
    let mut bad_crc = good(1, 0);
    bad_crc[31] ^= 1;
    assert!(Manifest::parse(&bad_crc, 0).is_err(), "crc");
}

// ---------------------------------------------------------------------------------------------
// §14.6 WAL payloads (after-images)
// ---------------------------------------------------------------------------------------------

/// A §14.4 slot payload, plaintext sealer, no extension: `u16be id_len ‖ id padded to 256 ‖ x̃ as
/// d × i32be`.
fn payload_bytes(id: &str, x: &[i32]) -> Vec<u8> {
    let mut b = B::default()
        .u16(id.len() as u16)
        .raw(id.as_bytes())
        .zeros(256 - id.len());
    for v in x {
        b = b.raw(&v.to_be_bytes());
    }
    b.done()
}

/// A §14.4 slot, plaintext sealer: `scrambled_id (64) ‖ wrapped key (empty) ‖ payload ‖ padding to
/// 8`.
fn slot_bytes(sid: u8, id: &str, x: &[i32]) -> Vec<u8> {
    let p = payload_bytes(id, x);
    let len = 64 + p.len();
    B::default()
        .raw(&[sid; 64])
        .raw(&p)
        .zeros(len.next_multiple_of(8) - len)
        .done()
}

fn slot(sid: u8, id: &str, x: &[i32]) -> SlotBytes {
    SlotBytes {
        scrambled_id: ScrambledId::from_bytes([sid; 64]),
        envelope: vec![],
        sealed_payload: payload_bytes(id, x),
    }
}

/// A §14.3 group header, plaintext sealer, no extension: `group_id (32) ‖ kind ‖ seal_version ‖ n ‖
/// C_S (empty) ‖ centroid d × f64 ‖ S as d × i64` (no accumulator for the holding area).
fn header_bytes(label: &str, kind: u8, n: u64, centroid: f64, s: Option<i64>) -> Vec<u8> {
    let mut b = B::default().gid(label).u8(kind).u64(0).u64(n);
    for _ in 0..D {
        b = b.raw(&centroid.to_bits().to_be_bytes());
    }
    if let Some(s) = s {
        for _ in 0..D {
            b = b.raw(&s.to_be_bytes());
        }
    }
    b.done()
}

fn header(id: GroupId, n: u64, centroid: f64, s: Option<i64>) -> GroupHeader {
    GroupHeader {
        group_id: id,
        seal_version: 0,
        n,
        ext_public: vec![],
        centroid: vec![centroid; D],
        sealed_accumulator: s
            .map(|s| B::default().raw(&s.to_be_bytes()).done().repeat(D))
            .unwrap_or_default(),
    }
}

fn meta() -> CollectionMeta {
    CollectionMeta {
        cid: CollectionId::from_bytes(CID),
        d: D as u16,
        spawn_target: 200,
        spawning_enabled: true,
        store_passages: false,
        artefact_sha256: [0xa5; 32],
    }
}

/// §14.9 collection metadata: `collection_id ‖ u16be d ‖ u32be spawn_target ‖ u8
/// spawning_enabled ‖ u8 store_passages ‖ sha256_artefact (32)`.
fn meta_bytes() -> Vec<u8> {
    B::default()
        .raw(&CID)
        .u16(D as u16)
        .u32(200)
        .u8(1)
        .u8(0)
        .raw(&[0xa5; 32])
        .done()
}

#[test]
// oracle: A §14.6 type table and payload table; §14.3, §14.4, §14.9 metadata; G-19 group_id
#[spec("SR-14.6-2")]
fn p2_format_wal_payloads_are_the_spec_s() {
    let l = Layout::plain(D);
    let cid = CollectionId::from_bytes(CID);
    let sp = GroupId::Spawned([0xab; 8]);
    let x: Vec<i32> = (0..D as i32).map(|i| i * 1_000 - 7).collect();
    let cases: Vec<(CoreRecord, u8, Vec<u8>)> = vec![
        (CoreRecord::Begin, 1, vec![]),
        (CoreRecord::Commit, 15, vec![]),
        (
            CoreRecord::CollectionCreate {
                meta: meta(),
                artefact: vec![9, 8, 7],
            },
            16,
            B::default()
                .raw(&meta_bytes())
                .u32(3)
                .raw(&[9, 8, 7])
                .done(),
        ),
        (CoreRecord::CollectionDrop { cid }, 17, CID.to_vec()),
        (
            CoreRecord::GroupCreate {
                cid,
                header: header(sp, 0, 0.5, Some(0)),
                bucket_block: vec![],
            },
            2,
            B::default()
                .raw(&CID)
                .raw(&header_bytes("spawn-abababababababab", 1, 0, 0.5, Some(0)))
                .u32(0)
                .done(),
        ),
        (
            CoreRecord::GroupHeader {
                cid,
                header: header(GroupId::frozen(7).unwrap(), 3, -1.25, Some(-42)),
            },
            3,
            B::default()
                .raw(&CID)
                .raw(&header_bytes("frozen-0007", 0, 3, -1.25, Some(-42)))
                .done(),
        ),
        (
            CoreRecord::GroupHeader {
                cid,
                header: header(GroupId::Holding, 2, 0.0, None),
            },
            3,
            B::default()
                .raw(&CID)
                .raw(&header_bytes("holding", 2, 2, 0.0, None))
                .done(),
        ),
        (
            CoreRecord::SlotPut {
                cid,
                group: GroupId::frozen(7).unwrap(),
                index: 5,
                slot: slot(0x33, "doc-1", &x),
            },
            5,
            B::default()
                .raw(&CID)
                .gid("frozen-0007")
                .u64(5)
                .raw(&slot_bytes(0x33, "doc-1", &x))
                .done(),
        ),
        (
            CoreRecord::SlotTruncate {
                cid,
                group: GroupId::Holding,
                len: 199,
            },
            6,
            B::default().raw(&CID).gid("holding").u64(199).done(),
        ),
        (
            CoreRecord::LocatorPut {
                cid,
                scrambled_id: ScrambledId::from_bytes([0x44; 64]),
                group: sp,
                index: 9,
            },
            7,
            B::default()
                .raw(&CID)
                .raw(&[0x44; 64])
                .gid("spawn-abababababababab")
                .u64(9)
                .done(),
        ),
        (
            CoreRecord::LocatorDel {
                cid,
                scrambled_id: ScrambledId::from_bytes([0x44; 64]),
            },
            8,
            B::default().raw(&CID).raw(&[0x44; 64]).done(),
        ),
        (
            CoreRecord::PayloadRef {
                cid,
                scrambled_id: ScrambledId::from_bytes([0x55; 64]),
                at: PayloadRef {
                    segment: 2,
                    offset: 16,
                    len: 300,
                },
            },
            12,
            B::default()
                .raw(&CID)
                .raw(&[0x55; 64])
                .u64(2)
                .u64(16)
                .u32(300)
                .done(),
        ),
        (
            CoreRecord::Counters {
                cid,
                big_n: 1_000,
                k: 130,
            },
            13,
            B::default().raw(&CID).u64(1_000).u64(130).done(),
        ),
        (
            CoreRecord::Participant {
                ty: RecordType::Extension,
                bytes: vec![0, 3, 0xde, 0xad],
            },
            14,
            vec![0, 3, 0xde, 0xad],
        ),
    ];
    for (rec, code, want) in cases {
        assert_eq!(rec.ty() as u8, code, "§14.6 type code of {rec:?}");
        assert_eq!(
            rec.encode_payload(&l).unwrap(),
            want,
            "§14.6 payload of {rec:?}"
        );
    }
}

// ---------------------------------------------------------------------------------------------
// §14.9 storage checkpoint streams
// ---------------------------------------------------------------------------------------------

#[test]
// oracle: A §14.9 stream rows (meta, collections, groups, slots, locator, payloads); G-19 group_id
#[spec("SR-14.9-1")]
fn p2_format_checkpoint_streams_are_the_spec_s() {
    let l = Layout::plain(D);
    let cid = CollectionId::from_bytes(CID);
    let f0 = GroupId::frozen(0).unwrap();
    let xa = vec![1i32; D];
    let xb = vec![-2i32; D];
    let mut img = DbImage::default();
    for r in [
        CoreRecord::CollectionCreate {
            meta: meta(),
            artefact: vec![1, 2, 3],
        },
        CoreRecord::GroupCreate {
            cid,
            header: header(f0, 1, 0.25, Some(1)),
            bucket_block: vec![],
        },
        CoreRecord::GroupCreate {
            cid,
            header: header(GroupId::Holding, 1, 0.0, None),
            bucket_block: vec![],
        },
        CoreRecord::SlotPut {
            cid,
            group: f0,
            index: 0,
            slot: slot(0x20, "a", &xa),
        },
        CoreRecord::SlotPut {
            cid,
            group: GroupId::Holding,
            index: 0,
            slot: slot(0x10, "b", &xb),
        },
        // Inserted in descending scrambled_id order; the streams list them ascending.
        CoreRecord::LocatorPut {
            cid,
            scrambled_id: ScrambledId::from_bytes([0x20; 64]),
            group: f0,
            index: 0,
        },
        CoreRecord::LocatorPut {
            cid,
            scrambled_id: ScrambledId::from_bytes([0x10; 64]),
            group: GroupId::Holding,
            index: 0,
        },
        CoreRecord::PayloadRef {
            cid,
            scrambled_id: ScrambledId::from_bytes([0x20; 64]),
            at: PayloadRef {
                segment: 1,
                offset: 16,
                len: 40,
            },
        },
        CoreRecord::PayloadRef {
            cid,
            scrambled_id: ScrambledId::from_bytes([0x10; 64]),
            at: PayloadRef {
                segment: 1,
                offset: 72,
                len: 8,
            },
        },
        CoreRecord::Counters {
            cid,
            big_n: 1,
            k: 1,
        },
    ] {
        img.apply(&r).unwrap();
    }
    let cm = CheckpointMeta {
        checkpoint_id: 3,
        next_wal_seq: 900,
        next_txn_id: 41,
        config_hash: [0x77; 32],
    };
    let s = img.to_streams(&cm, &|_| l).unwrap();

    let meta_stream = B::default()
        .u64(3)
        .u64(900)
        .u64(41)
        .raw(&[0x77; 32])
        .u32(1)
        .raw(&CID)
        .done();
    assert_eq!(s.meta, meta_stream, "meta.bin");

    let collections = B::default().raw(&meta_bytes()).u64(1).u64(1).done();
    assert_eq!(s.collections, collections, "collections.bin");

    let groups = B::default()
        .raw(&CID)
        .u64(2)
        .raw(&header_bytes("frozen-0000", 0, 1, 0.25, Some(1)))
        .raw(&header_bytes("holding", 2, 1, 0.0, None))
        .done();
    assert_eq!(s.groups, groups, "groups.bin: headers in creation order");

    let slots = B::default()
        .raw(&CID)
        .gid("frozen-0000")
        .u64(1)
        .raw(&slot_bytes(0x20, "a", &xa))
        .raw(&CID)
        .gid("holding")
        .u64(1)
        .raw(&slot_bytes(0x10, "b", &xb))
        .done();
    assert_eq!(s.slots, slots, "slots.bin: per group, in slot order");

    let locator = B::default()
        .raw(&CID)
        .u64(2)
        .raw(&[0x10; 64])
        .gid("holding")
        .u64(0)
        .raw(&[0x20; 64])
        .gid("frozen-0000")
        .u64(0)
        .done();
    assert_eq!(s.locator, locator, "locator.bin: ascending by scrambled_id");

    let payloads = B::default()
        .raw(&CID)
        .u64(2)
        .raw(&[0x10; 64])
        .u64(1)
        .u64(72)
        .u32(8)
        .raw(&[0x20; 64])
        .u64(1)
        .u64(16)
        .u32(40)
        .done();
    assert_eq!(
        s.payload_refs, payloads,
        "payloads.bin: ascending by scrambled_id"
    );
}
