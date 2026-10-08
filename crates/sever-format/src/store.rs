//! Append-store records (spec §14.8): `u64be key ‖ u32be len ‖ bytes ‖ u32be crc32c`, after a
//! 16-byte file header (DB-48).

use crate::codec::{Writer, crc};

/// The largest stored value (passage text, a certificate): 16 MiB.
pub const MAX_VALUE: usize = 16 * 1024 * 1024;

/// One record.
#[derive(Clone, PartialEq, Eq)]
pub struct StoreRecord {
    /// `database_lsn`, a leaf index or a sequence number (§14.8).
    pub key: u64,
    /// The stored bytes.
    pub bytes: Vec<u8>,
}

impl core::fmt::Debug for StoreRecord {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(
            f,
            "StoreRecord(key {}, {} bytes)",
            self.key,
            self.bytes.len()
        )
    }
}

impl StoreRecord {
    /// Bytes around the value: key 8, len 4, crc 4.
    pub const OVERHEAD: usize = 16;

    /// The encoded record.
    pub fn encode(&self) -> Vec<u8> {
        let mut w = Writer(Vec::with_capacity(Self::OVERHEAD + self.bytes.len()));
        w.u64(self.key)
            .u32(u32::try_from(self.bytes.len()).unwrap_or(u32::MAX))
            .bytes(&self.bytes);
        let c = crc(&w.0);
        w.u32(c);
        w.finish()
    }

    /// The record at the start of `buf` and its encoded length, or `None` if it is not a
    /// complete, valid record (a torn or unreferenced tail, §14.8).
    pub fn parse_next(buf: &[u8]) -> Option<(Self, usize)> {
        let key = u64::from_be_bytes(*buf.first_chunk::<8>()?);
        let len = u32::from_be_bytes(*buf.get(8..12)?.first_chunk::<4>()?) as usize;
        if len > MAX_VALUE {
            return None;
        }
        let total = Self::OVERHEAD + len;
        let rec = buf.get(..total)?;
        let (body, tail) = rec.split_last_chunk::<4>()?;
        if crc(body) != u32::from_be_bytes(*tail) {
            return None;
        }
        Some((
            Self {
                key,
                bytes: body.get(12..)?.to_vec(),
            },
            total,
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;
    use sever_spec::spec;

    #[test]
    // oracle: A §14.8 record layout by hand (the CRC value comes from the crate)
    #[spec("SR-14.8-1")]
    fn p2_format_store_record_layout_by_offset() {
        let r = StoreRecord {
            key: 9,
            bytes: b"text".to_vec(),
        };
        let b = r.encode();
        assert_eq!(&b[..8], &9u64.to_be_bytes());
        assert_eq!(&b[8..12], &4u32.to_be_bytes());
        assert_eq!(&b[12..16], b"text");
        assert_eq!(&b[16..], &crc(&b[..16]).to_be_bytes());
        assert_eq!(StoreRecord::parse_next(&b), Some((r, 20)));
    }

    #[test]
    // oracle: A §14.9 a wrong CRC is refused; §14.8 a torn record is not a record
    #[spec("SR-14-2")]
    fn p2_format_store_record_detects_every_bit_flip_and_tear() {
        let b = StoreRecord {
            key: 1,
            bytes: vec![0x5a; 20],
        }
        .encode();
        for i in 0..b.len() * 8 {
            let mut f = b.clone();
            f[i / 8] ^= 1 << (i % 8);
            assert_eq!(StoreRecord::parse_next(&f), None, "bit {i}");
        }
        for n in 0..b.len() {
            assert_eq!(StoreRecord::parse_next(&b[..n]), None, "torn at {n}");
        }
    }

    proptest! {
        #[test]
        fn p2_format_prop_store_record_round_trips(key in any::<u64>(), bytes in prop::collection::vec(any::<u8>(), 0..500)) {
            let r = StoreRecord { key, bytes };
            let b = r.encode();
            prop_assert_eq!(StoreRecord::parse_next(&b), Some((r, b.len())));
        }
    }
}
