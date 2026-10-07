//! L3 conformance of the paged checkpoint files (spec §14.2 and the "Storage checkpoint files" row
//! of §14.9's table). Offsets and sizes come from the spec text, and the CRC-32C here is an
//! independent bitwise implementation checked against the standard check value, so every
//! tampered page is re-sealed without the crate's help: only the rule under test is broken.
//!
//! §14.2: 16,384-byte pages, `u32be page_type ‖ u64be page_no ‖ u64be wal_seq ‖ payload ‖ u32be
//! crc32c`. Page 0 (type 1) holds `magic ‖ u16be version ‖ u16be sealer_id ‖ u64be stream_len`,
//! then zeros; pages 1… (type 2) carry the stream, the last zero-padded; every page carries the
//! covered `wal_seq`.

#![allow(clippy::unwrap_used, clippy::indexing_slicing, clippy::panic)]

use sever_format::paged::{decode, encode};
use sever_spec::spec;

const PAGE: usize = 16_384;
const PAYLOAD: usize = PAGE - 4 - 8 - 8 - 4; // 16,360
const MAGIC: [u8; 8] = *b"SVTESTPG";

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

/// A stream of three data pages: two full, one partial.
fn stream() -> Vec<u8> {
    (0..2 * PAYLOAD + 100)
        .map(|i| (i * 31 % 253) as u8)
        .collect()
}

fn file() -> Vec<u8> {
    encode(&MAGIC, 0, 77, &stream())
}

/// Rewrites page `no`'s CRC after a change.
fn reseal(f: &mut [u8], no: usize) {
    let p = &mut f[no * PAGE..(no + 1) * PAGE];
    let c = crc32c(&p[..PAGE - 4]);
    p[PAGE - 4..].copy_from_slice(&c.to_be_bytes());
}

/// Changes bytes at `at` of page `no`, re-seals it, and decodes.
fn decode_with(no: usize, at: usize, bytes: &[u8]) -> Result<(u64, Vec<u8>), sever_types::Error> {
    let mut f = file();
    f[no * PAGE + at..no * PAGE + at + bytes.len()].copy_from_slice(bytes);
    reseal(&mut f, no);
    decode(&f, &MAGIC, 0)
}

fn refused(r: Result<(u64, Vec<u8>), sever_types::Error>, rule: &str) {
    match r {
        Err(sever_types::Error::IntegrityViolation { invariant }) => {
            assert!(
                invariant.contains(rule),
                "refused for {invariant}, not {rule}"
            )
        }
        other => panic!("accepted or wrong error ({other:?}); wanted {rule}"),
    }
}

#[test]
#[spec("SR-14.2-1")]
fn p2_format_paged_layout_is_the_spec_s() {
    let f = file();
    assert_eq!(f.len(), 4 * PAGE, "one header page and three data pages");
    for no in 0..4 {
        let p = &f[no * PAGE..(no + 1) * PAGE];
        let ty = u32::from_be_bytes(p[0..4].try_into().unwrap());
        assert_eq!(ty, if no == 0 { 1 } else { 2 });
        assert_eq!(u64::from_be_bytes(p[4..12].try_into().unwrap()), no as u64);
        assert_eq!(u64::from_be_bytes(p[12..20].try_into().unwrap()), 77);
        assert_eq!(
            u32::from_be_bytes(p[PAGE - 4..].try_into().unwrap()),
            crc32c(&p[..PAGE - 4])
        );
    }
    assert_eq!(&f[20..28], &MAGIC);
    assert_eq!(u16::from_be_bytes([f[28], f[29]]), 1, "format_version 1");
    assert_eq!(u16::from_be_bytes([f[30], f[31]]), 0, "sealer_id");
    assert_eq!(
        u64::from_be_bytes(f[32..40].try_into().unwrap()),
        stream().len() as u64
    );
    assert!(f[40..PAGE - 4].iter().all(|&b| b == 0), "header zeros");
    let s = stream();
    assert_eq!(&f[PAGE + 20..PAGE + 20 + PAYLOAD], &s[..PAYLOAD]);
    let last = 3 * PAGE + 20;
    assert_eq!(&f[last..last + 100], &s[2 * PAYLOAD..]);
    assert!(
        f[last + 100..4 * PAGE - 4].iter().all(|&b| b == 0),
        "last page zero-padded"
    );
    assert_eq!(decode(&f, &MAGIC, 0).unwrap(), (77, s));
}

#[test]
#[spec("SR-14.2-1")]
fn p2_format_paged_refuses_a_broken_page_frame() {
    let mut f = file();
    f.pop();
    refused(decode(&f, &MAGIC, 0), "§14.2 page size");
    refused(decode(&[], &MAGIC, 0), "§14.2 page size");
    let mut f = file();
    f[PAGE + 100] ^= 1; // not re-sealed
    refused(decode(&f, &MAGIC, 0), "§14.2 page crc");
    refused(decode_with(2, 4, &5u64.to_be_bytes()), "§14.2 page number");
}

#[test]
#[spec("SR-14.2-1")]
fn p2_format_paged_refuses_a_wrong_header_page() {
    refused(decode_with(0, 0, &2u32.to_be_bytes()), "§14.2 page type");
    refused(decode(&file(), b"OTHERMAG", 0), "§14 file magic");
    refused(
        decode_with(0, 28, &2u16.to_be_bytes()),
        "§14 format version",
    );
    refused(decode(&file(), &MAGIC, 1), "DB-48 sealer_id");
    let longer = (stream().len() + PAYLOAD) as u64;
    refused(
        decode_with(0, 32, &longer.to_be_bytes()),
        "§14.2 stream length",
    );
    refused(decode_with(0, 500, &[1]), "§14.2 header padding");
}

#[test]
#[spec("SR-14.2-1")]
fn p2_format_paged_refuses_a_wrong_data_page() {
    refused(decode_with(1, 0, &1u32.to_be_bytes()), "§14.2 page type");
    // Every page carries the same covered wal_seq.
    refused(decode_with(2, 12, &78u64.to_be_bytes()), "§14.2 page type");
    refused(decode_with(3, 20 + 100, &[9]), "§14.2 page padding");
}
