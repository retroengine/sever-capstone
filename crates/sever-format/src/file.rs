//! File-level structures: the common file header (DB-48), WAL segment headers, `MANIFEST` and
//! `SECRETS` (spec §14.1, §12.4).

use sever_types::Error;
use sever_types::constants::SCRAMBLE_KEY_BYTES;

use crate::codec::{Reader, Writer, bad, crc};
use crate::{FORMAT_VERSION, magic};

/// Checks magic, version and sealer in that order, naming the failed one.
fn check_ident(
    r: &mut Reader<'_>,
    want_magic: &[u8; 8],
    sealer_id: u16,
    what: &'static str,
) -> Result<(), Error> {
    if r.array::<8>()? != *want_magic {
        return Err(bad(what));
    }
    if r.u16()? != FORMAT_VERSION {
        return Err(bad("§14 format version"));
    }
    if r.u16()? != sealer_id {
        return Err(bad("DB-48 sealer_id"));
    }
    Ok(())
}

/// Splits `bytes` into the body and its trailing CRC-32C, checking the CRC.
fn split_crc<'a>(bytes: &'a [u8], what: &'static str) -> Result<&'a [u8], Error> {
    let (body, tail) = bytes
        .split_last_chunk::<4>()
        .map(|(b, t)| (b, *t))
        .ok_or(bad(what))?;
    if crc(body) == u32::from_be_bytes(tail) {
        Ok(body)
    } else {
        Err(bad(what))
    }
}

/// The 16-byte header of a streamed file (an append store): `magic ‖ u16be format_version ‖
/// u16be sealer_id ‖ u32be crc32c`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FileHeader {
    /// The file's magic.
    pub magic: [u8; 8],
    /// The sealer the file was written with (DB-48).
    pub sealer_id: u16,
}

impl FileHeader {
    /// Encoded size.
    pub const LEN: usize = 16;

    /// The 16 bytes.
    pub fn encode(&self) -> Vec<u8> {
        let mut w = Writer::new();
        w.bytes(&self.magic).u16(FORMAT_VERSION).u16(self.sealer_id);
        let c = crc(&w.0);
        w.u32(c);
        w.finish()
    }

    /// Parses and checks a header that must have `magic` and `sealer_id`.
    pub fn parse(bytes: &[u8], magic: &[u8; 8], sealer_id: u16) -> Result<Self, Error> {
        let body = split_crc(bytes, "§14 file header crc")?;
        let mut r = Reader::new(body, "§14 file header");
        check_ident(&mut r, magic, sealer_id, "§14 file magic")?;
        r.end()?;
        Ok(Self {
            magic: *magic,
            sealer_id,
        })
    }
}

/// The header of a WAL segment `wal/<seq>.wal`: `magic ‖ u16be version ‖ u16be sealer_id ‖
/// u64be segment_seq ‖ u64be first_wal_seq ‖ u32be crc32c` (32 bytes).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SegmentHeader {
    /// The sealer (DB-48).
    pub sealer_id: u16,
    /// The segment's number, as in its file name.
    pub segment_seq: u64,
    /// The `wal_seq` of its first record.
    pub first_wal_seq: u64,
}

impl SegmentHeader {
    /// Encoded size.
    pub const LEN: usize = 32;

    /// The 32 bytes.
    pub fn encode(&self) -> Vec<u8> {
        let mut w = Writer::new();
        w.bytes(&magic::WAL_SEGMENT)
            .u16(FORMAT_VERSION)
            .u16(self.sealer_id)
            .u64(self.segment_seq)
            .u64(self.first_wal_seq);
        let c = crc(&w.0);
        w.u32(c);
        w.finish()
    }

