//! L3 conformance of the bytes a `FileStore` leaves on disk (spec §14.8, §14.9 file header row),
//! read raw from the simulated disk (CLAUDE.md §6.3, oracle A). Expected bytes are written here
//! from the spec, with an independent bitwise CRC-32C; the store magic and version are DB-71's.

#![allow(clippy::unwrap_used, clippy::indexing_slicing)]

use std::sync::Arc;

use sever_appendstore::{AppendStore, DEFAULT_SEGMENT_BYTES, FileStore, StoreConfig};
use sever_spec::spec;
use sever_vfs::{OpenMode, SimVfs, Vfs, read_all};

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

/// `u64be key ‖ u32be len ‖ bytes ‖ u32be crc32c` (§14.8).
fn record(key: u64, bytes: &[u8]) -> Vec<u8> {
    let mut r = key.to_be_bytes().to_vec();
    r.extend_from_slice(&(bytes.len() as u32).to_be_bytes());
    r.extend_from_slice(bytes);
    let c = crc32c(&r);
    r.extend_from_slice(&c.to_be_bytes());
    r
}

#[test]
// oracle: A §14.8 records after the 16-byte §14.9 file header (SVDBSTOR, version 1: DB-71)
#[spec("SR-14.8-1", "SR-14-1")]
fn p2_store_file_on_disk_is_the_spec_s() {
    let v = SimVfs::new();
    let cfg = StoreConfig {
        dir: "payloads".into(),
        sealer_id: 0,
        segment_bytes: DEFAULT_SEGMENT_BYTES,
    };
    let mut s = FileStore::create(Arc::new(v.clone()), cfg).unwrap();
    let a = s.append(7, b"first passage").unwrap();
    let b = s.append(u64::MAX, b"").unwrap();
    s.sync().unwrap();

    let mut header = b"SVDBSTOR".to_vec();
    header.extend_from_slice(&1u16.to_be_bytes());
    header.extend_from_slice(&0u16.to_be_bytes());
    let c = crc32c(&header);
    header.extend_from_slice(&c.to_be_bytes());
    let mut want = header;
    want.extend(record(7, b"first passage"));
    want.extend(record(u64::MAX, b""));

    // §14.1: one file payloads/<seq>.store (the width of <seq> is not specified, so not checked).
    let names = v.list("payloads").unwrap();
    assert_eq!(names.len(), 1, "{names:?}");
    let stem = names[0].strip_suffix(".store").unwrap();
    assert!(stem.bytes().all(|c| c.is_ascii_digit()), "{stem}");
    let file = v
        .open(&format!("payloads/{}", names[0]), OpenMode::Existing)
        .unwrap();
    assert_eq!(read_all(file.as_ref()).unwrap(), want);

    // A reference names the record's offset in the file and its value length (§14.6 PAYLOAD_REF).
    assert_eq!((a.offset, a.len), (16, 13));
    assert_eq!((b.offset, b.len), (16 + 8 + 4 + 13 + 4, 0));
}
