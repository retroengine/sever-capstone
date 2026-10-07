//! Paged files (spec §14.2): every storage checkpoint file is a sequence of 16,384-byte pages,
//! `u32be page_type ‖ u64be page_no ‖ u64be wal_seq ‖ payload ‖ u32be crc32c`.
//!
//! Page 0 (type 1) holds the file header: `magic ‖ u16be format_version ‖ u16be sealer_id
//! (DB-48) ‖ u64be stream_len`, then zeros. Pages 1… (type 2) carry the file's byte stream in
//! order; the last page is zero-padded. Every page carries the `wal_seq` the checkpoint covers, so
//! a page from another checkpoint is rejected, and every byte of the file is under a CRC.

use sever_types::Error;

use crate::FORMAT_VERSION;
use crate::codec::{Reader, Writer, bad, crc};

/// Page size (§14.2, §18.1 `page_size_bytes`).
pub const PAGE: usize = 16_384;
/// Payload bytes per page: page size minus type, number, `wal_seq` and CRC.
pub const PAGE_PAYLOAD: usize = PAGE - 4 - 8 - 8 - 4;
/// Page type of the header page.
pub const PAGE_HEADER: u32 = 1;
/// Page type of a data page.
pub const PAGE_DATA: u32 = 2;

fn page(page_type: u32, page_no: u64, wal_seq: u64, payload: &[u8], out: &mut Vec<u8>) {
    let start = out.len();
    let mut w = Writer::new();
    w.u32(page_type).u64(page_no).u64(wal_seq).bytes(payload);
    w.0.resize(PAGE - 4, 0);
    let c = crc(&w.0);
    w.u32(c);
    out.extend_from_slice(&w.0);
    debug_assert_eq!(out.len() - start, PAGE);
}

/// Encodes `stream` as a paged file.
pub fn encode(magic: &[u8; 8], sealer_id: u16, wal_seq: u64, stream: &[u8]) -> Vec<u8> {
    let pages = stream.len().div_ceil(PAGE_PAYLOAD);
    let mut out = Vec::with_capacity((pages + 1) * PAGE);
    let mut h = Writer::new();
    h.bytes(magic)
        .u16(FORMAT_VERSION)
        .u16(sealer_id)
        .u64(stream.len() as u64);
    page(PAGE_HEADER, 0, wal_seq, &h.0, &mut out);
    for (i, chunk) in stream.chunks(PAGE_PAYLOAD).enumerate() {
        page(PAGE_DATA, i as u64 + 1, wal_seq, chunk, &mut out);
    }
    out
}