    /// Parses a header written with `sealer_id`.
    pub fn parse(bytes: &[u8], sealer_id: u16) -> Result<Self, Error> {
        let body = split_crc(bytes, "§14.6 segment header crc")?;
        let mut r = Reader::new(body, "§14.6 segment header");
        check_ident(
            &mut r,
            &magic::WAL_SEGMENT,
            sealer_id,
            "§14.6 segment magic",
        )?;
        let h = Self {
            sealer_id,
            segment_seq: r.u64()?,
            first_wal_seq: r.u64()?,
        };
        r.end()?;
        Ok(h)
    }
}

/// `MANIFEST` (§14.1, §15.6 step 3): the current storage checkpoint and the first WAL position
/// still needed. `magic ‖ u16be version ‖ u16be sealer_id ‖ u64be checkpoint_id ‖ u64be
/// first_wal_seq ‖ u32be crc32c` (32 bytes).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Manifest {
    /// The sealer (DB-48).
    pub sealer_id: u16,
    /// `checkpoint/<id>/` is current.
    pub checkpoint_id: u64,
    /// Replay starts at the record with this `wal_seq`; earlier records are covered.
    pub first_wal_seq: u64,
}

impl Manifest {
    /// Encoded size.
    pub const LEN: usize = 32;

    /// The 32 bytes.
    pub fn encode(&self) -> Vec<u8> {
        let mut w = Writer::new();
        w.bytes(&magic::MANIFEST)
            .u16(FORMAT_VERSION)
            .u16(self.sealer_id)
            .u64(self.checkpoint_id)
            .u64(self.first_wal_seq);
        let c = crc(&w.0);
        w.u32(c);
        w.finish()
    }

    /// Parses a manifest written with `sealer_id`.
    pub fn parse(bytes: &[u8], sealer_id: u16) -> Result<Self, Error> {
        let body = split_crc(bytes, "§14.1 MANIFEST crc")?;
        let mut r = Reader::new(body, "§14.1 MANIFEST");
        check_ident(&mut r, &magic::MANIFEST, sealer_id, "§14.1 MANIFEST magic")?;
        let m = Self {
            sealer_id,
            checkpoint_id: r.u64()?,
            first_wal_seq: r.u64()?,
        };
        r.end()?;
        Ok(m)
    }
}

/// `SECRETS` (§14.1): `magic ‖ u16be version ‖ u16be sealer_id ‖ u32be entry_count ‖ entries ‖
/// u32be crc32c`, each entry `u16be kind ‖ u32be len ‖ bytes`. Kind 1 is `k_scramble` (64 bytes,
/// §9.7). Later parts add kinds (Part 3: operator signing keys by epoch).
#[derive(Clone, PartialEq, Eq)]
pub struct Secrets {
    /// The sealer of the database this belongs to (DB-48).
    pub sealer_id: u16,
    /// Every entry, in file order.
    pub entries: Vec<(u16, Vec<u8>)>,
}

impl core::fmt::Debug for Secrets {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "Secrets({} entries, redacted)", self.entries.len())
    }
}

impl Secrets {
    /// Entry kind of `k_scramble`.
    pub const K_SCRAMBLE: u16 = 1;

    /// The bytes.
    pub fn encode(&self) -> Vec<u8> {
        let mut w = Writer::new();
        w.bytes(&magic::SECRETS)
            .u16(FORMAT_VERSION)
            .u16(self.sealer_id)
            .u32(u32::try_from(self.entries.len()).unwrap_or(u32::MAX));
        for (kind, bytes) in &self.entries {
            w.u16(*kind).var(bytes);
        }
        let c = crc(&w.0);
        w.u32(c);
        w.finish()
    }

    /// Parses `SECRETS` written with `sealer_id`.
    pub fn parse(bytes: &[u8], sealer_id: u16) -> Result<Self, Error> {
        let body = split_crc(bytes, "§14.1 SECRETS crc")?;
        let mut r = Reader::new(body, "§14.1 SECRETS");
        check_ident(&mut r, &magic::SECRETS, sealer_id, "§14.1 SECRETS magic")?;
        let n = r.u32()?;
        let mut entries = Vec::new();
        for _ in 0..n {
            let kind = r.u16()?;
            entries.push((kind, r.var()?.to_vec()));
        }
        r.end()?;
        Ok(Self { sealer_id, entries })
    }

    /// `k_scramble`: exactly one entry of kind 1, exactly 64 bytes.
    pub fn k_scramble(&self) -> Result<[u8; SCRAMBLE_KEY_BYTES], Error> {
        let mut found = self.entries.iter().filter(|(k, _)| *k == Self::K_SCRAMBLE);
        match (found.next(), found.next()) {
            (Some((_, key)), None) => <[u8; SCRAMBLE_KEY_BYTES]>::try_from(key.as_slice())
                .map_err(|_| bad("§9.7 k_scramble")),
            _ => Err(bad("§9.7 k_scramble")),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sever_spec::spec;

    #[test]
    #[spec("SR-14-1", "SR-14-2")]
    fn p2_format_file_header_round_trips_and_checks_every_field() {
        let h = FileHeader {
            magic: magic::STORE,
            sealer_id: 0,
        };
        let b = h.encode();
        assert_eq!(b.len(), FileHeader::LEN);
        assert_eq!(FileHeader::parse(&b, &magic::STORE, 0), Ok(h));
        assert_eq!(
            FileHeader::parse(&b, &magic::STORE, 1),
            Err(bad("DB-48 sealer_id"))
        );
        assert_eq!(
            FileHeader::parse(&b, &magic::SLOTS, 0),
            Err(bad("§14 file magic"))
        );
        let mut v2 = Writer::new();
        v2.bytes(&magic::STORE).u16(2).u16(0);
        let c = crc(&v2.0);
        v2.u32(c);
        assert_eq!(
            FileHeader::parse(&v2.0, &magic::STORE, 0),
            Err(bad("§14 format version"))
        );
    }

    #[test]
    #[spec("SR-14-1", "SR-14.9-1")]
    fn p2_format_manifest_and_segment_header_round_trip() {
        let m = Manifest {
            sealer_id: 0,
            checkpoint_id: 7,
            first_wal_seq: 1_234,
        };
        let b = m.encode();
        assert_eq!(b.len(), Manifest::LEN);
        assert_eq!(Manifest::parse(&b, 0), Ok(m));
        let s = SegmentHeader {
            sealer_id: 0,
            segment_seq: 3,
            first_wal_seq: 99,
        };
        let b = s.encode();
        assert_eq!(b.len(), SegmentHeader::LEN);
        assert_eq!(SegmentHeader::parse(&b, 0), Ok(s));
        assert!(SegmentHeader::parse(&b, 1).is_err());
    }

    #[test]
    fn p2_format_secrets_round_trip_and_hold_one_scramble_key() {
        let s = Secrets {
            sealer_id: 0,
            entries: vec![(Secrets::K_SCRAMBLE, vec![9; 64])],
        };
        let p = Secrets::parse(&s.encode(), 0).unwrap();
        assert_eq!(p, s);
        assert_eq!(p.k_scramble().unwrap(), [9; 64]);
        assert!(!format!("{p:?}").contains('9'), "Debug is redacted");
        let two = Secrets {
            sealer_id: 0,
            entries: vec![(1, vec![1; 64]), (1, vec![2; 64])],
        };
        assert!(two.k_scramble().is_err());
        let short = Secrets {
            sealer_id: 0,
            entries: vec![(1, vec![1; 63])],
        };
        assert!(short.k_scramble().is_err());
    }

    #[test]
    #[spec("SR-14-2")]
    fn p2_format_every_single_bit_flip_in_a_manifest_is_detected() {
        let b = Manifest {
            sealer_id: 0,
            checkpoint_id: 1,
            first_wal_seq: 2,
        }
        .encode();
        for i in 0..b.len() * 8 {
            let mut f = b.clone();
            f[i / 8] ^= 1 << (i % 8);
            assert!(Manifest::parse(&f, 0).is_err(), "bit {i}");
        }
    }
}