/// Decodes a paged file; returns `(wal_seq, stream)`.
pub fn decode(bytes: &[u8], magic: &[u8; 8], sealer_id: u16) -> Result<(u64, Vec<u8>), Error> {
    if bytes.is_empty() || bytes.len() % PAGE != 0 {
        return Err(bad("§14.2 page size"));
    }
    let mut stream = Vec::new();
    let mut seq = 0u64;
    let mut want_len = 0usize;
    for (no, p) in bytes.chunks_exact(PAGE).enumerate() {
        let (body, tail) = p.split_last_chunk::<4>().ok_or(bad("§14.2 page"))?;
        if crc(body) != u32::from_be_bytes(*tail) {
            return Err(bad("§14.2 page crc"));
        }
        let mut r = Reader::new(body, "§14.2 page");
        let ty = r.u32()?;
        if r.u64()? != no as u64 {
            return Err(bad("§14.2 page number"));
        }
        let wal_seq = r.u64()?;
        if no == 0 {
            if ty != PAGE_HEADER {
                return Err(bad("§14.2 page type"));
            }
            seq = wal_seq;
            if r.array::<8>()? != *magic {
                return Err(bad("§14 file magic"));
            }
            if r.u16()? != FORMAT_VERSION {
                return Err(bad("§14 format version"));
            }
            if r.u16()? != sealer_id {
                return Err(bad("DB-48 sealer_id"));
            }
            want_len = usize::try_from(r.u64()?).map_err(|_| bad("§14.2 stream length"))?;
            if want_len.div_ceil(PAGE_PAYLOAD) + 1 != bytes.len() / PAGE {
                return Err(bad("§14.2 stream length"));
            }
            if r.take(r.remaining())?.iter().any(|&b| b != 0) {
                return Err(bad("§14.2 header padding"));
            }
        } else {
            if ty != PAGE_DATA || wal_seq != seq {
                return Err(bad("§14.2 page type"));
            }
            let take = (want_len - stream.len()).min(PAGE_PAYLOAD);
            stream.extend_from_slice(r.take(take)?);
            if r.take(r.remaining())?.iter().any(|&b| b != 0) {
                return Err(bad("§14.2 page padding"));
            }
        }
    }
    Ok((seq, stream))
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;
    use sever_spec::spec;

    #[test]
    #[spec("SR-14.2-1")]
    fn p2_format_page_layout_by_offset() {
        let f = encode(b"SVDBTEST", 0, 77, &[5; 10]);
        assert_eq!(f.len(), 2 * PAGE);
        assert_eq!(&f[..4], &PAGE_HEADER.to_be_bytes());
        assert_eq!(&f[4..12], &0u64.to_be_bytes(), "page_no");
        assert_eq!(&f[12..20], &77u64.to_be_bytes(), "wal_seq");
        assert_eq!(&f[20..28], b"SVDBTEST");
        let p1 = &f[PAGE..];
        assert_eq!(&p1[..4], &PAGE_DATA.to_be_bytes());
        assert_eq!(&p1[4..12], &1u64.to_be_bytes());
        assert_eq!(&p1[20..30], &[5; 10]);
        assert_eq!(&p1[PAGE - 4..], &crc(&p1[..PAGE - 4]).to_be_bytes());
    }

    #[test]
    fn p2_format_paged_round_trip_at_page_boundaries() {
        for n in [
            0,
            1,
            PAGE_PAYLOAD - 1,
            PAGE_PAYLOAD,
            PAGE_PAYLOAD + 1,
            3 * PAGE_PAYLOAD,
        ] {
            let s: Vec<u8> = (0..n).map(|i| (i % 251) as u8).collect();
            let f = encode(b"SVDBTEST", 1, 5, &s);
            assert_eq!(f.len(), (n.div_ceil(PAGE_PAYLOAD) + 1) * PAGE);
            assert_eq!(decode(&f, b"SVDBTEST", 1).unwrap(), (5, s), "n = {n}");
        }
    }

    #[test]
    #[spec("SR-14-2", "SR-12.7-4")]
    fn p2_format_paged_detects_bit_flips_and_mixups() {
        let f = encode(b"SVDBTEST", 0, 5, &[1; 100]);
        for i in (0..f.len() * 8).step_by(97) {
            let mut g = f.clone();
            g[i / 8] ^= 1 << (i % 8);
            assert!(decode(&g, b"SVDBTEST", 0).is_err(), "bit {i}");
        }
        assert!(decode(&f, b"SVDBXXXX", 0).is_err());
        assert!(decode(&f, b"SVDBTEST", 1).is_err());
        assert!(decode(&f[..PAGE], b"SVDBTEST", 0).is_err(), "missing page");
        let other = encode(b"SVDBTEST", 0, 6, &[1; 100]);
        let mut mixed = f[..PAGE].to_vec();
        mixed.extend_from_slice(&other[PAGE..]);
        assert!(
            decode(&mixed, b"SVDBTEST", 0).is_err(),
            "page from another checkpoint"
        );
    }

    proptest! {
        #![proptest_config(ProptestConfig::with_cases(32))]
        #[test]
        fn p2_format_prop_paged_round_trips(s in prop::collection::vec(any::<u8>(), 0..40_000)) {
            let f = encode(b"SVDBTEST", 0, 1, &s);
            prop_assert_eq!(decode(&f, b"SVDBTEST", 0).unwrap(), (1, s));
        }
    }
}
